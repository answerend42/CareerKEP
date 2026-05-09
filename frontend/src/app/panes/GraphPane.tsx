import type { RecommendationResponse } from '../types';

interface GraphPaneProps {
  snapshot: RecommendationResponse['propagationSnapshot'];
  activeStep: string;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

const layerTone: Record<string, string> = {
  evidence: 'tone-evidence',
  ability: 'tone-ability',
  composite: 'tone-composite',
  direction: 'tone-direction',
  role: 'tone-role'
};

export function GraphPane({ snapshot, activeStep, selectedNodeId, onSelectNode }: GraphPaneProps) {
  return (
    <div className="pane-stack">
      <div className="pane-header">
        <div>
          <p className="pane-kicker">阶段 3</p>
          <h2>图谱传播</h2>
        </div>
        <span className="status-badge">{activeStep === '鍥捐氨浼犳挱' ? '正在查看' : '传播快照'}</span>
      </div>

      <div className="graph-columns">
        {snapshot.layers.map((layer) => (
          <section key={layer.layer} className={`layer-column ${layerTone[layer.layer]}`}>
            <div className="layer-head">
              <h3>{layer.label}</h3>
              <span>{layer.nodes.length} 个节点</span>
            </div>
            <div className="node-stack">
              {layer.nodes.map((node) => (
                <article key={node.id} className={`node-card ${selectedNodeId === node.id ? 'active' : ''}`}>
                  <button
                    type="button"
                    className="node-card-hitbox"
                    onClick={() => onSelectNode(node.id)}
                    aria-label={`选择 ${node.label}`}
                  >
                    <span className="sr-only">选择 {node.label}</span>
                  </button>
                  <div className="node-row">
                    <strong>{node.label}</strong>
                    <span>{node.score.toFixed(2)}</span>
                  </div>
                  <p>{node.detail}</p>
                  <div className="score-bar">
                    <span style={{ width: `${Math.round(node.score * 100)}%` }} />
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>

      <div className="edge-list">
        <div className="layer-head">
          <h3>高贡献边</h3>
          <span>{snapshot.edges.length} 条</span>
        </div>
        {snapshot.edges.map((edge) => (
          <button
            key={`${edge.source}-${edge.target}`}
            type="button"
            className="edge-row edge-row-button"
            onClick={() => onSelectNode(edge.target)}
          >
            <div>
              <strong>
                {edge.source} {'→'} {edge.target}
              </strong>
              <p>{edge.relation}</p>
            </div>
            <span>{edge.contribution.toFixed(2)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
