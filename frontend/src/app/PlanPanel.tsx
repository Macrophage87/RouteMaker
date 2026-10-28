/**
 * Plan mode's plan panel (v0.7.0, "Plan mode: write the plan first, then route"; lib/planFirst.ts): the Route
 * button (Enter or Ctrl+Enter from the panel), which becomes a progress bar with its step, the seconds and Cancel
 * while routing; the one-line summary of what an update changed; and Reset and Clear behind "More".
 *
 * Plan streamline (Stephen 2026-10-17): the plan in plain sentences is no longer shown, since the points and the
 * ride chips above say the same; it is the Route button's description, so a screen reader still hears the plan
 * whole. "Up to date" is said on the button itself, and Reset and Clear sit behind one "More" button.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { t } from "../lib/i18n.ts";
import { FINDING_LOCATION } from "../lib/geolocation.ts";
import { CLEAR_LABEL, RESET_LABEL, ROUTE_UP_TO_DATE, type Phrase } from "../lib/planFirst.ts";

export interface PlanPanelProps {
  sentences: Phrase[][];
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
  /**
   * With no point yet, Route's place holds "Start at current location" (Stephen 2026-10-20: "where it currently has
   * route, have a button that says start at current location when no route has started"); null once there is a
   * start. `busy` while the location is being found; `unavailable` why this browser cannot find it, or null.
   */
  locate?: { onLocate: () => void; busy: boolean; unavailable: string | null } | null;
}

/** The button in Route's place on an empty plan. */
export const START_HERE_LABEL = t("Start at current location");

export function PlanPanel(props: PlanPanelProps) {
  const { sentences, button, onRoute, routing, onCancel, change, details, onCloseChange, resetUnavailable, onReset, clearDisabled, onClear, locate } = props;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const moreId = useId();
  const planId = useId();
  const upToDate = button.unavailable === ROUTE_UP_TO_DATE;
  const detailsId = useId();
  const routeWhy = useId();
  const resetWhy = useId();
  const busyId = useId();
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
      <h2 id="plan-panel-heading" className="visually-hidden">
        {t("Your plan")}
      </h2>
      {/* The plan in words, out of sight: the Route button's description (the points and ride chips show it). */}
      <p id={planId} className="visually-hidden plan-sentences">
        {sentences.map((sentence) => sentence.map((phrase) => phrase.text).join("")).join(" ")}
      </p>
      {routing ? (
        <div className="plan-routing" role="group" aria-label={t("Routing")}>
          <progress className="planning" aria-label={t("Planning route: {step}", { step: routing.step })} />
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
            {t("Cancel")}
          </button>
        </div>
      ) : (
        <div className="plan-route">
          {locate ? (
            // aria-disabled, not disabled, as Use my location is (PlaceSearch.tsx): it stays in the Tab order with its
            // reason as its description; a press while finding starts no second look-up, and is answered again.
            <button
              type="button"
              className="route-button start-here"
              aria-disabled={locate.unavailable !== null || locate.busy || undefined}
              aria-describedby={`${locate.unavailable ? `${routeWhy} ` : locate.busy ? `${busyId} ` : ""}${planId}`}
              onClick={() => {
                if (locate.unavailable === null) locate.onLocate();
              }}
            >
              {START_HERE_LABEL}
            </button>
          ) : (
            <button
              type="button"
              ref={routeRef}
              className="route-button"
              aria-disabled={button.unavailable ? true : undefined}
              aria-describedby={button.unavailable ? `${routeWhy} ${planId}` : planId}
              aria-keyshortcuts="Control+Enter Meta+Enter"
              onFocus={() => (routeHadFocus.current = true)}
              onBlur={(event) => {
                if (event.relatedTarget) routeHadFocus.current = false;
              }}
              onClick={route}
            >
              {button.label}
              {upToDate && (
                <span className="route-state" aria-hidden="true">
                  {" "}{t("✓ up to date")}
                </span>
              )}
            </button>
          )}
          {locate?.busy && (
            <span id={busyId} className="visually-hidden">
              {FINDING_LOCATION}
            </span>
          )}
          {locate?.unavailable && (
            <span id={routeWhy} className="hint">
              {locate.unavailable}
            </span>
          )}
          {button.unavailable && !locate && (
            // Said with the button, not shown: the points above show what is missing (Stephen 2026-10-20: "it needs to
            // be simpler, still a wall of text").
            <span id={routeWhy} className="visually-hidden">
              {button.unavailable}
            </span>
          )}
          {/* Reset and Clear, behind one button (Plan streamline). */}
          <button
            type="button"
            className="secondary icon-button plan-more"
            aria-expanded={moreOpen}
            aria-controls={moreId}
            aria-label={t("More: Reset and Clear")}
            onClick={() => setMoreOpen(!moreOpen)}
          >
            <span aria-hidden="true">⋯</span>
          </button>
        </div>
      )}
      {change && (
        <p className="plan-change">
          <span>{change}</span>
          {details.length > 0 && (
            <button type="button" className="link" aria-expanded={detailsOpen} aria-controls={detailsId} onClick={() => setDetailsOpen(!detailsOpen)}>
              {t("Details")}<span className="visually-hidden">{" "}{t("by leg")}</span>
            </button>
          )}
          <button type="button" className="secondary icon-button" aria-label={t("Close the change summary")} onClick={onCloseChange}>
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
      <div id={moreId} className="actions plan-reset-clear" hidden={!moreOpen}>
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
