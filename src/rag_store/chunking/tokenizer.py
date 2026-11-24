"""Token counting.

Production uses a tokenizer file prepared inside the isolated network. The basic
tokenizer is a documented approximation for development and tests. Neither path
downloads a tokenizer.
"""

from __future__ import annotations

import re
from pathlib import Path

from rag_store.common.errors import ConfigurationError
from rag_store.config.settings import ChunkingSettings


class BasicTokenizer:
    """Counts words and punctuation. This is not the embedding model's tokenizer."""

    name = "rag-store-basic/1"

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


class HuggingFaceTokenizer:
    name = "huggingface-local"

    def __init__(self, path: str):
        file_path = Path(path)
        if not file_path.is_file():
            raise ConfigurationError(
                "The configured tokenizer file does not exist.",
                details={"path": path},
            )
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(file_path))
        self.name = f"huggingface-local:{file_path.name}"

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tokenizer.encode(text).ids)


def build_tokenizer(settings: ChunkingSettings):
    if settings.tokenizer_mode == "huggingface":
        if not settings.tokenizer_path:
            if settings.tokenizer_required:
                raise ConfigurationError("RAG_STORE_CHUNKING__TOKENIZER_PATH is required.")
            return BasicTokenizer()
        return HuggingFaceTokenizer(settings.tokenizer_path)
    return BasicTokenizer()
