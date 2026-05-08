import type { RecommendationResponse, RobustnessReport } from '../types';

interface ResultPaneProps {
  response: RecommendationResponse;
  activeStep: string;
  robustnessReport: RobustnessReport;
}

const formatPercent = (value: number) => `${Math.round(value * 100)}%`;
const formatDelta = (value: number) => {
  const rounded = Math.round(value * 100);
  return rounded > 0 ? `+${rounded}%` : `${rounded}%`;
};

export function ResultPane({ response, activeStep, robustnessReport }: ResultPaneProps) {
  return (
    <div className="pane-stack">
      <div className="pane-header">
        <div>
          <p className="pane-kicker">阶段 4</p>
          <h2>结果解释</h2>
        </div>
        <span className="status-badge">{activeStep === '结果解释' ? '当前焦点' : '输出摘要'}</span>
      </div>

      <section className="result-block">
        <div className="section-head">
          <h3>正式推荐</h3>
          <span>{response.recommendations.length} 个</span>
        </div>
        <div className="result-list">
          {response.recommendations.map((item) => (
            <article key={item.nodeId} className="result-card strong">
              <div className="node-row">
                <strong>{item.label}</strong>
                <span>{formatPercent(item.score)}</span>
              </div>
              <p>{item.reason.join('；')}</p>
              <small>路径：{item.path.join(' · ')}</small>
            </article>
          ))}
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
          <span>{formatPercent(robustnessReport.averageTopScore)}</span>
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
            <span>改进率</span>
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
                {item.warning} · 默认 {formatPercent(item.baselineTopScore)} · 变化 {formatDelta(item.scoreDelta)} · 推荐{' '}
                {item.recommendationCount} 个 · near miss {item.nearMissCount} 个 · 覆盖率 {formatPercent(item.coverage)}
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
        <div className="clause-list">
          {response.inputTrace.signalTrace.clauses.map((clause, index) => (
            <span key={`${index}-${clause}`} className="clause-chip">
              {clause}
            </span>
          ))}
        </div>
        <pre>{JSON.stringify(response.inputTrace, null, 2)}</pre>
      </section>
    </div>
  );
}
