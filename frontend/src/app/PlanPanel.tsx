/**
 * Plan mode's plan panel (v0.7.0, "Plan mode: write the plan first, then route"; lib/planFirst.ts): the progress bar
 * with its step, the seconds and Cancel while routing; the one-line summary of what an update changed; and Reset.
 *
 * Plan streamline (Stephen 2026-10-17): the plan in plain sentences is no longer shown, since the points and the
 * ride chips above say the same; it is the panel's description, so a screen reader still hears the plan whole.
 *
 * One of each control (Plan on a phone, P10): Route is Plan's bar's at the top of the map (the owner, 2026-10-17),
 * no longer here too; Enter or Ctrl+Enter from the panel still routes. Clear is the bar's trash, so Reset is the
 * panel's one button, shown with the plan changed; a route up to date shows no row, and says so out of sight.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { t } from "../lib/i18n.ts";
import { FINDING_LOCATION } from "../lib/geolocation.ts";
import { RESET_LABEL, planRowShown, type Phrase } from "../lib/planFirst.ts";

export interface PlanPanelProps {
  sentences: Phrase[][];
  /** The Route button's label, and why it does nothing now (null: it routes). The button is Plan's bar's. */
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
  /**
   * With no point yet, the panel holds "Start at current location" (Stephen 2026-10-20: "where it currently has
   * route, have a button that says start at current location when no route has started"); null once there is a
   * start. `busy` while the location is being found; `unavailable` why this browser cannot find it, or null.
   */
  locate?: { onLocate: () => void; busy: boolean; unavailable: string | null } | null;
}

/** The button on an empty plan. */
export const START_HERE_LABEL = t("Start at current location");

export function PlanPanel(props: PlanPanelProps) {
  const { sentences, button, onRoute, routing, onCancel, change, details, onCloseChange, resetUnavailable, onReset, locate } = props;
  const [detailsOpen, setDetailsOpen] = useState(false);
  const planId = useId();
  const detailsId = useId();
  const routeWhy = useId();
  const resetWhy = useId();
  const busyId = useId();
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  // Routing started from the panel (Enter): the focus goes to Cancel, and back to the panel when it ends.
  const panelHadFocus = useRef(false);
  useEffect(() => {
    if (routing && panelHadFocus.current) cancelRef.current?.focus();
    else if (!routing && panelHadFocus.current && document.activeElement === document.body) panelRef.current?.focus();
  }, [routing !== null]);
  const route = () => {
    if (button.unavailable === null && !routing) onRoute();
  };
  // Enter on the panel itself, or Ctrl+Enter (Cmd+Enter) anywhere in it, routes; Enter on a link opens its editor.
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Enter") return;
    if (!(event.ctrlKey || event.metaKey) && event.target !== event.currentTarget) return;
    event.preventDefault();
    panelHadFocus.current = true;
    route();
  };
  const rowShown = planRowShown({ routing: routing !== null, locate: !!locate, unavailable: button.unavailable });
  return (
    <section
      ref={panelRef}
      className={routing || rowShown || change ? "plan-panel" : "plan-panel plan-panel-quiet"}
      aria-labelledby="plan-panel-heading"
      aria-describedby={planId}
      aria-keyshortcuts="Control+Enter Meta+Enter"
      tabIndex={-1}
      onKeyDown={onKeyDown}
      onBlur={(event) => {
        if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget as Node)) panelHadFocus.current = false;
      }}
    >
      <h2 id="plan-panel-heading" className="visually-hidden">
        {t("Your plan")}
      </h2>
      {/* The plan in words, out of sight: the panel's description (the points and ride chips show it). */}
      <p id={planId} className="visually-hidden plan-sentences">
        {sentences.map((sentence) => sentence.map((phrase) => phrase.text).join("")).join(" ")}
      </p>
      {/* Why Route is not offered now ("The route shown is up to date."), said, not shown: the bar has no Route then. */}
      {button.unavailable && !locate && !routing && (
        <p id={routeWhy} className="visually-hidden plan-route-state">
          {button.unavailable}
        </p>
      )}
      {routing ? (
        <div className="plan-routing" role="group" aria-label={t("Routing")}>
          <progress className="planning" aria-label={t("Planning route: {step}", { step: routing.step })} />
          <span className="plan-step">
            {routing.step}… <span className="plan-elapsed">{routing.elapsed}</span>
          </span>
          <button type="button" ref={cancelRef} className="secondary" onClick={onCancel}>
            {t("Cancel")}
          </button>
        </div>
      ) : rowShown ? (
        <div className="plan-route">
          {locate && (
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
          {/* Reset, the panel's one button (Clear is the bar's trash). aria-disabled with its reason, never removed. */}
          {!locate && (
            <button
              type="button"
              className="secondary plan-reset"
              aria-disabled={resetUnavailable ? true : undefined}
              aria-describedby={resetUnavailable ? resetWhy : undefined}
              title={resetUnavailable ?? undefined}
              onClick={() => {
                if (!resetUnavailable) onReset();
              }}
            >
              {RESET_LABEL}
            </button>
          )}
          {resetUnavailable && !locate && (
            <span id={resetWhy} className="visually-hidden">
              {resetUnavailable}
            </span>
          )}
        </div>
      ) : null}
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
    </section>
  );
}
