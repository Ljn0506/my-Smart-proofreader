"""验证模拟文档的期望问题是否都被检出。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from proofreader.pipeline import Proofreader


def main():
    base = Path(__file__).parent.parent / "data" / "sample-docs"
    result = Proofreader().proofread(base / "requirements.docx", base / "bid.docx")

    print("=== 验证报告 ===\n")

    checks = [
        ("备份周期不一致", lambda: any("7.0天" in i.message and "5.0天" in i.message for i in result.consistency_issues)),
        ("质保期不一致", lambda: any("3.0年" in i.message and "2.0年" in i.message for i in result.consistency_issues)),
        ("项目经理年限不一致", lambda: any("5.0年" in i.message and "4.0年" in i.message for i in result.consistency_issues)),
        ("7×24 技术支持偏离", lambda: any("7×24" in i.message for i in result.consistency_issues)),
        ("交付周期不一致", lambda: any("6.0个月" in i.message and "8.0个月" in i.message for i in result.consistency_issues)),
        ("培训次数/人数不一致", lambda: any(
            "3.0次" in i.message and "2.0次" in i.message and "20.0人" in i.message and "15.0人" in i.message
            for i in result.consistency_issues
        )),
        ("错别字「架购」", lambda: any(typo.word == "架购" for typo in result.typo_issues)),
        ("截图 OCR 检查", lambda: len(result.ocr_issues) >= 1),
    ]

    all_pass = True
    for name, check in checks:
        ok = check()
        status = "✅ 通过" if ok else "❌ 未通过"
        print(f"{status}：{name}")
        if not ok:
            all_pass = False

    print(f"\n总计问题：{len(result.consistency_issues)} 处一致性/偏离，"
          f"{len(result.typo_issues)} 处错别字，{len(result.ocr_issues)} 处截图")
    print("\n验证全部通过" if all_pass else "\n存在未通过的验证项")


if __name__ == "__main__":
    main()
