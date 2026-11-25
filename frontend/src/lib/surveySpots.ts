/**
 * Survey spots (the owner, 2026-11-25): stretches whose rating was a low-confidence call, marked on the map for riders
 * to check on the spot. A tap on one opens its card (SurveyCard.tsx): "When were you last here?" and a few one-tap
 * questions picked for that road. A spot a rider has answered is no longer marked for them. A spot answered "Today"
 * counts toward their total, for a Freezing Saddles side prize (the honor system). The answers are evidence for the
 * next re-rate, never a rating by themselves (server: core/survey_spots.py).
 *
 * One switch in the Layers sheet, off by default, kept on this device. Its words are English and Spanish only, as
 * the Interval stretches layer's are (i18n.ts planStaysEnglish): each English is kept in a constant not exported.
 */
import { t } from "./i18n.ts";
import { csrfFromCookie } from "./stressEditor.ts";

const LABEL = "Survey spots";
const HINT = "Roads we are unsure about. Tap a dot to tell us what it is like there.";
const UNAVAILABLE = "Survey spots are unavailable for now.";
const COUNT = "Spots you have surveyed: {n}. Answered on the day you rode there: {today}.";
const SIGN_IN = "Sign in to answer survey spots.";
const HEADING = "Survey: {road}";
const SEND = "Send";
const CANCEL = "Cancel";
const DONE = "Done";
const SENT = "Thanks. Your answers will help rate this road.";
const NEED_WHEN = "Say when you were last here.";
const FAILED = "That didn't send. Try again shortly.";
const ALREADY = "You've already answered this spot.";
const NEAR = "List spots near the map's centre";
const PASSED = "You passed {n} survey spots. Answer them";
const PASSED_ONE = "You passed 1 survey spot. Answer it";

export const SURVEY_LABEL = t(LABEL);
export const SURVEY_HINT = t(HINT);
export const SURVEY_UNAVAILABLE = t(UNAVAILABLE);
export const SURVEY_SIGN_IN = t(SIGN_IN);
export const SURVEY_SEND = t(SEND);
export const SURVEY_CANCEL = t(CANCEL);
export const SURVEY_DONE = t(DONE);
export const SURVEY_SENT = t(SENT);
export const SURVEY_NEED_WHEN = t(NEED_WHEN);
export const SURVEY_FAILED = t(FAILED);
export const SURVEY_ALREADY = t(ALREADY);
export const SURVEY_NEAR = t(NEAR);
export const surveyHeading = (road: string) => t(HEADING, { road });
export const surveyCountText = (n: number, today: number) => t(COUNT, { n, today });
export const surveyPassedText = (n: number) => (n === 1 ? t(PASSED_ONE) : t(PASSED, { n }));

export const SURVEY_PREF_KEY = "routemaker.surveyLayer";
export const SURVEY_SOURCE = "survey-spots";
export const SURVEY_LAYER = "survey-spots-dots";
/** Amber with a dark rim: not a stress colour, the route's blue, the intervals' pink nor the places' teal. */
export const SURVEY_COLOUR = "#f59e0b";
export const SURVEY_RIM = "#1f2937";
/** The whole map's box: the layer fetches every spot once (about 6,000 points). */
export const SURVEY_BOX = { west: -79.6, south: 37.9, east: -75.0, north: 40.0 } as const;
/** A ride passes a spot when its line comes this close to the spot's point. */
export const PASS_METRES = 40;

export interface SurveySpot {
  id: string;
  road: string;
  lon: number;
  lat: number;
}

export interface SurveyQuestion {
  key: string;
  text: string;
  options: { value: string; label: string }[];
}

export interface SurveyMine {
  done: string[];
  count: number;
}

export type Fetch = (input: string, init?: RequestInit) => Promise<Response>;
const net: Fetch = (...args) => fetch(...args);

export function readSurveyLayer(storage: Pick<Storage, "getItem"> | undefined = globalThis.localStorage): boolean {
  try {
    return storage?.getItem(SURVEY_PREF_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveSurveyLayer(on: boolean, storage: Pick<Storage, "setItem"> | undefined = globalThis.localStorage): void {
  try {
    storage?.setItem(SURVEY_PREF_KEY, on ? "1" : "0");
  } catch {
    // A private window: the switch lasts this page only.
  }
}

/** Every spot not yet answered by the signed-in rider, or null when the server has none. */
export async function loadSurveySpots(origin: string, fetcher: Fetch = net): Promise<SurveySpot[] | null> {
  const q = new URLSearchParams(Object.entries(SURVEY_BOX).map(([k, v]) => [k, String(v)]));
  try {
    const r = await fetcher(`${origin}/api/survey/spots?${q}`, { credentials: "same-origin" });
    if (!r.ok) return null;
    const body = (await r.json()) as { spots?: SurveySpot[] };
    return Array.isArray(body.spots) ? body.spots : null;
  } catch {
    return null;
  }
}

export async function loadSurveyQuestions(origin: string, spot: string, fetcher: Fetch = net): Promise<SurveyQuestion[] | null> {
  try {
    const r = await fetcher(`${origin}/api/survey/spots/${encodeURIComponent(spot)}/questions`, { credentials: "same-origin" });
    if (!r.ok) return null;
    const body = (await r.json()) as { questions?: SurveyQuestion[] };
    return Array.isArray(body.questions) ? body.questions : null;
  } catch {
    return null;
  }
}

export async function loadSurveyMine(origin: string, fetcher: Fetch = net): Promise<SurveyMine | null> {
  try {
    const r = await fetcher(`${origin}/api/me/survey`, { credentials: "same-origin" });
    if (!r.ok) return null;
    return (await r.json()) as SurveyMine;
  } catch {
    return null;
  }
}

export type SendResult = { ok: true; mine: SurveyMine } | { ok: false; said: string };

/** Sends one spot's answers. Only a chosen answer is sent; "when" is required (the card asks it first). */
export async function sendSurveyAnswers(
  origin: string,
  spot: string,
  answers: Record<string, string>,
  fetcher: Fetch = net,
  cookie: string = typeof document !== "undefined" ? document.cookie : "",
): Promise<SendResult> {
  if (!answers.when) return { ok: false, said: SURVEY_NEED_WHEN };
  const csrf = csrfFromCookie(cookie);
  try {
    const r = await fetcher(`${origin}/api/survey/answer`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRFToken": csrf } : {}) },
      body: JSON.stringify({ spot, answers }),
    });
    if (r.status === 409) return { ok: false, said: SURVEY_ALREADY };
    if (r.status === 401 || r.status === 403) return { ok: false, said: SURVEY_SIGN_IN };
    if (!r.ok) return { ok: false, said: SURVEY_FAILED };
    return { ok: true, mine: (await r.json()) as SurveyMine };
  } catch {
    return { ok: false, said: SURVEY_FAILED };
  }
}

export function surveyGeoJson(spots: readonly SurveySpot[]): { type: "FeatureCollection"; features: object[] } {
  return {
    type: "FeatureCollection",
    features: spots.map((s) => ({ type: "Feature", id: s.id, properties: { id: s.id, road: s.road }, geometry: { type: "Point", coordinates: [s.lon, s.lat] } })),
  };
}

/** A circle per spot, bigger as the map zooms in, drawn over the roads. */
export function surveyLayer(): Record<string, unknown> {
  return {
    id: SURVEY_LAYER,
    type: "circle",
    source: SURVEY_SOURCE,
    paint: {
      "circle-color": SURVEY_COLOUR,
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, 3, 13, 6, 16, 9],
      "circle-stroke-color": SURVEY_RIM,
      "circle-stroke-width": 1.5,
    },
  };
}

function metres(a: [number, number], b: [number, number]): number {
  const lat = ((a[1] + b[1]) / 2) * (Math.PI / 180);
  const dx = (a[0] - b[0]) * 111_320 * Math.cos(lat);
  const dy = (a[1] - b[1]) * 110_574;
  return Math.hypot(dx, dy);
}

/** Distance from a point to a segment in metres, and how far along it the nearest point is (0 to 1). Flat earth: fine
 * over a few hundred metres. */
function toSegment(p: [number, number], a: [number, number], b: [number, number]): { d: number; u: number } {
  const k = Math.cos(((a[1] + b[1]) / 2) * (Math.PI / 180));
  const ax = a[0] * k;
  const bx = b[0] * k;
  const px = p[0] * k;
  const dx = bx - ax;
  const dy = b[1] - a[1];
  const len = dx * dx + dy * dy;
  const u = len === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (p[1] - a[1]) * dy) / len));
  return { d: metres(p, [(ax + u * dx) / k, a[1] + u * dy]), u };
}

/** The spots a ride's line passed within `PASS_METRES`, in the order first passed. */
export function spotsPassed(line: readonly [number, number][], spots: readonly SurveySpot[]): SurveySpot[] {
  if (line.length === 0) return [];
  let west = Infinity;
  let east = -Infinity;
  let south = Infinity;
  let north = -Infinity;
  for (const [x, y] of line) {
    west = Math.min(west, x);
    east = Math.max(east, x);
    south = Math.min(south, y);
    north = Math.max(north, y);
  }
  // About 110 m of slack round the line's box, more than PASS_METRES.
  const pad = 0.001;
  const near = spots.filter((s) => s.lon >= west - pad && s.lon <= east + pad && s.lat >= south - pad && s.lat <= north + pad);
  const found: { at: number; spot: SurveySpot }[] = [];
  for (const spot of near) {
    const p: [number, number] = [spot.lon, spot.lat];
    if (line.length === 1) {
      if (metres(p, line[0]) <= PASS_METRES) found.push({ at: 0, spot });
      continue;
    }
    for (let i = 1; i < line.length; i++) {
      const { d, u } = toSegment(p, line[i - 1], line[i]);
      if (d <= PASS_METRES) {
        found.push({ at: i - 1 + u, spot });
        break;
      }
    }
  }
  return found.sort((a, b) => a.at - b.at).map((f) => f.spot);
}

/** The `n` spots nearest a point, nearest first: the keyboard's and screen reader's way to a spot (the dots answer a
 * pointer only). */
export function spotsNear(at: [number, number], spots: readonly SurveySpot[], n = 5): SurveySpot[] {
  return spots
    .map((spot) => ({ d: metres(at, [spot.lon, spot.lat]), spot }))
    .sort((a, b) => a.d - b.d)
    .slice(0, n)
    .map((f) => f.spot);
}
