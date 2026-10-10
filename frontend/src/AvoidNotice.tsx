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
import type { RouteResponse } from "./lib/api.ts";
import { AVOID_BACK, AVOID_SHOWING_AROUND, AVOID_SYMBOL, avoidNoticeFor } from "./lib/avoidJunctions.ts";

interface Props {
  /** The planner's answer, with its routes to choose from and its way round. */
  answer: RouteResponse;
  /** Which of its routes is chosen: 0 for the answer. */
  choice: number;
  /** Whether the way round is shown in place of the planned route. */
  around: boolean;
  onAround: (around: boolean) => void;
}

export function AvoidNotice({ answer, choice, around, onAround }: Props) {
  const said = avoidNoticeFor(answer, choice);
  if (!said) return null;
  const { notice, offer, none } = said;
  return (
    <div className="avoid-notice" role="alert">
      <p>
        <span className="avoid-symbol" aria-hidden="true">
          {AVOID_SYMBOL}
        </span>
        <strong>{around && offer ? AVOID_SHOWING_AROUND : notice}</strong>
      </p>
      {offer ? (
        <button type="button" className="secondary" onClick={() => onAround(!around)}>
          {around ? AVOID_BACK : offer}
        </button>
      ) : (
        none && <p className="hint">{none}</p>
      )}
    </div>
  );
}
