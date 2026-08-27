# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-08-27

### Added

- Structured data models (`RequirementItem`, `CheckTarget`, `EvaluationRule`, `DocumentClassificationResult`) and shared enums for category, constraint type, review status, document type, and procurement method.
- Document type classifier with rule-based confidence scoring, plus `DocumentType.REQUIREMENT` support for 采购需求/需求文件 documents.
- Date normalizer for Chinese absolute dates, relative periods, and date ranges.
- `docx_parser` section inference, paragraph type classification, table type classification, heading-level inference, and single-pass parsing that populates blocks, headings, sections, raw tables, and embedded images in one read.
- Extractor subsystem: numbered-paragraph, heading-based, table-row (with per-type strategies), composite extractor, semantic deduplicator, and scoring extractor that produces atomic scoring items and aggregate `EvaluationRule`s.
- JSON-backed `RequirementRepository` with project metadata and path-traversal validation.
- Tests covering models, parser, repository, extractors, semantic matcher, consistency checker, OCR checker, date normalizer, document classifier, and bid annotator.

### Changed

- `parse_docx` now returns a `ParsedDocument` with both flat blocks/images and section-aware structures, and attaches document classification automatically.
- `parse_docx_with_sections` now shares the single-pass parser and attaches classification to match `parse_docx`.
- `extract_requirements` remains backward-compatible and delegates internally to `CompositeExtractor`.

### Fixed

- Stopped `consistency_checker` from silently passing when a bid quantity uses a different unit than the requirement; it now reports an explicit mismatch.
- Normalized whitespace in OCR entity/keyword extraction so space-stripped requirement text still matches OCR output.
- Sanitized OCR issue image paths and Streamlit download filenames to prevent path traversal and unsafe HTML injection.
- Added a size guard (`_MAX_DOC_BYTES`) and image-size checks (`_MAX_IMAGE_BYTES`, `_MAX_IMAGE_PIXELS`) to avoid memory exhaustion on malformed or oversized inputs.
- Capped the subsequence matcher in `bid_annotator` and added a linear greedy fallback for long paragraphs, eliminating an O(n²) hang on large documents.
- Escaped issue IDs and suggestions rendered with `unsafe_allow_html=True` in the Streamlit UI.
- Removed unused `re` import from `json_repository.py`.

### Deferred

- Pipeline integration with `RequirementRepository` and the `proofread_project` entry point.
- Streamlit requirement manager page and navigation entry.
- Enforcement of `check_target` when `check_method="rule"`.
- These items are tracked as P1 TODOs in `TODOS.md`.

## [0.1.0] - 2026-06-18

- Initial end-to-end proofreading pipeline: parse Word documents, extract requirements, detect consistency/typo/table/OCR issues, and export annotated bids and Excel reports.
