import { useMemo, useState } from 'react';
import {
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
import type { DemoState, RecommendationResponse } from './types';

const stepLabels = ['输入画像', '微调画像', '图谱传播', '结果解释'] as const;

export function AppShell() {
  const [state, setState] = useState<DemoState>(defaultDemoState);
  const [activeStep, setActiveStep] = useState<(typeof stepLabels)[number]>('输入画像');
  const [lastRun, setLastRun] = useState<RecommendationResponse>(() => buildRecommendationResponse(defaultDemoState));
  const [isRunning, setIsRunning] = useState(false);

  const roleOptions = useMemo(() => getRoleOptions(), []);
  const demoCopy = useMemo(() => getDemoCopy(lastRun), [lastRun]);
  const robustnessReport = useMemo(() => buildRobustnessReport(state), [state]);
  const normalPresets = useMemo(() => scenarioPresets.filter((item) => item.kind === 'normal'), []);
  const stressPresets = useMemo(() => scenarioPresets.filter((item) => item.kind === 'stress'), []);

  const updateState = <K extends keyof DemoState>(key: K, value: DemoState[K]) => {
    setState((current) => {
      const nextState = { ...current, [key]: value };
      setLastRun(buildRecommendationResponse(nextState));
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
    setActiveStep('输入画像');
  };

  const runRecommendation = async () => {
    setIsRunning(true);
    try {
      const response = await fetch('/api/recommend', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
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
      setActiveStep('结果解释');
    } catch {
      setLastRun(buildRecommendationResponse(state));
      setActiveStep('结果解释');
    } finally {
      setIsRunning(false);
    }
  };

  const syncAndPreview = (nextState: DemoState) => {
    setState(nextState);
    setLastRun(buildRecommendationResponse(nextState));
  };

  const exportDiagnosticSnapshot = () => {
    const snapshot = buildDiagnosticSnapshot(activeStep, state, lastRun, robustnessReport);
    const content = JSON.stringify(snapshot, null, 2);
    const blob = new Blob([content], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');

    link.href = url;
    link.download = `career-kg-diagnostic-${snapshot.generatedAt.replace(/[:.]/g, '-')}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="hero-card">
        <div className="hero-copy">
          <p className="eyebrow">Career KG · 前端工作台</p>
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
            onExportSnapshot={exportDiagnosticSnapshot}
          />
        </section>
      </main>
    </div>
  );
}
