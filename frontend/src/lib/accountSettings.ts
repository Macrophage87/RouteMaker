/**
 * Saved settings (v0.7.0 plan, "Discord sign-in on, with saved settings and routes", item 2): signed in,
 * the planning choices this device already remembers sync to the account (GET and POST /api/me/settings;
 * core.models.AccountSettings). One document per account, last write wins.
 *
 * - The favorite ride types ("favorites", lib/favoriteRides.ts), starred first in the ride type pickers.
 * - The ride type and dials ("plan": a plan link's fragment with no points), the Layers switches this
 *   device keeps (Water, Climbs and its smallest category, contour lines, each section's remembered
 *   switches) and, when the micromobility work adds them, the service switches. My Go syncs on its own
 *   (lib/myGo.ts), Home included.
 * - The rider and bike weight ("weight", lib/weight.ts; the owner, 2026-10-19: "Weight should be retained
 *   for signed in users"): kept with the account so it follows the rider, never in the plan setting, a
 *   link, a log or an AI assistant's answer, and erased with the rest by Delete account. Cleared, it is
 *   `weight: null`, so every signed-in device clears its copy rather than putting its own back.
 * - The rider's riding speed ("speed", lib/ridingSpeed.ts), whole mph; null once set back to the ride type's own,
 *   so every signed-in device goes back too.
 * - The units ("units", lib/units.ts): "us" or "metric" (the owner, 2026-11-03: "have a metric mode in settings").
 * - On sign-in (every signed-in load): an empty account takes this device's settings; an account that has
 *   settings wins, and its settings replace the device's. Where the read came late (it failed at load and was tried
 *   again, retryUntil), what the rider changed on this device since load is kept and saved to the account, and a
 *   Units choice made while the account could not be read is too (unitsPending): the rest is the account's
 *   (signInLate).
 * - Signed out, everything stays on the device as before.
 */
import { FAVORITES_KEY, parseFavorites } from "./favoriteRides.ts";
import { t } from "./i18n.ts";
import { CLIMBS_FROM_KEY, CLIMBS_KEY, CLIMB_CATEGORIES, type ClimbCategory } from "./climbs.ts";
import type { Dials } from "./dials.ts";
import { LAYER_SECTIONS_KEY } from "./layerSection.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import type { PresetId } from "./presets.ts";
import { csrfFromCookie } from "./stressEditor.ts";
import { TOPO_STORAGE_KEY } from "./topoLines.ts";
import { WEIGHT_CLEARED, WEIGHT_STORAGE_KEY, migrate as weightOf, storedSetting, type StoredWeight } from "./weight.ts";
import { SPEED_OWN, SPEED_STORAGE_KEY, speedOf, speedSetting } from "./ridingSpeed.ts";
import { WATER_PREFS_KEY, type WaterPrefs } from "./waterRestrooms.ts";
import { UNITS_STORAGE_KEY, unitsOf, unitsSetting, type Units } from "./units.ts";

export const SETTINGS_VERSION = 1;

export interface SettingsDoc {
  v: number;
  /** The ride type and dials as a plan link's fragment with no points ("#preset=...&v=..."). */
  plan?: string;
  water?: WaterPrefs;
  climbs?: boolean;
  climbsFrom?: ClimbCategory;
  topo?: boolean;
  sections?: Record<string, string[]>;
  bikeshare?: Record<string, boolean>;
  favorites?: PresetId[];
  /** The rider and bike weight (lib/weight.ts StoredWeight), or null once cleared. */
  weight?: StoredWeight | null;
  /** The rider's riding speed in whole mph (lib/ridingSpeed.ts), or null for the ride type's own. */
  speed?: number | null;
  /** The units shown and said (lib/units.ts). */
  units?: Units;
}

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

function read(store: Store | null, key: string): string | null {
  try {
    return store?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function json(raw: string | null): unknown {
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}

/** The trip-specific dials that are not settings: a station picked, a transit option, the target of one ride. */
const TRIP_DIALS: readonly (keyof Dials)[] = ["pickupStation", "dropoffStation", "transitOption", "targetDistanceM", "systemWeightKg", "ridingSpeedKmh", "loop"];

/** The ride type and dials as a settings value: no points, nothing that belongs to one trip, never the weight. */
export function planSetting(preset: PresetId, dials: Dials): string {
  const kept: Dials = { ...dials };
  for (const key of TRIP_DIALS) delete kept[key];
  return encodePlan([], preset, kept);
}

/** The ride type and dials a settings value holds, or null when it holds none. */
export function planFromSetting(plan: string | undefined): { preset: PresetId; dials: Dials } | null {
  if (typeof plan !== "string" || !/[#&]preset=/.test(plan) || /(^|[#&])[pq]=/.test(plan)) return null;
  const decoded = decodePlan(plan);
  return { preset: decoded.preset, dials: decoded.dials };
}

function waterOf(value: unknown): WaterPrefs | undefined {
  if (!value || typeof value !== "object") return undefined;
  const v = value as Record<string, unknown>;
  if (typeof v.on !== "boolean" || typeof v.basic !== "boolean" || typeof v.untreated !== "boolean") return undefined;
  return { on: v.on, basic: v.basic, untreated: v.untreated };
}

function sectionsOf(value: unknown): Record<string, string[]> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const out: Record<string, string[]> = {};
  for (const [id, keys] of Object.entries(value as Record<string, unknown>)) {
    if (Array.isArray(keys) && keys.every((k) => typeof k === "string")) out[id] = keys as string[];
  }
  return out;
}

function flagsOf(value: unknown): Record<string, boolean> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const out: Record<string, boolean> = {};
  for (const [id, on] of Object.entries(value as Record<string, unknown>)) if (typeof on === "boolean") out[id] = on;
  return out;
}

/** The parts of an answered or stored document that make sense; anything else is left out. */
export function parseSettings(raw: unknown): SettingsDoc | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const body = raw as Record<string, unknown>;
  const doc: SettingsDoc = { v: SETTINGS_VERSION };
  if (typeof body.plan === "string" && planFromSetting(body.plan)) doc.plan = body.plan;
  const water = waterOf(body.water);
  if (water) doc.water = water;
  if (typeof body.climbs === "boolean") doc.climbs = body.climbs;
  if (typeof body.climbsFrom === "string" && (CLIMB_CATEGORIES as readonly string[]).includes(body.climbsFrom)) doc.climbsFrom = body.climbsFrom as ClimbCategory;
  if (typeof body.topo === "boolean") doc.topo = body.topo;
  const sections = sectionsOf(body.sections);
  if (sections) doc.sections = sections;
  const bikeshare = flagsOf(body.bikeshare);
  if (bikeshare) doc.bikeshare = bikeshare;
  if (Array.isArray(body.favorites)) doc.favorites = parseFavorites(body.favorites);
  if (body.weight === null) doc.weight = null;
  else if (body.weight !== undefined) {
    const weight = weightOf(body.weight);
    if (weight) doc.weight = weight;
  }
  if (body.speed === null) doc.speed = null;
  else if (speedOf(body.speed) !== null) doc.speed = speedOf(body.speed);
  const units = unitsOf(body.units);
  if (units) doc.units = units;
  return doc;
}

/** Whether a document holds any setting at all (an empty account holds none). */
export function hasSettings(doc: SettingsDoc | null): boolean {
  return doc !== null && Object.keys(doc).some((key) => key !== "v");
}

/**
 * This device's settings as a document: what it keeps, and the ride type and dials in use. The weight is
 * App's (WeightStore.setting(), which holds it even where the browser refuses storage); left out, it is
 * read from the store.
 */
export function deviceSettings(
  plan: { preset: PresetId; dials: Dials } | null,
  store: Store | null = local(),
  weight: StoredWeight | null | undefined = storedSetting(read(store, WEIGHT_STORAGE_KEY)),
): SettingsDoc {
  const doc: SettingsDoc = { v: SETTINGS_VERSION };
  if (plan) doc.plan = planSetting(plan.preset, plan.dials);
  const water = waterOf(json(read(store, WATER_PREFS_KEY)));
  if (water) doc.water = water;
  const climbs = read(store, CLIMBS_KEY);
  if (climbs === "1" || climbs === "0") doc.climbs = climbs === "1";
  const from = read(store, CLIMBS_FROM_KEY);
  if (from && (CLIMB_CATEGORIES as readonly string[]).includes(from)) doc.climbsFrom = from as ClimbCategory;
  const topo = read(store, TOPO_STORAGE_KEY);
  if (topo === "on" || topo === "off") doc.topo = topo === "on";
  const sections = sectionsOf(json(read(store, LAYER_SECTIONS_KEY)));
  if (sections && Object.keys(sections).length) doc.sections = sections;
  const favorites = json(read(store, FAVORITES_KEY));
  if (Array.isArray(favorites)) doc.favorites = parseFavorites(favorites);
  if (weight !== undefined) doc.weight = weight;
  const speed = speedSetting(read(store, SPEED_STORAGE_KEY));
  if (speed !== undefined) doc.speed = speed;
  const units = unitsSetting(read(store, UNITS_STORAGE_KEY));
  if (units) doc.units = units;
  return doc;
}

/** Put an account's settings on this device, where the page reads them; what the account lacks is left as it is. */
export function applyToDevice(doc: SettingsDoc, store: Store | null = local()): void {
  const write = (key: string, value: string) => {
    try {
      store?.setItem(key, value);
    } catch {
      // Not kept: the page still uses them for this visit.
    }
  };
  if (doc.water) write(WATER_PREFS_KEY, JSON.stringify(doc.water));
  if (doc.climbs !== undefined) write(CLIMBS_KEY, doc.climbs ? "1" : "0");
  if (doc.climbsFrom) write(CLIMBS_FROM_KEY, doc.climbsFrom);
  if (doc.topo !== undefined) write(TOPO_STORAGE_KEY, doc.topo ? "on" : "off");
  if (doc.sections) write(LAYER_SECTIONS_KEY, JSON.stringify(doc.sections));
  if (doc.favorites) write(FAVORITES_KEY, JSON.stringify(doc.favorites));
  if (doc.weight !== undefined) write(WEIGHT_STORAGE_KEY, doc.weight === null ? WEIGHT_CLEARED : JSON.stringify(doc.weight));
  if (doc.speed !== undefined) write(SPEED_STORAGE_KEY, doc.speed === null ? SPEED_OWN : String(doc.speed));
  if (doc.units) write(UNITS_STORAGE_KEY, doc.units);
}

export type SignInStep = { kind: "push-device"; doc: SettingsDoc } | { kind: "use-account"; doc: SettingsDoc };

/**
 * What a signed-in load does with the two: an account with no settings takes this device's; an account
 * with settings wins (the plan's default: "account settings win over device on sign-in"), and nothing merges.
 */
export function onSignIn(account: SettingsDoc | null, device: SettingsDoc): SignInStep {
  return hasSettings(account) ? { kind: "use-account", doc: account as SettingsDoc } : { kind: "push-device", doc: device };
}

/** The settings a document holds, by key, for comparing one with another. */
const KEYS: readonly (keyof SettingsDoc)[] = ["plan", "water", "climbs", "climbsFrom", "topo", "sections", "bikeshare", "favorites", "weight", "speed", "units"];

/**
 * The sign-in step where the account's settings were read late (the 2026-11-05 review: a read that failed at load
 * succeeded mid-ride and replaced what the rider had changed since). `atLoad` is this device's settings when the
 * page first asked; each key the device has changed since, and the units where a choice is pending (made while the
 * account could not be read), are the device's; the rest are the account's. `save` is the document to put in the
 * account, or null where it holds it already.
 */
export function signInLate(account: SettingsDoc | null, device: SettingsDoc, atLoad: SettingsDoc, unitsPending = false): SignInStep & { save: SettingsDoc | null } {
  const step = onSignIn(account, device);
  if (step.kind === "push-device") return { ...step, save: device };
  const kept = KEYS.filter((key) => JSON.stringify(device[key]) !== JSON.stringify(atLoad[key]) || (key === "units" && unitsPending));
  if (kept.length === 0) return { ...step, save: null };
  const doc: SettingsDoc = { ...step.doc };
  for (const key of kept) {
    if (key === "favorites") {
      // Star by star: a ride starred or unstarred here, and the account's other stars (another device's) kept.
      const was = new Set(atLoad.favorites ?? []);
      const now = new Set(device.favorites ?? []);
      const starred = [...now].filter((id) => !was.has(id));
      const unstarred = new Set([...was].filter((id) => !now.has(id)));
      const merged = [...(step.doc.favorites ?? []), ...starred].filter((id) => !unstarred.has(id));
      doc.favorites = [...new Set(merged)];
      continue;
    }
    if (key === "sections") {
      // Section by section: the Layers sections changed here, the account's others kept.
      const sections = { ...(step.doc.sections ?? {}) };
      for (const name of new Set([...Object.keys(device.sections ?? {}), ...Object.keys(atLoad.sections ?? {})])) {
        const here = device.sections?.[name];
        if (JSON.stringify(here) === JSON.stringify(atLoad.sections?.[name])) continue;
        if (here === undefined) delete sections[name];
        else sections[name] = here;
      }
      doc.sections = sections;
      continue;
    }
    if (device[key] === undefined) delete doc[key];
    else (doc as unknown as Record<string, unknown>)[key] = device[key];
  }
  return { kind: "use-account", doc, save: sameSettings(doc, step.doc) ? null : doc };
}

/** Marks a Units choice made while the account could not be read: the next read keeps it (signInLate). */
export const UNITS_PENDING_KEY = "routemaker.unitsPending";

export function unitsPending(store: Store | null = local()): boolean {
  try {
    return store?.getItem(UNITS_PENDING_KEY) === "1";
  } catch {
    return false;
  }
}

export function setUnitsPending(pending: boolean, store: Store | null = local()): void {
  try {
    if (pending) store?.setItem(UNITS_PENDING_KEY, "1");
    else store?.removeItem(UNITS_PENDING_KEY);
  } catch {
    // Not kept: the choice still stays on this device for this visit.
  }
}

/** Two documents hold the same settings (so a save would change nothing). */
export function sameSettings(a: SettingsDoc | null, b: SettingsDoc | null): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** How long after the last change a save goes, so a slider dragged is one save, not fifty. */
export const SAVE_SETTLE_MS = 2000;

type Fetch = typeof fetch;

/** GET /api/me/settings: undefined when it could not be read (signed out, offline), null for an empty account. */
export async function fetchSettings(origin: string, get: Fetch = fetch): Promise<SettingsDoc | null | undefined> {
  try {
    const response = await get(`${origin}/api/me/settings`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { settings?: unknown };
    return body.settings === null || body.settings === undefined ? null : parseSettings(body.settings);
  } catch {
    return undefined;
  }
}

/** POST /api/me/settings: whether it was saved. */
export async function saveSettings(origin: string, doc: SettingsDoc, post: Fetch = fetch, cookie = typeof document === "undefined" ? "" : document.cookie): Promise<boolean> {
  try {
    const token = csrfFromCookie(cookie);
    const response = await post(`${origin}/api/me/settings`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: JSON.stringify({ settings: doc }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/** The waits between tries of the sign-in read of the settings, when it could not be read (a 5xx, a timeout, offline). */
export const SETTINGS_RETRY_MS: readonly number[] = [2000, 8000, 30000];

/** The window's timer and events that retryUntil uses (a test passes a stand-in). */
export interface RetryEnv {
  setTimeout(run: () => void, ms: number): number;
  clearTimeout(id: number): void;
  addEventListener(type: "focus" | "online", run: () => void): void;
  removeEventListener(type: "focus" | "online", run: () => void): void;
}

/**
 * Runs `attempt` now and again after each of `delays` until it answers true; past the last wait, on the next time the
 * page has the focus or is back online (either of which also tries at once during the waits). One try at a time.
 * Returns a stop, for when the page no longer needs the answer.
 */
export function retryUntil(attempt: () => Promise<boolean>, env: RetryEnv, delays: readonly number[] = SETTINGS_RETRY_MS): () => void {
  let stopped = false;
  let busy = false;
  let tries = 0;
  let timer: number | undefined;
  const clear = () => {
    if (timer !== undefined) env.clearTimeout(timer);
    timer = undefined;
  };
  const unlisten = () => {
    env.removeEventListener("focus", again);
    env.removeEventListener("online", again);
  };
  const run = async () => {
    if (stopped || busy) return;
    busy = true;
    const done = await attempt().catch(() => false);
    busy = false;
    if (stopped) return;
    if (done) {
      stopped = true;
      unlisten();
      return;
    }
    if (tries < delays.length) timer = env.setTimeout(() => {
      timer = undefined;
      void run();
    }, delays[tries++]);
  };
  function again() {
    if (busy) return;
    clear();
    void run();
  }
  env.addEventListener("focus", again);
  env.addEventListener("online", again);
  void run();
  return () => {
    stopped = true;
    clear();
    unlisten();
  };
}

/**
 * A Units change made before the account's settings could be read on sign-in: the account is read now and, where it
 * holds settings, saved with only the units changed (never this device's other settings over the account's). Where it
 * is empty (the sign-in read gives it this device's), the change stays on this device: true. Where it still cannot be
 * read, the change stays on this device and is marked pending, so the sign-in read, when it succeeds, keeps it and
 * saves it to the account rather than putting the account's units back (signInLate): true.
 */
export async function saveUnitsUnsynced(
  origin: string,
  units: Units | undefined,
  get: Fetch = fetch,
  post: Fetch = fetch,
  cookie?: string,
  store: Store | null = local(),
): Promise<boolean> {
  const account = await fetchSettings(origin, get);
  if (account === undefined) {
    setUnitsPending(true, store);
    return true;
  }
  if (!account) return true;
  const doc: SettingsDoc = { ...account };
  if (units) doc.units = units;
  else delete doc.units;
  const saved = await saveSettings(origin, doc, post, cookie);
  if (saved) setUnitsPending(false, store);
  return saved;
}

/** The Settings sheet's one line for a rider who can sign in (the plan, item 4). */
export const SIGN_IN_LINE = "Sign in with Discord to save routes and sync settings across devices.";
/** Said once the account's settings are in use on this device. */
export const ACCOUNT_SETTINGS_USED = t("Your account's saved settings are in use on this device.");
