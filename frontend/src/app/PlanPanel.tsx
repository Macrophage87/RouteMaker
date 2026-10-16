/**
 * Plan mode's plan panel (v0.7.0, "Plan mode: write the plan first, then route"; lib/planFirst.ts): the plan in
 * plain sentences, each name and setting a link to its editor; the Route button (Enter or Ctrl+Enter from the
 * panel), which becomes a progress bar with its step, the seconds and Cancel while routing; the one-line summary
 * of what an update changed; and Reset and Clear side by side.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { CLEAR_LABEL, RESET_LABEL, type Phrase, type PhraseTarget } from "../lib/planFirst.ts";

export interface PlanPanelProps {
  sentences: Phrase[][];
  onPhrase: (target: PhraseTarget) => void;
  /** The Route button's label, and why it does nothing now (null: it routes). */
  button: { label: string; unavailable: string | null };
  onRoute: () => void;
  /** While routing: the step in words and the seconds elapsed; null otherwise. */
  routing: { step: string; elapsed: string } | null;
  onCancel: () => void;
  /** What the last update changed, until the next change or its close; null otherwise. */
  change: string | null;
  /** The per-leg details behind the summary's Details (lib/planFirst.ts legChanges); empty: no Details. */
  details: readonly string[];
  onCloseChange: () => void;
  /** Why Reset does nothing now (null: it resets). */
  resetUnavailable: string | null;
  onReset: () => void;
  clearDisabled: boolean;
  onClear: () => void;
}

export function PlanPanel(props: PlanPanelProps) {
  const { sentences, onPhrase, button, onRoute, routing, onCancel, change, details, onCloseChange, resetUnavailable, onReset, clearDisabled, onClear } = props;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const detailsId = useId();
  const routeWhy = useId();
  const resetWhy = useId();
  const routeRef = useRef<HTMLButtonElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const routeHadFocus = useRef(false);
  // The Route button becomes the progress bar and Cancel while routing: the focus goes with it, and back.
  useEffect(() => {
    if (routing && routeHadFocus.current) cancelRef.current?.focus();
    else if (!routing && cancelRef.current === null && routeHadFocus.current) routeRef.current?.focus();
  }, [routing !== null]);
  const route = () => {
    if (button.unavailable === null && !routing) onRoute();
  };
  // Enter on the panel itself, or Ctrl+Enter (Cmd+Enter) anywhere in it, routes; Enter on a link opens its editor.
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Enter") return;
    if (!(event.ctrlKey || event.metaKey) && event.target !== event.currentTarget) return;
    event.preventDefault();
    route();
  };
  return (
    <section className="plan-panel" aria-labelledby="plan-panel-heading" tabIndex={-1} onKeyDown={onKeyDown}>
      <h2 id="plan-panel-heading">Your plan</h2>
      <p className="plan-sentences">
        {sentences.map((sentence, i) => (
          <span key={i} className="plan-sentence">
            {sentence.map((phrase, j) =>
              phrase.target ? (
                <button key={j} type="button" className="link plan-phrase" onClick={() => onPhrase(phrase.target as PhraseTarget)}>
                  {phrase.text}
                </button>
              ) : (
                <span key={j}>{phrase.text}</span>
              ),
            )}{" "}
          </span>
        ))}
      </p>
      {routing ? (
        <div className="plan-routing" role="group" aria-label="Routing">
          <progress className="planning" aria-label={`Planning route: ${routing.step}`} />
          <span className="plan-step">
            {routing.step}… <span className="plan-elapsed">{routing.elapsed}</span>
          </span>
          <button
            type="button"
            ref={cancelRef}
            className="secondary"
            onBlur={(event) => {
              // The rider moved on: the focus is not brought back to Route when the routing ends.
              if (event.relatedTarget) routeHadFocus.current = false;
            }}
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="plan-route">
          <button
            type="button"
            ref={routeRef}
            className="route-button"
            aria-disabled={button.unavailable ? true : undefined}
            aria-describedby={button.unavailable ? routeWhy : undefined}
            aria-keyshortcuts="Control+Enter Meta+Enter"
            onFocus={() => (routeHadFocus.current = true)}
            onBlur={(event) => {
              if (event.relatedTarget) routeHadFocus.current = false;
            }}
            onClick={route}
          >
            {button.label}
          </button>
          {button.unavailable && (
            <span id={routeWhy} className="hint">
              {button.unavailable}
            </span>
          )}
        </div>
      )}
      {change && (
        <p className="plan-change">
          <span>{change}</span>
          {details.length > 0 && (
            <button type="button" className="link" aria-expanded={detailsOpen} aria-controls={detailsId} onClick={() => setDetailsOpen(!detailsOpen)}>
              Details<span className="visually-hidden"> by leg</span>
            </button>
          )}
          <button type="button" className="secondary icon-button" aria-label="Close the change summary" onClick={onCloseChange}>
            ×
          </button>
        </p>
      )}
      {change && details.length > 0 && (
        <ul id={detailsId} className="plan-change-details" hidden={!detailsOpen}>
          {details.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <div className="actions plan-reset-clear">
        <button
          type="button"
          className="secondary"
          aria-disabled={resetUnavailable ? true : undefined}
          aria-describedby={resetUnavailable ? resetWhy : undefined}
          title={resetUnavailable ?? undefined}
          onClick={() => {
            if (!resetUnavailable) onReset();
          }}
        >
          {RESET_LABEL}
        </button>
        {/* aria-disabled, not disabled: after a press empties the plan the button keeps the focus (review a11y-1). */}
        <button
          type="button"
          className="secondary"
          aria-disabled={clearDisabled || undefined}
          onClick={() => {
            if (!clearDisabled) onClear();
          }}
        >
          {CLEAR_LABEL}
        </button>
        {resetUnavailable && (
          <span id={resetWhy} className="visually-hidden">
            {resetUnavailable}
          </span>
        )}
      </div>
    </section>
  );
}
