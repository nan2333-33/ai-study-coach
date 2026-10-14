"""知识点语义聚类 —— 阈值诊断脚本（会真实调用 embedding API，不写库）。

用途：聚类阈值不能拍脑袋定。这个脚本把库里所有知识点名字拿去做 embedding，
然后在几个候选阈值下跑聚类，打印「哪些被合并了」，用来选阈值。

运行（需先配好 .env 的 EMB_API_KEY）：
    .venv/Scripts/python.exe tests/test_kp_cluster.py

它只打印，不写库、不改数据。真正写库走：
    POST /api/progress/knowledge/merge
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import Config
from models.knowledge import KnowledgePoint, ensure_canonical_id_column
from services.clients import embedding_client
from services.kp_cluster import DEFAULT_THRESHOLD, _cos, _norm_name, cluster_names


def _prepare(names):
    """和线上 merge_knowledge_points 完全一致：先按归一化名并桶，再用代表名聚类。

    不这么做的话，脚本算出的组数和接口返回的会对不上。
    """
    buckets = {}
    for i, n in enumerate(names):
        buckets.setdefault(_norm_name(n), []).append(i)
    reps = [idxs[0] for idxs in buckets.values()]
    return reps, list(buckets.values())


def _group_all(names, vectors, threshold):
    """返回完整分组（含同名桶展开后的全部下标）。"""
    reps, buckets = _prepare(names)
    g, _ = cluster_names([names[i] for i in reps], [vectors[i] for i in reps], threshold)
    return [[i for ri in grp for i in buckets[ri]] for grp in g]


def main():
    engine = create_engine(Config.DB_URL, future=True)
    ensure_canonical_id_column(engine)
    Session = sessionmaker(bind=engine, future=True)

    with Session() as s:
        kps = s.query(KnowledgePoint).all()

    if not kps:
        print("库里没有知识点，先做一次测评再来。")
        return 1

    names = [k.name for k in kps]
    print(f"知识点表共 {len(names)} 行，开始 embedding…\n")

    vectors = embedding_client.embed(names)
    reps, buckets = _prepare(names)
    dup_rows = len(names) - len(reps)
    print(f"embedding 完成，维度 {len(vectors[0])}")
    print(f"其中同名重复行 {dup_rows} 行（归一化后即合并，不占阈值判断）")
    print(f"参与语义聚类的是 {len(reps)} 个不同的名字\n")

    # ---------- 1. 各阈值下的聚类规模 ----------
    print("=" * 68)
    print("一、不同阈值 → 聚类结果")
    print("=" * 68)
    print(f"{'阈值':<8}{'组数':<8}{'比原来少':<8}")
    for th in (0.78, 0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92):
        groups = _group_all(names, vectors, th)
        print(f"{th:<8}{len(groups):<8}{len(names) - len(groups):<8}")

    # ---------- 2. 边界附近的相似度对 ----------
    print()
    print("=" * 68)
    print("二、相似度落在 0.78~0.94 的「难判断」对（决定阈值的关键证据）")
    print("=" * 68)
    pairs = []
    for i in range(len(reps)):
        for j in range(i + 1, len(reps)):
            sim = _cos(vectors[reps[i]], vectors[reps[j]])
            if 0.78 <= sim <= 0.94:
                pairs.append((sim, names[reps[i]], names[reps[j]]))
    pairs.sort(reverse=True)
    if not pairs:
        print("（没有落在区间的对 —— 说明这批数据聚类边界很干净）")
    for sim, a, b in pairs[:40]:
        print(f"  {sim:.3f}   {a}   ⟷   {b}")
    print(f"\n  共 {len(pairs)} 对（最多显示 40）")

    # ---------- 3. 默认阈值的实际合并清单 ----------
    print()
    print("=" * 68)
    print(f"三、默认阈值 {DEFAULT_THRESHOLD} 下实际会被合并的组（只列有合并发生的）")
    print("=" * 68)
    groups = _group_all(names, vectors, DEFAULT_THRESHOLD)
    hits = [g for g in groups if len(g) > 1]
    if not hits:
        print("  没有发生合并 —— 阈值偏高，考虑下调")
    for g in hits:
        members = [names[i] for i in g]
        print(f"  ← {members[0]}")
        for m in members[1:]:
            print(f"     + {m}")
    print(f"\n被合并的组：{len(hits)}，共 {len(names)} → {len(groups)}")

    print("\n（本脚本只读不写。确认后调用 POST /api/progress/knowledge/merge 才会写库）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
