/**
 * OpenStreetMap's `opening_hours` in a rider's words (place sheets, P7 of the 2026-10-28 audit: "Opening hours show
 * as raw OpenStreetMap ("Mo-Th 07:00-11:00,16:00-22:00"). Show "Open now · closes 10 PM""): open or closed now and
 * when that changes, on the region's own clock (America/New_York, whatever the phone's zone), or where that cannot
 * be read, the hours themselves cleaned up ("Mon–Thu 7–11 AM, 4–10 PM"), never the raw tag.
 *
 * Read (the OSM wiki's Key:opening_hours specification, the common part of it): "24/7"; rules split on ";" (and on
 * "," before a day, the spec's additional rule); each rule's days ("Mo-Fr", "Sa,Su"; none is every day) and times
 * ("10:00-18:00", several with ","), or "off"/"closed". A later rule for a day replaces an earlier one; a day no rule
 * names is closed; a time past midnight ("22:00-02:00") runs into the next day. Holidays ("PH off", "SH ...") are
 * left out, as the app does not know the holidays. Anything else (months, weeks, sunrise, comments) is not read, so
 * nothing is claimed for it. The data files cut each tag at MAX_TEXT characters (scripts/build_water_restrooms.py),
 * so a tag that long has its last rule's days treated as unknown, and "Sa 11." is unknown, not closed.
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { t } from "./i18n.ts";

/** The region's clock: the place's hours are its local time, whatever zone the phone is in. */
export const HOURS_ZONE = "America/New_York";
/** The data files' cut (scripts/build_water_restrooms.py MAX_TEXT): a tag this long may have lost its end. */
export const HOURS_CUT_AT = 80;

const DAY = 24 * 60;
const WEEK = 7 * DAY;
const CODES = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"] as const;
const DAY_CODE = "(?:Mo|Tu|We|Th|Fr|Sa|Su)";
const DAYS_RE = new RegExp(`^(${DAY_CODE}(?:\\s*-\\s*${DAY_CODE})?(?:\\s*,\\s*${DAY_CODE}(?:\\s*-\\s*${DAY_CODE})?)*)(?:\\s+|$)(.*)$`);

/** A span of a day, in minutes from its midnight; `to` at or before `from` runs past midnight. */
type Span = readonly [number, number];
/** Each day's spans (Sunday first), or null where the hours do not say. */
export type Week = ReadonlyArray<readonly Span[] | null>;

function dayList(spec: string): number[] | null {
  const out = new Set<number>();
  for (const part of spec.split(",")) {
    const [a, b] = part.split("-").map((s) => s.trim());
    const from = CODES.indexOf(a as (typeof CODES)[number]);
    const to = CODES.indexOf((b ?? a) as (typeof CODES)[number]);
    if (from < 0 || to < 0) return null;
    for (let d = from; ; d = (d + 1) % 7) {
      out.add(d);
      if (d === to) break;
    }
  }
  return [...out];
}

function minutes(hhmm: string): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm);
  if (!m) return null;
  const v = Number(m[1]) * 60 + Number(m[2]);
  return Number(m[2]) < 60 && v <= 48 * 60 ? v : null;
}

function spans(times: string): Span[] | null {
  if (times === "off" || times === "closed") return [];
  const out: Span[] = [];
  for (const part of times.split(",")) {
    const m = /^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$/.exec(part.trim());
    if (!m) return null;
    const from = minutes(m[1]);
    const to = minutes(m[2]);
    if (from === null || to === null || from >= DAY) return null;
    // "18:00-24:00" ends at midnight; "22:00-26:00" is OSM's way to say 2 AM the next day.
    out.push([from, to > DAY ? to - DAY : to === DAY ? DAY : to]);
  }
  return out;
}

/** A holiday rule ("PH off", "SH 10:00-14:00"), left out; a day list's holiday ("Mo-Fr,PH") is dropped from it. */
const HOLIDAY = /^(?:PH|SH)\b/;
const ADDITIONAL = new RegExp(`(?<=\\d|off|closed)\\s*,\\s*(?=${DAY_CODE}\\b|PH\\b|SH\\b)`);
const HOLIDAY_AFTER = new RegExp(`^((?:${DAY_CODE}[-,\\s]*)+),\\s*(?:PH|SH)\\b`);
const HOLIDAY_BEFORE = new RegExp(`^(?:PH|SH)\\s*,\\s*(?=${DAY_CODE})`);

/** The rules of a tag: split on ";", and on "," where a day follows a time or "off" (an additional rule). */
function rules(spec: string): string[] {
  return spec
    .split(";")
    .flatMap((rule) => rule.split(ADDITIONAL))
    .map((rule) => rule.trim().replace(HOLIDAY_AFTER, "$1").replace(HOLIDAY_BEFORE, ""))
    .filter((rule) => rule && !HOLIDAY.test(rule));
}

// A list or a ride's Detour reads thousands of places' hours at once, most of them alike: each tag is read once.
const PARSED = new Map<string, Week | null>();

/** The tag as a week, or null when it uses more than this reads. */
export function parseHours(hours: string): Week | null {
  if (PARSED.has(hours)) return PARSED.get(hours) ?? null;
  const week = readHours(hours);
  if (PARSED.size > 5000) PARSED.clear();
  PARSED.set(hours, week);
  return week;
}

function readHours(hours: string): Week | null {
  const spec = hours.trim();
  if (!spec) return null;
  if (spec === "24/7") return CODES.map(() => [[0, DAY] as Span]);
  const cut = spec.length >= HOURS_CUT_AT;
  const list = rules(spec);
  if (list.length === 0) return null;
  const week: Array<readonly Span[] | null> = CODES.map(() => []);
  let anyRead = false;
  for (const [i, rule] of list.entries()) {
    const m = DAYS_RE.exec(rule);
    const days = m ? dayList(m[1].replace(/\s+/g, "")) : CODES.map((_, d) => d);
    if (!days) return null;
    const times = (m ? m[2] : rule).trim();
    // The last rule of a tag cut short may have lost its end: its days are not known.
    const read = cut && i === list.length - 1 ? null : spans(times);
    // A rule with no days that cannot be read leaves nothing known; one with its days leaves just them unknown.
    if (read === null && !m) return null;
    if (read !== null) anyRead = true;
    for (const d of days) week[d] = read;
  }
  // Days no rule names are closed only where some rule could be read.
  return anyRead ? week : null;
}

/** The weekday (0 Sunday) and the minute of the day at `at` on the region's clock. */
const CLOCKS = new Map<string, Intl.DateTimeFormat>();
let lastClock: { time: number; zone: string; value: { day: number; minute: number } } | null = null;
export function regionClock(at: Date, zone = HOURS_ZONE): { day: number; minute: number } {
  // A list says every row's hours for the same moment: the clock is read once for it.
  if (lastClock && lastClock.time === at.getTime() && lastClock.zone === zone) return lastClock.value;
  const value = readClock(at, zone);
  lastClock = { time: at.getTime(), zone, value };
  return value;
}

function readClock(at: Date, zone: string): { day: number; minute: number } {
  let clock = CLOCKS.get(zone);
  if (!clock) {
    clock = new Intl.DateTimeFormat("en-US", { timeZone: zone, weekday: "short", hour: "numeric", minute: "numeric", hourCycle: "h23" });
    CLOCKS.set(zone, clock);
  }
  const parts = clock.formatToParts(at);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(get("weekday"));
  return { day, minute: (Number(get("hour")) % 24) * 60 + Number(get("minute")) };
}

type Timeline = { opens: Array<[number, number]>; unknowns: Array<[number, number]> };
const TIMELINES = new WeakMap<Week, Timeline>();

/**
 * The week's open spans as minutes from Sunday's midnight, and the unknown days' spans; each also a week earlier and
 * a week later, so a search runs past Saturday night. Worked out once for each week read.
 */
function timeline(week: Week): Timeline {
  const known = TIMELINES.get(week);
  if (known) return known;
  const open: Array<[number, number]> = [];
  const unknown: Array<[number, number]> = [];
  week.forEach((day, d) => {
    if (day === null) unknown.push([d * DAY, (d + 1) * DAY]);
    else for (const [from, to] of day) open.push([d * DAY + from, d * DAY + (to <= from ? to + DAY : to)]);
  });
  const shift = (list: Array<[number, number]>) => list.flatMap(([a, b]) => [[a - WEEK, b - WEEK], [a, b], [a + WEEK, b + WEEK]] as Array<[number, number]>);
  const out = { opens: shift(open), unknowns: shift(unknown) };
  TIMELINES.set(week, out);
  return out;
}

export interface HoursNow {
  open: boolean;
  /** When it changes (closes when open, opens when closed), minutes from now; null when not known or never. */
  changeIn: number | null;
  /** The change's weekday (0 Sunday) and minute of the day, on the region's clock. */
  changeAt: { day: number; minute: number } | null;
  /** Open all week round. */
  always: boolean;
}

/** Open or closed at `at`, and when that changes; null when the hours do not say. */
export function hoursNow(hours: string, at: Date): HoursNow | null {
  const week = parseHours(hours);
  if (!week) return null;
  const { day, minute } = regionClock(at);
  const now = day * DAY + minute;
  const { opens, unknowns } = timeline(week);
  const inside = (list: Array<[number, number]>, m: number) => list.find(([a, b]) => m >= a && m < b) ?? null;
  const span = inside(opens, now);
  if (!span) {
    if (inside(unknowns, now)) return null;
    // Early in a day after an unknown one, the night before may still be open.
    if (minute < 6 * 60 && week[(day + 6) % 7] === null) return null;
  }
  const at2 = (m: number) => ({ day: (((Math.floor(m / DAY) % 7) + 7) % 7), minute: ((m % DAY) + DAY) % DAY });
  if (span) {
    // Where it closes: the span's end, run on through any span that starts as it ends ("…-24:00; 00:00-…").
    let end = span[1];
    for (let i = 0; i < 16; i++) {
      const next = opens.find(([a, b]) => a <= end && b > end);
      if (!next) break;
      end = next[1];
    }
    if (end - now >= WEEK) return { open: true, changeIn: null, changeAt: null, always: true };
    const unsure = unknowns.some(([a]) => a === end);
    return { open: true, changeIn: unsure ? null : end - now, changeAt: unsure ? null : at2(end), always: false };
  }
  // Where it opens: the first span that starts after now, unless an unknown day comes first.
  const start = opens.filter(([a]) => a > now).reduce((m, [a]) => Math.min(m, a), Infinity);
  const blind = unknowns.filter(([, b]) => b > now).reduce((m, [a]) => Math.min(m, a), Infinity);
  if (start === Infinity || start - now > WEEK || blind < start) return { open: false, changeIn: null, changeAt: null, always: false };
  return { open: false, changeIn: start - now, changeAt: at2(start), always: false };
}

/** "10 PM", "7:30 AM", "noon", "midnight". */
export function clockText(minute: number): string {
  const m = ((minute % DAY) + DAY) % DAY;
  if (m === 0) return t("midnight");
  if (m === 12 * 60) return t("noon");
  const h = Math.floor(m / 60);
  const mm = m % 60;
  const hour12 = h % 12 === 0 ? 12 : h % 12;
  return `${hour12}${mm ? `:${String(mm).padStart(2, "0")}` : ""} ${h < 12 ? "AM" : "PM"}`;
}

const DAY_NAMES = (): string[] => [t("Sun"), t("Mon"), t("Tue"), t("Wed"), t("Thu"), t("Fri"), t("Sat")];

/** A span in words: "7–11 AM", "7 AM–2 PM", "11 AM–1 AM", "noon–3 PM". */
function spanText(from: number, to: number): string {
  const a = clockText(from);
  const b = clockText(to);
  const half = (m: number) => (((m % DAY) + DAY) % DAY < 12 * 60 ? "AM" : "PM");
  // One AM or PM for both where they share it and neither is noon or midnight.
  if (a.endsWith(half(from)) && b.endsWith(half(to)) && half(from) === half(to) && from < to) return `${a.slice(0, -3)}–${b}`;
  return `${a}–${b}`;
}

/**
 * The tag cleaned up, for where open-now cannot be read: "Mon–Thu 7–11 AM, 4–10 PM; Fri 7–11 AM, 4–11 PM". Days and
 * times are put in words; holidays are left out; what is not read (months, sunrise) stays as written; a tag cut
 * short loses its broken end and says so with "…".
 */
export function hoursClean(hours: string): string {
  const spec = hours.trim();
  if (spec === "24/7") return t("Open 24 hours");
  const names = DAY_NAMES();
  const code = (c: string) => names[CODES.indexOf(c as (typeof CODES)[number])] ?? c;
  let list = rules(spec);
  const cut = spec.length >= HOURS_CUT_AT;
  // A cut tag's last rule is shown only up to its last whole time span ("Sa 07:00-14:00,16:00-" is "Sat 7 AM–2 PM…").
  if (cut && list.length > 0) {
    const last = list[list.length - 1];
    const whole = [...last.matchAll(/\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}/g)].pop();
    const kept = whole ? last.slice(0, (whole.index ?? 0) + whole[0].length) : /\b(?:off|closed)$/.test(last) ? last : "";
    list = [...list.slice(0, -1), ...(kept ? [kept] : [])];
  }
  const words = list.map((rule) =>
    rule
      .replace(/(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})/g, (all, a: string, b: string) => {
        const from = minutes(a);
        const to = minutes(b);
        return from === null || to === null ? all : spanText(from, to);
      })
      .replace(new RegExp(`\\b${DAY_CODE}\\b`, "g"), code)
      .replace(/(\p{L})\s*-\s*(\p{L})/gu, "$1–$2")
      .replace(/\s*,\s*/g, ", ")
      .replace(/\b(?:off|closed)\b/g, t("closed")),
  );
  return words.join("; ") + (cut ? "…" : "");
}

/**
 * The hours in a rider's words at `at`: "Open now · closes 10 PM", "Closed now · opens 11 AM", "Open 24 hours";
 * where open-now cannot be read, "Hours: Mon–Fri 9 AM–5 PM". No full stop: the caller ends the sentence.
 */
export function hoursText(hours: string, at: Date): string {
  const now = hoursNow(hours, at);
  if (!now) return t("Hours: {hours}", { hours: hoursClean(hours) });
  if (now.always) return t("Open 24 hours");
  if (now.changeIn === null || now.changeAt === null) return now.open ? t("Open now") : t("Closed now");
  const time = clockText(now.changeAt.minute);
  if (now.open) return t("Open now · closes {time}", { time });
  const today = regionClock(at).day;
  if (now.changeAt.day === today && now.changeIn < DAY) return t("Closed now · opens {time}", { time });
  if (now.changeAt.day === (today + 1) % 7) return t("Closed now · opens {time} tomorrow", { time });
  return t("Closed now · opens {day} {time}", { day: DAY_NAMES()[now.changeAt.day], time });
}

/** Whether the place is open at `at`: true, false, or null when its hours do not say. */
export function openAt(hours: string, at: Date): boolean | null {
  return hoursNow(hours, at)?.open ?? null;
}
