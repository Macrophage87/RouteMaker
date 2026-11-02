/*
 * The page's colour theme. By default it follows the sun: dark from sunset to sunrise, light by day, in DC (the
 * covered region is one place for this). The owner, 2026-11-01: "Set the default color mode to adjust by time of day"
 * and "do sunrise/sunset"; a dark page at night also saves screen power on OLED phones (battery audit). Then, asked
 * "There's the ability to use whatever setting you want still?", a choice in Settings > Display > Colors: the sun,
 * the phone's own setting, or always light or always dark. The class on the root carries it (styles.css
 * `:root.theme-dark`, and the post page's own CSS, core/route_posts.py), and the event tells the map (useMapFlavour.ts).
 *
 * Kept light: main.tsx runs it before the first render, so it reads the sun from lib/lightTimes.ts, not from
 * mapFlavour.ts and the base map's styles.
 */
import { isDark, nextLightChange } from "./lightTimes.ts";
import { COVERAGE_CENTRE } from "./plusCode.ts";
import { browserStore, type KeyValueStore } from "./accessMode.ts";

export const THEME_DARK_CLASS = "theme-dark";
/** Set when the page is decided light: the post page's own CSS falls back to the phone's theme until one is set. */
export const THEME_LIGHT_CLASS = "theme-light";
/** Sent on window when the theme turns. */
export const THEME_EVENT = "routemaker-theme";
/** The browser bar's colour in each theme (index.html's theme-color, the panels' --bg). */
export const THEME_BAR = { light: "#ffffff", dark: "#1b1e24" } as const;
/** Where the rider's choice is kept on this device. */
export const THEME_KEY = "routemaker.theme";
/** The phone's own theme, for "Phone's setting". */
export const PHONE_DARK = "(prefers-color-scheme: dark)";

/** Settings > Display > Colors, in the picker's order; "sun" is the default (the owner, 2026-11-01). */
export const THEME_CHOICES = ["sun", "phone", "light", "dark"] as const;
export type ThemeChoice = (typeof THEME_CHOICES)[number];

/** Whether the sun is down at `ms`: from sunset to sunrise at the region's centre. */
export function sunDownAt(ms: number): boolean {
  return isDark(ms, COVERAGE_CENTRE[1], COVERAGE_CENTRE[0]);
}

/** The next sunrise or sunset at the region's centre after `ms`; null if none within two days. */
export function nextSunTurn(ms: number): number | null {
  return nextLightChange(ms, COVERAGE_CENTRE[1], COVERAGE_CENTRE[0]);
}

/** The kept choice; the sun when nothing is kept, storage refuses, or it holds something else. */
export function readThemeChoice(store: KeyValueStore | null = browserStore()): ThemeChoice {
  try {
    const kept = store?.getItem(THEME_KEY);
    return (THEME_CHOICES as readonly string[]).includes(kept ?? "") ? (kept as ThemeChoice) : "sun";
  } catch {
    return "sun";
  }
}

/** Keep the choice on this device; false when storage refused (it then lasts this visit). */
export function writeThemeChoice(choice: ThemeChoice, store: KeyValueStore | null = browserStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(THEME_KEY, choice);
    return true;
  } catch {
    return false;
  }
}

/** Whether the page is dark under `choice` at `ms`, the phone's own theme being `phoneDark`. */
export function themeDarkFor(choice: ThemeChoice, ms: number, phoneDark: boolean): boolean {
  if (choice === "light") return false;
  if (choice === "dark") return true;
  if (choice === "phone") return phoneDark;
  return sunDownAt(ms);
}

/**
 * How long to wait before looking again: following the sun, until a second past the next sunrise or sunset, at most
 * an hour; any other choice has no clock to wait for (null).
 */
export function themeWait(choice: ThemeChoice, ms: number): number | null {
  if (choice !== "sun") return null;
  const next = nextSunTurn(ms);
  return next === null ? 60 * 60_000 : Math.min(60 * 60_000, Math.max(1000, next - ms + 1000));
}

/** Whether the page shows the dark theme now (the class, set by followTheme). */
export function themeIsDark(root: { classList: { contains(name: string): boolean } } | null = typeof document === "undefined" ? null : document.documentElement): boolean {
  return root?.classList.contains(THEME_DARK_CLASS) ?? false;
}

interface Page {
  documentElement: { classList: { contains(name: string): boolean; toggle(name: string, on: boolean): unknown } };
  querySelectorAll(selector: string): ArrayLike<{ setAttribute(name: string, value: string): void; removeAttribute(name: string): void }>;
  visibilityState?: string;
  addEventListener(type: "visibilitychange", listener: () => void): void;
}

/** The phone's theme as matchMedia gives it; null where there is none. */
interface PhoneTheme {
  matches: boolean;
  addEventListener?(type: "change", listener: () => void): void;
}

/** Set the page dark or light: its class and the browser bar's colour. True when it changed. */
export function applyTheme(page: Page, dark: boolean): boolean {
  const root = page.documentElement.classList;
  const was = root.contains(THEME_DARK_CLASS);
  root.toggle(THEME_DARK_CLASS, dark);
  root.toggle(THEME_LIGHT_CLASS, !dark);
  const bars = page.querySelectorAll('meta[name="theme-color"]');
  for (let i = 0; i < bars.length; i += 1) {
    bars[i].removeAttribute("media");
    bars[i].setAttribute("content", dark ? THEME_BAR.dark : THEME_BAR.light);
  }
  return was !== dark;
}

function phoneTheme(): PhoneTheme | null {
  try {
    return typeof matchMedia === "function" ? matchMedia(PHONE_DARK) : null;
  } catch {
    return null;
  }
}

/** The page's follower, once followTheme has started it: chooseTheme hands it a new choice. */
let follower: ((choice: ThemeChoice) => void) | null = null;

/**
 * Follow the rider's choice from now on: set the theme, then again at each sunrise and sunset when following the
 * sun, when the phone's theme changes when following the phone, and when the page is shown again (a phone asleep
 * through sunset). Called before the first render, so the app never draws in the wrong theme.
 */
export function followTheme(
  page: Page = document,
  win: Pick<Window, "setTimeout" | "clearTimeout" | "dispatchEvent"> = window,
  now: () => number = Date.now,
  store: KeyValueStore | null = browserStore(),
  phone: PhoneTheme | null = phoneTheme(),
): void {
  let choice = readThemeChoice(store);
  let timer: number | undefined;
  const look = () => {
    if (timer !== undefined) win.clearTimeout(timer);
    timer = undefined;
    const at = now();
    if (applyTheme(page, themeDarkFor(choice, at, phone?.matches ?? false))) win.dispatchEvent(new Event(THEME_EVENT));
    const wait = themeWait(choice, at);
    if (wait !== null) timer = win.setTimeout(look, wait) as unknown as number;
  };
  look();
  page.addEventListener("visibilitychange", () => {
    if (page.visibilityState !== "hidden") look();
  });
  phone?.addEventListener?.("change", () => {
    if (choice === "phone") look();
  });
  follower = (next) => {
    choice = next;
    look();
  };
}

/** Settings > Display > Colors: keep the rider's choice and show it at once (the page and, by the event, the map). */
export function chooseTheme(choice: ThemeChoice, store: KeyValueStore | null = browserStore()): void {
  writeThemeChoice(choice, store);
  follower?.(choice);
}
