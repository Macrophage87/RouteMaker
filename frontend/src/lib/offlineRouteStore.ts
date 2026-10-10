/**
 * Where the routes kept for offline live (WEB-NAV-plan.md section 8, phase P3; OWNER-DECISIONS 465a;
 * the pure part is lib/offlineRoutes.ts, the keeping itself lib/offlineKeep.ts):
 *
 * - IndexedDB, database OFFLINE_DB: `routes` (one record per kept route: the plan, its API answer,
 *   the tiles and ranges it uses) and `ranges` (the base map's byte ranges, keyed "offset:length",
 *   with the archive's ETag, as the ride's corridor keeps them).
 * - Cache Storage, bucket OFFLINE_BUCKET: the stress tiles, the style's glyphs and its sprite, by URL.
 *   The service worker reads the glyphs and sprite from it (src/sw/swCore.mjs, the "kept" rule); the
 *   page's stress protocol reads the tiles (corridorStore.ts `corridorStress`).
 *
 * Kept apart from a ride's corridor (corridorStore.ts: CORRIDOR_BUCKET, CORRIDOR_DB), which End ride
 * clears; nothing here is cleared but by the rider's Remove. This module imports nothing of the
 * corridor's, so the corridor can read it (a kept route's ranges answer when the network fails).
 * Nothing here holds a position.
 */
import type { KeptRange, RangeStore } from "./corridor.ts";
import type { KeptRoute } from "./offlineRoutes.ts";

export const OFFLINE_DB = "routemaker-offline";
/** Also named in src/sw/swCore.mjs (a test holds the two equal). */
export const OFFLINE_BUCKET = "routemaker-offline-v1";
/** How many routes are kept (a count, never a place), so the page knows without opening the database. */
const COUNT_KEY = "routemaker.offlineRoutes";

type Store = "routes" | "ranges";

let opened: Promise<IDBDatabase> | null = null;

function db(): Promise<IDBDatabase> {
  if (typeof indexedDB === "undefined") return Promise.reject(new Error("no IndexedDB"));
  return (opened ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(OFFLINE_DB, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("routes", { keyPath: "id" });
      request.result.createObjectStore("ranges", { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      opened = null;
      reject(request.error);
    };
  }));
}

async function run<T>(name: Store, mode: IDBTransactionMode, act: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const store = (await db()).transaction(name, mode).objectStore(name);
  return new Promise<T>((resolve, reject) => {
    const request = act(store);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

// ---- The routes ------------------------------------------------------------------------------------

export async function listKept<A = unknown>(): Promise<KeptRoute<A>[]> {
  try {
    const all = await run<KeptRoute<A>[]>("routes", "readonly", (s) => s.getAll() as IDBRequest<KeptRoute<A>[]>);
    writeCount(all.length);
    return all;
  } catch {
    return [];
  }
}

export async function putKept(route: KeptRoute): Promise<void> {
  await run("routes", "readwrite", (s) => s.put(route));
}

export async function getKept<A = unknown>(id: string): Promise<KeptRoute<A> | undefined> {
  try {
    return await run<KeptRoute<A> | undefined>("routes", "readonly", (s) => s.get(id) as IDBRequest<KeptRoute<A> | undefined>);
  } catch {
    return undefined;
  }
}

export async function deleteKept(id: string): Promise<void> {
  await run("routes", "readwrite", (s) => s.delete(id));
}

function writeCount(n: number): void {
  try {
    if (n > 0) localStorage.setItem(COUNT_KEY, String(n));
    else localStorage.removeItem(COUNT_KEY);
  } catch {
    // No storage: the page opens the database when it needs to know.
  }
}

/** Whether any route is kept, as last counted (no database opened). */
export function anyKept(): boolean {
  try {
    return Number(localStorage.getItem(COUNT_KEY) ?? "0") > 0;
  } catch {
    return false;
  }
}

// ---- The base map's ranges -------------------------------------------------------------------------

/** The kept ranges, for the archive's source when the network fails (corridor.ts CorridorSource `fallback`). */
export const keptRanges: Pick<RangeStore, "get"> = {
  async get(key: string): Promise<KeptRange | undefined> {
    return run<KeptRange | undefined>("ranges", "readonly", (s) => s.get(key) as IDBRequest<KeptRange | undefined>);
  },
};

export async function putRange(range: KeptRange): Promise<void> {
  await run("ranges", "readwrite", (s) => s.put(range));
}

export async function deleteRanges(keys: readonly string[]): Promise<void> {
  if (!keys.length) return;
  const store = (await db()).transaction("ranges", "readwrite").objectStore("ranges");
  await Promise.all(
    keys.map(
      (key) =>
        new Promise<void>((resolve, reject) => {
          const request = store.delete(key);
          request.onsuccess = () => resolve();
          request.onerror = () => reject(request.error);
        }),
    ),
  );
}

// ---- The tiles, glyphs and sprite ------------------------------------------------------------------

/** A kept stress tile, for the stress protocol when the network fails. */
export async function keptTile(url: string): Promise<ArrayBuffer | null> {
  try {
    if (typeof caches === "undefined") return null;
    const hit = await (await caches.open(OFFLINE_BUCKET)).match(url);
    return hit ? await hit.arrayBuffer() : null;
  } catch {
    return null;
  }
}

export async function hasTile(url: string): Promise<boolean> {
  try {
    if (typeof caches === "undefined") return false;
    return !!(await (await caches.open(OFFLINE_BUCKET)).match(url));
  } catch {
    return false;
  }
}

export async function putTile(url: string, response: Response): Promise<void> {
  await (await caches.open(OFFLINE_BUCKET)).put(url, response);
}

export async function deleteTiles(urls: readonly string[]): Promise<void> {
  if (!urls.length || typeof caches === "undefined") return;
  const cache = await caches.open(OFFLINE_BUCKET);
  await Promise.all(urls.map((url) => cache.delete(url)));
}

// ---- Asking the browser to keep it ------------------------------------------------------------------

/** `navigator.storage.persist()`, asked at the rider's press (plan section 8): true, false, or null where there is none. */
export async function askPersist(): Promise<boolean | null> {
  try {
    const storage = typeof navigator === "undefined" ? undefined : navigator.storage;
    if (!storage?.persist) return null;
    if (await storage.persisted?.()) return true;
    return await storage.persist();
  } catch {
    return null;
  }
}

export async function persisted(): Promise<boolean | null> {
  try {
    const storage = typeof navigator === "undefined" ? undefined : navigator.storage;
    return storage?.persisted ? await storage.persisted() : null;
  } catch {
    return null;
  }
}
