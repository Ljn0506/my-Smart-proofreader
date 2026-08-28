import hashlib
import re
from typing import List

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from proofreader.models.requirements import RequirementItem


class SemanticDeduplicator:
    def __init__(self, threshold: float = 0.95):
        self.threshold = threshold

    def deduplicate(self, items: List[RequirementItem]) -> List[RequirementItem]:
        # 1. stable_hash dedup
        seen_hashes = set()
        candidates = []
        for item in items:
            h = self._stable_hash(item)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            candidates.append(item)

        if len(candidates) <= 1:
            return candidates

        # 2. semantic dedup with TF-IDF
        texts = [self._normalize(item.normalized_text) for item in candidates]
        try:
            vectorizer = TfidfVectorizer()
            matrix = vectorizer.fit_transform(texts)
            sim_matrix = cosine_similarity(matrix)
        except ValueError:
            return candidates

        keep = [True] * len(candidates)
        for i in range(len(candidates)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(candidates)):
                if not keep[j]:
                    continue
                if sim_matrix[i][j] >= self.threshold:
                    # Prefer table source / longer chapter_path
                    if self._prefer(candidates[i], candidates[j]) == candidates[j]:
                        keep[i] = False
                        break
                    else:
                        keep[j] = False

        return [candidates[i] for i in range(len(candidates)) if keep[i]]

    def _stable_hash(self, item: RequirementItem) -> str:
        if item.stable_hash:
            return item.stable_hash
        base = item.raw_text + (item.chapter_path[-1] if item.chapter_path else "")
        return hashlib.md5(base.encode("utf-8")).hexdigest()

    def _normalize(self, text: str) -> str:
        t = re.sub(r"[\s★▲]+", "", text)
        return t.lower()

    def _prefer(self, a: RequirementItem, b: RequirementItem) -> RequirementItem:
        if len(a.chapter_path) != len(b.chapter_path):
            return a if len(a.chapter_path) >= len(b.chapter_path) else b
        if len(a.raw_text) != len(b.raw_text):
            return a if len(a.raw_text) >= len(b.raw_text) else b
        return a
