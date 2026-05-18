from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .api.recommend import RecommendationService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Career KG recommendation service")
    parser.add_argument("--serve", action="store_true", help="start a local HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="server host")
    parser.add_argument("--port", type=int, default=8080, help="server port")
    parser.add_argument("--input-file", type=Path, help="JSON request file for one-off inference")
    return parser


def load_payload(input_file: Path | None) -> dict[str, Any]:
    if input_file:
        return json.loads(input_file.read_text(encoding="utf-8"))
    sample_path = Path(__file__).resolve().parents[2] / "data" / "demo" / "sample_request.json"
    return json.loads(sample_path.read_text(encoding="utf-8"))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def frontend_root() -> Path | None:
    dist_dir = repo_root() / "frontend" / "dist"
    if dist_dir.exists():
        return dist_dir
    return None


def serve(host: str, port: int) -> None:
    service = RecommendationService()
    static_root = frontend_root()
    if static_root is not None:
        static_root = static_root.resolve()
    else:
        print("frontend build not found at frontend/dist; serving API endpoints only.")

    class Handler(BaseHTTPRequestHandler):
        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._send_cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, file_path: Path, status: int = HTTPStatus.OK) -> None:
            body = file_path.read_bytes()
            content_type, _ = mimetypes.guess_type(file_path.name)
            self.send_response(status)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self._send_cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _resolve_static_path(self) -> Path | None:
            if static_root is None:
                return None
            raw_path = urlparse(self.path).path
            path = unquote(raw_path)
            if path in {"/", ""}:
                candidate = static_root / "index.html"
            else:
                candidate = (static_root / path.lstrip("/")).resolve()
                # Allow direct navigation to SPA routes while still serving real assets by path.
                if not candidate.exists() and "." not in Path(path).name:
                    candidate = static_root / "index.html"
            if not candidate.exists() or not candidate.is_file():
                return None
            if not candidate.is_relative_to(static_root):
                return None
            return candidate

        def do_GET(self) -> None:  # noqa: N802
            url_path = urlparse(self.path).path
            if url_path == "/health":
                self._send_json({"status": "ok"})
                return
            if url_path in {"/api/catalog", "/catalog"}:
                self._send_json(service.catalog())
                return
            static_path = self._resolve_static_path()
            if static_path is not None:
                self._send_file(static_path)
                return
            if static_root is None and url_path in {"/", "/index.html"}:
                self._send_json(
                    {
                        "error": "frontend build not found; API server is running",
                        "hint": "run the frontend dev server with `npm --prefix frontend run dev` or build it with `npm --prefix frontend run build`.",
                    },
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            url_path = urlparse(self.path).path
            if url_path not in {
                "/recommend",
                "/api/recommend",
                "/role-gap",
                "/api/role-gap",
                "/action-simulate",
                "/api/action-simulate",
            }:
                self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            except (ValueError, json.JSONDecodeError):
                self._send_json({"error": "invalid json payload"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(payload, dict):
                self._send_json({"error": "request body must be a JSON object"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                if url_path in {"/role-gap", "/api/role-gap"}:
                    self._send_json(service.role_gap(payload))
                    return
                if url_path in {"/action-simulate", "/api/action-simulate"}:
                    self._send_json(service.action_simulate(payload))
                    return
                self._send_json(service.recommend(payload))
            except ValueError as error:
                self._send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"serving on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.serve:
        serve(args.host, args.port)
        return

    service = RecommendationService()
    payload = load_payload(args.input_file)
    print(json.dumps(service.recommend(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
