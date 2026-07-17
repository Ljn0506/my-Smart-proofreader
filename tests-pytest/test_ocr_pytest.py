"""pytest 风格的 OCR 引擎测试。"""
from __future__ import annotations

from pathlib import Path

from proofreader.checkers.ocr_checker import (
    OcrEngine,
    OcrIssue,
    _check_ocr_quantity_mismatches,
    _extract_required_entities,
    _extract_relevant_keywords,
    check_images,
)
from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.parsers.docx_parser import EmbeddedImage, ParsedDocument, TextBlock


def test_ocr_caches_result_by_image_hash() -> None:
    """对同一张图片多次识别应直接返回缓存结果。"""
    base = Path(__file__).parent.parent / "data" / "sample-docs"
    image_blob = (base / "sample_screenshot.png").read_bytes()

    engine = OcrEngine()

    # 第一次识别
    text1 = engine.recognize(image_blob)
    assert text1 != ""
    assert len(engine._result_cache) == 1

    # 第二次识别同一图片，应返回缓存结果
    text2 = engine.recognize(image_blob)
    assert text2 == text1
    assert len(engine._result_cache) == 1


def test_ocr_cache_respects_max_size() -> None:
    """缓存达到上限时应按 LRU 淘汰旧项。"""
    engine = OcrEngine(result_cache_size=2)

    engine._cache_result("a", "text-a")
    engine._cache_result("b", "text-b")
    engine._cache_result("c", "text-c")

    assert "a" not in engine._result_cache
    assert "b" in engine._result_cache
    assert "c" in engine._result_cache


def test_ocr_cache_lru_update_on_hit() -> None:
    """访问缓存项时应更新其 LRU 顺序。"""
    engine = OcrEngine(result_cache_size=2)

    engine._cache_result("a", "text-a")
    engine._cache_result("b", "text-b")

    # 访问 a，使其变为最近使用
    _ = engine._result_cache["a"]
    engine._result_cache_keys.remove("a")
    engine._result_cache_keys.append("a")

    # 加入 c，应淘汰 b
    engine._cache_result("c", "text-c")
    assert "a" in engine._result_cache
    assert "b" not in engine._result_cache
    assert "c" in engine._result_cache


# ---------------------------------------------------------------------------
# 关键词提取与 check_images 行为测试
# ---------------------------------------------------------------------------


def test_extract_relevant_keywords_prefers_constraints_and_numbers() -> None:
    """关键词提取应优先包含约束词、数字+单位，并过滤泛化虚词。"""
    reqs = [
        RequirementItem(
            item_id="R1",
            text="系统必须支持 1000 并发用户同时在线访问，可用性需达到 99.9%。",
            constraint_keywords=["必须", "达到"],
        ),
        RequirementItem(
            item_id="R2",
            text="培训次数不少于 3 次，每次不少于 20 人。",
            constraint_keywords=["不少于"],
        ),
    ]
    keywords = _extract_relevant_keywords(reqs)

    # 应包含数字+单位
    assert any("1000" in kw and "用户" in kw for kw in keywords), "应提取 1000并发用户/1000用户类关键词"
    assert any("99.9%" in kw for kw in keywords), "应提取 99.9%"
    assert any("3次" in kw for kw in keywords), "应提取 3次"
    assert any("20人" in kw for kw in keywords), "应提取 20人"

    # 应过滤泛化虚词
    assert "投标" not in keywords
    assert "文件" not in keywords
    assert "需求" not in keywords
    assert "技术" not in keywords
    assert "服务" not in keywords


def test_extract_relevant_keywords_ignores_short_stopwords() -> None:
    """过短词与停用词不应作为 OCR 检查目标。"""
    reqs = [RequirementItem(item_id="R1", text="的 了 在 是", constraint_keywords=[])]
    keywords = _extract_relevant_keywords(reqs)
    assert keywords == set()


class _FakeOcrEngine:
    """不加载 easyocr 模型的假 OCR 引擎。"""

    def __init__(self, text: str) -> None:
        self.text = text

    def recognize(self, blob: bytes) -> str:
        return self.text


def _make_doc_with_image(
    block_text: str = "系统截图说明",
    block_section_title: str = "",
) -> ParsedDocument:
    """构造一个只含一张图片的 ParsedDocument。"""
    doc = ParsedDocument(path=Path("bid.docx"))
    block = TextBlock(
        text=block_text,
        block_type="paragraph",
        index=0,
        section_title=block_section_title,
    )
    doc.blocks.append(block)
    # 用一段任意非空 bytes 作为图片 blob；FakeOcrEngine 不解析 blob
    blob = b"fake-image-bytes"
    doc.images.append(EmbeddedImage(image_index=0, ext="png", blob=blob, block_index=0))
    return doc


def test_check_images_reports_low_coverage(tmp_path: Path) -> None:
    """存在参数偏离且覆盖率低于阈值时，消息中应包含覆盖率提示。"""
    req_text = "投标方须提供 ISO9001 质量管理体系认证证书，系统必须支持 1000 并发用户同时在线访问。"
    reqs = [
        RequirementItem(
            item_id="R1",
            text=req_text,
        )
    ]
    doc = _make_doc_with_image(block_text=req_text)
    engine = _FakeOcrEngine("支持 800 并发用户")

    issues = check_images(doc, reqs, engine, tmp_path, coverage_threshold=0.9)

    assert len(issues) == 1
    issue = issues[0]
    assert isinstance(issue, OcrIssue)
    assert issue.image_path.exists(), "生成 issue 时应将图片写入磁盘"
    assert "覆盖率" in issue.message
    assert any("1000" in m and "800" in m for m in issue.parameter_mismatches)


def test_check_images_skips_high_coverage(tmp_path: Path) -> None:
    """覆盖率高于阈值且没有其他问题时，不应生成 issue，且默认不写盘。"""
    req_text = "系统必须支持 1000 并发用户同时在线访问。"
    reqs = [
        RequirementItem(
            item_id="R1",
            text=req_text,
            constraint_keywords=["必须"],
        )
    ]
    doc = _make_doc_with_image(block_text=req_text)
    # OCR 文本包含几乎所有关键词，使覆盖率高，且无参数/证书问题
    engine = _FakeOcrEngine("系统必须支持1000并发用户同时在线访问")

    issues = check_images(doc, reqs, engine, tmp_path, coverage_threshold=0.3)

    assert len(issues) == 0
    assert not any(tmp_path.iterdir()), "未生成 issue 时默认不应写盘"


def test_check_images_debug_mode_writes_images(tmp_path: Path) -> None:
    """debug=True 时即使未生成 issue 也应将图片落盘。"""
    req_text = "系统必须支持 1000 并发用户同时在线访问。"
    reqs = [
        RequirementItem(
            item_id="R1",
            text=req_text,
            constraint_keywords=["必须"],
        )
    ]
    doc = _make_doc_with_image(block_text=req_text)
    engine_covered = _FakeOcrEngine("系统必须支持1000并发用户同时在线访问")
    issues = check_images(doc, reqs, engine_covered, tmp_path, coverage_threshold=0.3, debug=True)

    assert len(issues) == 0
    assert any(tmp_path.iterdir()), "debug=True 时未生成 issue 也应写盘"


def test_check_images_coverage_threshold_parameter(tmp_path: Path) -> None:
    """coverage_threshold 参数应能控制覆盖率提示是否出现。"""
    req_text = "投标方须提供 ISO9001 质量管理体系认证证书，系统必须支持 1000 并发用户同时在线访问。"
    reqs = [
        RequirementItem(
            item_id="R1",
            text=req_text,
        )
    ]
    doc = _make_doc_with_image(block_text=req_text)
    # 命中部分关键词，但缺失 ISO9001，会触发证书 issue
    engine = _FakeOcrEngine("系统必须支持")

    # 阈值极低时覆盖率视为通过，不出现覆盖率提示
    issues_low = check_images(doc, reqs, engine, tmp_path, coverage_threshold=0.0)
    # 阈值高时覆盖率不通过，出现覆盖率提示
    issues_high = check_images(doc, reqs, engine, tmp_path / "high", coverage_threshold=0.9)

    assert len(issues_low) == 1
    assert len(issues_high) == 1
    assert "覆盖率" not in issues_low[0].message
    assert "覆盖率" in issues_high[0].message


def test_extract_required_entities_finds_certificates_and_reports() -> None:
    """应能从需求中提取要求的证书、报告、资质等实体。"""
    reqs = [
        RequirementItem(item_id="R1", text="投标方须提供 ISO9001 质量管理体系认证证书。"),
        RequirementItem(item_id="R2", text="须提供第三方检测机构出具的检测报告。"),
        RequirementItem(item_id="R3", text="项目经理具备 PMP 证书。"),
        RequirementItem(item_id="R4", text="须提供 CMA 资质认定和等保测评报告。"),
        RequirementItem(item_id="R5", text="产品需取得商用密码产品认证证书。"),
        RequirementItem(item_id="R6", text="须提供信创适配证明或兼容性列表。"),
        RequirementItem(item_id="R7", text="须提供公安部检测报告及销售许可证。"),
        RequirementItem(item_id="R8", text="拥有软件著作权/专利证书。"),
        RequirementItem(item_id="R9", text="取得 IT产品信息安全认证证书。"),
    ]
    entities = _extract_required_entities(reqs)
    assert "ISO9001" in entities
    assert "检测报告" in entities
    assert "PMP" in entities
    assert "CMA" in entities
    assert "等保测评报告" in entities
    assert "商用密码产品认证证书" in entities
    assert "信创适配证明" in entities
    assert "兼容性列表" in entities
    assert "公安部检测报告" in entities
    assert "销售许可证" in entities
    assert "软件著作权" in entities
    assert "专利证书" in entities
    assert "IT产品信息安全认证证书" in entities


def test_check_ocr_quantity_mismatches_detects_lower_value() -> None:
    """OCR 文字中的数值低于需求时应报偏离。"""
    mismatches = _check_ocr_quantity_mismatches(
        "系统必须支持 1000 并发用户同时在线访问。",
        "经测试，系统可支持 800 并发用户",
    )
    assert len(mismatches) == 1
    assert "1000" in mismatches[0]
    assert "800" in mismatches[0]


def test_check_ocr_quantity_mismatches_respects_le_direction() -> None:
    """需求含『不超过』时，OCR 文字中数值过高应报偏离。"""
    mismatches = _check_ocr_quantity_mismatches(
        "核心功能响应时间不得超过 2 秒。",
        "响应时间为 3 秒",
    )
    assert len(mismatches) == 1
    assert "2" in mismatches[0]
    assert "3" in mismatches[0]


def test_check_images_detects_missing_certificate(tmp_path: Path) -> None:
    """需求要求某证书/报告，但图片 OCR 文字中未出现时应生成 issue。"""
    req_text = "投标方须提供 ISO9001 质量管理体系认证证书。"
    reqs = [
        RequirementItem(
            item_id="R1",
            text=req_text,
        )
    ]
    doc = _make_doc_with_image(block_text=req_text)
    engine = _FakeOcrEngine("这是一张普通系统截图，没有任何证书")

    issues = check_images(doc, reqs, engine, tmp_path, coverage_threshold=1.0)

    assert len(issues) == 1
    assert "ISO9001" in issues[0].missing_entities
    assert "证书" in issues[0].message or "报告" in issues[0].message


def test_check_images_detects_parameter_mismatch_in_screenshot(tmp_path: Path) -> None:
    """截图中的参数不满足需求时应生成 issue。"""
    reqs = [
        RequirementItem(
            item_id="R1",
            text="系统必须支持 1000 并发用户同时在线访问。",
        )
    ]
    doc = _make_doc_with_image()
    engine = _FakeOcrEngine("经测试，系统可支持 800 并发用户")

    issues = check_images(doc, reqs, engine, tmp_path, coverage_threshold=1.0)

    assert len(issues) == 1
    assert len(issues[0].parameter_mismatches) > 0
    assert any("1000" in m and "800" in m for m in issues[0].parameter_mismatches)
