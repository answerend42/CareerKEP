import { useEffect } from "react";

import { SourceProfileList } from "../components/SourceProfileList";
import { formatPercent } from "../lib/scoring";
import { useRecommendationFlow } from "../hooks/useRecommendationFlow";
import type { GapSuggestion, ResultCard, SourceRef } from "../types/api";

function scoreForCard(card: ResultCard): number {
  if (card.kind === "recommendation") {
    return card.score;
  }
  if (card.kind === "near_miss") {
    return card.near_miss_score;
  }
  return card.bridge_score;
}

function titleForCard(card: ResultCard): string {
  if (card.kind === "bridge") {
    return card.anchor_name;
  }
  return card.job_name;
}

function summaryForCard(card: ResultCard): string {
  if (card.kind === "recommendation") {
    return card.reason;
  }
  if (card.kind === "near_miss") {
    return card.gap_summary;
  }
  return card.summary;
}

function recommendationDegreeForCard(card: ResultCard): string {
  const score = formatPercent(scoreForCard(card));
  if (card.kind === "recommendation") {
    return `正式推荐（${score} 分）`;
  }
  if (card.kind === "near_miss") {
    return `临门一脚（${score} 分）`;
  }
  return `桥接方向（${score} 分）`;
}

function sourceRefsForCard(card: ResultCard): SourceRef[] {
  return card.source_refs || [];
}

function selectCard(flow: ReturnType<typeof useRecommendationFlow>, card: ResultCard) {
  if (card.kind === "recommendation") {
    flow.selectResult({ kind: "recommendation", id: card.job_id });
    return;
  }
  if (card.kind === "near_miss") {
    flow.selectResult({ kind: "near_miss", id: card.job_id });
    return;
  }
  flow.selectResult({ kind: "bridge", id: card.anchor_id });
}

function renderSuggestionChips(suggestions: GapSuggestion[]) {
  if (!suggestions.length) {
    return <div className="empty-slot compact">当前没有稳定的下一步建议。</div>;
  }
  return (
    <div className="chip-row">
      {suggestions.map((suggestion) => (
        <span key={`${suggestion.node_id}-${suggestion.tip}`} className="soft-chip accent-chip">
          {suggestion.tip} · {suggestion.node_name}
        </span>
      ))}
    </div>
  );
}

function SelectedResultDetail({
  card,
}: {
  card: ResultCard | null;
}) {
  if (!card) {
    return <div className="empty-slot">先生成推荐，再查看路径、限制与来源。</div>;
  }

  const topPaths = [...(card.paths || [])].sort((a, b) => b.score - a.score).slice(0, 5);
  const suggestions =
    card.kind === "bridge" ? card.next_steps : card.kind === "near_miss" ? card.suggestions : ([] as GapSuggestion[]);

  return (
    <section key={card.key} className="section-card detail-panel result-reveal">
      <div className="section-head result-detail-head">
        <div>
          <h3>{titleForCard(card)}</h3>
          <p>{summaryForCard(card)}</p>
        </div>
      </div>

      {topPaths.length ? (
        <ol className="path-cluster result-path-list">
          {topPaths.map((path, pathIndex) => (
            <li key={`${titleForCard(card)}-${path.score}-${pathIndex}`} className="result-path-row">
              <span className="score-badge path-score-badge">{formatPercent(path.score)}</span>
              <div className="path-track">
                {path.labels.map((label, labelIndex) => (
                  <div key={`${label}-${labelIndex}`} className="path-node">
                    <span>{label}</span>
                    {labelIndex < path.labels.length - 1 ? <i>→</i> : null}
                  </div>
                ))}
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <div className="empty-slot compact">当前卡片没有稳定路径，属于更稀疏的桥接结果。</div>
      )}

      <div className="detail-grid">
        <div className="mini-panel">
          <h4>限制与缺口</h4>
          {card.kind === "near_miss" && card.missing_requirements.length ? (
            <ul className="list-stack">
              {card.missing_requirements.map((item) => (
                <li key={item}>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          ) : card.limitations.length ? (
            <ul className="list-stack">
              {card.limitations.map((item) => (
                <li key={item}>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="empty-slot compact">当前没有额外限制说明。</div>
          )}
        </div>
        <div className="mini-panel">
          <h4>下一步建议</h4>
          {renderSuggestionChips(suggestions)}
          {card.kind === "bridge" && card.related_roles.length ? (
            <div className="chip-row top-gap">
              {card.related_roles.map((role) => (
                <span key={role.job_id} className="soft-chip">
                  {role.job_name}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mini-panel">
        <h4>来源锚点</h4>
        <SourceProfileList sources={sourceRefsForCard(card)} emptyText="这个结果卡片当前没有来源锚点。" />
      </div>
    </section>
  );
}

export function ResultPane({ flow }: { flow: ReturnType<typeof useRecommendationFlow> }) {
  const resultGroups = [
    {
      key: "recommendation" as const,
      label: "推荐",
      title: "Strong Match",
      description: "直接穿透岗位门槛的正式推荐。",
      empty: flow.recommendation?.empty_result_reason || "当前还没有正式推荐。",
      cards: flow.cards.recommendations,
    },
    {
      key: "near_miss" as const,
      label: "临门一脚",
      title: "Near Miss",
      description: "已经被激活，但还差关键前置或核心支撑。",
      empty: "当前没有需要重点补缺口的岗位。",
      cards: flow.cards.nearMisses,
    },
    {
      key: "bridge" as const,
      label: "桥接",
      title: "Bridge",
      description: "给稀疏输入准备的桥接方向，避免空白结果页。",
      empty: "当前没有桥接方向。",
      cards: flow.cards.bridges,
    },
  ];
  const roleResultCards: ResultCard[] = [
    ...flow.cards.recommendations,
    ...flow.cards.nearMisses,
  ];
  const allResultCards: ResultCard[] = [
    ...roleResultCards,
    ...flow.cards.bridges,
  ];
  const selectableResultCards = roleResultCards.length ? roleResultCards : allResultCards;
  const activeResultCard = flow.selectedCard && selectableResultCards.some((card) => card.key === flow.selectedCard?.key)
    ? flow.selectedCard
    : selectableResultCards[0] || null;
  const emptyResultText = resultGroups.find((group) => !group.cards.length)?.empty || "当前还没有可解释的推荐结果。";

  useEffect(() => {
    if (!selectableResultCards.length) {
      return;
    }

    if (!activeResultCard || !selectableResultCards.some((card) => card.key === activeResultCard.key)) {
      selectCard(flow, selectableResultCards[0]);
    }
  }, [activeResultCard, flow, selectableResultCards]);

  return (
    <section className="pane pane-results">
      <div className="pane-scroll">
          <div className="result-browser">
            <div className="result-browser-head">
              <h3>结果解释</h3>
              <label className="field-block result-picker result-select-field" htmlFor="result-card-select">
                <select
                  id="result-card-select"
                  className="editor-select result-select-control"
                  value={activeResultCard?.key || ""}
                  onChange={(event) => {
                    const nextCard = selectableResultCards.find((card) => card.key === event.target.value);
                    if (nextCard) {
                      selectCard(flow, nextCard);
                    }
                  }}
                >
                  {selectableResultCards.map((card) => (
                    <option key={card.key} value={card.key}>
                      {titleForCard(card)}
                    </option>
                  ))}
                </select>
              </label>
              <strong className="result-degree">{activeResultCard ? recommendationDegreeForCard(activeResultCard) : "暂无推荐"}</strong>
            </div>

            {selectableResultCards.length ? (
              <SelectedResultDetail card={activeResultCard} />
            ) : (
              <div className="empty-slot compact">{emptyResultText}</div>
            )}
          </div>
      </div>
    </section>
  );
}
