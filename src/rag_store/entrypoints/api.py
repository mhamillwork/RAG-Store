"""Search API process."""

from __future__ import annotations

from rag_store.api.app import create_app
from rag_store.config.settings import get_settings
from rag_store.entrypoints.serve import serve


def app():
    return create_app(get_settings(), files=False, search=True)


def main() -> None:
    serve("rag_store.entrypoints.api:app")


if __name__ == "__main__":
    main()
