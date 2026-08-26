"""对投标文件中的截图进行 OCR，并检查是否覆盖需求关键词、证书/报告及参数一致性。"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Set, Tuple

import numpy as np
from PIL import Image

from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument, TextBlock

logger = logging.getLogger(__name__)


# 单张图片安全上限：20 MB / 2000 万像素；超过则跳过，避免 OCR 耗尽内存
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_IMAGE_PIXELS = 20_000_000


def _image_size_ok(blob: bytes) -> bool:
    """粗略检查图片尺寸与字节数，拒绝超大图/解压炸弹。"""
    if len(blob) > _MAX_IMAGE_BYTES:
        return False
    try:
        with Image.open(io.BytesIO(blob)) as im:
            if im.width * im.height > _MAX_IMAGE_PIXELS:
                return False
    except Exception:
        # 无法识别的图片格式直接放行，后续 OCR 会失败
        pass
    return True


def _safe_image_ext(ext: str | None) -> str:
    """从 content-type 或外部输入得到的扩展名可能包含路径遍历字符，归一化为安全后缀。"""
    if not ext:
        return "png"
    safe = re.sub(r"[^a-zA-Z0-9]", "", ext.split(";")[0])
    return safe or "png"


@dataclass
class OcrIssue:
    """OCR 检查发现的问题。"""

    image_index: int
    image_path: Path
    missing_keywords: List[str] = field(default_factory=list)
    missing_entities: List[str] = field(default_factory=list)
    parameter_mismatches: List[str] = field(default_factory=list)
    message: str = ""
    context_block: TextBlock | None = None


class OcrEngine:
    """
    OCR 引擎封装。
    - 按 (language_list, gpu) 缓存 easyocr.Reader，避免重复加载模型。
    - 按图片内容 hash 缓存 OCR 结果，避免对同一张图片重复识别。
    """

    _reader_cache: ClassVar[Dict[tuple[tuple[str, ...], bool], object]] = {}

    def __init__(
        self,
        use_gpu: bool = False,
        languages: List[str] | None = None,
        result_cache_size: int = 256,
    ):
        self.use_gpu = use_gpu
        self.languages = tuple(languages or ["ch_sim", "en"])
        self._reader: Optional[object] = None
        self._result_cache: Dict[str, str] = {}
        self._result_cache_size = max(1, result_cache_size)
        self._result_cache_keys: List[str] = []

    @property
    def available(self) -> bool:
        """检查 OCR 引擎是否可用（依赖的库和模型能否正常加载）。"""
        try:
            self._get_reader()
            return True
        except Exception as exc:
            logger.warning("OCR 引擎不可用：%s", exc)
            return False

    def _get_reader(self):
        if self._reader is None:
            cache_key = (self.languages, self.use_gpu)
            reader = self._reader_cache.get(cache_key)
            if reader is None:
                import easyocr

                reader = easyocr.Reader(list(self.languages), gpu=self.use_gpu)
                self._reader_cache[cache_key] = reader
            self._reader = reader
        return self._reader

    def _cache_result(self, image_hash: str, text: str) -> None:
        """将 OCR 结果加入 LRU 缓存。"""
        if image_hash in self._result_cache:
            self._result_cache_keys.remove(image_hash)
        elif len(self._result_cache_keys) >= self._result_cache_size:
            oldest = self._result_cache_keys.pop(0)
            self._result_cache.pop(oldest, None)
        self._result_cache[image_hash] = text
        self._result_cache_keys.append(image_hash)

    def recognize(self, image_blob: bytes) -> str:
        """识别图片中的文字，优先使用内容 hash 缓存。"""
        image_hash = hashlib.sha256(image_blob).hexdigest()
        cached = self._result_cache.get(image_hash)
        if cached is not None:
            return cached

        try:
            image: Image.Image = Image.open(io.BytesIO(image_blob))
            if image.mode != "RGB":
                image = image.convert("RGB")
            array = np.asarray(image)
            result = self._get_reader().readtext(array, detail=0)
            text = "\n".join(result)
            self._cache_result(image_hash, text)
            return text
        except Exception as exc:
            logger.warning("OCR 识别失败：%s", exc)
            return ""


# ---------------------------------------------------------------------------
# 关键词提取
# ---------------------------------------------------------------------------


def _extract_relevant_keywords(
    requirements: List[RequirementItem],
    max_keywords: int = 30,
) -> Set[str]:
    """
    从需求条目中提取与 OCR 检查相关的关键词/核心实体。

    提取策略：
    1. 需求条目中已识别出的约束关键词（constraint_keywords）作为锚点；
    2. 数字+单位组合（如 1000并发用户、99.9%、3次）；
    3. 强约束词（必须、应、需要、要求等）附近的名词/动名词；
    4. 过滤泛化虚词与过短词，按权重排序后截断。
    """
    from collections import Counter

    import jieba.posseg as pseg

    keywords: Counter[str] = Counter()

    # 强约束词，用于定位关键语义区域
    strong_constraints = ["必须", "应", "须", "不得", "禁止", "应当", "需要", "要求"]

    # 数字+单位正则（与 consistency_checker 保持相近的覆盖范围，并允许常见修饰前缀）
    number_unit_pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:并发|在线|同时|核心|可用性|成功率|内存|存储|容量|带宽|延迟|响应|吞吐|支持|达到)?\s*"
        r"(核|核数|CPU|GB|G|TB|T|MB|M|年|月|日|天|小时|分钟|秒|ms|s|人|用户|个|%|百分之|万元|元|次|QPS|TPS|套)",
        re.IGNORECASE,
    )

    # 泛化虚词与常见停用词
    stop_words = {
        "必须", "应当", "需要", "要求", "提供", "具备", "支持", "实现",
        "投标", "文件", "需求", "技术", "服务", "项目", "合同", "工作",
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
        "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
        "没有", "看", "好", "自己", "这", "那",
    }

    for req in requirements:
        text = req.text

        # 1) 约束关键词作为锚点：提升权重，但本身如果是停用词则会被后续过滤
        for kw in req.constraint_keywords:
            normalized = kw.strip()
            if len(normalized) >= 2:
                keywords[normalized] += 5

        # 2) 数字+单位组合
        for match in number_unit_pattern.finditer(text):
            expr = re.sub(r"\s+", "", match.group(0))
            if len(expr) >= 2:
                keywords[expr] += 4

        # 3) 强约束词附近的名词/动名词
        for kw in strong_constraints:
            start = 0
            while True:
                idx = text.find(kw, start)
                if idx < 0:
                    break
                # 取约束词后最多 10 个字符的窗口
                window = text[idx + len(kw):idx + len(kw) + 10]
                for word in pseg.cut(window):
                    w = word.word.strip()
                    if word.flag.startswith(("n", "v")) and len(w) >= 2 and w not in stop_words:
                        keywords[w] += 2
                start = idx + 1

    filtered = [(w, c) for w, c in keywords.items() if w not in stop_words and len(w) >= 2]
    filtered.sort(key=lambda x: x[1], reverse=True)
    return set(w for w, _ in filtered[:max_keywords])


# ---------------------------------------------------------------------------
# 证书/报告与参数偏离检测
# ---------------------------------------------------------------------------


# 常见证书、报告、资质类关键词
_REPORT_CERTIFICATE_KEYWORDS = [
    # 通用报告
    "检测报告", "测试报告", "检验报告", "验收报告", "评测报告",
    # 项目管理/人员资质
    "PMP证书", "PMP", "项目经理证书",
    # ISO 体系
    "ISO9001", "ISO 9001", "ISO27001", "ISO 27001", "ISO20000", "ISO 20000",
    "ISO14001", "ISO 14001", "ISO45001", "ISO 45001",
    # 行业资质
    "CMMI", "ITSS", "CCRC", "等保", "等级保护", "CMA",
    # 营业执照/授权/资质
    "营业执照", "资质证书", "授权书", "代理授权", "原厂授权",
    "合格证", "产品合格证", "认证证书",
    # 知识产权
    "软著", "软件著作权", "计算机软件著作权",
    "专利证书", "专利", "商标注册证", "商标",
    "安全生产许可证", "经营许可证",
    # 信息安全/密码/信创/公安
    "等保测评报告", "等级保护测评报告",
    "商用密码产品认证证书", "商用密码认证证书", "密码产品认证证书",
    "信创适配证明", "信创适配", "兼容性列表", "信创兼容性",
    "销售许可证", "公安部检测报告", "公安部检测",
    "IT产品信息安全认证证书", "信息安全认证证书", "信息安全产品认证证书",
]


def _extract_required_entities(requirements: List[RequirementItem]) -> Set[str]:
    """从需求中提取要求提供的证书、报告、资质等实体关键词。"""
    entities: Set[str] = set()
    for req in requirements:
        # 与 OCR 结果做相同归一化后再匹配，避免空格/换行差异导致漏报
        text = re.sub(r"\s+", "", req.text)
        for kw in _REPORT_CERTIFICATE_KEYWORDS:
            normalized_kw = re.sub(r"\s+", "", kw)
            if normalized_kw in text:
                entities.add(normalized_kw)
    return entities


_QUANTITY_PATTERN = re.compile(
    r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*(?:并发|在线|同时|核心|可用性|成功率|内存|存储|容量|带宽|延迟|响应|吞吐|支持|达到)?\s*"
    r"(核|核数|CPU|GB|G|TB|年|个月|月|天|日|小时|分钟|秒|ms|s|人|用户|个|%|百分之|万元|元|次|QPS|TPS|套)",
    re.IGNORECASE,
)

# 单位简写 -> 标准写法（小写），与 table_checker 保持一致
_UNIT_ALIASES = {
    "g": "gb",
    "m": "mb",
    "t": "tb",
}


def _extract_quantities(text: str) -> List[Tuple[float, str]]:
    """从文本中提取数值+单位组合，返回 [(数值, 小写单位)]。"""
    results: List[Tuple[float, str]] = []
    for match in _QUANTITY_PATTERN.finditer(text):
        try:
            value = float(match.group(1))
            unit = _UNIT_ALIASES.get(match.group(2).lower(), match.group(2).lower())
            results.append((value, unit))
        except ValueError:
            continue
    return results


_LE_DIRECTION_KEYWORDS = ["不超过", "不得超过", "不大于", "不得大于", "不多于", "不得多于", "最多", "最高", "≤", "<=", "小于"]


def _is_le_direction(req_text: str) -> bool:
    """判断需求文本中的数值是否按『不超过/最多』方向约束。"""
    return any(kw in req_text for kw in _LE_DIRECTION_KEYWORDS)


def _check_ocr_quantity_mismatches(req_text: str, ocr_text: str) -> List[str]:
    """
    比较需求中的数值与 OCR 文字中的同单位数值。
    默认按『不少于』方向判断；若需求含『不超过』类词则按『不超过』判断。
    返回具体偏离描述列表。
    """
    mismatches: List[str] = []
    req_quantities = _extract_quantities(req_text)
    if not req_quantities:
        return mismatches

    ocr_quantities = _extract_quantities(ocr_text)
    if not ocr_quantities:
        return mismatches

    # 按单位聚合 OCR 中的数值
    ocr_by_unit: Dict[str, List[float]] = {}
    for value, unit in ocr_quantities:
        ocr_by_unit.setdefault(unit, []).append(value)

    is_le = _is_le_direction(req_text)

    seen: set[str] = set()
    for req_value, req_unit in req_quantities:
        ocr_values = ocr_by_unit.get(req_unit)
        if not ocr_values:
            continue
        # ge 方向取最大值：只要图片中存在满足要求的值即认为通过；
        # le 方向取最小值：最不利值仍超过要求才报偏离。
        compare_value = min(ocr_values) if is_le else max(ocr_values)
        msg: str | None = None
        if is_le and compare_value > req_value:
            msg = f"要求不超过 {req_value:g}{req_unit}，图片中为 {compare_value:g}{req_unit}"
        elif not is_le and compare_value < req_value:
            msg = f"要求不少于 {req_value:g}{req_unit}，图片中为 {compare_value:g}{req_unit}"
        if msg and msg not in seen:
            seen.add(msg)
            mismatches.append(msg)

    return mismatches


# 通用非产品证明材料章节，这些章节下的图片不应按产品需求做 OCR 校验
_GENERIC_SECTION_DENYLIST = {
    "授权委托书",
    "售后服务承诺函",
    "产品截图证明",
    "响应情况证明材料",
}


def _title_compatible(req_title: str, ctx_title: str, threshold: float = 0.5) -> bool:
    """判断两个章节/产品标题是否属于同一章节（支持近似匹配）。"""
    if not req_title or not ctx_title:
        return True

    r = req_title.lower().strip(" \t　、，：:.，,;；")
    c = ctx_title.lower().strip(" \t　、，：:.，,;；")
    if r in c or c in r:
        return True

    try:
        import jieba
    except ImportError:
        return False

    r_words = set(w for w in jieba.lcut(r) if w.strip())
    c_words = set(w for w in jieba.lcut(c) if w.strip())
    if not r_words:
        return False
    common = r_words & c_words
    return len(common) / len(r_words) >= threshold


def _context_compatible(req: RequirementItem, context_block: TextBlock | None) -> bool:
    """
    判断需求条目与截图上下文 block 是否属于同一章节/产品。

    投标文件的每个 block 已通过 bid_splitter 标注 section_title；
    截图位于其 context_block 之后，因此只应和该上下文所属章节/产品的需求做比对，
    避免把 A 产品的证书/参数要求套用到 B 产品的截图上。
    """
    if context_block is None:
        return True

    ctx_text = (context_block.text or "").strip()
    if ctx_text in _GENERIC_SECTION_DENYLIST:
        return False

    req_title = req.section_title or ""
    ctx_title = context_block.section_title or ""

    if _title_compatible(req_title, ctx_title):
        return True

    # 兜底：需求中的产品/章节名出现在上下文文本中（适用于标题识别失败的情况）
    product = req_title or (
        req.text.split(" | ", 1)[0].strip().lower() if " | " in req.text else ""
    )
    if product and product in context_block.text.lower():
        return True

    return False


def _text_overlaps(req_text: str, context_text: str, threshold: float = 0.3) -> bool:
    """判断需求文本与上下文文本是否有实质重叠（用于把截图精确归到对应需求条目）。"""
    if not req_text or not context_text:
        return False

    norm_req = re.sub(r"\s+", "", req_text)
    norm_ctx = re.sub(r"\s+", "", context_text)
    if norm_req in norm_ctx or norm_ctx in norm_req:
        return True

    try:
        import jieba
    except ImportError:
        return False

    req_words = set(jieba.lcut(norm_req.lower()))
    ctx_words = set(jieba.lcut(norm_ctx.lower()))
    if not req_words:
        return False
    overlap = req_words & ctx_words
    return len(overlap) / len(req_words) >= threshold


def _write_image_blob(image_path: Path, blob: bytes) -> bool:
    """将图片 blob 写入磁盘，返回是否成功。"""
    try:
        image_path.parent.mkdir(parents=True, exist_ok=True)
        with open(image_path, "wb") as f:
            f.write(blob)
        return True
    except Exception:
        return False


def check_images(
    doc: ParsedDocument,
    requirements: List[RequirementItem],
    engine: OcrEngine,
    output_dir: Path | str,
    coverage_threshold: float = 0.3,
    debug: bool = False,
) -> List[OcrIssue]:
    """
    检查投标文件中截图是否覆盖需求关键词、证书/报告及参数一致性。

    :param coverage_threshold: 关键词覆盖率低于该阈值时生成 OcrIssue，默认 0.3。
    :param debug: 是否将图片写入 output_dir 以便人工检查，默认 False；生成 issue 时始终写盘。
    """
    output_dir = Path(output_dir)

    issues: List[OcrIssue] = []

    # 建立 block_index -> TextBlock 映射，用于图片上下文定位
    block_by_index = {block.index: block for block in doc.blocks}

    for img in doc.images:
        if not _image_size_ok(img.blob):
            logger.warning("跳过超大图片 #%s（%s bytes）", img.image_index, len(img.blob))
            continue

        ocr_text = engine.recognize(img.blob)
        if not ocr_text:
            continue

        context_block = block_by_index.get(img.block_index)

        # 只保留与截图上下文同章节/产品的需求，避免全局关键词/证书/参数造成大量误报
        section_reqs = [r for r in requirements if _context_compatible(r, context_block)]
        if not section_reqs:
            if debug:
                image_path = output_dir / f"image_{img.image_index}.{_safe_image_ext(img.ext)}"
                _write_image_blob(image_path, img.blob)
            continue

        # 尽量把截图精确归到上下文对应的那条需求，用于关键词和证书检查
        narrow_reqs = [
            r for r in section_reqs
            if _text_overlaps(r.text, context_block.text if context_block else "")
        ]

        # 关键词：有精确匹配需求时用精确的，否则回退到同产品全部需求
        keyword_reqs = narrow_reqs if narrow_reqs else section_reqs
        keywords = _extract_relevant_keywords(keyword_reqs)

        # 证书/报告：优先只在上下文明确对应的需求中查找；若无精确匹配，
        # 回退到同产品全部需求（避免 generic 截图漏掉同一章节下的证书要求）。
        entity_reqs = narrow_reqs if narrow_reqs else section_reqs
        required_entities = _extract_required_entities(entity_reqs)

        # 关键词在提取时已去除空格，OCR 结果也做同样归一化
        ocr_text_normalized = re.sub(r"\s+", "", ocr_text)

        # 1) 关键词覆盖率（仅作为辅助信息，不再单独生成 issue）
        missing_keywords = [kw for kw in keywords if kw not in ocr_text_normalized]
        coverage = 1 - len(missing_keywords) / len(keywords) if keywords else 1.0
        low_coverage = coverage < coverage_threshold

        # 2) 缺失的证书/报告
        missing_entities = [e for e in required_entities if e not in ocr_text_normalized]

        # 3) 参数偏离：同产品需求中比对数值
        parameter_mismatches: List[str] = []
        for req in section_reqs:
            parameter_mismatches.extend(_check_ocr_quantity_mismatches(req.text, ocr_text_normalized))

        # 覆盖率单独出现时意义不大，仅在有证书/参数问题时作为补充说明
        should_report = bool(missing_entities) or bool(parameter_mismatches)
        report_coverage = low_coverage and should_report

        image_path = output_dir / f"image_{img.image_index}.{img.ext or 'png'}"

        if should_report:
            if not _write_image_blob(image_path, img.blob):
                continue

            context_hint = f"（位于「{context_block.text[:60]}...」之后）" if context_block else ""

            message_parts: List[str] = []
            if report_coverage:
                message_parts.append(f"OCR 文字覆盖需求关键词较少（覆盖率 {coverage:.0%}）")
            if missing_entities:
                message_parts.append(f"未找到要求的证书/报告：{', '.join(missing_entities[:10])}")
            if parameter_mismatches:
                message_parts.append(f"参数偏离：{'；'.join(parameter_mismatches[:5])}")

            message = f"截图 #{img.image_index}{context_hint} " + "；".join(message_parts) + "，请确认截图内容是否满足需求。"

            issues.append(
                OcrIssue(
                    image_index=img.image_index,
                    image_path=image_path,
                    missing_keywords=missing_keywords[:10],
                    missing_entities=missing_entities[:10],
                    parameter_mismatches=parameter_mismatches[:5],
                    message=message,
                    context_block=context_block,
                )
            )
        elif debug:
            _write_image_blob(image_path, img.blob)

    return issues
