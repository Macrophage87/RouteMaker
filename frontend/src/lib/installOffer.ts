/**
 * The install offer (WEB-NAV-plan.md section 8 "Install prompt", phase P4). Never a pop-up:
 *
 * - Chrome, Edge, Android: the browser's `beforeinstallprompt` is held (its own mini-bar is
 *   suppressed) and an "Install RouteMaker" button is offered in Settings and in More tips; pressing it
 *   shows the browser's own install dialog. `appinstalled` hides the offer.
 * - iOS (Safari, and any iOS browser, which are all Safari underneath): no prompt exists, so one line
 *   says how: "In Safari, press Share, then Add to Home Screen."
 * - Running installed (standalone): a line saying so, and no offer.
 * - Anything else (Firefox on a desktop): nothing.
 *
 * The event usually comes before React has drawn the page, so `watchInstall` is called from main.tsx
 * and holds it here; the page reads it with `subscribeInstall`.
 */

export const INSTALL_LABEL = "Install RouteMaker";
export const INSTALL_HEADING = "Install the app";
export const INSTALL_WHY =
  "Installed, RouteMaker opens from your home screen in its own window, starts with no signal, and keeps the routes you keep for offline.";
export const IOS_INSTALL = "In Safari, press Share, then Add to Home Screen.";
export const INSTALLED_NOTE = "RouteMaker is installed on this device.";
export const INSTALLED_SAID = "RouteMaker is installed. Open it from your home screen or app list.";
export const DISMISSED_SAID = "Not installed. The Install RouteMaker button is in Settings if you change your mind.";

export type Offer = "button" | "ios" | "installed" | "none";

export interface InstallState {
  /** A held `beforeinstallprompt`. */
  promptable: boolean;
  /** `appinstalled` came in this page. */
  installed: boolean;
  /** The page runs as the installed app. */
  standalone: boolean;
  ios: boolean;
}

export function installOffer(state: InstallState): Offer {
  if (state.standalone || state.installed) return "installed";
  if (state.promptable) return "button";
  if (state.ios) return "ios";
  return "none";
}

/** iPhone, iPod, and an iPad (which says it is a Mac, but has a touch screen). */
export function isIos(userAgent: string, platform = "", maxTouchPoints = 0): boolean {
  return /iPhone|iPad|iPod/.test(userAgent) || (platform === "MacIntel" && maxTouchPoints > 1);
}

export interface PromptEvent {
  preventDefault(): void;
  prompt(): Promise<unknown>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

interface InstallWindow {
  addEventListener(type: string, listener: (event: Event) => void): void;
  matchMedia?(query: string): { matches: boolean };
  navigator: { userAgent: string; platform?: string; maxTouchPoints?: number; standalone?: boolean };
}

let held: PromptEvent | null = null;
let installedHere = false;
let env: InstallWindow | null = null;
const listeners = new Set<() => void>();

const changed = () => listeners.forEach((listener) => listener());

/** Whether the page runs installed: the manifest's standalone (or fuller) display, or iOS's own flag. */
export function isStandalone(win: InstallWindow | null = env): boolean {
  if (!win) return false;
  const media = (q: string) => !!win.matchMedia?.(`(display-mode: ${q})`).matches;
  return media("standalone") || media("fullscreen") || media("minimal-ui") || win.navigator.standalone === true;
}

/** main.tsx, before the first render: hold the browser's install prompt, and hear `appinstalled`. */
export function watchInstall(win: InstallWindow): void {
  env = win;
  win.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    held = event as unknown as PromptEvent;
    changed();
  });
  win.addEventListener("appinstalled", () => {
    held = null;
    installedHere = true;
    changed();
  });
}

export function installState(): InstallState {
  const nav = env?.navigator;
  return {
    promptable: held !== null,
    installed: installedHere,
    standalone: isStandalone(),
    ios: nav ? isIos(nav.userAgent, nav.platform, nav.maxTouchPoints) : false,
  };
}

export function subscribeInstall(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * The Install press: the browser's own dialog. A prompt can be shown once, so it is let go either way;
 * the browser may offer a new one later (another `beforeinstallprompt`).
 */
export async function promptInstall(): Promise<"accepted" | "dismissed" | "none"> {
  const event = held;
  if (!event) return "none";
  held = null;
  try {
    await event.prompt();
    const { outcome } = await event.userChoice;
    return outcome;
  } catch {
    return "dismissed";
  } finally {
    changed();
  }
}

/** For the tests: forget everything held. */
export function resetInstall(): void {
  held = null;
  installedHere = false;
  env = null;
  listeners.clear();
}
