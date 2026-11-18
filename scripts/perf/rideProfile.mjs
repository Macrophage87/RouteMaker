// Ride on a cheap phone: which components re-render on each GPS fix, and how much main-thread time a fix costs.
// The a11y check's mocked API and ride line (scripts/a11y/cdp.mjs), a phone-sized page, the CPU slowed 4x (a
// mid-range Android against a laptop, as Lighthouse's mobile run does), a fix a second along the line, then the
// same time with no fix (the ride's clocks alone).
//
//   (in frontend/) node node_modules/vite/bin/vite.js build --config scripts/vite.profile.mjs
//   (in frontend/) node node_modules/vite/bin/vite.js preview --config scripts/vite.profile.mjs --port 4174 &
//   chromium --headless=new --remote-debugging-port=9222 &
//   node scripts/perf/rideProfile.mjs [--port 4174] [--fixes 120] [--throttle 4] [--lone-failures] [--why] [--cpu] [--json out.json]
//
// It lists each component's renders and own time per second of riding, and the main thread's time. Under the dev
// server React's dev build names the components but is several times slower than a rider's; frontend/scripts/
// vite.profile.mjs builds the production React with its timers on and names kept, the one to measure. --why lists
// which of App's and RideMode's state and props changed; --cpu the functions the time goes to. Nothing leaves the
// page: the API, tiles and base map are mocked.
import { writeFileSync } from "node:fs";
import { RIDE_COORDS, S_RIDE, connect, hashFor, media, mock, newPage, sleep } from "../a11y/cdp.mjs";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const PORT = Number(arg("--port", "5173"));
const FIXES = Number(arg("--fixes", "120"));
const THROTTLE = Number(arg("--throttle", "4"));
const OUT = arg("--json", null);
const ORIGIN = `http://127.0.0.1:${PORT}`;

// A stand-in for React DevTools: on each commit, every function component that rendered (mounted, or did work
// this commit) is counted with its own time. Subtrees React skipped whole are not walked.
const HOOK = `(() => {
  const counts = new Map();
  const why = new Map();
  let commits = 0;
  const preview = (v) => { try { if (v === null || typeof v !== 'object') return String(v).slice(0, 60); if (Array.isArray(v)) return 'array ' + v.length; return '{' + Object.keys(v).slice(0, 6).join(',') + '}'; } catch { return '?'; } };
  // Which of a component's hooks changed since its last render (the state's index in call order and a glimpse of it).
  const changed = (f, n) => {
    if (!f.alternate) return;
    let a = f.memoizedState, b = f.alternate.memoizedState, i = 0;
    while (a && b) {
      if (a.queue && a.memoizedState !== b.memoizedState) {
        const k = n + ' state#' + i + ' ' + preview(a.memoizedState);
        why.set(k, (why.get(k) || 0) + 1);
      }
      a = a.next; b = b.next; i++;
    }
    if (f.memoizedProps !== f.alternate.memoizedProps && f.alternate.memoizedProps) {
      for (const key of Object.keys(f.memoizedProps)) if (f.memoizedProps[key] !== f.alternate.memoizedProps[key]) { const k = n + ' prop ' + key; why.set(k, (why.get(k) || 0) + 1); }
    }
  };
  const nameOf = (f) => {
    const t = f.type;
    if (!t) return null;
    if (typeof t === "function") return t.displayName || t.name || "Anonymous";
    if (t.render) return t.displayName || t.render.displayName || t.render.name || "ForwardRef";
    if (t.type) return t.displayName || t.type.displayName || t.type.name || "Memo";
    return null;
  };
  const walk = (f) => {
    while (f) {
      if ([0, 1, 11, 14, 15].includes(f.tag)) {
        const rendered = !f.alternate || (f.flags & 1) === 1;
        if (rendered) {
          const n = nameOf(f);
          if (n) {
            const c = counts.get(n) || { renders: 0, selfMs: 0 };
            c.renders += 1;
            c.selfMs += f.selfBaseDuration || 0;
            counts.set(n, c);
            if (n === 'App' || n === 'RideMode') changed(f, n);
          }
        }
      }
      if (f.child && !(f.alternate && f.alternate.child === f.child)) walk(f.child);
      f = f.sibling;
    }
  };
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    renderers: new Map(), supportsFiber: true, isDisabled: false,
    inject(r) { this.renderers.set(1, r); return 1; },
    checkDCE() {}, onScheduleFiberRoot() {}, onCommitFiberUnmount() {}, onPostCommitFiberRoot() {}, setStrictMode() {},
    onCommitFiberRoot(_id, root) { commits += 1; walk(root.current.child); },
  };
  window.__renders = { reset() { counts.clear(); why.clear(); commits = 0; }, read() { return { commits, why: [...why].sort((x, y) => y[1] - x[1]).slice(0, 40), rows: [...counts].map(([name, c]) => ({ name, ...c })) }; } };
})()`;

const b = await connect();
const p = await newPage(b, { width: 390, height: 844, mobile: true });
await p.s("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
await mock(p, S_RIDE);
await media(p, { scheme: "light" });
await b.send("Browser.setPermission", { permission: { name: "geolocation" }, setting: "granted", origin: ORIGIN, browserContextId: p.contextId });
const [lon0, lat0] = RIDE_COORDS[0];
await p.s("Emulation.setGeolocationOverride", { latitude: lat0, longitude: lon0, accuracy: 5 });
await p.s("Page.addScriptToEvaluateOnNewDocument", { source: HOOK });
// The phone's GPS, played by the page: window.__fix(lat, lon) hands every watch a fix. With --lone-failures, Chromium's
// own location override instead, which sends a failure between fixes each time it is moved, as a patchy GPS does.
const LONE = process.argv.includes("--lone-failures");
if (!LONE) await p.s("Page.addScriptToEvaluateOnNewDocument", {
  source: `(() => {
    let last = { latitude: ${lat0}, longitude: ${lon0}, accuracy: 5, speed: null, heading: null };
    const watches = new Map();
    let n = 0;
    const position = () => ({ coords: { ...last, altitude: null, altitudeAccuracy: null }, timestamp: Date.now() });
    const geo = {
      getCurrentPosition(ok) { setTimeout(() => ok(position()), 50); },
      watchPosition(ok) { n += 1; watches.set(n, ok); setTimeout(() => ok(position()), 50); return n; },
      clearWatch(id) { watches.delete(id); },
    };
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: geo });
    window.__fix = (latitude, longitude, speed, heading) => { last = { latitude, longitude, accuracy: 5, speed, heading }; for (const ok of watches.values()) ok(position()); };
  })()`,
});
await p.s("Page.addScriptToEvaluateOnNewDocument", {
  source: `(() => {
    const synth = { speaking: false, speak() {}, cancel() {} };
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: synth });
    window.SpeechSynthesisUtterance = function (text) { this.text = text; };
    Object.defineProperty(navigator, 'wakeLock', { configurable: true, value: { request: async () => ({ released: false, release: async () => {} }) } });
    try { sessionStorage.setItem('routemaker.tab-mode', 'plan'); localStorage.setItem('routemaker.ride', '{"output":"both","verbosity":"full","chosen":true}'); } catch {}
  })()`,
});
await p.s("Page.navigate", { url: `${ORIGIN}/${hashFor("default", 70)}` });
if (!(await p.waitFor("!!document.querySelector('.start-ride button')", 60000))) throw new Error("no Start ride button");
await p.eval("document.querySelector('.start-ride button').click(); true");
if (!(await p.waitFor("!!document.querySelector('section.ride')", 20000))) throw new Error("the ride did not start");
await sleep(3000);
await p.s("Performance.enable");
await p.s("Emulation.setCPUThrottlingRate", { rate: THROTTLE });

// The line's length, then a point every `step` metres along it (about 6 m/s, 13 mph).
const R = 6371000;
const rad = (d) => (d * Math.PI) / 180;
const metres = ([a, b], [c, d]) => R * Math.hypot(rad(c - a) * Math.cos(rad((b + d) / 2)), rad(d - b));
function along(m) {
  for (let i = 1; i < RIDE_COORDS.length; i++) {
    const seg = metres(RIDE_COORDS[i - 1], RIDE_COORDS[i]);
    if (m <= seg) {
      const t = m / seg;
      return [RIDE_COORDS[i - 1][0] + (RIDE_COORDS[i][0] - RIDE_COORDS[i - 1][0]) * t, RIDE_COORDS[i - 1][1] + (RIDE_COORDS[i][1] - RIDE_COORDS[i - 1][1]) * t];
    }
    m -= seg;
  }
  return RIDE_COORDS.at(-1);
}
const metrics = async () => Object.fromEntries((await p.s("Performance.getMetrics")).metrics.map((m) => [m.name, m.value]));

const CPU = process.argv.includes("--cpu");
async function phase(label, moving) {
  await p.eval("window.__renders.reset(); true");
  if (CPU) {
    await p.s("Profiler.enable");
    await p.s("Profiler.setSamplingInterval", { interval: 500 });
    await p.s("Profiler.start");
  }
  const before = await metrics();
  const t0 = Date.now();
  for (let i = 0; i < FIXES; i++) {
    if (moving) {
      const [lon, lat] = along(20 + i * 6);
      if (LONE) await p.s("Emulation.setGeolocationOverride", { latitude: lat, longitude: lon, accuracy: 5 });
      else await p.eval(`window.__fix(${lat}, ${lon}, 6, null); true`);
    }
    await sleep(Math.max(0, t0 + (i + 1) * 1000 - Date.now()));
  }
  const after = await metrics();
  const r = await p.eval("window.__renders.read()");
  let hot = [];
  if (CPU) {
    // Self time by function, from the sampled profile: where the main thread's time goes.
    const { profile } = await p.s("Profiler.stop");
    const self = new Map();
    const byId = new Map(profile.nodes.map((n) => [n.id, n]));
    const dt = new Map();
    profile.samples.forEach((id, i) => dt.set(id, (dt.get(id) || 0) + (profile.timeDeltas[i] || 0)));
    for (const [id, us] of dt) {
      const f = byId.get(id).callFrame;
      const k = `${f.functionName || "(anon)"} ${f.url.replace(/^.*\/(src|deps)\//, "$1/").replace(/\?.*$/, "")}:${f.lineNumber + 1}`;
      self.set(k, (self.get(k) || 0) + us / 1000);
    }
    hot = [...self].sort((a, b) => b[1] - a[1]).slice(0, 40).map(([k, ms]) => ({ fn: k, msPerSecond: ms / FIXES }));
    // Who calls the browser's own costly calls (a forced layout, a style read): the frames above them, by time.
    const parent = new Map();
    for (const n of profile.nodes) for (const c of n.children || []) parent.set(c, n.id);
    const callers = new Map();
    for (const [id, us] of dt) {
      const f = byId.get(id).callFrame;
      if (!/^(getBoundingClientRect|getComputedStyle|offsetHeight|offsetWidth|measure|querySelectorAll|matchMedia)$/.test(f.functionName)) continue;
      const chain = [];
      for (let up = parent.get(id); up && chain.length < 4; up = parent.get(up)) {
        const g = byId.get(up).callFrame;
        chain.push(`${g.functionName || "(anon)"}@${g.url.replace(/^.*\//, "").replace(/\?.*$/, "")}:${g.lineNumber + 1}`);
      }
      const k = `${f.functionName} <- ${chain.join(" <- ")}`;
      callers.set(k, (callers.get(k) || 0) + us / 1000);
    }
    for (const [k, ms] of [...callers].sort((a, b) => b[1] - a[1]).slice(0, 12)) hot.push({ fn: "caller " + k, msPerSecond: ms / FIXES });
  }
  const per = (k) => (1000 * (after[k] - before[k])) / FIXES;
  return {
    label,
    msPerSecond: { task: per("TaskDuration"), script: per("ScriptDuration"), layout: per("LayoutDuration"), style: per("RecalcStyleDuration") },
    commitsPerSecond: r.commits / FIXES,
    why: r.why,
    hot,
    rows: r.rows.map((x) => ({ name: x.name, perSecond: x.renders / FIXES, selfMsPerSecond: x.selfMs / FIXES })).sort((a, b) => b.selfMsPerSecond - a.selfMsPerSecond),
  };
}

const ride = await phase("a fix a second", true);
const still = await phase("no fix (clocks alone)", false);
await p.s("Emulation.setCPUThrottlingRate", { rate: 1 });
await p.close();
b.close();

for (const ph of [ride, still]) {
  const m = ph.msPerSecond;
  console.log(`\n${ph.label}, CPU ${THROTTLE}x slower, ${FIXES} s: main thread ${m.task.toFixed(0)} ms/s (script ${m.script.toFixed(0)}, style ${m.style.toFixed(0)}, layout ${m.layout.toFixed(0)}); ${ph.commitsPerSecond.toFixed(2)} React commits/s`);
  for (const row of ph.rows.slice(0, 25)) console.log(`  ${row.name.padEnd(32)} ${row.perSecond.toFixed(2).padStart(6)} renders/s ${row.selfMsPerSecond.toFixed(2).padStart(7)} ms/s`);
  for (const h of ph.hot) console.log(`  cpu: ${h.msPerSecond.toFixed(1).padStart(6)} ms/s ${h.fn}`);
  if (process.argv.includes("--why")) for (const [k, n] of ph.why) console.log(`  why: ${n} x ${k}`);
}
if (OUT) writeFileSync(OUT, JSON.stringify({ throttle: THROTTLE, fixes: FIXES, ride, still }, null, 1));
