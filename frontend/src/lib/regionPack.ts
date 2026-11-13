/**
 * The region pack for riding off grid (Stephen, 2026-11-12: "the one mile would be a default, with a whole region pack
 * an optional download. Potentially split it by subregion"): the whole road network of one riding area, downloaded in
 * Settings and kept on this device (one at a time, our default), so a ride with no signal finds its way back to the
 * route even beyond the mile kept with the route (lib/offlineWayBack.ts).
 *
 * The packs are listed by GET /api/offline/packs and served as gzip JSON (core/offline_packs.py). The pack is kept
 * compressed in IndexedDB (REGION_PACK_DB) with its checksum, and opened (unzipped and read) only for a ride. Its name
 * and size are also kept in localStorage, so Settings shows them without opening the database. Map data only: nothing
 * about the rider.
 */
import { readableGraph, type CorridorGraph } from "./offlineRouter.ts";
import { t } from "./i18n.ts";

export const REGION_PACK_DB = "routemaker-region-pack";
const STATUS_KEY = "routemaker.regionPack";

// ---- Words (Settings > Riding; Go and Ride's 20 languages) ----------------------------------------------------------

export const PACK_LABEL = t("Map for no signal");
export const PACK_NONE = t("None");
export const PACK_HELP = t(
  "With no signal, a ride finds its way back to the route on this phone: near the route always, and anywhere in the area downloaded here. One area at a time; it updates when the map does.",
);
export const PACK_DOWNLOADING = t("Downloading…");
export const PACK_KEPT = t("Kept on this phone.");
export const PACK_FAILED = t("Could not download it. Try again with a signal.");
export const PACK_NO_ROOM = t("Not enough room on this phone.");
export const PACK_NO_LIST = t("Needs a signal to list the maps.");

/** The areas' names in the page's language, by the server's ids (core/offline_packs.py REGIONS); the server's own name for any other. */
const AREA_NAMES: Readonly<Record<string, string>> = {
  beltway: t("Inside the Beltway"),
  nova: t("Northern Virginia"),
  "nw-exurbs": t("Northwest exurbs"),
  baltimore: t("Baltimore and suburbs"),
  rest: t("The rest of the map"),
};

export function areaName(id: string, serverName: string): string {
  return AREA_NAMES[id] ?? serverName;
}

/** One pack as GET /api/offline/packs lists it. */
export interface PackInfo {
  id: string;
  name: string;
  bytes: number;
  sha256: string;
  url: string;
}

export interface PackList {
  buildId: string;
  packs: PackInfo[];
  levelFactor: number[];
}

/** What is kept: which pack, from which map, and its size; the bytes are in the database. */
export interface KeptPack {
  id: string;
  name: string;
  buildId: string;
  bytes: number;
  sha256: string;
  /** The level prices the list gave with it (the Default ride type), for a ride whose own could not be fetched. */
  levelFactor: number[];
}

/** The packs on offer, or null (no signal, not built yet, refused). Never throws. */
export async function fetchPackList(fetcher: typeof fetch = fetch): Promise<PackList | null> {
  try {
    const answer = await fetcher("/api/offline/packs?preset=default");
    if (!answer.ok) return null;
    const body = (await answer.json()) as { build_id?: unknown; packs?: unknown; level_factor?: unknown };
    if (typeof body.build_id !== "string" || !Array.isArray(body.packs) || !Array.isArray(body.level_factor)) return null;
    const packs = body.packs.filter(
      (p): p is PackInfo =>
        !!p &&
        typeof p.id === "string" &&
        typeof p.name === "string" &&
        typeof p.bytes === "number" &&
        typeof p.sha256 === "string" &&
        typeof p.url === "string" &&
        p.url.startsWith("/offline-packs/"),
    );
    return { buildId: body.build_id, packs, levelFactor: body.level_factor as number[] };
  } catch {
    return null;
  }
}

/** The kept pack's name and size, from localStorage; null when none (or storage is not readable). */
export function keptPack(): KeptPack | null {
  try {
    const raw = localStorage.getItem(STATUS_KEY);
    if (!raw) return null;
    const kept = JSON.parse(raw) as KeptPack;
    return kept && typeof kept.id === "string" && typeof kept.name === "string" ? kept : null;
  } catch {
    return null;
  }
}

function writeStatus(kept: KeptPack | null): void {
  try {
    if (kept) localStorage.setItem(STATUS_KEY, JSON.stringify(kept));
    else localStorage.removeItem(STATUS_KEY);
  } catch {
    // Private mode: the pack still works this session; Settings just will not remember it.
  }
}

// ---- The bytes, in IndexedDB --------------------------------------------------------------------------------------

/** The storage the pack's bytes go to: IndexedDB in the app, a stand-in in tests. */
export interface PackStore {
  put(bytes: ArrayBuffer): Promise<void>;
  get(): Promise<ArrayBuffer | null>;
  clear(): Promise<void>;
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
  put: async (bytes) => {
    await run("readwrite", (s) => s.put(bytes, "pack"));
  },
  get: async () => ((await run<ArrayBuffer | undefined>("readonly", (s) => s.get("pack") as IDBRequest<ArrayBuffer | undefined>)) ?? null),
  clear: async () => {
    await run("readwrite", (s) => s.delete("pack"));
  },
};

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}

export type DownloadOutcome = "kept" | "failed" | "no-room";

/**
 * Download `pack`, check it against its checksum, and keep it in place of any kept before; the outcome. The pack kept
 * before stays until the new one is checked and stored.
 */
export async function downloadPack(
  pack: PackInfo,
  list: PackList,
  fetcher: typeof fetch = fetch,
  store: PackStore = indexedDbStore,
): Promise<DownloadOutcome> {
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
    await store.put(bytes);
  } catch (error) {
    return error instanceof DOMException && error.name === "QuotaExceededError" ? "no-room" : "failed";
  }
  writeStatus({ id: pack.id, name: pack.name, buildId: list.buildId, bytes: bytes.byteLength, sha256: pack.sha256, levelFactor: list.levelFactor });
  return "kept";
}

/** Remove the kept pack. */
export async function removePack(store: PackStore = indexedDbStore): Promise<void> {
  writeStatus(null);
  try {
    await store.clear();
  } catch {
    // Nothing more to do: the status is gone, so nothing will try to open it.
  }
}

/** Unzip gzip bytes (DecompressionStream, in every browser the app supports). */
async function gunzip(bytes: ArrayBuffer): Promise<string> {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}

/** The kept pack's network and its stored level prices, for a ride; null when none is kept or it cannot be read. */
export async function openPack(store: PackStore = indexedDbStore): Promise<{ graph: CorridorGraph; levelFactor: number[] } | null> {
  const kept = keptPack();
  if (!kept) return null;
  try {
    const bytes = await store.get();
    if (!bytes) return null;
    const graph = JSON.parse(await gunzip(bytes)) as unknown;
    return readableGraph(graph) ? { graph, levelFactor: kept.levelFactor } : null;
  } catch {
    return null;
  }
}
