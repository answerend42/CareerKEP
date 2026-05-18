import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { useRecommendationFlow } from "./hooks/useRecommendationFlow";
import { useReducedMotionPreference } from "./hooks/useReducedMotionPreference";
import { pageTransitionFor } from "./lib/motionTokens";
import { GraphPane } from "./panes/GraphPane";
import { InputPane } from "./panes/InputPane";
import { ResultPane } from "./panes/ResultPane";
import { TunePane } from "./panes/TunePane";

type PageKey = "input" | "tune" | "graph" | "results";

export function AppShell() {
  const flow = useRecommendationFlow();
  const reducedMotion = useReducedMotionPreference();
  const [activePage, setActivePage] = useState<PageKey>("input");
  const pages = [
    {
      key: "input" as const,
      index: "01",
      label: "输入画像",
      render: <InputPane flow={flow} onNext={() => setActivePage("tune")} />,
    },
    {
      key: "tune" as const,
      index: "02",
      label: "微调画像",
      render: <TunePane flow={flow} onNext={() => setActivePage("graph")} />,
    },
    {
      key: "graph" as const,
      index: "03",
      label: "图谱传播",
      render: <GraphPane flow={flow} onNext={() => setActivePage("results")} />,
    },
    {
      key: "results" as const,
      index: "04",
      label: "结果解释",
      render: <ResultPane flow={flow} />,
    },
  ];
  const activePageMeta = pages.find((page) => page.key === activePage) || pages[0];
  const activePageIndex = pages.findIndex((page) => page.key === activePage);
  const previousPage = activePageIndex > 0 ? pages[activePageIndex - 1] : null;
  const pageMotion = pageTransitionFor(reducedMotion);

  return (
    <div className="app-shell app-shell--pager">
      <nav className="presentation-nav" aria-label="演示页面切换">
        <div className="deck-title">
          <span>Career KG</span>
          <strong>知识图谱职业推荐</strong>
        </div>

        <div className="page-tabs" role="tablist" aria-label="演示步骤">
          {pages.map((page) => (
            <button
              key={page.key}
              className={`page-tab ${activePage === page.key ? "is-active" : ""}`}
              type="button"
              role="tab"
              aria-selected={activePage === page.key}
              onClick={() => setActivePage(page.key)}
            >
              <span>{page.index}</span>
              <strong>{page.label}</strong>
            </button>
          ))}
        </div>

        <div className="deck-actions">
          {flow.notePills.length ? (
            <div className="global-status" aria-live="polite">
              {flow.notePills.map((note) => (
                <span key={`${note.tone}:${note.label}`} className={`note-pill is-${note.tone}`}>
                  {note.label}
                </span>
              ))}
            </div>
          ) : null}
          {previousPage ? (
            <button className="ghost-button compact-control" type="button" onClick={() => setActivePage(previousPage.key)}>
              上一步
            </button>
          ) : null}
        </div>
      </nav>

      <main className="presentation-page">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={activePageMeta.key}
            className={`presentation-slide motion-page motion-page--${activePageMeta.key}`}
            initial={pageMotion.initial}
            animate={pageMotion.animate}
            exit={pageMotion.exit}
            transition={pageMotion.transition}
          >
            {activePageMeta.render}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
