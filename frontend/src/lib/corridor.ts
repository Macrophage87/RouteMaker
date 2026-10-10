/**
 * Ride mode in dead spots (WEB-NAV-plan.md section 6, phase N5): the map along the ride's route,
 * fetched at Start ride and kept for the ride, so a stretch with no signal (Rock Creek, a tunnel, a
 * tree canopy) still shows the stress lines and the base map under the rider. No service worker yet
 * (that is phase P2): the page itself keeps the tiles and reads them back when the network fails.
 *
 * - Which tiles: every tile within CORRIDOR_M (about 1,000 ft) of the line, at the zooms a ride shows:
 *   the stress tiles at z12-14 (the source's deepest; z15-16 are drawn from z14, mapStyle.ts
 *   STRESS_ZOOMS), the base map at z12-15 (deeper zooms past the archive's own are drawn from its
 *   deepest). `corridorTiles` walks the line in order, so the start's tiles come first.
 * - Pacing (plan section 10, "server load"): one prefetch request at a time, and for the stress tiles
 *   through the protocol's own page queue (stressProtocol.ts: at most two of the page's requests in
 *   flight, the API's per-client draw cap) with STRESS_GAP_MS between them: at most 240 a minute, well
 *   under the 600 a minute tile limit (core/ratelimit.py TILES), and a refused draw (429 or 503) is
 *   backed off as the map's own are. At most MAX_JOBS tiles a route, and MAX_BYTES kept in all.
 * - The base map is one file read by HTTP range (Caddyfile, `/basemap/*`), which Cache Storage cannot
 *   hold (it refuses 206 answers), so `CorridorSource` sits under the pmtiles protocol's archive and
 *   keeps the byte ranges it reads (the header, the directories, the corridor's tiles) in a store
 *   keyed by offset and length, with the archive's ETag: a refreshed archive under the same name
 *   empties the store rather than mixing two files' bytes.
 *
 * Privacy (plan section 7): only tiles and map bytes are kept, never a position; everything is
 * cleared at End ride, and anything older than KEEP_MS is cleared at the next page load.
 */
import type { RangeResponse, Source } from "pmtiles";
import { lonLatToTile, type LonLat } from "./geo.ts";

/** About 1,000 ft (300 m) either side of the line (plan section 6). */
export const CORRIDOR_M = 300;
/** The stress tiles a ride shows: z12 ("where to ride") to the source's z14. */
export const STRESS_PREFETCH_ZOOMS = [14, 13, 12] as const;
/** The base map's: z15 down to z12 (the follow camera opens at z16, drawn from the deepest). */
export const BASE_PREFETCH_ZOOMS = [15, 14, 13, 12] as const;
/** At most this many tiles a route (a 30 mi ride at these zooms is about 1,100). */
export const MAX_JOBS = 1500;
/** At most this many bytes kept in all (plan section 6: "capped (e.g. 40 MB)"). */
export const MAX_BYTES = 40 * 1024 * 1024;
/** Between two stress tile requests: at most 240 a minute from the prefetch. */
export const STRESS_GAP_MS = 250;
/** Between two base map tiles: a file on the edge's disk, no draw, so less. */
export const BASE_GAP_MS = 50;
/** Failures in a row that stop one kind of tile (no signal, or the base map not served). */
export const STOP_AFTER_FAILURES = 4;
/** Kept this long at most (plan section 6: "cleared at End ride or after 24 h"). */
export const KEEP_MS = 24 * 60 * 60_000;

const EARTH_M = 40_075_016.686;

export interface TileJob {
  kind: "stress" | "base";
  z: number;
  x: number;
  y: number;
}

export function jobKey(job: TileJob): string {
  return `${job.kind}/${job.z}/${job.x}/${job.y}`;
}

/**
 * The tiles within `bufferM` of the line at zoom `z`, in the order the line reaches them. The line is
 * sampled at a step under the buffer and half a tile, and each sample adds the tiles its box touches,
 * so no tile the corridor crosses is skipped between two samples.
 */
export function corridorTiles(line: readonly LonLat[], z: number, bufferM = CORRIDOR_M): { z: number; x: number; y: number }[] {
  const out: { z: number; x: number; y: number }[] = [];
  const seen = new Set<string>();
  if (!line.length) return out;
  const add = ([lon, lat]: LonLat) => {
    const dLat = bufferM / 111_195;
    const dLon = bufferM / (111_195 * Math.max(Math.cos((lat * Math.PI) / 180), 0.01));
    const nw = lonLatToTile([lon - dLon, lat + dLat], z);
    const se = lonLatToTile([lon + dLon, lat - dLat], z);
    for (let x = nw.x; x <= se.x; x += 1) {
      for (let y = nw.y; y <= se.y; y += 1) {
        const key = `${x}/${y}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ z, x, y });
      }
    }
  };
  add(line[0]);
  for (let i = 1; i < line.length; i += 1) {
    const a = line[i - 1];
    const b = line[i];
    const tileM = (EARTH_M * Math.cos((a[1] * Math.PI) / 180)) / 2 ** z;
    const stepM = Math.max(10, Math.min(bufferM, tileM / 2));
    const kx = 111_195 * Math.cos((a[1] * Math.PI) / 180);
    const lengthM = Math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 111_195);
    const steps = Math.max(1, Math.ceil(lengthM / stepM));
    for (let s = 1; s <= steps; s += 1) add([a[0] + ((b[0] - a[0]) * s) / steps, a[1] + ((b[1] - a[1]) * s) / steps]);
  }
  return out;
}

/**
 * The prefetch's list for a route: the deepest zooms first (what the follow camera shows), the stress
 * and the base map's alternately, each in route order; at most MAX_JOBS, leaving out any in `done`
 * (a re-plan fetches only what the first route did not).
 */
export function corridorJobs(line: readonly LonLat[], done: ReadonlySet<string> = new Set(), max = MAX_JOBS): { jobs: TileJob[]; capped: boolean } {
  const jobs: TileJob[] = [];
  let capped = false;
  const levels = Math.max(STRESS_PREFETCH_ZOOMS.length, BASE_PREFETCH_ZOOMS.length);
  for (let level = 0; level < levels; level += 1) {
    const kinds: [TileJob["kind"], number | undefined][] = [
      ["stress", STRESS_PREFETCH_ZOOMS[level]],
      ["base", BASE_PREFETCH_ZOOMS[level]],
    ];
    for (const [kind, z] of kinds) {
      if (z === undefined) continue;
      for (const tile of corridorTiles(line, z)) {
        const job = { kind, ...tile };
        if (done.has(jobKey(job))) continue;
        if (jobs.length >= max) {
          capped = true;
          continue;
        }
        jobs.push(job);
      }
    }
  }
  return { jobs, capped };
}

export interface PrefetchDeps {
  /** Fetch and keep one tile; false where it failed. */
  fetch: (job: TileJob, signal: AbortSignal) => Promise<boolean>;
  /** The style's glyphs and sprites, once, before the tiles. */
  extras?: (signal: AbortSignal) => Promise<void>;
  /** Whether the kept bytes have reached MAX_BYTES: the prefetch stops. */
  full?: () => boolean;
  wait?: (ms: number, signal: AbortSignal) => Promise<void>;
  signal: AbortSignal;
  /** Keys of the tiles kept, added to as each comes. */
  done: Set<string>;
}

export interface PrefetchResult {
  kept: number;
  failed: number;
  total: number;
  /** The route had more tiles than MAX_JOBS, or the store filled. */
  capped: boolean;
  /** Ended at End ride (or a newer route), not finished. */
  stopped: boolean;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

/**
 * Fetch the corridor's tiles one at a time, paced (STRESS_GAP_MS, BASE_GAP_MS). A kind that fails
 * STOP_AFTER_FAILURES times in a row is stopped (no signal: the next route or ride tries again; a base
 * map that is not served: nothing to keep), so a dead spot at Start ride is not a minute of refusals.
 */
export async function prefetchCorridor(line: readonly LonLat[], deps: PrefetchDeps): Promise<PrefetchResult> {
  const wait = deps.wait ?? sleep;
  const { jobs, capped } = corridorJobs(line, deps.done);
  const result: PrefetchResult = { kept: 0, failed: 0, total: jobs.length, capped, stopped: false };
  if (deps.extras) {
    try {
      await deps.extras(deps.signal);
    } catch {
      // The glyphs and sprites are a nicety: the tiles still come.
    }
  }
  const failures = { stress: 0, base: 0 };
  for (const job of jobs) {
    if (deps.signal.aborted) {
      result.stopped = true;
      break;
    }
    if (deps.full?.()) {
      result.capped = true;
      break;
    }
    if (failures[job.kind] >= STOP_AFTER_FAILURES) continue;
    let ok = false;
    try {
      ok = await deps.fetch(job, deps.signal);
    } catch {
      ok = false;
    }
    if (deps.signal.aborted) {
      result.stopped = true;
      break;
    }
    if (ok) {
      failures[job.kind] = 0;
      result.kept += 1;
      deps.done.add(jobKey(job));
    } else {
      failures[job.kind] += 1;
      result.failed += 1;
    }
    await wait(job.kind === "stress" ? STRESS_GAP_MS : BASE_GAP_MS, deps.signal);
  }
  return result;
}

/** What Ride mode shows of it: a line under the controls, not said (it would only talk over the cues). */
export function corridorNote(result: PrefetchResult | "saving" | null): string {
  if (result === null) return "";
  if (result === "saving") return "Saving the map along the route for dead spots…";
  if (result.stopped) return "";
  if (result.kept === 0 && result.total > 0) return "The map along the route could not be saved; it needs a signal to show.";
  if (result.capped) return "The map along the first part of the route is saved for dead spots.";
  return "The map along the route is saved for dead spots.";
}

// ---- The base map's byte ranges -----------------------------------------------------------------

export interface KeptRange {
  /** `${offset}:${length}`. */
  key: string;
  etag: string | undefined;
  data: ArrayBuffer;
}

/** Where the ranges are kept: IndexedDB in the page (corridorStore.ts), a Map in the tests. */
export interface RangeStore {
  get(key: string): Promise<KeptRange | undefined>;
  put(range: KeptRange): Promise<void>;
  clear(): Promise<void>;
}

export function memoryRangeStore(): RangeStore & { ranges: Map<string, KeptRange> } {
  const ranges = new Map<string, KeptRange>();
  return {
    ranges,
    get: async (key) => ranges.get(key),
    put: async (range) => void ranges.set(range.key, range),
    clear: async () => ranges.clear(),
  };
}

/** The bytes kept in all (the stress tiles and the base map's ranges), against MAX_BYTES. */
export class ByteBudget {
  bytes = 0;
  readonly max: number;
  constructor(max = MAX_BYTES) {
    this.max = max;
  }
  /** Whether `n` more bytes fit; if so they are counted. */
  take(n: number): boolean {
    if (this.bytes + n > this.max) return false;
    this.bytes += n;
    return true;
  }
  get full(): boolean {
    return this.bytes >= this.max;
  }
  /** `n` bytes no longer kept. */
  give(n: number): void {
    this.bytes = Math.max(0, this.bytes - n);
  }
  reset(): void {
    this.bytes = 0;
  }
}

function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

/**
 * The archive's source for the pmtiles protocol: the network as before, and while a ride is on
 * (`keeping`), every range it reads is kept. A range asked for with the archive's ETag (a directory or
 * a tile: the same bytes for as long as the file is the same) is answered from the store first; the
 * header (asked with no ETag, to find out whether the file changed) goes to the network first. When
 * the network fails, any kept range of the same file answers.
 */
export class CorridorSource implements Source {
  keeping = false;
  private etag: string | undefined;
  private keptBytes = 0;
  private readonly inner: Source;
  private readonly store: RangeStore;
  private readonly budget: ByteBudget;
  private readonly fallback: Pick<RangeStore, "get"> | undefined;

  /**
   * `fallback` is the routes the rider kept for offline (lib/offlineRouteStore.ts, phase P3): read only
   * when the network fails, after the ride's own store, and never written or cleared from here.
   */
  constructor(inner: Source, store: RangeStore, budget: ByteBudget, fallback?: Pick<RangeStore, "get">) {
    this.inner = inner;
    this.store = store;
    this.budget = budget;
    this.fallback = fallback;
  }

  getKey(): string {
    return this.inner.getKey();
  }

  async getBytes(offset: number, length: number, signal?: AbortSignal, etag?: string): Promise<RangeResponse> {
    const key = `${offset}:${length}`;
    // Outside a ride, with nothing kept, the store is not touched at all: the archive reads exactly as
    // the plain FetchSource does (a first IndexedDB open takes about a second, and a header refusal held
    // back that long kept MapLibre's style from loading in the browser suite).
    const stored = this.keeping || this.keptBytes > 0;
    if (stored && etag !== undefined) {
      const kept = await this.read(key);
      if (kept && kept.etag === etag) return { data: kept.data, etag: kept.etag };
    }
    try {
      const answer = await this.inner.getBytes(offset, length, signal, etag);
      if (this.keeping) await this.keep(key, answer);
      return answer;
    } catch (error) {
      if (isAbort(error)) throw error;
      // The header's own (no ETag asked): any kept copy is the file the kept tiles came from.
      const fits = (kept: KeptRange | undefined): kept is KeptRange => !!kept && (etag === undefined || kept.etag === etag);
      const kept = stored ? await this.read(key) : undefined;
      if (fits(kept)) return { data: kept.data, etag: kept.etag };
      const saved = await this.readFallback(key);
      if (fits(saved)) return { data: saved.data, etag: saved.etag };
      throw error;
    }
  }

  /** The kept routes' copy of a range, when the network failed. */
  private async readFallback(key: string): Promise<KeptRange | undefined> {
    if (!this.fallback) return undefined;
    try {
      return await this.fallback.get(key);
    } catch {
      return undefined;
    }
  }

  /** End ride: nothing more is kept, and what was is cleared. */
  async clear(): Promise<void> {
    this.keeping = false;
    this.etag = undefined;
    this.budget.give(this.keptBytes);
    this.keptBytes = 0;
    try {
      await this.store.clear();
    } catch {
      // A store the browser refused (a private window) holds nothing to clear.
    }
  }

  private async read(key: string): Promise<KeptRange | undefined> {
    try {
      return await this.store.get(key);
    } catch {
      return undefined;
    }
  }

  private async keep(key: string, answer: RangeResponse): Promise<void> {
    try {
      // A refreshed archive (a new ETag) under the same name: the old file's bytes go first.
      if (this.etag !== undefined && answer.etag !== this.etag) {
        await this.store.clear();
        this.budget.give(this.keptBytes);
        this.keptBytes = 0;
      }
      this.etag = answer.etag;
      if (!this.budget.take(answer.data.byteLength)) return;
      this.keptBytes += answer.data.byteLength;
      await this.store.put({ key, etag: answer.etag, data: answer.data });
    } catch {
      // Keeping is best effort: a full or refused store leaves the ride online-only.
    }
  }
}

// ---- The style's glyphs ---------------------------------------------------------------------------

/** The glyph ranges a ride's labels need: Basic Latin, Latin-1 and General Punctuation. */
export const GLYPH_RANGES = ["0-255", "256-511", "8192-8447"] as const;

/**
 * The single-font stacks the style's labels name ("Noto Sans Regular"), from its layers' `text-font`,
 * plain arrays or inside expressions; a script's own font ("... Devanagari Regular v1") is left out,
 * since its glyphs are not in the Latin ranges.
 */
export function fontStacks(layers: readonly unknown[]): string[] {
  const found = new Set<string>();
  const walk = (value: unknown) => {
    if (typeof value === "string") {
      if (/^[A-Z][A-Za-z ]* (Regular|Medium|Italic|Bold)$/.test(value)) found.add(value);
    } else if (Array.isArray(value)) value.forEach(walk);
  };
  for (const layer of layers) {
    const layout = (layer as { layout?: Record<string, unknown> } | null)?.layout;
    if (layout && "text-font" in layout) walk(layout["text-font"]);
  }
  return [...found].sort();
}

/** The glyph URLs for the stacks, from the style's template (`{fontstack}`, `{range}`). */
export function glyphUrls(template: string, stacks: readonly string[]): string[] {
  return stacks.flatMap((stack) => GLYPH_RANGES.map((range) => template.replace("{fontstack}", stack).replace("{range}", range)));
}
