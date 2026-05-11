import type { RecommendationResponse, RobustnessReport, RunStatus, StageEdge, StageNode } from '../types';

interface ResultPaneProps {
  response: RecommendationResponse;
  activeStep: string;
  robustnessReport: RobustnessReport;
  runStatus: RunStatus;
  selectedNodeId: string | null;
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
  activeStep,
  robustnessReport,
  runStatus,
  selectedNodeId,
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

  return (
    <div className="pane-stack">
      <div className="pane-header">
        <div>
          <p className="pane-kicker">阶段 4</p>
          <h2>结果解释</h2>
        </div>
        <span className="status-badge">{activeStep === '结果解释' ? '当前焦点' : '输出摘要'}</span>
      </div>

      <section className="analysis-card run-status-panel">
        <div>
          <p className="pane-kicker">运行来源</p>
          <h3>{runStatus.label}</h3>
          <p>{runStatus.detail}</p>
        </div>
        <span className={`run-status-badge ${runStatus.source === 'backend' ? 'success' : 'warning'}`}>
          {runStatus.source === 'backend' ? '后端接口' : '本地回退'}
        </span>
      </section>

      <section className="analysis-card graph-detail">
        <div className="section-head">
          <h3>当前图谱锚点</h3>
          <span>{selectedLayerLabel}</span>
        </div>
        {selectedNode ? (
          <>
            <div className="graph-detail-head">
              <div>
                <strong>{selectedNode.label}</strong>
                <p>{selectedNode.detail}</p>
              </div>
              <span>{formatPercent(selectedNode.score)}</span>
            </div>
            <div className="graph-detail-stats">
              <div>
                <span>节点 ID</span>
                <strong>{selectedNode.id}</strong>
              </div>
              <div>
                <span>层级</span>
                <strong>{selectedLayerLabel}</strong>
              </div>
              <div>
                <span>关联边</span>
                <strong>
                  {incomingEdges.length} 入 / {outgoingEdges.length} 出
                </strong>
              </div>
            </div>
            <div className="graph-edge-grid">
              <div className="graph-edge-column">
                <span>入边</span>
                {incomingEdges.length ? (
                  incomingEdges.map((edge) => (
                    <div key={`${edge.source}-${edge.target}`} className="graph-edge-item">
                      <strong>
                        {edge.source} {'→'} {edge.target}
                      </strong>
                      <p>{edge.relation}</p>
                      <small>{formatPercent(edge.contribution)}</small>
                    </div>
                  ))
                ) : (
                  <p className="graph-edge-empty">没有入边</p>
                )}
              </div>
              <div className="graph-edge-column">
                <span>出边</span>
                {outgoingEdges.length ? (
                  outgoingEdges.map((edge) => (
                    <div key={`${edge.source}-${edge.target}`} className="graph-edge-item">
                      <strong>
                        {edge.source} {'→'} {edge.target}
                      </strong>
                      <p>{edge.relation}</p>
                      <small>{formatPercent(edge.contribution)}</small>
                    </div>
                  ))
                ) : (
                  <p className="graph-edge-empty">没有出边</p>
                )}
              </div>
            </div>
          </>
        ) : (
          <p className="result-intro">点击左侧图谱中的任意节点，查看它在推荐链路中的位置和关联边。</p>
        )}
      </section>

      <section className="analysis-card reachable-card">
        <div className="section-head">
          <h3>从当前节点可达的岗位</h3>
          <span>{reachableRoles.length} 个</span>
        </div>
        {selectedNode ? (
          reachableRoles.length ? (
            <div className="reachable-list">
              {reachableRoles.map((node) => (
                <article key={node.id} className="reachable-item">
                  <div className="node-row">
                    <strong>{node.label}</strong>
                    <span>{formatPercent(node.score)}</span>
                  </div>
                  <p>{node.detail}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="result-intro">当前节点还没有直接连到岗位层级，可以继续点更下游的方向节点。</p>
          )
        ) : (
          <p className="result-intro">先在图谱里选一个节点，这里会显示它能影响到的岗位节点。</p>
        )}
      </section>

      <section className="result-block">
        <div className="section-head">
          <h3>正式推荐</h3>
          <span>{response.recommendations.length} 个</span>
        </div>
        <div className="result-list">
          {response.recommendations.map((item) => {
            const isSelectedRole = item.nodeId === selectedNodeId;
            return (
              <article key={item.nodeId} className={`result-card strong ${isSelectedRole ? 'active' : ''}`}>
                <div className="node-row">
                  <strong>{item.label}</strong>
                  <span>{formatPercent(item.score)}</span>
                </div>
                <p>{item.reason.join('、')}</p>
                <small>路径：{item.path.join(' -> ')}</small>
              </article>
            );
          })}
        </div>
      </section>

      <section className="result-block">
        <div className="section-head">
          <h3>near miss</h3>
          <span>{response.nearMissRoles.length} 个</span>
        </div>
        <div className="result-list compact">
          {response.nearMissRoles.map((item) => (
            <article key={item.nodeId} className="result-card">
              <div className="node-row">
                <strong>{item.label}</strong>
                <span>{formatPercent(item.score)}</span>
              </div>
              <p>缺少：{item.missing.join('、') || '无'}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="result-grid">
        <article className="analysis-card">
          <div className="section-head">
            <h3>目标岗位分析</h3>
            <span>{formatPercent(response.targetRoleAnalysis.coverage)}</span>
          </div>
          <p>{response.targetRoleAnalysis.label}</p>
          <div className="tag-row">
            {response.targetRoleAnalysis.strengths.map((item) => (
              <span key={item} className="tag success">
                {item}
              </span>
            ))}
            {response.targetRoleAnalysis.gaps.map((item) => (
              <span key={item} className="tag warning">
                {item}
              </span>
            ))}
          </div>
        </article>

        <article className="analysis-card">
          <div className="section-head">
            <h3>桥接建议</h3>
            <span>{response.bridgeRecommendations.length} 条</span>
          </div>
          <div className="bridge-list">
            {response.bridgeRecommendations.map((item) => (
              <div key={item.nodeId} className="bridge-row">
                <div>
                  <strong>{item.label}</strong>
                  <p>{item.why}</p>
                </div>
                <span>{formatPercent(item.score)}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="result-block">
        <div className="section-head">
          <h3>鲁棒性测试</h3>
          <div className="section-actions">
            <span>{formatPercent(robustnessReport.averageTopScore)}</span>
            <button className="chip" type="button" onClick={onExportSnapshot}>
              导出快照
            </button>
            <button className="chip" type="button" onClick={onCopySnapshot}>
              复制快照
            </button>
          </div>
        </div>
        <p className="result-intro">{robustnessReport.headline}</p>
        <div className="analysis-card advice-card">
          <div className="section-head">
            <h3>下一步调参建议</h3>
            <span>{robustnessReport.tuningAdvice.length} 条</span>
          </div>
          <ul className="advice-list">
            {robustnessReport.tuningAdvice.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
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
            <small className="summary-note-inline">{formatDelta(robustnessReport.bestImprovementDelta)}</small>
          </div>
          <div className="result-summary-card">
            <span>最差回落</span>
            <strong>{robustnessReport.worstRegressionLabel}</strong>
            <small className="summary-note-inline">{formatDelta(robustnessReport.worstRegressionDelta)}</small>
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
              <p>{item.description}</p>
              <small>
                {item.warning} | 基线 {formatPercent(item.baselineTopScore)} | 变化 {formatDelta(item.scoreDelta)} | 推荐{' '}
                {item.recommendationCount} 个 | near miss {item.nearMissCount} 个 | 覆盖率 {formatPercent(item.coverage)}
              </small>
              <div className="tag-row">
                <span className={`tag ${item.scoreDelta >= 0 ? 'success' : 'warning'}`}>
                  {item.scoreDelta >= 0 ? '调参提升' : '调参回落'}
                </span>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="result-block trace-panel">
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
        <div className="trace-summary">
          <div className="trace-box">
            <span>命中证据</span>
            <p>{response.inputTrace.signalTrace.matchedSignals.join('、') || '暂无明确命中'}</p>
          </div>
          <div className="trace-box">
            <span>否定信号</span>
            <p>{response.inputTrace.signalTrace.negatedSignals.join('、') || '暂无否定信号'}</p>
          </div>
        </div>
        <div className="trace-summary compact">
          <div className="trace-box">
            <span>图谱节点</span>
            <p>{response.graphSnapshot.nodeCount} 个</p>
          </div>
          <div className="trace-box">
            <span>图谱边</span>
            <p>{response.graphSnapshot.edgeCount} 条</p>
          </div>
          <div className="trace-box">
            <span>目标覆盖</span>
            <p>{formatPercent(response.targetRoleAnalysis.coverage)}</p>
          </div>
        </div>
        <div className="structured-evidence">
          {response.inputTrace.structuredEvidence.map((item) => (
            <article key={item.nodeId} className="evidence-mini-card">
              <div className="node-row">
                <strong>{item.label}</strong>
                <span>{formatPercent(item.score)}</span>
              </div>
              <p>{item.rawText}</p>
              <small>
                来源：{item.source} | 节点：{item.nodeId}
              </small>
              <div className="score-bar">
                <span style={{ width: `${Math.round(item.score * 100)}%` }} />
              </div>
            </article>
          ))}
        </div>
        <details className="json-toggle">
          <summary>查看原始 JSON 快照</summary>
          <pre>{JSON.stringify(response.inputTrace, null, 2)}</pre>
        </details>
        <div className="clause-list">
          {response.inputTrace.signalTrace.clauses.map((clause, index) => (
            <span key={`${index}-${clause}`} className="clause-chip">
              {clause}
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}
