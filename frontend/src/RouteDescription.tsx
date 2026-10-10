/**
 * The route summary's "Route description" (OWNER-DECISIONS 220): the route in
 * words, stretch by stretch, for riders who hear it rather than see the map -
 * many blind cyclists ride as tandem stokers. A component of its own so App.tsx
 * only places it.
 *
 * - A heading, so a screen reader can jump to it.
 * - A disclosure button (aria-expanded) over an ordered list: closed unless the
 *   rider has opened it before. Nothing is announced when the route changes;
 *   the list just updates.
 * - One sentence to an item, with the severity and the tier in words, never in
 *   colour alone.
 * - A "Full detail" checkbox (only where the overview is shorter): the overview
 *   merges short stretches, the full list shows every entry; remembered.
 * - "Copy description" and "Download as text" (a cue sheet, no network) take
 *   whichever view is shown.
 *
 * In the sidebar redesign (OWNER-DECISIONS 312) it is also "Directions (N steps)", one of the route
 * summary's folds: `fold` draws the same list, checkbox and buttons inside a native <details> with
 * that summary, in place of its own heading and toggle button. Without `fold` it is as it was.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { RouteResponse } from "./lib/api.ts";
import "./routeDescription.css";
import { useHighStressLanes } from "./useStressStyle.ts";
import { ROUTE_FOLDS, copyText, foldTitle, selectionCopy, stepsCount } from "./lib/sidebar.ts";
import { Fold } from "./lib/sidebarParts.ts";
import {
  DESCRIPTION_HEADING,
  chevron,
  crossingsOf,
  cueSheetFileName,
  descriptionEntries,
  type DescriptionView,
  descriptionText,
  capacityLead,
  hasOverview,
  lanesHiddenNote,
  readOpen,
  readView,
  toggleLabel,
  toggleName,
  viewFor,
  writeOpen,
  writeView,
} from "./lib/routeDescription.ts";

/** How long the copy reply waits after clearing, so that it is a change a screen reader says. */
export const COPY_REPLY_DELAY_MS = 150;

function copy(text: string): Promise<boolean> {
  return copyText(text, navigator.clipboard, selectionCopy);
}

export function RouteDescription({
  route,
  fold = false,
  rideAction = null,
  federal = [],
}: {
  route: RouteResponse;
  fold?: boolean;
  /**
   * A Mass Ride's federal-land lines (lib/federalStops.ts federalLines, item 239): the heading
   * line, the stops on federal land and the parkway stretches; empty elsewhere.
   */
  federal?: readonly string[];
  /** Ride mode's Start ride, offered with the directions too (WEB-NAV-plan.md Q1, OWNER-DECISIONS 465). */
  rideAction?: ReactNode;
}) {
  const [open, setOpen] = useState<boolean>(() => readOpen());
  const [chosen, setChosen] = useState<DescriptionView>(() => readView());
  const choice = hasOverview(route);
  const view = viewFor(route, chosen);
  const showHighLanes = useHighStressLanes(); // the entries and the text follow the "Show bike lanes on high-stress roads" switch
  const entries = descriptionEntries(route, view, showHighLanes);
  const hiddenNote = lanesHiddenNote(route, view, showHighLanes);
  // A Mass Ride's riders per minute, said first (OWNER-DECISIONS 325); null on every other ride type.
  const lead = capacityLead(route);
  // Said only after the rider presses Copy: a reply to their action, not a
  // announcement about the route.
  const [copied, setCopied] = useState<"" | "done" | "failed">("");
  // Which press the status line answers: a reply to an earlier one is dropped.
  const presses = useRef(0);
  const listId = useId();
  // A confirmation of one press is not left standing over the next route.
  useEffect(() => setCopied(""), [route.description]);
  if (entries === null) return null;

  const toggle = () => {
    setOpen(!open);
    writeOpen(!open);
  };
  const onView = (full: boolean) => {
    const next: DescriptionView = full ? "full" : "overview";
    setChosen(next);
    writeView(next);
  };
  const onCopy = async () => {
    // Cleared first and set again a moment later, so a second press is said
    // again: the same words written over themselves change nothing a screen
    // reader hears (a11y re-check of 2b0cf00).
    const press = ++presses.current;
    setCopied("");
    const done = await copy(descriptionText(route, view, federal));
    window.setTimeout(() => {
      if (press === presses.current) setCopied(done ? "done" : "failed");
    }, COPY_REPLY_DELAY_MS);
  };
  const onDownload = () => {
    const blob = new Blob([descriptionText(route, view, federal)], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = cueSheetFileName(route);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  const items = entries.map((entry, i) => {
    const crossings = crossingsOf(entry);
    return (
      <li key={i} className={`description-${entry.kind}`}>
        {entry.text}
        {crossings.length > 0 ? (
          // A group's crossings, each with its mile marker (OWNER-DECISIONS 248).
          <ol className="description-crossings" aria-label="Crossings in this group, in route order">
            {crossings.map((crossing, k) => (
              <li key={k}>{crossing.text}</li>
            ))}
          </ol>
        ) : null}
      </li>
    );
  });

  // Named in the list's own words, before the steps (item 239): a reader who cannot point at the map's
  // shading hears which stops are on federal land and which stretches are on a parkway.
  const federalBlock = (hidden: boolean) =>
    federal.length > 0 ? (
      <div className="federal-route" hidden={hidden}>
        <p className="federal-route-heading" id={`${listId}-federal`}>
          {federal[0]}
        </p>
        <ul aria-labelledby={`${listId}-federal`}>
          {federal.slice(1).map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      </div>
    ) : null;

  const actions = (
    <div className="actions description-actions">
      <button type="button" onClick={onCopy}>
        Copy description
      </button>
      <button type="button" onClick={onDownload}>
        Download as text
      </button>
      {rideAction}
      <span role="status" className="hint description-status">
        {copied === "done" ? "Copied." : copied === "failed" ? "Could not copy. Use Download as text." : ""}
      </span>
    </div>
  );

  if (fold) {
    // No fold for a route with no steps ("Directions (0 steps)": the correctness review's N9). Its h3
    // comes first, out of sight, so a screen reader still jumps to the directions by heading (the a11y
    // review's S5); the fold itself is lib/sidebarParts.ts Fold, which a test renders.
    if (entries.length === 0) return null;
    return (
      <Fold
        title={foldTitle(ROUTE_FOLDS.directions.title, stepsCount(entries.length))}
        heading={ROUTE_FOLDS.directions.title}
        headingId="route-description-heading"
        open={open}
        className="route-description"
        onToggle={(now) => {
          if (now !== open) {
            setOpen(now);
            writeOpen(now);
          }
        }}
      >
        {choice ? (
          <label className="description-view">
            <input type="checkbox" checked={view === "full"} onChange={(e) => onView(e.target.checked)} />
            Full detail
          </label>
        ) : null}
        {lead && <p className="hint capacity-lead">{lead}</p>}
        {federalBlock(false)}
        {hiddenNote && <p className="hint lanes-hidden">{hiddenNote}</p>}
        <ol className="description-list">{items}</ol>
        {actions}
      </Fold>
    );
  }

  return (
    <section className="route-description" aria-labelledby="route-description-heading">
      <h3 id="route-description-heading">{DESCRIPTION_HEADING}</h3>
      <button
        type="button"
        className="description-toggle"
        aria-label={toggleName(entries, view, choice)}
        aria-expanded={open}
        aria-controls={listId}
        onClick={toggle}
      >
        <span aria-hidden="true">{chevron(open)} </span>
        {toggleLabel(entries, view, choice)}
      </button>
      {choice ? (
        <label className="description-view">
          <input type="checkbox" checked={view === "full"} onChange={(e) => onView(e.target.checked)} />
          Full detail
        </label>
      ) : null}
      {/* No scroll box of its own: the panel scrolls, so the list is read and
          scrolled like the rest of it by keyboard in every browser (a11y re-check
          of 2b0cf00, 2.1.1), with no extra Tab stop. */}
      {lead && (
        <p className="hint capacity-lead" hidden={!open}>
          {lead}
        </p>
      )}
      {federalBlock(!open)}
      {hiddenNote && (
        <p className="hint lanes-hidden" hidden={!open}>
          {hiddenNote}
        </p>
      )}
      <ol id={listId} className="description-list" hidden={!open}>
        {items}
      </ol>
      {actions}
    </section>
  );
}
