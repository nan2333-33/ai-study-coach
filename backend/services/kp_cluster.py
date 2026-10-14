"""知识点语义聚类。

## 为什么需要

大模型每次出题给知识点起的名字略有出入，会以**不同 id** 落库。
于是进度页出现「同一个概念既是熟练又是薄弱」，知识点总数也被撑大——
45 个知识点里可能有 13 个是同一概念的重复写法。

按名称归一化只能处理「空格 + 大小写」差异，处理不了：
    Transformer的起源 / Transformer 的定义与起源 / Transformer 定义与起源
    RAG的三个步骤 / RAG 三个步骤
    position encoding / 位置编码 / 位置编码的作用

## 做法

1. 对知识点名字做 embedding
2. 贪心凝聚聚类：与某组质心的余弦相似度 ≥ 阈值就归进去，否则自开一组
3. 每组选**答题量最多**的那个名字作规范名（它也是大模型最常写出的写法）
4. 组内所有行的 `canonical_id` 指向规范知识点的 id

结果**写库**，不在每次请求时重算。

## 代价（必须知道）

这会**改变知识点命名与聚合结果**：掌握度是组内加权平均，合并后某个知识点的
掌握度会和合并前不一样，「薄弱数」也会下降（那是虚高的部分）。
所以要提供 dry-run 先看建议、以及 reset 回滚。
"""

import logging
import math
import re

logger = logging.getLogger(__name__)

# 相似度阈值。0.84 是按本项目真实数据（49 个不同名字）调出来的，依据见
# tests/test_kp_cluster.py 的诊断输出：
#   0.78→25 组   0.82→26   0.84→29   0.86→32   0.88→34   0.92→35
#
# 选 0.84 的理由是**两类错误的代价不对称**：
#   · 合并不足 → 列表里还留着几条重复，只是「看起来多」，不影响掌握度判断
#   · 过度合并 → 两个不同知识点被当成一个，掌握度一平均，
#                就把「你其实不会」的那部分盖掉了 —— 学习产品最坏的错误
# 所以宁可保守。0.84 能收掉所有明显的同义改写（Transformer 的 4 种写法、
# 传统AI模型痛点的 4 种写法、RAG的三个步骤/RAG 三个步骤……），
# 但不会把 0.78~0.80 那些确实不同的概念并到一起。
#
# 已知未覆盖：自我介绍技巧 ⟷ 自我介绍埋钩子技巧 = 0.823，低于 0.84 不合。
# 想合并就把阈值调到 0.82（POST /api/progress/knowledge/merge?threshold=0.82）。
DEFAULT_THRESHOLD = 0.84


def _norm_name(name):
    """便宜的归一化：去空白 + 转小写。先把完全同名的合掉，减少 embedding 调用。"""
    return re.sub(r"\s+", "", (name or "")).lower()


def _cos(a, b):
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def cluster_names(names, vectors, threshold=DEFAULT_THRESHOLD):
    """把名字按 embedding 聚成组：凝聚式层次聚类（average linkage）。

    为什么不用「逐个跟已有质心比、够像就归进去」的贪心单遍：
    它只看当前点与质心的相似度，处理不了链式传递。实测
    「Transformer的起源」与「Transformer 定义与起源」是 0.840（差一点点没过阈值），
    但两者都跟「Transformer 的定义与起源」> 0.9 —— 贪心会把它拆成两组，
    average linkage 会正确并成一组。

    做法：先算全量相似度矩阵，然后每轮把**平均相似度最高**的两组合并，
    直到最高的那对也低于阈值。

    Args:
        names: 名字列表
        vectors: 与 names 一一对应的向量
        threshold: 相似度阈值

    Returns:
        (groups, merges)
        groups:  [[下标, ...], ...]，按下标升序
        merges:  [(名字A, 名字B, 相似度)]，合并日志，调阈值时看这个
    """
    n = len(names)
    if n == 0:
        return [], []
    if n == 1:
        return [[0]], []

    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            s = _cos(vectors[i], vectors[j])
            sim[i][j] = s
            sim[j][i] = s

    clusters = [[i] for i in range(n)]
    merges = []

    while len(clusters) > 1:
        best_s, best_a, best_b = -1.0, -1, -1
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                total = 0.0
                for i in clusters[a]:
                    for j in clusters[b]:
                        total += sim[i][j]
                avg = total / (len(clusters[a]) * len(clusters[b]))
                # 用 > 而不是 >=，保证同分时取靠前的一对，结果可复现
                if avg > best_s:
                    best_s, best_a, best_b = avg, a, b

        if best_s < threshold:
            break

        merges.append(
            (names[clusters[best_a][0]], names[clusters[best_b][0]], round(best_s, 3))
        )
        clusters[best_a] = clusters[best_a] + clusters[best_b]
        clusters.pop(best_b)

    for c in clusters:
        c.sort()
    clusters.sort(key=lambda c: c[0])
    return clusters, merges


def merge_knowledge_points(session, threshold=DEFAULT_THRESHOLD, embed_fn=None, dry_run=False):
    """把语义相近的知识点合并，把 canonical_id 写回库。

    **不提交事务**，由调用方 commit（方便 dry_run 与真实执行走同一条路径）。

    Args:
        dry_run: True 时只算不写，用来看建议 / 调阈值
        embed_fn: 注入用，默认走真实 embedding 客户端

    Returns:
        {
          "total": 知识点行数,
          "groups": 聚类后的组数,
          "merged": 被合并掉的行数（total - groups）,
          "threshold": 使用的阈值,
          "clusters": [{"canonical": 规范名, "members": [{"name", "questionCount"}...]}]
        }
    """
    from sqlalchemy import func

    from models.knowledge import KnowledgePoint
    from models.quiz import QuizAnswer, QuizQuestion
    from services.clients import embedding_client

    if embed_fn is None:
        embed_fn = embedding_client.embed

    kps = session.query(KnowledgePoint).all()
    if not kps:
        return {"total": 0, "groups": 0, "merged": 0, "threshold": threshold, "clusters": []}

    # 每个知识点的答题量，用来选规范名（答得最多的写法 = 大模型最常写出的写法）
    cnt_rows = (
        session.query(QuizQuestion.knowledge_point_id, func.count(QuizAnswer.id))
        .join(QuizAnswer, QuizAnswer.question_id == QuizQuestion.id)
        .group_by(QuizQuestion.knowledge_point_id)
        .all()
    )
    qc = {r[0]: int(r[1] or 0) for r in cnt_rows}

    # 第一步：完全同名的先并成桶，减少 embedding 调用量
    buckets = {}
    for kp in kps:
        buckets.setdefault(_norm_name(kp.name), []).append(kp)

    # 每个桶取一个代表名（答得最多的那条）去算向量
    bucket_keys = list(buckets.keys())
    rep_names = []
    for key in bucket_keys:
        members = buckets[key]
        best = max(members, key=lambda k: (qc.get(k.id, 0), -len(k.name or "")))
        rep_names.append(best.name or key)

    vectors = embed_fn(rep_names)
    groups, _sims = cluster_names(rep_names, vectors, threshold=threshold)

    clusters_out = []
    merged_rows = 0
    for idxs in groups:
        all_kps = []
        for i in idxs:
            all_kps.extend(buckets[bucket_keys[i]])
        # 规范名：组内答题量最多的那条；平局时取名字更短的（更可能是通用写法）
        canonical = max(all_kps, key=lambda k: (qc.get(k.id, 0), -len(k.name or "")))

        if not dry_run:
            for kp in all_kps:
                kp.canonical_id = canonical.id

        merged_rows += len(all_kps) - 1
        clusters_out.append(
            {
                "canonical": canonical.name,
                "canonicalId": canonical.id,
                "members": [
                    {"name": k.name, "questionCount": qc.get(k.id, 0)}
                    for k in sorted(all_kps, key=lambda k: -qc.get(k.id, 0))
                ],
            }
        )

    clusters_out.sort(key=lambda c: -sum(m["questionCount"] for m in c["members"]))

    return {
        "total": len(kps),
        "groups": len(clusters_out),
        "merged": merged_rows,
        "threshold": threshold,
        "clusters": clusters_out,
    }


def reset_canonical(session):
    """清空聚类结果（回滚到「按名称归一化」的旧行为）。**不提交事务。**"""
    from models.knowledge import KnowledgePoint

    n = session.query(KnowledgePoint).update({KnowledgePoint.canonical_id: None})
    return int(n or 0)
