/*
 * The page's colour theme follows the sun: dark from sunset to sunrise, light by day, in DC (the covered region is
 * one place for this). The owner, 2026-11-01: "Set the default color mode to adjust by time of day" and "do
 * sunrise/sunset". It replaces following the phone's own theme; a dark page at night also saves screen power on OLED
 * phones (battery audit). The class on the root carries it (styles.css `:root.theme-dark`), and the event tells the
 * map (useMapFlavour.ts).
 */
import { isDark, nextLightChange } from "./mapFlavour.ts";
import { COVERAGE_CENTRE } from "./plusCode.ts";

export const THEME_DARK_CLASS = "theme-dark";
/** Sent on window when the theme turns. */
export const THEME_EVENT = "routemaker-theme";
/** The browser bar's colour in each theme (index.html's theme-color, the panels' --bg). */
export const THEME_BAR = { light: "#ffffff", dark: "#1b1e24" } as const;

/** Whether the theme is dark at `ms`: from sunset to sunrise at the region's centre. */
export function themeDarkAt(ms: number): boolean {
  return isDark(ms, COVERAGE_CENTRE[1], COVERAGE_CENTRE[0]);
}

/** Whether the page shows the dark theme now (the class, set by followSun). */
export function themeIsDark(root: { classList: { contains(name: string): boolean } } | null = typeof document === "undefined" ? null : document.documentElement): boolean {
  return root?.classList.contains(THEME_DARK_CLASS) ?? false;
}

/** How long to wait before looking again: until a second past the next sunrise or sunset, at most an hour. */
export function themeWait(ms: number): number {
  const next = nextLightChange(ms, COVERAGE_CENTRE[1], COVERAGE_CENTRE[0]);
  return next === null ? 60 * 60_000 : Math.min(60 * 60_000, Math.max(1000, next - ms + 1000));
}

interface Page {
  documentElement: { classList: { contains(name: string): boolean; toggle(name: string, on: boolean): unknown } };
  querySelectorAll(selector: string): ArrayLike<{ setAttribute(name: string, value: string): void; removeAttribute(name: string): void }>;
  visibilityState?: string;
  addEventListener(type: "visibilitychange", listener: () => void): void;
}

/** Set the theme for `ms`; true when it changed. */
export function applyTheme(page: Page, ms: number): boolean {
  const dark = themeDarkAt(ms);
  const was = page.documentElement.classList.contains(THEME_DARK_CLASS);
  page.documentElement.classList.toggle(THEME_DARK_CLASS, dark);
  const bars = page.querySelectorAll('meta[name="theme-color"]');
  for (let i = 0; i < bars.length; i += 1) {
    bars[i].removeAttribute("media");
    bars[i].setAttribute("content", dark ? THEME_BAR.dark : THEME_BAR.light);
  }
  return was !== dark;
}

/**
 * Follow the sun from now on: set the theme, then again at each sunrise and sunset, and when the page is shown again
 * (a phone asleep through sunset). Called before the first render, so the page never flashes the wrong theme.
 */
export function followSun(page: Page = document, win: Pick<Window, "setTimeout" | "dispatchEvent"> = window, now: () => number = Date.now): void {
  let timer: number | undefined;
  const look = () => {
    if (timer !== undefined) clearTimeout(timer);
    const at = now();
    if (applyTheme(page, at)) win.dispatchEvent(new Event(THEME_EVENT));
    timer = win.setTimeout(look, themeWait(at)) as unknown as number;
  };
  look();
  page.addEventListener("visibilitychange", () => {
    if (page.visibilityState !== "hidden") look();
  });
}
