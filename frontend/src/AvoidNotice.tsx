/**
 * The notice at the top of the route panel when the route chosen goes through an
 * Avoid-rated junction (OWNER-DECISIONS 335): "This route goes through an
 * Avoid-rated junction: <name>, <reason>. Riding through it is a really bad idea.
 * Please reconsider your route.", announced first, with the best route that avoids it
 * offered beside it, however much longer, while the planner's own answer is chosen
 * (the way round is the answer's; a route to choose from has its own notice, or none
 * where it avoids the junction: `avoidNoticeFor`).
 *
 * role="alert": it is said as soon as it appears, ahead of the route's own sentence,
 * which waits to settle (App.tsx ANNOUNCE_SETTLE_MS). The symbol is seen, not heard
 * (309); the words name the rating.
 */
import { useId, useState } from "react";
import type { RouteResponse } from "./lib/api.ts";
import { AVOID_BACK, AVOID_SHOWING_AROUND, AVOID_SYMBOL, avoidLine, avoidNoticeFor, avoidOfferShort } from "./lib/avoidJunctions.ts";
import { candidateRoute } from "./lib/candidates.ts";
import { Icon } from "./Icon.tsx";

interface Props {
  /** The planner's answer, with its routes to choose from and its way round. */
  answer: RouteResponse;
  /** Which of its routes is chosen: 0 for the answer. */
  choice: number;
  /** Whether the way round is shown in place of the planned route. */
  around: boolean;
  onAround: (around: boolean) => void;
}

/**
 * UI-CLEANUP (the owner's choice 5 of 2026-10-11, the approved mockup's warning line): one line with the
 * warning icon and the junction's name ("Avoid junction: Main St and 1st Ave"), with "Avoid it" beside it;
 * the notice's whole sentence is behind Details. A screen reader hears the whole sentence at once (it is
 * in the alert, out of sight), so nothing of 335's wording is lost by the shorter line.
 */
export function AvoidNotice({ answer, choice, around, onAround }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const said = avoidNoticeFor(answer, choice);
  if (!said) return null;
  const { notice, offer, none } = said;
  const sentence = around && offer ? AVOID_SHOWING_AROUND : notice;
  const line = around && offer ? "Showing the way round the Avoid junction" : avoidLine(candidateRoute(answer, choice));
  return (
    <div className="avoid-notice alert-line" role="alert">
      <p className="alert-text">
        <Icon name="warn" />
        <span className="avoid-symbol" aria-hidden="true">
          {AVOID_SYMBOL}
        </span>
        <strong aria-hidden="true">{line}</strong>
        <span className="visually-hidden">{sentence}</span>
      </p>
      <div className="alert-actions">
        {offer && (
          <button type="button" className="secondary avoid-it" onClick={() => onAround(!around)} aria-describedby={around ? undefined : `${id}-offer`}>
            {around ? AVOID_BACK : `Avoid it ${avoidOfferShort(answer) ?? ""}`.trim()}
          </button>
        )}
        <button type="button" className="link alert-details-toggle" aria-expanded={open} aria-controls={`${id}-full`} onClick={() => setOpen(!open)}>
          Details
        </button>
      </div>
      {offer && (
        <span id={`${id}-offer`} hidden>
          {offer}
        </span>
      )}
      <div id={`${id}-full`} className="alert-full" hidden={!open}>
        <p>{sentence}</p>
        {offer && !around && <p className="hint">{offer}</p>}
        {!offer && none && <p className="hint">{none}</p>}
      </div>
    </div>
  );
}
