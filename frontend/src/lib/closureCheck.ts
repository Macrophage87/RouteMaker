/**
 * Closures on a kept line (v0.7.0 plan, "GPX export as close to identical as possible, closure warning first",
 * with Stephen's correction of 2026-10-15 20:19 UTC: "it's about what happens if you have a route planned and
 * suddenly there's construction when you go to ride").
 *
 * A saved route, a shared link, an opened GPX file or a plan left open keeps its line verbatim, so a work zone
 * closed since it was planned is not routed round. When such a route is opened, and again on Start ride, its
 * line is checked against the closures in force now (POST /api/closures/check). If it runs along any, a major
 * dialog names each in one line (street, from and to along the route, until when) and offers "Reroute around
 * them" (the default), "Ride it anyway" and "Cancel". Before a GPX download or a save the same check runs, with
 * "Download anyway" (or "Save anyway") for the middle choice. No closures: nothing is shown.
 *
 * Rerouting a planned route plans it again through the same stops and vias (the planner routes round closures
 * itself). Rerouting an opened GPX file replaces only the closed stretches: from the last point before each
 * closure to the first point after it, the rest of the file's line kept verbatim.
 */
import { haversineM, type LonLat } from "./geo.ts";
import type { ClosureNotice } from "./closureMap.ts";
import type { When } from "./dials.ts";
import { t } from "./i18n.ts";

/** One closure the line runs along, as the API answers it. */
export interface Closure {
  id: string;
  kind: "closed" | "unknown";
  road: string | null;
  /** Metres along the line as sent. */
  from_m: number;
  to_m: number;
  end: string | null;
  source: string;
  /** "Main Street, from 0.4 mi (0.6 km) to 0.6 mi (1.0 km) along the route, until Nov 14, 2026." */
  text: string;
  // Additive (v0.7.0, "DC closures source"): the DC sources' closures come through the same check, with their
  // card's words (lib/closureMap.ts) and whether, on a later ride, one with no end "may still apply".
  may_still_apply?: boolean;
  title?: string;
  source_name?: string;
  url?: string | null;
  when_text?: string;
}

export interface ClosureAnswer {
  closures: Closure[];
  /** "Work zones could not be checked ..." where a feed is not available, else null. */
  unchecked: string | null;
  /** Additive (v0.7.0): "Check before you go": the NPS park alerts and advisories that could not be placed. */
  notices?: ClosureNotice[];
  /** Additive (v0.7.0): the ride's moment the closures were matched at (the plan's When), ISO. */
  ride_at?: string;
}

/** The plan's ride time and the closures it routes through anyway, sent with the line (v0.7.0). */
export interface CheckAt {
  when?: When | null;
  bypass?: readonly string[];
  /** v0.9.1, Go and a ride: only the closures known to be on, not DDOT's permits (lib/dials.ts closuresNow). */
  nowOnly?: boolean;
}

/** Most points the check takes; a longer line is thinned (every k-th point), keeping where each came from. */
export const CHECK_MAX_POINTS = 10_000;

/** Why the check runs: opening a route, starting a ride, downloading, or saving. */
export type CheckFor = "open" | "ride" | "download" | "save";

/** The line to send and, for each of its points, its index in the full line. */
export function thinForCheck(line: readonly (readonly number[])[], max = CHECK_MAX_POINTS): { line: LonLat[]; index: number[] } {
  const stride = Math.max(1, Math.ceil(line.length / max));
  const index: number[] = [];
  for (let i = 0; i < line.length; i += stride) index.push(i);
  if (line.length && index[index.length - 1] !== line.length - 1) {
    if (index.length >= max) index[index.length - 1] = line.length - 1;
    else index.push(line.length - 1);
  }
  return { line: index.map((i) => [line[i][0], line[i][1]] as LonLat), index };
}

type Fetch = typeof fetch;

/** How long Start ride, a download or a save waits on the check: past it, they go ahead unchecked (v0.7.0 end review). */
export const CHECK_TIMEOUT_MS = 3000;

/**
 * POST /api/closures/check, or null when it could not be asked (offline, refused, no answer in
 * `timeoutMs`): the route is then not held up.
 */
export async function checkClosures(
  origin: string,
  line: readonly (readonly number[])[],
  post: Fetch = fetch,
  at: CheckAt = {},
  timeoutMs = CHECK_TIMEOUT_MS,
): Promise<(ClosureAnswer & { index: number[] }) | null> {
  if (line.length < 2) return null;
  const thin = thinForCheck(line);
  // As AbortSignal.timeout, but on a timer cleared once answered.
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), timeoutMs);
  try {
    const response = await post(`${origin}/api/closures/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      signal: stop.signal,
      // The plan's When, so a closure is matched at the ride and not today; and its "Route through anyway" ids.
      body: JSON.stringify({
        line: thin.line,
        ...(at.when ? { when: at.when } : {}),
        ...(at.bypass?.length ? { bypass: at.bypass } : {}),
        ...(at.nowOnly ? { now_only: true } : {}),
      }),
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<ClosureAnswer>;
    return {
      closures: Array.isArray(body.closures) ? body.closures : [],
      unchecked: body.unchecked ?? null,
      notices: Array.isArray(body.notices) ? body.notices : [],
      ride_at: body.ride_at,
      index: thin.index,
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** The dialog's heading: "This route goes through 2 closures". */
export function closureHeading(count: number): string {
  return count === 1 ? t("This route goes through 1 closure") : t("This route goes through {count} closures", { count });
}

export const REROUTE_LABEL = t("Reroute around them");
export const REROUTE_ONE_LABEL = t("Reroute around it");
export const CANCEL_LABEL = t("Cancel");

/** The default choice, for one closure or more (P11). */
export function rerouteLabel(count: number): string {
  return count === 1 ? REROUTE_ONE_LABEL : REROUTE_LABEL;
}

/** The park-wide notices' disclosure under the list (P11): "Park notices (6)", opened only when asked. */
export function parkNoticesSummary(count: number): string {
  return t("Park notices ({count})", { count });
}

/** The middle choice, by what the check was for. */
export function anywayLabel(why: CheckFor): string {
  return why === "download" ? t("Download anyway") : why === "save" ? t("Save anyway") : t("Ride it anyway");
}

/** One sentence under the heading, by what the check was for. */
export function closureLead(why: CheckFor): string {
  if (why === "download") return t("Closures in force now that the file's line runs along. Reroute first, or download it as it is.");
  if (why === "save") return t("Closures in force now that this route runs along. Reroute first, or save it as it is.");
  // At Start ride the route may have been planned a moment ago: it says what is so, not when it was planned (P11).
  return t("Closures on this route now.");
}

/** Metres along each vertex of a line. */
export function along(line: readonly (readonly number[])[]): number[] {
  const out = [0];
  for (let i = 1; i < line.length; i += 1) out.push(out[i - 1] + haversineM([line[i - 1][0], line[i - 1][1]], [line[i][0], line[i][1]]));
  return out;
}

/** How far past each end of a closure the replaced stretch starts and ends, so the detour starts clear of it. */
export const CLEAR_M = 30;

/** One stretch of the full line to replace: from the vertex `before` to the vertex `after`. */
export interface Stretch {
  before: number;
  after: number;
}

/**
 * The stretches to replace in the full line: for each closure, the last vertex before it and the first after it
 * (by its from and to on the line sent, mapped back through `index`), stretches that touch merged. A closure at
 * the very start or end keeps that end of the line's own point, so a ride still starts and ends where it did.
 */
export function closedStretches(full: readonly (readonly number[])[], closures: readonly Pick<Closure, "from_m" | "to_m">[], index: readonly number[]): Stretch[] {
  if (full.length < 2 || !closures.length) return [];
  const sent = index.map((i) => full[i]);
  const sentAlong = along(sent);
  const fullAlong = along(full);
  const toFull = (m: number) => {
    // The sent line's distance, as a distance on the full line (the same vertex's distance, between two).
    let k = 0;
    while (k < sentAlong.length - 1 && sentAlong[k + 1] <= m) k += 1;
    if (k >= sentAlong.length - 1) return fullAlong[fullAlong.length - 1];
    const a = sentAlong[k];
    const b = sentAlong[k + 1];
    const t = b > a ? (m - a) / (b - a) : 0;
    return fullAlong[index[k]] + t * (fullAlong[index[k + 1]] - fullAlong[index[k]]);
  };
  const stretches: Stretch[] = [];
  for (const c of [...closures].sort((x, y) => x.from_m - y.from_m)) {
    const from = toFull(c.from_m) - CLEAR_M;
    const to = toFull(c.to_m) + CLEAR_M;
    let before = 0;
    for (let i = 0; i < fullAlong.length && fullAlong[i] <= from; i += 1) before = i;
    let after = full.length - 1;
    for (let i = full.length - 1; i >= 0 && fullAlong[i] >= to; i -= 1) after = i;
    if (after <= before) after = Math.min(full.length - 1, before + 1);
    const last = stretches[stretches.length - 1];
    if (last && before <= last.after) last.after = Math.max(last.after, after);
    else stretches.push({ before, after });
  }
  return stretches;
}

/**
 * The full line with each stretch replaced by its detour (a routed line from the stretch's `before` vertex to its
 * `after` vertex); every other vertex is kept exactly as it was, elevation and all. A stretch with no detour
 * (null: the router could not find one) is kept as it was.
 */
export function spliceDetours<V extends readonly number[]>(full: readonly V[], stretches: readonly Stretch[], detours: readonly (readonly LonLat[] | null)[]): Array<V | LonLat> {
  const out: Array<V | LonLat> = [];
  let next = 0;
  stretches.forEach((s, k) => {
    for (let i = next; i <= s.before; i += 1) out.push(full[i]);
    const detour = detours[k];
    if (detour && detour.length >= 2) {
      // The detour's own ends are the kept vertices either side; only its inside is new.
      for (const p of detour.slice(1, -1)) out.push([p[0], p[1]]);
    } else {
      for (let i = s.before + 1; i < s.after; i += 1) out.push(full[i]);
    }
    next = s.after;
  });
  for (let i = next; i < full.length; i += 1) out.push(full[i]);
  return out;
}

/** Said once a reroute is done (the line is not drawn anew until then). */
export function reroutedSaid(count: number, failed: number): string {
  if (failed === count) return "No way round the closures was found; the route is as it was.";
  const done = count - failed;
  return failed
    ? `Rerouted around ${done} of ${count} closures; no way round the others was found.`
    : `Rerouted around ${count === 1 ? "the closure" : `the ${count} closures`}; the rest of the route is unchanged.`;
}
