/**
 * A Rebalance Ride at its crowded dock: where to dock, from the live counts there (lib/rebalanceDock.ts). Shown in the
 * ride's card in place of the cue, until a dock is chosen.
 */
import { useEffect, useRef } from "react";
import type { LonLat } from "./lib/geo.ts";
import { DOCK_CHOOSE_HEADING, DOCK_CHOOSE_LEDE, DOCK_RETRY, dockAsPlanned, dockChoiceLine, type DockChoice } from "./lib/rebalanceDock.ts";

/** Choosing where to dock: the crowded dock, how far it has got, the docks found, and the plan's own dock. */
export interface DockAsk {
  at: LonLat;
  phase: "finding" | "list" | "routing";
  choices: DockChoice[];
  /** What the card says under the heading: finding, none found, the way being found, or why it failed. */
  note: string;
  /** The dock the plan drew the ride to, offered when no list came back. */
  planned: { name: string; point: LonLat } | null;
}

export function RebalanceDockCard({
  ask,
  onChoose,
  onPlanned,
  onRetry,
}: {
  ask: DockAsk;
  onChoose: (choice: DockChoice) => void;
  onPlanned: () => void;
  onRetry: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  // The focus to the question as it comes up, so a screen reader is there with it.
  useEffect(() => heading.current?.focus(), []);
  const busy = ask.phase !== "list";
  return (
    <section className="ride-dock-choice" aria-labelledby="ride-dock-choice-heading" aria-busy={busy}>
      <h3 id="ride-dock-choice-heading" ref={heading} tabIndex={-1}>
        {DOCK_CHOOSE_HEADING}
      </h3>
      {ask.choices.length > 0 && <p className="ride-dock-lede">{DOCK_CHOOSE_LEDE}</p>}
      {ask.note && (
        // Said through the ride's own outputs as it changes (RideMode notify), so not a live region too.
        <p className="ride-dock-note">{ask.note}</p>
      )}
      {ask.choices.length > 0 && (
        <ul className="ride-dock-list">
          {ask.choices.map((choice, i) => (
            <li key={choice.id}>
              <button type="button" className={i === 0 ? "primary" : "secondary"} onClick={() => onChoose(choice)} aria-disabled={busy}>
                <span className="ride-dock-name">{choice.name}</span>
                <span className="ride-dock-line">{dockChoiceLine(choice)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {ask.phase === "list" && ask.choices.length === 0 && (
        <div className="ride-dock-none">
          <button type="button" className="secondary" onClick={onRetry}>
            {DOCK_RETRY}
          </button>
          {ask.planned && (
            <button type="button" className="secondary" onClick={onPlanned}>
              {dockAsPlanned(ask.planned.name)}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
