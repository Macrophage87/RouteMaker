/**
 * The rider and bike weight, kept private (OWNER-DECISIONS 313-318).
 *
 * - 313: "Have the rider and bike weight hidden behind a popup. Not everyone wants to
 *   share their weight. But if you're signed in, it will save it." The weight is never
 *   in a link, a download, the panel, the summary or what is announced: only the line
 *   saying whether one is set (weightLine), and the dialog where it is entered.
 * - 314: the line shows the state, never the value, with the date it was set.
 * - 315: kept in a shape ready for named loadouts ({name, totalKg, parts?, setAt});
 *   signed out there is one, named DEFAULT_NAME. The picker is the accounts work's.
 * - 316, 317: the dialog is a worksheet of Rider, Bike and Cargo, or a Total typed
 *   directly; blank parts take the ride type's defaults (defaultSplit). Saved values are
 *   never put back in the fields.
 * - 318: the two lines the dialog leads with (WEIGHT_PURPOSE, WEIGHT_ROUGH).
 *
 * Signed out it is kept in this browser only if the rider ticks "Remember on this
 * device" (localStorage, which may refuse); otherwise it lasts this visit. Signed in it
 * is to be saved to the rider's profile with the accounts work (WeightStore, TODO below).
 * Only the total reaches the API, rounded to whole kilograms (dials.ts dialFields).
 */
import type { Carrying, Dials } from "./dials.ts";
import { PASSENGERS_WEIGHT_KG, SYSTEM_WEIGHT_KG, SYSTEM_WEIGHT_MAX_KG, SYSTEM_WEIGHT_MIN_KG } from "./dials.ts";

export const LB_PER_KG = 2.20462;

/** A weight as kept: the total that feeds the effort model, the parts it was made from (if any), and when it was set. */
export interface StoredWeight {
  name: string;
  totalKg: number;
  parts?: { riderKg: number; bikeKg: number; cargoKg: number };
  /** Set where the total entered was outside the range and the nearer limit is used instead (338). */
  limit?: "min" | "max";
  /** Milliseconds since the epoch. */
  setAt: number;
}

/** The one weight a signed-out rider has (315). */
export const DEFAULT_NAME = "My weight";

/** Where a remembered weight is kept in this browser. */
export const WEIGHT_STORAGE_KEY = "routemaker.weight";

// ---- the ride panel's line (314, 315) ----------------------------------------

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole calendar days from `setAt` to `now`, in local time: 0 is today. */
export function daysSince(setAt: number, now: number = Date.now()): number {
  const day = (t: number) => {
    const d = new Date(t);
    return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY_MS;
  };
  return Math.max(0, Math.round(day(now) - day(setAt)));
}

/** "set today", "set 1 day ago", "set 3 days ago". */
export function setAgo(setAt: number, now: number = Date.now()): string {
  const days = daysSince(setAt, now);
  return days === 0 ? "set today" : `set ${days} ${days === 1 ? "day" : "days"} ago`;
}

/** The ride panel's line: whether a weight is set and when, never its value. The same words for a screen reader. */
export function weightLine(weight: StoredWeight | null, now: number = Date.now()): string {
  if (!weight) return "Rider and bike weight: not set, defaults used";
  if (weight.name && weight.name !== DEFAULT_NAME) return `Rider and bike: ${weight.name}, ${setAgo(weight.setAt, now)}`;
  return `Rider and bike weight: ${setAgo(weight.setAt, now)}`;
}

// ---- the dialog's words (317, 318) -------------------------------------------

export const WEIGHT_DIALOG_TITLE = "Rider and bike weight";
export const WEIGHT_PURPOSE =
  "Optional. Used only to work out your route, for how hard hills feel. It is never displayed, and never put in shared links or downloads.";
export const WEIGHT_ROUGH = "A rough estimate is fine. Within 20 lb (10 kg) or so makes no real difference.";

/** What the dialog says when a weight is saved: the date, never the numbers (317(b)). */
export function savedNotice(weight: StoredWeight, now: number = Date.now()): string {
  const limit = weight.limit ? ` ${limitNote(weight.limit)}` : "";
  return `A weight is saved (${setAgo(weight.setAt, now)}).${limit} Enter new values to replace it, or Clear to use the defaults.`;
}

// ---- the worksheet (316, 317) ------------------------------------------------

export interface Split {
  riderKg: number;
  bikeKg: number;
  cargoKg: number;
}

/**
 * The parts a blank field stands for, by what the bike carries: they sum to the ride
 * type's default total (dials.ts SYSTEM_WEIGHT_KG, PASSENGERS_WEIGHT_KG). A typical
 * rider 75 kg (165 lb) and bike 15 kg (33 lb) with no cargo; Cargo with passengers a
 * 30 kg (66 lb) cargo bike and 15 kg (33 lb) of passengers.
 */
export function defaultSplit(carrying: Carrying | null): Split {
  return carrying === "people" ? { riderKg: 75, bikeKg: 30, cargoKg: PASSENGERS_WEIGHT_KG - 105 } : { riderKg: 75, bikeKg: SYSTEM_WEIGHT_KG - 75, cargoKg: 0 };
}

/** What the rider has typed, in pounds; `mode` says whether the Total was typed or is the parts' sum. */
export interface Worksheet {
  rider: string;
  bike: string;
  cargo: string;
  total: string;
  mode: "parts" | "total";
}

/** Every open starts here: nothing filled in (317(b)). */
export const BLANK: Worksheet = { rider: "", bike: "", cargo: "", total: "", mode: "parts" };

/** Pounds typed as kilograms to a tenth; undefined for blank, null for an entry that is not a number. */
export function poundsToKg(text: string): number | undefined | null {
  const trimmed = text.trim().replace(/\s*(lb|lbs|pounds)$/i, "");
  if (trimmed === "") return undefined;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  return Math.round((Number(trimmed) / LB_PER_KG) * 10) / 10;
}

/** Kilograms as whole pounds, as the fields show them. */
export const lbOf = (kg: number): number => Math.round(kg * LB_PER_KG);

/** "165 lb (75 kg)". */
export const formatLbKg = (kg: number): string => `${lbOf(kg)} lb (${Math.round(kg)} kg)`;

/** A part typed: the parts are what count again, and the Total is their sum (317(a)). */
export function editPart(sheet: Worksheet, part: "rider" | "bike" | "cargo", text: string, split: Split): Worksheet {
  const next: Worksheet = { ...sheet, [part]: text, mode: "parts" };
  const total = worksheetKg(next, split);
  return { ...next, total: typeof total === "number" ? String(lbOf(total)) : "" };
}

/** The Total typed: it replaces the parts (317(a)). */
export function editTotal(text: string): Worksheet {
  return { ...BLANK, total: text, mode: "total" };
}

/** The worksheet's parts in kilograms, blanks at their defaults; null where one is not a number. */
export function partsKg(sheet: Worksheet, split: Split): Split | null {
  const rider = poundsToKg(sheet.rider);
  const bike = poundsToKg(sheet.bike);
  const cargo = poundsToKg(sheet.cargo);
  if (rider === null || bike === null || cargo === null) return null;
  return { riderKg: rider ?? split.riderKg, bikeKg: bike ?? split.bikeKg, cargoKg: cargo ?? split.cargoKg };
}

/** The total the worksheet comes to (kg, to a tenth); undefined with nothing entered, null for an entry that is not a number. */
export function worksheetKg(sheet: Worksheet, split: Split): number | undefined | null {
  if (sheet.mode === "total") return poundsToKg(sheet.total);
  if (!sheet.rider.trim() && !sheet.bike.trim() && !sheet.cargo.trim()) return undefined;
  const parts = partsKg(sheet, split);
  if (!parts) return null;
  return Math.round((parts.riderKg + parts.bikeKg + parts.cargoKg) * 10) / 10;
}

export const WEIGHT_NOTHING = "Enter your weight in at least one field, or Cancel.";
export const WEIGHT_NOT_A_NUMBER = "Enter numbers only, in pounds, or Cancel.";

/** "55 lb (25 kg)" and "990 lb (450 kg)": the limits as the dialog says them. */
const LIMIT_WORDS = { min: `${lbOf(SYSTEM_WEIGHT_MIN_KG)} lb (${SYSTEM_WEIGHT_MIN_KG} kg)`, max: `${lbOf(SYSTEM_WEIGHT_MAX_KG)} lb (${SYSTEM_WEIGHT_MAX_KG} kg)` };

/**
 * What the dialog says when a total is outside the range (OWNER-DECISIONS 338), neutrally,
 * with the limit planned with and never the number typed.
 */
export function limitNote(limit: "min" | "max"): string {
  return (
    `Routing is designed for totals between ${lbOf(SYSTEM_WEIGHT_MIN_KG)} and ${lbOf(SYSTEM_WEIGHT_MAX_KG)} lb (${SYSTEM_WEIGHT_MIN_KG} and ${SYSTEM_WEIGHT_MAX_KG} kg), ` +
    `so we'll plan with ${LIMIT_WORDS[limit]}.`
  );
}

/**
 * What Save keeps, or the words for why it cannot (nothing entered, or not a number).
 * A total outside the range is kept as the nearer limit, with `limit` saying which, and
 * without its parts, which no longer make it (OWNER-DECISIONS 337, 338); the parts are
 * kept only when they made the total.
 */
export function toStored(sheet: Worksheet, split: Split, now: number = Date.now(), name: string = DEFAULT_NAME): StoredWeight | { refused: string } {
  const total = worksheetKg(sheet, split);
  if (total === undefined) return { refused: WEIGHT_NOTHING };
  if (total === null) return { refused: WEIGHT_NOT_A_NUMBER };
  if (total < SYSTEM_WEIGHT_MIN_KG) return { name, totalKg: SYSTEM_WEIGHT_MIN_KG, limit: "min", setAt: now };
  if (total > SYSTEM_WEIGHT_MAX_KG) return { name, totalKg: SYSTEM_WEIGHT_MAX_KG, limit: "max", setAt: now };
  if (sheet.mode === "total") return { name, totalKg: total, setAt: now };
  return { name, totalKg: total, parts: partsKg(sheet, split)!, setAt: now };
}

// ---- keeping it ----------------------------------------------------------------

/** A stored value as this page now keeps it, from any shape an earlier version wrote: null if unusable. */
export function migrate(value: unknown, now: number = Date.now()): StoredWeight | null {
  let raw = value;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  const usable = (kg: unknown): kg is number => typeof kg === "number" && Number.isFinite(kg) && kg >= SYSTEM_WEIGHT_MIN_KG && kg <= SYSTEM_WEIGHT_MAX_KG;
  // The old single figure: kilograms, as the link's sysweight was.
  if (usable(raw)) return { name: DEFAULT_NAME, totalKg: Math.round(raw * 10) / 10, setAt: now };
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const total = r.totalKg ?? r.kg ?? r.systemWeightKg;
  if (!usable(total)) return null;
  const setAt = typeof r.setAt === "number" && Number.isFinite(r.setAt) ? r.setAt : typeof r.setAt === "string" && Number.isFinite(Date.parse(r.setAt)) ? Date.parse(r.setAt) : now;
  const p = r.parts as Record<string, unknown> | undefined;
  const parts =
    p && [p.riderKg, p.bikeKg, p.cargoKg].every((x) => typeof x === "number" && Number.isFinite(x) && x >= 0)
      ? { riderKg: p.riderKg as number, bikeKg: p.bikeKg as number, cargoKg: p.cargoKg as number }
      : undefined;
  const limit = r.limit === "min" || r.limit === "max" ? r.limit : undefined;
  return { name: typeof r.name === "string" && r.name.trim() ? r.name : DEFAULT_NAME, totalKg: Math.round(total * 10) / 10, ...(parts ? { parts } : {}), ...(limit ? { limit } : {}), setAt };
}

type Storage = Pick<globalThis.Storage, "getItem" | "setItem" | "removeItem">;

function browserStorage(): Storage | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/**
 * Where the weight is kept. Signed out: this browser, if the rider asked (`remember`),
 * else this visit only. TODO (accounts work, OWNER-DECISIONS 313, 315): signed in, load
 * and save it, and its named loadouts, with the rider's profile, with a way to delete
 * it there; nothing here sends it anywhere yet.
 */
export class WeightStore {
  private visit: StoredWeight | null = null;
  private readonly storage: Storage | null;
  constructor(storage: Storage | null = browserStorage()) {
    this.storage = storage;
  }

  /** What is kept: this visit's, else this browser's (migrated from an earlier shape). */
  load(now: number = Date.now()): StoredWeight | null {
    if (this.visit) return this.visit;
    try {
      const raw = this.storage?.getItem(WEIGHT_STORAGE_KEY);
      return raw == null ? null : migrate(raw, now);
    } catch {
      return null;
    }
  }

  /** Whether this browser keeps one. */
  remembered(): boolean {
    try {
      return this.storage?.getItem(WEIGHT_STORAGE_KEY) != null;
    } catch {
      return false;
    }
  }

  /** Keep it: in this browser with `remember` (false when storage refused), else for this visit and not in the browser. */
  save(weight: StoredWeight, remember: boolean): boolean {
    this.visit = weight;
    try {
      if (remember) {
        this.storage?.setItem(WEIGHT_STORAGE_KEY, JSON.stringify(weight));
        return this.storage != null;
      }
      this.storage?.removeItem(WEIGHT_STORAGE_KEY);
    } catch {
      return false;
    }
    return true;
  }

  /** Forget it everywhere: the defaults are used. */
  clear(): void {
    this.visit = null;
    try {
      this.storage?.removeItem(WEIGHT_STORAGE_KEY);
    } catch {
      // Nothing kept that can be reached.
    }
  }
}

/** The dials a plan is sent with: the weight's total added, or none (the ride type's default). Never in the link. */
export function withWeight(dials: Dials, weight: StoredWeight | null): Dials {
  const { systemWeightKg: _ignored, ...rest } = dials;
  return weight ? { ...rest, systemWeightKg: weight.totalKg } : rest;
}
