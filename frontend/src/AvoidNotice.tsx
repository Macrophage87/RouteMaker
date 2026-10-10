/**
 * The notice at the top of the route panel when the route goes through an
 * Avoid-rated junction (OWNER-DECISIONS 335): "This route goes through an
 * Avoid-rated junction: <name>, <reason>", announced first, with the best route
 * that avoids it offered beside it, however much longer.
 *
 * role="alert": it is said as soon as it appears, ahead of the route's own sentence,
 * which waits to settle (App.tsx ANNOUNCE_SETTLE_MS). The symbol is seen, not heard
 * (309); the words name the rating.
 */
import type { RouteResponse } from "./lib/api.ts";
import { AVOID_BACK, AVOID_SHOWING_AROUND, AVOID_SYMBOL, avoidNoAlternate, avoidOffer } from "./lib/avoidJunctions.ts";

interface Props {
  /** The planner's answer (not a candidate or the way round): its notice and its way round. */
  answer: RouteResponse;
  /** Whether the way round is shown in place of the planned route. */
  around: boolean;
  onAround: (around: boolean) => void;
}

export function AvoidNotice({ answer, around, onAround }: Props) {
  const notice = answer.avoid_notice;
  if (!notice) return null;
  const offer = avoidOffer(answer);
  const none = avoidNoAlternate(answer);
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
