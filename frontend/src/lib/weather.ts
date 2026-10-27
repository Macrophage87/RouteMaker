/**
 * Weather along the route (Stephen 2026-10-24: "Add a check for severe weather and send an alert if there's any
 * relevant NWS alert both before starting a ride and during it. Link to the notice. If there's any API that could say
 * rain possible in the next x min or something that could be helpful too").
 *
 * The page sends a few points along the line still to ride, one about every 5 mi (8 km), each with the seconds until
 * the rider gets there at the route's pace (POST /api/weather/check, core.weather). The server answers with the
 * National Weather Service alerts in force there during the ride (only those that matter on a bike) and the first
 * point where rain is forecast as the rider gets there (Open-Meteo's 15-minute forecast, NOAA's HRRR model).
 *
 * Shown with the route's warnings before Start (Go and Plan), each alert linked to the NWS's page for the place;
 * in a ride, checked every 5 minutes, a new alert or rain coming said through the rider's outputs and shown in the
 * bottom panel until dismissed. Never a step before Start: nothing asks, nothing waits.
 *
 * Privacy: the points go in a POST body; the server rounds them to 0.01 degree before asking either service, keeps
 * the answers 2 minutes and writes nothing (core.weather).
 */
import { haversineM, type LonLat } from "./geo.ts";
import { formatDuration, formatMilePost } from "./format.ts";
import { lightClock } from "./lightTimes.ts";
import { t } from "./i18n.ts";

/** One NWS alert, as core.weather.parse_alerts answers it. */
export interface WeatherAlert {
  id: string;
  /** "Severe Thunderstorm Warning". */
  event: string;
  severity: "Extreme" | "Severe" | "Moderate" | "Minor" | "Unknown";
  /** ISO times, or null. */
  onset: string | null;
  ends: string | null;
  area: string | null;
  instruction: string | null;
  /** The NWS's page for the place (forecast.weather.gov), its hazards at the top. */
  url: string;
}

/** The first point where rain is forecast as the rider gets there (core.weather.first_rain). */
export interface WeatherRain {
  /** Which point sent. */
  index: number;
  offset_s: number;
  /** Seconds from now until the 15-minute step with the rain begins. */
  starts_in_s: number;
  inches: number;
  heavy: boolean;
}

export interface WeatherReport {
  alerts: WeatherAlert[];
  rain: WeatherRain | null;
  /** What could not be checked: "alerts", "rain". */
  unchecked: string[];
  /** Metres along the route to each point sent, to say where the rain is. */
  alongM: number[];
}

/** Metres between points sent, and the most sent (the server takes 12). */
export const WEATHER_STEP_M = 8_000;
export const WEATHER_MAX_POINTS = 10;
/** How often a ride checks again; and how often a route on screen before Start does. */
export const RIDE_WEATHER_MS = 5 * 60_000;
export const ROUTE_WEATHER_MS = 10 * 60_000;
/** How long a check waits for the answer. */
export const WEATHER_TIMEOUT_MS = 15_000;

export type WeatherPoint = [number, number, number];

/**
 * The points to send: from `fromM` along the line to its end, one every WEATHER_STEP_M (spread further where the
 * rest is long), each [lon, lat, seconds until there at `paceMs`] (metres a second).
 */
export function weatherPoints(line: readonly (readonly number[])[], fromM: number, paceMs: number, max = WEATHER_MAX_POINTS): { points: WeatherPoint[]; alongM: number[] } {
  const points: WeatherPoint[] = [];
  const alongM: number[] = [];
  if (line.length === 0 || !(paceMs > 0)) return { points, alongM };
  const cum = [0];
  for (let i = 1; i < line.length; i++) cum.push(cum[i - 1] + haversineM(line[i - 1] as unknown as LonLat, line[i] as unknown as LonLat));
  const total = cum[cum.length - 1];
  const start = Math.min(Math.max(0, fromM), total);
  const rest = total - start;
  const step = Math.max(WEATHER_STEP_M, rest / Math.max(1, max - 1));
  const wanted: number[] = [];
  for (let m = start; m < total && wanted.length < max - 1; m += step) wanted.push(m);
  if (wanted.length === 0 || total - wanted[wanted.length - 1] > 1) wanted.push(total);
  let i = 0;
  for (const m of wanted) {
    while (i < cum.length - 2 && cum[i + 1] < m) i++;
    const span = cum[i + 1] - cum[i];
    const t = span > 0 ? Math.min(1, Math.max(0, (m - cum[i]) / span)) : 0;
    const a = line[i];
    const b = line[Math.min(i + 1, line.length - 1)];
    const lon = a[0] + (b[0] - a[0]) * t;
    const lat = a[1] + (b[1] - a[1]) * t;
    points.push([Math.round(lon * 1e5) / 1e5, Math.round(lat * 1e5) / 1e5, Math.round((m - start) / paceMs)]);
    alongM.push(m);
  }
  return { points, alongM };
}

type Fetch = typeof fetch;

/** The check; null where it could not be asked or answered (nothing is shown then). */
export async function checkWeather(origin: string, sent: { points: WeatherPoint[]; alongM: number[] }, post: Fetch = fetch, timeoutMs = WEATHER_TIMEOUT_MS): Promise<WeatherReport | null> {
  if (sent.points.length === 0) return null;
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), timeoutMs);
  try {
    const response = await post(`${origin}/api/weather/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      signal: stop.signal,
      body: JSON.stringify({ points: sent.points }),
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<WeatherReport>;
    return {
      alerts: Array.isArray(body.alerts) ? body.alerts.filter((a) => a && typeof a.event === "string" && typeof a.url === "string") : [],
      rain: body.rain && typeof body.rain.index === "number" ? body.rain : null,
      unchecked: Array.isArray(body.unchecked) ? body.unchecked : [],
      alongM: sent.alongM,
    };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

const ms = (iso: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? t : null;
};

/** An alert in one line: "Severe Thunderstorm Warning until 6:45 PM"; "Heat Advisory from 11:00 AM to 8:00 PM". */
export function alertLine(alert: WeatherAlert, now: number): string {
  const onset = ms(alert.onset);
  const ends = ms(alert.ends);
  if (onset !== null && onset > now + 60_000) return `${alert.event} from ${lightClock(onset)}${ends !== null ? ` to ${lightClock(ends)}` : ""}`;
  return ends !== null ? `${alert.event} until ${lightClock(ends)}` : alert.event;
}

/** The link's words beside each alert. */
export const NWS_LINK = t("NWS notice");
/** Its accessible name: "Severe Thunderstorm Warning: National Weather Service notice (opens in a new tab)". */
export const nwsLinkName = (alert: WeatherAlert) => `${alert.event}: National Weather Service notice (opens in a new tab)`;

/** Said: "Weather alert: Severe Thunderstorm Warning until 6:45 PM." */
export function alertSaid(alert: WeatherAlert, now: number): string {
  return `Weather alert: ${alertLine(alert, now)}.`;
}

/** Whether an alert is said urgently (assertive, interrupting): Extreme, or a warning rated Severe. */
export function alertUrgent(alert: WeatherAlert): boolean {
  return alert.severity === "Extreme" || (alert.severity === "Severe" && /Warning$/.test(alert.event));
}

/**
 * Rain in one line: "Rain expected in about 45 min, near mile 9.0 (14.5 km)."; "Heavy rain expected within 15 min, where
 * you are."; before Start the first point is "at the start".
 */
export function rainLine(rain: WeatherRain, alongM: readonly number[], riding: boolean): string {
  const what = rain.heavy ? "Heavy rain" : "Rain";
  const minutes = Math.round(rain.starts_in_s / 300) * 5;
  const when = rain.starts_in_s < 15 * 60 ? "within 15 min" : `in about ${formatDuration(minutes * 60)}`;
  // Within a tenth of a mile of the first point (Roam sends one place at several times): where the rider is.
  const here = (alongM[rain.index] ?? 0) - (alongM[0] ?? 0) < 160;
  const where = here ? (riding ? "where you are" : "at the start") : `near ${formatMilePost(alongM[rain.index] ?? 0)}`;
  return `${what} expected ${when}, ${where}.`;
}

/** The forecast's credit, beside the rain line (CC BY 4.0), and its accessible name. */
export const RAIN_CREDIT = t("Forecast: Open-Meteo");
export const RAIN_CREDIT_NAME = t("Forecast: Open-Meteo (opens in a new tab)");
export const WEATHER_DISMISS_NAME = t("Dismiss weather");
export const RAIN_CREDIT_URL = "https://open-meteo.com/";

/**
 * An alert's identity for saying and dismissing: its event, end and severity. Every NWS update of a warning has a new
 * id, so by id a warning updated every 20 minutes would be said again each time; by this, only when it is extended,
 * cut short or changes severity.
 */
export const alertKey = (alert: WeatherAlert) => `${alert.event}|${alert.ends ?? ""}|${alert.severity}`;

/** The alerts not said yet (by alertKey). */
export function newAlerts(report: WeatherReport | null, said: ReadonlySet<string>): WeatherAlert[] {
  return (report?.alerts ?? []).filter((a) => !said.has(alertKey(a)));
}

/** What a Dismiss hides: the alerts then shown and the rain's stage. */
export interface WeatherDismissed {
  alerts: ReadonlySet<string>;
  rain: string;
}
export const NOTHING_DISMISSED: WeatherDismissed = { alerts: new Set(), rain: "" };
export function dismissWeather(report: WeatherReport | null, before: WeatherDismissed): WeatherDismissed {
  if (!report) return before;
  return { alerts: new Set([...before.alerts, ...report.alerts.map(alertKey)]), rain: rainStage(report.rain) || before.rain };
}
/** The report to show after a Dismiss: shown again only for an alert not dismissed, or rain at a new stage; else null. */
export function weatherToShow(report: WeatherReport | null, dismissed: WeatherDismissed): WeatherReport | null {
  if (!report) return null;
  const stage = rainStage(report.rain);
  const fresh = report.alerts.some((a) => !dismissed.alerts.has(alertKey(a))) || (stage !== "" && stage !== dismissed.rain);
  return fresh ? report : null;
}

/** Everything in words, for a screen reader's status region before Start ("" with nothing to say). */
export function weatherSaid(report: WeatherReport | null, now: number): string {
  if (!report) return "";
  const lines = report.alerts.map((a) => alertSaid(a, now));
  if (report.rain) lines.push(rainLine(report.rain, report.alongM, false));
  return lines.join(" ");
}

/** Roam's points: the rider's place now and in 15, 30, 45 and 60 minutes, so rain coming there is found too. */
export function roamPoints(at: readonly number[]): { points: WeatherPoint[]; alongM: number[] } {
  const offsets = [0, 900, 1800, 2700, 3600];
  return { points: offsets.map((s) => [at[0], at[1], s] as WeatherPoint), alongM: offsets.map(() => 0) };
}

/**
 * Whether a ride says the rain: when it first appears, when it comes within 15 minutes after being further off, and
 * when it turns heavy. `before` is what was last said ("" for nothing).
 */
export function rainStage(rain: WeatherRain | null): string {
  if (!rain) return "";
  return `${rain.heavy ? "heavy" : "rain"}-${rain.starts_in_s < 15 * 60 ? "soon" : "later"}`;
}
export function rainSays(before: string, rain: WeatherRain | null): boolean {
  const now = rainStage(rain);
  if (!now || now === before) return false;
  if (!before) return true;
  const [beforeKind, beforeWhen] = before.split("-");
  const [kind, when] = now.split("-");
  return (kind === "heavy" && beforeKind !== "heavy") || (when === "soon" && beforeWhen === "later");
}
