"""后端入口：CLI + 本地 HTTP 服务。"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from typing import Any

from .api.recommend import recommend
from .services.graph_loader import GraphValidationError, build_graph_diagnostics, load_graph_data
from .services.graph_quality import validate_graph_quality
from .services.input_normalizer import load_alias_map, validate_alias_map


_MAX_REQUEST_BODY_BYTES = 1_048_576


def _normalize_lookup_term(value: str) -> str:
    """把展示文本统一成更适合做查找的形式。"""

    return "".join(str(value).strip().casefold().split())


def _append_search_term(search_terms: list[str], value: str) -> None:
    """把候选搜索词去空格、归一化后加入列表，保持去重。"""

    normalized = _normalize_lookup_term(value)
    if normalized and normalized not in search_terms:
        search_terms.append(normalized)


def _collect_role_search_terms(graph: Any, alias_map: dict[str, list[str]], node_id: str) -> list[str]:
    """收集岗位节点可用于搜索的所有词条。

    这里不仅收集岗位本身的 ID 和标签，还会沿着图谱向上回溯，把所有
    祖先节点的 ID、标签和别名一起纳入，避免前端只会搜到表层岗位名，
    漏掉更贴近用户输入习惯的能力词、证据词和别名词。
    """

    search_terms: list[str] = []
    visited: set[str] = set()

    def _visit(current_node_id: str) -> None:
        if current_node_id in visited:
            return
        visited.add(current_node_id)

        current_node = graph.nodes.get(current_node_id)
        if current_node is None:
            return

        _append_search_term(search_terms, current_node.id)
        _append_search_term(search_terms, current_node.label)
        for alias in alias_map.get(current_node.id, []):
            _append_search_term(search_terms, alias)

        for edge in graph.incoming.get(current_node_id, []):
            source_node = graph.nodes.get(edge.source)
            if source_node is None:
                continue
            _visit(source_node.id)

    _visit(node_id)
    return search_terms


def _build_role_options(graph: Any, alias_map: dict[str, list[str]]) -> list[dict[str, Any]]:
    """把角色节点整理成前端更容易直接使用的选项列表。

    这里额外附带 `search_terms`，方便前端做搜索下拉，不需要再自己处理
    节点 ID、标签里的空格或大小写问题。搜索词会沿图谱祖先链向上收集，
    这样前端可以直接用一份接口数据支持“岗位名 + 别名 + 能力词”搜索。
    """

    graph_summary = graph.summary()
    role_options: list[dict[str, Any]] = []
    for node in graph_summary.get("role_nodes", []):
        node_id = str(node.get("id") or "").strip()
        label = str(node.get("label") or node_id).strip()
        search_terms = _collect_role_search_terms(graph, alias_map, node_id)
        if label:
            # 把展示标签挪到前面，便于前端调试时优先看到最直观的岗位名。
            search_terms = [term for term in search_terms if term != _normalize_lookup_term(label)]
            search_terms.insert(0, _normalize_lookup_term(label))
        if node_id and _normalize_lookup_term(node_id) in search_terms:
            search_terms = [term for term in search_terms if term != _normalize_lookup_term(node_id)]
            search_terms.insert(0, _normalize_lookup_term(node_id))
        role_options.append(
            {
                "node_id": node_id,
                "label": label,
                "search_terms": search_terms,
            }
        )
    return role_options


class _RequestHandler(BaseHTTPRequestHandler):
    """简单 HTTP 接口，方便本地联调。"""

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_json_content_type(self) -> bool:
        """判断请求头是否声明为 JSON。"""

        raw_content_type = self.headers.get("Content-Type", "")
        media_type = raw_content_type.split(";", 1)[0].strip().lower()
        return media_type == "application/json" or media_type.endswith("+json")

    def _read_json_body(self) -> dict[str, Any]:
        """读取并解析请求体，统一处理 JSON 与类型错误。"""

        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("Content-Length 不是合法整数") from exc

        if length > _MAX_REQUEST_BODY_BYTES:
            raise _PayloadTooLargeError(f"请求体过大，最大允许 {_MAX_REQUEST_BODY_BYTES} 字节")

        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("请求体不是合法的 UTF-8 编码") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("请求体不是合法 JSON") from exc

        if not isinstance(payload, dict):
            raise TypeError("请求体 JSON 必须是对象")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/api/meta":
            try:
                graph = load_graph_data()
                alias_map = load_alias_map()
                alias_warnings = validate_alias_map(graph, alias_map)
                quality_warnings = validate_graph_quality(graph)
                graph_summary = build_graph_diagnostics(graph, alias_map, alias_warnings + quality_warnings)
                # 元信息接口既要稳定，也要把本地诊断尽量暴露出来，方便前端启动时直接判断图谱健康状态。
                self._send_json(
                    200,
                    {
                        "service": "career-kg-backend",
                        "version": "0.1.0",
                        "graph": graph_summary,
                        "role_options": _build_role_options(graph, alias_map),
                        "aliases_count": len(alias_map),
                        "alias_count": graph_summary["alias_count"],
                        "alias_node_count": graph_summary["alias_node_count"],
                        "endpoints": ["/health", "/api/meta", "/api/recommend"],
                    },
                )
            except GraphValidationError as exc:
                self._send_json(500, {"detail": f"graph validation failed: {exc}"})
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"detail": f"internal error: {exc}"})
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/recommend":
            self._send_json(404, {"detail": "not found"})
            return

        if not self._is_json_content_type():
            self._send_json(415, {"detail": "Content-Type 必须是 application/json"})
            return

        try:
            payload = self._read_json_body()
            response = recommend(payload).to_dict()
            self._send_json(200, response)
        except _PayloadTooLargeError as exc:
            self._send_json(413, {"detail": str(exc)})
        except (TypeError, ValueError) as exc:
            self._send_json(400, {"detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            # 这里保留服务端错误和客户端错误的区分，方便联调时快速定位问题。
            self._send_json(500, {"detail": f"internal error: {exc}"})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # 减少控制台噪音，保持本地体验干净。
        return


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动本地 HTTP 服务。"""

    server = ThreadingHTTPServer((host, port), _RequestHandler)
    print(f"Career KG 后端已启动：http://{host}:{port}")
    print("接口：GET /health, GET /api/meta, POST /api/recommend")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断信号，服务退出。")
    finally:
        server.server_close()


def _read_json_argument(value: str | None) -> dict[str, Any]:
    """解析 JSON 字符串参数。"""

    if not value:
        return {}

    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise TypeError("payload 必须是 JSON 对象")
    return payload


class _PayloadTooLargeError(ValueError):
    """请求体超过允许大小。"""


def _read_json_file_argument(path_value: str | None) -> dict[str, Any]:
    """从文件中读取 JSON 参数。"""

    if not path_value:
        return {}

    if path_value == "-":
        payload_text = sys.stdin.read()
        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            raise TypeError("payload 标准输入内容必须是 JSON 对象")
        return payload

    path = Path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"payload 文件不存在: {path_value}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("payload 文件内容必须是 JSON 对象")
    return payload


def _run_recommend_command(
    payload_json: str | None,
    payload_file: str | None,
    text: str | None,
    target_role: str | None,
    top_k: int,
) -> int:
    """执行一次推荐命令，并把错误分成参数错误和内部错误。"""

    try:
        if payload_json and payload_file:
            raise ValueError("payload_json 和 payload_file 不能同时使用")

        if payload_file:
            payload = _read_json_file_argument(payload_file)
        else:
            payload = _read_json_argument(payload_json)
        if text is not None:
            payload["text"] = text
        if target_role is not None:
            payload["target_role"] = target_role
        payload["top_k"] = top_k

        response = recommend(payload).to_dict()
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0
    except (json.JSONDecodeError, TypeError, ValueError, FileNotFoundError, OSError) as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


def _run_validate_graph_command() -> int:
    """校验本地运行时图谱产物并输出诊断 JSON。"""

    try:
        graph = load_graph_data()
        alias_map = load_alias_map()
        alias_warnings = validate_alias_map(graph, alias_map)
        quality_warnings = validate_graph_quality(graph)
        diagnostics = build_graph_diagnostics(graph, alias_map, alias_warnings + quality_warnings)
        print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
        return 0
    except GraphValidationError as exc:
        print(f"图谱校验失败: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Career KG 后端入口")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="启动 HTTP 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    recommend_parser = subparsers.add_parser("recommend", help="直接执行一次推荐并输出 JSON")
    recommend_parser.add_argument("--text", default=None, help="自然语言画像")
    payload_group = recommend_parser.add_mutually_exclusive_group()
    payload_group.add_argument("--payload-json", default=None, help="JSON 字符串")
    payload_group.add_argument("--payload-file", default=None, help="JSON 文件路径")
    recommend_parser.add_argument("--target-role", default=None, help="目标岗位节点 ID / 中文标签 / 别名")
    recommend_parser.add_argument("--top-k", type=int, default=5, help="返回条目数量")

    subparsers.add_parser("validate-graph", help="校验运行时图谱产物并输出本地诊断")

    args = parser.parse_args()

    if args.command == "serve":
        serve(args.host, args.port)
        return 0

    if args.command == "validate-graph":
        return _run_validate_graph_command()

    return _run_recommend_command(args.payload_json, args.payload_file, args.text, args.target_role, args.top_k)


if __name__ == "__main__":
    raise SystemExit(main())
