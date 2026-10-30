/**
 * The 311 log (Stephen, 2026-10-20: "texting for 311 doesn't work. Perhaps instead we enable it everywhere
 * as a log with what website to go to and the description of where. Such as marking potholes along a
 * route." and "put a checklist of what needs to be logged to 311 and which website, by location. Checking
 * archives it.").
 *
 * DC's Text to 32311 answers every message, even a plain NEW, with only "Welcome to DC311" (Stephen's
 * screenshot, 2026-10-20), so the report no longer goes by text. A problem is logged instead, everywhere
 * the map covers: from a ride's 311 button (lib/ride311.ts), or from the road panel's Log for 311 (a
 * right-click, or a long press on a phone). Each entry keeps what it is, where (the road's name and the
 * GPS position), the day, an optional note, the 311 website that takes it, and the day it was reported.
 *
 * The day, never the time of day (Stephen, 2026-10-29: the log keeps the date, not the time of day; the exact
 * spot stays, because crews need it to find the pothole): `at`, `changed` and `reported` are days in Washington's
 * time ("2026-10-20", dayOf), and an id is random, with no time in it. A copy kept before (full times, and ids that
 * began with the time they were made) is cut to that as it is read (parseEntry), here and on the server
 * (core/report_log.py dated, migration 0052). Two changes to one entry on the same day are told apart by `rev`,
 * a count of its changes.
 *
 * The log's list (Report311Log.tsx, in Reports) is a checklist by website: each site's open entries
 * under its name, with "Copy and open" for each; checking an entry archives it (Archived, folded).
 *
 * Signed out, kept on this device (localStorage). Signed in, the account's log (GET and POST
 * /api/me/report311-log, core.models.Report311Log), so it follows the rider; this device keeps a copy of it
 * apart from its own, tagged with the account (the server's owner tag), so one account's copy is never shown
 * signed out or merged into another account's. At sign-in, entries logged signed out on this device join the
 * account's. Saves wait for typing to settle (SAVE_WAIT_MS), go one at a time, and the server merges each into
 * what it has by entry: an entry in both keeps whichever changed last. Nothing is deleted, only archived, so a merge never brings back
 * something removed; past MAX_ENTRIES the oldest archived entries go first.
 *
 * Which website: inside DC from DC's boundary, here on the phone (lib/dcBoundary.ts); elsewhere the server
 * names the county or city (POST /api/report311/where; core.report_log). An entry logged with no signal
 * waits with no website and is looked up when the log is next opened online.
 */
import { useSyncExternalStore } from "react";
import { inDc } from "./dcBoundary.ts";
import type { LonLat } from "./geo.ts";
import { REPORT_KINDS, gpsWords, isUnnamed, type ReportKind, type ReportPlace } from "./report311.ts";
import { csrfFromCookie } from "./stressEditor.ts";
import { t } from "./i18n.ts";

/** This device's log, signed out. */
export const LOG_KEY = "routemaker.report311-log";
/** The account's log as last read, with its owner tag, signed in. */
export const ACCOUNT_LOG_KEY = "routemaker.report311-log.account";
/** Set while the account's copy here has changes the account has not taken yet (a save failed, or no signal). */
export const LOG_DIRTY_KEY = "routemaker.report311-log-dirty";
export const MAX_ENTRIES = 300;
export const NOTE_MAX = 500;
/** The most the account keeps, as UTF-8 JSON (core/report_log.py LOG_MAX_BYTES). */
export const LOG_MAX_BYTES = 160 * 1024;
/** How long a change waits before it is saved, so a note is saved once typing stops, not at each key. */
export const SAVE_WAIT_MS = 2_000;

/** A jurisdiction's id (core/report_log.py JURISDICTION_IDS); "none": looked up, and none the log names. */
export type WhereId =
  | "dc"
  | "moco"
  | "pg"
  | "baltimore-city"
  | "baltimore-county"
  | "howard"
  | "anne-arundel"
  | "frederick"
  | "carroll"
  | "harford"
  | "charles"
  | "arlington"
  | "alexandria"
  | "fairfax-city"
  | "falls-church"
  | "manassas"
  | "manassas-park"
  | "md"
  | "va"
  | "none";

export interface Jurisdiction {
  /** Where it is, as the checklist's heading says it. */
  name: string;
  /** The site's own name, for the button ("Open MC311"). */
  site: string;
  url: string;
  /** One short line under the heading, where the site needs saying (whose roads), else null. */
  note: string | null;
}

/**
 * The websites, each read 2026-10-20 (the county's or city's own page linking it: DC ouc.dc.gov/page/311-about;
 * Montgomery's road repair page; PG princegeorgescountymd.gov PGC311; Baltimore City baltimorecity.gov/311services;
 * Baltimore County baltimorecountymd.gov/report-problem; Howard's pothole repair page; Anne Arundel's potholes
 * page; Frederick's FCG FixIt; Carroll's See Click Report; Harford's Report a Concern; Charles's See Click
 * Report; Arlington's Online Service Request Tool page; Alexandria alexandriava.gov/Potholes (Alex311 replaced
 * Call.Click.Connect in 2020); City of Fairfax's Report Road Problems; Falls Church's Public Works; Manassas's
 * Public Works; MDOT SHA roads.maryland.gov "Contact Us"; My VDOT). Maryland's counties and Baltimore City
 * take reports for their own roads; Virginia's counties other than Arlington have their roads kept by VDOT
 * (fairfaxcounty.gov/transportation/roads-conditions-maintenance, loudoun.gov/3919), so a spot there is
 * VDOT's ("va"), and Virginia's cities keep their own. Calvert County has no online form (phone only), so a
 * spot there is the state's.
 */
export const JURISDICTIONS: Record<Exclude<WhereId, "none">, Jurisdiction> = {
  dc: { name: "Washington, DC", site: "DC 311", url: "https://311.dc.gov/citizen/s/", note: null },
  moco: { name: "Montgomery County", site: "MC311", url: "https://www.montgomerycountymd.gov/department-transportation/request-road-repairs", note: null },
  pg: { name: "Prince George's County", site: "PGC311", url: "https://www.pgc311.com/customer/s/", note: null },
  "baltimore-city": { name: "Baltimore City", site: "Baltimore 311", url: "https://balt311.baltimorecity.gov/citizen/s/", note: null },
  "baltimore-county": { name: "Baltimore County", site: "BaltCo 311", url: "https://www.baltimorecountymd.gov/report-problem", note: "Streetlights go to BGE." },
  howard: { name: "Howard County", site: "Tell HoCo", url: "https://www.howardcountymd.gov/tell-hoco", note: null },
  "anne-arundel": { name: "Anne Arundel County", site: "AA County 311", url: "https://www.aacounty.org/public-works/highways/road-maintenance-services/potholes", note: null },
  frederick: { name: "Frederick County", site: "FCG FixIt", url: "https://www.frederickcountymd.gov/8235/FCG-FixIT", note: null },
  carroll: { name: "Carroll County", site: "See Click Report", url: "https://www.carrollcountymd.gov/scr", note: "Its app takes the report." },
  harford: { name: "Harford County", site: "You Click We Fix", url: "https://harfordcountymd.gov/139/Report-a-Concern", note: null },
  charles: { name: "Charles County", site: "SeeClickReport", url: "https://www.charlescountymd.gov/services/e-services/see-click-report", note: null },
  arlington: { name: "Arlington County", site: "Arlington's Report a Problem", url: "https://arlingtonva.qscend.com/311/request/add", note: null },
  alexandria: { name: "Alexandria", site: "Alex311", url: "https://alex311.alexandriava.gov/", note: null },
  "fairfax-city": { name: "City of Fairfax", site: "City of Fairfax", url: "https://fairfaxva.gov/government/public-works/streets-division/report-road-problems", note: "By phone: the page has the number." },
  "falls-church": { name: "Falls Church", site: "RequestTracker", url: "https://www.fallschurchva.gov/requesttracker.aspx", note: null },
  manassas: { name: "Manassas", site: "Report a Concern", url: "https://user.govoutreach.com/manassascityva/support.php?cmd=shell", note: null },
  "manassas-park": { name: "Manassas Park", site: "Manassas Park", url: "https://www.manassasparkva.gov/how_do_i/report_request/submit_a_public_works_request.php", note: null },
  md: { name: "Maryland state roads", site: "MDOT SHA", url: "https://mdotsha.my.salesforce-sites.com/customercare", note: "Numbered state roads, and counties with no site here." },
  va: { name: "Virginia (VDOT roads)", site: "My VDOT", url: "https://my.vdot.virginia.gov/", note: "VDOT keeps the roads in Fairfax, Loudoun and Prince William counties." },
};

/** The heading for entries with no website yet (logged with no signal) or none the log names. */
export const WHERE_PENDING = t("Website not looked up yet");
export const WHERE_NONE = t("No 311 website known here");

export interface LogEntry {
  /** Made on the device: unique, and the key a merge matches by. */
  id: string;
  kind: ReportKind;
  lat: number;
  lon: number;
  /** The place words ("on R Street Northeast near 4th Street Northeast"), or null with none. */
  place: string | null;
  note: string;
  /** The day it was logged ("2026-10-20", Washington's time). */
  at: string;
  /** The day it last changed: the newer of two copies wins a merge, and on one day the one with the higher `rev`. */
  changed: string;
  /** How many times it has changed (a check-off, a note), so two copies changed on one day are told apart. */
  rev: number;
  /** Its website, or null until looked up. */
  where: WhereId | null;
  /** The day it was checked off, archiving it, or null while it is still to report. */
  reported: string | null;
}

const KINDS = new Set<string>(REPORT_KINDS.map((k) => k.kind));
const WHERE_IDS = new Set<string>([...Object.keys(JURISDICTIONS), "none"]);

export function kindLabel(kind: ReportKind): string {
  return REPORT_KINDS.find((k) => k.kind === kind)?.label ?? "Something else";
}

/** The problem as the rider reads it, in the page's language; kindLabel's English stays the report's own words. */
export function kindShown(kind: ReportKind): string {
  return t(kindLabel(kind));
}

function isTime(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && !Number.isNaN(Date.parse(value));
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const DAY_PARTS = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" });

/** The log's day for a moment: its date in Washington ("2026-10-20"), as the server's core/report_log.py today. */
export function today(now = new Date()): string {
  const part = (type: string) => DAY_PARTS.formatToParts(now).find((p) => p.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

/** A day as the server serves it: noon in Washington, with its offset (core/report_log.py served). */
const SERVED_DAY = /^(\d{4}-\d{2}-\d{2})T12:00:00[+-]\d{2}:\d{2}$/;

/** The day of a kept time ("2026-10-20"); a day stays as it is, and a served one is its day (core/report_log.py day_of). */
export function dayOf(value: string): string {
  if (DAY.test(value)) return value;
  return SERVED_DAY.exec(value)?.[1] ?? today(new Date(value));
}

/** An id as this page made them before 2026-10-29 (the time it was made, base 36, then a random part): its random part. */
const TIMED_ID = /^[0-9a-z]{8}-([0-9a-z]{1,8})$/;

/** One entry as kept, or null when it is not one (an old or damaged copy). */
export function parseEntry(raw: unknown): LogEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const e = raw as Record<string, unknown>;
  if (typeof e.id !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(e.id)) return null;
  if (typeof e.kind !== "string" || !KINDS.has(e.kind)) return null;
  if (typeof e.lat !== "number" || typeof e.lon !== "number" || !Number.isFinite(e.lat) || !Number.isFinite(e.lon)) return null;
  if (!isTime(e.at)) return null;
  return {
    id: TIMED_ID.exec(e.id)?.[1] ?? e.id,
    kind: e.kind as ReportKind,
    lat: e.lat,
    lon: e.lon,
    place: typeof e.place === "string" ? e.place.slice(0, 200) : null,
    note: typeof e.note === "string" ? e.note.slice(0, NOTE_MAX) : "",
    at: dayOf(e.at),
    changed: dayOf(isTime(e.changed) ? e.changed : e.at),
    rev: typeof e.rev === "number" && Number.isInteger(e.rev) && e.rev >= 0 ? e.rev : 0,
    where: typeof e.where === "string" && WHERE_IDS.has(e.where) ? (e.where as WhereId) : null,
    reported: isTime(e.reported) ? dayOf(e.reported) : null,
  };
}

export function parseLog(raw: unknown): LogEntry[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: LogEntry[] = [];
  for (const item of raw) {
    const entry = parseEntry(item);
    if (!entry || seen.has(entry.id)) continue;
    seen.add(entry.id);
    out.push(entry);
  }
  return out;
}

const encoder = new TextEncoder();

/**
 * At most MAX_ENTRIES and LOG_MAX_BYTES: the oldest archived go first, then (only if every one is open) the
 * oldest open. The same rule as the server's (core/report_log.py cap_log).
 */
export function capLog(entries: LogEntry[]): LogEntry[] {
  const size = new Map(entries.map((e) => [e.id, encoder.encode(JSON.stringify(e)).length + 1]));
  let bytes = 1 + [...size.values()].reduce((a, b) => a + b, 0);
  if (entries.length <= MAX_ENTRIES && bytes <= LOG_MAX_BYTES) return entries;
  const byAge = [...entries].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const order = [...byAge.filter((e) => e.reported !== null), ...byAge.filter((e) => e.reported === null)];
  const drop = new Set<string>();
  for (const entry of order) {
    if (entries.length - drop.size <= MAX_ENTRIES && bytes <= LOG_MAX_BYTES) break;
    drop.add(entry.id);
    bytes -= size.get(entry.id) ?? 0;
  }
  return entries.filter((e) => !drop.has(e.id));
}

/** Whether `x` wins over `y`: a later day, or on one day more changes; a tie goes to a reported copy, so a check-off is never lost. */
function newer(x: LogEntry, y: LogEntry): boolean {
  const days = Date.parse(x.changed) - Date.parse(y.changed);
  if (days !== 0) return days > 0;
  if (x.rev !== y.rev) return x.rev > y.rev;
  return x.reported !== null && y.reported === null;
}

/** The account's log and this device's, merged by entry: one in both keeps whichever changed last (a tie the first, unless only the second is reported). Newest first. */
export function mergeLogs(a: LogEntry[], b: LogEntry[]): LogEntry[] {
  const byId = new Map<string, LogEntry>();
  for (const entry of [...a, ...b]) {
    const had = byId.get(entry.id);
    const won = !had || newer(entry, had) ? entry : had;
    // A website looked up on one copy is kept whichever copy wins (a lookup is not a change).
    byId.set(entry.id, won.where === null && had ? { ...won, where: (won === entry ? had : entry).where } : won);
  }
  return capLog([...byId.values()].sort((x, y) => Date.parse(y.at) - Date.parse(x.at)));
}

export function sameLog(a: LogEntry[], b: LogEntry[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** A random id, with no time in it: 16 hex characters. */
function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  return Array.from({ length: 16 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

/** A new entry at `point`, on today's day: inside DC its website is known at once; elsewhere it waits for the lookup. */
export function newEntry(kind: ReportKind, place: ReportPlace, now = new Date()): LogEntry {
  const at = today(now);
  return {
    id: newId(),
    kind,
    lat: Number(place.point[1].toFixed(5)),
    lon: Number(place.point[0].toFixed(5)),
    place: place.words,
    note: "",
    at,
    changed: at,
    rev: 0,
    where: inDc(place.point) ? "dc" : null,
    reported: null,
  };
}

export function entryPoint(entry: LogEntry): LonLat {
  return [entry.lon, entry.lat];
}

/** The site's name for an entry's heading and its "Open" button, or null when none is known yet. */
export function jurisdictionOf(entry: LogEntry): Jurisdiction | null {
  return entry.where && entry.where !== "none" ? JURISDICTIONS[entry.where] : null;
}

/**
 * The report to paste into the site: what, where (the words, the area, the GPS position), the day, and the
 * note. "Pothole. Location: on R Street Northeast, Washington, DC. GPS 38.91260, -77.00709. Seen Oct 20."
 */
export function entryText(entry: LogEntry): string {
  const area = jurisdictionOf(entry);
  const areaName = entry.where === "dc" ? "Washington, DC" : area && entry.where !== "md" && entry.where !== "va" ? area.name : null;
  const where = [entry.place, areaName].filter(Boolean).join(", ");
  const note = entry.note.replace(/\s+/g, " ").trim();
  const seen = `Seen ${whenWords(entry.at)}.`;
  return `${kindLabel(entry.kind)}. Location: ${where ? `${where}. ` : ""}${gpsWords(entryPoint(entry))}. ${seen}${note ? ` ${/[.!?]$/.test(note) ? note : `${note}.`}` : ""}`;
}

// A day is read as midnight UTC (Date.parse of "2026-10-20"), so it is said in UTC, which keeps it the same day.
const WHEN = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" });

/** A kept day as the log says it: "Oct 20" (no time of day). */
export function whenWords(day: string): string {
  const at = new Date(dayOf(day));
  return Number.isNaN(at.getTime()) ? "" : WHEN.format(at);
}

/** The checklist's groups: the open entries by website (in the JURISDICTIONS order, then not looked up, then none), newest first in each. */
export interface LogGroup {
  where: WhereId | null;
  heading: string;
  site: Jurisdiction | null;
  entries: LogEntry[];
}

/**
 * An open entry this old is archived by itself (Stephen, 2026-10-21: "archive stale ones"): kept, under Archived,
 * marked not reported; checking it there records it as reported.
 */
export const STALE_DAYS = 30;
const DAY_MS = 86_400_000;

/**
 * The checklist's how-to in Reports, one short line each (P8): a phone's gesture on a phone (holding a road), a
 * computer's right-click on a computer (`touch`, lib/startOnComputer.ts looksLikePhone).
 */
export function logHint(touch: boolean): string[] {
  return [
    touch ? t("Log from a ride's 311 button or by holding a road.") : t("Log from a ride's 311 button or by right-clicking a road."),
    t("Copy the report into the site, then check it off."),
    t("One left unchecked is archived after {days} days.", { days: STALE_DAYS }),
  ];
}

/** Open more than STALE_DAYS whole days: counted in days, from the day it was logged to today. */
export function isStale(entry: LogEntry, now = new Date()): boolean {
  return entry.reported === null && Date.parse(today(now)) - Date.parse(entry.at) > STALE_DAYS * DAY_MS;
}

/** When an entry went to Archived: when it was reported, or when it went stale. */
export function archivedAt(entry: LogEntry): number {
  return entry.reported !== null ? Date.parse(entry.reported) : Date.parse(entry.at) + STALE_DAYS * DAY_MS;
}

export function openGroups(entries: LogEntry[], now = new Date()): LogGroup[] {
  const order: (WhereId | null)[] = [...(Object.keys(JURISDICTIONS) as WhereId[]), null, "none"];
  const groups: LogGroup[] = [];
  for (const where of order) {
    const these = entries.filter((e) => e.reported === null && !isStale(e, now) && e.where === where).sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
    if (these.length === 0) continue;
    const site = where && where !== "none" ? JURISDICTIONS[where] : null;
    groups.push({ where, heading: site ? site.name : where === null ? WHERE_PENDING : WHERE_NONE, site, entries: these });
  }
  return groups;
}

/** How many problems are still to report: the checklist's open entries (stale ones are archived). */
export function openCount(entries: LogEntry[], now = new Date()): number {
  return entries.filter((e) => e.reported === null && !isStale(e, now)).length;
}

/**
 * The ride summary's line while some are still to report (Stephen, 2026-10-21: "Make a link to find it after the ride
 * end and tell people where to do so, if 311 reports are still outstanding").
 */
export function outstandingSaid(n: number): string {
  return `${n} ${n === 1 ? "problem" : "problems"} still to report to 311.`;
}
/** Where Reports is, said under that line. */
export const REPORTS_WHERE = t("Reports is in Go's Settings and Plan's bottom bar.");
export const OPEN_REPORTS = t("Open Reports");

export function archived(entries: LogEntry[], now = new Date()): LogEntry[] {
  return entries.filter((e) => e.reported !== null || isStale(e, now)).sort((a, b) => archivedAt(b) - archivedAt(a));
}

// ---- The store ---------------------------------------------------------------------------------------

export interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readLog(store: Store | null = local()): LogEntry[] {
  try {
    const raw = store?.getItem(LOG_KEY);
    return raw ? parseLog(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

/** The account's copy on this device, or null: its entries and the owner tag they belong to. */
export interface AccountLog {
  owner: string;
  entries: LogEntry[];
  /** Kept after a sign-out only for changes the account has not taken: never shown, merged at that account's sign-in. */
  waiting?: boolean;
}

export function readAccountLog(store: Store | null = local()): AccountLog | null {
  try {
    const raw = store?.getItem(ACCOUNT_LOG_KEY);
    const body = raw ? (JSON.parse(raw) as { owner?: unknown; entries?: unknown; waiting?: unknown }) : null;
    if (!body || typeof body.owner !== "string" || !body.owner) return null;
    return { owner: body.owner, entries: parseLog(body.entries), ...(body.waiting === true ? { waiting: true } : {}) };
  } catch {
    return null;
  }
}

/**
 * This device's copies written back as they are read (days, no times, ids with no time in them), where a copy kept
 * before still holds a time: so the time goes from the device as the page opens, not at the next change. The
 * signed-out copy only while it is the one shown (`own`): signed in, it waits for the sign-in, which moves it.
 */
function tidyStored(store: Store | null, copy: AccountLog | null, own: boolean): void {
  try {
    const mine = own ? store?.getItem(LOG_KEY) : null;
    if (mine) {
      const read = JSON.stringify(readLog(store));
      if (read !== mine) store?.setItem(LOG_KEY, read);
    }
    const account = store?.getItem(ACCOUNT_LOG_KEY);
    if (account && copy) {
      const read = JSON.stringify({ owner: copy.owner, entries: copy.entries, ...(copy.waiting ? { waiting: true } : {}) });
      if (read !== account) store?.setItem(ACCOUNT_LOG_KEY, read);
    }
  } catch {
    // Refused: the copies are cut as they are read all the same.
  }
}

export function isDirty(store: Store | null = local()): boolean {
  try {
    return store?.getItem(LOG_DIRTY_KEY) === "1";
  } catch {
    return false;
  }
}

function setDirty(on: boolean, store: Store | null): void {
  try {
    if (on) store?.setItem(LOG_DIRTY_KEY, "1");
    else store?.removeItem(LOG_DIRTY_KEY);
  } catch {
    // Storage refused (a private window): the next change tries again.
  }
}

type Fetch = typeof fetch;

function accountAnswer(body: { entries?: unknown; owner?: unknown }): AccountLog | undefined {
  return typeof body.owner === "string" && body.owner ? { owner: body.owner, entries: parseLog(body.entries ?? []) } : undefined;
}

/** GET /api/me/report311-log: the account's log and owner tag; undefined when it could not be read (signed out, offline). */
export async function fetchAccountLog(origin: string, get: Fetch = fetch): Promise<AccountLog | undefined> {
  try {
    const response = await get(`${origin}/api/me/report311-log`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    return accountAnswer((await response.json()) as { entries?: unknown; owner?: unknown });
  } catch {
    return undefined;
  }
}

/** POST /api/me/report311-log: the account's log as the server merged it, or undefined when it did not take it. */
export async function saveAccountLog(origin: string, entries: LogEntry[], post: Fetch = fetch, cookie = typeof document === "undefined" ? "" : document.cookie): Promise<AccountLog | undefined> {
  try {
    const token = csrfFromCookie(cookie);
    const response = await post(`${origin}/api/me/report311-log`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: JSON.stringify({ entries }),
    });
    if (!response.ok) return undefined;
    return accountAnswer((await response.json()) as { entries?: unknown; owner?: unknown });
  } catch {
    return undefined;
  }
}

/**
 * POST /api/report311/where: the website's id ("none" where the log names none), or undefined when it could not be
 * asked. The point goes in the body, never the URL, so no request line in a server log carries it.
 */
export async function lookUpWhere(origin: string, point: LonLat, send: Fetch = fetch): Promise<WhereId | undefined> {
  try {
    const response = await send(`${origin}/api/report311/where`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ lat: Number(point[1].toFixed(5)), lon: Number(point[0].toFixed(5)) }),
    });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { where?: unknown };
    if (body.where === null) return "none";
    return typeof body.where === "string" && WHERE_IDS.has(body.where) ? (body.where as WhereId) : undefined;
  } catch {
    return undefined;
  }
}

/**
 * The log this page shows, with listeners (the ride's 311 button, the road panel and the checklist all see the
 * same entries): this device's own signed out, the account's copy signed in. Signed in, a change is saved
 * once changes settle (SAVE_WAIT_MS), one save at a time; until the account has it the copy is marked dirty,
 * so the next sign-in merges it.
 */
export class Report311LogStore {
  private entries: LogEntry[];
  private listeners = new Set<() => void>();
  /** Whose log is shown: this device's, or the account's with that account's owner tag. */
  private owner: string | null;
  private signedIn = false;
  private looking = new Set<string>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private saving = false;
  private again = false;
  private readonly store: Store | null;
  private readonly origin: string;
  private readonly net: Fetch;
  private readonly wait: number;

  constructor(
    store: Store | null = local(),
    origin = typeof window === "undefined" ? "" : window.location.origin,
    net: Fetch = (...args) => fetch(...args),
    wait = SAVE_WAIT_MS,
  ) {
    this.store = store;
    this.origin = origin;
    this.net = net;
    this.wait = wait;
    // The account's copy until the page knows whether it is signed in (as My Go does); signed out, it goes.
    // One left waiting by a sign-out is never shown.
    const copy = readAccountLog(store);
    const shown = copy && !copy.waiting ? copy : null;
    this.owner = shown?.owner ?? null;
    this.entries = shown ? shown.entries : readLog(store);
    tidyStored(store, copy, this.owner === null);
  }

  list = (): LogEntry[] => this.entries;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private keep(): void {
    try {
      if (this.owner === null) this.store?.setItem(LOG_KEY, JSON.stringify(this.entries));
      else this.store?.setItem(ACCOUNT_LOG_KEY, JSON.stringify({ owner: this.owner, entries: this.entries }));
    } catch {
      // Storage full or refused: the log still holds for this visit.
    }
  }

  private show(next: LogEntry[]): void {
    this.entries = next;
    this.keep();
    for (const listener of this.listeners) listener();
  }

  private write(next: LogEntry[]): void {
    this.show(capLog(next));
    if (this.owner === null) return;
    setDirty(true, this.store);
    if (!this.signedIn) return;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.save();
    }, this.wait);
  }

  /** One save at a time; a change made while one is out is sent after it. The server's merged log is kept. */
  private async save(): Promise<void> {
    if (this.saving) {
      this.again = true;
      return;
    }
    this.saving = true;
    const owner = this.owner;
    const sent = this.entries;
    const answer = await saveAccountLog(this.origin, sent, this.net);
    this.saving = false;
    if (owner === null || this.owner !== owner) return;
    if (answer && answer.owner === owner) {
      const changed = this.entries !== sent;
      const merged = mergeLogs(answer.entries, this.entries);
      if (!sameLog(merged, this.entries)) this.show(merged);
      if (!changed) setDirty(false, this.store);
    }
    if (this.again) {
      this.again = false;
      void this.save();
    }
  }

  /** Log a problem; returns the entry. Its website is looked up at once where it is not DC's. */
  add(kind: ReportKind, place: ReportPlace, now = new Date()): LogEntry {
    const entry = newEntry(kind, place, now);
    this.write([entry, ...this.entries]);
    if (entry.where === null) void this.lookUp();
    return entry;
  }

  private change(id: string, patch: Partial<LogEntry>, now = new Date()): void {
    if (!this.entries.some((e) => e.id === id)) return;
    this.write(this.entries.map((e) => (e.id === id ? { ...e, ...patch, changed: today(now), rev: e.rev + 1 } : e)));
  }

  /** Checked off (archived) on today's day, or back on the checklist. */
  setReported(id: string, reported: boolean, now = new Date()): void {
    this.change(id, { reported: reported ? today(now) : null }, now);
  }

  setNote(id: string, note: string, now = new Date()): void {
    this.change(id, { note: note.slice(0, NOTE_MAX) }, now);
  }

  /** Each entry with no website yet, asked of the server one at a time; one with no answer waits for the next time. */
  async lookUp(): Promise<void> {
    for (const entry of this.entries.filter((e) => e.where === null && !this.looking.has(e.id))) {
      this.looking.add(entry.id);
      const where = inDc(entryPoint(entry)) ? "dc" : await lookUpWhere(this.origin, entryPoint(entry), this.net);
      this.looking.delete(entry.id);
      // Not a change of the rider's (its time is kept), so it cannot outrank a check-off made on another device.
      if (where !== undefined && this.entries.some((e) => e.id === entry.id && e.where === null)) {
        this.write(this.entries.map((e) => (e.id === entry.id ? { ...e, where } : e)));
      }
    }
  }

  /**
   * Signed in (every signed-in load): the account's log, with this device's copy of it where that copy is the
   * same account's (another account's is dropped), and the entries logged signed out on this device, which
   * join the account's and leave the device's own log. The account is written only when that differs.
   */
  async signIn(): Promise<void> {
    const account = await fetchAccountLog(this.origin, this.net);
    if (account === undefined) return;
    const waiting = readAccountLog(this.store);
    const copy = this.owner === account.owner ? this.entries : waiting?.owner === account.owner ? waiting.entries : [];
    const device = readLog(this.store);
    const merged = mergeLogs(mergeLogs(account.entries, copy), device);
    this.signedIn = true;
    this.owner = account.owner;
    this.show(merged);
    try {
      this.store?.removeItem(LOG_KEY);
    } catch {
      // Refused: the device's entries are in the account's copy already.
    }
    if (!sameLog(merged, account.entries)) {
      setDirty(true, this.store);
      await this.save();
    } else setDirty(false, this.store);
    void this.lookUp();
  }

  /**
   * Signed out (the page found no account): this device's own log. The account's copy goes, unless it holds
   * changes the account has not taken, which wait, unshown, for that account's next sign-in.
   */
  signOut(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.signedIn = false;
    if (this.owner !== null) {
      try {
        if (isDirty(this.store)) this.store?.setItem(ACCOUNT_LOG_KEY, JSON.stringify({ owner: this.owner, entries: this.entries, waiting: true }));
        else this.store?.removeItem(ACCOUNT_LOG_KEY);
      } catch {
        // Refused: it is not shown either way.
      }
    }
    this.owner = null;
    this.entries = readLog(this.store);
    for (const listener of this.listeners) listener();
  }
}

let shared: Report311LogStore | null = null;

/** The page's one log. */
export function report311Log(): Report311LogStore {
  shared ??= new Report311LogStore();
  return shared;
}

/** The log's entries, kept current (a React hook over the page's one log). */
export function useReport311Log(log: Report311LogStore = report311Log()): LogEntry[] {
  return useSyncExternalStore(log.subscribe, log.list, log.list);
}

// ---- The road panel's Log for 311 (Stephen, 2026-10-20: "It should be on the right click panel") ------------

export const LOG_311_TEXT = t("Log for 311");

/** The panel's spot as an entry's place: "on <the road's name>" (none for an unnamed way), at the nearest point on it. */
export function panelPlace(title: string | null, point: LonLat): ReportPlace {
  const named = title && !isUnnamed(title) ? title : null;
  return { words: named ? `on ${named}` : null, point };
}

/** What the panel says once a problem is logged: "Logged for 311: Pothole on R Street Northeast." */
export function panelLoggedSaid(entry: LogEntry): string {
  return t("Logged for 311: {kind}{place}. It is in your 311 checklist in Reports.", { kind: kindShown(entry.kind), place: entry.place ? ` ${entry.place}` : "" });
}
