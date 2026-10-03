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

/** Answer /api, /tiles, /basemap and /auth here; `route` may be a function of the request count. */
export async function mock(page, route) {
  page.routeRequests = 0;
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
    if (url.pathname.startsWith("/tiles/stress/")) {
      status = 200;
      type = "application/x-protobuf";
    } else if (url.pathname === "/api/route" && request.method === "POST") {
      page.routeRequests += 1;
      status = 200;
      body = JSON.stringify(typeof route === "function" ? route(page.routeRequests) : route);
      type = "application/json";
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

export async function axNode(page, selector) {
  const { root } = await page.s("DOM.getDocument", { depth: 0 });
  const { nodeId } = await page.s("DOM.querySelector", { nodeId: root.nodeId, selector });
  if (!nodeId) return null;
  const { nodes } = await page.s("Accessibility.getPartialAXTree", { nodeId, fetchRelatives: false });
  const n = nodes[0];
  return { role: n.role?.value, name: n.name?.value, description: n.description?.value };
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

/** Trailmaxxing at the top: a strong detour, the calm search cut short by time. */
export const S_TRAIL = (() => {
  const r = copy();
  r.preset = "trailmaxxing";
  r.distance_m = 11200;
  r.duration_s = 2900;
  r.dials = { stress: 100, hills: 0, when: "weekday", carrying: null };
  r.calm_search = { rate: 10, rounds: 4, excluded: 7, limited: "time", trail_credit: 1.5 };
  r.detour = { basis: "direct_route", reference_m: 4660, ratio: 2.4, extra_m: 6540, level: "strong", avoided_m: 1800 };
  return r;
})();
/** The default ride, no detour. */
export const S_DEFAULT = (() => {
  const r = copy();
  r.dials = { stress: 70, hills: 0, when: "weekday", carrying: null };
  r.calm_search = { rate: 0, rounds: 0, excluded: 0, limited: null };
  return r;
})();
export const hashFor = (preset, stress, hills = 0) =>
  `#p=-77.04000,38.91000;-77.01000,38.89000&preset=${preset}&v=2&stress=${stress}&hills=${hills}`;
