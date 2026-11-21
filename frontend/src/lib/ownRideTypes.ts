/**
 * The rider's own ride types (the owner, 2026-11-21: "Let people save and name their own configuration dials"; "save as
 * my own ride type is a good option"): a ride type and its sliders as the Ride settings popup holds them, under a name
 * the rider gives. Listed first, under "My ride types", wherever a ride type is picked (Plan's dialog, Go's Ride sheet);
 * picking one sets its ride type and every slider.
 *
 * And Go's default (the owner, 2026-11-21: "make a button in the ride type list that will make it the default for go";
 * Settings' Primary Go method "is not in an intuitive spot"): a button on each card. A built-in ride type is My Go's
 * ride (lib/myGo.ts) as before; one of the rider's own is My Go's ride set to its base type, and `goOwn` names it, so
 * Go starts on its sliders too.
 *
 * Kept on this device (localStorage) and, signed in, in the account's saved settings ("own" and "goOwn",
 * lib/accountSettings.ts), as the favorites are. One small store with listeners, so both pickers see the same list.
 */
import { useSyncExternalStore } from "react";
import { decodePlan, encodePlan } from "./planHash.ts";
import { TRIP_DIALS, startDials as startDialsFor, type Dials } from "./dials.ts";
import { presetLabel, resolvePreset, type PresetId } from "./presets.ts";

export const OWN_KEY = "routemaker.own-ride-types";
export const GO_OWN_KEY = "routemaker.go-own-ride-type";
/** At most this many (the account's check, src/core/accounts.py OWN_MAX). */
export const OWN_MAX = 20;
export const OWN_NAME_MAX = 40;

export interface OwnRideType {
  /** Never shown: tells two of the same name apart while one replaces the other. */
  id: string;
  name: string;
  /** The ride type and sliders as a plan link's fragment with no points (accountSettings.ts planSetting's form). */
  plan: string;
}

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem?(key: string): void;
}

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The ride type and sliders as kept: the trip's own dials (a target distance, a loop) left out. */
export function ownPlan(preset: PresetId, dials: Dials): string {
  const kept: Dials = { ...dials };
  for (const key of TRIP_DIALS) delete kept[key];
  return encodePlan([], preset, kept);
}

/** The ride type and sliders one holds. */
export function ownSetup(own: OwnRideType): { preset: PresetId; dials: Dials } {
  const decoded = decodePlan(own.plan);
  return { preset: decoded.preset, dials: decoded.dials };
}

/** A name as kept: spaces folded, at most OWN_NAME_MAX characters. */
export function ownName(name: string): string {
  return name.replace(/\s+/g, " ").trim().slice(0, OWN_NAME_MAX);
}

const sameName = (a: string, b: string) => a.toLocaleLowerCase() === b.toLocaleLowerCase();

/** The parts of a stored or answered list that make sense, each name once; anything else is left out. */
export function parseOwn(raw: unknown): OwnRideType[] {
  if (!Array.isArray(raw)) return [];
  const out: OwnRideType[] = [];
  for (const value of raw) {
    if (!value || typeof value !== "object") continue;
    const v = value as Record<string, unknown>;
    if (typeof v.id !== "string" || !/^[a-z0-9]{1,16}$/.test(v.id)) continue;
    if (typeof v.name !== "string" || typeof v.plan !== "string") continue;
    const name = ownName(v.name);
    if (!name || !/[#&]preset=/.test(v.plan) || /(^|[#&])(p|q|via|line|sn|nt)=/.test(v.plan) || v.plan.length > 2048) continue;
    if (out.some((o) => o.id === v.id || sameName(o.name, name))) continue;
    out.push({ id: v.id, name, plan: v.plan });
    if (out.length >= OWN_MAX) break;
  }
  return out;
}

export function readOwn(store: Store | null = local()): OwnRideType[] {
  try {
    const raw = store?.getItem(OWN_KEY);
    return raw ? parseOwn(JSON.parse(raw)) : [];
  } catch {
    return [];
  }
}

export function readGoOwn(store: Store | null = local()): string | null {
  try {
    const raw = store?.getItem(GO_OWN_KEY);
    return raw && /^[a-z0-9]{1,16}$/.test(raw) ? raw : null;
  } catch {
    return null;
  }
}

const newId = () => Math.random().toString(36).slice(2, 10) || "own";

/**
 * The list with this setup saved under `name`: one of the same name (any case) is replaced in its place, else it is
 * added first. Past OWN_MAX the oldest (last) goes.
 */
export function withSaved(list: readonly OwnRideType[], name: string, preset: PresetId, dials: Dials, id: string = newId()): OwnRideType[] {
  const kept = ownName(name);
  if (!kept) return [...list];
  const plan = ownPlan(preset, dials);
  const at = list.findIndex((o) => sameName(o.name, kept));
  if (at >= 0) return list.map((o, i) => (i === at ? { id: o.id, name: kept, plan } : o));
  return [{ id, name: kept, plan }, ...list].slice(0, OWN_MAX);
}

/** The one of the rider's own that this ride type and sliders are, if any. */
export function matchingOwn(list: readonly OwnRideType[], preset: PresetId, dials: Dials): OwnRideType | null {
  const plan = ownPlan(preset, dials);
  return list.find((o) => o.plan === plan) ?? null;
}

let current: OwnRideType[] | null = null;
let goOwn: string | null | undefined;
const listeners = new Set<() => void>();
let snap: { list: OwnRideType[]; goOwn: string | null } | null = null;

function snapshot(): { list: OwnRideType[]; goOwn: string | null } {
  if (current === null) current = readOwn();
  if (goOwn === undefined) goOwn = readGoOwn();
  const go = goOwn && current.some((o) => o.id === goOwn) ? goOwn : null;
  if (!snap || snap.list !== current || snap.goOwn !== go) snap = { list: current, goOwn: go };
  return snap;
}

function tell(): void {
  for (const listener of listeners) listener();
}

function write(store: Store | null, key: string, value: string | null): void {
  try {
    if (value === null) store?.removeItem?.(key);
    else store?.setItem(key, value);
  } catch {
    // Not kept: it still applies to this visit.
  }
}

/** Keep a new list on this device and tell every picker. */
export function setOwn(list: readonly OwnRideType[], store: Store | null = local()): void {
  current = parseOwn(list);
  write(store, OWN_KEY, JSON.stringify(current));
  tell();
}

/** Which of the rider's own Go starts on, or null for none (a built-in ride type, My Go's ride). */
export function setGoOwn(id: string | null, store: Store | null = local()): void {
  goOwn = id;
  write(store, GO_OWN_KEY, id);
  tell();
}

/** Whether saving under this name needs a place the list does not have (OWN_MAX kept, none of that name). */
export function ownFull(list: readonly OwnRideType[], name: string): boolean {
  const kept = ownName(name);
  return list.length >= OWN_MAX && !list.some((o) => sameName(o.name, kept));
}

/**
 * Save this setup under a name (one of the same name replaced); returns the one kept, or null where the list is full
 * (release review of #1385: never a silent loss of the oldest).
 */
export function saveOwn(name: string, preset: PresetId, dials: Dials): OwnRideType | null {
  if (ownFull(snapshot().list, name)) return null;
  const list = withSaved(snapshot().list, name, preset, dials);
  removed = null;
  setOwn(list);
  return list.find((o) => sameName(o.name, ownName(name))) ?? null;
}

/** The one last removed and where it was, for Undo (release review of #1385). */
let removed: { own: OwnRideType; at: number } | null = null;

export function removeOwn(id: string): void {
  const list = snapshot().list;
  const at = list.findIndex((o) => o.id === id);
  if (at < 0) return;
  removed = { own: list[at], at };
  setOwn(list.filter((o) => o.id !== id));
}

/** Put the one last removed back where it was. */
export function undoRemoveOwn(): void {
  if (!removed) return;
  const list = [...snapshot().list];
  const back = removed;
  removed = null;
  if (list.length >= OWN_MAX || list.some((o) => o.id === back.own.id || sameName(o.name, back.own.name))) return tell();
  list.splice(Math.min(back.at, list.length), 0, back.own);
  setOwn(list);
}

const removedNow = () => removed;
/** Undo is for now only: it goes when the list it was offered in closes (release review). */
export function forgetRemovedOwn(): void {
  if (removed === null) return;
  removed = null;
  tell();
}
/** The one last removed, while Undo can bring it back. */
export function useRemovedOwn(): { own: OwnRideType; at: number } | null {
  return useSyncExternalStore(subscribe, removedNow, () => null);
}

/**
 * A name for settings loaded from someone else that does not replace one of the rider's own of the same name
 * (review of #1385): "Commute (2)". The same setup under the same name is the same one.
 */
export function freeName(list: readonly OwnRideType[], name: string, preset: PresetId, dials: Dials): string {
  const plan = ownPlan(preset, dials);
  const taken = (n: string) => list.some((o) => sameName(o.name, n) && o.plan !== plan);
  if (!taken(name)) return name;
  for (let i = 2; i < 100; i++) {
    const next = ownName(`${name.slice(0, OWN_NAME_MAX - 5)} (${i})`);
    if (!taken(next)) return next;
  }
  return name;
}

/** Read the device's again (after the account's settings are put on the device). */
export function reloadOwn(): void {
  removed = null;
  current = readOwn();
  goOwn = readGoOwn();
  tell();
}

const onStorage = (event: StorageEvent) => {
  if (event.key === OWN_KEY || event.key === GO_OWN_KEY) reloadOwn();
};

const subscribe = (listener: () => void) => {
  if (listeners.size === 0 && typeof window !== "undefined") window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
};

const EMPTY = { list: [] as OwnRideType[], goOwn: null };

/** The rider's own ride types and which one Go starts on, kept current. */
export function useOwnRideTypes(): { list: OwnRideType[]; goOwn: string | null } {
  return useSyncExternalStore(subscribe, snapshot, () => EMPTY);
}

/**
 * "Create custom" (the owner, 2026-11-21: 'have a "create custom" for ride settings'), from the ride type list: the
 * Ride settings popup opens with its name box ready. Each press counts one; the popup and its Save watch the count.
 */
let creates = 0;
const createListeners = new Set<() => void>();
export function requestCreate(): void {
  creates += 1;
  for (const listener of createListeners) listener();
}
const subscribeCreates = (listener: () => void) => {
  createListeners.add(listener);
  return () => createListeners.delete(listener);
};
export function useCreateRequests(): number {
  return useSyncExternalStore(subscribeCreates, () => creates, () => 0);
}

/** This device's, read once (Go's first ride type, before React). */
export function ownNow(): { list: OwnRideType[]; goOwn: string | null } {
  return snapshot();
}

/**
 * Ride settings to send to someone else (the owner, 2026-11-21: "have a share and load mechanism to send between
 * people, like via JSON"): the name, the ride type and its sliders as plain JSON, nothing else (no places, no route).
 */
export const SHARE_KIND = "routemaker-ride-settings";

export function shareJson(name: string, preset: PresetId, dials: Dials): string {
  const settings: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(decodePlan(ownPlan(preset, dials)).dials)) {
    if (value !== undefined && value !== null) settings[key] = value;
  }
  return JSON.stringify({ kind: SHARE_KIND, version: 1, name: ownName(name) || presetLabel(preset), rideType: preset, settings }, null, 2);
}

/**
 * Settings pasted in: the ride type and sliders as a plan link reads them (lib/planHash.ts decodePlan, which keeps only
 * values a link may hold), or null where the text is not ride settings.
 */
export function readShareJson(text: string): { name: string; preset: PresetId; dials: Dials } | null {
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return null;
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const b = body as Record<string, unknown>;
  if (b.kind !== SHARE_KIND) return null;
  const preset = resolvePreset(b.rideType);
  if (!preset) return null;
  const settings = b.settings && typeof b.settings === "object" && !Array.isArray(b.settings) ? (b.settings as Partial<Dials>) : {};
  try {
    // A link's checks, without a trip's own dials (a target distance, a loop): only the ride's settings come in.
    const decoded = decodePlan(ownPlan(preset, { ...startDialsFor(preset), ...settings } as Dials));
    if (decoded.preset !== preset) return null;
    const name = typeof b.name === "string" ? ownName(b.name) : "";
    return { name: name || presetLabel(preset), preset, dials: decoded.dials };
  } catch {
    return null;
  }
}
