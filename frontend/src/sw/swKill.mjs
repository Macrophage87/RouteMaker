/**
 * The service worker's kill switch (WEB-NAV-plan.md section 8 and section 10, "service-worker bugs
 * outlive a deploy"). swPlugin.mjs writes it to dist/sw-kill.js beside dist/sw.js; it is never
 * registered by the page. docs/OPERATIONS.md, "The app's service worker: the kill switch", says when
 * and how: copy sw-kill.js over sw.js on the edge, and every browser that checks for an update (each
 * load of the page, at most a day apart by the browser's own rule) installs this instead, which:
 *
 * 1. takes over at once (no waiting for the rider's Reload),
 * 2. deletes every cache the worker made (`workerCaches`: routemaker-app-*), and nothing else: the
 *    routes the rider kept for offline and a ride's corridor are the page's own, and stay,
 * 3. unregisters itself, and
 * 4. reloads the pages it controlled, which then load from the network with no worker at all.
 *
 * A page loaded afterwards registers /sw.js again, which is this file again while it is in place: it
 * installs, finds no page it controls (it never claims one), deletes nothing more and unregisters, so
 * there is no reload loop. The next normal deploy puts the real worker back.
 */
import { workerCaches } from "./swCore.mjs";

export async function kill(scope) {
  const names = await scope.caches.keys();
  await Promise.all(workerCaches(names).map((name) => scope.caches.delete(name)));
  await scope.registration.unregister();
  // Only the pages this worker controls (the default of matchAll): never a page that just registered it.
  const pages = await scope.clients.matchAll({ type: "window" });
  await Promise.all(pages.map((page) => Promise.resolve(page.navigate(page.url)).catch(() => undefined)));
}

export function installKillSwitch(scope) {
  scope.addEventListener("install", () => scope.skipWaiting());
  scope.addEventListener("activate", (event) => event.waitUntil(kill(scope)));
}
