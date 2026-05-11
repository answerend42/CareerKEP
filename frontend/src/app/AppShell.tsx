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

const stepLabels = ['输入画像', '调整参数', '图谱传播', '结果解释'] as const;
const requestTimeoutMs = 6000;

const localRunStatus: RunStatus = {
  source: 'local-demo',
  label: '本地模拟结果',
  detail: '当前由前端 demoData 直接生成，便于离线演示和后端未启动时查看。'
};

const layerOrder = ['evidence', 'ability', 'composite', 'direction', 'role'] as const;
const layerLabelMap: Record<string, string> = {
  evidence: '输入证据',
  ability: '基础能力',
  composite: '复合能力',
  direction: '岗位方向',
  role: '职业岗位'
};

const clamp01 = (value: number): number => {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(1, Math.max(0, value));
};

const asObject = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null;

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const asNumber = (value: unknown): number => (typeof value === 'number' ? value : Number(value) || 0);

const normalizeRecommendationResponse = (payload: unknown, fallbackState: DemoState): RecommendationResponse => {
  const root = asObject(payload);
  if (!root) {
    throw new Error('后端响应不是对象');
  }

  const inputTraceRaw = asObject(root.input_trace) ?? {};
  const parsedSignals = asObject(inputTraceRaw.parsed_natural_language_evidence) ?? {};
  const matchedSignals = Object.keys(parsedSignals);

  const structuredEvidenceRaw = Array.isArray(inputTraceRaw.structured_evidence) ? inputTraceRaw.structured_evidence : [];
  const structuredEvidence = structuredEvidenceRaw
    .map((item) => asObject(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => {
      const nodeId = String(item.node_id ?? item.nodeId ?? item.id ?? '');
      return {
        nodeId,
        label: String(item.label ?? nodeId),
        score: clamp01(asNumber(item.score)),
        source: String(item.source ?? 'backend'),
        rawText: String(item.raw_text ?? item.rawText ?? '')
      };
    });

  const recommendationRaw = Array.isArray(root.recommendations) ? root.recommendations : [];
  const normalizeCard = (item: unknown) => {
    const obj = asObject(item) ?? {};
    return {
      nodeId: String(obj.node_id ?? obj.nodeId ?? ''),
      label: String(obj.label ?? obj.node_id ?? obj.nodeId ?? '未命名岗位'),
      score: clamp01(asNumber(obj.score)),
      reason: asStringArray(obj.reasons).length ? asStringArray(obj.reasons) : asStringArray(obj.reason),
      missing: asStringArray(obj.missing_requirements).length ? asStringArray(obj.missing_requirements) : asStringArray(obj.missing),
      path: asStringArray(obj.path)
    };
  };

  const recommendations = recommendationRaw.map(normalizeCard);
  const nearMissRoles = (Array.isArray(root.near_miss_roles) ? root.near_miss_roles : []).map(normalizeCard);
  const bridgeRecommendations = (Array.isArray(root.bridge_recommendations) ? root.bridge_recommendations : [])
    .map((item) => asObject(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .map((item) => ({
      nodeId: String(item.node_id ?? item.nodeId ?? ''),
      label: String(item.label ?? item.node_id ?? '桥接建议'),
      score: clamp01(asNumber(item.score)),
      why: String(item.why ?? item.summary ?? '')
    }));

  const propagationNodesRaw = Array.isArray(root.propagation_snapshot) ? root.propagation_snapshot : [];
  const propagationNodes = propagationNodesRaw.map((item) => asObject(item)).filter((item): item is Record<string, unknown> => Boolean(item));

  const layers = layerOrder.map((layerKey) => {
    const nodes = propagationNodes
      .filter((item) => item.layer === layerKey)
      .map((item) => {
        const diagnostics = asObject(item.diagnostics) ?? {};
        const supportTotal = clamp01(asNumber(diagnostics.support_total));
        const requireTotal = clamp01(asNumber(diagnostics.require_total));
        const detail = `support ${supportTotal.toFixed(2)} / require ${requireTotal.toFixed(2)}`;
        return {
          id: String(item.node_id ?? item.id ?? ''),
          label: String(item.label ?? item.node_id ?? item.id ?? '未命名节点'),
          layer: layerKey,
          score: clamp01(asNumber(item.score)),
          detail
        };
      });
    return {
      layer: layerKey,
      label: layerLabelMap[layerKey],
      nodes
    };
  });

  const edges = propagationNodes.flatMap((item) => {
    const contributions = Array.isArray(item.parent_contributions) ? item.parent_contributions : [];
    return contributions
      .map((edge) => asObject(edge))
      .filter((edge): edge is Record<string, unknown> => Boolean(edge))
      .map((edge) => ({
        source: String(edge.source ?? ''),
        target: String(edge.target ?? ''),
        relation: String(edge.relation ?? 'supports'),
        contribution: clamp01(asNumber(edge.contribution))
      }))
      .filter((edge) => edge.source && edge.target);
  });

  const targetRaw = asObject(root.target_role_analysis) ?? {};
  const strengthsRaw = Array.isArray(targetRaw.strengths) ? targetRaw.strengths : [];
  const missingRaw = Array.isArray(targetRaw.missing_requirements) ? targetRaw.missing_requirements : [];
  const normalizeLabelItem = (item: unknown): string => {
    const obj = asObject(item);
    if (!obj) {
      return typeof item === 'string' ? item : '';
    }
    return String(obj.label ?? obj.node_id ?? obj.id ?? '');
  };
  const strengths = strengthsRaw.map(normalizeLabelItem).filter(Boolean);
  const gaps = missingRaw.map(normalizeLabelItem).filter(Boolean);

  const layerBreakdown = Object.fromEntries(layers.map((layer) => [layer.layer, layer.nodes.length]));
  const nodeCount = layers.reduce((sum, layer) => sum + layer.nodes.length, 0);

  return {
    inputTrace: {
      rawText: String(inputTraceRaw.text ?? fallbackState.text),
      targetRole: String(inputTraceRaw.target_role ?? fallbackState.targetRole ?? ''),
      resolvedTargetRole: String(inputTraceRaw.resolved_target_role ?? ''),
      structuredEvidence,
      signalTrace: {
        clauses: String(inputTraceRaw.text ?? fallbackState.text)
          .split(/[，。；,.!?！？]/)
          .map((item) => item.trim())
          .filter(Boolean),
        matchedSignals,
        negatedSignals: []
      }
    },
    recommendations,
    nearMissRoles,
    bridgeRecommendations,
    targetRoleAnalysis: {
      nodeId: String(targetRaw.role_id ?? targetRaw.node_id ?? targetRaw.id ?? ''),
      label: String(targetRaw.label ?? fallbackState.targetRole ?? '目标岗位'),
      coverage: clamp01(asNumber(targetRaw.coverage_score ?? targetRaw.coverage)),
      strengths,
      gaps,
      path: asStringArray(targetRaw.path)
    },
    propagationSnapshot: {
      layers,
      edges
    },
    graphSnapshot: {
      nodeCount,
      edgeCount: edges.length,
      layerBreakdown
    }
  };
};

const pickDefaultSelectedNodeId = (response: RecommendationResponse): string | null =>
  response.recommendations[0]?.nodeId ?? response.inputTrace.structuredEvidence[0]?.nodeId ?? response.targetRoleAnalysis.nodeId ?? null;

export function AppShell() {
  const [state, setState] = useState<DemoState>(defaultDemoState);
  const [activeStep, setActiveStep] = useState<(typeof stepLabels)[number]>('输入画像');
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
    setActiveStep('输入画像');
  };

  const resetDemoState = () => {
    const nextResponse = buildRecommendationResponse(defaultDemoState);
    setState(defaultDemoState);
    setLastRun(nextResponse);
    setRunStatus(localRunStatus);
    setSelectedNodeId(pickDefaultSelectedNodeId(nextResponse));
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

      const rawPayload = (await response.json()) as unknown;
      const payload = normalizeRecommendationResponse(rawPayload, state);
      setLastRun(payload);
      setSelectedNodeId(pickDefaultSelectedNodeId(payload));
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

      const fallbackResponse = buildRecommendationResponse(state);
      setLastRun(fallbackResponse);
      setSelectedNodeId(pickDefaultSelectedNodeId(fallbackResponse));
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
    const nextResponse = buildRecommendationResponse(nextState);
    setState(nextState);
    setLastRun(nextResponse);
    setSelectedNodeId(pickDefaultSelectedNodeId(nextResponse));
    setRunStatus(localRunStatus);
  };

  const selectGraphNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setActiveStep('图谱传播');
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
