"""后端入口：CLI + 本地 HTTP 服务。"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any

from .api.recommend import recommend


class _RequestHandler(BaseHTTPRequestHandler):
    """简单 HTTP 接口，方便本地联调。"""

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/recommend":
            self._send_json(404, {"detail": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            response = recommend(payload).to_dict()
            self._send_json(200, response)
        except Exception as exc:  # noqa: BLE001
            self._send_json(400, {"detail": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # 减少控制台噪音，保持本地体验干净。
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动本地 HTTP 服务。"""

    server = ThreadingHTTPServer((host, port), _RequestHandler)
    print(f"Career KG 后端已启动：http://{host}:{port}")
    print("接口：GET /health, POST /api/recommend")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断信号，服务退出。")
    finally:
        server.server_close()


def _read_json_argument(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    candidate = Path(value)
    if candidate.exists():
        return json.loads(candidate.read_text(encoding="utf-8"))
    return json.loads(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Career KG 后端入口")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="启动 HTTP 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    recommend_parser = subparsers.add_parser("recommend", help="直接执行一次推荐并输出 JSON")
    recommend_parser.add_argument("--text", default=None, help="自然语言画像")
    recommend_parser.add_argument("--payload", default=None, help="JSON 字符串或 JSON 文件路径")
    recommend_parser.add_argument("--target-role", default=None, help="目标岗位节点 ID")
    recommend_parser.add_argument("--top-k", type=int, default=5, help="返回条目数量")

    args = parser.parse_args()

    if args.command == "serve":
        serve(args.host, args.port)
        return

    payload = _read_json_argument(args.payload)
    if args.text is not None:
        payload["text"] = args.text
    if args.target_role is not None:
        payload["target_role"] = args.target_role
    payload["top_k"] = args.top_k

    response = recommend(payload).to_dict()
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

