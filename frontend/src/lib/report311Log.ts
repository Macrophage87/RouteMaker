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
 * GPS position), when, an optional note, the 311 website that takes it, and when it was reported.
 *
 * The log's list (Report311Log.tsx, in Suggest) is a checklist by website: each site's open entries
 * under its name, with "Copy and open" for each; checking an entry archives it (Archived, folded).
 *
 * Kept on this device (localStorage) and, signed in, with the account (GET and POST /api/me/report311-log,
 * core.models.Report311Log), so it follows the rider. On sign-in the two are merged by entry: an entry in
 * both keeps whichever changed last. Nothing is deleted, only archived, so a merge never brings back
 * something removed; past MAX_ENTRIES the oldest archived entries go first.
 *
 * Which website: inside DC from DC's boundary, here on the phone (lib/dcBoundary.ts); elsewhere the server
 * names the county or city (GET /api/report311/where; core.report_log). An entry logged with no signal
 * waits with no website and is looked up when the log is next opened online.
 */
import { useSyncExternalStore } from "react";
import { inDc } from "./dcBoundary.ts";
import type { LonLat } from "./geo.ts";
import { REPORT_KINDS, gpsWords, isUnnamed, type ReportKind, type ReportPlace } from "./report311.ts";
import { csrfFromCookie } from "./stressEditor.ts";

export const LOG_KEY = "routemaker.report311-log";
/** Set while this device has changes the account has not taken yet (a save failed, or no signal). */
export const LOG_DIRTY_KEY = "routemaker.report311-log-dirty";
export const MAX_ENTRIES = 300;
export const NOTE_MAX = 500;

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
export const WHERE_PENDING = "Website not looked up yet";
export const WHERE_NONE = "No 311 website known here";

export interface LogEntry {
  /** Made on the device: unique, and the key a merge matches by. */
  id: string;
  kind: ReportKind;
  lat: number;
  lon: number;
  /** The place words ("on R Street Northeast near 4th Street Northeast"), or null with none. */
  place: string | null;
  note: string;
  /** When it was logged (ISO). */
  at: string;
  /** When it last changed (ISO): the newer of two copies wins a merge. */
  changed: string;
  /** Its website, or null until looked up. */
  where: WhereId | null;
  /** When it was checked off, archiving it (ISO), or null while it is still to report. */
  reported: string | null;
}

const KINDS = new Set<string>(REPORT_KINDS.map((k) => k.kind));
const WHERE_IDS = new Set<string>([...Object.keys(JURISDICTIONS), "none"]);

export function kindLabel(kind: ReportKind): string {
  return REPORT_KINDS.find((k) => k.kind === kind)?.label ?? "Something else";
}

function isTime(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 && !Number.isNaN(Date.parse(value));
}

/** One entry as kept, or null when it is not one (an old or damaged copy). */
export function parseEntry(raw: unknown): LogEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const e = raw as Record<string, unknown>;
  if (typeof e.id !== "string" || !/^[A-Za-z0-9_-]{1,40}$/.test(e.id)) return null;
  if (typeof e.kind !== "string" || !KINDS.has(e.kind)) return null;
  if (typeof e.lat !== "number" || typeof e.lon !== "number" || !Number.isFinite(e.lat) || !Number.isFinite(e.lon)) return null;
  if (!isTime(e.at)) return null;
  return {
    id: e.id,
    kind: e.kind as ReportKind,
    lat: e.lat,
    lon: e.lon,
    place: typeof e.place === "string" ? e.place.slice(0, 200) : null,
    note: typeof e.note === "string" ? e.note.slice(0, NOTE_MAX) : "",
    at: e.at,
    changed: isTime(e.changed) ? e.changed : e.at,
    where: typeof e.where === "string" && WHERE_IDS.has(e.where) ? (e.where as WhereId) : null,
    reported: isTime(e.reported) ? e.reported : null,
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

/** At most MAX_ENTRIES: the oldest archived go first, then (only if every one is open) the oldest open. */
export function capLog(entries: LogEntry[]): LogEntry[] {
  if (entries.length <= MAX_ENTRIES) return entries;
  const extra = entries.length - MAX_ENTRIES;
  const byAge = [...entries].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const archived = byAge.filter((e) => e.reported !== null).slice(0, extra);
  const open = byAge.filter((e) => e.reported === null).slice(0, extra - archived.length);
  const drop = new Set([...archived, ...open].map((e) => e.id));
  return entries.filter((e) => !drop.has(e.id));
}

/** The account's log and this device's, merged by entry: one in both keeps whichever changed last. Newest first. */
export function mergeLogs(a: LogEntry[], b: LogEntry[]): LogEntry[] {
  const byId = new Map<string, LogEntry>();
  for (const entry of [...a, ...b]) {
    const had = byId.get(entry.id);
    if (!had || Date.parse(entry.changed) > Date.parse(had.changed)) byId.set(entry.id, entry);
  }
  return capLog([...byId.values()].sort((x, y) => Date.parse(y.at) - Date.parse(x.at)));
}

export function sameLog(a: LogEntry[], b: LogEntry[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function newId(now: Date): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID().slice(0, 8) : Math.random().toString(36).slice(2, 10);
  return `${now.getTime().toString(36)}-${random}`;
}

/** A new entry at `point`: inside DC its website is known at once; elsewhere it waits for the lookup. */
export function newEntry(kind: ReportKind, place: ReportPlace, now = new Date()): LogEntry {
  const at = now.toISOString();
  return {
    id: newId(now),
    kind,
    lat: Number(place.point[1].toFixed(5)),
    lon: Number(place.point[0].toFixed(5)),
    place: place.words,
    note: "",
    at,
    changed: at,
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
 * The report to paste into the site: what, where (the words, the area, the GPS position), when, and the
 * note. "Pothole. Location: on R Street Northeast, Washington, DC. GPS 38.91260, -77.00709. Seen Oct 20,
 * 10:29 AM."
 */
export function entryText(entry: LogEntry): string {
  const area = jurisdictionOf(entry);
  const areaName = entry.where === "dc" ? "Washington, DC" : area && entry.where !== "md" && entry.where !== "va" ? area.name : null;
  const where = [entry.place, areaName].filter(Boolean).join(", ");
  const note = entry.note.replace(/\s+/g, " ").trim();
  const seen = `Seen ${whenWords(entry.at)}.`;
  return `${kindLabel(entry.kind)}. Location: ${where ? `${where}. ` : ""}${gpsWords(entryPoint(entry))}. ${seen}${note ? ` ${/[.!?]$/.test(note) ? note : `${note}.`}` : ""}`;
}

const WHEN = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** "Oct 20, 10:29 AM", in the region's own time. */
export function whenWords(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? "" : WHEN.format(at);
}

/** The checklist's groups: the open entries by website (in the JURISDICTIONS order, then not looked up, then none), newest first in each. */
export interface LogGroup {
  where: WhereId | null;
  heading: string;
  site: Jurisdiction | null;
  entries: LogEntry[];
}

export function openGroups(entries: LogEntry[]): LogGroup[] {
  const order: (WhereId | null)[] = [...(Object.keys(JURISDICTIONS) as WhereId[]), null, "none"];
  const groups: LogGroup[] = [];
  for (const where of order) {
    const these = entries.filter((e) => e.reported === null && e.where === where).sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
    if (these.length === 0) continue;
    const site = where && where !== "none" ? JURISDICTIONS[where] : null;
    groups.push({ where, heading: site ? site.name : where === null ? WHERE_PENDING : WHERE_NONE, site, entries: these });
  }
  return groups;
}

export function archived(entries: LogEntry[]): LogEntry[] {
  return entries.filter((e) => e.reported !== null).sort((a, b) => Date.parse(b.reported ?? b.at) - Date.parse(a.reported ?? a.at));
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

/** GET /api/me/report311-log: undefined when it could not be read (signed out, offline), [] for none yet. */
export async function fetchAccountLog(origin: string, get: Fetch = fetch): Promise<LogEntry[] | undefined> {
  try {
    const response = await get(`${origin}/api/me/report311-log`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { entries?: unknown };
    return parseLog(body.entries ?? []);
  } catch {
    return undefined;
  }
}

/** POST /api/me/report311-log: whether the account took it. */
export async function saveAccountLog(origin: string, entries: LogEntry[], post: Fetch = fetch, cookie = typeof document === "undefined" ? "" : document.cookie): Promise<boolean> {
  try {
    const token = csrfFromCookie(cookie);
    const response = await post(`${origin}/api/me/report311-log`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: JSON.stringify({ entries }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/** GET /api/report311/where: the website's id ("none" where the log names none), or undefined when it could not be asked. */
export async function lookUpWhere(origin: string, point: LonLat, get: Fetch = fetch): Promise<WhereId | undefined> {
  try {
    const query = new URLSearchParams({ lat: point[1].toFixed(5), lon: point[0].toFixed(5) });
    const response = await get(`${origin}/api/report311/where?${query}`, { headers: { Accept: "application/json" } });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { where?: unknown };
    if (body.where === null) return "none";
    return typeof body.where === "string" && WHERE_IDS.has(body.where) ? (body.where as WhereId) : undefined;
  } catch {
    return undefined;
  }
}

/**
 * The one log on this device, with listeners (the ride's 311 button, the road panel and the checklist all
 * see the same entries). Signed in, each change is also saved to the account; a failed save leaves the
 * device dirty, so the next sign-in merge sends it.
 */
export class Report311LogStore {
  private entries: LogEntry[];
  private listeners = new Set<() => void>();
  private signedIn = false;
  private looking = new Set<string>();
  private readonly store: Store | null;
  private readonly origin: string;
  private readonly net: Fetch;

  constructor(store: Store | null = local(), origin = typeof window === "undefined" ? "" : window.location.origin, net: Fetch = (...args) => fetch(...args)) {
    this.store = store;
    this.origin = origin;
    this.net = net;
    this.entries = readLog(store);
  }

  list = (): LogEntry[] => this.entries;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private write(next: LogEntry[], toAccount = true): void {
    this.entries = capLog(next);
    try {
      this.store?.setItem(LOG_KEY, JSON.stringify(this.entries));
    } catch {
      // Storage full or refused: the log still holds for this visit.
    }
    for (const listener of this.listeners) listener();
    if (toAccount && this.signedIn) {
      setDirty(true, this.store);
      const sent = this.entries;
      void saveAccountLog(this.origin, sent, this.net).then((ok) => {
        if (ok && this.entries === sent) setDirty(false, this.store);
      });
    } else if (toAccount) setDirty(true, this.store);
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
    this.write(this.entries.map((e) => (e.id === id ? { ...e, ...patch, changed: now.toISOString() } : e)));
  }

  /** Checked off (archived), or back on the checklist. */
  setReported(id: string, reported: boolean, now = new Date()): void {
    this.change(id, { reported: reported ? now.toISOString() : null }, now);
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
      if (where === undefined) return;
      this.change(entry.id, { where });
    }
  }

  /**
   * Signed in (every signed-in load): the account's log and this device's merged by entry, kept on both.
   * The account is written only when the merge differs from what it has.
   */
  async signIn(): Promise<void> {
    const account = await fetchAccountLog(this.origin, this.net);
    if (account === undefined) return;
    this.signedIn = true;
    const merged = mergeLogs(account, this.entries);
    const accountNeeds = !sameLog(merged, account);
    this.write(merged, false);
    if (accountNeeds) {
      setDirty(true, this.store);
      if (await saveAccountLog(this.origin, merged, this.net)) setDirty(false, this.store);
    } else setDirty(false, this.store);
    void this.lookUp();
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

export const LOG_311_TEXT = "Log for 311";

/** The panel's spot as an entry's place: "on <the road's name>" (none for an unnamed way), at the nearest point on it. */
export function panelPlace(title: string | null, point: LonLat): ReportPlace {
  const named = title && !isUnnamed(title) ? title : null;
  return { words: named ? `on ${named}` : null, point };
}

/** What the panel says once a problem is logged: "Logged for 311: Pothole on R Street Northeast." */
export function panelLoggedSaid(entry: LogEntry): string {
  return `Logged for 311: ${kindLabel(entry.kind)}${entry.place ? ` ${entry.place}` : ""}. It is in your 311 checklist in Suggest.`;
}
