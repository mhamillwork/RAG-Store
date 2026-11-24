# Developer guide

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
PYTHONPATH=src pytest tests/unit tests/docling tests/integration
cd src/frontend && npm ci && npm run build
helm lint helm-chart
```

The integration test drops and recreates the `ragstore` schema. Point it at a disposable database.

`ruff check src tests` is the Python lint. The frontend build is `tsc` plus Vite.

Do not add a network call to a model host in a test without an explicit fixture. Production code paths must keep failing when the inference URL is empty.
