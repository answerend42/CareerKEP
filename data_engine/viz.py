"""把 backend/data/seeds/ 渲染成离线 SVG 网页（无外部依赖、无 JS）。

5 列布局，每层一列，节点之间画弧线、按 relation 上色，V3+V4 新增节点
高亮金色。供没法用前端"图谱传播"页（需要先提交才有数据）的用户直接看
图结构。
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_NODES = REPO_ROOT / "backend" / "data" / "seeds" / "nodes.json"
SEED_EDGES = REPO_ROOT / "backend" / "data" / "seeds" / "edges.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output" / "graph_view.html"

LAYERS = ("evidence", "ability", "composite", "direction", "role")
LAYER_LABEL = {
    "evidence": "证据",
    "ability": "能力",
    "composite": "复合",
    "direction": "方向",
    "role": "职业",
}
REL_COLOR = {
    "supports": "#9aa6c4",
    "evidences": "#5fb6d4",
    "requires": "#e26c6c",
    "prefers": "#9bd07d",
    "inhibits": "#e2a36c",
}

# data_engine 自身写过的节点 id（V3 + V4 curated 批次）。这份名单只影响
# 视图里的金色高亮，不参与图本身的语义。新增 curated 节点时同步追加这里
# 即可让它们在视图里显眼。
HIGHLIGHTED_IDS = frozenset(
    {
        # V3
        "pytorch", "tensorflow", "bert", "transformer", "nlp",
        "spacy", "gpt", "llm", "mongodb", "git",
        # V4
        "fastapi", "redis", "kubernetes", "huggingface", "langchain",
        "prompt_engineering", "fine_tuning", "rag", "llama", "java",
    }
)

NODE_W = 200
NODE_H = 36
ROW_H = 48
COL_GAP = 340
COL_X0 = 100
TOP_PAD = 80
BOTTOM_PAD = 80


def _layout(nodes: list[dict]) -> tuple[dict[str, tuple[int, int]], int, int]:
    """计算每个节点的左上角坐标，返回 (positions, canvas_w, canvas_h)。"""

    by_layer = {layer: sorted([n for n in nodes if n["layer"] == layer], key=lambda x: x["id"]) for layer in LAYERS}
    heights = {layer: len(items) * ROW_H for layer, items in by_layer.items()}
    max_h = max(heights.values()) if heights else 0
    pos: dict[str, tuple[int, int]] = {}
    layer_x = {layer: i * COL_GAP + COL_X0 for i, layer in enumerate(LAYERS)}
    for layer in LAYERS:
        items = by_layer[layer]
        layer_top = TOP_PAD + (max_h - heights[layer]) // 2
        for i, node in enumerate(items):
            pos[node["id"]] = (layer_x[layer], layer_top + i * ROW_H)
    canvas_w = layer_x[LAYERS[-1]] + NODE_W + 80
    canvas_h = TOP_PAD + max_h + BOTTOM_PAD
    return pos, canvas_w, canvas_h


def _render_html(nodes: list[dict], edges: list[dict]) -> str:
    pos, canvas_w, canvas_h = _layout(nodes)
    by_layer_count: dict[str, int] = Counter(n["layer"] for n in nodes)
    layer_x = {layer: i * COL_GAP + COL_X0 for i, layer in enumerate(LAYERS)}

    parts: list[str] = []
    parts.append(
        f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>CareerKEP graph ({len(nodes)} nodes / {len(edges)} edges)</title>
<style>
  body {{ margin:0; background:#0f1421; color:#dde3f4; font-family:system-ui,Helvetica,Arial,sans-serif; }}
  header {{ padding:16px 24px; border-bottom:1px solid #1f2640; }}
  header h1 {{ margin:0; font-size:18px; font-weight:600; }}
  header p {{ margin:4px 0 0; opacity:0.7; font-size:13px; }}
  .legend {{ display:flex; gap:20px; flex-wrap:wrap; margin-top:8px; font-size:12px; }}
  .legend span {{ display:inline-flex; align-items:center; gap:6px; }}
  .legend i {{ display:inline-block; width:18px; height:3px; }}
  .legend i.dot {{ height:10px; width:10px; border-radius:50%; }}
  svg {{ display:block; }}
  text {{ font: 13px system-ui, Helvetica, Arial; }}
</style></head><body>
<header>
  <h1>CareerKEP 知识图谱</h1>
  <p>{len(nodes)} 节点 · {len(edges)} 边 · 5 层（左 → 右：证据 → 能力 → 复合 → 方向 → 职业）</p>
  <div class="legend">"""
    )
    for rel, color in REL_COLOR.items():
        parts.append(f'<span><i style="background:{color}"></i> {rel}</span>')
    parts.append('<span><i class="dot" style="background:#ffcc66"></i> data_engine 引入的节点</span>')
    parts.append("</div></header>")
    parts.append(
        f'<svg width="{canvas_w}" height="{canvas_h}" viewBox="0 0 {canvas_w} {canvas_h}" xmlns="http://www.w3.org/2000/svg">'
    )

    # 箭头标记
    parts.append("<defs>")
    for rel, color in REL_COLOR.items():
        parts.append(
            f'<marker id="arrow-{rel}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
        )
    parts.append("</defs>")

    # 列标题
    for layer in LAYERS:
        parts.append(
            f'<text x="{layer_x[layer] + NODE_W / 2}" y="40" text-anchor="middle" '
            f'fill="#8a93b1" font-size="14" font-weight="600">'
            f'{LAYER_LABEL[layer]}（{by_layer_count.get(layer, 0)}）</text>'
        )

    # 边
    for edge in edges:
        if edge["source"] not in pos or edge["target"] not in pos:
            continue
        sx, sy = pos[edge["source"]]
        tx, ty = pos[edge["target"]]
        sx += NODE_W
        sy += NODE_H / 2
        ty += NODE_H / 2
        cx1 = sx + (tx - sx) * 0.5
        cx2 = sx + (tx - sx) * 0.5
        color = REL_COLOR.get(edge["relation"], "#666")
        opacity = 0.35 + float(edge.get("weight", 0.5)) * 0.55
        parts.append(
            f'<path d="M{sx},{sy} C{cx1},{sy} {cx2},{ty} {tx - 6},{ty}" '
            f'stroke="{color}" stroke-width="1.4" fill="none" '
            f'opacity="{opacity:.2f}" marker-end="url(#arrow-{edge["relation"]})"/>'
        )

    # 节点
    for node in nodes:
        x, y = pos[node["id"]]
        is_new = node["id"] in HIGHLIGHTED_IDS
        fill = "#ffcc66" if is_new else "#1c2438"
        stroke = "#ffcc66" if is_new else "#3b4767"
        text_color = "#0f1421" if is_new else "#dde3f4"
        parts.append(
            f'<g><rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" ry="6" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
            f'<text x="{x + 12}" y="{y + 22}" fill="{text_color}" font-size="13">{node["label"]}</text>'
            f'<text x="{x + NODE_W - 10}" y="{y + 22}" fill="{text_color}" font-size="10" '
            f'text-anchor="end" opacity="0.55">{node["id"]}</text></g>'
        )

    parts.append("</svg></body></html>")
    return "\n".join(parts)


def render(output_path: Path | None = None) -> Path:
    """读 backend/data/seeds/，写一份自包含 HTML，返回文件路径。"""

    nodes = json.loads(SEED_NODES.read_text(encoding="utf-8"))
    edges = json.loads(SEED_EDGES.read_text(encoding="utf-8"))
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("seeds 文件结构异常")

    target = output_path or DEFAULT_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_html(nodes, edges), encoding="utf-8")
    return target
