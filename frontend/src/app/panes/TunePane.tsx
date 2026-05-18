import { useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent } from "react";

import { formatPercent } from "../lib/scoring";
import { useRecommendationFlow } from "../hooks/useRecommendationFlow";
import { useReducedMotionPreference } from "../hooks/useReducedMotionPreference";

type Flow = ReturnType<typeof useRecommendationFlow>;

const SCORE_BANDS = [0.18, 0.35, 0.55, 0.75, 0.92] as const;

const BAND_LABELS: Record<string, string[]> = {
  constraint: ["轻微排斥", "有点排斥", "明显排斥", "强排斥", "硬约束"],
  interest: ["略感兴趣", "有兴趣", "偏好", "强偏好", "核心偏好"],
  project: ["接触过", "做过", "完整做过", "熟练复用", "代表项目"],
  soft_skill: ["一般", "可用", "稳定", "熟练", "强项"],
  skill: ["了解", "入门", "可用", "熟悉", "强项"],
  tool: ["了解", "入门", "可用", "熟悉", "强项"],
  knowledge: ["了解", "入门", "可用", "扎实", "强项"],
};

function bandIndex(score: number): number {
  let index = 0;
  for (const [currentIndex, threshold] of SCORE_BANDS.entries()) {
    if (score >= threshold) {
      index = currentIndex;
    }
  }
  return index;
}

function strengthLabel(flow: Flow, nodeId: string, nodeName: string, score: number): string {
  const catalogNode = flow.catalog?.evidence_nodes.find((node) => node.id === nodeId || node.name === nodeName);
  const text = `${nodeName} ${catalogNode?.description || ""}`;
  const type = /不喜欢|不擅长|排斥|弱|dislike|constraint/i.test(text) ? "constraint" : catalogNode?.node_type || "skill";
  return (BAND_LABELS[type] || BAND_LABELS.skill)[bandIndex(score)];
}

function displayName(signal: Flow["confirmedSignals"][number]): string {
  return signal.nodeName || signal.nodeId || "";
}

function clampSliderValue(value: number): number {
  return Math.min(100, Math.max(0, value));
}

function nearestSegmentScore(score: number): number {
  return Math.min(1, Math.max(0, Math.round(score * 10) / 10));
}

function nearestSegmentValue(value: number): number {
  return Math.round(nearestSegmentScore(value / 100) * 100);
}

function sliderProgressPercent(value: number): number {
  return clampSliderValue(value);
}

function easeInOutCubic(progress: number): number {
  return progress < 0.5 ? 4 * progress * progress * progress : 1 - Math.pow(-2 * progress + 2, 3) / 2;
}

function valueFromPointer(clientX: number, element: HTMLElement): number {
  const rect = element.getBoundingClientRect();
  const ratio = rect.width > 0 ? (clientX - rect.left) / rect.width : 0;
  return nearestSegmentValue(ratio * 100);
}

function keyboardTargetValue(current: number, key: string): number | null {
  const snapped = nearestSegmentValue(current);
  if (key === "ArrowRight" || key === "ArrowUp") {
    return Math.min(100, snapped + 10);
  }
  if (key === "ArrowLeft" || key === "ArrowDown") {
    return Math.max(0, snapped - 10);
  }
  if (key === "PageUp") {
    return Math.min(100, snapped + 20);
  }
  if (key === "PageDown") {
    return Math.max(0, snapped - 20);
  }
  if (key === "Home") {
    return 0;
  }
  if (key === "End") {
    return 100;
  }
  return null;
}

export function TunePane({ flow, onNext }: { flow: Flow; onNext: () => void }) {
  const evidenceNodes = flow.catalog?.evidence_nodes || [];
  const reducedMotion = useReducedMotionPreference();
  const [sliderPositions, setSliderPositions] = useState<Record<string, number>>({});
  const sliderAnimationFrames = useRef<Record<string, number>>({});
  const sliderPositionRef = useRef<Record<string, number>>({});
  const sliderTargetRef = useRef<Record<string, number>>({});
  const draggingSliderIdRef = useRef<string | null>(null);

  useEffect(
    () => () => {
      for (const frame of Object.values(sliderAnimationFrames.current)) {
        window.cancelAnimationFrame(frame);
      }
    },
    [],
  );

  function sliderValue(signal: Flow["confirmedSignals"][number]): number {
    return sliderPositions[signal.id] ?? nearestSegmentValue(signal.score * 100);
  }

  function cancelSliderAnimation(id: string): void {
    const frame = sliderAnimationFrames.current[id];
    if (frame !== undefined) {
      window.cancelAnimationFrame(frame);
      delete sliderAnimationFrames.current[id];
    }
  }

  function animateSliderTo(signal: Flow["confirmedSignals"][number], targetValue: number): void {
    const target = nearestSegmentValue(targetValue);
    if (sliderTargetRef.current[signal.id] === target) {
      return;
    }
    sliderTargetRef.current[signal.id] = target;
    const targetScore = target / 100;
    if (targetScore !== signal.score) {
      flow.updateConfirmedSignal(signal.id, { score: targetScore });
    }
    cancelSliderAnimation(signal.id);
    const start = sliderPositionRef.current[signal.id] ?? sliderValue(signal);
    if (reducedMotion || start === target) {
      sliderPositionRef.current[signal.id] = target;
      setSliderPositions((current) => ({ ...current, [signal.id]: target }));
      return;
    }

    const startedAt = window.performance.now();
    const duration = 240;
    const animate = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration);
      const eased = easeInOutCubic(progress);
      const nextPosition = start + (target - start) * eased;
      sliderPositionRef.current[signal.id] = nextPosition;
      setSliderPositions((current) => ({ ...current, [signal.id]: clampSliderValue(nextPosition) }));
      if (progress < 1) {
        sliderAnimationFrames.current[signal.id] = window.requestAnimationFrame(animate);
        return;
      }
      delete sliderAnimationFrames.current[signal.id];
      sliderPositionRef.current[signal.id] = target;
      setSliderPositions((current) => ({ ...current, [signal.id]: target }));
    };
    sliderAnimationFrames.current[signal.id] = window.requestAnimationFrame(animate);
  }

  function moveSliderToPointer(signal: Flow["confirmedSignals"][number], event: PointerEvent<HTMLDivElement>): void {
    animateSliderTo(signal, valueFromPointer(event.clientX, event.currentTarget));
  }

  function handleSliderPointerDown(signal: Flow["confirmedSignals"][number], event: PointerEvent<HTMLDivElement>): void {
    if (flow.status.busy) {
      return;
    }
    draggingSliderIdRef.current = signal.id;
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    moveSliderToPointer(signal, event);
  }

  function handleSliderPointerMove(signal: Flow["confirmedSignals"][number], event: PointerEvent<HTMLDivElement>): void {
    if (draggingSliderIdRef.current !== signal.id || flow.status.busy) {
      return;
    }
    moveSliderToPointer(signal, event);
  }

  function handleSliderPointerEnd(signal: Flow["confirmedSignals"][number], event: PointerEvent<HTMLDivElement>): void {
    if (draggingSliderIdRef.current === signal.id) {
      draggingSliderIdRef.current = null;
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function handleSliderKeyDown(signal: Flow["confirmedSignals"][number], rawValue: number, event: KeyboardEvent<HTMLDivElement>): void {
    const target = keyboardTargetValue(rawValue, event.key);
    if (target === null || flow.status.busy) {
      return;
    }
    event.preventDefault();
    animateSliderTo(signal, target);
  }

  async function continueToGraph() {
    if (!flow.confirmedSignals.length) {
      const ok = await flow.submitInitialRecommendation();
      if (!ok) {
        return;
      }
      onNext();
      return;
    }
    if (flow.confirmedSignalsDirty) {
      const ok = await flow.recomputeFromConfirmedSignals();
      if (!ok) {
        return;
      }
    }
    onNext();
  }

  return (
    <section className="pane pane-support tune-pane">
      <div className="pane-header">
        <div>
          <p className="section-kicker">Tune</p>
          <h2>微调画像</h2>
        </div>
        <div className="header-inline-actions">
          <button className="ghost-button header-peer-button" type="button" onClick={flow.addConfirmedSignalRow} disabled={flow.status.busy}>
            补节点
          </button>
          <button className="primary-button next-step-button" type="button" onClick={() => void continueToGraph()} disabled={flow.status.busy}>
            下一步：看图谱
          </button>
        </div>
      </div>

      <datalist id="evidence-node-options">
        {evidenceNodes.map((node) => (
          <option key={node.id} value={node.id}>
            {node.name}
          </option>
        ))}
      </datalist>

      <div className="pane-scroll tune-scroll">
        {flow.confirmedSignals.length ? (
          <div className="tune-list" aria-label="系统打分微调列表">
            {flow.confirmedSignals.map((signal) => {
              const rawSliderValue = sliderValue(signal);
              const displayValue = nearestSegmentValue(rawSliderValue);
              const displayScore = displayValue / 100;
              return (
                <article key={signal.id} className="tune-row">
                  <div className="tune-name">
                    <span>{signal.source === "manual" ? "手动" : "系统"}</span>
                    <input
                      className="tune-node-input"
                      list="evidence-node-options"
                      value={displayName(signal)}
                      onChange={(event) => flow.setConfirmedSignalEntity(signal.id, event.target.value)}
                      placeholder="节点名称"
                      disabled={flow.status.busy}
                    />
                  </div>
                  <div className="tune-control">
                    <div
                      className={`segmented-slider ${flow.status.busy ? "is-disabled" : ""}`}
                      style={
                        {
                          "--segment-progress": `${sliderProgressPercent(rawSliderValue)}%`,
                        } as CSSProperties & Record<"--segment-progress", string>
                      }
                      role="slider"
                      tabIndex={flow.status.busy ? -1 : 0}
                      aria-label={`${signal.nodeName || signal.nodeId} 十一档强度`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={displayValue}
                      aria-valuetext={formatPercent(displayScore)}
                      aria-disabled={flow.status.busy}
                      onPointerDown={(event) => handleSliderPointerDown(signal, event)}
                      onPointerMove={(event) => handleSliderPointerMove(signal, event)}
                      onPointerUp={(event) => handleSliderPointerEnd(signal, event)}
                      onPointerCancel={(event) => handleSliderPointerEnd(signal, event)}
                      onKeyDown={(event) => handleSliderKeyDown(signal, rawSliderValue, event)}
                    >
                      <div className="segmented-slider__thumb" aria-hidden="true" />
                    </div>
                    <strong>{formatPercent(displayScore)}</strong>
                    <em>{strengthLabel(flow, signal.nodeId, signal.nodeName, displayScore)}</em>
                    <button className="icon-button" type="button" onClick={() => flow.removeConfirmedSignalRow(signal.id)} disabled={flow.status.busy}>
                      ×
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="empty-slot">先在输入页生成系统打分。系统解析出的节点会默认显示在这里。</div>
        )}
      </div>
    </section>
  );
}
