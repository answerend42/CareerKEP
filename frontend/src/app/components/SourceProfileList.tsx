import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { sourceTypeLabel } from "../lib/scoring";
import type { SourceRef } from "../types/api";

function sourceTitle(source: SourceRef): string {
  return source.source_title || source.source_id || source.profile_id;
}

function sourceMeta(source: SourceRef): string {
  return sourceTypeLabel(source.source_type);
}

export function SourceProfileList({
  sources,
  emptyText,
  compact = false,
}: {
  sources: SourceRef[];
  emptyText: string;
  compact?: boolean;
}) {
  const [activeSource, setActiveSource] = useState<SourceRef | null>(null);

  useEffect(() => {
    if (!activeSource) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setActiveSource(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeSource]);

  if (!sources.length) {
    return <div className="empty-slot compact">{emptyText}</div>;
  }

  return (
    <>
      <ul className={`source-list ${compact ? "compact-list" : ""}`}>
        {sources.slice(0, 4).map((source) => (
          <li key={`${source.profile_id}-${source.source_id}`}>
            <button className="source-link" type="button" onClick={() => setActiveSource(source)}>
              <strong>{sourceTitle(source)}</strong>
              <span>{sourceMeta(source)}</span>
            </button>
          </li>
        ))}
      </ul>

      {activeSource
        ? createPortal(
            <div className="source-popover-backdrop" role="presentation" onClick={() => setActiveSource(null)}>
              <section
                className="source-popover"
                role="dialog"
                aria-modal="true"
                aria-label="来源画像详情"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="source-popover-head">
                  <div>
                    <p className="micro-label">{sourceMeta(activeSource) || "来源画像"}</p>
                    <h3>{sourceTitle(activeSource)}</h3>
                  </div>
                  <button className="icon-button" type="button" aria-label="关闭来源浮窗" onClick={() => setActiveSource(null)}>
                    ×
                  </button>
                </div>

                <div className="source-popover-body">
                  <div className="source-popover-section">
                    <span>相关内容</span>
                    <p>{activeSource.evidence_snippet || "当前来源没有可展示的摘录内容。"}</p>
                  </div>

                  {activeSource.sample_job_titles?.length ? (
                    <div className="source-popover-section">
                      <span>样例岗位</span>
                      <div className="chip-row">
                        {activeSource.sample_job_titles.slice(0, 6).map((title) => (
                          <span key={title} className="soft-chip">
                            {title}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <dl className="source-popover-kv">
                    <div>
                      <dt>Profile</dt>
                      <dd>{activeSource.profile_id || "-"}</dd>
                    </div>
                    <div>
                      <dt>Source</dt>
                      <dd>{activeSource.source_id || "-"}</dd>
                    </div>
                  </dl>

                  {activeSource.source_url ? (
                    <a className="source-popover-url" href={activeSource.source_url} target="_blank" rel="noreferrer">
                      打开外部来源
                    </a>
                  ) : null}
                </div>
              </section>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
