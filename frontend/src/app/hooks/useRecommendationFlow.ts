import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { SCORE_OPTIONS, clampScore } from "../lib/scoring";
import type {
  ActionCard,
  ActionSimulationResponse,
  CatalogNode,
  CatalogResponse,
  ConfirmedSignalDraft,
  DemoCase,
  GraphSnapshotNode,
  RecommendationResponse,
  ResultCard,
  RoleGapResponse,
  SelectionState,
  SignalInput,
  StatusState,
  StructuredSignalDraft,
} from "../types/api";

type RecommendationCard = Extract<ResultCard, { kind: "recommendation" }>;
type NearMissCard = Extract<ResultCard, { kind: "near_miss" }>;
type BridgeCard = Extract<ResultCard, { kind: "bridge" }>;

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2, 10);
}

function createStructuredSignal(): StructuredSignalDraft {
  return { id: createId(), entity: "", score: SCORE_OPTIONS[2].value };
}

function createConfirmedSignal(): ConfirmedSignalDraft {
  return {
    id: createId(),
    nodeId: "",
    nodeName: "",
    score: SCORE_OPTIONS[1].value,
    source: "manual",
  };
}

function toSignalPayload(signals: StructuredSignalDraft[]): SignalInput[] {
  return signals
    .map((signal) => ({
      entity: signal.entity.trim(),
      score: clampScore(signal.score),
    }))
    .filter((signal) => signal.entity);
}

function toConfirmedPayload(signals: ConfirmedSignalDraft[]): SignalInput[] {
  return signals
    .map((signal) => ({
      entity: (signal.nodeId || signal.nodeName).trim(),
      score: clampScore(signal.score),
    }))
    .filter((signal) => signal.entity);
}

function buildResultCards(result: RecommendationResponse | null): {
  recommendations: RecommendationCard[];
  nearMisses: NearMissCard[];
  bridges: BridgeCard[];
} {
  if (!result) {
    return { recommendations: [], nearMisses: [], bridges: [] };
  }

  return {
    recommendations: result.recommendations.map((item) => ({
      ...item,
      kind: "recommendation" as const,
      key: `recommendation:${item.job_id}`,
    })),
    nearMisses: result.near_miss_roles.map((item) => ({
      ...item,
      kind: "near_miss" as const,
      key: `near_miss:${item.job_id}`,
    })),
    bridges: result.bridge_recommendations.map((item) => ({
      ...item,
      kind: "bridge" as const,
      key: `bridge:${item.anchor_id}`,
    })),
  };
}

function firstSelection(result: RecommendationResponse | null): SelectionState | null {
  if (!result) {
    return null;
  }
  const firstRecommendation = result.recommendations[0];
  if (firstRecommendation) {
    return { kind: "recommendation", id: firstRecommendation.job_id };
  }
  const firstNearMiss = result.near_miss_roles[0];
  if (firstNearMiss) {
    return { kind: "near_miss", id: firstNearMiss.job_id };
  }
  const firstBridge = result.bridge_recommendations[0];
  if (firstBridge) {
    return { kind: "bridge", id: firstBridge.anchor_id };
  }
  return null;
}

function roleSelection(result: RecommendationResponse | null, roleId: string): SelectionState | null {
  if (!result) {
    return null;
  }
  if (result.recommendations.some((item) => item.job_id === roleId)) {
    return { kind: "recommendation", id: roleId };
  }
  if (result.near_miss_roles.some((item) => item.job_id === roleId)) {
    return { kind: "near_miss", id: roleId };
  }
  return null;
}

function findSelectedCard(result: RecommendationResponse | null, selection: SelectionState | null): ResultCard | null {
  const cards = buildResultCards(result);
  if (!selection) {
    return cards.recommendations[0] || cards.nearMisses[0] || cards.bridges[0] || null;
  }
  if (selection.kind === "recommendation") {
    return cards.recommendations.find((item) => item.job_id === selection.id) || null;
  }
  if (selection.kind === "near_miss") {
    return cards.nearMisses.find((item) => item.job_id === selection.id) || null;
  }
  return cards.bridges.find((item) => item.anchor_id === selection.id) || null;
}

function cardNodeId(card: ResultCard | null): string | null {
  if (!card) {
    return null;
  }
  return card.kind === "bridge" ? card.anchor_id : card.job_id;
}

function buildPayloadSignature(targetRoleId: string, signals: ConfirmedSignalDraft[]): string {
  return JSON.stringify({
    targetRoleId,
    signals: signals
      .map((signal) => ({
        entity: signal.nodeId || signal.nodeName,
        score: clampScore(signal.score),
      }))
      .sort((a, b) => a.entity.localeCompare(b.entity) || a.score - b.score),
  });
}

function mergeSimulationIntoSignals(
  currentSignals: ConfirmedSignalDraft[],
  boosts: ActionSimulationResponse["simulation"]["injected_boosts"],
): ConfirmedSignalDraft[] {
  const merged = new Map<string, ConfirmedSignalDraft>();
  for (const signal of currentSignals) {
    const key = signal.nodeId || signal.nodeName;
    if (!key) {
      continue;
    }
    merged.set(key, signal);
  }
  for (const boost of boosts) {
    const current = merged.get(boost.node_id);
    merged.set(boost.node_id, {
      id: current?.id || createId(),
      nodeId: boost.node_id,
      nodeName: boost.node_name,
      score: Math.max(current?.score || 0, clampScore(boost.to_score)),
      source: "simulation",
    });
  }
  return Array.from(merged.values()).sort((a, b) => b.score - a.score || a.nodeName.localeCompare(b.nodeName));
}

function resolveCatalogNode(catalog: CatalogNode[], input: string): CatalogNode | null {
  const normalized = input.trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  return (
    catalog.find((node) => node.id.toLowerCase() === normalized) ||
    catalog.find((node) => node.name.toLowerCase() === normalized) ||
    catalog.find((node) => (node.aliases || []).some((alias) => alias.toLowerCase() === normalized)) ||
    null
  );
}

function findActionByKey(targetAnalysis: RoleGapResponse | null, actionKey: string): ActionCard | null {
  if (!targetAnalysis) {
    return null;
  }
  for (const step of targetAnalysis.target_role.learning_path) {
    const match = step.recommended_actions.find((action) => action.action_key === actionKey);
    if (match) {
      return match;
    }
  }
  return null;
}

export function useRecommendationFlow() {
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [inputText, setInputTextState] = useState("");
  const [structuredSignals, setStructuredSignals] = useState<StructuredSignalDraft[]>([createStructuredSignal()]);
  const [confirmedSignals, setConfirmedSignals] = useState<ConfirmedSignalDraft[]>([]);
  const [confirmedSignalsDirty, setConfirmedSignalsDirty] = useState(false);
  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [targetRoleId, setTargetRoleId] = useState("");
  const [targetAnalysis, setTargetAnalysis] = useState<RoleGapResponse | null>(null);
  const [targetAnalysisSignature, setTargetAnalysisSignature] = useState("");
  const [actionSimulation, setActionSimulation] = useState<ActionSimulationResponse["simulation"] | null>(null);
  const [selectedBundleActionKeys, setSelectedBundleActionKeys] = useState<string[]>([]);
  const [selection, setSelection] = useState<SelectionState | null>(null);
  const [selectedPathIndex, setSelectedPathIndex] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [graphReplaySeed, setGraphReplaySeed] = useState(0);
  const [status, setStatus] = useState<StatusState>({
    busy: false,
    message: "",
    error: "",
  });

  const cards = buildResultCards(recommendation);
  const selectedCard = findSelectedCard(recommendation, selection);
  const selectedPath = selectedCard?.paths?.[selectedPathIndex] || selectedCard?.paths?.[0] || null;
  const selectedSnapshotNode =
    recommendation?.propagation_snapshot?.nodes.find((node) => node.id === selectedNodeId) ||
    recommendation?.propagation_snapshot?.nodes.find((node) => node.id === cardNodeId(selectedCard)) ||
    null;

  function setBusy(message: string): void {
    setStatus({ busy: true, message, error: "" });
  }

  function setSuccess(message: string): void {
    setStatus({ busy: false, message, error: "" });
  }

  function setError(message: string): void {
    setStatus({ busy: false, message: "", error: message });
  }

  function resetDownstream(): void {
    setRecommendation(null);
    setConfirmedSignals([]);
    setConfirmedSignalsDirty(false);
    setTargetAnalysis(null);
    setTargetAnalysisSignature("");
    setActionSimulation(null);
    setSelectedBundleActionKeys([]);
    setSelection(null);
    setSelectedPathIndex(0);
    setSelectedNodeId(null);
    setGraphReplaySeed((seed) => seed + 1);
  }

  function setInputText(value: string): void {
    setInputTextState(value);
    if (recommendation || confirmedSignals.length || confirmedSignalsDirty || targetAnalysis || actionSimulation) {
      resetDownstream();
    }
  }

  async function loadCatalog(): Promise<void> {
    setBusy("正在加载图谱目录…");
    try {
      const response = await api.catalog();
      setCatalog(response);
      setSuccess("图谱目录已加载。");
    } catch (error) {
      setError(error instanceof Error ? error.message : "加载目录失败");
    }
  }

  useEffect(() => {
    void loadCatalog();
  }, []);

  function applyInputPreset(demoCase: Pick<DemoCase, "text" | "signals" | "target_role_id"> | CatalogResponse["sample_request"]): void {
    resetDownstream();
    setInputTextState(demoCase.text || "");
    setStructuredSignals([createStructuredSignal()]);
  }

  async function runRecommendation(payload: { text: string; signals: SignalInput[] }, successMessage: string): Promise<boolean> {
    if (!payload.text && payload.signals.length === 0) {
      setError("请至少提供一句自然语言描述或一条结构化信号。");
      return false;
    }
    setBusy("正在解析输入并运行知识图谱推理…");
    try {
      const response = await api.recommend({
        ...payload,
        top_k: 6,
        include_snapshot: true,
      });
      const nextSelection = firstSelection(response);
      setRecommendation(response);
      setConfirmedSignals(
        response.normalized_inputs.map((item) => ({
          id: createId(),
          nodeId: item.node_id,
          nodeName: item.node_name,
          score: clampScore(item.score),
          source: item.source,
        })),
      );
      setConfirmedSignalsDirty(false);
      setSelection(nextSelection);
      setSelectedPathIndex(0);
      setSelectedNodeId(nextSelection?.id || null);
      setTargetAnalysis(null);
      setTargetAnalysisSignature("");
      setActionSimulation(null);
      setSelectedBundleActionKeys([]);
      setGraphReplaySeed((seed) => seed + 1);
      setSuccess(successMessage);
      return true;
    } catch (error) {
      setError(error instanceof Error ? error.message : "推荐请求失败");
      return false;
    }
  }

  async function submitInitialRecommendation(): Promise<boolean> {
    return runRecommendation(
      {
        text: inputText.trim(),
        signals: [],
      },
      "推荐结果已更新，可继续确认节点后重算。",
    );
  }

  async function recomputeFromConfirmedSignals(): Promise<boolean> {
    return runRecommendation(
      {
        text: "",
        signals: toConfirmedPayload(confirmedSignals),
      },
      "已按确认画像重算推荐。",
    );
  }

  async function applyDemoCase(caseId: string, replay: boolean): Promise<void> {
    const demoCase = catalog?.demo_cases.find((item) => item.id === caseId);
    if (!demoCase) {
      setError("未找到对应案例。");
      return;
    }
    applyInputPreset(demoCase);
    if (!replay) {
      setSuccess(`已载入案例：${demoCase.title}`);
      return;
    }
    const recommendationOk = await runRecommendation(
      {
        text: demoCase.text,
        signals: [],
      },
      `案例已回放：${demoCase.title}`,
    );
    if (!recommendationOk) {
      return;
    }
  }

  async function analyzeTargetRole(): Promise<boolean> {
    if (!targetRoleId) {
      setError("请先选择目标岗位。");
      return false;
    }
    const signals = confirmedSignals.length ? toConfirmedPayload(confirmedSignals) : toSignalPayload(structuredSignals);
    const payload = {
      target_role_id: targetRoleId,
      text: confirmedSignals.length ? "" : inputText.trim(),
      signals,
    };
    if (!payload.text && payload.signals.length === 0) {
      setError("请先形成一组可用信号，再分析目标岗位。");
      return false;
    }
    setBusy("正在分析目标岗位与成长路径…");
    try {
      const response = await api.roleGap(payload);
      setTargetAnalysis(response);
      setTargetAnalysisSignature(buildPayloadSignature(targetRoleId, confirmedSignals));
      setActionSimulation(null);
      setSelectedBundleActionKeys([]);
      setSuccess("目标岗位分析已更新。");
      return true;
    } catch (error) {
      setError(error instanceof Error ? error.message : "目标岗位分析失败");
      return false;
    }
  }

  async function runActionSimulation(payload: Record<string, unknown>, successMessage: string): Promise<void> {
    if (!targetRoleId || !targetAnalysis) {
      setError("请先完成一次目标岗位分析。");
      return;
    }
    if (targetAnalysisSignature && targetAnalysisSignature !== buildPayloadSignature(targetRoleId, confirmedSignals)) {
      setError("确认画像已变更，请先重新分析目标岗位，再执行行动模拟。");
      return;
    }
    setBusy("正在模拟行动对图谱传播的影响…");
    try {
      const response = await api.actionSimulate(payload);
      setActionSimulation(response.simulation);
      setSuccess(successMessage);
    } catch (error) {
      setError(error instanceof Error ? error.message : "行动模拟失败");
    }
  }

  async function simulateAction(templateId: string, actionKey?: string): Promise<void> {
    const payload = {
      target_role_id: targetRoleId,
      text: "",
      signals: toConfirmedPayload(confirmedSignals),
      template_id: templateId,
      action_key: actionKey || "",
    };
    await runActionSimulation(payload, "单动作模拟已更新。");
  }

  function toggleActionBundle(actionKey: string): void {
    setSelectedBundleActionKeys((current) => {
      if (current.includes(actionKey)) {
        return current.filter((item) => item !== actionKey);
      }
      if (current.length >= 2) {
        return [current[1], actionKey];
      }
      return [...current, actionKey];
    });
  }

  function clearActionBundle(): void {
    setSelectedBundleActionKeys([]);
  }

  async function simulateActionBundle(): Promise<void> {
    if (!selectedBundleActionKeys.length) {
      setError("请先加入 1-2 个动作。");
      return;
    }
    await runActionSimulation(
      {
        target_role_id: targetRoleId,
        text: "",
        signals: toConfirmedPayload(confirmedSignals),
        action_keys: selectedBundleActionKeys,
      },
      selectedBundleActionKeys.length > 1 ? "组合模拟已更新。" : "当前动作模拟已更新。",
    );
  }

  async function adoptSimulation(): Promise<void> {
    if (!actionSimulation?.injected_boosts?.length) {
      setError("当前模拟没有新增证据可采纳。");
      return;
    }
    const mergedSignals = mergeSimulationIntoSignals(confirmedSignals, actionSimulation.injected_boosts);
    setConfirmedSignals(mergedSignals);
    setActionSimulation(null);
    setTargetAnalysis(null);
    setTargetAnalysisSignature("");
    setSelectedBundleActionKeys([]);
    await runRecommendation(
      {
        text: "",
        signals: toConfirmedPayload(mergedSignals),
      },
      "已采纳模拟动作并重算推荐。",
    );
  }

  function updateStructuredSignal(id: string, updates: Partial<StructuredSignalDraft>): void {
    setStructuredSignals((current) =>
      current.map((signal) => (signal.id === id ? { ...signal, ...updates, score: clampScore(updates.score ?? signal.score) } : signal)),
    );
  }

  function updateConfirmedSignal(
    id: string,
    updates: Partial<ConfirmedSignalDraft>,
  ): void {
    setConfirmedSignals((current) =>
      current.map((signal) => (signal.id === id ? { ...signal, ...updates, score: clampScore(updates.score ?? signal.score) } : signal)),
    );
    setConfirmedSignalsDirty(true);
    setActionSimulation(null);
  }

  function addStructuredSignalRow(): void {
    setStructuredSignals((current) => [...current, createStructuredSignal()]);
  }

  function removeStructuredSignalRow(id: string): void {
    setStructuredSignals((current) => {
      const next = current.filter((signal) => signal.id !== id);
      return next.length ? next : [createStructuredSignal()];
    });
  }

  function addConfirmedSignalRow(): void {
    setConfirmedSignals((current) => [...current, createConfirmedSignal()]);
    setConfirmedSignalsDirty(true);
  }

  function removeConfirmedSignalRow(id: string): void {
    setConfirmedSignals((current) => current.filter((signal) => signal.id !== id));
    setConfirmedSignalsDirty(true);
    setActionSimulation(null);
  }

  function setConfirmedSignalEntity(id: string, value: string): void {
    const resolved = resolveCatalogNode(catalog?.evidence_nodes || [], value);
    updateConfirmedSignal(id, {
      nodeId: resolved?.id || value.trim(),
      nodeName: resolved?.name || value.trim(),
    });
  }

  function selectResult(nextSelection: SelectionState): void {
    setSelection(nextSelection);
    setSelectedPathIndex(0);
    setSelectedNodeId(nextSelection.id);
    setGraphReplaySeed((seed) => seed + 1);
  }

  function selectNode(nodeId: string, layer?: string): void {
    if (layer === "role") {
      const nextSelection = roleSelection(recommendation, nodeId);
      if (nextSelection) {
        setSelection(nextSelection);
        setSelectedPathIndex(0);
      }
    }
    setSelectedNodeId(nodeId);
  }

  function replayGraph(): void {
    setGraphReplaySeed((seed) => seed + 1);
  }

  const selectedBundleActions = selectedBundleActionKeys
    .map((actionKey) => findActionByKey(targetAnalysis, actionKey))
    .filter((action): action is ActionCard => Boolean(action));

  const headerStats = recommendation?.graph_stats || catalog?.graph_stats || null;
  const notePills = [
    !status.busy && status.error ? { tone: "error", label: status.error } : null,
  ].filter(Boolean) as Array<{ tone: "error"; label: string }>;

  return {
    catalog,
    inputText,
    structuredSignals,
    confirmedSignals,
    confirmedSignalsDirty,
    recommendation,
    cards,
    selectedCard,
    selectedPath,
    selectedPathIndex,
    selectedSnapshotNode,
    targetRoleId,
    targetAnalysis,
    actionSimulation,
    selectedBundleActionKeys,
    selectedBundleActions,
    graphReplaySeed,
    headerStats,
    notePills,
    status,
    setInputText,
    setTargetRoleId: (value: string) => {
      setTargetRoleId(value);
      setTargetAnalysis(null);
      setTargetAnalysisSignature("");
      setActionSimulation(null);
      setSelectedBundleActionKeys([]);
    },
    addStructuredSignalRow,
    removeStructuredSignalRow,
    updateStructuredSignal,
    addConfirmedSignalRow,
    removeConfirmedSignalRow,
    updateConfirmedSignal,
    setConfirmedSignalEntity,
    submitInitialRecommendation,
    recomputeFromConfirmedSignals,
    applyDemoCase,
    applySampleRequest: () => {
      if (!catalog?.sample_request) {
        setError("示例请求尚未加载完成。");
        return;
      }
      applyInputPreset(catalog.sample_request);
      setSuccess("已载入示例输入。");
    },
    analyzeTargetRole,
    simulateAction,
    toggleActionBundle,
    clearActionBundle,
    simulateActionBundle,
    adoptSimulation,
    selectResult,
    setSelectedPathIndex,
    selectNode,
    replayGraph,
  };
}
