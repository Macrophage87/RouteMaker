/**
 * My Go (UI-CLEANUP, the owner's choice 2 of 2026-10-11): a rider's own default "go" — the view the
 * app opens in (Go or Plan, or by screen size), the ride type Go uses, and the Home the Go sheet's
 * Home chip rides to.
 *
 * Signed in it is saved to the Discord account (GET and POST /api/me/go; core.models.MyGo), so it
 * follows the rider to another phone. Signed out it stays on this device (localStorage), Home included
 * (Stephen 2026-10-13: Home without signing in; nothing is sent to the server). Signing in uses the
 * account's Home; the device's is kept for when the rider signs out, never merged silently.
 *
 * The account's copy is kept on the device as well (without Home), so the next visit opens in the
 * right view at once rather than after the network answers; a sign-out clears that copy.
 */
import { isOpenIn, type OpenIn } from "./appMode.ts";
import type { LonLat } from "./geo.ts";
import { isPreset, presetSaid, type PresetId } from "./presets.ts";
import { csrfFromCookie } from "./stressEditor.ts";

export interface Home {
  point: LonLat;
  label: string;
}

export interface MyGo {
  openIn: OpenIn;
  /** The ride type Go uses; null is Default. */
  ride: PresetId | null;
  /** Signed in only. */
  home: Home | null;
}

export const NO_MY_GO: MyGo = { openIn: "", ride: null, home: null };

/** This device's My Go, signed out. */
export const DEVICE_KEY = "routemaker.my-go";
/** The account's My Go as last read, without Home, signed in. */
export const ACCOUNT_COPY_KEY = "routemaker.my-go.account";

/**
 * Go's quick ride types (the owner, 2026-10-12, replacing choice 10's Default, Cargo and Bikeshare):
 * first the rider's own ride type, "Default (user sets)", which is My Go's ride (Default until the
 * rider sets one in Settings), then the two transit ride types. Cargo Bike, Bikeshare and the rest
 * are under More. `GO_FIXED` is the list to edit to change which types follow the rider's own.
 */
export const GO_FIXED: readonly PresetId[] = ["bike-transit", "bikeshare-transit"];

/** The default chips, before a My Go ride is set. */
export const GO_RIDES: readonly PresetId[] = ["default", ...GO_FIXED];

/** The rider's own ride type first, then the fixed ones; where the rider's own is one of them, Default fills its place. */
export function goRideChips(myRide: PresetId | null): PresetId[] {
  const own = myRide ?? "default";
  const rest = GO_FIXED.filter((id) => id !== own);
  return rest.length === GO_FIXED.length ? [own, ...rest] : [own, ...rest, "default"];
}

/** The first chip's description: it is the rider's own, set in Settings. */
export const OWN_RIDE_HINT = "Your ride type. Change it in Settings, under My Go.";

/** My Go in a few words, the Settings row's value: "Go · Default", "By screen size · Cargo Bike". */
export function myGoSummary(myGo: MyGo): string {
  const where = myGo.openIn === "go" ? "Go" : myGo.openIn === "plan" ? "Plan" : "By screen size";
  return `${where} · ${presetSaid(myGo.ride ?? "default")}`;
}

/** The parts of a stored or answered My Go that make sense; anything else is left at its default. */
export function parseMyGo(raw: unknown): MyGo {
  if (!raw || typeof raw !== "object") return NO_MY_GO;
  const body = raw as { open_in?: unknown; ride?: unknown; home?: unknown };
  const openIn = isOpenIn(body.open_in) ? body.open_in : "";
  const ride = isPreset(body.ride) ? body.ride : null;
  let home: Home | null = null;
  const h = body.home as { lon?: unknown; lat?: unknown; label?: unknown } | null | undefined;
  if (h && typeof h.lon === "number" && typeof h.lat === "number" && Number.isFinite(h.lon) && Number.isFinite(h.lat)) {
    home = { point: [h.lon, h.lat], label: typeof h.label === "string" ? h.label : "" };
  }
  return { openIn, ride, home };
}

/** The body POST /api/me/go takes: the whole of My Go. */
export function myGoBody(myGo: MyGo): { open_in: OpenIn; ride: string; home: { lon: number; lat: number; label: string } | null } {
  return {
    open_in: myGo.openIn,
    ride: myGo.ride && myGo.ride !== "default" ? myGo.ride : "",
    home: myGo.home ? { lon: myGo.home.point[0], lat: myGo.home.point[1], label: myGo.home.label.slice(0, 120) } : null,
  };
}

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function local(): Store | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The My Go to start with, before the account answers: the account's copy if there is one, else the device's. */
export function readStartMyGo(store: Store | null = local()): { myGo: MyGo; account: boolean } {
  try {
    const copy = store?.getItem(ACCOUNT_COPY_KEY);
    if (copy) return { myGo: { ...parseMyGo(JSON.parse(copy)), home: null }, account: true };
    const device = store?.getItem(DEVICE_KEY);
    if (device) return { myGo: parseMyGo(JSON.parse(device)), account: false };
  } catch {
    // A refused or broken store: the defaults.
  }
  return { myGo: NO_MY_GO, account: false };
}

/** Keep this device's My Go (signed out), Home included. */
export function saveDeviceMyGo(myGo: MyGo, store: Store | null = local()): void {
  try {
    store?.setItem(DEVICE_KEY, JSON.stringify(myGoBody(myGo)));
  } catch {
    // Not kept: it still applies to this visit.
  }
}

/** Keep (or with null, clear) the device's copy of the account's My Go, without Home. */
export function saveAccountCopy(myGo: MyGo | null, store: Store | null = local()): void {
  try {
    if (myGo === null) store?.removeItem(ACCOUNT_COPY_KEY);
    else store?.setItem(ACCOUNT_COPY_KEY, JSON.stringify({ ...myGoBody(myGo), home: null }));
  } catch {
    // Not kept.
  }
}

type Fetch = typeof fetch;

/** GET /api/me/go: the account's My Go, or null when signed out or unreadable. */
export async function fetchMyGo(origin: string, get: Fetch = fetch): Promise<MyGo | null> {
  try {
    const response = await get(`${origin}/api/me/go`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return null;
    return parseMyGo(await response.json());
  } catch {
    return null;
  }
}

export const MY_GO_SAVED = "My Go saved to your account.";
export const MY_GO_SAVED_DEVICE = "My Go saved on this device.";
export const MY_GO_NOT_SAVED = "My Go was not saved to your account; try again shortly. It still applies here.";

/** POST /api/me/go: the whole of My Go. Answers the saved My Go, or null if it was not saved. */
export async function saveMyGo(origin: string, myGo: MyGo, post: Fetch = fetch, cookie = typeof document === "undefined" ? "" : document.cookie): Promise<MyGo | null> {
  try {
    const token = csrfFromCookie(cookie);
    const response = await post(`${origin}/api/me/go`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(token ? { "X-CSRFToken": token } : {}) },
      body: JSON.stringify(myGoBody(myGo)),
    });
    if (!response.ok) return null;
    return parseMyGo(await response.json());
  } catch {
    return null;
  }
}

/** The Home chip's words when there is no Home yet. */
export const HOME_NOT_SET = "No Home yet: set it in My Go.";
