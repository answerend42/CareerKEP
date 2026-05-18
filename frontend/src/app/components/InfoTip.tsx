import { useState, type FocusEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";

export function InfoTip({ text }: { text: string }) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null);

  function show(event: MouseEvent<HTMLSpanElement> | FocusEvent<HTMLSpanElement>) {
    setAnchor(event.currentTarget.getBoundingClientRect());
  }

  function hide() {
    setAnchor(null);
  }

  return (
    <>
      <span className="info-tip" tabIndex={0} aria-label={text} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide}>
        i
      </span>
      {anchor
        ? createPortal(
            <span
              className="info-tip-bubble info-tip-bubble--floating"
              style={{
                left: Math.min(window.innerWidth - 340, Math.max(12, anchor.right - 320)),
                top: Math.min(window.innerHeight - 140, anchor.bottom + 8),
              }}
              aria-hidden="true"
            >
              {text}
            </span>,
            document.body,
          )
        : null}
    </>
  );
}
