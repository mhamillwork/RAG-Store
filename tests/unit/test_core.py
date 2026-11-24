"""Unit tests that do not need PostgreSQL or Docling models."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag_store.chunking.chunker import chunk_document
from rag_store.chunking.tokenizer import BasicTokenizer
from rag_store.common.paths import confine, normalize_relative_path
from rag_store.config.settings import (
    AuthSettings,
    ChunkingSettings,
    DatabaseSettings,
    DoclingSettings,
    EmbeddingSettings,
    Settings,
)
from rag_store.ocr.languages import map_languages
from rag_store.search.ranking import reciprocal_rank_fusion


def test_relative_path_rejects_traversal():
    with pytest.raises(Exception):
        normalize_relative_path("../secret")
    with pytest.raises(Exception):
        normalize_relative_path("/etc/passwd")


def test_confine_rejects_escape(tmp_path: Path):
    with pytest.raises(Exception):
        confine(tmp_path, "../outside")


def test_rank_fusion_prefers_agreement():
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
    assert fused["b"] > fused["a"]
    assert fused["b"] > fused["c"]


def test_table_chunk_keeps_header_and_value():
    drafts = chunk_document(
        {
            "texts": [{"text": "Introduction", "label": "title", "prov": [{"page_no": 1}]}],
            "tables": [{"headers": ["Field", "Value"], "rows": [["MTU", "1500 bytes"]], "page": 2}],
        },
        filename="manual.txt",
        relative_path="manual.txt",
        file_type="txt",
        max_tokens=128,
        overlap_tokens=16,
        strategy="auto",
        tokenizer=BasicTokenizer(),
    )
    table_chunks = [item.content for item in drafts if "MTU" in item.content]
    assert table_chunks
    assert "1500 bytes" in table_chunks[0]
    assert "Field" in table_chunks[0]


def test_language_mapping_differs_by_engine():
    assert map_languages("rapidocr", ["en"]) == ["en"]
    assert map_languages("tesseract", ["en"]) == ["eng"]


def test_production_rejects_test_embeddings_and_disabled_ocr():
    settings = Settings(
        environment="production",
        component="worker",
        database=DatabaseSettings(url="postgresql+psycopg://example"),
        auth=AuthSettings(jwt_secret="x" * 40),
        embedding=EmbeddingSettings(provider="deterministic-test", dimensions=768),
        chunking=ChunkingSettings(tokenizer_mode="basic", tokenizer_required=False),
        docling=DoclingSettings(ocr_enabled=False),
    )
    with pytest.raises(Exception) as caught:
        settings.validate_runtime()
    message = str(caught.value.details)
    assert "Test embedding providers" in message
    assert "OCR" in message


def test_dimension_mismatch_is_rejected():
    settings = Settings(
        environment="test",
        component="search",
        database=DatabaseSettings(url="postgresql+psycopg://example"),
        auth=AuthSettings(jwt_secret="x" * 40),
        embedding=EmbeddingSettings(provider="deterministic-test", dimensions=1024, model="deterministic-test"),
        chunking=ChunkingSettings(tokenizer_mode="basic", tokenizer_required=False),
    )
    with pytest.raises(Exception):
        settings.validate_runtime()
