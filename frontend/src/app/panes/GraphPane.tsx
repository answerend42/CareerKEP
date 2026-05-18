import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Graph, NodeEvent } from '@antv/g6';
import type { EdgeData, GraphData, IElementEvent, NodeData } from '@antv/g6';
import type { RecommendationResponse, StageEdge, StageNode } from '../types';

interface GraphPaneProps {
  snapshot: RecommendationResponse['propagationSnapshot'];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onNext: () => void;
}

type GraphNode = StageNode & {
  layerLabel: string;
};

type NodePosition = {
  x: number;
  y: number;
};

const LAYER_ORDER: StageNode['layer'][] = ['evidence', 'ability', 'composite', 'direction', 'role'];

const NODE_COLORS: Record<StageNode['layer'], string> = {
  evidence: 'oklch(0.79 0.065 252)',
  ability: 'oklch(0.83 0.055 205)',
  composite: 'oklch(0.86 0.06 155)',
  direction: 'oklch(0.86 0.075 84)',
  role: 'oklch(0.78 0.08 31)'
};

const RELATION_COLORS: Record<string, string> = {
  supports: 'oklch(0.58 0.13 205)',
  requires: 'oklch(0.67 0.15 80)',
  inhibits: 'oklch(0.58 0.18 31)',
  evidences: 'oklch(0.5 0.14 252)',
  prefers: 'oklch(0.57 0.12 155)'
};

const CANVAS_PADDING_X = 210;
const CANVAS_PADDING_TOP = 104;
const CANVAS_PADDING_BOTTOM = 54;

const LAYER_INDEX = new Map(LAYER_ORDER.map((layer, index) => [layer, index]));

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const formatPercent = (value: number) => `${Math.round(value * 100)}%`;

const layerRank = (layer: string): number => LAYER_INDEX.get(layer as StageNode['layer']) ?? LAYER_ORDER.length - 1;

const splitDetail = (detail: string) =>
  Object.fromEntries(
    detail
      .split('/')
      .map((part) => part.trim())
      .map((part) => {
        const [key, value] = part.split(/\s+/);
        return [key || 'score', value || part];
      })
  );

const nodeSize = (score: number): number => 14 + clamp(score, 0.15, 1) * 10;

const edgeLineWidth = (ratio: number): number => {
  const clamped = clamp(ratio, 0, 1);
  return clamp(0.75 + Math.pow(clamped, 0.72) * 4.25, 0.85, 5.2);
};

const isDestroyedGraphError = (error: unknown): boolean => {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes('graph instance has been destroyed');
};

const graphPointToPosition = (point: ArrayLike<number>): NodePosition => ({
  x: Number(point[0]),
  y: Number(point[1])
});

const layerLabelLeft = (index: number): string => {
  const ratio = index / Math.max(LAYER_ORDER.length - 1, 1);
  const offset = CANVAS_PADDING_X * (1 - ratio * 2);
  if (offset === 0) {
    return `${ratio * 100}%`;
  }
  return `calc(${ratio * 100}% ${offset > 0 ? '+' : '-'} ${Math.abs(offset)}px)`;
};

function buildGraphNodes(snapshot: RecommendationResponse['propagationSnapshot']): GraphNode[] {
  const layerLabelMap = new Map(snapshot.layers.map((layer) => [layer.layer, layer.label]));
  return LAYER_ORDER.flatMap((layer) => {
    const nodes = snapshot.layers.find((item) => item.layer === layer)?.nodes ?? [];
    return [...nodes]
      .sort((a, b) => b.score - a.score || a.label.localeCompare(b.label) || a.id.localeCompare(b.id))
      .map((node) => ({
        ...node,
        layerLabel: layerLabelMap.get(layer) ?? layer
      }));
  });
}

function buildLayout(nodes: GraphNode[], width: number, height: number): Map<string, NodePosition> {
  const layout = new Map<string, NodePosition>();
  const usableWidth = Math.max(520, width - CANVAS_PADDING_X * 2);
  const usableHeight = Math.max(260, height - CANVAS_PADDING_TOP - CANVAS_PADDING_BOTTOM);
  const centerY = CANVAS_PADDING_TOP + usableHeight / 2;

  for (const [layerIndex, layer] of LAYER_ORDER.entries()) {
    const layerNodes = nodes.filter((node) => node.layer === layer).sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
    const step = layerNodes.length > 1 ? Math.min(72, usableHeight / (layerNodes.length - 1)) : 0;
    const startY = layerNodes.length > 1 ? centerY - ((layerNodes.length - 1) * step) / 2 : centerY;
    layerNodes.forEach((node, index) => {
      layout.set(node.id, {
        x: CANVAS_PADDING_X + (usableWidth / Math.max(LAYER_ORDER.length - 1, 1)) * layerIndex,
        y: startY + step * index
      });
    });
  }

  return layout;
}

export function GraphPane({ snapshot, selectedNodeId, onSelectNode, onNext }: GraphPaneProps) {
  const graphHostRef = useRef<HTMLDivElement | null>(null);
  const graphInstanceRef = useRef<Graph | null>(null);
  const graphAliveRef = useRef(false);
  const renderPromiseRef = useRef<Promise<void> | null>(null);
  const visibleNodeByIdRef = useRef<Map<string, GraphNode>>(new Map());
  const customNodePositionsRef = useRef<Map<string, NodePosition>>(new Map());
  const onSelectNodeRef = useRef(onSelectNode);
  const [graphSize, setGraphSize] = useState({ width: 1120, height: 620 });
  const [replaySeed, setReplaySeed] = useState(0);
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(selectedNodeId);

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode;
  }, [onSelectNode]);

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

    const rect = host.getBoundingClientRect();
    const graph = new Graph({
      container: host,
      width: rect.width || graphSize.width,
      height: rect.height || graphSize.height,
      autoResize: false,
      background: 'transparent',
      animation: false,
      zoomRange: [0.65, 1.85],
      behaviors: [
        { type: 'drag-canvas' },
        { type: 'zoom-canvas' },
        {
          type: 'drag-element',
          onFinish: (ids: string[]) => {
            for (const id of ids) {
              try {
                customNodePositionsRef.current.set(id, graphPointToPosition(graph.getElementPosition(id)));
              } catch {
                customNodePositionsRef.current.delete(id);
              }
            }
          }
        }
      ],
      node: { type: 'circle' },
      edge: { type: 'cubic-horizontal' }
    });

    graph.on(NodeEvent.CLICK, (event: IElementEvent) => {
      const id = String(event.target.id);
      const node = visibleNodeByIdRef.current.get(id);
      if (node) {
        setHighlightedNodeId(node.id);
        onSelectNodeRef.current(node.id);
      }
    });

    graphInstanceRef.current = graph;
    graphAliveRef.current = true;
    return () => {
      const graphToDestroy = graph;
      const pendingRender = renderPromiseRef.current;
      graphAliveRef.current = false;
      graphInstanceRef.current = null;
      renderPromiseRef.current = null;
      const destroyGraph = () => {
        graphToDestroy.destroy();
      };
      if (pendingRender) {
        void pendingRender.finally(() => {
          window.setTimeout(destroyGraph, 0);
        });
        return;
      }
      window.setTimeout(destroyGraph, 0);
    };
  }, []);

  useEffect(() => {
    customNodePositionsRef.current.clear();
  }, [snapshot]);

  useEffect(() => {
    setHighlightedNodeId(selectedNodeId);
  }, [selectedNodeId]);

  const graphNodes = useMemo(() => buildGraphNodes(snapshot), [snapshot]);
  const nodeById = useMemo(() => new Map(graphNodes.map((node) => [node.id, node])), [graphNodes]);
  const layout = useMemo(() => buildLayout(graphNodes, graphSize.width, graphSize.height), [graphNodes, graphSize.height, graphSize.width]);
  const visibleEdges = useMemo(
    () =>
      snapshot.edges.filter((edge) => {
        const source = nodeById.get(edge.source);
        const target = nodeById.get(edge.target);
        return Boolean(source && target && layerRank(source.layer) <= layerRank(target.layer));
      }),
    [nodeById, snapshot.edges]
  );
  const selectedNode = (highlightedNodeId ? nodeById.get(highlightedNodeId) : null) ?? (selectedNodeId ? nodeById.get(selectedNodeId) : null) ?? graphNodes[0] ?? null;
  const activeHighlightId = selectedNode?.id ?? null;
  const highlightNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (!activeHighlightId) {
      return ids;
    }
    ids.add(activeHighlightId);
    for (const edge of visibleEdges) {
      if (edge.source === activeHighlightId || edge.target === activeHighlightId) {
        ids.add(edge.source);
        ids.add(edge.target);
      }
    }
    return ids;
  }, [activeHighlightId, visibleEdges]);

  const graphData = useMemo<GraphData>(() => {
    const maxVisibleEdgeValue = Math.max(...visibleEdges.map((edge) => edge.contribution), 0.001);
    return {
      nodes: graphNodes.map((node) => {
        const position = customNodePositionsRef.current.get(node.id) || layout.get(node.id) || { x: 0, y: 0 };
        const selected = selectedNode?.id === node.id;
        const focused = highlightNodeIds.has(node.id);
        const dimmed = Boolean(activeHighlightId) && !focused;
        const size = nodeSize(node.score);
        const evidenceLabel = node.layer === 'evidence';
        return {
          id: node.id,
          type: 'circle',
          data: {
            layer: node.layer,
            label: node.label
          },
          style: {
            x: position.x,
            y: position.y,
            size: focused ? size + 5 : selected ? size + 3 : size,
            fill: NODE_COLORS[node.layer],
            fillOpacity: dimmed ? 0.34 : 1,
            stroke: selected || focused ? 'oklch(0.24 0.13 252)' : 'oklch(0.58 0.035 220)',
            strokeOpacity: dimmed ? 0.36 : 1,
            lineWidth: selected ? 2.8 : focused ? 1.9 : 0.9,
            cursor: 'grab',
            labelText: node.label,
            labelPlacement: evidenceLabel ? 'left' : 'right',
            labelOffsetX: evidenceLabel ? -9 : 9,
            labelFill: 'oklch(0.17 0.03 220)',
            labelFillOpacity: dimmed ? 0.42 : 1,
            labelFontFamily: 'var(--sans)',
            labelFontSize: 15,
            labelFontWeight: selected || focused ? 760 : 680,
            labelTextAlign: evidenceLabel ? 'right' : 'left',
            labelMaxWidth: evidenceLabel ? 170 : 154,
            labelTextBaseline: 'middle',
            labelWordWrap: true,
            labelBackground: true,
            labelBackgroundFill: dimmed ? 'oklch(1 0 0 / 0.34)' : 'oklch(1 0 0 / 0.82)',
            labelBackgroundStroke: dimmed ? 'oklch(0.84 0.018 220 / 0.34)' : 'oklch(0.84 0.018 220)',
            labelBackgroundLineWidth: 0.7,
            labelBackgroundRadius: 0,
            labelPadding: [3, 6],
            port: true,
            ports: [
              { key: 'left', placement: [0, 0.5], r: 1, fill: 'transparent', stroke: 'transparent' },
              { key: 'right', placement: [1, 0.5], r: 1, fill: 'transparent', stroke: 'transparent' }
            ],
            zIndex: selected || focused ? 36 : dimmed ? 10 : 24
          }
        } satisfies NodeData;
      }),
      edges: visibleEdges.map((edge, index) => {
        const heatRatio = edge.contribution / maxVisibleEdgeValue;
        const focused = activeHighlightId ? edge.source === activeHighlightId || edge.target === activeHighlightId : false;
        const dimmed = Boolean(activeHighlightId) && !focused;
        return {
          id: `${edge.source}-${edge.target}-${edge.relation}-${index}`,
          source: edge.source,
          target: edge.target,
          type: 'cubic-horizontal',
          style: {
            sourcePort: 'right',
            targetPort: 'left',
            stroke: RELATION_COLORS[edge.relation] || 'oklch(0.55 0.03 220)',
            lineWidth: focused ? Math.max(3.2, edgeLineWidth(heatRatio) + 1.4) : edgeLineWidth(heatRatio),
            opacity: focused ? 0.86 : dimmed ? 0.045 : Math.max(0.18, Math.min(0.58, 0.16 + heatRatio * 0.34)),
            zIndex: focused ? 8 : 1
          }
        } satisfies EdgeData;
      })
    };
  }, [activeHighlightId, graphNodes, highlightNodeIds, layout, selectedNode?.id, visibleEdges]);

  const visibleNodeById = useMemo(() => new Map(graphNodes.map((node) => [node.id, node])), [graphNodes]);
  visibleNodeByIdRef.current = visibleNodeById;

  useEffect(() => {
    if (highlightedNodeId && !visibleNodeById.has(highlightedNodeId)) {
      setHighlightedNodeId(null);
    }
  }, [highlightedNodeId, visibleNodeById]);

  useEffect(() => {
    const graph = graphInstanceRef.current;
    if (!graph || !graphAliveRef.current) {
      return;
    }
    graph.resize(graphSize.width, graphSize.height);
    graph.setData(graphData);
    const renderPromise = graph.render();
    renderPromiseRef.current = renderPromise;
    void renderPromise.catch((error: unknown) => {
      if (graphAliveRef.current && !isDestroyedGraphError(error)) {
        console.error(error);
      }
    }).finally(() => {
      if (renderPromiseRef.current === renderPromise) {
        renderPromiseRef.current = null;
      }
    });
  }, [graphData, graphSize.height, graphSize.width]);

  const incomingEdges = selectedNode ? visibleEdges.filter((edge) => edge.target === selectedNode.id) : [];
  const outgoingEdges = selectedNode ? visibleEdges.filter((edge) => edge.source === selectedNode.id) : [];
  const selectedDiagnostics = selectedNode ? splitDetail(selectedNode.detail) : {};
  const resetLayout = () => {
    customNodePositionsRef.current.clear();
    setReplaySeed((value) => value + 1);
  };

  return (
    <div className="pane-stack graph-workflow">
      <div className="pane-header pane-header--graph">
        <div>
          <h2>知识图谱传播演示</h2>
        </div>
        <div className="header-inline-actions">
          <button className="ghost-button header-peer-button" type="button" onClick={resetLayout}>
            重置布局
          </button>
          <button className="primary-button next-step-button" type="button" onClick={onNext}>
            下一步：看结果
          </button>
        </div>
      </div>

      <div
        className="graph-stage-meta"
        style={{ '--graph-layer-side-pad': `${CANVAS_PADDING_X}px` } as CSSProperties & Record<'--graph-layer-side-pad', string>}
      >
        <div className="layer-ladder" aria-label="图谱层级">
          {snapshot.layers.map((layer, index) => (
            <div
              key={layer.layer}
              className={`layer-pill layer-pill--${index} is-complete`}
              style={{ left: layerLabelLeft(index) }}
            >
              <span>{layer.label}</span>
            </div>
          ))}
        </div>
        <div className="score-threshold-control" aria-label="图谱统计">
          <span>节点 / 边</span>
          <strong>
            {graphNodes.length} / {visibleEdges.length}
          </strong>
        </div>
      </div>

      <div className="graph-stage-grid">
        <div className={`graph-frame ${selectedNode ? 'has-selected-path' : ''}`}>
          <div className="graph-overlay">
            <div className="graph-overlay-card graph-legend-card">
              <p className="micro-label">图例</p>
              <div className="legend-grid" aria-label="图谱图例">
                <span><i className="legend-line legend-line--supports" />支持</span>
                <span><i className="legend-line legend-line--requires" />要求</span>
                <span><i className="legend-line legend-line--inhibits" />抑制</span>
                <span><i className="legend-line legend-line--evidences" />证据</span>
                <span><i className="legend-line legend-line--prefers" />偏好</span>
              </div>
            </div>
          </div>
          <div ref={graphHostRef} className="graph-canvas graph-g6-canvas" aria-label="知识图谱传播路径" />
        </div>

        <section className="section-card graph-detail-card">
          <div className="section-head">
            <div>
              <h3>节点详情</h3>
              <p>{selectedNode ? selectedNode.id : '未选择节点'}</p>
            </div>
          </div>
          {selectedNode ? (
            <div className="detail-stack">
              <div className="detail-topline graph-node-summary">
                <p className="micro-label">{selectedNode.layerLabel}</p>
                <strong>{selectedNode.label}</strong>
                <p className="detail-copy">{selectedNode.detail}</p>
                <span className="score-badge">{formatPercent(selectedNode.score)}</span>
              </div>
              <div className="mini-panel graph-score-source-panel">
                <h4>分数来源</h4>
                <ul className="list-stack compact-list">
                  <li>
                    <span>support</span>
                    <strong>{selectedDiagnostics.support ?? '-'}</strong>
                  </li>
                  <li>
                    <span>require</span>
                    <strong>{selectedDiagnostics.require ?? '-'}</strong>
                  </li>
                  <li>
                    <span>入边</span>
                    <strong>{incomingEdges.length}</strong>
                  </li>
                  <li>
                    <span>出边</span>
                    <strong>{outgoingEdges.length}</strong>
                  </li>
                </ul>
              </div>
              <div className="mini-panel">
                <h4>入边</h4>
                <div className="edge-mini-list">
                  {incomingEdges.length ? (
                    incomingEdges.map((edge) => (
                      <button key={`${edge.source}-${edge.target}`} className="edge-row edge-row-button" type="button" onClick={() => onSelectNode(edge.source)}>
                        <span>{nodeById.get(edge.source)?.label ?? edge.source}</span>
                        <strong>{edge.relation}</strong>
                        <em>{edge.contribution.toFixed(2)}</em>
                      </button>
                    ))
                  ) : null}
                </div>
              </div>
              <div className="mini-panel">
                <h4>出边</h4>
                <div className="edge-mini-list">
                  {outgoingEdges.length ? (
                    outgoingEdges.map((edge) => (
                      <button key={`${edge.source}-${edge.target}`} className="edge-row edge-row-button" type="button" onClick={() => onSelectNode(edge.target)}>
                        <span>{nodeById.get(edge.target)?.label ?? edge.target}</span>
                        <strong>{edge.relation}</strong>
                        <em>{edge.contribution.toFixed(2)}</em>
                      </button>
                    ))
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
