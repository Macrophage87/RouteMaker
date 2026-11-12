/**
 * Learning from each ride (the 2026-11-12 backlog, item 7): two lines on the ride summary (RideSummaryCard.tsx).
 *
 * - "Anything feel different from its rating?": the moment a rider knows a rating is wrong is at the end of the ride,
 *   and finding the road on the map later rarely happens. A tap lists the streets ridden at their levels, longest
 *   first; a tap on one opens the road panel's short suggestion form (SuggestQuick.tsx) on that road.
 * - Road closed presses (lib/roadClosed.ts) were on the phone only ("Nothing is reported anywhere"). Where a ride had
 *   any, the summary offers to send them for review, each time, opt in: each becomes the short form's "Closed" report
 *   on its road, which Review's Confirm closure already takes (ClosureEntry.tsx).
 *
 * What is sent (the privacy rule: nothing identifying stays on the server longer than two minutes): the road piece
 * (its OSM way and the nearest point on it, as the road panel's form sends) and, kept, the day; never the time, the
 * rider's path or fixes, or an account (core/signed_out_suggestions.py, `from_ride`). Looking a road up
 * (GET /api/segment-info) keeps nothing either. Nothing leaves the phone until the rider presses a button.
 *
 * Pure apart from the sends, which take their fetch, so it is tested without a server.
 */
import { formatDistance, METRES_PER_MILE } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import type { RiddenStretch, RideStats } from "./rideStats.ts";
import { segmentInfoUrl, type SegmentInfo } from "./roadInfo.ts";
import { QUICK_CLOSED, fetchQuickTicket, sendQuick } from "./suggestions.ts";

/** The summary's line, and its button. */
export const FELT_DIFFERENT = t("Anything feel different from its rating?");
/** The list's heading, once the line is pressed. */
export const FELT_PICK = t("Which stretch?");
/** The Road closed offer (the ride's Go round button): how many, then the button. */
export const CLOSED_OFFER = (n: number) => (n === 1 ? t("You marked a road closed.") : t("You marked {n} roads closed.", { n }));
export const CLOSED_SEND = t("Send for review");
/** Under the offer: what is sent. */
export const CLOSED_WHAT = t("Only the road and the day are sent.");
export const CLOSED_SENDING = t("Sending…");
export const CLOSED_SENT = (n: number) => (n === 1 ? t("Sent 1 closed road for review. Thank you.") : t("Sent {n} closed roads for review. Thank you.", { n }));
export const CLOSED_NOT_SENT = t("Not sent. Try again shortly.");

/** A street ridden shorter than this is not listed (our default, unmeasured): a few metres where a route meets a road. */
export const FELT_MIN_M = METRES_PER_MILE / 10;
/** At most this many streets are listed, longest first (our default, unmeasured): a short list, not a scroll. */
export const FELT_MOST = 6;
/** Two Road closed presses whose roads are this close are one spot (our default): a press twice at the same closure. */
export const CLOSED_SAME_M = 40;

/** One street to offer: its words for the button, and where to look the road up. */
export interface FeltStretch {
  label: string;
  street: string | null;
  tier: number;
  m: number;
  point: LonLat;
}

/** A level as the summary says it: "LTS 3", "LTS 2.5", "Avoid" (the rating's name, kept in every language). */
export function levelSaid(tier: number): string {
  return tier >= 5 ? "Avoid" : `LTS ${tier}`;
}

/**
 * The streets to offer: each street and level ridden, the same one ridden in several parts added up, at least
 * FELT_MIN_M of it, longest first, at most FELT_MOST.
 */
export function feltStretches(stats: Pick<RideStats, "ridden">): FeltStretch[] {
  const merged = new Map<string, RiddenStretch>();
  for (const r of Array.isArray(stats.ridden) ? stats.ridden : []) {
    // A path or an unnamed road is never added to another one: the same words, but likely another way.
    const key = r.street === null || r.named === false ? `#${merged.size}` : `${r.street}|${r.tier}`;
    const was = merged.get(key);
    merged.set(key, was ? { ...was, m: was.m + r.m } : r);
  }
  return [...merged.values()]
    .filter((r) => r.m >= FELT_MIN_M)
    .sort((a, b) => b.m - a.m)
    .slice(0, FELT_MOST)
    .map((r) => ({
      label: [r.street ?? t("an unnamed road"), levelSaid(r.tier), formatDistance(r.m)].join(" · "),
      street: r.street,
      tier: r.tier,
      m: r.m,
      point: r.point,
    }));
}

const M_PER_DEG_LAT = 111_195;

function apartM(a: LonLat, b: LonLat): number {
  const kx = M_PER_DEG_LAT * Math.cos((a[1] * Math.PI) / 180);
  return Math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * M_PER_DEG_LAT);
}

/**
 * Where each Road closed press's road is looked up: the middle of its stretch's first piece (its start is at a
 * junction as often as not, where the nearest road could be the cross street). Presses at one spot count once.
 */
export function closedSpots(stats: Pick<RideStats, "closed">): LonLat[] {
  const spots: LonLat[] = [];
  for (const line of Array.isArray(stats.closed) ? stats.closed : []) {
    if (!Array.isArray(line) || line.length === 0) continue;
    const [a, b] = [line[0], line[1] ?? line[0]];
    const mid: LonLat = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    if (!spots.some((s) => apartM(s, mid) < CLOSED_SAME_M)) spots.push(mid);
  }
  return spots;
}

type Fetch = typeof fetch;

/** The road at a point, as the road panel finds it, or null where none is found or the look-up fails. */
export async function roadAt(origin: string, point: LonLat, run: Fetch = fetch): Promise<SegmentInfo | null> {
  try {
    const response = await run(segmentInfoUrl(origin, point), { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const info = (await response.json()) as SegmentInfo;
    return info && info.found && typeof info.osm_way_id === "number" ? info : null;
  } catch {
    return null;
  }
}

/** The road's own level as the short form takes it (1 to 5 by halves). */
export function roadStep(info: Pick<SegmentInfo, "step" | "tier">): number {
  const step = info.step ?? info.tier ?? 0;
  return step >= 1 && step <= 5 ? step : 0;
}

/**
 * Send the Road closed presses for review: each spot's road looked up, its ticket asked (as opening the road panel's
 * form does) and the short form's "Closed" sent, at the road's own level. One send per road. How many were sent and
 * how many were not, and the spots not sent, which a retry sends again (never the ones sent).
 */
export async function sendClosedSpots(
  origin: string,
  spots: readonly LonLat[],
  csrf: () => string | null,
  run: Fetch = fetch,
): Promise<{ sent: number; failed: number; left: LonLat[] }> {
  const done = new Set<number>();
  const left: LonLat[] = [];
  let sent = 0;
  let failed = 0;
  for (const spot of spots) {
    const info = await roadAt(origin, spot, run);
    const way = info?.osm_way_id ?? null;
    if (!info || way === null) {
      failed += 1;
      left.push(spot);
      continue;
    }
    if (done.has(way)) continue;
    done.add(way);
    const ticket = await fetchQuickTicket(origin, way, run);
    const step = roadStep(info);
    if (!ticket || !step) {
      failed += 1;
      left.push(spot);
      continue;
    }
    const point = info.on_way ?? spot;
    const outcome = await sendQuick(
      origin,
      { from_ride: true, osm_way_id: way, lat: point[1], lon: point[0], step, reasons: [QUICK_CLOSED], other: "", ticket: ticket.ticket, website: "" },
      csrf(),
      run,
    );
    // Already sent today for this road (a retry, or End ride again after Keep riding) is as good as sent.
    if (outcome.kind === "sent" || outcome.status === 409) sent += 1;
    else {
      failed += 1;
      left.push(spot);
    }
  }
  return { sent, failed, left };
}
