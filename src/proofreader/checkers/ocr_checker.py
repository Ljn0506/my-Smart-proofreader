"""对投标文件中的截图进行 OCR，并检查是否覆盖需求关键词。"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Set

import numpy as np
from PIL import Image

from proofreader.extractors.requirement_extractor import RequirementItem
from proofreader.parsers.docx_parser import ParsedDocument, TextBlock


@dataclass
class OcrIssue:
    image_index: int
    image_path: Path
    missing_keywords: List[str]
    message: str
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
        except Exception:
            return ""


def _extract_top_keywords(requirements: List[RequirementItem], top_n: int = 20) -> Set[str]:
    """从需求条目中提取高频关键词。"""
    from collections import Counter
    import jieba

    word_freq: Counter[str] = Counter()
    for req in requirements:
        words = jieba.lcut(req.text)
        for w in words:
            if len(w) >= 2:
                word_freq[w] += 1

    # 过滤常见虚词
    stop_words = set([
        "必须", "应当", "需要", "要求", "提供", "具备", "支持", "实现",
        "投标", "文件", "需求", "技术", "服务", "项目", "合同", "工作",
    ])
    filtered = [(w, c) for w, c in word_freq.items() if w not in stop_words]
    return set(w for w, _ in filtered[:top_n])


def check_images(
    doc: ParsedDocument,
    requirements: List[RequirementItem],
    engine: OcrEngine,
    output_dir: Path | str,
) -> List[OcrIssue]:
    """检查投标文件中截图是否覆盖需求关键词。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    issues: List[OcrIssue] = []
    keywords = _extract_top_keywords(requirements)
    if not keywords:
        return issues

    # 建立 block_index -> TextBlock 映射，用于图片上下文定位
    block_by_index = {block.index: block for block in doc.blocks}

    for img in doc.images:
        image_path = output_dir / f"image_{img.image_index}.{img.ext or 'png'}"
        try:
            with open(image_path, "wb") as f:
                f.write(img.blob)
        except Exception:
            continue

        ocr_text = engine.recognize(img.blob)
        if not ocr_text:
            continue

        missing = [kw for kw in keywords if kw not in ocr_text]
        # 只报告严重缺失：关键词覆盖度低
        coverage = 1 - len(missing) / len(keywords)
        if coverage < 0.3:
            context_block = block_by_index.get(img.block_index)
            context_hint = f"（位于「{context_block.text[:60]}...」之后）" if context_block else ""
            issues.append(
                OcrIssue(
                    image_index=img.image_index,
                    image_path=image_path,
                    missing_keywords=missing[:10],
                    message=f"截图 #{img.image_index}{context_hint} OCR 文字覆盖需求关键词较少（覆盖率 {coverage:.0%}），请确认是否遗漏关键功能展示。",
                    context_block=context_block,
                )
            )

    return issues
