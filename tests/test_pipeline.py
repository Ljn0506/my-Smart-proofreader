"""测试完整校对流程。"""
from pathlib import Path

from proofreader.pipeline import Proofreader


def main():
    base = Path(__file__).parent.parent / "data" / "sample-docs"
    req_path = base / "requirements.docx"
    bid_path = base / "bid.docx"

    print("开始校对...")
    proofreader = Proofreader()
    result = proofreader.proofread(req_path, bid_path)

    print(f"\n提取到 {len(result.requirements)} 条需求：")
    for req in result.requirements:
        print(f"  [{req.item_id}] {req.text[:60]}...")

    print(f"\n投标文件拆分为 {len(result.bid_sections)} 个部分：")
    for sec in result.bid_sections:
        print(f"  [{sec.section_type.value}] {sec.title} ({len(sec.blocks)} 块)")

    print(f"\n一致性/偏离问题（{len(result.consistency_issues)} 个）：")
    for issue in result.consistency_issues:
        print(f"  [{issue.issue_type.value}] {issue.message}")
        print(f"    需求：{issue.requirement_text[:60]}")
        print(f"    投标：{issue.bid_text[:60] if issue.bid_text else '无'}")

    print(f"\n错别字问题（{len(result.typo_issues)} 个）：")
    for typo in result.typo_issues:
        print(f"  {typo.message}")

    print(f"\n截图 OCR 问题（{len(result.ocr_issues)} 个）：")
    for ocr in result.ocr_issues:
        print(f"  {ocr.message}")

    print(f"\n表格比对问题（{len(result.table_issues)} 个）：")
    for table in result.table_issues:
        print(f"  [{table.issue_id}] {table.message}")
        for detail in table.details[:5]:
            print(f"    - {detail}")


if __name__ == "__main__":
    main()
