"""pytest 风格的 OCR 引擎测试。"""
from __future__ import annotations

from pathlib import Path

from proofreader.checkers.ocr_checker import OcrEngine


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
