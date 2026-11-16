/**
 * The region packs for riding off grid (Stephen, 2026-11-12: "the one mile would be a default, with a whole region pack
 * an optional download. Potentially split it by subregion"): the whole road network of a riding area, downloaded in
 * Settings' Maps for no signal and kept on this device, so a ride with no signal finds its way back to the route even
 * beyond the mile kept with the route (lib/offlineWayBack.ts).
 *
 * Any number of areas can be kept (Stephen, 2026-11-15: "a popout where you can download one or all, and delete one or
 * all from your phone to save space. It should tell you what's on it"). "All" is the one whole-map pack, not every area
 * (the areas overlap a mile at their borders, so the one file is smaller), and keeping it removes the separate areas.
 * A ride opens only the kept pack that covers the rider (packFor), one at a time, so a phone never holds two in memory.
 *
 * The packs are listed by GET /api/offline/packs and served as gzip JSON (core/offline_packs.py), each with the area it
 * covers. Each is kept compressed in IndexedDB (REGION_PACK_DB) under its id, checked against its checksum, and opened
 * (unzipped and read) only for a ride. Their names, sizes and areas are also kept in localStorage, so Settings and a
 * ride with no signal know them without opening the database. Map data only: nothing about the rider.
 */
import type { LonLat } from "./geo.ts";
import { readableGraph, type CorridorGraph } from "./offlineRouter.ts";
import { t } from "./i18n.ts";

export const REGION_PACK_DB = "routemaker-region-pack";
const STATUS_KEY = "routemaker.regionPacks";
// v0.27.0 kept one pack, under this key and the database's "pack" key: read as kept until it is replaced or deleted.
const LEGACY_STATUS_KEY = "routemaker.regionPack";
const LEGACY_DB_KEY = "pack";
const AREAS_KEY = "routemaker.regionPackAreas";

// ---- Words (Settings > Riding; Go and Ride's 20 languages) ----------------------------------------------------------

export const PACK_LABEL = t("Map for no signal");
export const PACK_HELP = t(
  "With no signal, a ride finds its way back to the route on this phone: near the route always, and anywhere in an area downloaded here. Each updates when the map does.",
);
export const PACK_MANAGE = t("Manage");
export const PACK_NONE_KEPT = t("None on this phone");
export const PACK_ON_PHONE = t("On this phone");
export const PACK_IN_ALL = t("Part of the whole map");
export const PACK_DOWNLOAD = t("Download");
export const PACK_DELETE = t("Delete");
export const downloadName = (name: string) => t("Download {name}", { name });
export const deleteName = (name: string) => t("Delete {name}", { name });
export const PACK_DELETE_ALL = t("Delete all");
export const PACK_CLOSE = t("Close");
export const PACK_WAITING = t("Waiting…");
export const PACK_DOWNLOADING = t("Downloading…");
export const PACK_KEPT = t("Kept on this phone.");
export const PACK_FAILED = t("Could not download it. Try again with a signal.");
export const PACK_NO_ROOM = t("Not enough room on this phone.");
export const PACK_NO_LIST = t("Needs a signal to list the maps.");
export const PACK_MAP_LABEL = t("Map of the areas");

/** "On this phone: 31 MB" */
export const onPhoneText = (size: string) => t("On this phone: {size}", { size });
/** "Download all (69 MB)" */
export const downloadAllText = (size: string) => t("Download all ({size})", { size });
/** "Map of Nov 15, 2026" from a build id such as 20261115T125405Z; "" when it is not one. */
export function mapDateText(buildId: string, locale?: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T/.exec(buildId);
  if (!m) return "";
  const date = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12));
  const day = date.toLocaleDateString(locale, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  return t("Map of {date}", { date: day });
}

/** The areas' names in the page's language, by the server's ids (core/offline_packs.py REGIONS); the server's own name for any other. */
const AREA_NAMES: Readonly<Record<string, string>> = {
  beltway: t("Inside the Beltway"),
  nova: t("Northern Virginia"),
  "nw-exurbs": t("Northwest exurbs"),
  baltimore: t("Baltimore and suburbs"),
  rest: t("Southern Maryland"),
  all: t("Everything"),
};

export function areaName(id: string, serverName: string): string {
  return AREA_NAMES[id] ?? serverName;
}

// ---- The list ------------------------------------------------------------------------------------------------------

/** Where a pack covers: its outline (null: the box less every outlined area, or the whole box), and whether the Beltway is cut out. */
export interface PackArea {
  outline: LonLat[] | null;
  outsideBeltway: boolean;
  whole: boolean;
}

/** One pack as GET /api/offline/packs lists it. */
export interface PackInfo {
  id: string;
  name: string;
  bytes: number;
  sha256: string;
  url: string;
  area: PackArea | null;
}

export interface PackList {
  buildId: string;
  packs: PackInfo[];
  levelFactor: number[];
  /** The map's box, [west, south, east, north]; null from a server before the areas were listed. */
  box: [number, number, number, number] | null;
}

/** What is kept: which pack, from which map, and its size; the bytes are in the database under `key`. */
export interface KeptPack {
  id: string;
  name: string;
  buildId: string;
  bytes: number;
  sha256: string;
  /** The level prices the list gave with it (the Default ride type), for a ride whose own could not be fetched. */
  levelFactor: number[];
  /** The database key: the pack's id (a v0.27.0 pack: "pack"). */
  key: string;
}

function readArea(raw: unknown): PackArea | null {
  if (!raw || typeof raw !== "object") return null;
  const area = raw as { outline?: unknown; outside_beltway?: unknown; whole?: unknown };
  const outline = Array.isArray(area.outline)
    ? (area.outline.filter((p): p is LonLat => Array.isArray(p) && p.length === 2 && p.every((n) => typeof n === "number")) as LonLat[])
    : null;
  return { outline: outline && outline.length >= 4 ? outline : null, outsideBeltway: area.outside_beltway === true, whole: area.whole === true };
}

/** The packs on offer, or null (no signal, not built yet, refused). Never throws. */
export async function fetchPackList(fetcher: typeof fetch = fetch): Promise<PackList | null> {
  try {
    const answer = await fetcher("/api/offline/packs?preset=default");
    if (!answer.ok) return null;
    const body = (await answer.json()) as { build_id?: unknown; packs?: unknown; level_factor?: unknown; box?: unknown };
    if (typeof body.build_id !== "string" || !Array.isArray(body.packs) || !Array.isArray(body.level_factor)) return null;
    const packs: PackInfo[] = [];
    for (const p of body.packs as Record<string, unknown>[]) {
      if (
        !!p &&
        typeof p.id === "string" &&
        typeof p.name === "string" &&
        typeof p.bytes === "number" &&
        typeof p.sha256 === "string" &&
        typeof p.url === "string" &&
        p.url.startsWith("/offline-packs/")
      ) {
        packs.push({ id: p.id, name: p.name, bytes: p.bytes, sha256: p.sha256, url: p.url, area: readArea(p.area) });
      }
    }
    const box = Array.isArray(body.box) && body.box.length === 4 && body.box.every((n) => typeof n === "number") ? (body.box as [number, number, number, number]) : null;
    const list = { buildId: body.build_id, packs, levelFactor: body.level_factor as number[], box };
    rememberAreas(list);
    return list;
  } catch {
    return null;
  }
}

// ---- What is kept (localStorage) -----------------------------------------------------------------------------------

function read<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Private mode: the packs still work this session; Settings just will not remember them.
  }
}

const isKept = (k: unknown): k is KeptPack => !!k && typeof (k as KeptPack).id === "string" && typeof (k as KeptPack).name === "string";

/** Every kept pack, from localStorage (a v0.27.0 pack too); none when storage is not readable. */
export function keptPacks(): KeptPack[] {
  const now = read<unknown[]>(STATUS_KEY);
  if (Array.isArray(now)) return now.filter(isKept).map((k) => ({ ...k, key: typeof k.key === "string" ? k.key : k.id }));
  const legacy = read<unknown>(LEGACY_STATUS_KEY);
  return isKept(legacy) ? [{ ...legacy, key: LEGACY_DB_KEY }] : [];
}

function writeKept(kept: KeptPack[]): void {
  write(STATUS_KEY, kept);
  write(LEGACY_STATUS_KEY, null);
}

/** The areas of the packs last listed, kept so a ride with no signal can tell which pack covers it. */
export interface Areas {
  box: [number, number, number, number] | null;
  areas: Record<string, PackArea>;
}

/** The areas last listed, for the map in Settings with no signal; null before any list. */
export function storedAreas(): Areas | null {
  return read<Areas>(AREAS_KEY);
}

function rememberAreas(list: PackList): void {
  const areas: Record<string, PackArea> = {};
  for (const pack of list.packs) if (pack.area) areas[pack.id] = pack.area;
  if (Object.keys(areas).length) write(AREAS_KEY, { box: list.box, areas } satisfies Areas);
}

// ---- Which pack covers a place ---------------------------------------------------------------------------------------

function inRing([x, y]: LonLat, ring: readonly LonLat[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function inBox([x, y]: LonLat, box: Areas["box"]): boolean {
  return !box || (x >= box[0] && x <= box[2] && y >= box[1] && y <= box[3]);
}

/** Whether `id`'s area holds `here`, by the areas last listed. */
export function covers(id: string, here: LonLat, found: Areas = read<Areas>(AREAS_KEY) ?? { box: null, areas: {} }): boolean {
  const area = found.areas[id];
  if (!area) return false;
  if (area.whole) return inBox(here, found.box);
  const beltway = Object.values(found.areas).find((a) => a.outline && !a.outsideBeltway)?.outline;
  if (area.outline) return inRing(here, area.outline) && !(area.outsideBeltway && beltway && inRing(here, beltway));
  // The map less every outlined area.
  return inBox(here, found.box) && !Object.values(found.areas).some((a) => a.outline && inRing(here, a.outline));
}

/**
 * The kept pack a ride at `here` opens: an area that holds it, else the whole map; else, where the areas are not known
 * (kept before they were listed) or the rider is just outside every kept area, the only one kept. Null: none.
 */
export function packFor(here: LonLat | null | undefined, kept: KeptPack[] = keptPacks()): string | null {
  if (!kept.length) return null;
  if (here) {
    const areas = read<Areas>(AREAS_KEY);
    if (areas) {
      const parts = kept.filter((k) => !areas.areas[k.id]?.whole);
      const holding = parts.find((k) => covers(k.id, here, areas));
      if (holding) return holding.id;
      const whole = kept.find((k) => areas.areas[k.id]?.whole);
      if (whole) return whole.id;
    }
  }
  return kept.length === 1 ? kept[0].id : null;
}

// ---- The bytes, in IndexedDB --------------------------------------------------------------------------------------

/** The storage the packs' bytes go to: IndexedDB in the app, a stand-in in tests. */
export interface PackStore {
  put(key: string, bytes: ArrayBuffer): Promise<void>;
  get(key: string): Promise<ArrayBuffer | null>;
  delete(key: string): Promise<void>;
}

let opened: Promise<IDBDatabase> | null = null;

function db(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") return Promise.reject(new Error("no IndexedDB"));
  return (opened ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(REGION_PACK_DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("pack");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      opened = null;
      reject(request.error);
    };
  }));
}

function run<T>(mode: IDBTransactionMode, act: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return db().then(
    (open) =>
      new Promise<T>((resolve, reject) => {
        const request = act(open.transaction("pack", mode).objectStore("pack"));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
  );
}

export const indexedDbStore: PackStore = {
  put: async (key, bytes) => {
    await run("readwrite", (s) => s.put(bytes, key));
  },
  get: async (key) => ((await run<ArrayBuffer | undefined>("readonly", (s) => s.get(key) as IDBRequest<ArrayBuffer | undefined>)) ?? null),
  delete: async (key) => {
    await run("readwrite", (s) => s.delete(key));
  },
};

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ---- Downloads: one at a time, the rest waiting ------------------------------------------------------------------

export type DownloadOutcome = "kept" | "failed" | "no-room";

interface Job {
  pack: PackInfo;
  list: PackList;
  fetcher: typeof fetch;
  store: PackStore;
  done: Promise<DownloadOutcome>;
  resolve: (outcome: DownloadOutcome) => void;
}

const jobs: Job[] = [];
const listeners = new Set<() => void>();
const tell = () => listeners.forEach((listen) => listen());

/** Called whenever a download starts, ends or is added; the unsubscribe. */
export function onDownloads(listen: () => void): () => void {
  listeners.add(listen);
  return () => void listeners.delete(listen);
}

/** The pack downloading now and those waiting their turn, by id. */
export function downloads(): { active: string | null; waiting: string[] } {
  return { active: jobs[0]?.pack.id ?? null, waiting: jobs.slice(1).map((j) => j.pack.id) };
}

/**
 * Download `pack`, check it against its checksum, and keep it (in place of the same area's older map); the outcome.
 * One at a time for the whole app: a pack already downloading or waiting is joined, any other waits its turn. The whole
 * map, once kept, removes the separate areas.
 */
export function downloadPack(pack: PackInfo, list: PackList, fetcher: typeof fetch = fetch, store: PackStore = indexedDbStore): Promise<DownloadOutcome> {
  const same = jobs.find((j) => j.pack.sha256 === pack.sha256);
  if (same) return same.done;
  let resolve!: (outcome: DownloadOutcome) => void;
  const done = new Promise<DownloadOutcome>((r) => (resolve = r));
  jobs.push({ pack, list, fetcher, store, done, resolve });
  if (jobs.length === 1) void next();
  tell();
  return done;
}

async function next(): Promise<void> {
  const job = jobs[0];
  if (!job) return;
  const outcome = await fetchAndKeep(job.pack, job.list, job.fetcher, job.store);
  jobs.shift();
  job.resolve(outcome);
  tell();
  void next();
}

/** Stop the waiting downloads (not the one under way). */
export function cancelWaiting(): void {
  for (const job of jobs.splice(1)) job.resolve("failed");
  tell();
}

async function fetchAndKeep(pack: PackInfo, list: PackList, fetcher: typeof fetch, store: PackStore): Promise<DownloadOutcome> {
  let bytes: ArrayBuffer;
  try {
    const answer = await fetcher(pack.url);
    if (!answer.ok) return "failed";
    bytes = await answer.arrayBuffer();
    if ((await sha256Hex(bytes)) !== pack.sha256) return "failed";
  } catch {
    return "failed";
  }
  try {
    await store.put(pack.id, bytes);
  } catch (error) {
    return error instanceof DOMException && error.name === "QuotaExceededError" ? "no-room" : "failed";
  }
  const before = keptPacks();
  const kept: KeptPack = { id: pack.id, name: pack.name, buildId: list.buildId, bytes: bytes.byteLength, sha256: pack.sha256, levelFactor: list.levelFactor, key: pack.id };
  // The whole map stands for every area: the separate ones are removed once it is in.
  const gone = pack.area?.whole ? before.filter((k) => k.id !== pack.id) : before.filter((k) => k.id === pack.id && k.key !== pack.id);
  writeKept([...before.filter((k) => k.id !== pack.id && !gone.includes(k)), kept]);
  for (const k of gone) await store.delete(k.key).catch(() => undefined);
  return "kept";
}

/** Remove one kept pack. */
export async function removePack(id: string, store: PackStore = indexedDbStore): Promise<void> {
  const before = keptPacks();
  const gone = before.filter((k) => k.id === id);
  writeKept(before.filter((k) => k.id !== id));
  for (const k of gone) await store.delete(k.key).catch(() => undefined);
}

/** Remove every kept pack, and the downloads waiting. */
export async function removeAll(store: PackStore = indexedDbStore): Promise<void> {
  cancelWaiting();
  const before = keptPacks();
  writeKept([]);
  for (const k of before) await store.delete(k.key).catch(() => undefined);
}

// ---- Opening a pack for a ride -----------------------------------------------------------------------------------

/** Unzip gzip bytes (DecompressionStream, in every browser the app supports). */
async function gunzip(bytes: ArrayBuffer): Promise<string> {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}

export interface OpenedPack {
  graph: CorridorGraph;
  levelFactor: number[];
}

/** Kept pack `id`'s network and its stored level prices, for a ride; null when it is not kept or cannot be read. */
export async function openPack(id: string, store: PackStore = indexedDbStore): Promise<OpenedPack | null> {
  const kept = keptPacks().find((k) => k.id === id);
  if (!kept) return null;
  try {
    const bytes = await store.get(kept.key);
    if (!bytes) return null;
    const graph = JSON.parse(await gunzip(bytes)) as unknown;
    return readableGraph(graph) ? { graph, levelFactor: kept.levelFactor } : null;
  } catch {
    return null;
  }
}

/**
 * The kept packs for one ride: `open(here)` opens the one covering the rider, held for the ride while it stays the one
 * that covers; another area's lets the first go, so only one is ever in memory. A failed open is tried again next time.
 */
export function ridePacks(store: PackStore = indexedDbStore) {
  let held: { id: string; open: Promise<OpenedPack | null> } | null = null;
  return {
    any: () => keptPacks().length > 0,
    open(here: LonLat | null | undefined): Promise<OpenedPack | null> | null {
      const id = packFor(here);
      if (!id) return null;
      if (held?.id !== id) {
        const mine = { id, open: openPack(id, store) };
        held = mine;
        void mine.open.then((pack) => {
          if (!pack && held === mine) held = null;
        });
      }
      return held.open;
    },
  };
}
