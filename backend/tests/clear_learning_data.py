"""清空学习/测评数据，只保留资料与对话。

用途：前期的功能验证数据都是"随便做的"，不是真实学习记录，
     会影响进度页、掌握度、周报的可信度，需要清掉重来。

删除（8 张表）：
    quiz_answers      答题
    quiz_submissions  测评提交
    quiz_questions    题目
    quizzes           测评
    error_book        错题本
    knowledge_points  知识点（掌握度由答题算出，答题没了它们就成了僵尸数据）
    weekly_reports    周报（基于答题生成，留着会出现「周报 86 题 / 进度 0 题」的矛盾）
    learning_sessions 学习行为（连续学习天数）

保留（5 张表）：
    materials / material_chunks / material_notes / chat_sessions / chat_messages

用法：
    python tests/clear_learning_data.py            # 先打印将要删除的内容
    python tests/clear_learning_data.py --dry-run  # 只统计不删
    python tests/clear_learning_data.py --yes      # 实际执行
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from config import Config  # noqa: E402

DELETE = [
    "quiz_answers",
    "quiz_submissions",
    "quiz_questions",
    "quizzes",
    "error_book",
    "knowledge_points",
    "weekly_reports",
    "learning_sessions",
]

KEEP = [
    "materials",
    "material_chunks",
    "material_notes",
    "chat_sessions",
    "chat_messages",
]


def counts(conn, tables):
    return {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables}


def main():
    dry = "--dry-run" in sys.argv
    yes = "--yes" in sys.argv

    engine = create_engine(Config.DB_URL, future=True)
    with engine.begin() as conn:
        before_del = counts(conn, DELETE)
        before_keep = counts(conn, KEEP)

        print("即将删除：")
        for t in DELETE:
            print(f"  {t:20s} {before_del[t]:6d}")
        print("\n将保留：")
        for t in KEEP:
            print(f"  {t:20s} {before_keep[t]:6d}")

        if dry:
            print("\n[dry-run] 未做任何修改。")
            return

        if not yes:
            print("\n未执行。确认无误后加 --yes 再跑一次。")
            return

        total = 0
        for t in DELETE:
            n = conn.execute(text(f"DELETE FROM {t}")).rowcount
            total += n or 0
            print(f"  已删 {t:20s} {n:6d}")

        after_del = counts(conn, DELETE)
        after_keep = counts(conn, KEEP)

    print(f"\n共删除 {total} 行。")
    print("删除后校验：")
    bad = [t for t in DELETE if after_del[t] != 0]
    print("  待删表残留：", bad or "全部为 0 ✓")
    lost = [t for t in KEEP if after_keep[t] != before_keep[t]]
    if lost:
        print("  !! 保留表数量发生变化：", {t: (before_keep[t], after_keep[t]) for t in lost})
    else:
        print(f"  保留表未受影响 ✓（资料 {after_keep['materials']} 份 / "
              f"知识块 {after_keep['material_chunks']} / 对话 {after_keep['chat_sessions']} 会话）")


if __name__ == "__main__":
    main()
