import { isStandalone } from "./installOffer.ts";
import { nativeBridge } from "./nativeShell.ts";

/**
 * Running as an installed app: the installed web app (standalone), or the Android app, whose WebView is not a
 * standalone display, so it kept no "Last ride" and was told Safari's seven-day rule (backlog 2026-11-12, area 13
 * item 11: a ride in a dead spot should reopen in the Play app as in the installed web app).
 */
export function installedApp(): boolean {
  return isStandalone() || nativeBridge() !== null;
}
