import type { RecommendationResponse, RobustnessReport, StageEdge, StageNode } from '../types';

interface ResultPaneProps {
  response: RecommendationResponse;
  robustnessReport: RobustnessReport;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onExportSnapshot: () => void;
  onCopySnapshot: () => void;
}

const formatPercent = (value: number) => `${Math.round(value * 100)}%`;
const formatDelta = (value: number) => {
  const rounded = Math.round(value * 100);
  return rounded > 0 ? `+${rounded}%` : `${rounded}%`;
};

const flattenNodes = (response: RecommendationResponse): StageNode[] =>
  response.propagationSnapshot.layers.flatMap((layer) => layer.nodes);

const buildOutgoingMap = (edges: StageEdge[]): Map<string, StageEdge[]> => {
  const map = new Map<string, StageEdge[]>();

  for (const edge of edges) {
    const bucket = map.get(edge.source) ?? [];
    bucket.push(edge);
    map.set(edge.source, bucket);
  }

  return map;
};

const collectReachableNodes = (
  startNodeId: string | null,
  nodes: StageNode[],
  edges: StageEdge[]
): StageNode[] => {
  if (!startNodeId) {
    return [];
  }

  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const outgoingMap = buildOutgoingMap(edges);
  const visited = new Set<string>([startNodeId]);
  const queue = [startNodeId];
  const reachable: StageNode[] = [];

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) {
      continue;
    }

    for (const edge of outgoingMap.get(current) ?? []) {
      if (visited.has(edge.target)) {
        continue;
      }

      visited.add(edge.target);
      queue.push(edge.target);

      const node = nodeMap.get(edge.target);
      if (node) {
        reachable.push(node);
      }
    }
  }

  return reachable;
};

export function ResultPane({
  response,
  robustnessReport,
  selectedNodeId,
  onSelectNode,
  onExportSnapshot,
  onCopySnapshot
}: ResultPaneProps) {
  const allNodes = flattenNodes(response);
  const selectedNode = allNodes.find((node) => node.id === selectedNodeId) ?? null;
  const incomingEdges = selectedNodeId
    ? response.propagationSnapshot.edges.filter((edge) => edge.target === selectedNodeId)
    : [];
  const outgoingEdges = selectedNodeId
    ? response.propagationSnapshot.edges.filter((edge) => edge.source === selectedNodeId)
    : [];
  const reachableNodes = collectReachableNodes(selectedNodeId, allNodes, response.propagationSnapshot.edges);
  const reachableRoles = reachableNodes.filter((node) => node.layer === 'role');

  const selectedLayerLabel =
    response.propagationSnapshot.layers.find((layer) => layer.nodes.some((node) => node.id === selectedNodeId))?.label ?? '未选择';
  const selectableResults = response.recommendations.length
    ? response.recommendations
    : response.nearMissRoles.length
      ? response.nearMissRoles
      : [];
  const activeResult = selectableResults.find((item) => item.nodeId === selectedNodeId) ?? selectableResults[0] ?? null;

  return (
    <div className="pane-stack result-workflow">
      <div className="result-browser">
        <div className="result-browser-head">
          <h3>结果解释</h3>
          <label className="field-block result-picker result-select-field">
            <select
              className="editor-select result-select-control"
              value={activeResult?.nodeId ?? ''}
              onChange={(event) => onSelectNode(event.target.value)}
            >
              {selectableResults.map((item) => (
                <option key={item.nodeId} value={item.nodeId}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {activeResult ? <strong className="result-degree">推荐分 {formatPercent(activeResult.score)}</strong> : null}
        </div>

        <section className="section-card detail-panel result-reveal">
          <div className="section-head result-detail-head">
            <div>
              <h3>{activeResult?.label ?? ''}</h3>
            </div>
          </div>

          {activeResult ? (
            <ol className="path-cluster result-path-list">
              <li className="result-path-row">
                <span className="score-badge path-score-badge">{formatPercent(activeResult.score)}</span>
                <div className="path-track">
                  {(activeResult.path.length ? activeResult.path : [activeResult.label]).map((label, labelIndex) => (
                    <div key={`${activeResult.nodeId}-${label}-${labelIndex}`} className="path-node">
                      <span>{label}</span>
                      {labelIndex < activeResult.path.length - 1 ? <i>→</i> : null}
                    </div>
                  ))}
                </div>
              </li>
            </ol>
          ) : null}

          <div className="detail-grid">
            <div className="mini-panel">
              <h4>目标岗位分析</h4>
              <div className="tag-row">
                {response.targetRoleAnalysis.strengths.map((item) => (
                  <span key={item} className="soft-chip accent-chip">
                    {item}
                  </span>
                ))}
                {response.targetRoleAnalysis.gaps.map((item) => (
                  <span key={item} className="soft-chip warning-chip">
                    {item}
                  </span>
                ))}
              </div>
            </div>
            <div className="mini-panel">
              <h4>图谱锚点</h4>
              {selectedNode ? (
                <ul className="list-stack compact-list">
                  <li>
                    <span>节点</span>
                    <strong>{selectedNode.label}</strong>
                  </li>
                  <li>
                    <span>层级</span>
                    <strong>{selectedLayerLabel}</strong>
                  </li>
                  <li>
                    <span>关联边</span>
                    <strong>{incomingEdges.length} 入 / {outgoingEdges.length} 出</strong>
                  </li>
                  <li>
                    <span>可达岗位</span>
                    <strong>{reachableRoles.length} 个</strong>
                  </li>
                </ul>
              ) : null}
            </div>
          </div>

          <div className="detail-grid">
            <div className="mini-panel">
              <h4>正式推荐</h4>
              <div className="result-card-list">
                {response.recommendations.map((item) => (
                  <button
                    key={item.nodeId}
                    type="button"
                    className={`result-card result-card-button ${item.nodeId === selectedNodeId ? 'is-selected' : ''}`}
                    onClick={() => onSelectNode(item.nodeId)}
                  >
                    <div className="node-row">
                      <strong>{item.label}</strong>
                      <span>{formatPercent(item.score)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
            <div className="mini-panel">
              <h4>Near Miss / Bridge</h4>
              <div className="result-card-list">
                {response.nearMissRoles.map((item) => (
                  <button key={item.nodeId} type="button" className="result-card result-card-button" onClick={() => onSelectNode(item.nodeId)}>
                    <div className="node-row">
                      <strong>{item.label}</strong>
                      <span>{formatPercent(item.score)}</span>
                    </div>
                    <div className="tag-row">
                      {item.missing.map((missingItem) => (
                        <span key={missingItem} className="soft-chip warning-chip">{missingItem}</span>
                      ))}
                    </div>
                  </button>
                ))}
                {response.bridgeRecommendations.map((item) => (
                  <button key={item.nodeId} type="button" className="result-card result-card-button" onClick={() => onSelectNode(item.nodeId)}>
                    <div className="node-row">
                      <strong>{item.label}</strong>
                      <span>{formatPercent(item.score)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>
      </div>

      <section className="section-card robustness-card">
        <div className="section-head">
          <h3>鲁棒性测试</h3>
          <div className="section-actions">
            <span>{formatPercent(robustnessReport.averageTopScore)}</span>
            <button className="button-chip" type="button" onClick={onExportSnapshot}>
              导出快照
            </button>
            <button className="button-chip" type="button" onClick={onCopySnapshot}>
              复制快照
            </button>
          </div>
        </div>
        <div className="result-summary-row">
          <div className="result-summary-card">
            <span>平均变化</span>
            <strong className={robustnessReport.averageDelta >= 0 ? 'summary-positive' : 'summary-negative'}>
              {formatDelta(robustnessReport.averageDelta)}
            </strong>
          </div>
          <div className="result-summary-card">
            <span>改善场景</span>
            <strong>{robustnessReport.improvedCount} 个</strong>
          </div>
          <div className="result-summary-card">
            <span>脆弱场景</span>
            <strong>{robustnessReport.fragileCount} 个</strong>
          </div>
        </div>
        <div className="result-summary-row">
          <div className="result-summary-card">
            <span>最佳提升</span>
            <strong>{robustnessReport.bestImprovementLabel}</strong>
            <span className="summary-note-inline">{formatDelta(robustnessReport.bestImprovementDelta)}</span>
          </div>
          <div className="result-summary-card">
            <span>最差回落</span>
            <strong>{robustnessReport.worstRegressionLabel}</strong>
            <span className="summary-note-inline">{formatDelta(robustnessReport.worstRegressionDelta)}</span>
          </div>
          <div className="result-summary-card">
            <span>改善率</span>
            <strong>{formatPercent(robustnessReport.cases.length ? robustnessReport.improvedCount / robustnessReport.cases.length : 0)}</strong>
          </div>
        </div>
        <div className="result-list compact">
          {robustnessReport.cases.map((item) => (
            <article key={item.id} className="result-card">
              <div className="node-row">
                <strong>{item.label}</strong>
                <span>{formatPercent(item.topScore)}</span>
              </div>
              <div className="tag-row">
                <span className="soft-chip">基线 {formatPercent(item.baselineTopScore)}</span>
                <span className="soft-chip">变化 {formatDelta(item.scoreDelta)}</span>
                <span className="soft-chip">推荐 {item.recommendationCount}</span>
                <span className="soft-chip">near miss {item.nearMissCount}</span>
                <span className="soft-chip">覆盖率 {formatPercent(item.coverage)}</span>
                <span className={`soft-chip ${item.scoreDelta >= 0 ? 'accent-chip' : 'warning-chip'}`}>
                  {item.scoreDelta >= 0 ? '调参提升' : '调参回落'}
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="section-card trace-panel">
        <div className="section-head">
          <h3>输入追踪</h3>
          <span>{response.inputTrace.resolvedTargetRole}</span>
        </div>
        <div className="trace-metrics">
          <div className="trace-metric">
            <strong>{response.inputTrace.signalTrace.clauses.length}</strong>
            <span>句子片段</span>
          </div>
          <div className="trace-metric">
            <strong>{response.inputTrace.signalTrace.matchedSignals.length}</strong>
            <span>命中信号</span>
          </div>
          <div className="trace-metric">
            <strong>{response.inputTrace.signalTrace.negatedSignals.length}</strong>
            <span>否定信号</span>
          </div>
        </div>
        <div className="trace-summary compact">
          <div className="trace-box">
            <span>图谱节点</span>
            <strong>{response.graphSnapshot.nodeCount} 个</strong>
          </div>
          <div className="trace-box">
            <span>图谱边</span>
            <strong>{response.graphSnapshot.edgeCount} 条</strong>
          </div>
          <div className="trace-box">
            <span>目标覆盖</span>
            <strong>{formatPercent(response.targetRoleAnalysis.coverage)}</strong>
          </div>
        </div>
      </section>
    </div>
  );
}
