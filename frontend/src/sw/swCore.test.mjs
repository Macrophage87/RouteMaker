// The service worker's rules (WEB-NAV-plan.md section 8 table, section 11 "a test per table row"),
// its install, update and activate steps, and the kill switch, against a stand-in for the worker's
// `self`: Cache Storage as Maps, the network as a function.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import {
  APP_CACHE_PREFIX,
  OFFLINE_BUCKET,
  SHELL_KEY,
  SKIP_WAITING,
  STATIC_CACHE,
  activate,
  buildCache,
  buildOf,
  installWorker,
  precache,
  respond,
  ruleFor,
  staleCaches,
  workerCaches,
} from "./swCore.mjs";
import { installKillSwitch, kill } from "./swKill.mjs";
import { buildIdFor, killSource, plainScript, precacheList, workerSource } from "./swPlugin.mjs";

const ORIGIN = "https://routes.example.org";
const nav = (path) => ({ method: "GET", url: `${ORIGIN}${path}`, mode: "navigate" });
const get = (path, mode = "cors") => ({ method: "GET", url: path.startsWith("http") ? path : `${ORIGIN}${path}`, mode });

// ---- ruleFor: one test per row of the plan's table ------------------------------------------------

test("a navigation to / or /index.html is the shell (network first), with or without a query or fragment", () => {
  for (const path of ["/", "/index.html", "/?x=1", "/#p=-77.0,38.9;-77.1,38.8&preset=default"]) {
    assert.equal(ruleFor(nav(path), ORIGIN), "shell", path);
  }
});

test("any other navigation is not intercepted: sign-in, a made-up admin path, /static, the preset redirects, the stress page", () => {
  for (const path of ["/auth/login", "/auth/discord/callback?code=x", "/internal-zz9q/", "/internal-zz9q/login/", "/static/admin/css/base.css", "/trailmaxxing", "/default/", "/about/stress.html", "/healthz", "/api/route"]) {
    assert.equal(ruleFor(nav(path), ORIGIN), "pass", path);
  }
});

test("/assets/* is precached, cache first", () => {
  assert.equal(ruleFor(get("/assets/index-abc123.js"), ORIGIN), "precache");
  assert.equal(ruleFor(get("/assets/maplibre-gl-worker-x.js", "same-origin"), ORIGIN), "precache");
  assert.equal(ruleFor(get("/assets/atkinson.woff2", "no-cors"), ORIGIN), "precache");
});

test("the favicon, the icons and the licence notices are stale-while-revalidate", () => {
  for (const path of ["/favicon.svg", "/icons/icon-192.png", "/icons/apple-touch-icon.png", "/licenses.txt"]) {
    assert.equal(ruleFor(get(path, "no-cors"), ORIGIN), "static", path);
  }
});

test("the base map archive is not intercepted (range requests and the edge's guard; the page keeps it)", () => {
  assert.equal(ruleFor(get("/basemap/region.pmtiles"), ORIGIN), "pass");
  assert.equal(ruleFor(get("/basemap/other.pmtiles"), ORIGIN), "pass");
});

test("the glyphs and sprites come from the kept routes' bucket first, else the network", () => {
  assert.equal(ruleFor(get("/basemap/fonts/Noto%20Sans%20Regular/0-255.pbf"), ORIGIN), "kept");
  assert.equal(ruleFor(get("/basemap/sprites/light@2x.png"), ORIGIN), "kept");
});

test("/tiles/* passes through: the page's corridor cache serves them offline", () => {
  assert.equal(ruleFor(get("/tiles/stress/14/4686/6265.pbf"), ORIGIN), "pass");
  assert.equal(ruleFor(get("/tiles/mass/13/2343/3132.pbf"), ORIGIN), "pass");
});

test("/api/*, /auth/*, /healthz and every non-GET are never intercepted", () => {
  for (const path of ["/api/route", "/api/me", "/api/reverse?lat=38.9&lon=-77.0", "/api/segment-info?lat=1&lon=2", "/auth/login", "/auth/logout", "/healthz"]) {
    assert.equal(ruleFor(get(path), ORIGIN), "pass", path);
  }
  for (const method of ["POST", "PUT", "PATCH", "DELETE", "HEAD"]) {
    assert.equal(ruleFor({ method, url: `${ORIGIN}/assets/index.js`, mode: "cors" }, ORIGIN), "pass", method);
    assert.equal(ruleFor({ method, url: `${ORIGIN}/`, mode: "navigate" }, ORIGIN), "pass", method);
  }
});

test("another origin, an unlisted path of the site, the worker and manifest themselves pass through", () => {
  assert.equal(ruleFor(get("https://other.example/assets/index.js"), ORIGIN), "pass");
  assert.equal(ruleFor(nav("https://other.example/"), "https://routes.example.org"), "pass");
  assert.equal(ruleFor({ method: "GET", url: "https://other.example/", mode: "navigate" }, ORIGIN), "pass");
  for (const path of ["/sw.js", "/sw-kill.js", "/manifest.webmanifest", "/robots.txt", "/something-new", "/assetsx/a.js"]) {
    assert.equal(ruleFor(get(path), ORIGIN), "pass", path);
  }
  assert.equal(ruleFor({ method: "GET", url: "not a url", mode: "cors" }, ORIGIN), "pass");
});

// ---- small pure parts -----------------------------------------------------------------------------

test("buildOf reads the build id that the plugin writes", () => {
  assert.equal(buildOf('<head><meta name="routemaker-build" content="0123456789abcdef"></head>'), "0123456789abcdef");
  assert.equal(buildOf("<head></head>"), null);
});

test("activate deletes only older builds' caches: never the static cache, a ride's corridor or the kept routes", () => {
  const names = [buildCache("new"), buildCache("old1"), buildCache("old2"), STATIC_CACHE, "routemaker-corridor-v1", OFFLINE_BUCKET, "someone-else"];
  assert.deepEqual(staleCaches(names, "new"), [buildCache("old1"), buildCache("old2")]);
});

test("the kill switch deletes every cache of the worker's and nothing else", () => {
  const names = [buildCache("a"), STATIC_CACHE, "routemaker-corridor-v1", OFFLINE_BUCKET, "x"];
  assert.deepEqual(workerCaches(names), [buildCache("a"), STATIC_CACHE]);
  assert.ok(!OFFLINE_BUCKET.startsWith(APP_CACHE_PREFIX) && !"routemaker-corridor-v1".startsWith(APP_CACHE_PREFIX));
});

test("the worker's bucket name for kept routes is the page's", () => {
  const page = readFileSync(new URL("../lib/offlineRouteStore.ts", import.meta.url), "utf8");
  assert.match(page, new RegExp(`OFFLINE_BUCKET = "${OFFLINE_BUCKET}"`));
});

// ---- a stand-in for the worker's self -------------------------------------------------------------

function keyOf(request) {
  const url = typeof request === "string" ? request : request.url;
  return new URL(url, ORIGIN).href;
}

class FakeResponse {
  constructor(body, status = 200, label = "") {
    this.body = body;
    this.status = status;
    this.ok = status >= 200 && status < 300;
    this.label = label;
  }
  clone() {
    return new FakeResponse(this.body, this.status, this.label);
  }
  async text() {
    return this.body;
  }
}

function fakeScope({ network } = {}) {
  const stores = new Map();
  const listeners = new Map();
  const log = [];
  const timers = [];
  const scope = {
    location: { origin: ORIGIN },
    matchOptions: [],
    log,
    stores,
    timers,
    caches: {
      async open(name) {
        if (!stores.has(name)) stores.set(name, new Map());
        const store = stores.get(name);
        return {
          match: async (request, options) => {
            scope.matchOptions.push(options ?? null);
            return store.get(keyOf(request));
          },
          put: async (request, response) => void store.set(keyOf(request), response),
          addAll: async (urls) => {
            for (const url of urls) {
              const response = await scope.fetch(url);
              if (!response.ok) throw new Error(`${url} ${response.status}`);
              store.set(keyOf(url), response);
            }
          },
        };
      },
      keys: async () => [...stores.keys()],
      delete: async (name) => stores.delete(name),
    },
    fetch: async (request, init) => {
      log.push(["fetch", keyOf(request), init?.cache ?? null]);
      return network(keyOf(request), request);
    },
    setTimeout: (fn, ms) => timers.push({ fn, ms }),
    skipWaiting: () => log.push(["skipWaiting"]),
    clients: { claim: async () => log.push(["claim"]), matchAll: async () => scope.pages ?? [] },
    registration: { unregister: async () => log.push(["unregister"]) },
    addEventListener: (type, fn) => listeners.set(type, fn),
    async dispatch(type, extra = {}) {
      const waits = [];
      let responded = null;
      const event = { ...extra, waitUntil: (p) => waits.push(p), respondWith: (p) => (responded = p) };
      listeners.get(type)(event);
      const settled = await Promise.allSettled(waits);
      return { responded, settled };
    },
  };
  return scope;
}

const SHELL = (id) => `<!doctype html><head><meta name="routemaker-build" content="${id}"></head>`;
const ASSETS = ["/assets/index-1.js", "/assets/index-1.css"];

function site(id, { down = false } = {}) {
  return async (url) => {
    if (down) throw new TypeError("Failed to fetch");
    const path = new URL(url).pathname;
    if (path === "/index.html" || path === "/") return new FakeResponse(SHELL(id), 200, "network-shell");
    if (path.startsWith("/assets/")) return new FakeResponse(`asset ${path}`, 200, "network");
    return new FakeResponse(`file ${path}`, 200, "network");
  };
}

// ---- install --------------------------------------------------------------------------------------

test("install precaches the shell (fetched past the HTTP cache) and every asset of the build", async () => {
  const scope = fakeScope({ network: site("b1") });
  installWorker(scope, { buildId: "b1", assets: ASSETS });
  const { settled } = await scope.dispatch("install");
  assert.equal(settled[0].status, "fulfilled");
  const cache = scope.stores.get(buildCache("b1"));
  assert.deepEqual([...cache.keys()].sort(), [`${ORIGIN}/assets/index-1.css`, `${ORIGIN}/assets/index-1.js`, `${ORIGIN}${SHELL_KEY}`]);
  assert.deepEqual(scope.log[0], ["fetch", `${ORIGIN}/index.html`, "no-store"]);
});

test("install fails, leaving nothing, while the edge still serves another build's index.html (a deploy half published)", async () => {
  const scope = fakeScope({ network: site("old") });
  await assert.rejects(precache(scope, "new", ASSETS), /not yet published/);
  assert.equal(scope.stores.has(buildCache("new")), false);
});

test("install fails when index.html is refused (basic auth, a 502) or an asset is missing", async () => {
  const refused = fakeScope({ network: async () => new FakeResponse("no", 401) });
  await assert.rejects(precache(refused, "b1", ASSETS), /401/);
  const missing = fakeScope({
    network: async (url) => (url.endsWith(".css") ? new FakeResponse("", 404) : site("b1")(url)),
  });
  await assert.rejects(precache(missing, "b1", ASSETS), /404/);
});

// ---- activate and the update flow -----------------------------------------------------------------

test("activate deletes older builds' caches, keeps the kept routes and the corridor, and claims the pages", async () => {
  const scope = fakeScope({ network: site("b2") });
  for (const name of [buildCache("b1"), buildCache("b2"), STATIC_CACHE, OFFLINE_BUCKET, "routemaker-corridor-v1"]) scope.stores.set(name, new Map());
  await activate(scope, "b2");
  assert.deepEqual([...scope.stores.keys()].sort(), [buildCache("b2"), STATIC_CACHE, "routemaker-corridor-v1", OFFLINE_BUCKET].sort());
  assert.deepEqual(scope.log.at(-1), ["claim"]);
});

test("a waiting worker skips waiting only on the page's SKIP_WAITING message (the rider's Reload)", async () => {
  const scope = fakeScope({ network: site("b1") });
  installWorker(scope, { buildId: "b1", assets: [] });
  await scope.dispatch("install");
  assert.ok(!scope.log.some(([what]) => what === "skipWaiting"), "installing alone never skips waiting");
  await scope.dispatch("message", { data: { type: "something else" } });
  await scope.dispatch("message", { data: null });
  assert.ok(!scope.log.some(([what]) => what === "skipWaiting"));
  await scope.dispatch("message", { data: { type: SKIP_WAITING } });
  assert.deepEqual(scope.log.at(-1), ["skipWaiting"]);
});

// ---- fetch ----------------------------------------------------------------------------------------

test("a request the rules pass is not answered at all: no respondWith", async () => {
  const scope = fakeScope({ network: site("b1") });
  installWorker(scope, { buildId: "b1", assets: [] });
  for (const request of [get("/api/route"), nav("/auth/login"), get("/tiles/stress/1/2/3.pbf"), { method: "POST", url: `${ORIGIN}/api/route`, mode: "cors" }]) {
    const { responded } = await scope.dispatch("fetch", { request });
    assert.equal(responded, null, request.url);
  }
  assert.equal(scope.log.length, 0, "and nothing was fetched or cached by the worker");
});

test("the shell: online, the network's answer (so a deploy is picked up at once), and it is not cached", async () => {
  const scope = fakeScope({ network: site("b2") });
  scope.stores.set(buildCache("b1"), new Map([[`${ORIGIN}${SHELL_KEY}`, new FakeResponse(SHELL("b1"), 200, "kept-shell")]]));
  const answer = await respond(scope, "shell", nav("/"), "b1");
  assert.equal(answer.label, "network-shell");
  assert.equal(scope.stores.get(buildCache("b1")).get(`${ORIGIN}${SHELL_KEY}`).label, "kept-shell");
});

test("the shell: offline, the kept one; with none kept, the network's failure", async () => {
  const scope = fakeScope({ network: site("b1", { down: true }) });
  scope.stores.set(buildCache("b1"), new Map([[`${ORIGIN}${SHELL_KEY}`, new FakeResponse(SHELL("b1"), 200, "kept-shell")]]));
  assert.equal((await respond(scope, "shell", nav("/"), "b1")).label, "kept-shell");
  const empty = fakeScope({ network: site("b1", { down: true }) });
  await assert.rejects(respond(empty, "shell", nav("/"), "b1"), /Failed to fetch/);
});

test("the shell: a network slower than the timeout gives way to the kept shell", async () => {
  const scope = fakeScope({ network: () => new Promise(() => undefined) });
  scope.stores.set(buildCache("b1"), new Map([[`${ORIGIN}${SHELL_KEY}`, new FakeResponse(SHELL("b1"), 200, "kept-shell")]]));
  const pending = respond(scope, "shell", nav("/"), "b1", undefined, 3000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(scope.timers[0].ms, 3000);
  scope.timers[0].fn();
  assert.equal((await pending).label, "kept-shell");
});

test("an asset: from the build's cache when precached, else the network (not cached)", async () => {
  const scope = fakeScope({ network: site("b1") });
  scope.stores.set(buildCache("b1"), new Map([[`${ORIGIN}/assets/a.js`, new FakeResponse("a", 200, "precached")]]));
  assert.equal((await respond(scope, "precache", get("/assets/a.js"), "b1")).label, "precached");
  assert.equal((await respond(scope, "precache", get("/assets/b.js"), "b1")).label, "network");
  assert.equal(scope.stores.get(buildCache("b1")).has(`${ORIGIN}/assets/b.js`), false);
  // Whatever the edge's Vary: a module script's request carries Origin, the precache's did not.
  assert.ok(scope.matchOptions.length > 0 && scope.matchOptions.every((o) => o?.ignoreVary === true));
});

test("the favicon: the kept copy at once, refreshed behind it; the first time, the network's, then kept", async () => {
  const scope = fakeScope({ network: site("b1") });
  const waits = [];
  const first = await respond(scope, "static", get("/favicon.svg"), "b1", (p) => waits.push(p));
  assert.equal(first.label, "network");
  await Promise.all(waits);
  assert.ok(scope.stores.get(STATIC_CACHE).has(`${ORIGIN}/favicon.svg`));
  scope.stores.get(STATIC_CACHE).set(`${ORIGIN}/favicon.svg`, new FakeResponse("old", 200, "kept"));
  const second = await respond(scope, "static", get("/favicon.svg"), "b1", (p) => waits.push(p));
  assert.equal(second.label, "kept");
  await Promise.all(waits);
  assert.equal(scope.stores.get(STATIC_CACHE).get(`${ORIGIN}/favicon.svg`).label, "network");
});

test("the favicon offline: the kept copy, and the failed refresh is swallowed", async () => {
  const scope = fakeScope({ network: site("b1", { down: true }) });
  scope.stores.set(STATIC_CACHE, new Map([[`${ORIGIN}/favicon.svg`, new FakeResponse("x", 200, "kept")]]));
  const waits = [];
  assert.equal((await respond(scope, "static", get("/favicon.svg"), "b1", (p) => waits.push(p))).label, "kept");
  await Promise.all(waits);
});

test("a glyph: from the kept routes' bucket when there, else the network; the worker never writes that bucket", async () => {
  const scope = fakeScope({ network: site("b1") });
  const glyph = `${ORIGIN}/basemap/fonts/Noto%20Sans%20Regular/0-255.pbf`;
  scope.stores.set(OFFLINE_BUCKET, new Map([[glyph, new FakeResponse("g", 200, "kept")]]));
  assert.equal((await respond(scope, "kept", get(glyph), "b1")).label, "kept");
  assert.equal((await respond(scope, "kept", get("/basemap/sprites/light.json"), "b1")).label, "network");
  assert.equal(scope.stores.get(OFFLINE_BUCKET).size, 1);
});

// ---- the kill switch ------------------------------------------------------------------------------

test("the kill switch takes over at once, deletes the worker's caches only, unregisters and reloads the pages it controls", async () => {
  const scope = fakeScope({ network: site("b1") });
  for (const name of [buildCache("b1"), STATIC_CACHE, OFFLINE_BUCKET, "routemaker-corridor-v1"]) scope.stores.set(name, new Map());
  const reloaded = [];
  scope.pages = [{ url: `${ORIGIN}/#p=1`, navigate: async (url) => reloaded.push(url) }, { url: `${ORIGIN}/`, navigate: async () => { throw new Error("gone"); } }];
  installKillSwitch(scope);
  await scope.dispatch("install");
  assert.deepEqual(scope.log[0], ["skipWaiting"]);
  const { settled } = await scope.dispatch("activate");
  assert.equal(settled[0].status, "fulfilled");
  assert.deepEqual([...scope.stores.keys()].sort(), [OFFLINE_BUCKET, "routemaker-corridor-v1"].sort());
  assert.ok(scope.log.some(([what]) => what === "unregister"));
  assert.deepEqual(reloaded, [`${ORIGIN}/#p=1`]);
});

test("the kill switch, registered again by a fresh page, controls none, so reloads none: no loop", async () => {
  const scope = fakeScope({ network: site("b1") });
  scope.pages = [];
  await kill(scope);
  assert.deepEqual(scope.log, [["unregister"]]);
});

// ---- the build step -------------------------------------------------------------------------------

test("the worker's sources import nothing but each other, so the plain scripts are complete", () => {
  for (const name of ["swCore.mjs", "swKill.mjs"]) {
    const source = readFileSync(new URL(name, import.meta.url), "utf8");
    const imports = source.split("\n").filter((line) => /^\s*import\s/.test(line));
    assert.ok(imports.every((line) => /from "\.\/sw(Core|Kill)\.mjs";$/.test(line)), `${name}: ${imports.join(" | ")}`);
    assert.ok(!/^\s*import\s/m.test(plainScript(source)) && !/^\s*export\s/m.test(plainScript(source)), name);
  }
});

test("dist/sw.js runs as a classic script and answers with its build's rules", async () => {
  const source = workerSource("0123456789abcdef", ["/assets/a.js"]);
  const scope = fakeScope({ network: site("0123456789abcdef", { down: true }) });
  vm.runInNewContext(source, { self: scope, URL, Promise, Error, TypeError });
  const { responded } = await scope.dispatch("fetch", { request: get("/api/route") });
  assert.equal(responded, null);
  scope.stores.set(buildCache("0123456789abcdef"), new Map([[`${ORIGIN}${SHELL_KEY}`, new FakeResponse("s", 200, "kept-shell")]]));
  const shell = await scope.dispatch("fetch", { request: nav("/") });
  assert.equal((await shell.responded).label, "kept-shell");
});

test("dist/sw-kill.js runs as a classic script and is the kill switch", async () => {
  const scope = fakeScope({ network: site("b1") });
  scope.stores.set(buildCache("b1"), new Map());
  vm.runInNewContext(killSource(), { self: scope, URL, Promise, Error });
  await scope.dispatch("install");
  await scope.dispatch("activate");
  assert.equal(scope.stores.size, 0);
  assert.ok(scope.log.some(([what]) => what === "unregister"));
});

test("the build id changes with any written file or index.html, and not with their order", () => {
  const a = buildIdFor(["assets/a-1.js", "assets/b-1.css", "index.html"], "<html>");
  assert.equal(a, buildIdFor(["index.html", "assets/b-1.css", "assets/a-1.js"], "<html>"));
  assert.notEqual(a, buildIdFor(["assets/a-2.js", "assets/b-1.css"], "<html>"));
  assert.notEqual(a, buildIdFor(["assets/a-1.js", "assets/b-1.css"], "<html lang=en>"));
  assert.match(a, /^[0-9a-f]{16}$/);
});

test("the precache list is the build's assets only: not index.html, the worker, the licence notices or the public files", () => {
  assert.deepEqual(precacheList(["index.html", "sw.js", "licenses.txt", "assets/b.js", "assets/a.css", "favicon.svg", "icons/icon-192.png"]), ["/assets/a.css", "/assets/b.js"]);
});
