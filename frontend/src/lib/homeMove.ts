/**
 * Home on sign-in (v0.7.0 plan, "Home without signing in"): signed out, Home is kept on this device with the
 * rest of My Go (the v0.6.1 patch); signing in afterwards offers to move the device's Home into the account.
 * It is never merged silently: the account's Home stays until the rider says Move, and a No is remembered
 * for that Home, so the question is not asked again on every load.
 */
import { DEVICE_KEY, parseMyGo, type Home } from "./myGo.ts";

/** The device Home a rider answered (Move or Keep) about, so it is asked once. */
export const HOME_OFFER_KEY = "routemaker.home-offer";

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function local(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** This device's Home (signed-out My Go), or null. */
export function deviceHome(store: Store | null = local()): Home | null {
  try {
    const raw = store?.getItem(DEVICE_KEY);
    return raw ? parseMyGo(JSON.parse(raw)).home : null;
  } catch {
    return null;
  }
}

function homeKey(home: Home): string {
  return `${home.point[0].toFixed(5)},${home.point[1].toFixed(5)}|${home.label}`;
}

/** Two Homes at the same spot (to about a metre) with the same label. */
export function sameHome(a: Home | null, b: Home | null): boolean {
  if (!a || !b) return a === b;
  return homeKey(a) === homeKey(b);
}

export interface HomeOffer {
  device: Home;
  account: Home | null;
  question: string;
  move: string;
  keep: string;
}

function named(home: Home): string {
  return home.label.trim() || "the spot you picked";
}

/**
 * The offer to make once the account's My Go is read, or null: none when the device has no Home, when the
 * account already has that same Home, or when the rider answered about this Home before.
 */
export function homeOffer(device: Home | null, account: Home | null, store: Store | null = local()): HomeOffer | null {
  if (!device || sameHome(device, account)) return null;
  try {
    if (store?.getItem(HOME_OFFER_KEY) === homeKey(device)) return null;
  } catch {
    // Unreadable: ask.
  }
  return account
    ? {
        device,
        account,
        question: `This device has a Home (${named(device)}). Replace your account's Home (${named(account)}) with it?`,
        move: "Use this device's Home",
        keep: "Keep my account's Home",
      }
    : {
        device,
        account,
        question: `This device has a Home (${named(device)}). Move it into your account, so it follows you to other devices?`,
        move: "Move Home to my account",
        keep: "Not now",
      };
}

/** Remember the rider's answer about this device Home (either way), so it is not asked again. */
export function answerHomeOffer(device: Home, store: Store | null = local()): void {
  try {
    store?.setItem(HOME_OFFER_KEY, homeKey(device));
  } catch {
    // Asked again next time.
  }
}

export const HOME_MOVED = "Home moved to your account.";
export const HOME_KEPT = "Your account's Home is unchanged.";
