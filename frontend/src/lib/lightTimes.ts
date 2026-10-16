/**
 * Light times on the route (the owner, 2026-10-16: "If we're within about an hour of sunset and civil
 * twilight, put the next event on it ... Before sunset, put Sunset and civil twilight ending.").
 *
 * Civil dawn, sunrise, sunset and civil dusk are worked out here, in the browser, with NOAA's solar
 * position formulas (the NOAA Solar Calculator's, after Meeus); no network. The rider is taken to leave
 * now and to ride at the route's own pace (distance over moving time), so where they are at a moment is
 * that share of the line. Only what is still ahead: the first twilight after setting off (dawn: civil
 * dawn and sunrise; dusk: sunset and the end of civil twilight), its events not yet past, when the next
 * of them comes during the ride or within about an hour of arriving. An event during the ride is marked
 * on the map where the rider will be; one just after it is said in the line only. Past sunrise, before
 * the afternoon, nothing is shown ("Then just leave empty"). Times in the region's time, miles first.
 */
import type { LonLat } from "./geo.ts";
import { haversineM } from "./geo.ts";
import { formatMilePost } from "./format.ts";
import type { When } from "./dials.ts";
import { whenAt } from "./rideTime.ts";

const ZONE = "America/New_York";
const DAY_MS = 86_400_000;
/** "About an hour": a ride this close to an event's twilight gets that twilight's two events. */
export const LIGHT_WINDOW_MS = 60 * 60_000;

/** The sun's centre this far below the horizon: refraction and the disc at rise and set; civil twilight. */
const ZENITH_RISE_SET = 90.833;
const ZENITH_CIVIL = 96;

export type LightKind = "civil_dawn" | "sunrise" | "sunset" | "civil_dusk";

export const LIGHT_NAME: Record<LightKind, string> = {
  civil_dawn: "Civil twilight begins",
  sunrise: "Sunrise",
  sunset: "Sunset",
  civil_dusk: "Civil twilight ends",
};

const rad = (deg: number) => (deg * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/**
 * Minutes after 00:00 UTC of the UTC calendar day `dayMs` (its midnight) at which the sun's centre
 * crosses `zenith`, rising or setting, at `lat`, `lon` (east positive); null where it does not that day.
 * NOAA's formulas, worked out at the event's own moment (two passes).
 */
function crossingMinutes(dayMs: number, lat: number, lon: number, zenith: number, rising: boolean): number | null {
  let minutes = 720 - 4 * lon; // first guess: solar noon, near enough
  for (let pass = 0; pass < 2; pass += 1) {
    const jd = (dayMs + minutes * 60_000) / DAY_MS + 2440587.5;
    const t = (jd - 2451545) / 36525;
    const l0 = (((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360) + 360) % 360;
    const m = 357.52911 + t * (35999.05029 - 0.0001537 * t);
    const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
    const c =
      Math.sin(rad(m)) * (1.914602 - t * (0.004817 + 0.000014 * t)) +
      Math.sin(rad(2 * m)) * (0.019993 - 0.000101 * t) +
      Math.sin(rad(3 * m)) * 0.000289;
    const omega = 125.04 - 1934.136 * t;
    const lambda = l0 + c - 0.00569 - 0.00478 * Math.sin(rad(omega));
    const obliq0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60;
    const obliq = obliq0 + 0.00256 * Math.cos(rad(omega));
    const decl = Math.asin(Math.sin(rad(obliq)) * Math.sin(rad(lambda)));
    const y = Math.tan(rad(obliq / 2)) ** 2;
    const eqTime =
      4 *
      deg(
        y * Math.sin(2 * rad(l0)) -
          2 * e * Math.sin(rad(m)) +
          4 * e * y * Math.sin(rad(m)) * Math.cos(2 * rad(l0)) -
          0.5 * y * y * Math.sin(4 * rad(l0)) -
          1.25 * e * e * Math.sin(2 * rad(m)),
      );
    const cosHa = Math.cos(rad(zenith)) / (Math.cos(rad(lat)) * Math.cos(decl)) - Math.tan(rad(lat)) * Math.tan(decl);
    if (cosHa < -1 || cosHa > 1) return null;
    const ha = deg(Math.acos(cosHa));
    const noon = 720 - 4 * lon - eqTime;
    minutes = rising ? noon - 4 * ha : noon + 4 * ha;
  }
  return minutes;
}

/** The region's calendar day a moment falls on, as the UTC midnight of that date. */
const DATE_FORMAT = new Intl.DateTimeFormat("en-US", { timeZone: ZONE, year: "numeric", month: "numeric", day: "numeric" });
const CLOCK_FORMAT = new Intl.DateTimeFormat("en-US", { timeZone: ZONE, hour: "numeric", minute: "2-digit" });

function localDay(ms: number): number {
  const parts = Object.fromEntries(
    DATE_FORMAT.formatToParts(new Date(ms))
      .map((p) => [p.type, p.value]),
  );
  return Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day));
}

export interface SolarDay {
  civil_dawn: number | null;
  sunrise: number | null;
  sunset: number | null;
  civil_dusk: number | null;
}

/**
 * The four light times (epoch ms) of the region's calendar day `ms` falls on, at `lat`, `lon`. The
 * region is west of Greenwich by less than the day's length, so the local date's solar day is the
 * UTC date's.
 */
export function solarDay(ms: number, lat: number, lon: number): SolarDay {
  const day = localDay(ms);
  const at = (zenith: number, rising: boolean) => {
    const minutes = crossingMinutes(day, lat, lon, zenith, rising);
    return minutes === null ? null : day + Math.round(minutes * 60_000);
  };
  return {
    civil_dawn: at(ZENITH_CIVIL, true),
    sunrise: at(ZENITH_RISE_SET, true),
    sunset: at(ZENITH_RISE_SET, false),
    civil_dusk: at(ZENITH_CIVIL, false),
  };
}

/** The point `metres` along a line, and its cumulative length. */
export function pointAlong(line: readonly LonLat[], metres: number): LonLat | null {
  if (line.length === 0) return null;
  if (metres <= 0 || line.length === 1) return line[0];
  let done = 0;
  for (let i = 1; i < line.length; i += 1) {
    const step = haversineM(line[i - 1], line[i]);
    if (done + step >= metres && step > 0) {
      const f = (metres - done) / step;
      const [a, b] = [line[i - 1], line[i]];
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    }
    done += step;
  }
  return line[line.length - 1];
}

export interface LightMark {
  kind: LightKind;
  /** When it happens, epoch ms. */
  at: number;
  /** "during": on the route at `alongM`; "after": after arriving. */
  where: "during" | "after";
  /** How far along the route the rider is at that moment, metres (during only). */
  alongM: number | null;
  /** Where on the map (during only). */
  point: LonLat | null;
}

export interface LightRide {
  line: readonly LonLat[];
  distanceM: number;
  durationS: number;
  departMs: number;
}

/**
 * The light events to show for a ride, in time order: the first twilight after setting off (dawn: civil
 * dawn and sunrise; dusk: sunset and civil dusk), only its events still ahead, when the next of them
 * comes before arriving or within `windowMs` after. Empty otherwise, or when the route has no line or time.
 */
export function lightMarks(ride: LightRide, windowMs = LIGHT_WINDOW_MS): LightMark[] {
  const { line, distanceM, durationS, departMs } = ride;
  if (line.length < 2 || !(distanceM > 0) || !(durationS > 0)) return [];
  const arriveMs = departMs + durationS * 1000;
  const along = (ms: number) => ((ms - departMs) / (durationS * 1000)) * distanceM;
  const [lon0, lat0] = line[0];
  // The first twilight whose last event is still ahead: today's dawn or dusk, or tomorrow's dawn.
  const pairs = [["civil_dawn", "sunrise"], ["sunset", "civil_dusk"]] as const;
  for (const day of [localDay(departMs), localDay(departMs + DAY_MS)]) {
    // Noon of the region's day: its light times at the start, then each at where the rider is then.
    const noon = day + 17 * 3_600_000;
    const base = solarDay(noon, lat0, lon0);
    for (const pair of pairs) {
      const ahead = pair.filter((kind) => base[kind] !== null && (base[kind] as number) >= departMs);
      if (ahead.length === 0) continue;
      if ((base[ahead[0]] as number) > arriveMs + windowMs) return [];
      return ahead.map((kind) => {
        let at = base[kind] as number;
        if (at <= arriveMs) {
          // Once more where the rider is at that moment: the times move about 4 seconds a kilometre east.
          const there = pointAlong(line, along(at));
          const again = there ? solarDay(noon, there[1], there[0])[kind] : null;
          if (again !== null && again >= departMs) at = again;
        }
        const during = at <= arriveMs;
        const alongM = during ? Math.min(distanceM, Math.max(0, along(at))) : null;
        return { kind, at, where: during ? "during" : "after", alongM, point: alongM === null ? null : pointAlong(line, alongM) };
      });
    }
  }
  return [];
}

/** Whether two lists of marks say and show the same, to the minute and the tenth of a mile. */
export function sameLightMarks(a: readonly LightMark[], b: readonly LightMark[]): boolean {
  const key = (m: LightMark) => `${m.kind}|${m.where}|${CLOCK_FORMAT.format(new Date(m.at))}|${m.alongM === null ? "" : Math.round(m.alongM / 160.9344)}`;
  return a.length === b.length && a.every((m, i) => key(m) === key(b[i]));
}

/** A moment as the region's clock: "6:31 PM". */
export function lightClock(ms: number): string {
  return CLOCK_FORMAT.format(new Date(ms));
}

/** One event in words: "Sunset 6:31 PM near mile 12.4 (20.0 km)", "Sunrise 7:18 AM, after you arrive". */
export function lightMarkSaid(mark: LightMark): string {
  const head = `${LIGHT_NAME[mark.kind]} ${lightClock(mark.at)}`;
  if (mark.where === "after") return `${head}, after you arrive`;
  return `${head} near ${formatMilePost(mark.alongM ?? 0)}`;
}

/** The route summary's one line (the accessible form of the map's marks), or null: "Sunset 6:31 PM near mile 12.4 (20.0 km); civil twilight ends 6:58 PM, after you arrive." */
export function lightLine(marks: readonly LightMark[]): string | null {
  if (marks.length === 0) return null;
  const said = marks.map(lightMarkSaid);
  return `${said.map((text, i) => (i === 0 ? text : text.charAt(0).toLowerCase() + text.slice(1))).join("; ")}.`;
}

/** The map marker's short text: "Sunset 6:31 PM". */
export function lightMarkerText(mark: LightMark): string {
  return `${LIGHT_NAME[mark.kind]} ${lightClock(mark.at)}`;
}

/** The map marker's accessible name: "Sunset 6:31 PM, where you will be near mile 12.4 (20.0 km)". */
export function lightMarkerLabel(mark: LightMark): string {
  return `${lightMarkerText(mark)}, where you will be near ${formatMilePost(mark.alongM ?? 0)}`;
}

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/**
 * Whether a light marker's box lies under one of the map's controls (the scale bar, the credits, the zoom
 * buttons): there it is not drawn, since the route summary's line says the same and a label half under the
 * scale bar reads as neither.
 */
export function underControls(marker: Box, controls: readonly Box[]): boolean {
  return controls.some((c) => marker.left < c.right && marker.right > c.left && marker.top < c.bottom && marker.bottom > c.top);
}

/**
 * The marks for a planned route, leaving at `nowMs`, or none: not for a transit or bikeshare plan (its
 * line is not the whole trip), nor where the ride time chosen is not the time now (the When control is
 * categorical: "weekend" chosen on a Tuesday says nothing about when the rider leaves). "When I'm
 * planning" (null) is leaving now; so is Night, which runs into dawn and from dusk whatever the day.
 */
export function routeLightMarks(
  route: {
    geometry?: { coordinates: LonLat[] } | null;
    distance_m: number;
    duration_s: number;
    transit?: unknown;
    bikeshare?: unknown;
  } | null,
  nowMs: number,
  chosen: When | null,
): LightMark[] {
  if (!route || route.transit || route.bikeshare) return [];
  if (chosen !== null && chosen !== "night" && chosen !== whenAt(new Date(nowMs))) return [];
  return lightMarks({ line: route.geometry?.coordinates ?? [], distanceM: route.distance_m, durationS: route.duration_s, departMs: nowMs });
}
