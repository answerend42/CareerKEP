import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Graph, NodeEvent } from "@antv/g6";
import type { EdgeData, GraphData, IElementEvent, NodeData } from "@antv/g6";

import { useRecommendationFlow } from "../hooks/useRecommendationFlow";
import { useReducedMotionPreference } from "../hooks/useReducedMotionPreference";
import { motionTimings } from "../lib/motionTokens";
import { SourceProfileList } from "../components/SourceProfileList";
import type { GraphSnapshotEdge, GraphSnapshotNode } from "../types/api";

const LAYER_ORDER = ["evidence", "ability", "composite", "direction", "role"] as const;
const LAYER_LABELS: Record<string, string> = {
  evidence: "原子证据",
  ability: "基础能力",
  composite: "复合能力",
  direction: "岗位方向",
  role: "具体职业",
};

const NODE_COLORS: Record<string, string> = {
  evidence: "oklch(0.79 0.065 252)",
  ability: "oklch(0.83 0.055 205)",
  composite: "oklch(0.86 0.06 155)",
  direction: "oklch(0.86 0.075 84)",
  role: "oklch(0.78 0.08 31)",
};

const RELATION_COLORS: Record<string, string> = {
  support: "oklch(0.58 0.13 205)",
  supports: "oklch(0.58 0.13 205)",
  requires: "oklch(0.67 0.15 80)",
  prefers: "oklch(0.57 0.12 155)",
  inhibits: "oklch(0.58 0.18 31)",
};

const DIAGNOSTIC_LABELS: Record<string, string> = {
  support_total: "支持得分",
  require_total: "要求得分",
  prefer_total: "偏好得分",
  inhibit_total: "抑制得分",
};

const DETAIL_DIAGNOSTIC_KEYS = ["support_total", "require_total", "prefer_total", "inhibit_total"] as const;

const NODE_HEIGHT = 34;
const NODE_GAP = 12;
const CANVAS_PADDING_X = 210;
const CANVAS_PADDING_TOP = 104;
const CANVAS_PADDING_BOTTOM = 52;
const DEFAULT_SCORE_THRESHOLD = 0.05;

const LAYER_INDEX = new Map<string, number>(LAYER_ORDER.map((layer, index) => [layer, index]));
type NodePosition = { x: number; y: number };

function layerRank(layer: string): number {
  return LAYER_INDEX.get(layer) ?? LAYER_ORDER.length - 1;
}

function buildVisibleNodes(
  nodes: GraphSnapshotNode[],
  pinnedNodeRanks: Map<string, number>,
): GraphSnapshotNode[] {
  const byLayer = new Map(LAYER_ORDER.map((layer) => [layer, [] as GraphSnapshotNode[]]));
  for (const node of nodes) {
    if (byLayer.has(node.layer as (typeof LAYER_ORDER)[number])) {
      byLayer.get(node.layer as (typeof LAYER_ORDER)[number])?.push(node);
    }
  }

  const visible: GraphSnapshotNode[] = [];
  for (const layer of LAYER_ORDER) {
    const ranked = [...(byLayer.get(layer) || [])].sort((a, b) => {
      const pinnedA = pinnedNodeRanks.get(a.id);
      const pinnedB = pinnedNodeRanks.get(b.id);
      if (pinnedA !== undefined || pinnedB !== undefined) {
        return (pinnedA ?? Number.POSITIVE_INFINITY) - (pinnedB ?? Number.POSITIVE_INFINITY);
      }
      return b.score - a.score || a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
    });
    visible.push(...ranked);
  }

  const deduped = new Map<string, GraphSnapshotNode>();
  for (const node of visible) {
    deduped.set(node.id, node);
  }
  return Array.from(deduped.values());
}

function applyScoreThreshold(
  nodes: GraphSnapshotNode[],
  edges: GraphSnapshotEdge[],
  threshold: number,
): GraphSnapshotNode[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const candidateIds = new Set(
    nodes
      .filter((node) => node.layer === "evidence" || node.score >= threshold)
      .map((node) => node.id),
  );
  const visibleIds = new Set(
    nodes
      .filter((node) => node.layer === "evidence")
      .map((node) => node.id),
  );

  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of edges) {
      if (edge.value <= 0 || !visibleIds.has(edge.source) || !candidateIds.has(edge.target)) {
        continue;
      }
      if (!visibleIds.has(edge.target)) {
        visibleIds.add(edge.target);
        changed = true;
      }
    }
  }

  return nodes.filter((node) => visibleIds.has(node.id) && nodeById.has(node.id));
}

function keepEvidenceLinkedAbilityNodes(
  nodes: GraphSnapshotNode[],
  edges: GraphSnapshotEdge[],
): GraphSnapshotNode[] {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const keepAbilityIds = new Set<string>();

  for (const edge of edges) {
    if (edge.value <= 0) {
      continue;
    }
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    if (!sourceNode || !targetNode) {
      continue;
    }
    if (sourceNode.layer === "evidence" && targetNode.layer === "ability") {
      keepAbilityIds.add(targetNode.id);
    }
    if (sourceNode.layer === "ability" && targetNode.layer === "evidence") {
      keepAbilityIds.add(sourceNode.id);
    }
  }

  return nodes.filter((node) => node.layer !== "ability" || keepAbilityIds.has(node.id));
}

function buildLayout(nodes: GraphSnapshotNode[], width: number, height: number): Map<string, { x: number; y: number }> {
  const layout = new Map<string, { x: number; y: number }>();
  const usableWidth = Math.max(520, width - CANVAS_PADDING_X * 2);
  const usableHeight = Math.max(260, height - CANVAS_PADDING_TOP - CANVAS_PADDING_BOTTOM);
  const centerY = CANVAS_PADDING_TOP + usableHeight / 2;
  for (const [layerIndex, layer] of LAYER_ORDER.entries()) {
    const layerNodes = nodes.filter((node) => node.layer === layer).sort((a, b) => b.score - a.score);
    const step = layerNodes.length > 1 ? Math.min(70, usableHeight / (layerNodes.length - 1)) : 0;
    const startY = layerNodes.length > 1 ? centerY - ((layerNodes.length - 1) * step) / 2 : centerY;
    layerNodes.forEach((node, index) => {
      layout.set(node.id, {
        x: CANVAS_PADDING_X + (usableWidth / (LAYER_ORDER.length - 1)) * layerIndex,
        y: startY + step * index,
      });
    });
  }
  return layout;
}

function nodeSize(score: number): number {
  return 14 + Math.max(0.15, Math.min(1, score)) * 10;
}

function edgeLineWidth(ratio: number): number {
  const clamped = Math.max(0, Math.min(1, ratio));
  return Math.max(0.85, Math.min(5.2, 0.75 + Math.pow(clamped, 0.72) * 4.25));
}

function graphPointToPosition(point: ArrayLike<number>): NodePosition {
  return { x: Number(point[0]), y: Number(point[1]) };
}

function graphLabel(node: GraphSnapshotNode): string {
  return node.name;
}

function layerLabelLeft(index: number): string {
  const ratio = index / (LAYER_ORDER.length - 1);
  const offset = CANVAS_PADDING_X * (1 - ratio * 2);
  if (offset === 0) {
    return `${ratio * 100}%`;
  }
  return `calc(${ratio * 100}% ${offset > 0 ? "+" : "-"} ${Math.abs(offset)}px)`;
}

function formatDiagnosticValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.join("、") || "-";
  }
  if (typeof value === "number") {
    return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function diagnosticLabel(key: string): string {
  return DIAGNOSTIC_LABELS[key] || key;
}

function isGraphDestroyedError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("graph instance has been destroyed");
}

export function GraphPane({ flow, onNext }: { flow: ReturnType<typeof useRecommendationFlow>; onNext: () => void }) {
  const reducedMotion = useReducedMotionPreference();
  const graphHostRef = useRef<HTMLDivElement | null>(null);
  const graphInstanceRef = useRef<Graph | null>(null);
  const pendingGraphRenderRef = useRef<Promise<void> | null>(null);
  const selectNodeRef = useRef(flow.selectNode);
  const visibleNodeByIdRef = useRef<Map<string, GraphSnapshotNode>>(new Map());
  const customNodePositionsRef = useRef<Map<string, NodePosition>>(new Map());
  const [graphSize, setGraphSize] = useState({ width: 1120, height: 620 });
  const [revealIndex, setRevealIndex] = useState(LAYER_ORDER.length - 1);
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);
  const [scoreThreshold, setScoreThreshold] = useState(DEFAULT_SCORE_THRESHOLD);
  const snapshot = flow.recommendation?.propagation_snapshot;

  useEffect(() => {
    selectNodeRef.current = flow.selectNode;
  }, [flow.selectNode]);

  useEffect(() => {
    const host = graphHostRef.current;
    if (!host) {
      return;
    }
    const updateSize = () => {
      const rect = host.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setGraphSize({ width: rect.width, height: rect.height });
      }
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const host = graphHostRef.current;
    if (!host || graphInstanceRef.current) {
      return;
    }
    const graph = new Graph({
      container: host,
      width: graphSize.width,
      height: graphSize.height,
      autoResize: false,
      background: "transparent",
      animation: false,
      zoomRange: [0.65, 1.8],
      behaviors: [
        { type: "drag-canvas" },
        { type: "zoom-canvas" },
        {
          type: "drag-element",
          onFinish: (ids: string[]) => {
            for (const id of ids) {
              try {
                customNodePositionsRef.current.set(id, graphPointToPosition(graph.getElementPosition(id)));
              } catch {
                customNodePositionsRef.current.delete(id);
              }
            }
          },
        },
      ],
      node: { type: "circle" },
      edge: { type: "cubic-horizontal" },
    });
    graph.on(NodeEvent.CLICK, (event: IElementEvent) => {
      const id = String(event.target.id);
      const node = visibleNodeByIdRef.current.get(id);
      if (node) {
        setHighlightedNodeId((current) => (current === node.id ? null : node.id));
        selectNodeRef.current(node.id, node.layer);
      }
    });
    graphInstanceRef.current = graph;
    return () => {
      graphInstanceRef.current = null;
      const destroyGraph = () => {
        try {
          graph.destroy();
        } catch (error) {
          if (!isGraphDestroyedError(error)) {
            console.error(error);
          }
        }
      };
      const pendingRender = pendingGraphRenderRef.current;
      if (pendingRender) {
        void pendingRender.finally(destroyGraph);
        return;
      }
      destroyGraph();
    };
  }, [graphSize.height, graphSize.width]);

  useEffect(() => {
    if (!snapshot || reducedMotion) {
      setRevealIndex(LAYER_ORDER.length - 1);
      return;
    }

    setRevealIndex(0);
    const timer = window.setInterval(() => {
      setRevealIndex((current) => {
        if (current >= LAYER_ORDER.length - 1) {
          window.clearInterval(timer);
          return current;
        }
        return current + 1;
      });
    }, motionTimings.layerRevealStepMs);

    return () => window.clearInterval(timer);
  }, [flow.graphReplaySeed, reducedMotion, snapshot]);

  useEffect(() => {
    customNodePositionsRef.current.clear();
  }, [flow.graphReplaySeed, snapshot]);

  const nodeById = useMemo(() => new Map((snapshot?.nodes || []).map((node) => [node.id, node])), [snapshot]);
  const pinnedNodeRanks = useMemo(() => {
    const rankedIds = [...flow.cards.recommendations, ...flow.cards.nearMisses]
      .map((card) => card.job_id);
    return new Map(rankedIds.map((id, index) => [id, index]));
  }, [flow.cards.nearMisses, flow.cards.recommendations]);
  const allVisibleNodes = useMemo(
    () => (snapshot ? buildVisibleNodes(snapshot.nodes, pinnedNodeRanks) : []),
    [pinnedNodeRanks, snapshot],
  );
  const thresholdedNodes = useMemo(
    () => (snapshot ? applyScoreThreshold(allVisibleNodes, snapshot.edges, scoreThreshold) : []),
    [allVisibleNodes, scoreThreshold, snapshot],
  );
  const evidenceLinkedNodes = useMemo(
    () => (snapshot ? keepEvidenceLinkedAbilityNodes(thresholdedNodes, snapshot.edges) : []),
    [snapshot, thresholdedNodes],
  );
  const visibleNodes = useMemo(() => evidenceLinkedNodes.filter((node) => layerRank(node.layer) <= revealIndex), [evidenceLinkedNodes, revealIndex]);
  const layout = useMemo(() => buildLayout(visibleNodes, graphSize.width, graphSize.height), [graphSize.height, graphSize.width, visibleNodes]);
  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = (snapshot?.edges || []).filter((edge) => {
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);
    const sourceLayer = sourceNode ? layerRank(sourceNode.layer) : 0;
    const targetLayer = targetNode ? layerRank(targetNode.layer) : 0;
    return (
      visibleNodeIds.has(edge.source) &&
      visibleNodeIds.has(edge.target) &&
      sourceLayer <= revealIndex &&
      targetLayer <= revealIndex
    );
  });
  const maxVisibleEdgeValue = Math.max(...visibleEdges.map((edge) => edge.value), 0.001);
  const selectedNode = flow.selectedSnapshotNode && visibleNodeIds.has(flow.selectedSnapshotNode.id) ? flow.selectedSnapshotNode : visibleNodes[0] || null;
  const activeHighlightId = highlightedNodeId && visibleNodeIds.has(highlightedNodeId) ? highlightedNodeId : null;
  const highlightNodeIds = new Set<string>();
  if (activeHighlightId) {
    highlightNodeIds.add(activeHighlightId);
    for (const edge of visibleEdges) {
      if (edge.source === activeHighlightId || edge.target === activeHighlightId) {
        highlightNodeIds.add(edge.source);
        highlightNodeIds.add(edge.target);
      }
    }
  }
  const graphData: GraphData = {
    nodes: visibleNodes.map((node) => {
      const position = customNodePositionsRef.current.get(node.id) || layout.get(node.id) || { x: 0, y: 0 };
      const selected = selectedNode?.id === node.id;
      const focused = highlightNodeIds.has(node.id);
      const dimmed = Boolean(activeHighlightId) && !focused;
      const size = nodeSize(node.score);
      const evidenceLabel = node.layer === "evidence";
      return {
        id: node.id,
        type: "circle",
        data: {
          layer: node.layer,
        },
        style: {
          x: position.x,
          y: position.y,
          size: focused ? size + 5 : selected ? size + 3 : size,
          fill: NODE_COLORS[node.layer] || "oklch(0.78 0.02 220)",
          fillOpacity: dimmed ? 0.34 : 1,
          stroke: selected || focused ? "oklch(0.24 0.13 252)" : "oklch(0.58 0.035 220)",
          strokeOpacity: dimmed ? 0.36 : 1,
          lineWidth: selected ? 2.8 : focused ? 1.9 : 0.9,
          cursor: "pointer",
          labelText: graphLabel(node),
          labelPlacement: evidenceLabel ? "left" : "right",
          labelOffsetX: evidenceLabel ? -9 : 9,
          labelFill: "oklch(0.17 0.03 220)",
          labelFillOpacity: dimmed ? 0.42 : 1,
          labelFontFamily: "var(--sans)",
          labelFontSize: 15,
          labelFontWeight: selected || focused ? 760 : 680,
          labelTextAlign: evidenceLabel ? "right" : "left",
          labelMaxWidth: evidenceLabel ? 170 : 154,
          labelTextBaseline: "middle",
          labelWordWrap: true,
          labelBackground: true,
          labelBackgroundFill: dimmed ? "oklch(1 0 0 / 0.34)" : "oklch(1 0 0 / 0.82)",
          labelBackgroundStroke: dimmed ? "oklch(0.84 0.018 220 / 0.34)" : "oklch(0.84 0.018 220)",
          labelBackgroundLineWidth: 0.7,
          labelBackgroundRadius: 0,
          labelPadding: [3, 6],
          port: true,
          ports: [
            { key: "left", placement: [0, 0.5], r: 1, fill: "transparent", stroke: "transparent" },
            { key: "right", placement: [1, 0.5], r: 1, fill: "transparent", stroke: "transparent" },
          ],
          zIndex: selected || focused ? 36 : dimmed ? 10 : 24,
        },
      } satisfies NodeData;
    }),
    edges: visibleEdges.map((edge, index) => {
      const heatRatio = edge.value / maxVisibleEdgeValue;
      const focused = activeHighlightId ? edge.source === activeHighlightId || edge.target === activeHighlightId : false;
      const dimmed = Boolean(activeHighlightId) && !focused;
      return {
        id: `${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        type: "cubic-horizontal",
        style: {
          sourcePort: "right",
          targetPort: "left",
          stroke: RELATION_COLORS[edge.relation] || "oklch(0.55 0.03 220)",
          lineWidth: focused ? Math.max(3.2, edgeLineWidth(heatRatio) + 1.4) : edgeLineWidth(heatRatio),
          opacity: focused ? 0.86 : dimmed ? 0.045 : Math.max(0.18, Math.min(0.58, 0.16 + heatRatio * 0.34)),
          lineDash: undefined,
          zIndex: focused ? 8 : 1,
        },
      } satisfies EdgeData;
    }),
  };
  const visibleNodeById = useMemo(() => new Map(visibleNodes.map((node) => [node.id, node])), [visibleNodes]);

  visibleNodeByIdRef.current = visibleNodeById;

  useEffect(() => {
    if (highlightedNodeId && !visibleNodeById.has(highlightedNodeId)) {
      setHighlightedNodeId(null);
    }
  }, [highlightedNodeId, visibleNodeById]);

  useEffect(() => {
    const graph = graphInstanceRef.current;
    if (!graph) {
      return;
    }
    let cancelled = false;
    try {
      graph.resize(graphSize.width, graphSize.height);
      graph.setData(graphData);
      const trackedRender = Promise.resolve(graph.render())
        .catch((error: unknown) => {
          if (!isGraphDestroyedError(error) && !cancelled && graphInstanceRef.current === graph) {
            console.error(error);
          }
        })
        .finally(() => {
          if (pendingGraphRenderRef.current === trackedRender) {
            pendingGraphRenderRef.current = null;
          }
        });
      pendingGraphRenderRef.current = trackedRender;
    } catch (error) {
      if (!isGraphDestroyedError(error) && !cancelled && graphInstanceRef.current === graph) {
        console.error(error);
      }
    }
    return () => {
      cancelled = true;
    };
  }, [graphData, graphSize.height, graphSize.width]);

  if (!snapshot) {
    return (
      <section className="pane pane-graph">
        <div className="pane-header pane-header--graph">
          <div>
            <p className="section-kicker">Graph Stage</p>
            <h2>图谱传播主舞台</h2>
          </div>
        </div>
        <div className="graph-empty-state">
          <div className="empty-slot compact">先填写画像并生成推荐，再开始图谱传播演示。</div>
        </div>
      </section>
    );
  }

  return (
    <section className="pane pane-graph has-ambient-flow">
      <div className="pane-header pane-header--graph">
          <div>
            <p className="section-kicker">Graph Stage</p>
            <h2>知识图谱传播演示</h2>
        </div>
        <div className="header-inline-actions">
          <button className="ghost-button header-peer-button" type="button" onClick={flow.replayGraph}>
            重播
          </button>
          <button className="primary-button next-step-button" type="button" onClick={onNext}>
            下一步：看结果
          </button>
        </div>
      </div>

      <div
        className="graph-stage-meta"
        style={{ "--graph-layer-side-pad": `${CANVAS_PADDING_X}px` } as CSSProperties & Record<"--graph-layer-side-pad", string>}
      >
        <div className="layer-ladder" aria-label="graph propagation layers">
          {LAYER_ORDER.map((layer, index) => {
            const state = index < revealIndex ? "is-complete" : index === revealIndex ? "is-active" : "is-upcoming";
            return (
              <div
                key={layer}
                className={`layer-pill layer-pill--${index} ${state}`}
                style={{ left: layerLabelLeft(index) }}
              >
                <span>{LAYER_LABELS[layer]}</span>
              </div>
            );
          })}
        </div>
        <label className="score-threshold-control">
          <span>阈值</span>
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              value={Math.round(scoreThreshold * 100)}
              onChange={(event) => setScoreThreshold(Number(event.currentTarget.value) / 100)}
              aria-label="图谱节点分数阈值"
              aria-valuetext={`${Math.round(scoreThreshold * 100)}%`}
            />
          <strong>{Math.round(scoreThreshold * 100)}%</strong>
        </label>
      </div>

      <div className="graph-stage-grid">
        <div className="graph-frame">
          <div className="graph-overlay">
            <div className="graph-overlay-card graph-legend-card">
              <p className="micro-label">图例</p>
              <div className="legend-grid" aria-label="图谱图例">
                <span><i className="legend-line legend-line--supports" />支持</span>
                <span><i className="legend-line legend-line--requires" />要求</span>
                <span><i className="legend-line legend-line--prefers" />偏好</span>
                <span><i className="legend-line legend-line--inhibits" />抑制</span>
              </div>
            </div>
          </div>
          <div ref={graphHostRef} className="graph-canvas graph-g6-canvas" aria-label="knowledge graph propagation" />
        </div>

        <section className="section-card graph-detail-card">
          <div className="section-head">
            <div>
              <h3>节点详情</h3>
            </div>
          </div>
          {selectedNode ? (
            <div className="detail-stack">
              <div className="detail-topline graph-node-summary">
                <p className="micro-label">{LAYER_LABELS[selectedNode.layer] || selectedNode.layer}</p>
                <strong>{selectedNode.name}</strong>
                <p className="detail-copy">{selectedNode.description}</p>
              </div>
              <div className="mini-panel graph-score-source-panel">
                <h4>分数来源</h4>
                <ul className="list-stack compact-list">
                  {DETAIL_DIAGNOSTIC_KEYS.map((key) => (
                    <li key={key}>
                      <span>{diagnosticLabel(key)}</span>
                      <strong>{formatDiagnosticValue(selectedNode.diagnostics?.[key] ?? 0)}</strong>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mini-panel graph-source-profile-panel">
                <h4>来源画像</h4>
                <SourceProfileList
                  sources={selectedNode.metadata.source_refs || []}
                  emptyText="这个节点当前没有外部来源锚点。"
                  compact
                />
              </div>
            </div>
          ) : (
            <div className="empty-slot compact">当前还没有可查看的节点详情。</div>
          )}
        </section>
      </div>
    </section>
  );
}
