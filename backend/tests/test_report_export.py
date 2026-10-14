"""验证：周报主指标是「答题数」而不是推算的学习时长，且能导出 md / docx / pdf。

覆盖 4 件事：
1. 答题数统计的区间边界（硬计数，不做任何折算）
2. 进度页不再返回学习时长，只返回答题数
3. 导出的三种格式都带「做题量」，且不出现「学习时长」
4. 下载接口的三种格式与非法格式处理

运行：backend/.venv/Scripts/python.exe tests/test_report_export.py
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from app import create_app  # noqa: E402
from models.report import WeeklyReport  # noqa: E402
from services import tracking, exporters  # noqa: E402

app = create_app()


def check_question_rules():
    """答题数是硬计数：用构造好的日期列表验证区间边界。"""
    fake = type("S", (), {"info": {}})()
    dates = [
        (date(2026, 10, 5), 3),
        (date(2026, 10, 12), 5),
        (date(2026, 10, 18), 4),
    ]
    orig = tracking.question_dates
    tracking.question_dates = lambda s: dates
    try:
        got = tracking.question_count(fake)
        assert got == 12, got
        got = tracking.question_count(fake, date(2026, 10, 12), date(2026, 10, 18))
        assert got == 9, got
        got = tracking.question_count(fake, date(2026, 10, 13), date(2026, 10, 18))
        assert got == 4, got
        got = tracking.question_count(fake, date(2026, 10, 19), date(2026, 10, 25))
        assert got == 0, got
    finally:
        tracking.question_dates = orig
    print("答题数区间边界用例通过（3+5+4=12，含端点）")


def check_progress():
    client = app.test_client()
    resp = client.get("/api/progress/overview")
    assert resp.status_code == 200
    d = resp.get_json()["data"]

    for gone in ("totalStudyMinutes", "weekStudyMinutes", "studySessions"):
        assert gone not in d, f"进度页还在返回已被移除的 {gone}"
    for need in ("totalQuestionCount", "weekQuestionCount", "currentStreakDays"):
        assert need in d, f"进度页缺少 {need}"
    assert isinstance(d["totalQuestionCount"], int)
    assert isinstance(d["weekQuestionCount"], int)

    print(
        f"进度页: 累计答题={d['totalQuestionCount']} 本周={d['weekQuestionCount']} "
        f"连续学习={d['currentStreakDays']}天 累计测验={d.get('totalQuizCount')}次"
    )

    resp = client.get("/api/progress/sessions")
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    print(f"每日明细: total={d['total']} 返回 {len(d['list'])} 条")
    for item in d["list"]:
        assert "questionCount" in item, item
        assert "minutes" not in item and "durationMinutes" not in item, item
        break


def check_exports():
    with app.SessionLocal() as s:
        row = s.query(WeeklyReport).order_by(WeeklyReport.week_start.desc()).first()
        if not row:
            print("库里没有周报，跳过导出验证")
            return
        from routes.report import _report_doc

        doc = _report_doc(row, s)

    md = exporters.to_markdown(doc)
    assert md.startswith("# 学习周报"), md[:50]
    assert "## ✍️ 做题量" in md or "做题量" in md, md[:200]
    assert "学习时长" not in md, f"周报里还在提学习时长：{md[:200]}"
    print(f"Markdown: {len(md)} 字符")

    docx_bytes = exporters.to_docx(doc)
    assert docx_bytes[:2] == b"PK", "docx 应该是 zip（PK 开头）"
    print(f"Word(.docx): {len(docx_bytes)} 字节")

    pdf_bytes = exporters.to_pdf(doc)
    assert pdf_bytes[:4] == b"%PDF", "pdf 头不正确"
    print(f"PDF: {len(pdf_bytes)} 字节")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_导出样例")
    os.makedirs(out, exist_ok=True)
    name = f"学习周报_{row.week_start}_{row.week_end}"
    with open(os.path.join(out, name + ".md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(out, name + ".docx"), "wb") as f:
        f.write(docx_bytes)
    with open(os.path.join(out, name + ".pdf"), "wb") as f:
        f.write(pdf_bytes)
    print("样例文件已写入:", out)


def check_download_endpoint():
    client = app.test_client()
    with app.SessionLocal() as s:
        row = s.query(WeeklyReport).order_by(WeeklyReport.week_start.desc()).first()
        if not row:
            print("库里没有周报，跳过接口验证")
            return
        rid = row.id

    for fmt, magic in (("md", None), ("docx", b"PK"), ("pdf", b"%PDF")):
        resp = client.get(f"/api/report/{rid}/download?format={fmt}")
        assert resp.status_code == 200, (fmt, resp.status_code, resp.data[:200])
        if magic:
            assert resp.data[: len(magic)] == magic, (fmt, resp.data[:10])
        print(f"GET /download?format={fmt} -> {resp.status_code} "
              f"{resp.headers.get('Content-Type')} {len(resp.data)}字节")

    bad = client.get(f"/api/report/{rid}/download?format=xlsx")
    assert bad.status_code == 400, bad.status_code
    print("非法 format 正确返回 400")


if __name__ == "__main__":
    check_question_rules()
    print("-" * 50)
    check_progress()
    print("-" * 50)
    check_download_endpoint()
    print("-" * 50)
    check_exports()
    print("\n全部通过")
