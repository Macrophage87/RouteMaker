// A small Chrome DevTools Protocol driver over Node 22's WebSocket, and the mock
// API the a11y browser check plans against. Nothing leaves the page: /api,
// /tiles, /basemap and /auth are answered here (CDP Fetch). Adapted from the
// combined a11y review's scripts (integrate-2).
import { writeFileSync } from "node:fs";
import { inflateSync } from "node:zlib";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function connect(port = 9222) {
  let version;
  for (let i = 0; i < 100 && !version; i++) {
    try {
      version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
    } catch {
      await sleep(200);
    }
  }
  if (!version) throw new Error("no Chromium on the debugging port");
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });
  let id = 0;
  const pending = new Map();
  const handlers = new Set();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) rej(new Error(JSON.stringify(msg.error)));
      else res(msg.result);
    } else if (msg.method) for (const h of handlers) h(msg);
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((res, rej) => {
      const i = ++id;
      pending.set(i, { res, rej });
      ws.send(JSON.stringify({ id: i, method, params, sessionId }));
    });
  return { send, on: (h) => handlers.add(h), off: (h) => handlers.delete(h), close: () => ws.close() };
}

/** A fresh browser context and page. */
export async function newPage(b, { width = 1280, height = 900, mobile = false } = {}) {
  const { browserContextId } = await b.send("Target.createBrowserContext", { disposeOnDetach: true });
  const { targetId } = await b.send("Target.createTarget", { url: "about:blank", browserContextId });
  const { sessionId } = await b.send("Target.attachToTarget", { targetId, flatten: true });
  const s = (m, p) => b.send(m, p, sessionId);
  const page = {
    s,
    /** For Browser.setPermission and the like, which are per context. */
    contextId: browserContextId,
    listeners: new Set(),
    async close() {
      b.off(handler);
      await b.send("Target.closeTarget", { targetId }).catch(() => {});
      await b.send("Target.disposeBrowserContext", { browserContextId }).catch(() => {});
    },
    async eval(expr) {
      const r = await s("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) throw new Error("eval: " + JSON.stringify(r.exceptionDetails).slice(0, 600));
      return r.result.value;
    },
    async waitFor(expr, ms = 20000) {
      const t0 = Date.now();
      while (Date.now() - t0 < ms) {
        try {
          if (await page.eval(expr)) return true;
        } catch {
          // not yet
        }
        await sleep(150);
      }
      return false;
    },
    async png(clip) {
      const params = { format: "png" };
      if (clip) params.clip = { ...clip, scale: 1 };
      const { data } = await s("Page.captureScreenshot", params);
      return Buffer.from(data, "base64");
    },
    async shot(path, clip) {
      writeFileSync(path, await page.png(clip));
    },
    async key(key, code, keyCode, modifiers = 0) {
      const text = key.length === 1 ? key : key === "Enter" ? "\r" : undefined;
      await s("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: keyCode, text, modifiers });
      await s("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: keyCode, modifiers });
    },
    /** Text typed into the focused field (no key events: the page sees input). */
    type(text) {
      return s("Input.insertText", { text });
    },
    tab(shift = false) {
      return page.key("Tab", "Tab", 9, shift ? 8 : 0);
    },
    enter() {
      return page.key("Enter", "Enter", 13);
    },
    escape() {
      return page.key("Escape", "Escape", 27);
    },
  };
  const handler = (msg) => {
    if (msg.sessionId === sessionId) for (const f of page.listeners) f(msg);
  };
  b.on(handler);
  await s("Page.enable");
  await s("Runtime.enable");
  await s("DOM.enable");
  await s("Accessibility.enable");
  await s("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  return page;
}

export async function media(page, { scheme = "light", forced = false } = {}) {
  await page.s("Emulation.setEmulatedMedia", {
    media: "",
    features: [
      { name: "prefers-color-scheme", value: scheme },
      { name: "forced-colors", value: forced ? "active" : "none" },
      { name: "prefers-reduced-motion", value: "reduce" },
    ],
  });
}

/**
 * Answer /api, /tiles, /basemap and /auth here; `route` may be a function of the request count.
 * `delayMs` holds every route answer from the `delayFrom`th on (a slow plan: the a11y review of
 * the release, SF1; lifted from its probe's mockDelayed), and `stressTiles: false` answers the
 * stress tiles with an error (the stress map unavailable).
 */
export async function mock(page, route, { delayMs = 0, delayFrom = 2, stressTiles = true, admin = false } = {}) {
  page.routeRequests = 0;
  // The bodies of the route requests, and the nearest-stations requests (OWNER-DECISIONS 466a).
  page.routeBodies = [];
  page.stationRequests = [];
  page.infoRequests = [];
  // The road panel's stress editor (OWNER-DECISIONS 441g, 441h; core/stress_edits.py): `admin` makes this
  // visitor an instance admin; `editRoad` is the one road's state, `editRequests` what the page sent
  // (method, path, headers, body), `tileUrls` the stress tiles asked for, and `editFail` an answer to give
  // the next write instead ({ status, body }).
  page.editRoad = { tier: 3, was: 3, edit: null, generation: 0, edits: 0 };
  page.editRequests = [];
  page.editFail = null;
  page.tileUrls = [];
  // Tile requests by set: the stress tiles (the first is MapView's probe) and the Mass Ride's own.
  page.tileRequests = { stress: 0, mass: 0 };
  await page.s("Fetch.enable", {
    patterns: [{ urlPattern: "*/api/*" }, { urlPattern: "*/tiles/*" }, { urlPattern: "*/basemap/*" }, { urlPattern: "*/auth/*" }],
  });
  page.listeners.add(async (msg) => {
    if (msg.method !== "Fetch.requestPaused") return;
    const { requestId, request } = msg.params;
    const url = new URL(request.url);
    let status = 404;
    let body = "";
    let type = "text/plain";
    if (url.pathname.startsWith("/tiles/mass/")) {
      // The Mass Ride map's own tiles (core/mass_tiles.py): roads with a capacity on a rebuilt
      // table, and empty on one without the column.
      page.tileRequests.mass += 1;
      status = stressTiles ? 200 : 503;
      type = "application/x-protobuf";
      if (stressTiles === "capacity") body = capacityTile();
    } else if (url.pathname.startsWith("/tiles/stress/")) {
      page.tileRequests.stress += 1;
      page.tileUrls.push(request.url);
      status = stressTiles ? 200 : 503;
      type = "application/x-protobuf";
      // "capacity": a tile of roads that carry the Mass Ride capacity (`rpm`), as a rebuilt table's do.
      if (stressTiles === "capacity") body = capacityTile();
    } else if (url.pathname === "/api/route" && request.method === "POST") {
      page.routeRequests += 1;
      // The bodies, for Ride mode's re-plan check (its first point is the rider's position).
      (page.routeBodies ??= []).push(request.postData ?? "");
      const n = page.routeRequests;
      // page.delayFrom, where a check sets it, is the request the delay starts at.
      if (delayMs && n >= (page.delayFrom ?? delayFrom)) await sleep(delayMs);
      status = 200;
      body = JSON.stringify(typeof route === "function" ? route(n) : route);
      type = "application/json";
    } else if (url.pathname === "/api/bikeshare/stations" && request.method === "POST") {
      // The nearest stations to pick up from or return to (core/bikeshare.py nearby_stations).
      const asked = JSON.parse(request.postData ?? "{}");
      page.stationRequests.push({ search: url.search, ...asked });
      status = 200;
      body = JSON.stringify(asked.action === "dropoff" ? S_STATIONS_DROPOFF : S_STATIONS_PICKUP);
      type = "application/json";
    } else if (url.pathname === "/api/segment-info") {
      // The map's road panel (OWNER-DECISIONS 441a; core/segment_info.py): one fixed road.
      page.infoRequests.push(url.search);
      status = 200;
      body = JSON.stringify(segmentInfoAt(page.editRoad.tier));
      type = "application/json";
    } else if (url.pathname === "/api/me") {
      status = 200;
      body = JSON.stringify({ signed_in: admin, can_change_lts: admin, can_suggest: false });
      type = "application/json";
    } else if (admin && url.pathname.startsWith("/api/stress-edits")) {
      const road = page.editRoad;
      const record = { method: request.method, path: url.pathname, headers: request.headers, body: request.postData ? JSON.parse(request.postData) : null };
      page.editRequests.push(record);
      type = "application/json";
      const undo = /^\/api\/stress-edits\/(\d+)\/undo$/.exec(url.pathname);
      if (request.method === "GET") {
        status = 200;
        body = JSON.stringify(editorState(road));
      } else if (page.editFail) {
        status = page.editFail.status;
        body = JSON.stringify(page.editFail.body);
        page.editFail = null;
      } else if (undo && Number(undo[1]) === road.edit) {
        road.tier = road.was;
        road.edit = null;
        road.generation += 1;
        status = 200;
        body = JSON.stringify({ edit_id: road.edits + 1, ways: [{ osm_way_id: 101, step: road.tier, changed: true }], generation: road.generation, undo_until: new Date().toISOString() });
        road.edits += 1;
      } else if (!undo && record.body && record.body.expected === `tok-${road.generation}`) {
        road.was = road.tier;
        road.tier = record.body.step;
        road.edits += 1;
        road.edit = road.edits;
        road.generation += 1;
        status = 200;
        body = JSON.stringify({ edit_id: road.edit, ways: [{ osm_way_id: 101, step: road.tier, changed: road.tier !== road.was }], generation: road.generation, undo_until: new Date(Date.now() + 30 * 60000).toISOString() });
      } else {
        status = 409;
        body = JSON.stringify({ error: "Someone changed this road since you opened it. Reopen it to see the change.", code: "stale" });
      }
    } else if (url.pathname.startsWith("/api/")) {
      body = JSON.stringify({ detail: "not found" });
      type = "application/json";
    }
    await page
      .s("Fetch.fulfillRequest", {
        requestId,
        responseCode: status,
        responseHeaders: [{ name: "Content-Type", value: type }],
        body: Buffer.from(body).toString("base64"),
      })
      .catch(() => {});
  });
}

// ---- A stress tile with the Mass Ride capacity (core/stress_tiles.py, `rpm`) ----

const varint = (n) => {
  const out = [];
  let v = n;
  while (v > 127) {
    out.push((v & 127) | 128);
    v = Math.floor(v / 128);
  }
  out.push(v);
  return Buffer.from(out);
};
const field = (number, wire, payload) => Buffer.concat([varint(number * 8 + wire), payload]);
const bytesField = (number, buf) => field(number, 2, Buffer.concat([varint(buf.length), buf]));
const uint = (number, n) => field(number, 0, varint(n));
const zigzag = (n) => (n << 1) ^ (n >> 31);

/**
 * One vector tile with a layer "stress": four roads across it at capacities 40, 90, 150 and 300
 * riders a minute (one in each band) and one marked Avoid (tier 5), each with a `tier` and an `rpm`.
 */
export function capacityTile() {
  const keys = ["tier", "rpm"];
  const values = [];
  const valueIndex = (n) => {
    let i = values.indexOf(n);
    if (i < 0) {
      values.push(n);
      i = values.length - 1;
    }
    return i;
  };
  const roads = [
    { y: 600, tier: 3, rpm: 40 },
    { y: 1300, tier: 3, rpm: 90 },
    { y: 2000, tier: 2, rpm: 150 },
    { y: 2700, tier: 4, rpm: 300 },
    { y: 3400, tier: 5, rpm: 300 },
  ];
  const features = roads.map(({ y, tier, rpm }) => {
    const geometry = Buffer.concat([varint(9), varint(zigzag(0)), varint(zigzag(y)), varint(10), varint(zigzag(4096)), varint(zigzag(0))]);
    const tags = Buffer.concat([varint(0), varint(valueIndex(tier)), varint(1), varint(valueIndex(rpm))]);
    return Buffer.concat([bytesField(2, tags), uint(3, 2), bytesField(4, geometry)]);
  });
  const layer = Buffer.concat([
    uint(15, 2),
    bytesField(1, Buffer.from("stress")),
    ...features.map((f) => bytesField(2, f)),
    ...keys.map((k) => bytesField(3, Buffer.from(k))),
    ...values.map((v) => bytesField(4, uint(4, v))),
    uint(5, 4096),
  ]);
  return bytesField(3, layer);
}

export async function axNode(page, selector) {
  const { root } = await page.s("DOM.getDocument", { depth: 0 });
  const { nodeId } = await page.s("DOM.querySelector", { nodeId: root.nodeId, selector });
  if (!nodeId) return null;
  const { nodes } = await page.s("Accessibility.getPartialAXTree", { nodeId, fetchRelatives: false });
  const n = nodes[0];
  const prop = (name) => n.properties?.find((q) => q.name === name)?.value?.value;
  return {
    role: n.role?.value,
    name: n.name?.value,
    description: n.description?.value,
    expanded: prop("expanded"),
    checked: prop("checked") === "true" ? true : prop("checked") === "false" ? false : prop("checked"),
    disabled: prop("disabled"),
    /** Left out of the accessibility tree (aria-hidden, display: none and the like). */
    ignored: n.ignored === true,
    valuetext: prop("valuetext"),
  };
}

/** Decode an 8-bit RGB(A) PNG, as CDP's screenshots are: { width, height, pixel(x, y) -> [r, g, b] }. */
export function decodePng(buffer) {
  let at = 8;
  let width = 0;
  let height = 0;
  let channels = 4;
  const idat = [];
  while (at < buffer.length) {
    const length = buffer.readUInt32BE(at);
    const type = buffer.toString("ascii", at + 4, at + 8);
    const data = buffer.subarray(at + 8, at + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      channels = data[9] === 6 ? 4 : 3;
      if (data[8] !== 8 || (data[9] !== 6 && data[9] !== 2)) throw new Error("only 8-bit RGB(A) PNGs");
    } else if (type === "IDAT") idat.push(data);
    at += 12 + length;
  }
  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const out = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x++) {
      const left = x >= channels ? out[y * stride + x - channels] : 0;
      const up = y > 0 ? out[(y - 1) * stride + x] : 0;
      const upLeft = y > 0 && x >= channels ? out[(y - 1) * stride + x - channels] : 0;
      let value = line[x];
      if (filter === 1) value += left;
      else if (filter === 2) value += up;
      else if (filter === 3) value += (left + up) >> 1;
      else if (filter === 4) {
        const p = left + up - upLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - up);
        const pc = Math.abs(p - upLeft);
        value += pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft;
      }
      out[y * stride + x] = value & 0xff;
    }
  }
  return {
    width,
    height,
    pixel: (x, y) => {
      const i = y * stride + x * channels;
      return [out[i], out[i + 1], out[i + 2]];
    },
  };
}

const channel = (c) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
};
export const luminance = ([r, g, b]) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
export const contrast = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

// ---- The mock routes: the shape of a RouteResponse (frontend/src/lib/api.ts), not real plans ----
const coords = [];
for (let i = 0; i <= 40; i++) coords.push([-77.04 + i * 0.00075, 38.91 - i * 0.0005]);
/**
 * The route chart's profile (core.api.ProfileOut; OWNER-DECISIONS 322, 323, 328, 333) for a route of `distance`
 * metres: a gentle rise, a climb from 1,800 m to 2,100 m (6%, with a 9% pitch in its last 90 m), a plateau, then a 4% descent. With `mass`, the riders
 * a minute (a pinch at the start, 90 on the climb, none on a stretch marked Avoid from 3,540 m to 4,140 m, 190 elsewhere) and seven major
 * intersections (OWNER-DECISIONS 396: each crosses or joins a road of LTS 3 or higher, or is flagged; 13th Street
 * one-way, so it takes one corker). The level figure is a 22 ft (6.7 m) road's everywhere but the Avoid stretch, so a
 * 500-rider group is about 1,560 ft (474 m) long (PLAN's worked example).
 */
const profileFor = (distance, mass = false) => {
  const n = Math.floor(distance / 30) + 1;
  const m = Array.from({ length: n }, (_, i) => i * 30);
  const height = (d) => (d < 1800 ? 100 + 0.002 * d : d < 2010 ? 103.6 + 0.06 * (d - 1800) : d < 2100 ? 116.2 + 0.09 * (d - 2010) : d < 3200 ? 124.3 : d < 3500 ? 124.3 - 0.04 * (d - 3200) : 112.3);
  const grade = (d) => (d < 1800 ? 0.2 : d <= 2010 ? 6 : d <= 2100 ? 9 : d < 3200 ? 0 : d <= 3500 ? -4 : 0);
  const avoid = (d) => d >= 3540 && d <= 4140;
  const riders = (d) => (avoid(d) ? null : d < 200 ? 55 : d >= 1800 && d <= 2100 ? 90 : 190);
  const crossing = (at, street, severity, control, tier, corkers, kind = "flagged", oneway = null) => ({ m: at, street, severity, control, lanes: 2, crossed_tier: tier, kind, corkers_needed: corkers, oneway });
  return {
    interval_m: 30,
    m,
    elevation_m: m.map((d) => Math.round(height(d) * 10) / 10),
    grade_pct: m.map(grade),
    climbs: [{ from_m: 1800, to_m: 2100, gain_m: 20.7, avg_grade_pct: 6.9, max_grade_pct: 9, tier: 2, ...(mass ? { capacity_drop_pct: 53, min_riders_per_min: 90 } : {}) }],
    riders_per_min: mass ? m.map(riders) : null,
    level_riders_per_min: mass ? m.map((d) => (avoid(d) ? null : 198)) : null,
    flow: mass ? { narrowest_riders_per_min: 55, narrowest_m: 0, typical_riders_per_min: 190, cruise_pace_ms: 3.1293, default_level_riders_per_min: 197.98 } : null,
    avoid: mass ? [{ from_m: 3540, to_m: 4140 }] : null,
    unchecked: mass ? [] : null,
    crossings: mass
      ? [
          crossing(1000, "18th Street Northwest", "orange", "none", 3, true),
          crossing(1700, "17th Street Northwest", "orange", "signal", 3, true),
          crossing(2100, "15th Street Northwest", "red", "signal", 4, true),
          crossing(2500, "14th Street Northwest", "orange", "signal", 3, true),
          crossing(2900, "13th Street Northwest", "orange", "signal", 3, true, "flagged", true),
          crossing(3300, "Pierce Street", null, "cross_stop", 3, true, "crossing"),
          crossing(4000, "9th Street Northwest", "red", "none", 4, true),
        ]
      : null,
    // Off a Mass Ride, the rolling stress score (OWNER-DECISIONS 460.12, 461d): quiet, a rise over the
    // mile around the junctions at 2,000 and 3,000 m, an Avoid stretch, so the chart draws all three bands.
    calm: mass
      ? null
      : {
          window_m: 1609,
          ratio: m.map((d) => (d < 1200 ? 0.6 : d < 2400 ? 1.8 : d < 3600 ? 11.5 : 3.1)),
          steps: [
            { from_m: 0, to_m: 900, ratio: 0.54, tier: 1 },
            { from_m: 900, to_m: 3200, ratio: 0.95, tier: 2 },
            { from_m: 3200, to_m: 3300, ratio: 14.34, tier: 5 },
            { from_m: 3300, to_m: distance, ratio: 0.95, tier: 2 },
          ],
          points: [
            { m: 2000, calm_m: 91, kind: "junction", severity: "orange" },
            { m: 3000, calm_m: 274, kind: "junction", severity: "red" },
            { m: 3200, calm_m: 4091, kind: "avoid_entry", severity: null },
          ],
          total_calm_m: 9200,
          rated_m: distance,
          junctions_counted: true,
          bands: [2.67, 9.34],
          estimate: false,
        },
  };
};
const BASE = {
  preset: "default",
  variant: "standard",
  geometry: { type: "LineString", coordinates: coords },
  distance_m: 4660,
  duration_s: 1836,
  climb_m: 12,
  descent_m: 20,
  stress_m: { 1: 900, 2: 1660, 3: 800, 4: 800, 5: 500, unknown: 0 },
  facility_m: { path: 900, protected: 660, lane: 1000, none: 2100, unknown: 0 },
  attribution: ["© OpenStreetMap contributors, ODbL"],
  leg_ends: [40],
  stress_spans: [
    { from_m: 0, to_m: 900, tier: 1, facility: "path" },
    { from_m: 900, to_m: 4660, tier: 2, facility: "lane" },
  ],
  profile: profileFor(4660),
  // One orange, then two reds 10 m apart: a group when zoomed out.
  intersections: [
    { m: 2000, lon: coords[17][0], lat: coords[17][1], severity: "orange", reason: "Left turn across a 4-lane 35 mph (56 km/h) road, signal", crossed_tier: 3, movement: "left", control: "signal", kind: "left_turn", cost_ft: 300 },
    { m: 3000, lon: coords[26][0], lat: coords[26][1], severity: "red", reason: "Straight across a 6-lane 40 mph (64 km/h) road, no signal", crossed_tier: 4, movement: "straight", control: "none", kind: "crossing", cost_ft: 900 },
    { m: 3010, lon: coords[26][0] + 0.00005, lat: coords[26][1], severity: "red", reason: "Right turn onto a 6-lane road", crossed_tier: 4, movement: "right", control: "none", kind: "turn", cost_ft: 600 },
  ],
  calm_search: null,
  detour: null,
};
const copy = () => JSON.parse(JSON.stringify(BASE));

/** A description entry (frontend/src/lib/api.ts DescriptionEntry), worded as the API words them. */
const entry = (kind, from_m, to_m, text, extra = {}) => ({
  kind, from_m, to_m, from_mi: +(from_m / 1609.344).toFixed(2), to_mi: +(to_m / 1609.344).toFixed(2),
  street: null, tier: null, facility: null, turn: null, severity: null, via: null, group: null, text, ...extra,
});
const STREETS = ["Old Georgetown Road", "Woodmont Avenue Cycletrack", "Capital Crescent Trail", "Leland Street", "Bethesda Avenue", "Custis Trail", "Water Street Northwest"];
/** Fourteen entries in full, eleven in the overview: longer than the old 20rem scroll box. */
const TRAIL_FULL = Array.from({ length: 14 }, (_, i) =>
  entry("stretch", i * 800, (i + 1) * 800,
    `${(i * 0.5).toFixed(1)} to ${(i * 0.5 + 0.5).toFixed(1)} mi (${(i * 0.8).toFixed(1)} to ${(i * 0.8 + 0.8).toFixed(1)} km): ` +
      `${i % 2 ? "Right onto" : "Left onto"} ${STREETS[i % STREETS.length]}, then ${STREETS[(i + 3) % STREETS.length]}, ` +
      `${i % 3 ? "traffic-free path" : "busy road (LTS 3)"}.`));
const TRAIL_OVERVIEW = TRAIL_FULL.slice(0, 11);

/** Trailmaxxing at the top: a strong detour, the calm search cut short by time. */
export const S_TRAIL = (() => {
  const r = copy();
  r.preset = "trailmaxxing";
  r.distance_m = 11200;
  r.duration_s = 2900;
  r.dials = { stress: 100, hills: 0, when: "weekday", carrying: null };
  r.calm_search = { rate: 10, rounds: 4, excluded: 7, limited: "time" };
  r.detour = { basis: "direct_route", reference_m: 4660, ratio: 2.4, extra_m: 6540, level: "strong", avoided_m: 1800 };
  r.description = TRAIL_FULL;
  r.description_overview = TRAIL_OVERVIEW;
  return r;
})();
/**
 * Trailmaxxing at the top with two more routes to choose from (OWNER-DECISIONS 265): each a
 * whole route body with its rank, the answer's own marked 1.
 */
export const S_CHOICES = (() => {
  const r = JSON.parse(JSON.stringify(S_TRAIL));
  r.effort_m = 13000;
  r.rank = 1;
  const other = (rank, distance, lts3) => {
    const c = JSON.parse(JSON.stringify(S_TRAIL));
    c.rank = rank;
    c.distance_m = distance;
    c.effort_m = distance * 1.1;
    c.stress_m = { ...c.stress_m, 3: lts3 };
    delete c.candidates;
    return c;
  };
  r.candidates = [other(2, 11600, 900), other(3, 12100, 1000)];
  return r;
})();
/**
 * Trailmaxxing past the rider's target distance (OWNER-DECISIONS 271): the extra miles
 * avoided enough busy road, so the route is 0.7 mi over a 6.2 mi target, and it says so.
 */
export const S_OVER = (() => {
  const r = JSON.parse(JSON.stringify(S_TRAIL));
  r.dials = { ...r.dials, target_distance_m: 10_000 };
  r.calm_search = {
    rate: 10,
    rounds: 4,
    excluded: 7,
    limited: null,
    target_distance_m: 10_000,
    target_distance_set: true,
    ceiling_m: 12_500,
    fits: false,
    over_target_m: 1_200,
  };
  return r;
})();
/** The default ride, no detour. */
export const S_DEFAULT = (() => {
  const r = copy();
  r.dials = { stress: 70, hills: 0, when: "weekday", carrying: null };
  r.calm_search = { rate: 0, rounds: 0, excluded: 0, limited: null };
  return r;
})();
/** Riding with kids (FOLLOWUP-KIDS-PRESET, OWNER-DECISIONS 240 (B)): the top of the traffic slider, hills toward avoid. */
export const S_KIDS = (() => {
  const r = copy();
  r.preset = "kids";
  r.dials = { stress: 100, hills: -80, when: "weekday", carrying: null };
  r.calm_search = { rate: 10, rounds: 2, excluded: 3, limited: null };
  return r;
})();
/**
 * A Mass Ride with a group of signalized crossings (OWNER-DECISIONS 233, 234): a lone
 * unsignalized left, four signalized crossings within a quarter mile of one another (one red),
 * then a lone unsignalized red. The group's row opens onto its four crossings.
 */
export const S_MASS = (() => {
  const r = copy();
  r.preset = "mass-ride";
  r.dials = { stress: 0, hills: 0, when: "weekday", carrying: null };
  r.calm_search = null;
  r.profile = profileFor(4660, true);
  const at = (i, m, severity, tier, control, kind, reason, group) => ({
    m, lon: coords[i][0], lat: coords[i][1], severity, reason, crossed_tier: tier, movement: "straight", control, kind, cost_ft: 300, group,
  });
  r.intersections = [
    at(8, 1000, "orange", 3, "none", "left_across", "Left turn across a 2-lane 30 mph (48 km/h) road, no signal mapped", null),
    at(14, 1700, "orange", 3, "signal", "crossing", "Crossing a 2-lane 30 mph (48 km/h) road, traffic signal", 1),
    at(17, 2100, "red", 4, "signal", "crossing", "Crossing a 4-lane 35 mph (56 km/h) road, traffic signal", 1),
    at(20, 2500, "orange", 3, "signal", "crossing", "Crossing a 2-lane 30 mph (48 km/h) road, traffic signal", 1),
    at(23, 2900, "orange", 3, "signal", "crossing", "Crossing a 2-lane 25 mph (40 km/h) road, traffic signal", 1),
    at(34, 4000, "red", 4, "none", "crossing", "Crossing a 4-lane 40 mph (64 km/h) road, no signal mapped", null),
  ];
  r.intersection_groups = [
    {
      group: 1,
      from_m: 1700,
      to_m: 2900,
      count: 4,
      lts4: 1,
      streets: ["17th Street Northwest", "15th Street Northwest", "14th Street Northwest"],
      more: 1,
      severity: "red",
      members: [1, 2, 3, 4],
      text: "1.1 to 1.8 mi (1.7 to 2.9 km): 4 crossings with traffic signals (17th Street Northwest, 15th Street Northwest, 14th Street Northwest and 1 more), 1 of them a heavy-traffic road (LTS 4)",
    },
  ];
  // The description (OWNER-DECISIONS 220, 248): the group is one entry; in full detail
  // it lists its four crossings with their mile markers, in the overview it does not.
  const streets = ["17th Street Northwest", "15th Street Northwest", "14th Street Northwest", "13th Street Northwest"];
  const crossings = [1700, 2100, 2500, 2900].map((m, k) => ({
    from_m: m, from_mi: +(m / 1609.344).toFixed(2), street: streets[k], severity: k === 1 ? "red" : "orange", crossed_tier: k === 1 ? 4 : 3,
    text: `At ${(m / 1609.344).toFixed(1)} mi (${(m / 1000).toFixed(1)} km): Cross ${streets[k]} (LTS ${k === 1 ? 4 : 3}) at a signal (${k === 1 ? "Very high" : "Higher"} stress junction).`,
  }));
  const group = (withCrossings) => entry("junction", 1700, 2900, `${r.intersection_groups[0].text} (Very high stress junctions).`, {
    severity: "red",
    group: { number: 1, count: 4, lts4: 1, streets: streets.slice(0, 3), more: 1, crossings: withCrossings ? crossings : null },
  });
  const head = [
    entry("stretch", 0, 600, "0.0 to 0.4 mi (0.0 to 0.6 km): Constitution Avenue Northwest, heavy traffic (LTS 4).", { tier: 4 }),
    entry("stretch", 600, 900, "0.4 to 0.6 mi (0.6 to 0.9 km): Continue on Constitution Avenue Northwest, busy road (LTS 3).", { tier: 3 }),
    entry("junction", 1000, 1000, "At 0.6 mi (1.0 km): Left turn across 18th Street Northwest (LTS 3), no signal mapped (Higher stress junction).", { severity: "orange" }),
  ];
  const tail = [entry("junction", 4000, 4000, "At 2.5 mi (4.0 km): Cross 9th Street Northwest (LTS 4), no signal mapped (Very high stress junction).", { severity: "red" })];
  r.description = [...head, group(true), ...tail];
  r.description_overview = [head[0], head[2], group(false), ...tail];
  return r;
})();
/**
 * A Mass Ride on a rebuilt table (OWNER-DECISIONS 325-327, 387): its sections carry riders per
 * minute, one in each band, and a stretch marked Avoid.
 */
export const S_MASS_CAPACITY = (() => {
  const r = JSON.parse(JSON.stringify(S_MASS));
  r.stress_spans = [
    { from_m: 0, to_m: 300, tier: 2, facility: "none", unpaved: null, rpm: 50 },
    { from_m: 300, to_m: 1500, tier: 3, facility: "none", unpaved: null, rpm: 90 },
    { from_m: 1500, to_m: 2700, tier: 3, facility: "none", unpaved: null, rpm: 190 },
    { from_m: 2700, to_m: 3400, tier: 4, facility: "none", unpaved: null, rpm: 590 },
    { from_m: 3400, to_m: 3600, tier: 5, facility: "none", unpaved: null, rpm: null },
    { from_m: 3600, to_m: 4660, tier: 2, facility: "none", unpaved: null, rpm: 150 },
  ];
  return r;
})();
/**
 * The same Mass Ride with its start across the Potomac in Rosslyn, Virginia: part of the route is
 * outside the District, which Mass Ride planning covers alone for now (OWNER-DECISIONS 418a).
 */
export const S_MASS_OUTSIDE_DC = (() => {
  const r = JSON.parse(JSON.stringify(S_MASS_CAPACITY));
  r.geometry.coordinates = [[-77.072, 38.896], ...r.geometry.coordinates];
  // 427: the API gives the part outside DC no figure, and says where it is.
  r.stress_spans[0] = { ...r.stress_spans[0], rpm: null, outside_dc: true };
  r.profile.outside_dc = [{ from_m: 0, to_m: 300 }];
  // The API never puts a narrowest point (either figure) in the outside part: with the hills it is in DC too.
  r.profile.flow = { ...r.profile.flow, narrowest_m: 600 };
  return r;
})();
/**
 * Ride mode (WEB-NAV-plan.md): the default route with a description to follow, a turn left onto R Street
 * Northwest at 1,000 m and a red crossing at 3,000 m; the line is the default one's (its measure is
 * scaled onto the line, as Ride mode does).
 */
export const S_RIDE = (() => {
  const r = copy();
  r.dials = { stress: 70, hills: 0, when: "weekday", carrying: null };
  r.calm_search = { rate: 0, rounds: 0, excluded: 0, limited: null };
  r.description = [
    entry("stretch", 0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): Q Street Northwest, low stress (LTS 1).", { street: "Q Street Northwest", tier: 1 }),
    entry("stretch", 1000, 4660, "0.6 to 2.9 mi (1.0 to 4.7 km): Left onto R Street Northwest at a signal, fairly low stress (LTS 2), painted bike lane.", {
      street: "R Street Northwest", tier: 2, facility: "lane",
      turn: { movement: "left", onto: "R Street Northwest", control: "signal", severity: null },
    }),
    entry("junction", 3000, 3000, "At 1.9 mi (3.0 km): Cross 14th Street Northwest (LTS 4), no signal mapped (Very high stress junction).", { severity: "red" }),
  ];
  r.description_overview = r.description;
  return r;
})();
/** The ride's line, for stepping a simulated GPS along it. */
export const RIDE_COORDS = coords;

export const hashFor = (preset, stress, hills = 0) =>
  `#p=-77.04000,38.91000;-77.01000,38.89000&preset=${preset}&v=2&stress=${stress}&hills=${hills}`;

/** The step words (core/segment_info.py TIER_WORDS; OWNER-DECISIONS 441l). */
export const STEP_WORDS = { 1: "Comfortable for everyone", 2: "Fine for adults", 3: "For experienced cyclists", 4: "High stress: busy, fast traffic", 5: "Avoid" };

/** The stress editor's starting state (GET /api/stress-edits/way/{id}), for the one road. */
export function editorState(road) {
  return {
    osm_way_id: 101,
    classifier_step: 3,
    can_raise_only: true,
    current: {
      step: road.tier, words: STEP_WORDS[road.tier], source: road.edit ? "panel" : "classifier", at_least: false,
      category: null, public_note: null, display: null, private_reason: null,
      when: road.edit ? new Date().toISOString() : null, by: road.edit ? "you" : null,
    },
    expected: `tok-${road.generation}`,
    steps: [1, 2, 3, 4, 5].map((value) => ({ value, words: STEP_WORDS[value] })),
    categories: [
      { id: "speed", label: "speed" }, { id: "road_conditions", label: "road conditions" }, { id: "driver_behaviour", label: "driver behaviour" },
      { id: "intersection", label: "an intersection" }, { id: "sightlines", label: "sightlines" },
      { id: "better_among_alternatives", label: "better than the alternatives nearby" }, { id: "other", label: "other" },
    ],
    reason_max: 500,
    note_max: 200,
    recent_edit: road.edit ? { id: road.edit, action: "set", at: new Date().toISOString(), can_undo: true } : null,
    pieces: 1,
  };
}

/** The road panel's answer at a level: the fixed road with its stress rows changed. */
export function segmentInfoAt(tier) {
  if (tier === 3) return S_SEGMENT_INFO;
  const info = JSON.parse(JSON.stringify(S_SEGMENT_INFO));
  info.tier = tier;
  info.summary.find((r) => r.id === "stress").value = tier === 5 ? "Avoid" : `LTS ${tier} \u00b7 ${STEP_WORDS[tier]}`;
  info.sections.find((x) => x.id === "stress").rows[0] = { label: "Level", value: tier === 5 ? "Avoid" : `LTS ${tier}: ${STEP_WORDS[tier]}`, source: "Owner override" };
  return info;
}
/**
 * A Bikeshare plan (FOLLOWUP-BIKESHARE): the route body is the ride between the docks, and
 * `bikeshare` has the walks, docks, availability, endings and notes. The words are the API's
 * (core.bikeshare); the source citation is core.gbfs.CREDIT.
 */
const BIKESHARE_CREDIT = "Capital Bikeshare";
const dockStop = (kind, name, at, bikes, docks) => ({
  kind, name, lon: at[0], lat: at[1], station_id: `fx-${name.length}`, availability: "known", bikes_available: bikes, docks_available: docks,
});
export const S_BIKESHARE = (() => {
  const r = copy();
  r.preset = "bikeshare";
  r.distance_m = 3400;
  r.duration_s = 940;
  r.dials = { stress: 80, hills: -60, when: "weekday", carrying: null, assist: false };
  r.calm_search = { rate: 0, rounds: 0, excluded: 0, limited: null };
  r.attribution = [...BASE.attribution, BIKESHARE_CREDIT];
  const start = coords[0];
  const end = coords[40];
  r.bikeshare = {
    bike: "classic",
    ending: "dock",
    start: dockStop("dock", "Columbus Circle / Union Station", start, 5, 40),
    end: dockStop("dock", "20th & O St NW / Dupont South", end, 0, 14),
    walk_start: { geometry: { type: "LineString", coordinates: [[start[0] - 0.001, start[1] + 0.0005], start] }, distance_m: 130, duration_s: 97, to: "Columbus Circle / Union Station" },
    walk_end: { geometry: { type: "LineString", coordinates: [end, [end[0] + 0.001, end[1] - 0.0005]] }, distance_m: 160, duration_s: 120, to: "your destination" },
    ride_m: 3400, ride_s: 940, walk_m: 290, walk_s: 217, total_s: 1157,
    availability: "live",
    endings: [{ kind: "dock", offered: true, chosen: true, reason: null, reason_text: null, fee: null, fee_text: null, walk_m: 160, text: "End at the dock at 20th & O St NW / Dupont South, then walk 520 ft (160 m) to your destination." }],
    pricing: [],
    pricing_note: null,
    steps: [
      { kind: "walk", text: "Walk 430 ft (130 m) to the dock at Columbus Circle / Union Station, take a classic bike (5 available)." },
      { kind: "ride", text: "Ride 2.1 mi (3.4 km) to the dock at 20th & O St NW / Dupont South (14 free slots)." },
      { kind: "walk", text: "Return the bike, then walk 520 ft (160 m) to your destination." },
    ],
    summary: "Bikeshare, classic bike: about 19 min in all. Walk 430 ft (130 m) to the dock at Columbus Circle / Union Station, take a classic bike (5 available). Ride 2.1 mi (3.4 km) to the dock at 20th & O St NW / Dupont South (14 free slots). Return the bike, then walk 520 ft (160 m) to your destination.",
    notes: ["The nearest dock, Union Station Plaza, 0.1 mi (0.2 km) away, has no classic bikes right now; the plan uses a farther one."],
    credit: BIKESHARE_CREDIT,
  };
  return r;
})();
/** The same on an e-bike, with the out-of-dock ending on offer beside the dock (zones read, a fee in the data). */
export const S_BIKESHARE_EBIKE = (() => {
  const r = JSON.parse(JSON.stringify(S_BIKESHARE));
  r.dials = { ...r.dials, hills: -20, assist: true };
  r.bikeshare.bike = "ebike";
  r.bikeshare.endings.push({
    kind: "outside_dock", offered: true, chosen: false, reason: null, reason_text: null,
    fee: { name: "Out-of-dock fee", price: "2.00", currency: "USD", description: "Leaving an e-bike outside a dock costs 2.00 USD." },
    fee_text: "The operator's data lists Out-of-dock fee: 2.00 USD. Leaving an e-bike outside a dock costs 2.00 USD.",
    walk_m: null, text: "End at your destination, outside a dock. The operator's data lists Out-of-dock fee: 2.00 USD.",
  });
  return r;
})();

/**
 * The nearest-stations answers (POST /api/bikeshare/stations, core/api.py NearbyStationsOut):
 * three stations at least 3/4 full to pick up from, three at most 1/4 full to return to.
 */
const station = (id, name, lon, lat, percent, metres, bikes, docks) => ({
  station_id: id, name, lon, lat, percent_full: percent, distance_m: metres, bikes, ebikes: 1, docks,
});
export const S_STATIONS_PICKUP = {
  action: "pickup",
  availability: "live",
  credit: "Capital Bikeshare",
  stations: [
    station("fx-001", "Columbus Circle / Union Station", -77.0063, 38.8973, 82, 320, 9, 2),
    station("fx-002", "Union Station Plaza", -77.0058, 38.8979, 78, 450, 7, 2),
    station("fx-003", "Massachusetts Ave & 2nd St NE", -77.0042, 38.8981, 76, 1500, 13, 4),
  ],
};
export const S_STATIONS_DROPOFF = {
  action: "dropoff",
  availability: "live",
  credit: "Capital Bikeshare",
  stations: [
    station("fx-011", "20th & O St NW / Dupont South", -77.0436, 38.9096, 10, 150, 1, 9),
    station("fx-012", "Dupont Circle", -77.0431, 38.9101, 25, 400, 3, 9),
    station("fx-013", "Connecticut Ave & R St NW", -77.0442, 38.9111, 0, 1100, 0, 11),
  ],
};

/** The road panel's answer (GET /api/segment-info), as core/segment_info.py writes it. */
export const S_SEGMENT_INFO = {
  found: true,
  title: "Connecticut Avenue Northwest",
  tier: 3,
  open: true,
  osm_way_id: 101,
  distance_m: 2.4,
  // The nearest point on the way: the Street View link opens here (OWNER-DECISIONS 441o).
  on_way: [-77.04, 38.91],
  kind: "Main road",
  summary: [
    { id: "stress", label: "Traffic stress", value: "LTS 3 · For experienced cyclists" },
    { id: "why", label: "Why", value: "30 mph, mixed traffic" },
    { id: "speed", label: "Speed", value: "30 mph (48 km/h), posted" },
    { id: "lanes", label: "Lanes", value: "2 each way" },
    { id: "traffic", label: "Traffic", value: "18,400 a day (DDOT 2024)" },
    { id: "bike_lane", label: "Bike lane", value: "Painted" },
    { id: "bikes", label: "Bikes", value: "Allowed" },
    { id: "mass", label: "Room for", value: "About 150 riders a minute" },
  ],
  attribution: ["© OpenStreetMap contributors (ODbL)"],
  sections: [
    { id: "road", heading: "Road or path", rows: [
      { label: "Name", value: "Connecticut Avenue Northwest", source: "OpenStreetMap, through RouteMaker's routing graph" },
      { label: "Kind", value: "Main road", source: "OpenStreetMap, through RouteMaker's routing graph" },
    ] },
    { id: "stress", heading: "Traffic stress", rows: [
      { label: "Level", value: "LTS 3: For experienced cyclists", source: "RouteMaker classifier" },
      { label: "Why", value: "30 mph, mixed traffic, several lanes, city street", source: "RouteMaker classifier" },
    ] },
    { id: "traffic", heading: "Traffic", rows: [
      { label: "Lanes", value: "2 each way", source: "OpenStreetMap" },
      { label: "Speed limit", value: "30 mph (48 km/h), posted", source: "DC Roadway Block (DDOT / DC GIS), DC Open Data (CC BY 4.0, adapted)" },
      { label: "Traffic volume", value: "18,400 vehicles a day (annual average), 2024 count", source: "DDOT 2024 Traffic Volume, DC Open Data (CC BY 4.0, adapted)" },
    ] },
    { id: "riding", heading: "Riding", rows: [
      { label: "Bike facility", value: "Painted bike lane", source: "OpenStreetMap" },
      { label: "Surface", value: "Paved", source: "OpenStreetMap" },
    ] },
    { id: "access", heading: "Bike access", rows: [{ label: "Bike access", value: "Open to bicycles", source: "OpenStreetMap, through RouteMaker's routing graph" }] },
    { id: "mass", heading: "Mass Ride capacity", rows: [
      { label: "Usable width", value: "22 ft (6.7 m)", source: "RouteMaker Mass Ride model" },
      { label: "Riders a minute", value: "About 150 on the level", source: "RouteMaker Mass Ride model" },
    ] },
  ],
};
