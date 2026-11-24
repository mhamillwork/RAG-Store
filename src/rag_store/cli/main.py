"""Authenticated command-line client.

The CLI talks only to the file and search APIs. It does not open PostgreSQL or
Kubernetes. Credentials are read from the environment or a local token file and
are not printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

TOKEN_PATH = Path(os.environ.get("RAGCTL_TOKEN_FILE", str(Path.home() / ".config" / "rag-store" / "token")))


class Client:
    def __init__(self, files_url: str, search_url: str, token: str, timeout: float):
        self.files_url = files_url.rstrip("/")
        self.search_url = search_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            print(response.text, file=sys.stderr)
            raise SystemExit(response.status_code if response.status_code < 200 else 1)
        return response


def _token(args) -> str:
    if args.api_key:
        return args.api_key
    if os.environ.get("RAGCTL_API_KEY"):
        return os.environ["RAGCTL_API_KEY"]
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    return ""


def _client(args) -> Client:
    files = args.files_url or os.environ.get("RAGCTL_FILES_URL", "")
    search = args.search_url or os.environ.get("RAGCTL_SEARCH_URL", files)
    if not files:
        print("Set --files-url or RAGCTL_FILES_URL.", file=sys.stderr)
        raise SystemExit(2)
    return Client(files, search or files, _token(args), args.timeout)


def _print(payload) -> None:
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2))
    else:
        print(payload)


def cmd_login(args) -> None:
    client = _client(args)
    username = args.username or input("Username: ")
    password = args.password or input("Password: ")
    response = httpx.post(f"{client.files_url}/api/v1/auth/login", json={"username": username, "password": password}, timeout=args.timeout)
    if response.status_code >= 400:
        print(response.text, file=sys.stderr)
        raise SystemExit(1)
    body = response.json()
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(body["access_token"], encoding="utf-8")
    os.chmod(TOKEN_PATH, 0o600)
    print("Logged in. The access token was stored locally.")


def cmd_upload(args) -> None:
    client = _client(args)
    root = Path(args.path)
    files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file() and not path.is_symlink()]
    if not files:
        print("No files found.", file=sys.stderr)
        raise SystemExit(2)
    failures = 0
    for path in files:
        relative = "" if root.is_file() else str(path.relative_to(root).parent)
        if relative == ".":
            relative = ""
        data = {"scope": args.scope, "collection": args.collection, "relative_path": relative, "priority": args.priority}
        if args.ocr_mode:
            data["ocr_mode"] = args.ocr_mode
        with path.open("rb") as handle:
            response = client.request(
                "POST",
                f"{client.files_url}/api/v1/documents/upload",
                data=data,
                files={"file": (path.name, handle)},
            )
        body = response.json()
        print(f"{path}: document {body.get('document', {}).get('id')} job {body.get('job_id')}")
        if response.status_code >= 400:
            failures += 1
    raise SystemExit(1 if failures else 0)


def cmd_collections(args) -> None:
    client = _client(args)
    if args.collections_command == "list":
        response = client.request("GET", f"{client.files_url}/api/v1/collections", params={"scope": args.scope} if args.scope else None)
        _print(response.json())
    elif args.collections_command == "create":
        response = client.request("POST", f"{client.files_url}/api/v1/collections", json={"name": args.name, "scope": args.scope, "description": args.description or ""})
        _print(response.json())


def cmd_documents(args) -> None:
    client = _client(args)
    base = f"{client.files_url}/api/v1/documents"
    if args.documents_command == "list":
        params = {}
        if args.scope:
            params["scope"] = args.scope
        _print(client.request("GET", base, params=params).json())
    elif args.documents_command == "download":
        response = client.request("GET", f"{base}/{args.document_id}/download")
        target = Path(args.output or "document.bin")
        target.write_bytes(response.content)
        print(target)
    elif args.documents_command == "delete":
        _print(client.request("DELETE", f"{base}/{args.document_id}", params={"physical": args.physical}).json())
    elif args.documents_command == "reindex":
        _print(client.request("POST", f"{base}/{args.document_id}/reindex").json())
    elif args.documents_command == "reprocess":
        _print(client.request("POST", f"{base}/{args.document_id}/reprocess", json={"ocr_mode": args.ocr_mode, "parser": args.parser}).json())
    elif args.documents_command == "markdown":
        print(client.request("GET", f"{base}/{args.document_id}/markdown").text)
    elif args.documents_command == "docling":
        _print(client.request("GET", f"{base}/{args.document_id}/docling", params={"include_content": True}).json())
    elif args.documents_command == "tables":
        _print(client.request("GET", f"{base}/{args.document_id}/tables").json())


def cmd_jobs(args) -> None:
    client = _client(args)
    if args.jobs_command == "list":
        _print(client.request("GET", f"{client.files_url}/api/v1/jobs").json())
    elif args.jobs_command == "retry":
        _print(client.request("POST", f"{client.files_url}/api/v1/jobs/{args.job_id}/retry").json())


def cmd_status(args) -> None:
    client = _client(args)
    _print(client.request("GET", f"{client.files_url}/api/v1/users/me").json())


def cmd_quota(args) -> None:
    client = _client(args)
    _print(client.request("GET", f"{client.files_url}/api/v1/users/me/quota").json())


def cmd_search(args) -> None:
    client = _client(args)
    payload = {"query": args.query, "scope": args.scope, "mode": args.mode, "top_k": args.top_k, "rerank": args.rerank}
    _print(client.request("POST", f"{client.search_url}/api/v1/search", json=payload).json())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ragctl", description="RAG Store command-line client")
    parser.add_argument("--files-url", default="")
    parser.add_argument("--search-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=120)
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login")
    login.add_argument("--username", default="")
    login.add_argument("--password", default="")
    login.set_defaults(func=cmd_login)

    upload = sub.add_parser("upload")
    upload.add_argument("path")
    upload.add_argument("--scope", required=True, choices=["global", "local"])
    upload.add_argument("--collection", required=True)
    upload.add_argument("--recursive", action="store_true")
    upload.add_argument("--priority", default="ordinary")
    upload.add_argument("--ocr-mode", default="")
    upload.set_defaults(func=cmd_upload)

    collections = sub.add_parser("collections")
    collections_sub = collections.add_subparsers(dest="collections_command", required=True)
    collections_list = collections_sub.add_parser("list")
    collections_list.add_argument("--scope", default="")
    collections_list.set_defaults(func=cmd_collections)
    collections_create = collections_sub.add_parser("create")
    collections_create.add_argument("name")
    collections_create.add_argument("--scope", required=True)
    collections_create.add_argument("--description", default="")
    collections_create.set_defaults(func=cmd_collections)

    documents = sub.add_parser("documents")
    documents_sub = documents.add_subparsers(dest="documents_command", required=True)
    documents_list = documents_sub.add_parser("list")
    documents_list.add_argument("--scope", default="")
    documents_list.set_defaults(func=cmd_documents)
    download = documents_sub.add_parser("download")
    download.add_argument("document_id")
    download.add_argument("--output", default="")
    download.set_defaults(func=cmd_documents)
    delete = documents_sub.add_parser("delete")
    delete.add_argument("document_id")
    delete.add_argument("--physical", action="store_true")
    delete.set_defaults(func=cmd_documents)
    reindex = documents_sub.add_parser("reindex")
    reindex.add_argument("document_id")
    reindex.set_defaults(func=cmd_documents)
    reprocess = documents_sub.add_parser("reprocess")
    reprocess.add_argument("document_id")
    reprocess.add_argument("--ocr-mode", default=None)
    reprocess.add_argument("--parser", default=None)
    reprocess.set_defaults(func=cmd_documents)
    markdown = documents_sub.add_parser("markdown")
    markdown.add_argument("document_id")
    markdown.set_defaults(func=cmd_documents)
    docling = documents_sub.add_parser("docling")
    docling.add_argument("document_id")
    docling.set_defaults(func=cmd_documents)
    tables = documents_sub.add_parser("tables")
    tables.add_argument("document_id")
    tables.set_defaults(func=cmd_documents)

    jobs = sub.add_parser("jobs")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    jobs_list = jobs_sub.add_parser("list")
    jobs_list.set_defaults(func=cmd_jobs)
    jobs_retry = jobs_sub.add_parser("retry")
    jobs_retry.add_argument("job_id")
    jobs_retry.set_defaults(func=cmd_jobs)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)
    quota = sub.add_parser("quota")
    quota.set_defaults(func=cmd_quota)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--scope", default="all")
    search.add_argument("--mode", default="hybrid")
    search.add_argument("--top-k", type=int, default=10)
    search.add_argument("--rerank", action="store_true")
    search.set_defaults(func=cmd_search)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except httpx.HTTPError as exc:
        print(f"Request failed: {exc.__class__.__name__}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
