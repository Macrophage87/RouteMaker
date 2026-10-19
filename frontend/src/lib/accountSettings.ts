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
 *   link, a log or an AI assistant's answer, and erased with the rest by Delete account. Cleared on the
 *   device, it is cleared from the account with the next save.
 * - On sign-in (every signed-in load): an empty account takes this device's settings; an account that has
 *   settings wins, and its settings replace the device's. Nothing is merged silently.
 * - Signed out, everything stays on the device as before.
 */
import { FAVORITES_KEY, parseFavorites } from "./favoriteRides.ts";
import { CLIMBS_FROM_KEY, CLIMBS_KEY, CLIMB_CATEGORIES, type ClimbCategory } from "./climbs.ts";
import type { Dials } from "./dials.ts";
import { LAYER_SECTIONS_KEY } from "./layerSection.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import type { PresetId } from "./presets.ts";
import { csrfFromCookie } from "./stressEditor.ts";
import { TOPO_STORAGE_KEY } from "./topoLines.ts";
import { WEIGHT_STORAGE_KEY, migrate as weightOf, type StoredWeight } from "./weight.ts";
import { WATER_PREFS_KEY, type WaterPrefs } from "./waterRestrooms.ts";

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
  /** The rider and bike weight, as this device keeps it (lib/weight.ts StoredWeight). */
  weight?: StoredWeight;
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
const TRIP_DIALS: readonly (keyof Dials)[] = ["pickupStation", "dropoffStation", "transitOption", "targetDistanceM", "systemWeightKg", "loop"];

/** The ride type and dials as a settings value: no points, nothing that belongs to one trip, never the weight. */
export function planSetting(preset: PresetId, dials: Dials): string {
  const kept: Dials = { ...dials };
  for (const key of TRIP_DIALS) delete kept[key];
  return encodePlan([], preset, kept);
}

/** The ride type and dials a settings value holds, or null when it holds none. */
export function planFromSetting(plan: string | undefined): { preset: PresetId; dials: Dials } | null {
  if (typeof plan !== "string" || !/[#&]preset=/.test(plan) || /[#&]p=/.test(plan)) return null;
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
  const weight = body.weight === undefined ? null : weightOf(body.weight);
  if (weight) doc.weight = weight;
  return doc;
}

/** Whether a document holds any setting at all (an empty account holds none). */
export function hasSettings(doc: SettingsDoc | null): boolean {
  return doc !== null && Object.keys(doc).some((key) => key !== "v");
}

/** This device's settings as a document: what it keeps, and the ride type and dials in use. */
export function deviceSettings(plan: { preset: PresetId; dials: Dials } | null, store: Store | null = local()): SettingsDoc {
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
  const weightRaw = read(store, WEIGHT_STORAGE_KEY);
  const weight = weightRaw === null ? null : weightOf(weightRaw);
  if (weight) doc.weight = weight;
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
  if (doc.weight) write(WEIGHT_STORAGE_KEY, JSON.stringify(doc.weight));
}

export type SignInStep = { kind: "push-device"; doc: SettingsDoc } | { kind: "use-account"; doc: SettingsDoc };

/**
 * What a signed-in load does with the two: an account with no settings takes this device's; an account
 * with settings wins (the plan's default: "account settings win over device on sign-in"), and nothing merges.
 */
export function onSignIn(account: SettingsDoc | null, device: SettingsDoc): SignInStep {
  return hasSettings(account) ? { kind: "use-account", doc: account as SettingsDoc } : { kind: "push-device", doc: device };
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

/** The Settings sheet's one line for a rider who can sign in (the plan, item 4). */
export const SIGN_IN_LINE = "Sign in with Discord to save routes and sync settings across devices.";
/** Said once the account's settings are in use on this device. */
export const ACCOUNT_SETTINGS_USED = "Your account's saved settings are in use on this device.";
