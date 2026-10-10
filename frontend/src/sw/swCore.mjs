/**
 * The installable app's service worker (WEB-NAV-plan.md section 8, phase P2), hand-written, no
 * Workbox. This file is both the worker's code and a module the tests import: swPlugin.mjs writes
 * dist/sw.js from it at build time (the `export` words dropped, the build's id and precache list
 * appended), so there is one copy of every rule.
 *
 * Scope "/". What it touches, and nothing else (`ruleFor`; an allowlist, so a path added to the site
 * later is passed through untouched until it is listed here):
 *
 * | Request                                   | Rule                                                  |
 * |-------------------------------------------|-------------------------------------------------------|
 * | navigation to / or /index.html            | network first, SHELL_TIMEOUT_MS, else the kept shell  |
 * | any other navigation                      | not intercepted (sign-in, the admin, /static, presets)|
 * | /assets/*                                 | precached at install; cache first                     |
 * | /favicon.svg, /icons/*, /licenses.txt     | stale-while-revalidate                                |
 * | /basemap/fonts/*, /basemap/sprites/*      | the kept routes' bucket first, else the network       |
 * | /basemap/region.pmtiles, /tiles/*         | not intercepted (the page keeps them: corridor.ts)    |
 * | /api/*, /auth/*, /healthz, any non-GET    | not intercepted, never cached                         |
 * | another origin                            | not intercepted                                       |
 *
 * Nothing private is cached: no API answer, no sign-in page, no position. The kept routes (the
 * rider's own, OWNER-DECISIONS 465a) are written by the page (lib/offlineRouteStore.ts), never by
 * this worker; it only reads their glyphs and sprite back.
 *
 * Updates: a new worker installs only when the edge's index.html is the same build as itself
 * (`buildOf`), so a deploy caught half published (sw.js copied, index.html not yet renamed) fails the
 * install and the browser tries again on the next load. Installed, it waits; the page offers "A new
 * version of RouteMaker is ready" with Reload (lib/appWorker.ts), and only that press sends
 * SKIP_WAITING. On activate, the caches of older builds are deleted. The kill switch is swKill.mjs.
 */

/** Every cache this worker makes starts with this; the kill switch deletes exactly these. */
export const APP_CACHE_PREFIX = "routemaker-app-";
/** The small files kept by stale-while-revalidate, across builds. */
export const STATIC_CACHE = "routemaker-app-static";
/** The kept routes' bucket (lib/offlineRouteStore.ts OFFLINE_BUCKET; a test holds the two equal). */
export const OFFLINE_BUCKET = "routemaker-offline-v1";
/** The shell's key in the build's cache. */
export const SHELL_KEY = "/index.html";
/** How long a navigation waits for the network before the kept shell answers. */
export const SHELL_TIMEOUT_MS = 3000;
/** index.html's <meta name=...> carrying the build's id (swPlugin.mjs writes it). */
export const BUILD_META = "routemaker-build";
/** The one message the page sends: the rider pressed Reload. */
export const SKIP_WAITING = "SKIP_WAITING";

/** The build's own cache: its assets and its shell. */
export function buildCache(buildId) {
  return `${APP_CACHE_PREFIX}${buildId}`;
}

/**
 * What the worker does with a request: "shell", "precache", "static", "kept", or "pass" (no
 * respondWith at all, so the browser handles it exactly as with no worker).
 * `request` needs `method`, `url` and `mode`; `origin` is the worker's own.
 */
export function ruleFor(request, origin) {
  if (request.method !== "GET") return "pass";
  let url;
  try {
    url = new URL(request.url);
  } catch {
    return "pass";
  }
  if (url.origin !== origin) return "pass";
  const path = url.pathname;
  if (request.mode === "navigate") return path === "/" || path === "/index.html" ? "shell" : "pass";
  if (path.startsWith("/assets/")) return "precache";
  if (path === "/favicon.svg" || path === "/licenses.txt" || path.startsWith("/icons/")) return "static";
  if (path.startsWith("/basemap/fonts/") || path.startsWith("/basemap/sprites/")) return "kept";
  return "pass";
}

/** The build id in an index.html, or null. */
export function buildOf(html) {
  const tag = /<meta\s+name="routemaker-build"\s+content="([^"]*)"/.exec(html);
  return tag ? tag[1] : null;
}

/** The caches to delete on activate: the worker's own, of any other build. Never the kept routes'. */
export function staleCaches(names, buildId) {
  return names.filter((name) => name.startsWith(APP_CACHE_PREFIX) && name !== buildCache(buildId) && name !== STATIC_CACHE);
}

/** The caches the kill switch deletes: every one of the worker's own, and only those. */
export function workerCaches(names) {
  return names.filter((name) => name.startsWith(APP_CACHE_PREFIX));
}

/** Precache: the shell (only if it is this build's) and every asset of the build. */
export async function precache(scope, buildId, assets) {
  const shell = await scope.fetch(SHELL_KEY, { cache: "no-store" });
  if (!shell.ok) throw new Error(`index.html answered ${shell.status}`);
  const found = buildOf(await shell.clone().text());
  if (found !== buildId) throw new Error(`index.html is build ${found}, this worker is ${buildId}: not yet published`);
  const cache = await scope.caches.open(buildCache(buildId));
  await cache.addAll(assets);
  await cache.put(SHELL_KEY, shell);
}

/** Activate: the older builds' caches go, and the open pages are taken (a first install works offline at once). */
export async function activate(scope, buildId) {
  const names = await scope.caches.keys();
  await Promise.all(staleCaches(names, buildId).map((name) => scope.caches.delete(name)));
  await scope.clients.claim();
}

async function shell(scope, request, buildId, timeoutMs) {
  const network = scope.fetch(request);
  network.catch(() => undefined);
  const late = new Promise((resolve) => scope.setTimeout(() => resolve(null), timeoutMs));
  try {
    const answer = await Promise.race([network, late]);
    if (answer) return answer;
  } catch {
    // No network: the kept shell.
  }
  const cache = await scope.caches.open(buildCache(buildId));
  const kept = await cache.match(SHELL_KEY, ANY_VARY);
  return kept ?? network;
}

/**
 * Kept files answer whatever their Vary says: a module script's request carries Origin and the
 * precache's did not, so an edge that varies on Origin would otherwise miss every one. Safe here,
 * since each is one file under one name (hashed, or kept as it was fetched).
 */
const ANY_VARY = { ignoreVary: true };

async function fromCache(scope, name, request) {
  const cache = await scope.caches.open(name);
  return (await cache.match(request, ANY_VARY)) ?? scope.fetch(request);
}

function staleWhileRevalidate(scope, request, waitUntil) {
  const answer = scope.caches.open(STATIC_CACHE).then(async (cache) => {
    const kept = await cache.match(request, ANY_VARY);
    const fresh = scope.fetch(request).then((response) => {
      if (response.ok) return cache.put(request, response.clone()).then(() => response);
      return response;
    });
    waitUntil(fresh.catch(() => undefined));
    return kept ?? fresh;
  });
  return answer;
}

/** The answer for a request whose rule is not "pass". */
export function respond(scope, rule, request, buildId, waitUntil = () => undefined, timeoutMs = SHELL_TIMEOUT_MS) {
  if (rule === "shell") return shell(scope, request, buildId, timeoutMs);
  if (rule === "precache") return fromCache(scope, buildCache(buildId), request);
  if (rule === "static") return staleWhileRevalidate(scope, request, waitUntil);
  if (rule === "kept") return fromCache(scope, OFFLINE_BUCKET, request);
  return scope.fetch(request);
}

/** The worker's listeners, on `scope` (the worker's `self`, or a stand-in in the tests). */
export function installWorker(scope, { buildId, assets }) {
  scope.addEventListener("install", (event) => event.waitUntil(precache(scope, buildId, assets)));
  scope.addEventListener("activate", (event) => event.waitUntil(activate(scope, buildId)));
  scope.addEventListener("message", (event) => {
    if (event.data && event.data.type === SKIP_WAITING) scope.skipWaiting();
  });
  scope.addEventListener("fetch", (event) => {
    const rule = ruleFor(event.request, scope.location.origin);
    if (rule === "pass") return;
    event.respondWith(respond(scope, rule, event.request, buildId, (p) => event.waitUntil(p)));
  });
}
