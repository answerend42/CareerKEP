import { useMemo, useState } from 'react';
import {
  buildDiagnosticExport,
  buildDiagnosticSnapshot,
  buildRecommendationResponse,
  buildRobustnessReport,
  defaultDemoState,
  getDemoCopy,
  getRoleOptions,
  scenarioPresets
} from './demoData';
import { InputPane } from './panes/InputPane';
import { TunePane } from './panes/TunePane';
import { GraphPane } from './panes/GraphPane';
import { ResultPane } from './panes/ResultPane';
import type { DemoState, RecommendationResponse, RunStatus } from './types';

const stepLabels = ['输入画像', '调整参数', '图谱传播', '结果解释'] as const;
const requestTimeoutMs = 6000;

const localRunStatus: RunStatus = {
  source: 'local-demo',
  label: '本地模拟结果',
  detail: '当前由前端 demoData 直接生成，便于离线演示和后端未启动时查看。'
};

export function AppShell() {
  const [state, setState] = useState<DemoState>(defaultDemoState);
  const [activeStep, setActiveStep] = useState<(typeof stepLabels)[number]>('输入画像');
  const [lastRun, setLastRun] = useState<RecommendationResponse>(() => buildRecommendationResponse(defaultDemoState));
  const [isRunning, setIsRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<RunStatus>(localRunStatus);

  const roleOptions = useMemo(() => getRoleOptions(), []);
  const demoCopy = useMemo(() => getDemoCopy(lastRun), [lastRun]);
  const robustnessReport = useMemo(() => buildRobustnessReport(state), [state]);
  const normalPresets = useMemo(() => scenarioPresets.filter((item) => item.kind === 'normal'), []);
  const stressPresets = useMemo(() => scenarioPresets.filter((item) => item.kind === 'stress'), []);

  const updateState = <K extends keyof DemoState>(key: K, value: DemoState[K]) => {
    setState((current) => {
      const nextState = { ...current, [key]: value };
      setLastRun(buildRecommendationResponse(nextState));
      setRunStatus(localRunStatus);
      return nextState;
    });
  };

  const applyPreset = (presetId: string) => {
    const preset = scenarioPresets.find((item) => item.id === presetId);
    if (!preset) {
      return;
    }

    setState(preset.state);
    setLastRun(buildRecommendationResponse(preset.state));
    setRunStatus(localRunStatus);
    setActiveStep('输入画像');
  };

  const runRecommendation = async () => {
    setIsRunning(true);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);

    try {
      const response = await fetch('/api/recommend', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        signal: controller.signal,
        body: JSON.stringify({
          text: state.text,
          target_role: state.targetRole,
          top_k: state.topK,
          evidence: state.evidence,
          tuning: state.tuning
        })
      });

      if (!response.ok) {
        throw new Error(`后端返回状态码 ${response.status}`);
      }

      const payload = (await response.json()) as RecommendationResponse;
      setLastRun(payload);
      setRunStatus({
        source: 'backend',
        label: '后端推荐结果',
        detail: '当前内容来自 `/api/recommend`，可以直接和本地模拟结果对比。'
      });
      setActiveStep('结果解释');
    } catch (error) {
      const detail =
        error instanceof DOMException && error.name === 'AbortError'
          ? '后端请求超时，页面已回退到本地模拟结果。'
          : '后端请求失败，页面已回退到本地模拟结果。';

      setLastRun(buildRecommendationResponse(state));
      setRunStatus({
        source: 'local-demo',
        label: '本地模拟结果',
        detail
      });
      setActiveStep('结果解释');
    } finally {
      window.clearTimeout(timeoutId);
      setIsRunning(false);
    }
  };

  const syncAndPreview = (nextState: DemoState) => {
    setState(nextState);
    setLastRun(buildRecommendationResponse(nextState));
    setRunStatus(localRunStatus);
  };

  const exportDiagnosticSnapshot = () => {
    const snapshot = buildDiagnosticSnapshot(activeStep, state, lastRun, robustnessReport);
    const exportResult = buildDiagnosticExport(snapshot);
    const blob = new Blob([exportResult.content], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');

    link.href = url;
    link.download = exportResult.filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const copyDiagnosticSnapshot = async () => {
    const snapshot = buildDiagnosticSnapshot(activeStep, state, lastRun, robustnessReport);
    const exportResult = buildDiagnosticExport(snapshot);

    try {
      await navigator.clipboard.writeText(exportResult.content);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = exportResult.content;
      textarea.setAttribute('readonly', 'true');
      textarea.style.position = 'fixed';
      textarea.style.left = '-9999px';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
  };

  return (
    <div className="page-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">Career KG 前端工作台</p>
          <h1>把自然语言画像，变成可解释的职业推荐</h1>
          <p className="hero-text">
            这个前端围绕四个阶段展开：输入画像、微调画像、图谱传播、结果解释。
            你可以直接跑本地演示，也可以接到后端 `/api/recommend`。
          </p>
          <div className="hero-metrics">
            <div>
              <strong>{lastRun.graphSnapshot.nodeCount}</strong>
              <span>图谱节点</span>
            </div>
            <div>
              <strong>{lastRun.graphSnapshot.edgeCount}</strong>
              <span>传播边</span>
            </div>
            <div>
              <strong>{lastRun.recommendations.length}</strong>
              <span>正式推荐</span>
            </div>
          </div>
        </div>
        <aside className="hero-aside">
          <div className="summary-card">
            <span className="summary-label">当前结论</span>
            <h2>{demoCopy.headline}</h2>
            <p>{demoCopy.summary}</p>
            <p className="summary-note">{demoCopy.targetLine}</p>
            <div className="run-status">
              <span className={`run-status-badge ${runStatus.source === 'backend' ? 'success' : 'warning'}`}>
                {runStatus.label}
              </span>
              <small>{runStatus.detail}</small>
            </div>
          </div>
          <div className="step-rail" aria-label="四阶段导航">
            {stepLabels.map((label, index) => (
              <button
                key={label}
                className={`step-pill ${activeStep === label ? 'active' : ''}`}
                onClick={() => setActiveStep(label)}
                type="button"
              >
                <span>{index + 1}</span>
                {label}
              </button>
            ))}
          </div>
        </aside>
      </header>

      <main className="workspace-grid">
        <section className="panel panel-input">
          <InputPane
            state={state}
            roleOptions={roleOptions}
            presets={normalPresets}
            stressPresets={stressPresets}
            onChange={updateState}
            onPreset={applyPreset}
            onRun={runRecommendation}
            isRunning={isRunning}
          />
        </section>

        <section className="panel panel-tune">
          <TunePane
            state={state}
            onChange={updateState}
            onApply={(nextState) => syncAndPreview(nextState)}
            activeStep={activeStep}
          />
        </section>

        <section className="panel panel-graph">
          <GraphPane snapshot={lastRun.propagationSnapshot} activeStep={activeStep} />
        </section>

        <section className="panel panel-result">
          <ResultPane
            response={lastRun}
            activeStep={activeStep}
            robustnessReport={robustnessReport}
            runStatus={runStatus}
            onExportSnapshot={exportDiagnosticSnapshot}
            onCopySnapshot={copyDiagnosticSnapshot}
          />
        </section>
      </main>
    </div>
  );
}
