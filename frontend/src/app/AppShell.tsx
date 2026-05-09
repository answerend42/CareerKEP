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
import { GraphPane } from './panes/GraphPane';
import { InputPane } from './panes/InputPane';
import { ResultPane } from './panes/ResultPane';
import { TunePane } from './panes/TunePane';
import type { DemoState, RecommendationResponse, RunStatus } from './types';

const stepLabels = ['杈撳叆鐢诲儚', '璋冩暣鍙傛暟', '鍥捐氨浼犳挱', '缁撴灉瑙ｉ噴'] as const;
const requestTimeoutMs = 6000;

const localRunStatus: RunStatus = {
  source: 'local-demo',
  label: '鏈湴妯℃嫙缁撴灉',
  detail: '褰撳墠鐢卞墠绔?demoData 鐩存帴鐢熸垚锛屼究浜庣绾挎紨绀哄拰鍚庣鏈惎鍔ㄦ椂鏌ョ湅銆?'
};

const pickDefaultSelectedNodeId = (response: RecommendationResponse): string | null =>
  response.recommendations[0]?.nodeId ?? response.inputTrace.structuredEvidence[0]?.nodeId ?? response.targetRoleAnalysis.nodeId ?? null;

export function AppShell() {
  const [state, setState] = useState<DemoState>(defaultDemoState);
  const [activeStep, setActiveStep] = useState<(typeof stepLabels)[number]>('杈撳叆鐢诲儚');
  const [lastRun, setLastRun] = useState<RecommendationResponse>(() => buildRecommendationResponse(defaultDemoState));
  const [isRunning, setIsRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<RunStatus>(localRunStatus);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(() => pickDefaultSelectedNodeId(buildRecommendationResponse(defaultDemoState)));

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

    const nextResponse = buildRecommendationResponse(preset.state);
    setState(preset.state);
    setLastRun(nextResponse);
    setRunStatus(localRunStatus);
    setSelectedNodeId(pickDefaultSelectedNodeId(nextResponse));
    setActiveStep('杈撳叆鐢诲儚');
  };

  const resetDemoState = () => {
    const nextResponse = buildRecommendationResponse(defaultDemoState);
    setState(defaultDemoState);
    setLastRun(nextResponse);
    setRunStatus(localRunStatus);
    setSelectedNodeId(pickDefaultSelectedNodeId(nextResponse));
    setActiveStep('杈撳叆鐢诲儚');
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
        throw new Error(`鍚庣杩斿洖鐘舵€佺爜 ${response.status}`);
      }

      const payload = (await response.json()) as RecommendationResponse;
      setLastRun(payload);
      setSelectedNodeId(pickDefaultSelectedNodeId(payload));
      setRunStatus({
        source: 'backend',
        label: '鍚庣鎺ㄨ崘缁撴灉',
        detail: '褰撳墠鍐呭鏉ヨ嚜 `/api/recommend`锛屽彲浠ョ洿鎺ュ拰鏈湴妯℃嫙缁撴灉瀵规瘮銆?'
      });
      setActiveStep('缁撴灉瑙ｉ噴');
    } catch (error) {
      const detail =
        error instanceof DOMException && error.name === 'AbortError'
          ? '鍚庣璇锋眰瓒呮椂锛岄〉闈㈠凡鍥為€€鍒版湰鍦版ā鎷熺粨鏋溿€?'
          : '鍚庣璇锋眰澶辫触锛岄〉闈㈠凡鍥為€€鍒版湰鍦版ā鎷熺粨鏋溿€?';

      const fallbackResponse = buildRecommendationResponse(state);
      setLastRun(fallbackResponse);
      setSelectedNodeId(pickDefaultSelectedNodeId(fallbackResponse));
      setRunStatus({
        source: 'local-demo',
        label: '鏈湴妯℃嫙缁撴灉',
        detail
      });
      setActiveStep('缁撴灉瑙ｉ噴');
    } finally {
      window.clearTimeout(timeoutId);
      setIsRunning(false);
    }
  };

  const syncAndPreview = (nextState: DemoState) => {
    const nextResponse = buildRecommendationResponse(nextState);
    setState(nextState);
    setLastRun(nextResponse);
    setSelectedNodeId(pickDefaultSelectedNodeId(nextResponse));
    setRunStatus(localRunStatus);
  };

  const selectGraphNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setActiveStep('鍥捐氨浼犳挱');
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
            这个前端围绕四个阶段展开：输入画像、调整参数、图谱传播、结果解释。你可以直接跑本地演示，也可以接到后端
            `/api/recommend`。
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
            <div>
              <strong>{state.evidence.length}</strong>
              <span>可调证据</span>
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
            onReset={resetDemoState}
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
          <GraphPane
            snapshot={lastRun.propagationSnapshot}
            activeStep={activeStep}
            selectedNodeId={selectedNodeId}
            onSelectNode={selectGraphNode}
          />
        </section>

        <section className="panel panel-result">
          <ResultPane
            response={lastRun}
            activeStep={activeStep}
            robustnessReport={robustnessReport}
            runStatus={runStatus}
            onExportSnapshot={exportDiagnosticSnapshot}
            onCopySnapshot={copyDiagnosticSnapshot}
            selectedNodeId={selectedNodeId}
          />
        </section>
      </main>
    </div>
  );
}
