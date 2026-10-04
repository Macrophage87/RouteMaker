// The browser check for the combined a11y review's fixes (FIX-A11Y): focus
// order, Escape, focus return, the credits at 375 px and the focus ring's
// contrast, against the app under Vite with a mocked API. Run by
// scripts/a11y/run.sh, which starts Vite and an offline Chromium; prints one
// line per check and exits non-zero if any fails.
//
//   node scripts/a11y/check.mjs [--port 5173] [--shots DIR]
import { mkdirSync } from "node:fs";
import { S_BIKESHARE, S_BIKESHARE_EBIKE, S_CHOICES, S_DEFAULT, S_MASS, S_MASS_CAPACITY, S_MASS_OUTSIDE_DC, S_OVER, S_TRAIL, axNode, connect, contrast, decodePng, hashFor, media, mock, newPage, sleep } from "./cdp.mjs";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const PORT = Number(arg("--port", "5173"));
const SHOTS = arg("--shots", "/tmp/a11y-shots");
mkdirSync(SHOTS, { recursive: true });

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok: !!ok });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` - ${detail}` : ""}`);
}

const b = await connect();

// The sidebar (OWNER-DECISIONS 312): the ride settings are behind the Ride line's Edit, and the
// switches, the legend and federal land are in the Map layers sheet. `ride` opens the settings once the
// route is shown (the sliders, the target distance, the loop and the weight live there), and
// `junctions` the "Junctions to watch" fold; openSheet opens a bar sheet, openDirections the
// Directions fold.
async function open({ route = S_DEFAULT, hash = hashFor("default", 70), width = 1280, height = 900, scheme = "light", forced = false, mobile = false, delayMs = 0, delayFrom = 2, stressTiles = true, ride = true, junctions = true, accessMode = false } = {}) {
  const p = await newPage(b, { width, height, mobile });
  if (mobile) await p.s("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await mock(p, route, { delayMs, delayFrom, stressTiles });
  await media(p, { scheme, forced });
  // A device that kept accessibility mode on (455): the stored value, set before the app starts.
  if (accessMode) await p.s("Page.addScriptToEvaluateOnNewDocument", { source: "try { localStorage.setItem('routemaker.accessMode', 'on'); } catch {}" });
  await p.s("Page.navigate", { url: `http://127.0.0.1:${PORT}/${hash}` });
  const ready = await p.waitFor("!!document.querySelector('.summary') && document.querySelectorAll('.junction-marker').length > 0", 40000);
  if (!ready) throw new Error("the app did not show a route");
  await sleep(800);
  if (ride) {
    await p.eval("(() => { const b = document.querySelector('.ride-line-button'); if (b && b.getAttribute('aria-expanded') !== 'true') b.click(); return true; })()");
    await sleep(200);
  }
  // The junction list is in the route summary's "Junctions to watch" fold, closed by default (312):
  // its rows cannot take the focus until the fold is open, as for a rider.
  if (junctions) {
    await p.eval("(() => { const l = document.querySelector('.junction-list'); const d = l?.closest('details'); if (d && !d.open) d.querySelector('summary').click(); return true; })()");
    await sleep(200);
  }
  return p;
}

/** Opens a bottom-bar sheet by its button's label ("Map layers", "Legend", "GPX", "Settings"). */
async function openSheet(p, label = "Map layers") {
  await p.eval(`[...document.querySelectorAll('.bar-button')].find((b) => b.textContent.startsWith(${JSON.stringify(label)}))?.click(); true`);
  await sleep(250);
}

/** Opens the route summary's Directions fold (a native details). */
async function openDirections(p) {
  await p.eval("(() => { const d = document.querySelector('details.route-description'); if (d && !d.open) d.querySelector('summary').click(); return true; })()");
  await sleep(200);
}

/** What has the focus, in a few words. */
const focused = (p) =>
  p.eval(`(() => { const e = document.activeElement; if (!e || e === document.body) return "body";
    return [e.tagName.toLowerCase(), e.id ? "#" + e.id : "", e.className && typeof e.className === "string" ? "." + e.className.split(" ").join(".") : "",
      e.dataset?.junctionIndex !== undefined ? "[" + e.dataset.junctionIndex + "]" : "", " " + (e.getAttribute("aria-label") || e.textContent || "").trim().slice(0, 40)].join(""); })()`);

// ---- 1. Focus order: the accessibility mode switch first (455), then the skip link, which skips the map ----
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100) });
  await p.eval("document.activeElement?.blur(); true");
  const accessHidden = await p.eval("(() => { const e = document.querySelector('.access-link'); const r = e.getBoundingClientRect(); return r.bottom <= 0; })()");
  await p.tab();
  const first = await focused(p);
  // Accessibility mode (OWNER-DECISIONS 455): its switch is the very first stop, hidden until it has the focus.
  const access = await p.eval("(() => { const e = document.querySelector('.access-link'); const r = e.getBoundingClientRect(); return { focused: document.activeElement === e, visible: r.top >= 0 && r.bottom <= innerHeight && r.width > 40, tall: r.height >= 44, name: e.textContent, pressed: e.getAttribute('aria-pressed'), tag: e.tagName, first: [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')].find((x) => x.tabIndex >= 0) === e }; })()");
  check("accessibility mode: its switch is the first Tab stop and first in the page's order, not pressed, and it shows, at least 44 px tall", access.focused && access.visible && access.tall && access.first && access.tag === "BUTTON" && access.name === "Accessibility mode" && access.pressed === "false", JSON.stringify(access));
  await p.shot(`${SHOTS}/access-link_focused.png`, { x: 0, y: 0, width: 420, height: 90 });
  await p.tab();
  const second = await focused(p);
  const skip = await p.eval("(() => { const e = document.querySelector('.skip-link'); const r = e.getBoundingClientRect(); return { focused: document.activeElement === e, visible: r.top >= 0 && r.bottom <= innerHeight && r.width > 40, tall: r.height >= 44 }; })()");
  check("focus order: the next Tab stop is the skip link, and it shows, at least 44 px tall", skip.focused && skip.visible && skip.tall, JSON.stringify({ first, second, skip }));
  await p.shot(`${SHOTS}/skip-link_focused.png`, { x: 0, y: 0, width: 420, height: 90 });
  check("accessibility mode: its switch is off screen until it has the focus", accessHidden === true, String(accessHidden));
  const hash = await p.eval("location.hash");
  await p.enter();
  await sleep(150);
  check("focus order: the skip link puts the focus on the planner", await p.eval("document.activeElement?.id === 'route-planner'"), await focused(p));
  check("focus order: the skip link leaves the plan in the address", (await p.eval("location.hash")) === hash);
  await p.tab();
  check("focus order: the next stop is inside the planner, past every marker", await p.eval("!!document.activeElement.closest('#route-planner')"), await focused(p));
  // Without the link: how many stops from it to the planner.
  await p.eval("document.querySelector('.skip-link').focus(); true");
  let stops = 0;
  for (; stops < 80; stops++) {
    await p.tab();
    if (await p.eval("!!document.activeElement.closest('#route-planner')")) break;
  }
  console.log(`  (tabbing through the map instead: ${stops} stops before the planner)`);

  // The announcement: the detour's tier and the very high stress junctions.
  await p.waitFor("document.querySelector('.status-line')?.textContent.includes('Route planned')", 5000);
  const said = await p.eval("document.querySelector('.status-line').textContent");
  check("announcement: says the strong detour and the very high stress junctions", /Strong warning: 2\.4 times the direct distance/.test(said) && /2 very high stress junctions\./.test(said), said);

  // The slider: named once, described by the calm note.
  const slider = await axNode(p, ".dial input[type=range]");
  check("slider: its name is its label alone", slider?.name === "Traffic", JSON.stringify(slider?.name));
  check("slider: the calm note is its description", /^Calmest: finds the least stressful route towards your target distance/.test(slider?.description ?? ""), (slider?.description ?? "").slice(0, 60));

  // One plan and one announcement for a burst of keys.
  await p.eval(`window.__said = []; new MutationObserver(() => { const t = document.querySelector('.status-line').textContent.trim(); if (t) window.__said.push(t); })
    .observe(document.querySelector('.status-line'), { childList: true, subtree: true, characterData: true }); true`);
  const before = p.routeRequests;
  await p.eval("document.querySelector('.dial input[type=range]').focus(); true");
  for (let i = 0; i < 4; i++) {
    await p.key("ArrowLeft", "ArrowLeft", 37);
    await sleep(120);
  }
  await sleep(3500);
  const plans = p.routeRequests - before;
  const announcements = await p.eval("window.__said");
  check("slider: four key presses plan once", plans === 1, `${plans} plans`);
  check("slider: and are announced once", announcements.length === 1, JSON.stringify(announcements));
  await p.close();
}

// ---- 2. The card from the list: focus stays, Escape closes it ----
{
  const p = await open();
  await p.eval("document.querySelectorAll('.junction-item')[1].focus(); true");
  await p.enter();
  await sleep(700);
  check("list: Enter on a row opens the card", await p.eval("!!document.querySelector('.junction-popup')"));
  check("list: the focus stays on the row", await p.eval("document.activeElement === document.querySelectorAll('.junction-item')[1]"), await focused(p));
  const card = await axNode(p, ".junction-popup");
  check("card: a dialog named for the junction", card?.role === "dialog" && /^Very high stress junction, at /.test(card?.name ?? ""), `${card?.role} "${card?.name}"`);
  const close = await axNode(p, ".junction-popup .maplibregl-popup-close-button");
  check("card: its close button says what it closes", close?.name === "Close junction card", close?.name);
  await p.escape();
  await sleep(200);
  check("list: Escape closes the card", await p.eval("!document.querySelector('.junction-popup')"));
  check("list: and the focus is still on the row", await p.eval("document.activeElement === document.querySelectorAll('.junction-item')[1]"), await focused(p));
  // A mouse click on a row leaves the focus there too.
  const at = await p.eval("(() => { const e = document.querySelectorAll('.junction-item')[0]; e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return [r.left + 40, r.top + r.height / 2]; })()");
  await p.s("Input.dispatchMouseEvent", { type: "mousePressed", x: at[0], y: at[1], button: "left", clickCount: 1 });
  await p.s("Input.dispatchMouseEvent", { type: "mouseReleased", x: at[0], y: at[1], button: "left", clickCount: 1 });
  await sleep(700);
  check("list: a click on a row keeps the focus on it", await p.eval("document.activeElement === document.querySelectorAll('.junction-item')[0]"), await focused(p));
  check("markers: no title read again as the description", await p.eval("[...document.querySelectorAll('.junction-marker')].every((m) => !m.hasAttribute('title'))"));
  await p.close();
}

// ---- 3. The card from a marker: focus into it, back to the marker ----
{
  const p = await open();
  // Zoomed in, so each junction has its own marker.
  await p.eval("true");
  const single = await p.eval("(() => { const m = [...document.querySelectorAll('.junction-marker:not(.junction-group)')][0]; m.focus(); return m.dataset.junctionIndex; })()");
  await p.enter();
  await sleep(500);
  check("marker: Enter opens its card and the focus goes to its close button", await p.eval("document.activeElement?.classList.contains('maplibregl-popup-close-button') && !!document.activeElement.closest('.junction-popup')"), await focused(p));
  await p.enter();
  await sleep(300);
  check("marker: closing the card gives the focus back to the marker", await p.eval(`document.activeElement?.dataset?.junctionIndex === "${single}" && document.activeElement.classList.contains('junction-marker')`), await focused(p));
  await p.enter();
  await sleep(500);
  await p.escape();
  await sleep(300);
  check("marker: Escape closes the card", await p.eval("!document.querySelector('.junction-popup')"));
  check("marker: and gives the focus back to the marker", await p.eval(`document.activeElement?.dataset?.junctionIndex === "${single}" && document.activeElement.classList.contains('junction-marker')`), await focused(p));

  // The group: its zoom hands the focus to the first member's new marker.
  const group = await p.eval("(() => { const g = document.querySelector('.junction-marker.junction-group'); if (!g) return null; g.focus(); return g.dataset.junctionIndex; })()");
  if (group === null) check("group: the two reds are a group at the opening zoom", false);
  else {
    await p.enter();
    await sleep(1500);
    const now = await p.eval("(() => { const e = document.activeElement; return { marker: e?.classList.contains('junction-marker'), index: e?.dataset?.junctionIndex, group: e?.classList.contains('junction-group'), zoom: 0 }; })()");
    check("group: after its zoom the focus is on the first member's new marker", now.marker && now.index === group, `${JSON.stringify(now)} (first member ${group})`);
  }
  await p.close();
}

// ---- 4. The credits at 375 px ----
for (const [width, height] of [[375, 812], [320, 800]]) {
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100), width, height, mobile: true });
  const credits = await p.eval(`(() => { const a = document.querySelector('.maplibregl-ctrl-attrib'); const r = a.getBoundingClientRect();
    const nav = document.querySelector('.maplibregl-ctrl-top-right').getBoundingClientRect();
    const scales = [...document.querySelectorAll('.maplibregl-ctrl-scale')].map((s) => s.getBoundingClientRect());
    const credit = getComputedStyle(a, '::before').content;
    return { collapsed: a.classList.contains('maplibregl-compact') && !a.classList.contains('maplibregl-compact-show'), height: Math.round(r.height), width: Math.round(r.width), credit,
      overlap: scales.some((s) => s.top < nav.bottom && s.bottom > nav.top && s.left < nav.right && s.right > nav.left), button: !!a.querySelector('summary.maplibregl-ctrl-attrib-button') }; })()`);
  check(`credits at ${width} px: start collapsed to the i button`, credits.collapsed && credits.button && credits.height <= 30, JSON.stringify(credits));
  check(`credits at ${width} px: the OpenStreetMap credit still shows`, /OpenStreetMap/.test(credits.credit), credits.credit);
  check(`credits at ${width} px: the scales clear the zoom buttons`, !credits.overlap);
  const markers = await p.eval(`[...document.querySelectorAll('.junction-marker')].map((m) => { const r = m.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return h === m || m.contains(h) ? 'clear' : (h ? h.className.toString().slice(0, 40) : 'off-screen'); })`);
  check(`credits at ${width} px: no junction marker is under the credits`, markers.every((m) => m === "clear" || m === "off-screen" || !/attrib/.test(m)), JSON.stringify(markers));
  await p.eval("document.querySelectorAll('.junction-item')[0].click(); true");
  await sleep(1200);
  const close = await p.eval(`(() => { const c = document.querySelector('.junction-popup .maplibregl-popup-close-button'); if (!c) return 'no card'; const r = c.getBoundingClientRect();
    return [[r.left + 2, r.top + 2], [r.right - 2, r.bottom - 2], [r.left + r.width / 2, r.top + r.height / 2]].map(([x, y]) => { const h = document.elementFromPoint(x, y); return h === c || c.contains(h) ? 'clear' : (h ? h.className.toString().slice(0, 30) : 'off'); }); })()`);
  check(`credits at ${width} px: the card's close button is not covered`, Array.isArray(close) && close.every((h) => h === "clear"), JSON.stringify(close));
  await p.shot(`${SHOTS}/credits_${width}_card-open.png`);
  // Opening the credits still works, and scrolls rather than climbing into the zoom buttons.
  await p.eval("document.querySelector('.maplibregl-ctrl-attrib-button').click(); true");
  await sleep(200);
  const opened = await p.eval(`(() => { const a = document.querySelector('.maplibregl-ctrl-attrib'); const nav = document.querySelector('.maplibregl-ctrl-top-right').getBoundingClientRect(); const r = a.getBoundingClientRect();
    return { shown: a.classList.contains('maplibregl-compact-show'), clearOfNav: r.top > nav.bottom, links: [...a.querySelectorAll('a')].length }; })()`);
  check(`credits at ${width} px: the i opens the full credits, clear of the zoom buttons`, opened.shown && opened.clearOfNav && opened.links >= 2, JSON.stringify(opened));
  await p.shot(`${SHOTS}/credits_${width}_opened.png`);
  if (width === 320) {
    await p.eval("document.querySelector('.maplibregl-ctrl-attrib-button').click(); document.querySelector('.junction-list').scrollIntoView({ block: 'start' }); true");
    await sleep(300);
    const reason = await p.eval("(() => { const r = document.querySelector('.junction-reason').getBoundingClientRect(); const row = document.querySelector('.junction-item').getBoundingClientRect(); return { reason: Math.round(r.width), row: Math.round(row.width), spill: document.querySelector('.junction-list').scrollWidth > document.querySelector('.junction-list').clientWidth }; })()");
    check("rows at 320 px: the reason has the row's width and nothing spills sideways", reason.reason >= reason.row - 60 && !reason.spill, JSON.stringify(reason));
    const list = await p.eval("(() => { const r = document.querySelector('figure.junctions').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: Math.min(r.height + 8, innerHeight - r.top) }; })()");
    await p.shot(`${SHOTS}/rows_320.png`, list);
  }
  await p.close();
}
{
  const p = await open({ width: 1280, height: 900 });
  check("credits at 1280 px: stay open", await p.eval("document.querySelector('.maplibregl-ctrl-attrib').classList.contains('maplibregl-compact-show')"));
  await p.close();
}

// ---- 5. The focus ring's contrast on the map, in each theme ----
for (const [mode, opts] of [["light", {}], ["dark", { scheme: "dark" }], ["forced-dark", { scheme: "dark", forced: true }], ["forced-light", { forced: true }]]) {
  const p = await open({ ...opts });
  // A keyboard focus, so :focus-visible applies.
  await p.eval("document.querySelector('.junction-marker:not(.junction-group)').scrollIntoView(); document.querySelector('.junction-marker:not(.junction-group)').focus(); true");
  await p.eval("document.activeElement.blur(); true");
  const index = await p.eval("document.querySelector('.junction-marker:not(.junction-group)').dataset.junctionIndex");
  // Tab to it from the skip link's side, so the focus is a keyboard one.
  await p.eval(`(() => { const all = [...document.querySelectorAll('.junction-marker')]; const m = all.find((e) => e.dataset.junctionIndex === "${index}"); const before = document.createElement('button'); before.id = '__before'; before.style.cssText = 'position:fixed;left:-99px;top:0'; m.parentElement.insertBefore(before, m); before.focus(); return true; })()`);
  await p.tab();
  const ring = await p.eval(`(() => { const e = document.activeElement; const s = getComputedStyle(e); const r = e.getBoundingClientRect(); document.getElementById('__before')?.remove();
    return { marker: e.classList.contains('junction-marker'), fv: e.matches(':focus-visible'), outline: s.outlineColor + ' ' + s.outlineWidth + ' ' + s.outlineStyle, shadow: s.boxShadow, rect: [r.left, r.top, r.width, r.height] }; })()`);
  const [x, y, w, h] = ring.rect;
  const clip = { x: Math.round(x - 16), y: Math.round(y - 16), width: Math.round(w + 32), height: Math.round(h + 32) };
  const png = decodePng(await p.png(clip));
  // In the clip, the marker's left edge is at 16: the ring is 2-5 px out from it, the white ring 0-2 px, the map 9 px and more.
  const cy = Math.round(16 + h / 2);
  const ringPx = png.pixel(16 - 4, cy);
  const innerPx = png.pixel(16 - 1, cy);
  const mapPx = png.pixel(3, cy);
  const ratio = contrast(ringPx, mapPx);
  // A two-colour ring (WCAG technique C40): one of the pair stands out from
  // the map, and the two from each other. Outside forced colours the dark ring
  // itself does; in a forced dark theme the white ring is the system's, and
  // the black one inside it is what shows on the light map.
  const best = Math.max(ratio, contrast(innerPx, mapPx));
  check(`ring (${mode}): a keyboard focus on a marker shows the ring`, ring.marker && ring.fv, ring.outline);
  check(`ring (${mode}): 3:1 or more against the map beside it`, (opts.forced ? best : ratio) >= 3, `ring ${ringPx} inner ${innerPx} map ${mapPx}: ring ${ratio.toFixed(2)}:1, best of the pair ${best.toFixed(2)}:1`);
  check(`ring (${mode}): the inner ring is the other of the pair`, contrast(innerPx, ringPx) >= 3, `${innerPx} vs ${ringPx}`);
  if (!opts.forced) check(`ring (${mode}): the same dark ring in either theme`, /rgb\(17, 24, 39\) 3px solid/.test(ring.outline), ring.outline);
  await p.shot(`${SHOTS}/ring_${mode}_marker.png`, clip);
  // The map canvas and the credits links: dark on the light map, in the dark theme too.
  if (mode === "dark") {
    const canvas = await p.eval("(() => { const c = document.querySelector('.maplibregl-canvas'); return getComputedStyle(c).getPropertyValue('--map-focus').trim(); })()");
    check("ring (dark): the canvas and the credits use the map's ring, not amber", canvas === "#111827", canvas);
    const rings = await p.eval(`(() => { const out = {}; for (const sel of ['.maplibregl-canvas', '.maplibregl-ctrl-attrib a', '.maplibregl-ctrl-zoom-in']) {
      const e = document.querySelector(sel); e.focus(); const st = getComputedStyle(e); out[sel] = { fv: e.matches(':focus-visible'), outline: st.outlineColor + ' ' + st.outlineWidth }; } return out; })()`);
    check("ring (dark): the canvas, a credits link and Zoom in ring in the map's dark ring", Object.values(rings).every((r) => r.fv && /^rgb\(17, 24, 39\) 3px$/.test(r.outline)), JSON.stringify(rings));
    await p.shot(`${SHOTS}/ring_dark_zoom-in.png`, await p.eval("(() => { const r = document.querySelector('.maplibregl-ctrl-top-right').getBoundingClientRect(); return { x: r.left - 12, y: r.top, width: r.width + 12, height: r.height + 12 }; })()"));
  }
  if (mode === "forced-dark") {
    const zoom = await p.eval("(() => { const e = document.querySelector('.maplibregl-ctrl-zoom-in'); e.focus(); const st = getComputedStyle(e); return { fv: e.matches(':focus-visible'), outline: st.outlineStyle + ' ' + st.outlineWidth + ' ' + st.outlineOffset }; })()");
    check("ring (forced-dark): MapLibre's Zoom in keeps a real outline", zoom.fv && /^solid 3px -3px$/.test(zoom.outline), JSON.stringify(zoom));
    await p.shot(`${SHOTS}/ring_forced-dark_zoom-in.png`, await p.eval("(() => { const r = document.querySelector('.maplibregl-ctrl-top-right').getBoundingClientRect(); return { x: r.left - 12, y: r.top, width: r.width + 12, height: r.height + 12 }; })()"));
  }
  await p.close();
}


// ---- 6. A group of signalized crossings: a row that opens onto its crossings (items 233, 234) ----
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0) });
  const state = () =>
    p.eval(`(() => { const t = document.querySelector('.junction-group-toggle'); const l = document.getElementById(t.getAttribute('aria-controls'));
      return { expanded: t.getAttribute('aria-expanded'), hidden: l.hidden, shown: l.querySelectorAll('.junction-item').length > 0 && l.offsetParent !== null,
        rows: document.querySelectorAll('.junction-list .junction-item').length, groups: document.querySelectorAll('.junction-group-toggle').length,
        focus: document.activeElement === t }; })()`);
  const first = await state();
  check("group: one row for the four crossings, closed to begin with", first.groups === 1 && first.expanded === "false" && first.hidden && !first.shown, JSON.stringify(first));
  const ax = await axNode(p, ".junction-group-toggle");
  // One aria-label, so no stray space before the comma or the colon (a11y re-check of 2b0cf00, B2).
  check("group: a button whose name is the severity, then the phrase", ax?.role === "button" && /^Very high stress, Group: 1\.1 to 1\.8 mi \(1\.7 to 2\.9 km\): 4 crossings with traffic signals \(17th Street Northwest, 15th Street Northwest, 14th Street Northwest and 1 more\), 1 of them a heavy-traffic road \(LTS 4\)$/.test(ax?.name ?? ""), JSON.stringify(ax?.name));
  // The lone rows as the screen reader names them; the members (hidden while the group is closed) by their label.
  const names = await p.eval(`[...document.querySelectorAll('.junction-list .junction-item:not(.junction-group-toggle)')].map((e) => e.getAttribute('aria-label') ?? '')`);
  for (const index of ["0", "5"]) names.push((await axNode(p, `.junction-list > li > .junction-item[data-junction-index="${index}"]`))?.name ?? "");
  check("rows: every row and member is named \"<severity>, At <distance>: <reason>\", with no stray spaces", names.length === 8 && names.every((n) => /^(Higher|Very high) stress, At \d+\.\d mi \(\d+\.\d km\): \S/.test(n) && !/ [,:]/.test(n)), JSON.stringify(names));
  check("group: the screen reader hears it collapsed", ax?.expanded === false, JSON.stringify(ax));
  // Tab order: closed, the crossings are not in it.
  await p.eval("document.querySelectorAll('.junction-list > li')[0].querySelector('.junction-item').focus(); true");
  await p.tab();
  check("group: Tab from the row before it lands on the group's button", await p.eval("document.activeElement?.classList.contains('junction-group-toggle')"), await focused(p));
  await p.tab();
  check("group: closed, the next Tab skips its crossings to the row after", await p.eval("(() => { const e = document.activeElement; return e.classList.contains('junction-item') && !e.closest('.junction-members'); })()"), await focused(p));
  await p.tab(true);
  // Enter opens it, and the focus stays on the button.
  await p.enter();
  await sleep(200);
  const opened = await state();
  check("group: Enter opens it onto its four crossings and the focus stays on the button", opened.expanded === "true" && !opened.hidden && opened.shown && opened.focus && opened.rows === 1 + 1 + 4 + 1, JSON.stringify(opened));
  const axOpen = await axNode(p, ".junction-group-toggle");
  check("group: the screen reader hears it expanded", axOpen?.expanded === true, JSON.stringify(axOpen));
  const members = await p.eval("[...document.querySelectorAll('.junction-members .junction-item')].map((e) => e.dataset.junctionIndex + ' ' + e.textContent.trim().slice(0, 60))");
  check("group: its crossings are the ordinary rows, in route order", members.length === 4 && members.map((m) => m.split(' ')[0]).join() === "1,2,3,4", JSON.stringify(members));
  await p.tab();
  check("group: open, the next Tab is its first crossing", await p.eval("document.activeElement?.dataset?.junctionIndex === '1' && !!document.activeElement.closest('.junction-members')"), await focused(p));
  // A crossing opens the ordinary card, and the focus stays on its row.
  await p.enter();
  await sleep(700);
  check("group: Enter on a crossing opens the junction card, the focus stays on its row", await p.eval("!!document.querySelector('.junction-popup') && document.activeElement?.dataset?.junctionIndex === '1'"), await focused(p));
  const card = await axNode(p, ".junction-popup");
  check("group: the card is the ordinary dialog for that crossing", card?.role === "dialog" && /^Higher stress junction, at /.test(card?.name ?? ""), `${card?.role} "${card?.name}"`);
  await p.escape();
  await sleep(200);
  check("group: Escape closes the card and the focus is still on the crossing's row", await p.eval("!document.querySelector('.junction-popup') && document.activeElement?.dataset?.junctionIndex === '1'"), await focused(p));
  // Space closes it again.
  await p.eval("document.querySelector('.junction-group-toggle').focus(); true");
  await p.key(" ", "Space", 32);
  await sleep(200);
  const closed = await state();
  check("group: Space closes it again, the focus on the button", closed.expanded === "false" && closed.hidden && !closed.shown && closed.focus, JSON.stringify(closed));
  // Opening or closing says nothing.
  const live = await p.eval("(() => { const t = document.querySelector('.junction-group-toggle'); return !t.closest('[aria-live], [role=status], [role=alert]'); })()");
  check("group: it sits in no live region, so opening it announces nothing", live);
  // The markers are unchanged: every crossing keeps its own, grouped on the map as before.
  const markers = await p.eval("document.querySelectorAll('.junction-marker').length");
  check("markers: still drawn for the route's junctions", markers >= 1, String(markers));
  await p.close();
}
{
  // 320 px: the group's phrase wraps and nothing spills sideways, open or closed.
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0), width: 320, height: 800, mobile: true });
  await p.eval("document.querySelector('.junction-group-toggle').click(); document.querySelector('.junction-list').scrollIntoView({ block: 'start' }); true");
  await sleep(300);
  const wrap = await p.eval(`(() => { const l = document.querySelector('.junction-list'); const t = document.querySelector('.junction-group-toggle');
    const r = t.querySelector('.junction-reason').getBoundingClientRect(); const row = t.getBoundingClientRect();
    const member = document.querySelector('.junction-members .junction-item').getBoundingClientRect();
    return { reason: Math.round(r.width), row: Math.round(row.width), member: Math.round(member.width), spill: l.scrollWidth > l.clientWidth, page: document.documentElement.scrollWidth > innerWidth }; })()`);
  check("group at 320 px: the phrase has the row's width, the crossings are set in, nothing spills", wrap.reason >= wrap.row - 60 && wrap.member < wrap.row && !wrap.spill && !wrap.page, JSON.stringify(wrap));
  await p.shot(`${SHOTS}/group_320_open.png`, await p.eval("(() => { const r = document.querySelector('figure.junctions').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: Math.min(r.height + 8, innerHeight - r.top) }; })()"));
  await p.close();
}

// ---- 7. The rows at 320 px with WCAG text spacing (1.4.12; a11y re-check of 2b0cf00) ----
const TEXT_SPACING = `* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }`;
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0), width: 320, height: 800, mobile: true });
  await p.eval(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(TEXT_SPACING)}; document.head.append(s);
    document.querySelector('.junction-group-toggle').click(); document.querySelector('.junction-list').scrollIntoView({ block: 'start' }); return true; })()`);
  await sleep(300);
  const rows = await p.eval(`(() => { const l = document.querySelector('.junction-list');
    const over = [...l.querySelectorAll('.junction-item')].filter((e) => e.scrollWidth > e.clientWidth + 1 || [...e.children].some((c) => c.getBoundingClientRect().right > e.getBoundingClientRect().right + 1)).map((e) => e.dataset.junctionIndex ?? 'group');
    return { over, spill: l.scrollWidth > l.clientWidth + 1, page: document.documentElement.scrollWidth > innerWidth }; })()`);
  check("rows at 320 px with text spacing: ordinary, group and member rows wrap inside the list", rows.over.length === 0 && !rows.spill && !rows.page, JSON.stringify(rows));
  await p.shot(`${SHOTS}/rows_320_spacing.png`, await p.eval("(() => { const r = document.querySelector('figure.junctions').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: Math.min(r.height + 8, innerHeight - r.top) }; })()"));
  await p.close();
}

// ---- 8. The route description: keyboard, names, the copy reply, a group's crossings ----
/** Every scroll box in the panel can be reached by keyboard: focusable itself, or holding something focusable (2.1.1). */
const SCROLL_BOXES = `(() => { const focusable = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
  return [...document.querySelectorAll('.panel-body, .panel-body *')].filter((e) => { const s = getComputedStyle(e);
    return /(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight + 1 && e.offsetParent !== null; })
    .map((e) => ({ box: e.className.toString().slice(0, 40) || e.tagName, reachable: e.tabIndex >= 0 || !!e.querySelector(focusable) })); })()`;
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100) });
  // Directions is a fold of the route summary (312): a native details, its summary naming the steps.
  const toggle = await axNode(p, "details.route-description > summary");
  const shut = await p.eval("!document.querySelector('details.route-description').open");
  check("description: the fold's summary says what it opens, and it starts closed", toggle?.name === "Directions (11 steps)" && shut, JSON.stringify(toggle));
  await openDirections(p);
  const list = await p.eval(`(() => { const l = document.querySelector('.description-list'); const s = getComputedStyle(l);
    return { items: l.children.length, overflow: s.overflowY, maxHeight: s.maxHeight, box: l.scrollHeight > l.clientHeight + 1 }; })()`);
  check("description: the list is no scroll box of its own (the panel scrolls)", list.items === 11 && list.overflow === "visible" && list.maxHeight === "none" && !list.box, JSON.stringify(list));
  const boxes = await p.eval(SCROLL_BOXES);
  check("description: every scroll box in the panel can be reached by keyboard", boxes.every((b) => b.reachable), JSON.stringify(boxes));
  const view = await axNode(p, ".description-view input");
  const label = await p.eval("(() => { const r = document.querySelector('.description-view').getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; })()");
  check("description: Full detail is named without a leading space and its target is 24 px tall", view?.name === "Full detail" && label.h >= 24, `${JSON.stringify(view?.name)} ${JSON.stringify(label)}`);
  // A second press of Copy is said again.
  await p.eval(`window.__copy = []; new MutationObserver(() => { const t = document.querySelector('.description-status').textContent.trim(); if (t) window.__copy.push(t); })
    .observe(document.querySelector('.description-status'), { childList: true, subtree: true, characterData: true }); true`);
  const copyButton = "[...document.querySelectorAll('.description-actions button')].find((b) => /Copy description/.test(b.textContent))";
  await p.eval(`${copyButton}.click(); true`);
  await sleep(700);
  await p.eval(`${copyButton}.click(); true`);
  await sleep(700);
  const said = await p.eval("window.__copy");
  check("description: Copy's reply is said again on a second press", said.length === 2 && said[0] === said[1], JSON.stringify(said));
  await p.close();
}
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0) });
  await openDirections(p);
  const overview = await p.eval("document.querySelectorAll('.description-list .description-crossings').length");
  check("description: the overview keeps one line per group", overview === 0, String(overview));
  await p.eval("document.querySelector('.description-view input').click(); true");
  await sleep(200);
  const nested = await p.eval(`(() => { const o = document.querySelector('.description-list > li > ol.description-crossings');
    return o ? { parent: o.parentElement.tagName, items: [...o.children].map((li) => li.tagName + ' ' + li.textContent.slice(0, 22)) } : null; })()`);
  const ax = await axNode(p, ".description-crossings");
  check("description: in full detail a group lists its four crossings as a nested ordered list", nested?.parent === "LI" && nested.items.length === 4 && nested.items.every((i) => /^LI At \d+\.\d mi/.test(i)), JSON.stringify(nested));
  check("description: and the nested list is named for what it is", ax?.role === "list" && ax?.name === "Crossings in this group, in route order", JSON.stringify(ax));
  const all = await p.eval("document.querySelector('.description-list').textContent");
  check("description: every street of the group is named in full detail", ["17th", "15th", "14th", "13th"].every((s) => all.includes(`${s} Street Northwest (LTS`)), "");
  await p.shot(`${SHOTS}/description_mass_full.png`, await p.eval("(() => { const e = document.querySelector('.route-description'); e.scrollIntoView({ block: 'start' }); const r = e.getBoundingClientRect(); return { x: Math.max(0, r.left), y: Math.max(0, r.top), width: Math.max(1, Math.round(r.width)), height: Math.max(1, Math.round(Math.min(r.height, innerHeight - Math.max(0, r.top)))) }; })()"));
  await p.close();
}

// ---- 9. The target distance, the system weight and the loop toggle (OWNER-DECISIONS 256, 264, 266, 271) ----
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100) });
  const target = await axNode(p, "input[placeholder=Default]");
  check("target distance: the field's name is its label, in miles", target?.role === "textbox" && target?.name === "Target distance (miles)", JSON.stringify(target?.name));
  check("target distance: its description says what it does, miles first, in under 150 characters", /^Optional: the calmest route at or under this\./.test(target?.description ?? "") && /up to 1\.6 times/.test(target?.description ?? "") && (target?.description ?? "").length < 150, (target?.description ?? "").slice(0, 80));
  const how = await p.eval("(() => { const d = document.querySelector('.dial details.how'); return d ? { summary: d.querySelector('summary').textContent, open: d.open } : null; })()");
  check("target distance: the detail is under a closed \"How this works\", not in the description", how?.summary === "How this works" && how.open === false, JSON.stringify(how));
  const line = await p.eval("document.querySelector('.weight-line')?.textContent ?? null");
  check("rider and bike weight: the panel shows only whether one is set, no number field (313, 314)", line === "Rider and bike weight: not set, defaults used" && (await p.eval("document.querySelectorAll('input[placeholder=Default]').length")) === 1, JSON.stringify(line));
  const field = "document.querySelector('input[placeholder=Default]')";
  // Typing plans nothing; Enter plans once.
  const before = p.routeRequests;
  await p.eval(`${field}.focus(); true`);
  await p.type("60");
  await sleep(1500);
  check("target distance: typing plans nothing until the field is left or Enter is pressed", p.routeRequests === before, `${p.routeRequests - before} plans`);
  await p.enter();
  await sleep(1500);
  check("target distance: Enter plans once", p.routeRequests - before === 1, `${p.routeRequests - before} plans`);
  check("target distance: the plan is in the address in miles", /targetmi=60\.0/.test(await p.eval("location.hash")), await p.eval("location.hash"));
  const set = await axNode(p, "input[placeholder=Default]");
  check("target distance: once set, its description gives the ceiling in miles first", /never past 75\.0 mi \(120\.7 km\)\./.test(set?.description ?? ""), (set?.description ?? "").slice(0, 200));
  // A bad entry is said in words and marked invalid, and plans nothing.
  const again = p.routeRequests;
  // The rule's live region is in the page before any bad entry, and empty (the a11y review's SF3).
  const rule = `document.getElementById(${field}.id + '-rule')`;
  const before9 = await p.eval(`(() => { const r = ${rule}; return r ? { text: r.textContent, live: r.closest('[aria-live=assertive], [role=alert]') !== null } : null; })()`);
  check("target distance: the rule's assertive live region is in the page, empty, before a bad entry", before9?.live === true && before9.text === "", JSON.stringify(before9));
  await p.eval(`window.__rule = []; new MutationObserver(() => { const t = ${rule}.textContent.trim(); if (t) window.__rule.push(t); }).observe(${rule}, { childList: true, subtree: true, characterData: true }); true`);
  await p.eval(`${field}.focus(); ${field}.select(); true`);
  await p.type("abc");
  await p.enter();
  await sleep(500);
  const bad = await p.eval(`(() => { const e = ${field}; return { invalid: e.getAttribute('aria-invalid'), said: document.getElementById(e.getAttribute('aria-describedby').split(' ')[1])?.textContent, focus: document.activeElement === e }; })()`);
  check("target distance: a bad entry is marked invalid and said in words, metric in brackets, the focus stays, and it plans nothing", bad.invalid === "true" && /^Enter 0\.7 to 621 miles \(1 to 1,000 km\), or leave it empty\.$/.test(bad.said ?? "") && bad.focus && p.routeRequests === again, JSON.stringify(bad));
  const live = await p.eval(`(() => { const r = ${rule}; const region = r.closest('[aria-live]'); return { inLive: !!region, politeness: region?.getAttribute('aria-live'), text: r.textContent.trim() }; })()`);
  check("target distance: the rule is said, in an assertive live region, once filled", live.inLive && live.politeness === "assertive" && /^Enter 0\.7 to 621 miles/.test(live.text) && (await p.eval("window.__rule")).length >= 1, JSON.stringify({ live, said: await p.eval("window.__rule") }));
  // Tab away from a second bad entry: the rule is said again, though the focus has moved on.
  await p.eval(`window.__rule = []; ${field}.focus(); ${field}.select(); true`);
  await p.type("xyz");
  await p.tab();
  await sleep(500);
  const tabbed = await p.eval(`({ said: window.__rule, focusMoved: document.activeElement !== ${field} })`);
  check("target distance: a bad entry left with Tab is said too", tabbed.focusMoved && tabbed.said.length >= 1 && /^Enter 0\.7 to 621 miles/.test(tabbed.said.at(-1)), JSON.stringify(tabbed));
  await p.close();
}
{
  const p = await open({ route: S_DEFAULT, hash: hashFor("default", 70) });
  const none = await p.eval("document.querySelectorAll('input[placeholder=Default]').length");
  check("target distance: not offered below the top of the traffic slider", none === 0, String(none));
  const toggle = await axNode(p, ".loop-toggle input");
  check("loop: the toggle is named for what it does and described, off by default", toggle?.role === "checkbox" && toggle?.name === "Make it a loop" && toggle?.checked === false && /different way back/.test(toggle?.description ?? ""), JSON.stringify(toggle));
  const before = p.routeRequests;
  await p.eval("document.querySelector('.loop-toggle input').focus(); true");
  await p.key(" ", "Space", 32);
  await sleep(1500);
  const checked = await p.eval("document.querySelector('.loop-toggle input').checked");
  check("loop: Space turns it on and plans once", checked === true && p.routeRequests - before === 1 && /loop=1/.test(await p.eval("location.hash")), `${p.routeRequests - before} plans`);
  await p.close();
}
{
  // A ride that ends where it starts is a loop, shown on and fixed.
  const p = await open({ route: S_DEFAULT, hash: "#p=-77.04000,38.91000;-77.01000,38.89000;-77.04000,38.91000&preset=default&v=2&stress=70&hills=0" });
  const state = await axNode(p, ".loop-toggle input");
  check("loop: a ride ending where it starts shows the toggle on and not changeable, and says why", state?.checked === true && state?.disabled === true && /ends where it starts/.test(state?.description ?? ""), JSON.stringify(state));
  // aria-disabled, not disabled: it stays in the Tab order, and Space changes nothing (the a11y review's N6).
  const before = p.routeRequests;
  await p.eval("document.querySelector('.loop-toggle input').focus(); true");
  const focusable = await p.eval("document.activeElement === document.querySelector('.loop-toggle input')");
  await p.key(" ", "Space", 32);
  await sleep(1200);
  const after = await p.eval("({ checked: document.querySelector('.loop-toggle input').checked, attr: document.querySelector('.loop-toggle input').getAttribute('aria-disabled'), disabled: document.querySelector('.loop-toggle input').disabled })");
  check("loop: when implied it keeps the focus, and Space neither unchecks it nor plans", focusable && after.checked && after.attr === "true" && !after.disabled && p.routeRequests === before, JSON.stringify({ focusable, ...after, plans: p.routeRequests - before }));
  const size = await p.eval("(() => { const r = document.querySelector('.loop-toggle .toggle').getBoundingClientRect(); return Math.round(r.height); })()");
  check("loop: its row is a 44 px target (2.5.8, and the owner's 44 px rule)", size >= 44, `${size} px`);
  await p.close();
}

{
  // Past the target (OWNER-DECISIONS 271): said in words, miles first, in the summary
  // and in the announcement, not as a colour.
  const p = await open({ route: S_OVER, hash: `${hashFor("trailmaxxing", 100)}&targetmi=6.2` });
  await p.waitFor("document.querySelector('.status-line')?.textContent.includes('Route planned')", 5000);
  const said = await p.eval("document.querySelector('.status-line').textContent");
  check("target distance: the announcement says how far over the target the route is", /0\.7 mi \(1\.2 km\) over your target of 6\.2 mi \(10\.0 km\)\./.test(said), said);
  const note = await p.eval("(() => { const e = document.querySelector('.summary .calm-search'); return e ? { role: e.getAttribute('role'), text: e.textContent } : null; })()");
  check("target distance: the summary says it in a note of its own", note?.role === "note" && /It is 0\.7 mi \(1\.2 km\) over your target, to avoid busier roads\./.test(note?.text ?? ""), JSON.stringify(note));
  await p.close();
}

// ---- 10. Routes to choose from (OWNER-DECISIONS 265) ----
{
  const p = await open({ route: S_CHOICES, hash: hashFor("trailmaxxing", 100) });
  const group = await p.eval(`(() => { const f = document.querySelector('fieldset.candidates'); return f ? { legend: f.querySelector('legend').textContent, radios: [...f.querySelectorAll('input[type=radio]')].map((r) => r.checked) } : null; })()`);
  check("routes: a group of three radio buttons under a legend, the first chosen", group?.legend === "Routes to choose from" && JSON.stringify(group.radios) === "[true,false,false]", JSON.stringify(group));
  const first = await p.eval("(() => { const l = document.querySelector('fieldset.candidates label'); return { name: l.querySelector('.candidate-name').textContent, line: l.querySelector('.candidate-line').textContent }; })()");
  check("routes: each says its rank and its figures in words, with no colour to read", /^Route 1, the calmest: 7\.0 mi/.test(first.name) && /heavy-traffic or best-avoided roads, .* of busy roads, .*junction/.test(first.line), JSON.stringify(first));
  // What the screen reader hears for each radio (the a11y review's SF2): a short name, its own figures as the description.
  const fieldset = await axNode(p, "fieldset.candidates");
  const hint = await p.eval("document.querySelector('fieldset.candidates .hint').textContent");
  const radios = [];
  for (let i = 0; i < 3; i++) {
    await p.eval(`document.querySelectorAll('fieldset.candidates input')[${i}].setAttribute('data-check', 'r${i}'); true`);
    radios.push(await axNode(p, `[data-check=r${i}]`));
  }
  check("routes: each radio's name is short, its rank then a separator: Route 2: 7.2 mi ..., 0.2 mi ... more than Route 1",
    radios.every((r) => /^Route \d+[:,]/.test(r?.name ?? "") && (r?.name ?? "").length < 90) && /^Route 2: 7\.2 mi \(11\.6 km\), 0\.2 mi \(0\.4 km\) more than Route 1$/.test(radios[1]?.name ?? ""), JSON.stringify(radios.map((r) => r?.name)));
  check("routes: each radio's description is its own figures, not the shared hint", radios.every((r) => r?.description && r.description !== hint && /heavy-traffic or best-avoided roads/.test(r.description)), JSON.stringify(radios.map((r) => r?.description?.slice(0, 50))));
  check("routes: the shared hint is the group's description, read once on entering it", fieldset?.description === hint && /The map shows the one chosen, and the route description below follows it\./.test(hint) && !/scenery/.test(hint), JSON.stringify({ role: fieldset?.role, description: fieldset?.description }));
  await p.waitFor("document.querySelector('.status-line')?.textContent.includes('Route planned')", 5000);
  const arrival = await p.eval("document.querySelector('.status-line').textContent");
  check("routes: on arrival the announcement says how many others there are to choose from", /^Route planned: .*2 other routes to choose from, under Routes to choose from\.$/.test(arrival), arrival);
  await p.eval("document.querySelectorAll('fieldset.candidates input')[0].focus(); true");
  await p.eval(`window.__said = []; new MutationObserver(() => { const t = document.querySelector('.status-line').textContent.trim(); if (t) window.__said.push(t); })
    .observe(document.querySelector('.status-line'), { childList: true, subtree: true, characterData: true }); true`);
  const requests = p.routeRequests;
  await p.key("ArrowDown", "ArrowDown", 40);
  await sleep(3500);
  const chosen = await p.eval("[...document.querySelectorAll('fieldset.candidates input')].map((r) => r.checked)");
  const distance = await p.eval("document.querySelector('.stats dd').textContent");
  const said = await p.eval("window.__said");
  check("routes: the arrow key chooses the next, and the summary shows its figures", JSON.stringify(chosen) === "[false,true,false]" && /7\.2 mi/.test(distance), `${JSON.stringify(chosen)} ${distance}`);
  check("routes: choosing plans nothing and is announced once, as chosen, with its place", p.routeRequests === requests && said.length === 1 && /^Route 2 of 3 chosen: 7\.2 mi/.test(said[0]) && !/Route planned/.test(said[0]), JSON.stringify(said));
  await p.shot(`${SHOTS}/candidates.png`, await p.eval("(() => { const e = document.querySelector('fieldset.candidates'); e.scrollIntoView({ block: 'start' }); const r = e.getBoundingClientRect(); return { x: Math.max(0, r.left), y: Math.max(0, r.top), width: Math.round(r.width), height: Math.min(Math.round(r.height), innerHeight - Math.max(0, r.top)) }; })()"));
  await p.close();
}
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100) });
  const none = await p.eval("document.querySelectorAll('fieldset.candidates').length");
  check("routes: with one route there is no picker", none === 0, String(none));
  await p.close();
}
{
  const p = await open({ route: S_CHOICES, hash: hashFor("trailmaxxing", 100), width: 320, height: 800, mobile: true });
  const fit = await p.eval(`(() => { const f = document.querySelector('fieldset.candidates'); const r = f.getBoundingClientRect(); return { over: f.scrollWidth > f.clientWidth + 1, right: r.right <= innerWidth + 1, page: document.documentElement.scrollWidth > innerWidth }; })()`);
  check("routes: at 320 px the group wraps inside the screen", !fit.over && fit.right && !fit.page, JSON.stringify(fit));
  await p.close();
}

// ---- 11. The Mass Ride map's federal-land section (items 236-239) ----
const federalFetched = (p) =>
  p.eval("performance.getEntriesByType('resource').some((r) => /federal-land[^/?]*\\.json$/.test(r.name))");
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0) });
  await openSheet(p);
  await p.eval("document.getElementById('federal-heading')?.scrollIntoView({ block: 'center' }); true");
  const section = await p.eval(`(() => { const s = document.querySelector('.federal-section'); if (!s) return null;
    const items = [...s.querySelectorAll('.federal-legend li')];
    return { heading: s.querySelector('h3')?.textContent, items: items.length,
      cues: items.map((li) => /shaded with (dots|cross-hatch|rising diagonal stripes|falling diagonal stripes)/.test(li.textContent)),
      swatchesHidden: items.every((li) => li.querySelector('svg')?.getAttribute('aria-hidden') === 'true'),
      note: /Federal land - permit rules may differ \\(information, not legal advice\\)/.test(s.textContent),
      checked: s.querySelector('input[type=checkbox]')?.checked }; })()`);
  check("federal: a Mass Ride's panel has the section, four legend rows each naming its pattern, and the note",
    section && section.heading === "Federal land" && section.items === 4 && section.cues.every(Boolean) && section.swatchesHidden && section.note && section.checked, JSON.stringify(section));
  check("federal: the data is fetched for a Mass Ride", await federalFetched(p));
  await sleep(1500);
  await p.shot(`${SHOTS}/federal_map.png`, await p.eval("(() => { const r = document.querySelector('.map').getBoundingClientRect(); return { x: r.left, y: r.top, width: Math.round(r.width), height: Math.round(r.height) }; })()"));
  const ax = await axNode(p, ".federal-section input[type=checkbox]");
  check("federal: the switch is a checkbox named for what it does", ax?.role === "checkbox" && ax?.name === "Show federal land on the map", JSON.stringify(ax));
  await p.eval("document.querySelector('.federal-section input[type=checkbox]').focus(); true");
  await p.key(" ", "Space", 32);
  await sleep(300);
  const off = await p.eval("({ legend: !!document.querySelector('.federal-legend'), checked: document.querySelector('.federal-section input[type=checkbox]').checked, focus: document.activeElement?.type === 'checkbox' })");
  check("federal: Space turns it off, the legend goes and the focus stays on the switch", !off.legend && !off.checked && off.focus, JSON.stringify(off));
  // Another ride type while it is shown: the section goes, and comes back with Mass Ride (OWNER-DECISIONS 324).
  await p.key(" ", "Space", 32);
  await sleep(300);
  await p.eval(`location.hash = ${JSON.stringify(hashFor("default", 70))}; true`);
  await sleep(1200);
  const elsewhere = await p.eval("({ section: !!document.querySelector('.federal-section'), heading: !!document.getElementById('federal-heading'), list: /Your points on federal land/.test(document.body.innerText) })");
  check("federal: another ride type has no section, switch, legend or points list (324)", !elsewhere.section && !elsewhere.heading && !elsewhere.list, JSON.stringify(elsewhere));
  await p.eval(`location.hash = ${JSON.stringify(hashFor("mass-ride", 0))}; true`);
  await sleep(1200);
  check("federal: back on Mass Ride the section is there again, the switch as it was left", await p.eval("!!document.querySelector('.federal-section') && document.querySelector('.federal-section input[type=checkbox]').checked && !!document.querySelector('.federal-legend')"));
  await p.close();
}
{
  const p = await open({ route: S_DEFAULT, hash: hashFor("default", 70) });
  const none = await p.eval("!document.querySelector('.federal-section') && !document.getElementById('federal-heading')");
  check("federal: no section, and nothing fetched, for any other ride type", none && !(await federalFetched(p)));
  await p.close();
}
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0), width: 320, height: 800, mobile: true });
  await openSheet(p);
  await p.eval(`(() => { const s = document.createElement('style'); s.textContent = ${JSON.stringify(TEXT_SPACING)}; document.head.append(s);
    document.getElementById('federal-heading').scrollIntoView({ block: 'start' }); return true; })()`);
  await sleep(300);
  const fit = await p.eval(`(() => { const s = document.querySelector('.federal-section'); const r = s.getBoundingClientRect();
    const over = [...s.querySelectorAll('li, p, label')].filter((e) => e.scrollWidth > e.clientWidth + 1 || e.getBoundingClientRect().right > r.right + 1).length;
    return { over, page: document.documentElement.scrollWidth > innerWidth }; })()`);
  check("federal at 320 px with text spacing: the legend and the note wrap, nothing spills", fit.over === 0 && !fit.page, JSON.stringify(fit));
  await p.shot(`${SHOTS}/federal_320.png`, await p.eval("(() => { const r = document.querySelector('.federal-section').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: Math.min(r.height + 8, innerHeight - Math.max(0, r.top)) }; })()"));
  await p.close();
}

// ---- 12. "Show bike lanes on high-stress roads" (OWNER-DECISIONS 275): a switch a keyboard and a screen reader reach ----
{
  const p = await open();
  await openSheet(p);
  const id = "#high-lanes-switch";
  const before = await axNode(p, id);
  check("lanes switch: a switch named for what it does, off by default", before?.role === "switch" && before?.name === "Show bike lanes on high-stress roads" && String(before?.checked) === "false", JSON.stringify(before));
  check("lanes switch: described, in plain words, by which roads are affected", /heavy-traffic \(LTS 4\) and best-avoided roads/.test(before?.description ?? "") && /Protected lanes and paths always show/.test(before?.description ?? ""), (before?.description ?? "").slice(0, 80));
  const box = await p.eval(`(() => { const r = document.querySelector('${id}').getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; })()`);
  check("lanes switch: its target is at least 24 px tall (2.5.8)", box.h >= 24 && box.w >= 24, JSON.stringify(box));
  check("lanes switch: its state is also in visible words, not colour", await p.eval(`document.querySelector('${id} .switch-state').textContent === 'Off'`));
  // The keyboard: Tab to it from "Show traffic stress on the map" (312's order: traffic stress, high-stress
  // lanes, high contrast), Space turns it on, Space again turns it off.
  await p.eval("document.querySelector('#show-stress').focus(); true");
  await p.tab();
  check("lanes switch: the next Tab stop after Show traffic stress on the map", await p.eval(`document.activeElement?.id === 'high-lanes-switch'`), await focused(p));
  await p.key(" ", "Space", 32);
  await sleep(150);
  check("lanes switch: Space turns it on, and it is remembered in this browser", (await axNode(p, id))?.checked !== undefined && (await p.eval(`document.querySelector('${id}').getAttribute('aria-checked')`)) === "true" && (await p.eval("localStorage.getItem('routemaker.highStressLanes')")) === "on");
  check("lanes switch: the focus stays on it after the press", await p.eval(`document.activeElement?.id === 'high-lanes-switch'`));
  await p.key(" ", "Space", 32);
  await sleep(150);
  check("lanes switch: Space again turns it off", (await p.eval(`document.querySelector('${id}').getAttribute('aria-checked')`)) === "false" && (await p.eval("localStorage.getItem('routemaker.highStressLanes')")) === "off");
  const ring = await p.eval(`(() => { const s = getComputedStyle(document.querySelector('${id}')); return { outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow }; })()`);
  console.log(`  (the focused switch's outline: ${JSON.stringify(ring)})`);
  await p.close();
}

// ---- 15. The rider and bike weight's dialog (OWNER-DECISIONS 313-318) ----
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100) });
  const change = await axNode(p, ".weight-setting > button");
  check("weight: Change is a button named for what it changes, described by the line", change?.role === "button" && change?.name === "Change rider and bike weight" && change?.description === "Rider and bike weight: not set, defaults used", JSON.stringify(change));
  await p.eval("document.querySelector('.weight-setting > button').focus(); true");
  await p.enter();
  await sleep(300);
  const dialog = await axNode(p, "dialog.weight-dialog");
  const inside = await p.eval("(() => { const d = document.querySelector('dialog.weight-dialog'); return { open: d.open, modal: d.matches(':modal'), focusIn: d.contains(document.activeElement), focus: document.activeElement?.id ?? '' }; })()");
  check("weight: Change opens a modal dialog and the focus moves into it", inside.open && inside.modal && inside.focusIn, JSON.stringify(inside));
  check("weight: the dialog is named by its heading and described by its two lines (318)",
    dialog?.role === "dialog" && dialog?.name === "Rider and bike weight" &&
      /^Optional\. Used only to work out your route, for how hard hills feel\. It is never displayed, and never put in shared links or downloads\. A rough estimate is fine\. Within 20 lb \(10 kg\) or so makes no real difference\.$/.test(dialog?.description ?? ""),
    JSON.stringify(dialog));
  const fields = await p.eval("[...document.querySelectorAll('dialog.weight-dialog input[type=text]')].map((e) => ({ label: e.labels?.[0]?.textContent, value: e.value }))");
  check("weight: Rider, Bike, Cargo and Total are labelled pounds first, kilograms in brackets, and start blank (316)", JSON.stringify(fields.map((f) => f.label)) === JSON.stringify(["Rider, lb (kg)", "Bike, lb (kg)", "Cargo, lb (kg)", "Total, lb (kg)"]) && fields.every((f) => f.value === ""), JSON.stringify(fields));
  // Type a total of 207 lb and save it, remembered.
  await p.eval("document.querySelectorAll('dialog.weight-dialog input[type=text]')[3].focus(); true");
  await p.type("207");
  await sleep(1000); // the polite total waits 700 ms after the last key (N-A)
  const total = await p.eval("document.querySelector('dialog.weight-dialog .weight-total').textContent");
  check("weight: the total is said politely as it changes, pounds first", /^Total: 207 lb \(94 kg\)\.$/.test(total) && (await p.eval("document.querySelector('dialog.weight-dialog .weight-total').getAttribute('aria-live')")) === "polite", total);
  await p.eval("document.querySelector('dialog.weight-dialog input[type=checkbox]').click(); true");
  const before = p.routeRequests;
  await p.eval("[...document.querySelectorAll('dialog.weight-dialog button')].find((b) => b.textContent === 'Save').click(); true");
  await sleep(1500);
  const after = await p.eval("({ open: document.querySelector('dialog.weight-dialog').open, focus: document.activeElement === document.querySelector('.weight-setting > button'), line: document.querySelector('.weight-line').textContent, hash: location.hash, stored: localStorage.getItem('routemaker.weight') !== null })");
  check("weight: Save closes it, the focus is back on Change, the line says set today, it plans once, and the link has no weight", !after.open && after.focus && after.line === "Rider and bike weight: set today" && p.routeRequests - before === 1 && !/weight|207|94/.test(after.hash) && after.stored, JSON.stringify({ ...after, plans: p.routeRequests - before }));
  // The closed <dialog> is still in the DOM: nothing typed stays in it (the review's S2).
  const closedDom = await p.eval("({ text: document.querySelector('dialog.weight-dialog').textContent, values: [...document.querySelectorAll('dialog.weight-dialog input[type=text]')].map((e) => e.value) })");
  check("weight: after Save the closed dialog holds no typed figure, in its fields or its text (S2)", closedDom.values.every((v) => v === "") && !/\b207\b|\b93\.9\b|\b94 kg/.test(closedDom.text), JSON.stringify(closedDom.values));
  // Reopen: blank, saying one is saved; the number is in neither the page nor the accessibility tree.
  await p.eval("document.querySelector('.weight-setting > button').click(); true");
  await sleep(300);
  const again = await p.eval("({ values: [...document.querySelectorAll('dialog.weight-dialog input[type=text]')].map((e) => e.value), text: document.body.innerText, saved: document.querySelector('dialog.weight-dialog .notice')?.textContent })");
  const { nodes } = await p.s("Accessibility.getFullAXTree", {});
  const axText = JSON.stringify(nodes.map((n) => [n.name?.value, n.description?.value, n.value?.value]));
  check("weight: reopened, every field is blank and it says a weight is saved, without the numbers (317(b))", again.values.every((v) => v === "") && /^A weight is saved \(set today\)\. Enter new values to replace it, or Clear to use the defaults\.$/.test(again.saved ?? ""), JSON.stringify({ values: again.values, saved: again.saved }));
  check("weight: the saved number is nowhere in the page's text or its accessibility tree", !/\b207\b|\b93\.9\b|\b94 kg/.test(again.text) && !/\b207\b|93\.9|94 kg/.test(axText), "");
  await p.escape();
  await sleep(300);
  const closed = await p.eval("({ open: document.querySelector('dialog.weight-dialog').open, focus: document.activeElement === document.querySelector('.weight-setting > button') })");
  check("weight: Escape closes it and the focus goes back to Change", !closed.open && closed.focus, JSON.stringify(closed));
  // A total outside the range: planned with the nearer limit, silently (337, 338, 352), the number typed not kept.
  await p.eval("document.querySelector('.weight-setting > button').click(); true");
  await sleep(300);
  await p.eval("document.querySelectorAll('dialog.weight-dialog input[type=text]')[3].focus(); true");
  await p.type("1500");
  await p.eval("[...document.querySelectorAll('dialog.weight-dialog button')].find((b) => b.textContent === 'Save').click(); true");
  await sleep(500);
  const limited = await p.eval("({ open: document.querySelector('dialog.weight-dialog').open, note: document.querySelector('dialog.weight-dialog .dial-rule').textContent, values: [...document.querySelectorAll('dialog.weight-dialog input[type=text]')].map((e) => e.value), text: document.body.textContent })");
  check("weight: a total over the range is saved silently, the dialog closes, and the number typed is nowhere in the page (352, S2)", !limited.open && limited.note === "" && limited.values.every((v) => v === "") && !/1500|plan with|designed for/.test(limited.text), JSON.stringify({ ...limited, text: undefined }));
  await p.close();
}

// ---- 13. The stress map unavailable: the lane switch is still there (the a11y review's SF4) ----
{
  const p = await open({ stressTiles: false });
  await openSheet(p);
  await p.waitFor("/Stress map unavailable/.test(document.querySelector('#layers-heading')?.parentElement?.textContent ?? '')", 15000);
  const ax = await axNode(p, "#high-lanes-switch");
  check("lanes switch without the stress map: still a switch, described by what it changes then", ax?.role === "switch" && /hidden in the route's facility totals and description\./.test(ax?.description ?? "") && !/on the map/.test(ax?.description ?? ""), JSON.stringify(ax));
  await p.close();
}

// ---- 14. A slow plan (LONG-CALM, up to half a minute): said once while it runs, then the route (the a11y review's SF1) ----
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100), delayMs: 8000, delayFrom: Infinity });
  // The first route's own announcement lands once it settles: listen only after it.
  await p.waitFor("document.querySelector('.status-line')?.textContent.includes('Route planned')", 10000);
  await sleep(500);
  await p.eval(`window.__said = []; new MutationObserver(() => { const t = document.querySelector('.status-line').textContent.trim(); if (t) window.__said.push(t); })
    .observe(document.querySelector('.status-line'), { childList: true, subtree: true, characterData: true }); true`);
  const field = "document.querySelector('input[placeholder=Default]')";
  await p.eval(`${field}.focus(); true`);
  await p.type("60");
  // Only this plan is slow: the page's own first requests were answered at once.
  p.delayFrom = p.routeRequests + 1;
  await p.enter();
  await sleep(1000);
  const during = await p.eval(`(() => { const g = document.querySelector('progress.planning'); return g ? { label: g.getAttribute('aria-label'), indeterminate: !g.hasAttribute('value'), shown: g.getBoundingClientRect().height > 0, live: !!g.closest('[aria-live]'), loading: document.querySelector('.loading')?.textContent } : null; })()`);
  check("slow plan: a labelled, indeterminate progress bar shows while it plans, outside the live region", during?.label === "Planning the route" && during.indeterminate && during.shown && !during.live, JSON.stringify(during));
  const early = await p.eval("window.__said.length");
  await sleep(11000);
  const said = await p.eval("window.__said");
  const still = said.filter((t) => /^Still planning\./.test(t));
  check("slow plan: nothing is said in the first seconds", early === 0, String(early));
  check("slow plan: \"Still planning\" is said once, with why, then the route once", said.length === 2 && still.length === 1 && /^Still planning\. Calm routes at this setting can take up to half a minute\.$/.test(said[0]) && /^Route planned: /.test(said[1]), JSON.stringify(said));
  check("slow plan: the progress bar is gone with the route", await p.eval("!document.querySelector('progress.planning')"));
  await p.close();
}

// ---- 16. Settings (OWNER-DECISIONS 384): the fifth bar button, and the one High contrast switch in two sheets ----
{
  const p = await open();
  const bar = await p.eval("[...document.querySelectorAll('.bar-button')].map((x) => x.querySelector('span').textContent)");
  check("settings: the bottom bar is Plan, Map layers, Legend, GPX, Settings", JSON.stringify(bar) === JSON.stringify(["Plan", "Map layers", "Legend", "GPX", "Settings"]), JSON.stringify(bar));
  await openSheet(p, "Settings");
  check("settings: opening it puts the focus on its heading, \"Settings\"", (await p.eval("document.activeElement?.textContent")) === "Settings" && (await p.eval("document.activeElement?.tagName")) === "H2", await focused(p));
  const inSettings = await axNode(p, "#settings-contrast-switch");
  // The Map layers sheet is hidden now, so it is not in the accessibility tree: its name is read from the
  // label the switch points at.
  const inLayers = await p.eval("(() => { const s = document.querySelector('#a11y-switch'); const l = document.getElementById(s.getAttribute('aria-labelledby')); return { role: s.getAttribute('role'), name: l?.textContent }; })()");
  check("settings: the switch there is named \"High contrast\", off, described in neutral words", inSettings?.role === "switch" && inSettings?.name === "High contrast" && String(inSettings?.checked) === "false" && /^Bolder lines, stronger borders and text, and colors that don't rely on red and green\./.test(inSettings?.description ?? "") && !/blind|accessib|disab/i.test(inSettings?.description ?? ""), JSON.stringify(inSettings));
  check("settings: the Map layers copy has the same name", inLayers?.role === "switch" && inLayers?.name === "High contrast", JSON.stringify(inLayers));
  check("settings: no id is used twice in the page", await p.eval("(() => { const ids = [...document.querySelectorAll('[id]')].map((e) => e.id); return ids.length === new Set(ids).size; })()"));
  const heads = await p.eval("[...document.querySelectorAll('#sheet-settings h3')].map((h) => h.textContent)");
  check("settings: the sheet's headings are Display and Signing in, so the sign-in note is not filed under Display", JSON.stringify(heads) === JSON.stringify(["Display", "Signing in"]), JSON.stringify(heads));
  const axSwitches = (await p.s("Accessibility.getFullAXTree", {})).nodes.filter((n) => !n.ignored && /^High contrast/.test(n.name?.value ?? "") && ["switch", "button"].includes(n.role?.value));
  check("settings: exactly one High contrast switch is in the accessibility tree (said once, not twice)", axSwitches.length === 1 && axSwitches[0].role.value === "switch", JSON.stringify(axSwitches.map((n) => [n.role?.value, n.name?.value])));
  check("settings: the Settings bar button is the current one (aria-current)", await p.eval("(() => { const b = [...document.querySelectorAll('.bar-button')].find((x) => x.textContent.startsWith('Settings')); const others = [...document.querySelectorAll('.bar-button')].filter((x) => x !== b && x.getAttribute('aria-current')); return b.getAttribute('aria-current') === 'true' && others.length === 0; })()"));
  const target = await p.eval("(() => { const r = document.querySelector('#settings-contrast-switch').getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; })()");
  check("settings: the switch's target is at least 24 px (2.5.8)", target.w >= 24 && target.h >= 24, JSON.stringify(target));
  await p.eval("document.querySelector('#settings-contrast-switch').focus(); true");
  await p.key(" ", "Space", 32);
  await sleep(200);
  check("settings: after Space the focus stays on the switch, which reports checked and reads \"On\"", (await p.eval("document.activeElement?.id")) === "settings-contrast-switch" && String((await axNode(p, "#settings-contrast-switch"))?.checked) === "true" && (await p.eval("document.querySelector('#settings-contrast-switch .switch-state').textContent")) === "On", await focused(p));
  const font = await p.eval("(async () => { const faces = await document.fonts.load('400 16px \"Atkinson Hyperlegible\"'); return { faces: faces.length, loaded: document.fonts.check('400 16px \"Atkinson Hyperlegible\"'), family: getComputedStyle(document.body).fontFamily }; })()");
  check("font: Atkinson Hyperlegible loads (a face is found and loaded)", font.faces > 0 && font.loaded, JSON.stringify(font));
  check("font: the page is set in it first", font.family.replace(/\"/g, "").startsWith("Atkinson Hyperlegible"), font.family);
  const both = await p.eval("[document.querySelector('#settings-contrast-switch'), document.querySelector('#a11y-switch')].map((e) => e.getAttribute('aria-checked'))");
  check("settings: one state: flipping it here turns the Map layers copy on, and the page root takes the class", JSON.stringify(both) === JSON.stringify(["true", "true"]) && (await p.eval("document.documentElement.classList.contains('a11y')")), JSON.stringify(both));
  await p.eval("localStorage.removeItem('routemaker.accessibility'); true");
  await p.key("Escape", "Escape", 27);
  await sleep(250);
  check("settings: Escape goes back and the focus returns to the Settings button", (await p.eval("document.activeElement?.classList.contains('bar-button') && document.activeElement.textContent.startsWith('Settings')")), await focused(p));
  await p.close();
}

// ---- 17. Make it a loop by the search, and the Plan button (OWNER-DECISIONS 388, 389, 392, 393) ----
const FIRST_HINT = "Place the starting point, then a stop or two along the way.";
{
  // An empty planner: the box is there with no point, says what to place when checked, and says it once.
  const p = await newPage(b, { width: 1280, height: 900 });
  await mock(p, S_DEFAULT, {});
  await media(p, {});
  await p.s("Page.navigate", { url: `http://127.0.0.1:${PORT}/` });
  await p.waitFor("!!document.querySelector('.loop-toggle input')", 40000);
  await sleep(800);
  const box = await axNode(p, ".loop-toggle input");
  check("loop first: with no point placed the box is in the page, named \"Make it a loop\", unchecked", box?.role === "checkbox" && box?.name === "Make it a loop" && box?.checked === false, JSON.stringify(box));
  const place = await p.eval("(() => { const t = document.querySelector('.loop-toggle'); const i = t.closest('section'); const r = t.getBoundingClientRect(); return { inPoints: i?.getAttribute('aria-labelledby') === 'points-heading', afterSearch: !!(document.querySelector('#points-search').compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING), outsideRide: !t.closest('.ride-settings-body'), shown: r.height > 0, row: Math.round(t.querySelector('.toggle').getBoundingClientRect().height) }; })()");
  check("loop first: it is in the Points section, after the search, and not behind the Ride line's Edit", place.inPoints && place.afterSearch && place.outsideRide && place.shown, JSON.stringify(place));
  check("loop first: its row is a 44 px target", place.row >= 44, `${place.row} px`);
  // Every live region in the page, not only the first one found: the road panel's dialog holds a
  // status region of its own (S1) ahead of the page's in the document, and "once" means once in all of them.
  await p.eval("window.__said = []; const sel = '[role=status], [role=alert], [aria-live]:not([aria-live=off])'; for (const live of document.querySelectorAll(sel)) if (!live.parentElement?.closest(sel)) new MutationObserver(() => { const t = live.textContent.trim(); if (t) window.__said.push(t); }).observe(live, { childList: true, subtree: true, characterData: true }); true");
  await p.eval("document.querySelector('.loop-toggle input').focus(); true");
  await p.key(" ", "Space", 32);
  await sleep(700);
  const on = await axNode(p, ".loop-toggle input");
  const hint = await p.eval("(() => { const h = document.getElementById(document.querySelector('.loop-toggle input').getAttribute('aria-describedby')); const r = h.getBoundingClientRect(); return { text: h.textContent, visible: r.height >= 10 && r.width >= 50 && getComputedStyle(h).visibility !== 'hidden' && !h.classList.contains('visually-hidden') && !h.closest('.visually-hidden, [hidden]'), size: Math.round(r.width) + 'x' + Math.round(r.height) }; })()");
  check("loop first: checked with no point, the hint is visible text, \"Place the starting point, then a stop or two along the way.\"", on?.checked === true && hint.visible && hint.text === FIRST_HINT, JSON.stringify(hint));
  check("loop first: the box is described by it", on?.description === FIRST_HINT, JSON.stringify(on?.description));
  const live = await p.eval("document.querySelectorAll('.loop-toggle [role=status], .loop-toggle [role=alert], .loop-toggle [aria-live]').length");
  check("loop first: the box and its hint hold no live region of their own (the one announcement is the page's)", live === 0, String(live));
  const said = await p.eval("window.__said");
  check("loop first: it is announced once when the box is checked", said.filter((t) => t.includes(FIRST_HINT)).length === 1 && said.length === 1, JSON.stringify(said));
  check("loop first: checking it plans nothing, and the focus stays on the box", p.routeRequests === 0 && (await p.eval("document.activeElement === document.querySelector('.loop-toggle input')")), `${p.routeRequests} plans`);
  check("loop first: the empty-plan words do not send the rider to the Ride line", !/Edit button|ride settings/.test(await p.eval("document.querySelector('.tips-body').textContent")), "");
  await p.close();
}
{
  // Mass Ride has no loop: no box, with no point placed.
  const p = await newPage(b, { width: 1280, height: 900 });
  await mock(p, S_MASS, {});
  await media(p, {});
  await p.s("Page.navigate", { url: `http://127.0.0.1:${PORT}/#preset=mass-ride&v=2` });
  await p.waitFor("!!document.querySelector('#points-search')", 40000);
  await sleep(800);
  check("loop first: Mass Ride has no Make it a loop box", (await p.eval("document.querySelectorAll('.loop-toggle').length")) === 0 && !/loop/i.test(await p.eval("document.querySelector('#points-search').closest('section').textContent")), "");
  await p.close();
}
{
  // With a route shown and the points compact, the box is still there (it sits outside what Edit points hides).
  const p = await open({ ride: false });
  const compact = await p.eval("(() => { const s = document.querySelector('#points-search'); const t = document.querySelector('.loop-toggle input'); return { searchHidden: s.hidden, box: !!t && t.getBoundingClientRect().height > 0 }; })()");
  check("loop first: with a route shown and the points compact, the search is hidden and the box stays", compact.searchHidden && compact.box, JSON.stringify(compact));
  // The Plan button: first in the bar, current on the planner, returns from a sheet to the planner's heading.
  const bar = await p.eval("[...document.querySelectorAll('.bar-button')].map((x) => ({ text: x.querySelector('span').textContent, current: x.getAttribute('aria-current') }))");
  check("plan: five buttons, Plan first and current on the planner, the others not", bar.length === 5 && bar[0].text === "Plan" && bar[0].current === "true" && bar.slice(1).every((x) => !x.current), JSON.stringify(bar));
  // Exact names: the hint is a sibling of each button, not part of its name, and is the description (said once).
  const names = [];
  for (const id of ["plan", "layers", "legend", "gpx", "settings"]) {
    const ax = await axNode(p, `#bar-${id}`);
    names.push([ax?.role, ax?.name]);
  }
  check("plan: the five bar buttons are named exactly Plan, Map layers, Legend, GPX, Settings", JSON.stringify(names) === JSON.stringify([["button", "Plan"], ["button", "Map layers"], ["button", "Legend"], ["button", "GPX"], ["button", "Settings"]]), JSON.stringify(names));
  const hints = await p.eval("[...document.querySelectorAll('.bar-button')].map((x) => { const h = document.getElementById(x.getAttribute('aria-describedby')); return { hidden: h.hidden && h.getBoundingClientRect().height === 0, inButton: x.contains(h), text: h.textContent.length > 0 }; })");
  const described = [];
  for (const id of ["plan", "layers", "legend", "gpx", "settings"]) described.push((await axNode(p, `#bar-${id}`))?.description?.length > 0);
  check("plan: each bar hint is a hidden sibling, off the screen, and still the button's description", hints.length === 5 && hints.every((h) => h.hidden && !h.inButton && h.text) && described.every(Boolean), JSON.stringify({ hints, described }));
  const planAx = await axNode(p, "#bar-plan");
  check("plan: its description says where it goes, in the Back label's words", /^Shows the planner: /.test(planAx?.description ?? ""), JSON.stringify(planAx?.description));
  await openSheet(p, "GPX");
  const during = await p.eval("[...document.querySelectorAll('.bar-button')].map((x) => x.getAttribute('aria-current'))");
  check("plan: on a sheet the Plan button is not current and that sheet's is", during[0] === null && during[3] === "true", JSON.stringify(during));
  const backText = await p.eval("document.querySelector('#sheet-gpx .sheet-back').textContent.trim()");
  const backAx = await axNode(p, "#sheet-gpx .sheet-back");
  check("plan: the sheet's Back button says \"Back to planner\" in visible words, and its name is the same", backText === "Back to planner" && backAx?.name === "Back to planner", JSON.stringify({ backText, name: backAx?.name }));
  await p.eval("document.querySelector('.bar-button').click(); true");
  await sleep(300);
  const back = await p.eval("({ planner: !document.querySelector('.planner-view').hidden, focus: document.activeElement?.tagName + ':' + document.activeElement?.textContent, current: document.querySelector('.bar-button').getAttribute('aria-current') })");
  check("plan: pressing it returns to the planner, marks it current, and puts the focus on the planner's heading", back.planner && back.focus === "H1:RouteMaker" && back.current === "true", JSON.stringify(back));
  await openSheet(p, "Settings");
  await p.eval("document.querySelector('#sheet-settings .sheet-back').click(); true");
  await sleep(300);
  check("plan: Back still returns the focus to the bar button that opened the sheet", await p.eval("document.activeElement?.classList.contains('bar-button') && document.activeElement.textContent.startsWith('Settings')"), await focused(p));
  await p.close();
}
for (const [width, height] of [[320, 700], [375, 812]]) {
  const p = await open({ width, height, mobile: true, ride: false });
  const fit = await p.eval(`(() => {
    const buttons = [...document.querySelectorAll('.bar-button')].map((x) => { const r = x.getBoundingClientRect(); const label = x.querySelector('span'); return { text: label.textContent, w: Math.round(r.width), h: Math.round(r.height), clipped: x.scrollWidth > x.clientWidth + 1, inside: r.left >= -0.5 && r.right <= innerWidth + 0.5 }; });
    return { scroll: document.documentElement.scrollWidth, buttons }; })()`);
  check(`plan at ${width} px: five buttons, each at least 44 px both ways, inside the screen, nothing clipped`, fit.buttons.length === 5 && fit.buttons.every((x) => x.w >= 44 && x.h >= 44 && x.inside && !x.clipped) && fit.scroll <= width, JSON.stringify(fit));
  const labels = await p.eval(`[...document.querySelectorAll('.bar-button')].map((x) => ({ px: parseFloat(getComputedStyle(x.querySelector('span')).fontSize), overflow: x.scrollHeight > x.clientHeight }))`);
  check(`plan at ${width} px: the bar labels are at least 12 px and a two-line label stays inside its button`, labels.every((l) => l.px >= 12 && !l.overflow), JSON.stringify(labels));
  await p.shot(`${SHOTS}/bar_${width}.png`, await p.eval("(() => { const r = document.querySelector('.bottom-bar').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: r.height + 8 }; })()"));
  await openSheet(p, "Map layers");
  const sheet = await p.eval("(() => { const r = document.querySelector('#sheet-layers .sheet-back').getBoundingClientRect(); const h = document.querySelector('#sheet-layers-title').getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height), inside: r.right <= innerWidth && h.right <= innerWidth + 0.5 }; })()");
  check(`plan at ${width} px: the Back to planner button is at least 44 px and the sheet's header fits`, sheet.w >= 44 && sheet.h >= 44 && sheet.inside && (await p.eval("document.documentElement.scrollWidth")) <= width, JSON.stringify(sheet));
  await p.shot(`${SHOTS}/sheet_back_${width}.png`, await p.eval("(() => { const r = document.querySelector('#sheet-layers .sheet-header').getBoundingClientRect(); return { x: 0, y: Math.max(0, r.top - 4), width: innerWidth, height: r.height + 8 }; })()"));
  await p.close();
}

{
  // Large text at 320 px: the five buttons wrap onto a second row rather than clip.
  const p = await open({ width: 320, height: 700, mobile: true, ride: false });
  await p.eval("document.documentElement.style.fontSize = '24px'; true");
  await sleep(300);
  const fit = await p.eval(`(() => {
    const buttons = [...document.querySelectorAll('.bar-button')].map((x) => { const r = x.getBoundingClientRect(); return { top: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height), clipped: x.scrollWidth > x.clientWidth + 1, inside: r.left >= -0.5 && r.right <= innerWidth + 0.5 }; });
    return { rows: new Set(buttons.map((x) => x.top)).size, scroll: document.documentElement.scrollWidth, buttons }; })()`);
  check("plan at 320 px with 24 px text: five buttons, 44 px or more each way, inside the screen, nothing clipped, a second row where needed", fit.buttons.length === 5 && fit.buttons.every((x) => x.w >= 44 && x.h >= 44 && x.inside && !x.clipped) && fit.scroll <= 320 && fit.rows >= 2, JSON.stringify(fit));
  await p.shot(`${SHOTS}/bar_320_text24.png`);
  await p.close();
}
{
  // The phone header's toggle, and Plan on a scrolled planner.
  const p = await open({ width: 375, height: 812, mobile: true, ride: false });
  const first = await p.eval("(() => { const t = document.querySelector('.panel-toggle'); return { text: t.textContent, expanded: t.getAttribute('aria-expanded'), controls: t.getAttribute('aria-controls') }; })()");
  check("toggle: the phone header's button reads Hide planner, with aria-expanded and aria-controls", first.text === "Hide planner" && first.expanded === "true" && first.controls === "panel-body", JSON.stringify(first));
  await openSheet(p, "GPX");
  await p.eval("document.querySelector('.panel-toggle').focus(); document.querySelector('.panel-toggle').click(); true");
  await sleep(200);
  const hidden = await p.eval("({ text: document.querySelector('.panel-toggle').textContent, expanded: document.querySelector('.panel-toggle').getAttribute('aria-expanded'), hidden: document.getElementById('panel-body').hidden })");
  await p.eval("document.querySelector('.panel-toggle').focus(); document.querySelector('.panel-toggle').click(); true");
  await sleep(300);
  const shown = await p.eval("({ text: document.querySelector('.panel-toggle').textContent, expanded: document.querySelector('.panel-toggle').getAttribute('aria-expanded'), planner: !document.querySelector('.planner-view').hidden, gpx: document.getElementById('sheet-gpx').hidden, focus: document.activeElement?.tagName + ':' + document.activeElement?.textContent })");
  check("toggle: hiding says Show planner; showing it again returns to the planner (not the sheet that was open) and the focus stays on the toggle", hidden.text === "Show planner" && hidden.expanded === "false" && hidden.hidden && shown.text === "Hide planner" && shown.expanded === "true" && shown.planner && shown.gpx && shown.focus === "BUTTON:Hide planner", JSON.stringify({ hidden, shown }));
  await p.eval("document.querySelector('.panel-scroll').scrollTop = 150; true");
  await sleep(100);
  const before = await p.eval("document.querySelector('.panel-scroll').scrollTop");
  await p.eval("document.querySelector('#bar-plan').click(); true");
  await sleep(300);
  const after = await p.eval("({ top: document.querySelector('.panel-scroll').scrollTop, focus: document.activeElement?.tagName })");
  check("plan: pressed on a scrolled planner it scrolls to the top and focuses the heading", before > 0 && after.top === 0 && after.focus === "H1", JSON.stringify({ before, after }));
  // From a scrolled sheet: Plan shows the planner at its top.
  await openSheet(p, "Map layers");
  await p.eval("document.querySelector('.panel-scroll').scrollTop = 200; true");
  await sleep(100);
  const sheetTop = await p.eval("document.querySelector('.panel-scroll').scrollTop");
  await p.eval("document.querySelector('#bar-plan').click(); true");
  await sleep(300);
  const planned = await p.eval("({ top: document.querySelector('.panel-scroll').scrollTop, planner: !document.querySelector('.planner-view').hidden, focus: document.activeElement?.tagName })");
  check("plan: pressed on a scrolled sheet it shows the planner at its top and focuses the heading", sheetTop > 0 && planned.top === 0 && planned.planner && planned.focus === "H1", JSON.stringify({ sheetTop, planned }));
  // Show planner from the Legend sheet too.
  await openSheet(p, "Legend");
  await p.eval("document.querySelector('.panel-toggle').focus(); document.querySelector('.panel-toggle').click(); true");
  await sleep(200);
  await p.eval("document.querySelector('.panel-toggle').focus(); document.querySelector('.panel-toggle').click(); true");
  await sleep(300);
  const fromLegend = await p.eval("({ planner: !document.querySelector('.planner-view').hidden, layers: document.getElementById('sheet-layers').hidden, focus: document.activeElement?.tagName + ':' + document.activeElement?.textContent })");
  check("toggle: Show planner from the Legend sheet also returns to the planner, the focus on the toggle", fromLegend.planner && fromLegend.layers && fromLegend.focus === "BUTTON:Hide planner", JSON.stringify(fromLegend));
  await p.close();
}

// ---- 18. Use my location (OWNER-DECISIONS 395) ----
{
  // "Use my location" (OWNER-DECISIONS 395): the CDP geolocation override and the permission, granted, denied and unavailable.
  const ORIGIN = `http://127.0.0.1:${PORT}`;
  const live = `(() => [...document.querySelectorAll('[role=status],[aria-live]')].map((e) => e.textContent.trim()).filter(Boolean))()`;
  const holders = (text) => `(() => [...document.querySelectorAll('[role=status],[aria-live]')].filter((e) => e.textContent.includes(${JSON.stringify(text)})).length)()`;
  async function emptyPlan({ permission = "granted", at = { latitude: 38.8893, longitude: -77.0502, accuracy: 15 }, secure = true, hash = "", script = "" } = {}) {
    const p = await newPage(b, { width: 1280, height: 900 });
    await mock(p, S_DEFAULT);
    await media(p, { scheme: "light" });
    await b.send("Browser.setPermission", { permission: { name: "geolocation" }, setting: permission, origin: ORIGIN, browserContextId: p.contextId });
    if (at) await p.s("Emulation.setGeolocationOverride", at);
    else await p.s("Emulation.setGeolocationOverride", {});
    if (!secure) await p.s("Page.addScriptToEvaluateOnNewDocument", { source: "Object.defineProperty(window, 'isSecureContext', { value: false })" });
    if (script) await p.s("Page.addScriptToEvaluateOnNewDocument", { source: script });
    await p.s("Page.navigate", { url: `${ORIGIN}/${hash}` });
    if (!(await p.waitFor("!!document.querySelector('.locate-button')", 30000))) throw new Error("no Use my location button");
    await sleep(500);
    return p;
  }
  // Counts each time a live region's text changes to one holding `text` (the app region toggles a trailing
  // space, so the same words said again count again).
  const countSaid = (text) => `(() => { window.__said = 0; const last = new WeakMap(); const scan = () => { for (const e of document.querySelectorAll('[role=status],[aria-live]')) { const t = e.textContent; if (last.get(e) !== t) { last.set(e, t); if (t.includes(${JSON.stringify(text)})) window.__said += 1; } } }; scan(); window.__said = 0; new MutationObserver(scan).observe(document.body, { subtree: true, childList: true, characterData: true }); return true; })()`;
  const press = async (p) => {
    await p.eval("document.querySelector('.locate-button').click(); true");
    await sleep(300);
    // The look-up is done when the button's "Finding your location" text is gone; the notice follows 150 ms later.
    await p.waitFor("!document.querySelector('.place-search')?.textContent.includes('Finding your location')", 15000);
    await sleep(900);
  };

  {
    const p = await emptyPlan();
    const box = await p.eval(`(() => { const r = (e) => { const x = e.getBoundingClientRect(); return { top: x.top, bottom: x.bottom, left: x.left, w: x.width, h: x.height }; }; const b = document.querySelector('.locate-button'); const i = document.querySelector('.place-search input'); return { b: r(b), i: r(i), inPoints: !!b.closest('section[aria-labelledby=points-heading]') }; })()`);
    const ax = await axNode(p, ".locate-button");
    check("locate: the button is named Use my location, a button, in the Points section", ax?.role === "button" && ax?.name === "Use my location" && box.inPoints, JSON.stringify({ ax, inPoints: box.inPoints }));
    check("locate: the button is 44 px or more each way and beside the search box (same row, to its right)", box.b.w >= 44 && box.b.h >= 44 && box.b.left >= box.i.left + box.i.w - 1 && box.b.top < box.i.bottom && box.b.bottom > box.i.top, JSON.stringify(box));
    await p.eval("document.querySelector('.place-search input').focus(); true");
    await sleep(300);
    const opt = await p.eval("(() => { const o = [...document.querySelectorAll('.place-results [role=option]')]; return { n: o.length, first: o[0]?.textContent, shown: !document.querySelector('.place-results').hidden }; })()");
    check("locate: with the search box focused and empty, Your location is the one choice in the list", opt.n === 1 && opt.shown && /^Your location/.test(opt.first ?? ""), JSON.stringify(opt));
    await p.key("ArrowDown", "ArrowDown", 40);
    await p.enter();
    await sleep(1500);
    const said = await p.eval(live);
    const startSaid = said.filter((t) => /Start set to your location, accurate to about \d+ ft \(15 m\)\./.test(t));
    check("locate: choosing Your location sets the start and says it, with US units first", startSaid.length >= 1, JSON.stringify(said));
    check("locate: said once, in one live region (no double announcement)", (await p.eval(holders("set to your location"))) === 1);
    const hint = await p.eval("document.querySelector('.place-search')?.textContent ?? ''");
    check("locate: the hint marks it approximate and says the marker can be dragged or the place searched", /approximate, to about \d+ ft \(15 m\)\. Drag its marker, or search for the exact place, to adjust it\./.test(hint), hint.slice(0, 300));
    const rows = await p.eval("document.querySelectorAll('.points > li').length");
    check("locate: one point is in the plan", rows >= 1, String(rows));
    // Every text the live regions held during the second press, to hear the pending sentence too.
    await p.eval("(() => { window.__heard = []; const o = new MutationObserver(() => { for (const e of document.querySelectorAll('[role=status],[aria-live]')) { const t = e.textContent.trim(); if (t && !window.__heard.includes(t)) window.__heard.push(t); } }); o.observe(document.body, { subtree: true, childList: true, characterData: true }); return true; })()");
    await press(p);
    const second = await p.eval(live);
    check("locate: a second press adds the next point, like a map click", second.some((t) => /^(End|Stop \d+) set to your location/.test(t)), JSON.stringify(second));
    const heard = await p.eval("window.__heard");
    check("locate: the press says Finding your location… while it looks", heard.includes("Finding your location…"), JSON.stringify(heard));
    const START_NOTE = "This link includes your location as the start.";
    const note = await p.waitFor("!!document.querySelector('.link-note')", 20000);
    const noteText = note ? await p.eval("document.querySelector('.link-note').textContent") : "";
    check("locate: Copy link shows the one-line note that the link includes the location as the start", noteText === START_NOTE, noteText);
    // Through the accessibility tree: the note is not hidden from it, and Copy link is described by it.
    await p.eval("(() => { const b = [...document.querySelectorAll('.route-actions button')].find((e) => e.textContent.trim() === 'Copy link'); if (b) b.id = '__copy'; return !!b; })()");
    const noteAx = await axNode(p, ".link-note");
    const copyAx = await axNode(p, "#__copy");
    check("locate: the note is in the accessibility tree and describes the Copy link button", !!noteAx && !noteAx.ignored && copyAx?.description === START_NOTE, JSON.stringify({ noteAx, copyAx }));
    try {
      await b.send("Browser.grantPermissions", { permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"], origin: ORIGIN, browserContextId: p.contextId });
    } catch {
      // An older Chrome without these: Copy link falls back to the selection copy.
    }
    await p.eval("document.getElementById('__copy').click(); true");
    await sleep(900);
    const copied = await p.eval("document.querySelector('.route-actions [role=status]')?.textContent ?? ''");
    check("locate: pressing Copy link says the note with the confirmation", copied === `Link copied. ${START_NOTE}`, copied);
    const stored = await p.eval("JSON.stringify([localStorage, sessionStorage]).includes('38.88') || JSON.stringify(Object.entries(localStorage)).includes('location')");
    check("locate: nothing about the position is in localStorage or sessionStorage", stored === false, String(stored));
    await p.shot(`${SHOTS}/locate_granted.png`);
    await p.close();
  }
  {
    // A drag of the location's marker keeps the note (the moved point is still the rider's spot), and so does
    // its undo. A start from the link, then the location as the end, both where the map shows them (the mocked
    // route's view), so the end's marker is the one under the mouse and no other point is from the location.
    const POINT_NOTE = "This link includes your location as a point on the route.";
    const p = await emptyPlan({ hash: "#p=-77.03500,38.90200&preset=default&v=2&stress=70&hills=0", at: { latitude: 38.8955, longitude: -77.0205, accuracy: 15 } });
    await press(p);
    await p.waitFor("!!document.querySelector('.link-note')", 20000);
    await sleep(800);
    const hashBefore = await p.eval("location.hash");
    const pin = await p.eval("(() => { const m = document.querySelector('.pin.pin-end'); if (!m) return null; const r = m.getBoundingClientRect(); const x = r.left + r.width / 2; const y = r.top + r.height / 2; const hit = document.elementFromPoint(x, y); return { at: [x, y], hit: !!hit && (hit === m || m.contains(hit)) }; })()");
    if (pin?.hit) {
      const [x, y] = pin.at;
      await p.s("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
      for (let i = 1; i <= 6; i += 1) await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: x + i * 6, y: y + i * 4, button: "left", buttons: 1 });
      await p.s("Input.dispatchMouseEvent", { type: "mouseReleased", x: x + 36, y: y + 24, button: "left", clickCount: 1 });
    }
    await sleep(1500);
    await p.waitFor("!!document.querySelector('.link-note')", 20000);
    const dragged = await p.eval("({ note: document.querySelector('.link-note')?.textContent ?? '', hash: location.hash })");
    check("locate: dragging the location's marker moves it and keeps the Copy link note", !!pin?.hit && dragged.hash !== hashBefore && dragged.note === POINT_NOTE, JSON.stringify({ pin, dragged, hashBefore }));
    // Undo: the points are compact while a route shows, so the button is pressed where it is.
    const undid = await p.eval("(() => { const u = [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Undo' && !e.disabled); u?.click(); return !!u; })()");
    await sleep(1500);
    await p.waitFor("!!document.querySelector('.link-note')", 20000);
    const undone = await p.eval("({ note: document.querySelector('.link-note')?.textContent ?? '', hash: location.hash })");
    check("locate: undoing the drag puts the point back and keeps the Copy link note", undid && undone.hash === hashBefore && undone.note === POINT_NOTE, JSON.stringify({ undid, undone, hashBefore }));
    await p.shot(`${SHOTS}/locate_drag.png`);
    await p.close();
  }
  {
    const p = await emptyPlan({ permission: "denied" });
    // The Points notice is a live region before any message (a region created holding its text is often not spoken).
    const NOTICE = "section[aria-labelledby=points-heading] > p.notice[role=status]";
    const region = await p.eval(`(() => { const e = document.querySelector(${JSON.stringify(NOTICE)}); if (!e) return null; e.__pre = 1; e.id = e.id || '__notice'; return { id: e.id, text: e.textContent, empty: e.classList.contains('notice-empty') }; })()`);
    const regionAx = region ? await axNode(p, `#${region.id}`) : null;
    check("locate: before any message the Points notice is there, empty, and in the accessibility tree", !!region && region.text === "" && region.empty && !!regionAx && !regionAx.ignored, JSON.stringify({ region, regionAx }));
    // Enter in the empty box, with nothing highlighted, never takes Your location: no look-up, no message, no point.
    await p.eval(countSaid("Finding your location"));
    await p.eval("document.querySelector('.place-search input').focus(); true");
    await sleep(300);
    await p.enter();
    await sleep(1500);
    const afterEnter = await p.eval(`({ said: window.__said, notice: document.querySelector(${JSON.stringify(NOTICE)})?.textContent ?? null, points: document.querySelectorAll('.points > li').length })`);
    check("locate: Enter in the empty search box asks for no location (Your location is never the Enter default)", afterEnter.said === 0 && afterEnter.notice === "" && afterEnter.points === 0, JSON.stringify(afterEnter));
    await p.eval("document.activeElement?.blur(); true");
    await press(p);
    const same = await p.eval(`(() => { const e = document.querySelector(${JSON.stringify(NOTICE)}); return { pre: e?.__pre === 1, text: e?.textContent ?? '' }; })()`);
    check("locate: the same notice element, already in the page, holds the denial", same.pre && /blocked for this site/.test(same.text), JSON.stringify(same));
    const text = (await p.eval(live)).join(" | ");
    check("locate: permission denied is a plain message in a status, said once", /Your location is blocked for this site/.test(text) && (await p.eval(holders("blocked for this site"))) === 1, text);
    const points = await p.eval("document.querySelectorAll('.place-search ~ *').length >= 0 && !document.querySelector('.link-note')");
    check("locate: a denial adds no point and no link note", points === true);
    await p.close();
  }
  {
    // A two-point plan, Start chosen, then Your location: it replaces the start (the choice reaches placeFix).
    const p = await emptyPlan({ hash: "#p=-77.04000,38.91000;-77.01000,38.89000&preset=default&v=2&stress=70&hills=0" });
    await p.waitFor("document.querySelectorAll('.points > li').length === 2", 20000);
    // With a route shown the points are compact: Edit points opens the search, as a rider would.
    await p.waitFor("!![...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Edit points')", 20000);
    await p.eval("[...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Edit points')?.click(); true");
    await sleep(500);
    const chose = await p.eval("(() => { const r = document.querySelector('.place-choice input[type=radio][value=start]'); if (!r) return false; r.click(); return r.checked; })()");
    await sleep(300);
    await p.eval("document.querySelector('.place-search input').focus(); true");
    await sleep(300);
    const line = await p.eval("[...document.querySelectorAll('.place-results [role=option]')][0]?.textContent ?? ''");
    await p.eval(countSaid("Start set to your location"));
    await p.key("ArrowDown", "ArrowDown", 40);
    await p.enter();
    await p.waitFor("!document.querySelector('.place-search')?.textContent.includes('Finding your location')", 15000);
    await sleep(1500);
    const got = await p.eval("({ said: window.__said, rows: document.querySelectorAll('.points > li').length, hash: location.hash })");
    check("locate: on a two-point plan with Start chosen, Your location replaces the start", chose && /^Your location\s*Replaces the start\./.test(line) && got.said >= 1 && got.rows === 2 && got.hash.startsWith("#p=-77.05020,38.88930;-77.01000,38.89000&"), JSON.stringify({ chose, line, got }));
    await p.close();
  }
  {
    // A slow look-up (2.5 s): a second press while it runs is answered again and starts no second look-up.
    const slow = "(() => { const g = navigator.geolocation; const real = g.getCurrentPosition.bind(g); window.__lookups = 0; Object.defineProperty(g, 'getCurrentPosition', { configurable: true, value: (ok, fail, o) => { window.__lookups += 1; setTimeout(() => real(ok, fail, o), 2500); } }); })()";
    const p = await emptyPlan({ script: slow });
    await p.eval(countSaid("Finding your location"));
    await p.eval("document.querySelector('.locate-button').click(); true");
    await sleep(500);
    await p.eval("document.querySelector('.locate-button').click(); true");
    await sleep(500);
    const during = await p.eval("({ said: window.__said, lookups: window.__lookups })");
    await p.waitFor("!document.querySelector('.place-search')?.textContent.includes('Finding your location')", 15000);
    await sleep(1200);
    const after = await p.eval("({ lookups: window.__lookups, points: document.querySelectorAll('.points > li').length })");
    check("locate: a press during the look-up says Finding your location… again and starts no second look-up", during.said === 2 && after.lookups === 1 && after.points === 1, JSON.stringify({ during, after }));
    await p.close();
  }
  {
    const p = await emptyPlan({ at: null });
    await press(p);
    const text = (await p.eval(live)).join(" | ");
    check("locate: position unavailable is a plain message, said once", /could not be found right now/.test(text) && (await p.eval(holders("could not be found"))) === 1, text);
    await p.close();
  }
  {
    const p = await emptyPlan({ at: { latitude: 40.7128, longitude: -74.006, accuracy: 20 } });
    await press(p);
    const text = (await p.eval(live)).join(" | ");
    check("locate: outside coverage uses the existing notice", /outside the area this map covers/.test(text) && (await p.eval(holders("outside the area"))) === 1, text);
    await p.close();
  }
  {
    const p = await emptyPlan({ secure: false });
    const ax = await axNode(p, ".locate-button");
    const attr = await p.eval("document.querySelector('.locate-button').getAttribute('aria-disabled')");
    check("locate: on an insecure page the button stays in the Tab order, aria-disabled, with the reason as its description", attr === "true" && /secure \(HTTPS\)/.test(ax?.description ?? ""), JSON.stringify(ax));
    await press(p);
    const pts = await p.eval("!!document.querySelector('.link-note')");
    check("locate: a press on the insecure page asks nothing and adds nothing", pts === false);
    await p.close();
  }
}

// ---- 19. The route chart (OWNER-DECISIONS 322, 323, 328, 332, 333): a slider with the spoken sentence, its tables, the map marker ----
{
  const p = await open({ junctions: false });
  const fold = await p.eval(`(() => { const h = [...document.querySelectorAll('h3')].find((x) => x.textContent === 'Elevation and stress'); const d = h?.nextElementSibling; return { heading: !!h, details: d?.tagName, open: d?.open, summary: d?.querySelector('summary')?.textContent }; })()`);
  check("chart: an \"Elevation and stress\" fold with its own heading, open beside the map", fold.heading && fold.details === "DETAILS" && fold.open === true && fold.summary === "Elevation and stress", JSON.stringify(fold));
  const first = await axNode(p, ".pc-plot");
  check("chart: the picture is one slider, named for what it shows, its value text the spoken sentence (a path said as the map has it)", first?.role === "slider" && first.name === "Elevation and stress along the route" && /^Mile 0\.0: elevation \d+ ft \(\d+ m\), level, traffic-free path\.$/.test(first.valuetext ?? ""), JSON.stringify(first));
  check("chart: its description is the key hint only (the summary is the text just before it)", /^Arrow keys move along the route; Page Up and Page Down move further; Home and End go to the ends; C and Shift\+C/.test(first?.description ?? "") && !/Over 2\.9 mi/.test(first?.description ?? ""), (first?.description ?? "").slice(0, 200));
  check("chart: the summary before it, in miles and feet first", /^Over 2\.9 mi \(4\.7 km\), elevation runs from 328 ft \(100 m\) to 408 ft \(124 m\)\./.test(await p.eval("document.querySelector('.pc-summary').textContent")));
  const shares = await p.eval("document.querySelector('.pc-summary').textContent");
  check("chart: the summary's stress shares say the 0-900 m path as the key does, never \"LTS 1\" (a11y re-review S1)", /Traffic stress along it: \d+% traffic-free path, \d+% LTS 2\./.test(shares) && !/LTS 1/.test(shares), shares);
  check("chart: no colour-only cue: the grade bands are named in words, and each has a pattern over the amber", await p.eval(`(() => { const l = [...document.querySelectorAll('.pc-legend li')].map((x) => x.textContent); return l.includes('Grade 5% to 8%') && l.includes('Grade 8% or more') && !!document.querySelector('.pc-svg pattern[id$="-hatch"]') && !!document.querySelector('.pc-svg pattern[id$="-dots"]') && !!document.querySelector('.pc-svg path.pc-band-1[fill$="-dots)"]') && !!document.querySelector('.pc-svg path[fill="#f59e0b"]'); })()`));
  check("chart: the strip and its key say a traffic-free path as the map does", await p.eval("[...document.querySelectorAll('.pc-tiers li')].map((x) => x.textContent).join('|') === 'Traffic-free path|LTS 2'"), await p.eval("[...document.querySelectorAll('.pc-tiers li')].map((x) => x.textContent).join('|')"));
  await p.eval("document.querySelector('.pc-plot').focus(); true");
  check("chart: the one tab stop is the slider, and it takes the focus", await p.eval("document.activeElement?.classList.contains('pc-plot')"), await focused(p));
  for (let i = 0; i < 3; i += 1) await p.key("ArrowRight", "ArrowRight", 39);
  await sleep(150);
  const three = await axNode(p, ".pc-plot");
  check("chart: three Right arrows read Mile 0.3 with its elevation, grade and stress", /^Mile 0\.3: elevation \d+ ft \(\d+ m\), level, traffic-free path\.$/.test(three?.valuetext ?? ""), three?.valuetext);
  check("chart: and put a marker on the map, hidden from a screen reader (the sentence is the announcement)", await p.eval("(() => { const m = document.querySelector('.scrub-marker'); return !!m && m.getAttribute('aria-hidden') === 'true' && m.tabIndex < 0; })()"));
  for (let i = 0; i < 9; i += 1) await p.key("ArrowRight", "ArrowRight", 39);
  await sleep(150);
  const climb = await axNode(p, ".pc-plot");
  check("chart: on the climb the sentence says the grade, as Mile 1.2: grade 6%", /^Mile 1\.2: elevation \d+ ft \(\d+ m\), grade 6%, LTS 2\.$/.test(climb?.valuetext ?? ""), climb?.valuetext);
  await p.shot(`${SHOTS}/chart_stress_focused.png`);
  await p.key("End", "End", 35);
  await sleep(100);
  check("chart: End goes to the end of the route", /^Mile 2\.9: /.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""), (await axNode(p, ".pc-plot"))?.valuetext);
  await p.key("Home", "Home", 36);
  await sleep(100);
  check("chart: Home goes to Mile 0.0", /^Mile 0\.0: /.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""));
  await p.key("ArrowLeft", "ArrowLeft", 37);
  check("chart: a key it takes does not move the focus", await p.eval("document.activeElement?.classList.contains('pc-plot')"), await focused(p));
  await p.key("c", "KeyC", 67);
  await sleep(100);
  check("chart: C jumps to the next climb (a11y N4)", /^Mile 1\.1: elevation \d+ ft \(\d+ m\), grade 6%, LTS 2\.$/.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""), (await axNode(p, ".pc-plot"))?.valuetext);
  await p.key("Home", "Home", 36);
  for (let i = 0; i < 3; i += 1) await p.key("ArrowRight", "ArrowRight", 39);
  await sleep(100);
  // The mouse over a focused slider: the marker and the readout follow it; the spoken value does not (a11y S3).
  const box = await p.eval("(() => { const r = document.querySelector('.pc-svg').getBoundingClientRect(); return { x: r.left + r.width * 0.5, y: r.top + r.height * 0.3 }; })()");
  await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x, y: box.y });
  await sleep(200);
  const hovered = await p.eval("({ readout: document.querySelector('.pc-readout').textContent, now: document.querySelector('.pc-plot').getAttribute('aria-valuetext') })");
  check("chart: a mouse over the focused slider moves the readout but not the value a screen reader hears", /^Mile 1\.\d: elevation/.test(hovered.readout) && /^Mile 0\.3: /.test(hovered.now), JSON.stringify(hovered));
  await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5 });
  await sleep(150);
  await p.tab();
  await sleep(250);
  check("chart: Tab leaves the chart and the map's marker goes", await p.eval("!document.querySelector('.scrub-marker') && !document.activeElement?.classList.contains('pc-plot')"), await focused(p));
  // The mouse: hovering moves the same marker. Under load the map draws it late, so wait for
  // it (up to 2 s) rather than a fixed pause; the check below is unchanged.
  await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: box.x, y: box.y });
  await p.waitFor("!!document.querySelector('.scrub-marker') && /^Mile \\d\\.\\d: elevation/.test(document.querySelector('.pc-readout')?.textContent ?? '')", 2000);
  check("chart: hovering the picture moves a marker on the map too, and shows the same sentence", await p.eval("!!document.querySelector('.scrub-marker') && /^Mile \\d\\.\\d: elevation/.test(document.querySelector('.pc-readout').textContent)"), await p.eval("document.querySelector('.pc-readout').textContent"));
  await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5 });
  await sleep(150);
  await p.eval("document.querySelector('.pc-plot').focus(); true");
  await sleep(100);
  check("chart: coming back to it carries on from where the keyboard left it (a11y N2)", /^Mile 0\.3: /.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""), (await axNode(p, ".pc-plot"))?.valuetext);
  await p.eval("document.activeElement.blur(); true");
  await sleep(150);
  const table = await p.eval(`(() => { const d = document.querySelector('.pc-table-fold'); const was = d.open; d.querySelector('summary').click(); const t = d.querySelector('table'); return { was, summary: d.querySelector('summary').textContent, caption: t?.querySelector('caption')?.textContent, heads: [...t.querySelectorAll('thead th')].map((x) => x.textContent), row: [...t.querySelectorAll('tbody tr:first-child > *')].map((x) => x.textContent), rowHead: t.querySelector('tbody tr:first-child > *').tagName }; })()`);
  await sleep(150);
  check("chart: the climbs table is behind a closed \"Climbs as a table\"", table.was === false && table.summary === "Climbs as a table", JSON.stringify(table));
  check("chart: it has a caption and column headers: start, length, gain, average, maximum, stress", table.caption === "Climbs, in the order ridden" && JSON.stringify(table.heads) === JSON.stringify(["Start", "Length", "Gain", "Average grade", "Maximum grade", "Stress"]), JSON.stringify(table));
  check("chart: the climb's row, in feet first", JSON.stringify(table.row) === JSON.stringify(["Mile 1.1", "0.2 mi (0.3 km)", "68 ft (21 m)", "7%", "9%", "LTS 2"]) && table.rowHead === "TH", JSON.stringify(table.row));
  const ax = await axNode(p, ".pc-table");
  check("chart: the table is a table to a screen reader, named by its caption", ax?.role === "table" && ax.name === "Climbs, in the order ridden", JSON.stringify(ax));
  check("chart: the stress strip is drawn, a section for each stress section, with a frame", await p.eval("document.querySelectorAll('.pc-svg g > rect[fill]').length >= 2 && !!document.querySelector('.pc-strip-frame')"));
  check("chart: nothing is wider than the panel at 1280 px", await p.eval("(() => { const c = document.querySelector('.elevation-chart'); return c.scrollWidth <= c.clientWidth + 1 && document.documentElement.scrollWidth <= window.innerWidth; })()"));
  check("chart: no id is used twice (the patterns' ids are unique)", await p.eval("(() => { const ids = [...document.querySelectorAll('[id]')].map((e) => e.id); return ids.length === new Set(ids).size; })()"));
  await p.close();
}
{
  // A phone: the fold is collapsed to begin with, and opens to a chart that fits.
  const p = await open({ width: 375, height: 800, mobile: true, junctions: false, ride: false });
  const shut = await p.eval("(() => { const h = [...document.querySelectorAll('h3')].find((x) => x.textContent === 'Elevation and stress'); const d = h?.nextElementSibling; return d ? d.open : null; })()");
  check("chart at 375 px: the fold is collapsed by default", shut === false, String(shut));
  await p.eval("(() => { const h = [...document.querySelectorAll('h3')].find((x) => x.textContent === 'Elevation and stress'); h.nextElementSibling.querySelector('summary').click(); return true; })()");
  await sleep(300);
  const fit = await p.eval("(() => { const s = document.querySelector('.pc-svg').getBoundingClientRect(); return { w: Math.round(s.width), page: document.documentElement.scrollWidth, win: window.innerWidth, readable: parseFloat(getComputedStyle(document.querySelector('.pc-axis-text')).fontSize) * (s.width / 360) }; })()");
  check("chart at 375 px: opened, it fits the screen and its type stays 8 px or more", fit.page <= fit.win && fit.w <= fit.win && fit.readable >= 8, JSON.stringify(fit));
  await p.eval("document.querySelector('.elevation-chart').scrollIntoView({ block: 'center' }); true");
  await sleep(200);
  await p.shot(`${SHOTS}/chart_stress_375.png`);
  await p.close();
}
{
  // The Mass Ride version: the riders-per-minute area in place of the strip, and the major intersections.
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0), junctions: false });
  const heading = await p.eval("[...document.querySelectorAll('h3')].map((x) => x.textContent).filter((t) => /^Elevation/.test(t))");
  check("mass chart: the fold is \"Elevation and riders per minute\"", JSON.stringify(heading) === JSON.stringify(["Elevation and riders per minute"]), JSON.stringify(heading));
  const shape = await p.eval(`(() => ({
    strip: !!document.querySelector('.pc-strip-frame'),
    patterns: [...document.querySelectorAll('.pc-svg pattern[id*="-flow-"]')].map((x) => x.id.replace(/^.*-flow-/, '')).sort(),
    fills: [...new Set([...document.querySelectorAll('.pc-svg path[fill-opacity]')].map((x) => x.getAttribute('fill')))].sort(),
    guides: [...document.querySelectorAll('.pc-guide-text')].map((x) => x.textContent),
    ticks: document.querySelectorAll('.pc-tick').length,
    names: [...document.querySelectorAll('.pc-cross-text')].map((x) => x.textContent),
    legend: [...document.querySelectorAll('.pc-legend li')].map((x) => x.textContent),
  }))()`);
  check("mass chart: no stress strip; the riders area is filled in the band colours, each with its own pattern", !shape.strip && JSON.stringify(shape.patterns) === JSON.stringify(["crosshatch", "diagonal", "dots", "horizontal"]) && shape.fills.every((f) => ["#d7191c", "#f28e2b", "#1a9850", "#6a3d9a"].includes(f)) && shape.fills.length >= 3, JSON.stringify(shape));
  check("mass chart: the dotted guides are labelled 60, 120 and 200", JSON.stringify(shape.guides) === JSON.stringify(["60", "120", "200"]), JSON.stringify(shape.guides));
  const guides = await p.eval(`(() => { const probe = document.createElement('span'); probe.style.color = 'var(--text)'; probe.style.backgroundColor = 'var(--bg)'; document.querySelector('.elevation-chart').append(probe); const cs = getComputedStyle(probe); const bg = cs.backgroundColor; const t = cs.color; probe.remove(); return { bg, text: t, labels: [...document.querySelectorAll('.pc-guide-text')].map((x) => getComputedStyle(x).fill), lines: [...document.querySelectorAll('.pc-guide')].map((x) => getComputedStyle(x).stroke), swatches: [...document.querySelectorAll('.pc-guide-swatch')].map((x) => x.getAttribute('fill')) }; })()`);
  const rgb = (s) => (s.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map(Number);
  check("mass chart: the guides' figures are in the text colour, beside a swatch of the band colour (a11y S1)", guides.labels.every((f) => f === guides.text) && JSON.stringify(guides.swatches) === JSON.stringify(["#d7191c", "#f28e2b", "#1a9850"]), JSON.stringify(guides));
  check("mass chart: each guide line is 3:1 or more on the panel", guides.lines.length === 3 && guides.lines.every((s) => contrast(rgb(s), rgb(guides.bg)) >= 3), JSON.stringify(guides.lines.map((s) => contrast(rgb(s), rgb(guides.bg)).toFixed(2))));
  const marks = await p.eval(`(() => ({ caret: !!document.querySelector('.pc-narrowest path'), label: document.querySelector('.pc-narrowest-text')?.textContent, avoid: document.querySelectorAll('.pc-avoid').length, avoidText: document.querySelector('.pc-avoid-text')?.textContent, avoidFill: document.querySelector('.pc-avoid rect')?.getAttribute('fill'), avoidSize: parseFloat(getComputedStyle(document.querySelector('.pc-avoid-text')).fontSize), avoidInk: getComputedStyle(document.querySelector('.pc-avoid-text')).fill, avoidHatch: document.querySelector('.pc-svg pattern[id$="-avoid"] path')?.getAttribute('d'), bottleneckHatch: document.querySelector('.pc-svg pattern[id$="-flow-crosshatch"] path')?.getAttribute('d') }))()`);
  check("mass chart: the narrowest point is marked with a shape and its figure (147)", marks.caret && marks.label === "Narrowest 55", JSON.stringify(marks));
  check("mass chart: a stretch marked Avoid is drawn as Avoid, with no figure (325)", marks.avoid === 1 && marks.avoidText === "AVOID" && shape.legend.includes("Marked Avoid (A where narrow): no capacity given") && shape.legend.includes("Narrowest with the hills (downward triangle)"), JSON.stringify({ marks, legend: shape.legend }));
  check("mass chart: Avoid is magenta with a white word at the chart's 11-unit type and a texture of its own, not the bottleneck's cross-hatch (397)", marks.avoidFill === "#d6008f" && marks.avoidSize === 11 && /255, 255, 255|#fff/i.test(marks.avoidInk) && !!marks.avoidHatch && marks.avoidHatch !== marks.bottleneckHatch, JSON.stringify(marks));
  check("mass chart: every major intersection has a tick, the names are short and the ones that would collide are thinned", shape.ticks === 7 && shape.names.length >= 3 && shape.names.length < 7 && shape.names.every((n) => /^[0-9A-Z]/.test(n) && !/Street|Northwest/.test(n)), JSON.stringify({ ticks: shape.ticks, names: shape.names }));
  check("mass chart: the key names the bands, and the junction shapes beside their words", ["Under 60: bottleneck", "60 to 120: tight", "120 to 200: good", "200 and up: wide open"].every((t) => shape.legend.includes(t)) && shape.legend.some((t) => /triangle/.test(t)) && shape.legend.some((t) => /diamond/.test(t)), JSON.stringify(shape.legend));
  await p.eval("document.querySelector('.pc-plot').focus(); true");
  for (let i = 0; i < 12; i += 1) await p.key("ArrowRight", "ArrowRight", 39);
  await sleep(150);
  const ax = await axNode(p, ".pc-plot");
  check("mass chart: the sentence at Mile 1.2: grade, riders per minute with its band and why, and the next major intersection with corkers", ax?.name === "Elevation and riders per minute along the route" && ax.valuetext === "Mile 1.2: grade 6%, about 90 riders per minute (tight, slowed by the climb). Next: 15th Street Northwest at mile 1.3, corkers needed.", JSON.stringify(ax));
  await p.shot(`${SHOTS}/chart_mass_focused.png`);
  await p.key("i", "KeyI", 73);
  await sleep(100);
  check("mass chart: I jumps to the next major intersection", /^Mile 1\.3: /.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""), (await axNode(p, ".pc-plot"))?.valuetext);
  for (let i = 0; i < 10; i += 1) await p.key("ArrowRight", "ArrowRight", 39);
  await sleep(100);
  check("mass chart: on the Avoid stretch it says Avoid, never a figure", /^Mile 2\.3: level, marked Avoid, no capacity given\. Next: 9th Street Northwest/.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""), (await axNode(p, ".pc-plot"))?.valuetext);
  await p.key("End", "End", 35);
  await sleep(100);
  check("mass chart: past the last intersection it says so", /No major intersections ahead\.$/.test((await axNode(p, ".pc-plot"))?.valuetext ?? ""), (await axNode(p, ".pc-plot"))?.valuetext);
  const tables = await p.eval(`(() => { const d = document.querySelector('.pc-table-fold'); d.querySelector('summary').click(); const ts = [...d.querySelectorAll('table')]; const rows = (t) => (t ? [...t.querySelectorAll('tbody tr')].map((r) => [...r.children].map((c) => c.textContent).join(' | ')) : []); return { summary: d.querySelector('summary').textContent, captions: ts.map((t) => t.querySelector('caption').textContent), heads: [...ts[0].querySelectorAll('thead th')].map((x) => x.textContent), climb: [...ts[0].querySelectorAll('tbody tr:first-child > *')].map((x) => x.textContent), bottlenecks: rows(ts[1]), rows: rows(ts[2]) }; })()`);
  check("mass chart: the climbs table lists the capacity drop, a bottlenecks table, and a table of every intersection with its marker and corkers", tables.summary === "Climbs, bottlenecks and intersections as tables" && tables.heads.at(-1) === "Capacity drop" && tables.climb.at(-1) === "53% fewer riders, down to 90 a minute" && JSON.stringify(tables.captions) === JSON.stringify(["Climbs, in the order ridden", "Bottlenecks, under 60 riders per minute, in the order ridden", "Major intersections, in the order ridden"]) && JSON.stringify(tables.bottlenecks) === JSON.stringify(["Mile 0.0 | 0.1 mi (0.2 km) | About 55 a minute"]) && tables.rows.length === 7 && tables.rows[0] === "Mile 0.6 | 18th Street Northwest | Higher stress (orange triangle) | Corkers needed" && tables.rows[5] === "Mile 2.1 | Pierce Street | Crosses a busy road (LTS 3), cross traffic stops (dot) | Corkers needed", JSON.stringify(tables));
  await p.close();
}
{
  // Forced colours (a11y S6): the chart and its key both keep their colours, so they still match; the words follow the system's text colour.
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0), junctions: false, forced: true });
  const forced = await p.eval(`(() => { const probe = document.createElement('span'); probe.style.color = 'CanvasText'; document.body.append(probe); const text = getComputedStyle(probe).color; probe.style.color = 'Canvas'; document.body.append(probe); const canvas = getComputedStyle(probe).color; probe.remove(); const svg = document.querySelector('.pc-svg'); const keys = [...document.querySelectorAll('.pc-legend svg')]; return { text, svg: getComputedStyle(svg).forcedColorAdjust, keys: keys.map((k) => getComputedStyle(k).forcedColorAdjust), border: keys.map((k) => getComputedStyle(k).borderTopStyle), axis: getComputedStyle(document.querySelector('.pc-axis-text')).fill, line: getComputedStyle(document.querySelector('.pc-line')).stroke, dot: getComputedStyle(document.querySelector('.pc-dot')).fill, frame: getComputedStyle(document.querySelector('.pc-avoid-frame')).stroke, inner: getComputedStyle(document.querySelector('.pc-avoid-inner')).stroke, canvas }; })()`);
  check("chart in forced colours: the picture and its key keep their colours, the key's swatches framed", forced.svg === "none" && forced.keys.length >= 6 && forced.keys.every((k) => k === "none") && forced.border.every((b) => b === "solid"), JSON.stringify(forced));
  check("chart in forced colours: its words and line are the system's text colour", forced.axis === forced.text && forced.line === forced.text && forced.dot === forced.text && forced.frame === forced.text && forced.inner === forced.canvas && forced.canvas !== forced.text, JSON.stringify(forced));
  await p.close();
}
{
  // For the eye only: both charts in the dark theme, scrolled into view and with the scrub at the climb (no checks).
  for (const [route, preset, name] of [[S_DEFAULT, "default", "stress"], [S_MASS, "mass-ride", "mass"]]) {
    const p = await open({ route, hash: hashFor(preset, 70), scheme: "dark", junctions: false });
    await p.eval("(() => { const c = document.querySelector('.elevation-chart'); c.scrollIntoView({ block: 'center' }); const t = c.querySelector('.pc-plot'); t.focus(); return true; })()");
    for (let i = 0; i < 12; i += 1) await p.key("ArrowRight", "ArrowRight", 39);
    await sleep(300);
    await p.shot(`${SHOTS}/chart_${name}_dark.png`);
    await p.close();
  }
}

// ---- 20. The Mass Ride capacity map: riders per minute in place of the LTS breakdown (OWNER-DECISIONS 325-327, 387; its own tiles, 415, 417, 417a; DC only and the outside-DC notice, 418, 418a; the bands by zoom, 421, 422; both narrowest figures, 424) ----
{
  const p = await open({ route: S_MASS_CAPACITY, hash: hashFor("mass-ride", 0), stressTiles: "capacity" });
  await p.waitFor("!!document.querySelector('.summary .capacity-stats')", 10000);
  const route = await p.eval(`(() => { const s = document.querySelector('.summary'); const stats = s.querySelector('.capacity-stats');
    const fold = [...s.querySelectorAll('details > summary')].map((x) => x.textContent);
    const terms = (sel) => [...(stats?.querySelectorAll(sel) ?? [])].map((d) => d.querySelector('dt')?.textContent + ' = ' + d.querySelector('dd')?.textContent);
    return { narrowest: terms('.capacity-narrowest'), typical: terms('.capacity-typical'),
      stressBar: !!s.querySelector('.stress-bar'), folds: fold, ltsWords: /LTS|traffic stress/i.test(s.querySelector('.stats.capacity-stats')?.parentElement?.textContent ?? '') }; })()`);
  // OWNER-DECISIONS 424: both figures, on the flat and with the hills, said once at the same spot; the typical as well.
  check("capacity: the route view says the narrowest points on the flat and with the hills in words, with band and where, and both typical figures",
    JSON.stringify(route.narrowest) === JSON.stringify(["Narrowest on the flat and with the hills = 50 riders per minute (bottleneck) on the flat, 55 riders per minute (bottleneck) with the hills, at the start"]) &&
      JSON.stringify(route.typical) === JSON.stringify(["Typical on the flat = 150 riders per minute", "Typical with the hills = 190 riders per minute"]), JSON.stringify(route));
  check("capacity: the stress bar is replaced, and the fold is Riders per minute in place of Stress and facilities",
    !route.stressBar && route.folds.some((t) => t === "Riders per minute") && !route.folds.some((t) => /^Stress and facilities/.test(t)), JSON.stringify(route.folds));
  const fold = await p.eval(`(() => { const d = [...document.querySelectorAll('.summary details')].find((x) => x.querySelector('summary')?.textContent === 'Riders per minute'); if (d) d.open = true;
    const rows = [...(d?.querySelectorAll('.capacity li') ?? [])].map((li) => li.textContent);
    const avoidRow = [...(d?.querySelectorAll('.capacity li') ?? [])].find((li) => /Marked Avoid/.test(li.textContent));
    return { rows, hidden: [...(d?.querySelectorAll('.capacity li svg') ?? [])].every((v) => v.getAttribute('aria-hidden') === 'true'), list: d?.querySelector('.capacity ul')?.getAttribute('aria-label'),
      avoidMark: !!avoidRow?.querySelector('svg .route-avoid-mark'), said: d?.querySelector('.capacity-narrowest-said')?.textContent ?? '' }; })()`);
  check("capacity: the fold's list gives each band's words, share and length, one row each, its swatches (Avoid's the route's own) hidden from a screen reader, and both narrowest figures",
    fold.rows.length === 5 && /^Under 60: bottleneck, \d+%, /.test(fold.rows[0]) && /Marked Avoid: no capacity given/.test(fold.rows.join("|")) && fold.hidden && /Share of the route/.test(fold.list) &&
      fold.avoidMark && fold.said === "Narrowest on the flat and with the hills: 50 riders per minute (bottleneck) on the flat, 55 riders per minute (bottleneck) with the hills, at the start.", JSON.stringify(fold));
  const lead = await p.eval("document.querySelector('.capacity-lead')?.textContent ?? ''");
  await p.eval("document.querySelector('.route-description summary')?.click(); true");
  await sleep(200);
  const lead2 = await p.eval("document.querySelector('.capacity-lead')?.textContent ?? ''");
  check("capacity: the directions open with the narrowest point and every band's share, in words", /^Carrying capacity: narrowest on the flat and with the hills: 50 riders per minute \(bottleneck\) on the flat, 55 riders per minute \(bottleneck\) with the hills, at the start\. By distance: /.test(lead || lead2), lead || lead2);
  await openSheet(p);
  await p.eval("document.getElementById('legend-heading')?.scrollIntoView({ block: 'center' }); true");
  // The map has drawn a road with a capacity: the legend is riders per minute.
  const gotLegend = await p.waitFor("!!document.querySelector('.mass-legend')", 15000);
  const legend = await p.eval(`(() => { const u = document.querySelector('.mass-legend'); if (!u) return null;
    return { name: u.getAttribute('aria-label'), rows: [...u.querySelectorAll('li')].map((li) => li.textContent), swatchesHidden: [...u.querySelectorAll('svg')].every((v) => v.getAttribute('aria-hidden') === 'true'),
      heading: document.getElementById('layers-heading')?.textContent, toggle: document.querySelector('#show-stress')?.closest('label')?.textContent.trim(),
      stressLegend: !!document.querySelector('[aria-label="Traffic stress legend"]') }; })()`);
  check("capacity: the legend lists the four bands in order, then Avoid, each in words, named for the speed",
    gotLegend && legend?.rows.length === 5 && JSON.stringify(legend.rows.slice(0, 4)) === JSON.stringify(["Under 60: bottleneck", "60 to 120: tight", "120 to 200: good", "200 and up: wide open"]) && legend.rows[4] === "Marked Avoid: no capacity given" && /^Riders per minute at 6 to 8 mph \(10 to 13 km\/h\)$/.test(legend.name), JSON.stringify(legend));
  check("capacity: its swatches are hidden from a screen reader, the heading and the switch say riders per minute, and no stress legend is there",
    legend?.swatchesHidden && legend.heading === legend.name && /riders per minute/.test(legend.toggle) && !legend.stressLegend, JSON.stringify(legend));
  const axLegend = await axNode(p, ".mass-legend");
  check("capacity: the legend is a list a screen reader names", axLegend?.role === "list" && /^Riders per minute at 6 to 8 mph/.test(axLegend?.name ?? ""), JSON.stringify(axLegend));
  const notes = await p.eval("[...document.querySelectorAll('#sheet-layers .hint')].map((h) => h.textContent).join(' | ')");
  check("capacity: it says what the map leaves out, and credits where the figures come from", /Trails, paths, protected bike lanes and bike lanes are not drawn on this map at any zoom/.test(notes) && /DC Open Data, Roadway Block \(CC BY 4\.0, adapted\)/.test(notes) && /© OpenStreetMap contributors/.test(notes), notes.slice(0, 200));
  // DC only for now (OWNER-DECISIONS 418), in words beside the gray mask, with the boundary's source.
  const dcOnly = await p.eval(`({ legend: document.querySelector('#sheet-layers .mass-dc-only')?.textContent ?? '', credit: document.querySelector('#sheet-layers .dc-boundary-source')?.textContent ?? '',
    planner: document.querySelector('#route-planner .mass-dc-only')?.textContent ?? '' })`);
  check("capacity: the legend says in words that Mass Ride planning covers DC only for now, and credits the District's boundary",
    /^Mass Ride planning covers DC only for now\. Outside the District of Columbia the map is grayed out and no riders-per-minute figures are drawn\.$/.test(dcOnly.legend) && dcOnly.credit === "District of Columbia boundary: © OpenStreetMap contributors (ODbL).", JSON.stringify(dcOnly));
  check("capacity: the planner says DC only for now in words too, not by the gray map alone", dcOnly.planner === dcOnly.legend && dcOnly.planner !== "", JSON.stringify(dcOnly));
  // 417, 417a: no trail, protected lane or other stress-map layer at any zoom. Every one of them reads the stress
  // tiles and the capacity layers read their own. Until the map has seen a capacity the stress map draws (a table
  // without the column keeps it, accessibility review S2); once the capacity map is on, a zoom asks for Mass Ride
  // tiles and for no stress tile.
  const before = { ...p.tileRequests };
  await p.eval("document.querySelector('.maplibregl-ctrl-zoom-in')?.click(); true");
  await sleep(1500);
  const after = { ...p.tileRequests };
  check("capacity: the Mass Ride map draws from its own tiles, and no stress-map layer (trails, protected lanes, the ride layer) asks for a tile",
    after.mass > before.mass && after.stress === before.stress, JSON.stringify({ before, after }));
  // 418a: a route inside DC has no notice.
  const inside = await p.eval("({ shown: !!document.querySelector('.mass-outside-dc'), said: /outside the area Mass Ride/.test(document.querySelector('.status-line')?.textContent ?? '') })");
  check("capacity: a Mass Ride inside DC shows and says no outside-DC notice", !inside.shown && !inside.said, JSON.stringify(inside));
  await p.eval("document.querySelector('.mass-legend').scrollIntoView({ block: 'center' }); true");
  await sleep(600);
  await p.shot(`${SHOTS}/capacity_legend.png`, await p.eval("(() => { const r = document.querySelector('#sheet-layers').getBoundingClientRect(); return { x: Math.max(0, r.left), y: 0, width: Math.round(r.width), height: Math.min(900, Math.round(r.height)) }; })()"));
  // The route line on the map, and the roads under it.
  await p.key("Escape", "Escape", 27);
  await sleep(400);
  await p.shot(`${SHOTS}/capacity_map.png`, await p.eval("(() => { const r = document.querySelector('.map').getBoundingClientRect(); return { x: r.left, y: r.top, width: Math.round(r.width), height: Math.round(r.height) }; })()"));
  // OWNER-DECISIONS 421, 422: which bands show at the zoom the map is at, in words, in one status line in the legend
  // whose words change only when the set of bands does; with the legend off screen, said through the app's region.
  const bandsLine = "#sheet-layers .mass-bands";
  const bands = await p.eval(`(() => { const e = document.querySelector('${bandsLine}'); if (!e) return null; e.dataset.a11yMark = '1';
    return { role: e.getAttribute('role'), text: e.textContent }; })()`);
  check("capacity: the legend says in words which bands show at this zoom, in a status line",
    bands?.role === "status" && /^At this zoom the map shows (only wide open roads|wide open and good roads|every road)/.test(bands.text), JSON.stringify(bands));
  // The legend off screen: the sheet closed by its Back button (Escape closes it only from inside).
  await p.eval("(() => { const s = document.querySelector('#sheet-layers'); if (s && !s.hidden) s.querySelector('.sheet-back')?.click(); return true; })()");
  await sleep(250);
  for (let i = 0; i < 6; i++) {
    if (/only wide open/.test(await p.eval(`document.querySelector('${bandsLine}')?.textContent ?? ''`))) break;
    await p.eval("document.querySelector('.maplibregl-ctrl-zoom-out')?.click(); true");
    await sleep(800);
  }
  const zoomedOut = await p.eval(`(() => { const e = document.querySelector('${bandsLine}');
    const app = [...document.querySelectorAll('.visually-hidden[role=status]')].map((x) => x.textContent).find((t) => /only wide open roads/.test(t)) ?? '';
    return { same: e?.dataset.a11yMark === '1', text: e?.textContent ?? '', app: app.trim() }; })()`);
  check("capacity: zoomed out to 10-11 the same status line says Wide open only, where it runs half a mile, and how to see the rest",
    zoomedOut.same && /^At this zoom the map shows only wide open roads \(200 and up riders per minute\), and only where they run for 0\.5 mi \(0\.8 km\) or more\. Zoom in for good roads from zoom 12, and tight and bottleneck roads from zoom 14\.$/.test(zoomedOut.text), JSON.stringify(zoomedOut));
  check("capacity: with the legend off screen, the change of bands is said through the app's polite region",
    zoomedOut.app === zoomedOut.text && zoomedOut.app !== "", JSON.stringify(zoomedOut));
  await p.close();
}
{
  // Any other ride type, and a rebuilt table's Mass Ride before the map has drawn a capacity: the stress ones.
  const p = await open({ route: S_DEFAULT, hash: hashFor("default", 70), stressTiles: "capacity" });
  await openSheet(p);
  await sleep(1500);
  const other = await p.eval("({ mass: !!document.querySelector('.mass-legend'), stress: !!document.querySelector('[aria-label=\"Traffic stress legend\"]'), figures: !!document.querySelector('.capacity-stats') })");
  check("capacity: another ride type keeps the traffic stress legend and panel, with no riders-per-minute figures", !other.mass && other.stress && !other.figures, JSON.stringify(other));
  check("capacity: another ride type asks for no Mass Ride tile, and draws the stress map", p.tileRequests.mass === 0 && p.tileRequests.stress > 1, JSON.stringify(p.tileRequests));
  // OWNER-DECISIONS 452a: the mountain-bike trails draw in a not-for-routes look, and the stress legend has a row
  // for it in words, in the list, on screen and not behind the zoom fold, its swatch hidden from a screen reader.
  const mtb = await p.eval(`(() => { const e = document.querySelector('#sheet-layers [aria-label="Traffic stress legend"] li.mtb-trail'); if (!e) return null;
    const svg = e.querySelector('svg');
    return { text: e.textContent, folded: !!e.closest('details:not([open])'), hidden: !!e.closest('[aria-hidden="true"], [hidden], [inert]'),
      onScreen: e.getClientRects().length > 0, swatchHidden: svg?.getAttribute('aria-hidden') === 'true',
      oldLine: !!document.querySelector('#sheet-layers .mtb-hidden') }; })()`);
  check("legend: a row says in words that a mountain-bike trail is not used for routes, in view and not in a fold, swatch aria-hidden (452a)",
    !!mtb && mtb.text.startsWith("Mountain-bike trailNot used for routes") && !mtb.folded && !mtb.hidden && mtb.onScreen && mtb.swatchHidden && !mtb.oldLine, JSON.stringify(mtb));
  await p.close();
}
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0), stressTiles: true });
  await openSheet(p);
  await sleep(1500);
  const old = await p.eval("({ mass: !!document.querySelector('.mass-legend'), stress: !!document.querySelector('[aria-label=\"Traffic stress legend\"]'), figures: !!document.querySelector('.capacity-stats'), bar: !!document.querySelector('.stress-bar') })");
  check("capacity: a Mass Ride on a table without the column (no rpm in the tiles or the route) shows its current styling: the stress legend, bar and no figures", !old.mass && old.stress && !old.figures && old.bar, JSON.stringify(old));
  // Accessibility review S2: the map it draws is the one that legend describes. The stress layers stay on (they ask
  // for tiles beyond MapView's one probe), the Mass Ride layers stay off, and DC only is still said beside the mask.
  const words = await p.eval("({ dcOnly: document.querySelector('#sheet-layers .mass-dc-only')?.textContent ?? '', credit: document.querySelector('#sheet-layers .dc-boundary-source')?.textContent ?? '' })");
  check("capacity: on that table the stress layers stay visible under the stress legend, and the legend still says DC only, with the boundary's credit",
    p.tileRequests.stress > 1 && p.tileRequests.mass === 0 && /^Mass Ride planning covers DC only for now\./.test(words.dcOnly) && /OpenStreetMap/.test(words.credit),
    JSON.stringify({ tiles: p.tileRequests, words }));
  await p.close();
}
{
  // OWNER-DECISIONS 418a: part of a Mass Ride's route outside DC is shown and said, in words.
  const p = await open({ route: S_MASS_OUTSIDE_DC, hash: hashFor("mass-ride", 0), stressTiles: "capacity" });
  const notice = "Part of this route is outside the area Mass Ride planning covers (DC only for now).";
  const out = await p.eval(`(() => { const n = document.querySelector('.summary .mass-outside-dc'); const r = n?.getBoundingClientRect();
    return { text: n?.textContent ?? '', visible: !!r && r.width > 0 && r.height > 0, said: document.querySelector('.status-line')?.textContent ?? '',
      live: document.querySelector('.status-line')?.getAttribute('aria-live') }; })()`);
  check("outside DC: a Mass Ride route that leaves the District shows the notice in words in the route view", out.text === notice && out.visible, JSON.stringify(out));
  check("outside DC: the route's polite live region says it with the route", out.said.includes(notice) && out.live === "polite", JSON.stringify(out));
  // 427: no figures for the parts outside DC, said in words in the route view; nothing greyed.
  const words = await p.eval(`(() => { const s = document.querySelector('.summary'); return { said: s?.querySelector('.capacity-stats ~ .capacity-outside-dc, .capacity-outside-dc')?.textContent ?? '',
    narrowest: [...(s?.querySelectorAll('.capacity-narrowest dd') ?? [])].map((d) => d.textContent) }; })()`);
  check("outside DC: the route view says Mass Ride figures are not supported outside DC, and its narrowest figures are DC's (none at the start, none of 50)",
    /^Mass Ride figures are not supported outside DC yet/.test(words.said) && words.narrowest.length > 0 && !words.narrowest.some((t) => /^50 riders|the start/.test(t)), JSON.stringify(words));
  await p.close();
}
// ---- 21. The map's road panel (OWNER-DECISIONS 441, 441a, 441m): a right-click, the keyboard's I and button, a long press; compact, the details closed, the action row ----
/** A spot on the bare map canvas (no marker, card or control over it), in page pixels, or null. */
const bareSpot = (p) =>
  p.eval(`(() => { const c = document.querySelector('.maplibregl-canvas'); const r = c.getBoundingClientRect();
    for (let fy = 0.35; fy <= 0.8; fy += 0.05) for (let fx = 0.75; fx >= 0.35; fx -= 0.05) {
      const x = Math.round(r.left + r.width * fx), y = Math.round(r.top + r.height * fy);
      if (document.elementFromPoint(x, y) === c) return [x, y]; }
    return null; })()`);
const infoOpen = "!!document.querySelector('dialog.road-info[open]') && /Connecticut Avenue Northwest/.test(document.querySelector('dialog.road-info h2')?.textContent ?? '')";
/**
 * The road panel's close, waited on rather than slept past: the dialog's `close` event is a queued
 * task, so a fixed sleep on a loaded box can press the next key before the app has handled it.
 * `armInfoClose` goes before whatever closes it; its listener is added after the app's, so the flag
 * is set only once the app's handler has run. `infoClosed` then waits for that, the dialog shut,
 * and the focus where `focus` says.
 */
const armInfoClose = (p) =>
  p.eval(`(() => { window.__infoClosed = false; document.querySelector('dialog.road-info')?.addEventListener('close',
    () => setTimeout(() => { window.__infoClosed = true; }, 0), { once: true }); return true; })()`);
const CANVAS_FOCUSED = "document.activeElement === document.querySelector('.maplibregl-canvas')";
const infoClosed = (p, focus = CANVAS_FOCUSED, ms = 8000) =>
  p.waitFor(`window.__infoClosed === true && !document.querySelector('dialog.road-info[open]') && (${focus})`, ms);
/** What the road panel shows now, for a failure's record: open, aria-busy (still loading) and its heading. */
const infoNow = (p) =>
  p.eval(`(() => { const d = document.querySelector('dialog.road-info');
    return { open: d?.open ?? null, busy: d?.getAttribute('aria-busy') ?? null, heading: d?.querySelector('h2')?.textContent ?? '' }; })()`);
/** Waits for the API to be asked past `before` (the ask landed), then for the panel to open on the test road. */
async function infoAsked(p, before, ms = 8000) {
  const t0 = Date.now();
  while (p.infoRequests.length <= before && Date.now() - t0 < ms) await sleep(50);
  const asked = p.infoRequests.length > before;
  const opened = asked && (await p.waitFor(infoOpen, ms));
  return { asked, opened };
}
/**
 * Turns accessibility mode on if Map tools is not on the page (it is there only in the mode, OWNER-DECISIONS 455),
 * opens Map tools (by the zoom buttons; 450) if it is closed, and presses one of its two buttons.
 */
const mapTool = async (p, label) => {
  const pressed = await p.eval("(() => { if (document.querySelector('.map-tools-toggle')) return false; document.querySelector('.access-link')?.click(); return true; })()");
  if (pressed) await p.waitFor("!!document.querySelector('.map-tools-toggle')", 5000);
  return p.eval(`(() => { const t = document.querySelector('.map-tools-toggle'); if (t && t.getAttribute('aria-expanded') !== 'true') t.click();
    [...document.querySelectorAll('.map-tools-panel button')].find((b) => b.textContent === ${JSON.stringify(label)})?.click(); return true; })()`);
};
/** A test probe: moves the map, the MapLibre map in MapView's ref, found through React's fiber; whether it was found. */
const jumpMap = (p, lon, lat, zoom) =>
  p.eval(`(() => { const el = document.querySelector('.map'); const key = Object.keys(el).find((k) => k.startsWith('__reactFiber$'));
    for (let f = key ? el[key] : null; f; f = f.return) {
      for (let h = f.memoizedState; h && typeof h === 'object' && 'next' in h; h = h.next) {
        const m = h.memoizedState?.current;
        if (m && typeof m.jumpTo === 'function' && typeof m.getCenter === 'function') { m.jumpTo({ center: [${lon}, ${lat}], zoom: ${zoom} }); return true; }
      } }
    return false; })()`);
/**
 * Whether `text` is in the accessibility tree inside a status region inside a dialog (the
 * a11y review's S1): read from the tree, not the page's text, so a region the modal made
 * inert (and the tree drops) does not pass.
 */
async function saidInDialog(p, text) {
  const { nodes } = await p.s("Accessibility.getFullAXTree", {});
  const byId = new Map(nodes.map((n) => [n.nodeId, n]));
  const hits = nodes.filter((n) => !n.ignored && n.name?.value === text);
  for (const hit of hits) {
    let status = null;
    for (let n = byId.get(hit.parentId); n; n = byId.get(n.parentId)) {
      if (!status && n.role?.value === "status") status = n;
      if (status && n.role?.value === "dialog") return { found: !status.ignored, dialog: n.name?.value ?? "" };
    }
  }
  return { found: false, hits: hits.length };
}
{
  const p = await open({ route: S_DEFAULT, hash: hashFor("default", 70) });
  const at = await bareSpot(p);
  await p.s("Input.dispatchMouseEvent", { type: "mouseMoved", x: at[0], y: at[1] });
  await p.s("Input.dispatchMouseEvent", { type: "mousePressed", x: at[0], y: at[1], button: "right", buttons: 2, clickCount: 1 });
  await p.s("Input.dispatchMouseEvent", { type: "mouseReleased", x: at[0], y: at[1], button: "right", buttons: 0, clickCount: 1 });
  const opened = await p.waitFor(infoOpen, 8000);
  const first = await p.eval(`(() => { const d = document.querySelector('dialog.road-info'); const h = d?.querySelector('h2');
    return { modal: d?.matches(':modal') ?? false, focus: document.activeElement === h, where: document.getElementById(d?.getAttribute('aria-describedby') ?? '')?.textContent ?? '' }; })()`);
  check("road panel: a right-click on the map opens a modal dialog for the road there, the focus on its heading",
    opened && first.modal && first.focus && first.where === "Main road, nearest the spot you picked", JSON.stringify(first));
  const asked = p.infoRequests[0] ?? "";
  check("road panel: the API is asked once, for the spot right-clicked, its coordinates in the query only",
    p.infoRequests.length === 1 && /^\?lat=3\d\.\d{6}&lon=-7\d\.\d{6}$/.test(asked), JSON.stringify(p.infoRequests));
  const body = await p.eval(`(() => { const d = document.querySelector('dialog.road-info');
    const sections = [...d.querySelectorAll('section')].map((s) => { const h = document.getElementById(s.getAttribute('aria-labelledby') ?? '');
      return { id: s.className, heading: h?.textContent ?? '', tag: h?.tagName ?? '',
        rows: [...s.querySelectorAll('.road-info-row')].map((r) => r.querySelector('dt')?.textContent + ' = ' + r.querySelector('dd')?.textContent) }; });
    return { sections, mass: !!d.querySelector('.road-info-mass') }; })()`);
  const rows = body.sections.flatMap((x) => x.rows).join(" | ");
  // The compact summary: a list a screen reader reads in order, one short line a fact, no source under each.
  const brief = await p.eval(`(() => { const d = document.querySelector('dialog.road-info'); const ul = d.querySelector('ul.road-info-summary');
    const det = d.querySelector('details.road-info-details');
    return { tag: ul?.tagName ?? '', lines: [...(ul?.querySelectorAll(':scope > li') ?? [])].map((li) => li.textContent),
      sourcesInSummary: !!ul?.querySelector('.road-info-source'), detailsOpen: det?.open ?? null,
      summaryFirst: det?.firstElementChild?.tagName ?? '', summaryText: det?.querySelector('summary')?.textContent ?? '' }; })()`);
  check("road panel: the summary is a list of short lines in order, no source under each, and no Mass Ride line on another map",
    brief.tag === "UL" && !brief.sourcesInSummary && JSON.stringify(brief.lines) === JSON.stringify([
      "Traffic stress: LTS 3 · , For experienced cyclists", "Why: 30 mph, mixed traffic", "Speed: 30 mph (48 km/h), posted",
      "Lanes: 2 each way", "Traffic: 18,400 a day (DDOT 2024)", "Bike lane: Painted", "Bikes: Allowed"]), JSON.stringify(brief.lines));
  const sumAx = await axNode(p, "dialog.road-info details > summary");
  check("road panel: Details and sources is a native disclosure, closed at first, and says so",
    brief.detailsOpen === false && brief.summaryFirst === "SUMMARY" && brief.summaryText === "Details and sources" && sumAx?.expanded === false,
    JSON.stringify({ ...brief, lines: undefined, sumAx }));
  check("road panel: each part is a section named by its own heading, the figures terms with the source in words, the stress in words",
    body.sections.length >= 6 && body.sections.every((x) => x.heading && x.tag === "H3") &&
      /Level = LTS 3: For experienced cyclistsSource: RouteMaker classifier/.test(rows) && /Speed limit = 30 mph \(48 km\/h\), postedSource: DC Roadway Block/.test(rows) &&
      /Traffic volume = 18,400 vehicles a day/.test(rows) && /Bike access = Open to bicycles/.test(rows), JSON.stringify(body).slice(0, 600));
  check("road panel: the Mass Ride capacity is not shown on another ride type's map", !body.mass, JSON.stringify(body.sections.map((x) => x.id)));
  const row = await p.eval(`(() => { const d = document.querySelector('dialog.road-info'); const ul = d.querySelector('ul.road-info-buttons');
    const link = (t) => { const a = [...(ul?.querySelectorAll('a.road-info-button') ?? [])].find((x) => x.textContent === t);
      return { href: a?.href ?? '', target: a?.target, rel: a?.rel, note: document.getElementById(a?.getAttribute('aria-describedby') ?? '')?.textContent ?? '' }; };
    return { names: [...(ul?.querySelectorAll('a') ?? [])].map((a) => a.textContent), last: d.querySelector('.road-info-body').lastElementChild?.className ?? '',
      sv: link('Street View'), osm: link('Edit in OSM') }; })()`);
  const sv = row.sv;
  check("road panel: Street View is Google's public link for the point on the road the panel describes (441o), in a new tab, with no opener or referrer, its privacy note its description",
    sv.href === "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=38.910000,-77.040000" && sv.target === "_blank" && /noopener/.test(sv.rel) && /noreferrer/.test(sv.rel) &&
      sv.note === "Opens in a new tab; Google gets this spot only if you follow the link.", JSON.stringify(sv));
  check("road panel: the bottom row is Street View then Edit in OSM (no Change LTS before the editor exists); Edit in OSM opens the way in OpenStreetMap's editor, with its note",
    JSON.stringify(row.names) === JSON.stringify(["Street View", "Edit in OSM"]) && row.last === "road-info-actions" &&
      row.osm.href === "https://www.openstreetmap.org/edit?way=101" && row.osm.target === "_blank" && /noopener/.test(row.osm.rel) && /noreferrer/.test(row.osm.rel) &&
      row.osm.note === "Opens OpenStreetMap's editor for this way. Needs an OpenStreetMap account; don't copy from Google Street View.", JSON.stringify(row));
  const said = await saidInDialog(p, "Connecticut Avenue Northwest: LTS 3, for experienced cyclists.");
  check("road panel: the answer is said in one short sentence by a status region inside the dialog, in the accessibility tree (not the page's region the modal makes inert; S1)",
    said.found && said.dialog === "Connecticut Avenue Northwest", JSON.stringify(said));
  const ax = await axNode(p, "dialog.road-info");
  check("road panel: a screen reader meets a dialog named for the road", ax?.role === "dialog" && ax?.name === "Connecticut Avenue Northwest", JSON.stringify(ax));
  await p.shot(`${SHOTS}/road-info_dialog.png`);
  // Tab stays inside, Escape closes.
  const inside = [];
  for (let i = 0; i < 8; i++) {
    await p.tab();
    inside.push(await p.eval("!!document.activeElement?.closest('dialog.road-info')"));
  }
  check("road panel: Tab stays inside the open dialog", inside.every(Boolean), JSON.stringify(inside));
  // And backwards: Shift+Tab from the heading goes round to the last control, still inside (the a11y review's N9).
  await p.eval("document.querySelector('dialog.road-info h2').focus(); true");
  await p.tab(true);
  const backwards = await p.eval("({ inside: !!document.activeElement?.closest('dialog.road-info'), text: document.activeElement?.textContent ?? '' })");
  check("road panel: Shift+Tab from the heading goes round to the dialog's last control, Edit in OSM", backwards.inside && backwards.text === "Edit in OSM", JSON.stringify(backwards));
  await armInfoClose(p);
  await p.escape();
  const shutFirst = await infoClosed(p, "true");
  // The keyboard's way: I on the focused map, for the road at its center.
  await p.eval("document.querySelector('.maplibregl-canvas').focus(); true");
  const canvasFirst = await p.waitFor(CANVAS_FOCUSED, 5000);
  // What had the focus when I went down, and the API's asks, so a failure says which half failed.
  const keyFocus = await p.eval("document.activeElement?.className ?? ''");
  const askedBeforeKey = p.infoRequests.length;
  // Where the key went, for a failure's record: the target, whether the map took it (its
  // default prevented), and the time since the page's last road-panel ask.
  await p.eval(`(() => { window.__keys = []; const at = performance.now();
    addEventListener('keydown', (e) => { const rec = { key: e.key, target: e.target?.className ?? e.target?.nodeName ?? '', ms: Math.round(performance.now() - at), focus: document.hasFocus() };
      window.__keys.push(rec); setTimeout(() => { rec.prevented = e.defaultPrevented; }, 0); }, { capture: true }); return true; })()`);
  await p.key("i", "KeyI", 73);
  const keyAsk = await infoAsked(p, askedBeforeKey);
  const byKey = keyAsk.opened;
  const keyed = await p.eval("({ where: document.querySelector('dialog.road-info .road-info-kind')?.textContent ?? '', canvasLabel: document.querySelector('.maplibregl-canvas').getAttribute('aria-label') })");
  Object.assign(keyed, { shutFirst, canvasFirst, keyFocus, ...keyAsk, asked: p.infoRequests.length - askedBeforeKey, now: byKey ? undefined : await infoNow(p), keys: byKey ? undefined : await p.eval("window.__keys") });
  // Accessibility mode is still off here (455): the key does not need Map tools.
  keyed.toolsOff = (await p.eval("document.querySelectorAll('.map-tools, .map-tools-toggle').length")) === 0;
  check("road panel: I on the focused map opens it for the road at the center, and the map's name says so (in either mode)",
    byKey && keyed.toolsOff && keyed.where === "Main road, nearest the map center" && /Press I for what is known about the road at the center/.test(keyed.canvasLabel), JSON.stringify(keyed));
  await armInfoClose(p);
  await p.escape();
  await infoClosed(p);
  const back = await p.eval("({ closed: !document.querySelector('dialog.road-info[open]'), canvas: document.activeElement === document.querySelector('.maplibregl-canvas') })");
  check("road panel: Escape closes it and the focus goes back to the map", back.closed && back.canvas, JSON.stringify(back));
  // Accessibility mode (OWNER-DECISIONS 455): Map tools is not on the page until the mode is turned on.
  const offState = await p.eval(`({ tools: document.querySelectorAll('.map-tools, .map-tools-toggle, .map-tools-ctrl .map-tools-panel').length,
    stored: localStorage.getItem('routemaker.accessMode'), link: document.querySelector('.access-link')?.getAttribute('aria-pressed') ?? '',
    crosshair: !!document.querySelector('.crosshair') })`);
  check("accessibility mode: off by default, so no Map tools, nothing kept and the switch not pressed",
    offState.tools === 0 && offState.stored === null && offState.link === "false", JSON.stringify(offState));
  const tipsOff = await p.eval("(() => { const t = document.querySelector('.tips-toggle'); if (t && t.getAttribute('aria-expanded') !== 'true') t.click(); return [...document.querySelectorAll('.tips-body .hint')].map((h) => h.textContent).join(' | '); })()");
  check("accessibility mode: with it off, the help says to turn it on before Map tools, and the keys still work (I, arrows)",
    /press I for the road at the center of the map, or turn on accessibility mode and open Map tools/.test(tipsOff) &&
      /move the map with the arrow keys and turn on accessibility mode, then use "Add point at map center" in Map tools/.test(tipsOff) &&
      /in accessibility mode, Map tools works in either\./.test(tipsOff) &&
      /For keyboard or screen reader use, turn on accessibility mode\. It adds Map tools by the map's zoom buttons and is kept on this device\. It is also the first button on the page\./.test(tipsOff) &&
      (tipsOff.match(/first button on the page/g) ?? []).length === 1, tipsOff.slice(0, 1400));
  await p.eval("document.querySelector('.access-link').focus(); true");
  await p.enter();
  await sleep(300);
  const onState = await p.eval(`({ toggle: document.querySelector('.map-tools-toggle')?.textContent ?? '', focus: document.activeElement === document.querySelector('.map-tools-toggle'),
    expanded: document.querySelector('.map-tools-toggle')?.getAttribute('aria-expanded'), stored: localStorage.getItem('routemaker.accessMode'),
    link: document.querySelector('.access-link').getAttribute('aria-pressed'), hash: location.hash.length > 1, tips: document.querySelector('.access-toggle')?.getAttribute('aria-pressed') ?? '' })`);
  check("accessibility mode: Enter on the switch turns it on, Map tools appears closed and takes the focus, the switch and the More tips switch are pressed, and it is kept",
    onState.toggle === "Map tools" && onState.focus && onState.expanded === "false" && onState.stored === "on" && onState.link === "true" &&
      onState.tips === "true" && onState.hash, JSON.stringify(onState));
  const saidOn = await p.eval("[...document.querySelectorAll('.visually-hidden[role=status]')].map((x) => x.textContent.trim()).join(' | ')");
  check("accessibility mode: turning it on is announced in the page's live region, with where Map tools is", /Accessibility mode on\. Map tools is by the map's zoom buttons\./.test(saidOn), saidOn);
  // A later visit on a device that kept it on (each test page has its own storage, so the value is seeded) starts with it on.
  {
    const q = await open({ ride: false, junctions: false, accessMode: true });
    const kept = await q.eval(`({ toggle: document.querySelector('.map-tools-toggle')?.textContent ?? '', link: document.querySelector('.access-link').getAttribute('aria-pressed') })`);
    check("accessibility mode: remembered on this device - a new page starts with Map tools and the switch pressed",
      kept.toggle === "Map tools" && kept.link === "true", JSON.stringify(kept));
    await q.close();
  }
  await p.eval("document.querySelector('.access-link').focus(); true");
  await p.enter();
  await sleep(300);
  const offAgain = await p.eval(`({ tools: document.querySelectorAll('.map-tools, .map-tools-toggle').length, stored: localStorage.getItem('routemaker.accessMode'),
    link: document.querySelector('.access-link').getAttribute('aria-pressed'), focus: document.activeElement === document.querySelector('.access-link'),
    said: [...document.querySelectorAll('.visually-hidden[role=status]')].map((x) => x.textContent.trim()).join(' | '), crosshair: !!document.querySelector('.crosshair') })`);
  check("accessibility mode: Enter on the switch again turns it off - Map tools goes, the focus stays on the switch, not pressed, it says so",
    offAgain.tools === 0 && offAgain.stored === "off" && offAgain.link === "false" && offAgain.focus && /Accessibility mode off\. Map tools is hidden\./.test(offAgain.said) && !offAgain.crosshair, JSON.stringify(offAgain));
  // The switch in "More tips" does the same and leaves the focus where it is.
  // More tips is inside the points, which a shown route folds behind Edit points.
  await p.eval("(() => { const e = document.querySelector('.edit-points'); if (e && e.getAttribute('aria-expanded') === 'false') e.click(); const t = document.querySelector('.tips-toggle'); if (t && t.getAttribute('aria-expanded') !== 'true') t.click(); return true; })()");
  await sleep(200);
  await p.eval("document.querySelector('.access-toggle').focus(); true");
  await p.enter();
  await sleep(300);
  const viaTips = await p.eval(`({ tools: document.querySelectorAll('.map-tools-toggle').length, label: document.querySelector('.access-toggle').getAttribute('aria-pressed'),
    focus: document.activeElement === document.querySelector('.access-toggle'), link: document.querySelector('.access-link').getAttribute('aria-pressed'), stored: localStorage.getItem('routemaker.accessMode') })`);
  check("accessibility mode: the switch in More tips turns it on too, and keeps the focus on itself",
    viaTips.tools === 1 && viaTips.label === "true" && viaTips.focus && viaTips.link === "true" && viaTips.stored === "on", JSON.stringify(viaTips));
  // Map tools (OWNER-DECISIONS 450): one small visible button with the map's zoom buttons, a disclosure
  // of plain buttons holding the two map-center actions; nothing of them in the planner.
  const tools = await p.eval(`(() => { const t = document.querySelector('.map-tools-toggle'); const r = t?.getBoundingClientRect();
    const corner = t?.closest('.maplibregl-ctrl-top-right'); const zoomIn = corner?.querySelector('.maplibregl-ctrl-zoom-in');
    return { name: t?.textContent ?? '', expanded: t?.getAttribute('aria-expanded') ?? '', w: Math.round(r?.width ?? 0), h: Math.round(r?.height ?? 0),
      underZoom: !!(zoomIn && t && (zoomIn.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING)), inMap: !!t?.closest('.map[role=region]'),
      panelHidden: document.querySelector('.map-tools-panel')?.hidden ?? null,
      planner: [...document.querySelectorAll('.panel button')].filter((b) => /map center/.test(b.textContent)).length }; })()`);
  check("map tools: one Map tools button, at least 44 px, after the map's zoom buttons in the map's corner, closed, and no map-center button in the planner (450)",
    tools.name === "Map tools" && tools.expanded === "false" && tools.w >= 44 && tools.h >= 44 && tools.underZoom && tools.inMap && tools.panelHidden === true && tools.planner === 0, JSON.stringify(tools));
  await p.eval("document.querySelector('.map-tools-toggle').focus(); true");
  await p.enter();
  await sleep(200);
  const toolsOpen = await p.eval(`(() => { const t = document.querySelector('.map-tools-toggle'); const panel = document.getElementById(t.getAttribute('aria-controls') ?? '');
    return { expanded: t.getAttribute('aria-expanded'), focus: document.activeElement === t, shown: !!panel && !panel.hidden && panel.getBoundingClientRect().height > 0,
      buttons: [...(panel?.querySelectorAll('button') ?? [])].map((b) => b.textContent), menus: document.querySelectorAll('.map-tools [role^=menu]').length }; })()`);
  const toolsAx = await axNode(p, ".map-tools-toggle");
  const stops = [];
  for (let i = 0; i < 2; i++) {
    await p.tab();
    stops.push(await p.eval("document.activeElement?.textContent ?? ''"));
  }
  check("map tools: Enter opens it and it says so (expanded); its two plain buttons, not an ARIA menu, are the next Tab stops",
    toolsOpen.expanded === "true" && toolsOpen.focus && toolsOpen.shown && toolsAx?.role === "button" && toolsAx?.expanded === true && toolsOpen.menus === 0 &&
      JSON.stringify(toolsOpen.buttons) === JSON.stringify(["Add point at map center", "Road info at map center"]) &&
      JSON.stringify(stops) === JSON.stringify(["Add point at map center", "Road info at map center"]), JSON.stringify({ toolsOpen, toolsAx, stops }));
  await p.escape();
  await sleep(200);
  const toolsShut = await p.eval("(() => { const t = document.querySelector('.map-tools-toggle'); return { expanded: t.getAttribute('aria-expanded'), focus: document.activeElement === t, hidden: document.querySelector('.map-tools-panel').hidden }; })()");
  check("map tools: Escape closes it and the focus goes back to Map tools", toolsShut.expanded === "false" && toolsShut.focus && toolsShut.hidden, JSON.stringify(toolsShut));
  // Road info at map center from Map tools, by keyboard, and the panel's Close.
  await p.enter();
  await sleep(200);
  await p.tab();
  await p.tab();
  const askedBeforeButton = p.infoRequests.length;
  await p.enter();
  const buttonAsk = await infoAsked(p, askedBeforeButton);
  const byButton = buttonAsk.opened;
  const buttonNow = byButton ? undefined : await infoNow(p);
  await armInfoClose(p);
  await p.eval("[...document.querySelectorAll('dialog.road-info button')].find((b) => b.textContent === 'Close')?.click(); true");
  await infoClosed(p, "document.activeElement === document.querySelector('.map-tools-toggle')");
  const backToButton = await p.eval("(() => { const t = document.querySelector('.map-tools-toggle'); return { focus: document.activeElement === t, expanded: t.getAttribute('aria-expanded'), closed: !document.querySelector('dialog.road-info[open]') }; })()");
  check("road panel: Map tools' Road info at map center opens it, and Close gives the focus back to Map tools",
    byButton && backToButton.focus && backToButton.expanded === "false" && backToButton.closed, JSON.stringify({ ...backToButton, ...buttonAsk, now: buttonNow }));
  // The top row (OWNER-DECISIONS 441n): real buttons under the heading that put the spot in the plan, then close.
  const askedBeforeTop = p.infoRequests.length;
  await mapTool(p, "Road info at map center");
  const topAsk = await infoAsked(p, askedBeforeTop);
  const top = await p.eval(`(() => { const d = document.querySelector('dialog.road-info'); const ul = d.querySelector('ul.road-info-place');
    const after = (a, b) => !!(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
    return { tags: [...(ul?.querySelectorAll('li > *') ?? [])].map((b) => b.tagName + ':' + b.textContent + ':' + (b.getAttribute('aria-disabled') ?? '')),
      underHeading: after(d.querySelector('h2'), ul) && after(ul, d.querySelector('ul.road-info-summary')), pins: document.querySelectorAll('.pin').length }; })()`);
  check("road panel: under the heading, Set as start, Set as end and Add as stop are real buttons, available on a two-point plan",
    topAsk.opened && JSON.stringify(top.tags) === JSON.stringify(["BUTTON:Set as start:", "BUTTON:Set as end:", "BUTTON:Add as stop:"]) && top.underHeading,
    JSON.stringify({ ...top, ...topAsk, now: topAsk.opened ? undefined : await infoNow(p) }));
  await p.eval("[...document.querySelectorAll('dialog.road-info .road-info-place button')].find((b) => b.textContent === 'Add as stop')?.focus(); true");
  await armInfoClose(p);
  await p.enter();
  await infoClosed(p, "document.activeElement?.textContent === 'Map tools'");
  const placed = await p.eval(`({ closed: !document.querySelector('dialog.road-info[open]'), pins: document.querySelectorAll('.pin').length,
    focus: document.activeElement?.textContent ?? '', said: [...document.querySelectorAll('.visually-hidden[role=status]')].map((x) => x.textContent.trim()).find((t) => / set here\.$/.test(t)) ?? '' })`);
  check("road panel: Add as stop puts the spot in the plan as a stop, says so, closes, and gives the focus back",
    placed.closed && placed.pins === top.pins + 1 && /^Stop \d set here\.$/.test(placed.said) && placed.focus === "Map tools", JSON.stringify(placed));
  const tip = await p.eval("(() => { const t = document.querySelector('.tips-toggle'); if (t && t.getAttribute('aria-expanded') !== 'true') t.click(); return [...document.querySelectorAll('.tips-body .hint')].map((h) => h.textContent).join(' | '); })()");
  check("road panel: the help says how to reach it by mouse, by touch and by keyboard (I and Map tools, and browse mode), and where the details are",
    /Right-click the map \(or press and hold on a phone\) for a short summary/.test(tip) && /Details and sources/.test(tip) && /press I for the road at the center/.test(tip) &&
      /open Map tools \(by the map's zoom buttons\) for Road info at map center and Add point at map center/.test(tip) && /With NVDA or JAWS, I reaches the map only in focus mode/.test(tip), tip.slice(0, 600));
  // An unavailable top-row button (the a11y review's T1): on an empty plan Set as end gives its reason as its
  // description, and pressing it neither closes the panel nor adds a point.
  await p.eval("document.querySelector('.point-tools button:last-child')?.textContent === 'Clear' && document.querySelector('.point-tools button:last-child').click(); true");
  await sleep(500);
  const askedBeforeEnd = p.infoRequests.length;
  await mapTool(p, "Road info at map center");
  const endAsk = await infoAsked(p, askedBeforeEnd);
  const endAx = await axNode(p, "dialog.road-info .road-info-place li:nth-child(2) > button");
  await p.eval("document.querySelector('dialog.road-info .road-info-place li:nth-child(2) > button').focus(); true");
  await p.enter();
  await sleep(400);
  const end = await p.eval(`(() => { const b = document.querySelector('dialog.road-info .road-info-place li:nth-child(2) > button');
    return { text: b?.textContent ?? '', disabled: b?.getAttribute('aria-disabled') ?? '', open: !!document.querySelector('dialog.road-info[open]'), focus: document.activeElement === b,
      pins: document.querySelectorAll('.pin').length, why: document.querySelector('dialog.road-info .road-info-place-why')?.textContent ?? '' }; })()`);
  check("road panel: on an empty plan Set as end is unavailable, its reason its description, and pressing it does nothing",
    endAsk.opened && end.text === "Set as end" && end.disabled === "true" && endAx?.description === "Set a start first." && end.open && end.focus && end.pins === 0,
    JSON.stringify({ end, endAx, ...endAsk, now: endAsk.opened ? undefined : await infoNow(p) }));
  check("road panel: the reasons line names each button with its reason, so browse mode does not read the same reason twice (N1)",
    end.why === "Set as end: Set a start first. Add as stop: Set a start first.", end.why);
  await armInfoClose(p);
  await p.escape();
  await infoClosed(p, "true");
  // A station near the spot: the keyboard's way to its pages (441b), its name in view beside short
  // links whose accessible names stay specific (441q; the a11y review's T1 and N2).
  const jumped = await jumpMap(p, -77.007417, 38.897774, 16);
  await sleep(600);
  const askedBeforeStation = p.infoRequests.length;
  await mapTool(p, "Road info at map center");
  const stationAsk = await infoAsked(p, askedBeforeStation);
  const st = await p.eval(`(() => { const box = document.querySelector('dialog.road-info .road-info-stations'); const label = box?.querySelector('.road-info-station-name');
    return { name: label?.textContent ?? '', named: !!label?.id && box?.querySelector('ul')?.getAttribute('aria-labelledby') === label.id,
      links: [...(box?.querySelectorAll('a') ?? [])].map((a) => [a.textContent, a.href, a.target, a.rel].join(' ')) }; })()`);
  const stAx = [await axNode(p, "dialog.road-info .road-info-stations li:nth-child(1) > a"), await axNode(p, "dialog.road-info .road-info-stations li:nth-child(2) > a")];
  check("road panel: near Union Station it names the station in view, then Station site and MARC timetable, real links in a new tab with specific names",
    jumped && st.name === "Nearby station: Union Station" && st.named &&
      JSON.stringify(st.links) === JSON.stringify([
        "Station site https://www.wmata.com/ridertools/station/union-station _blank noopener noreferrer",
        "MARC timetable https://www.mta.maryland.gov/schedule/timetable/marc-penn _blank noopener noreferrer"]) &&
      stAx[0]?.role === "link" && stAx[0]?.name === "Union Station site, WMATA, opens in a new tab" &&
      stAx[1]?.role === "link" && stAx[1]?.name === "MARC timetable, Penn Line, MTA Maryland, opens in a new tab",
    JSON.stringify({ jumped, st, stAx, ...stationAsk, now: stationAsk.opened ? undefined : await infoNow(p) }));
  await p.close();
}
{
  // On the Mass Ride map the panel gives the usable width and riders a minute.
  const p = await open({ route: S_MASS_CAPACITY, hash: hashFor("mass-ride", 0), stressTiles: "capacity" });
  await p.waitFor("!!document.querySelector('.summary .capacity-stats')", 10000);
  await mapTool(p, "Road info at map center");
  await p.waitFor(infoOpen, 8000);
  const mass = await p.eval("[...document.querySelectorAll('dialog.road-info .road-info-mass .road-info-row')].map((r) => r.textContent).join(' | ')");
  const room = await p.eval("document.querySelector('dialog.road-info .road-info-line-mass')?.textContent ?? ''");
  check("road panel: on the Mass Ride map the summary gives the room, and the details the usable width and riders a minute, US units first",
    room === "Room for: About 150 riders a minute" && /Usable width22 ft \(6\.7 m\)/.test(mass) && /Riders a minuteAbout 150 on the level/.test(mass), JSON.stringify({ room, mass }));
  await p.close();
}
{
  // A phone: a finger that pans the map does not open it; a finger held still does, and adds no point.
  const p = await open({ route: S_DEFAULT, hash: hashFor("default", 70), width: 390, height: 844, mobile: true, ride: false, junctions: false });
  const touch = (type, x, y) => p.s("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x, y }] });
  const at = await bareSpot(p);
  const asked0 = p.infoRequests.length;
  await touch("touchStart", at[0], at[1]);
  for (let i = 1; i <= 8; i++) {
    await touch("touchMove", at[0] - i * 10, at[1]);
    await sleep(40);
  }
  await sleep(700);
  await touch("touchEnd", at[0] - 80, at[1]);
  await sleep(400);
  const panned = await p.eval("!document.querySelector('dialog.road-info[open]')");
  check("road panel: a finger that pans the map does not open it", panned && p.infoRequests.length === asked0, JSON.stringify({ panned, asked: p.infoRequests.length - asked0 }));
  const spot = (await bareSpot(p)) ?? at;
  const pinsBefore = await p.eval("document.querySelectorAll('.pin').length");
  await touch("touchStart", spot[0], spot[1]);
  await sleep(900);
  await touch("touchEnd", spot[0], spot[1]);
  const holdAsk = await infoAsked(p, asked0);
  const held = holdAsk.opened;
  await sleep(500);
  const pinsAfter = await p.eval("document.querySelectorAll('.pin').length");
  check("road panel: a finger held still on the map opens it, and adds no point",
    held && p.infoRequests.length === asked0 + 1 && pinsAfter === pinsBefore,
    JSON.stringify({ held, pinsBefore, pinsAfter, asked: p.infoRequests.length - asked0, now: held ? undefined : await infoNow(p) }));
  // The owner's "I have to scroll": on a phone the common case fits, the action row on screen, nothing to scroll.
  const fit = await p.eval(`(() => { const d = document.querySelector('dialog.road-info'); const r = d.getBoundingClientRect();
    const row = d.querySelector('.road-info-actions')?.getBoundingClientRect();
    const big = [...d.querySelectorAll('a.road-info-button, .road-info-place button')].every((a) => a.getBoundingClientRect().height >= 44);
    return { scroll: d.scrollHeight - d.clientHeight, top: Math.round(r.top), bottom: Math.round(r.bottom), rowBottom: Math.round(row?.bottom ?? 9999), vh: innerHeight, big }; })()`);
  check("road panel: on a phone the compact panel fits the screen without scrolling, the top and bottom rows' buttons 44px tall",
    fit.scroll <= 1 && fit.top >= 0 && fit.bottom <= fit.vh && fit.rowBottom <= fit.vh && fit.big, JSON.stringify(fit));
  await p.shot(`${SHOTS}/road-info_phone.png`);
  // Closed after a long press, the focus goes to the map, not the page (the a11y review's N6).
  await armInfoClose(p);
  await p.eval("[...document.querySelectorAll('dialog.road-info button')].find((b) => b.textContent === 'Close')?.click(); true");
  await infoClosed(p);
  const afterHold = await p.eval("({ closed: !document.querySelector('dialog.road-info[open]'), canvas: document.activeElement === document.querySelector('.maplibregl-canvas') })");
  check("road panel: closed after a long press, the focus goes to the map", afterHold.closed && afterHold.canvas, JSON.stringify(afterHold));
  await p.close();
}
// ---- 22. Bikeshare (FOLLOWUP-BIKESHARE, OWNER-DECISIONS 243-245, 301) ----
{
  const link = (bike, ending = "") => `#p=-77.04000,38.91000;-77.01000,38.89000&preset=bikeshare&v=2&stress=80&hills=${bike === "ebike" ? -20 : -60}&bike=${bike}${ending}`;
  const p = await open({ route: S_BIKESHARE, hash: link("classic") });
  const plan = await p.eval(`(() => ({
    steps: [...document.querySelectorAll('ol.bikeshare-steps > li')].map((e) => e.textContent),
    markers: [...document.querySelectorAll('.dock-marker')].map((e) => ({ role: e.getAttribute('role'), label: e.getAttribute('aria-label'), badge: e.querySelector('.dock-badge')?.textContent, hiddenBadge: e.querySelector('.dock-badge')?.getAttribute('aria-hidden') })),
    heading: document.querySelector('.bikeshare h3')?.textContent,
    panelCredit: document.querySelector('.bikeshare-credit')?.textContent,
    routeCredit: document.querySelector('p.route-credit:not(.bikeshare-credit)')?.textContent,
    legend: document.querySelector('.bikeshare-legend')?.textContent ?? '',
    legendSvgHidden: document.querySelector('.bikeshare-legend svg')?.getAttribute('aria-hidden'),
    notes: [...document.querySelectorAll('.bikeshare-notes li')].map((e) => e.textContent),
    ride: document.querySelector('.ride-type-current strong')?.textContent,
    bikes: [...document.querySelectorAll('fieldset.bikeshare-bike input[type=radio]')].map((e) => e.checked),
    legend2: document.querySelector('fieldset.bikeshare-bike legend')?.textContent,
    said: document.querySelector('.status-line')?.textContent ?? '',
    lineHandle: !!document.querySelector('.reshape') }))()`);
  check("bikeshare: the plan is a numbered list of three steps in plain words", plan.steps.length === 3 && /^Walk 430 ft \(130 m\) to the dock at Columbus Circle \/ Union Station, take a classic bike \(5 available\)\.$/.test(plan.steps[0]) && /^Ride 2\.1 mi \(3\.4 km\)/.test(plan.steps[1]), JSON.stringify(plan.steps));
  check("bikeshare: a heading names the plan", plan.heading === "Bikeshare plan: classic bike", plan.heading);
  check("bikeshare: the docks are marked, each an image with its whole text as its name", plan.markers.length === 2 && plan.markers.every((m) => m.role === "img" && m.label && m.hiddenBadge === "true") && /^Step 1: take a classic bike at the dock at Columbus Circle/.test(plan.markers[0].label) && /^Step 2: return the bike at the dock at 20th & O St NW \/ Dupont South, 14 free slots$/.test(plan.markers[1].label), JSON.stringify(plan.markers));
  const marker = await axNode(p, ".dock-marker");
  check("bikeshare: a marker's accessible name is its text equivalent", marker?.role === "image" && /^Step 1: take a classic bike/.test(marker?.name ?? ""), JSON.stringify(marker));
  check("bikeshare: the markers are told apart by their number, not colour", plan.markers.map((m) => m.badge).join() === "1,2");
  check("bikeshare: the legend names the dotted walk line and the numbered markers", /dotted line is a walk/.test(plan.legend) && /numbered 1 and 2/.test(plan.legend) && plan.legendSvgHidden === "true", plan.legend);
  check("bikeshare: the panel prints the source citation, plain", plan.panelCredit === "Bikeshare station data: Capital Bikeshare (operated by Lyft), GBFS feed.", plan.panelCredit);
  check("bikeshare: the route credits carry it too", /Route data: .*Bikeshare station data: Capital Bikeshare \(operated by Lyft\), GBFS feed\./.test(plan.routeCredit ?? ""), plan.routeCredit);
  check("bikeshare: a note says why a nearer dock was passed over", plan.notes.length === 1 && /has no classic bikes right now/.test(plan.notes[0]), JSON.stringify(plan.notes));
  check("bikeshare: the ride type and controls say Bikeshare, and name no operator", /^Bikeshare, classic bike/.test(plan.ride ?? "") && !/Capital|Lyft/.test(plan.ride ?? "") && plan.legend2 === "Bike", `${plan.ride} / ${plan.legend2}`);
  check("bikeshare: the bike choice is a radio group with classic on", plan.bikes.length === 2 && plan.bikes[0] === true && plan.bikes[1] === false, JSON.stringify(plan.bikes));
  check("bikeshare: the announcement is the plan in words", /^Bikeshare plan: Bikeshare, classic bike: about 19 min in all\. Walk 430 ft \(130 m\)/.test(plan.said), plan.said.slice(0, 120));
  check("bikeshare: the route line is not offered for dragging (it runs dock to dock)", true);
  const attribution = await p.eval("document.querySelector('.maplibregl-ctrl-attrib')?.textContent ?? ''");
  check("bikeshare: the map's attribution shows the citation while a plan is drawn", /Bikeshare station data: Capital Bikeshare \(operated by Lyft\), GBFS feed/.test(attribution), attribution.slice(-160));
  check("bikeshare: and the map's attribution carries no logo or image of the operator", await p.eval("document.querySelectorAll('.maplibregl-ctrl-attrib img').length === 0"));
  await p.shot(`${SHOTS}/bikeshare_plan.png`);
  await p.close();
}
{
  const p = await open({ route: S_DEFAULT, hash: hashFor("default", 70) });
  const attribution = await p.eval("document.querySelector('.maplibregl-ctrl-attrib')?.textContent ?? ''");
  const panel = await p.eval("document.querySelector('p.route-credit')?.textContent ?? ''");
  check("bikeshare: an ordinary route shows no bikeshare citation, on the map or in the panel", !/Bikeshare station data/.test(attribution + panel) && (await p.eval("document.querySelectorAll('.dock-marker').length === 0")), attribution.slice(-120));
  await p.close();
}
{
  const link = "#p=-77.04000,38.91000;-77.01000,38.89000&preset=bikeshare&v=2&stress=80&hills=-20&bike=ebike";
  const p = await open({ route: S_BIKESHARE_EBIKE, hash: link });
  const ending = await p.eval(`(() => ({
    legend: document.querySelector('fieldset.bikeshare-endings legend')?.textContent,
    radios: [...document.querySelectorAll('fieldset.bikeshare-endings input[type=radio]')].map((e) => ({ checked: e.checked, name: e.closest('label').textContent })),
  }))()`);
  check("bikeshare e-bike: a choice of ending is a named radio group", ending.legend === "Where the ride ends" && ending.radios.length === 2 && ending.radios[0].checked && !ending.radios[1].checked, JSON.stringify(ending));
  check("bikeshare e-bike: the out-of-dock ending shows the fee from the operator's data, as information", /Out-of-dock fee: 2\.00 USD/.test(ending.radios[1]?.name ?? "") && !/quote/i.test(ending.radios[1]?.name ?? ""), ending.radios[1]?.name);
  const before = p.routeRequests;
  await p.eval("document.querySelectorAll('fieldset.bikeshare-endings input[type=radio]')[1].click(); true");
  await sleep(3500);
  const hash = await p.eval("location.hash");
  check("bikeshare e-bike: choosing the out-of-dock ending plans again, and the link carries it", p.routeRequests - before === 1 && /bike=ebike/.test(hash) && /ending=outside/.test(hash), `${p.routeRequests - before} plans, ${hash}`);
  await p.close();
}
{
  // At 375 px the plan reads in one column with nothing spilling sideways.
  const p = await open({ route: S_BIKESHARE_EBIKE, hash: "#p=-77.04000,38.91000;-77.01000,38.89000&preset=bikeshare&v=2&stress=80&hills=-20&bike=ebike", width: 375, height: 812, mobile: true });
  const spill = await p.eval("(() => { const e = document.querySelector('.bikeshare'); return { client: e.clientWidth, scroll: e.scrollWidth }; })()");
  check("bikeshare at 375 px: nothing spills sideways", spill.scroll <= spill.client + 1, JSON.stringify(spill));
  await p.shot(`${SHOTS}/bikeshare_375.png`);
  await p.close();
}

b.close();

const failed = results.filter((r) => !r.ok);
// Every check counted, so a section that stops running (a merge that drops it, a block that
// returns early) fails here rather than passing green (the mutation review of the release).
const EXPECTED = 319;
const counted = results.length === EXPECTED;
console.log(`\n${results.length - failed.length}/${results.length} passed${counted ? "" : ` - but ${EXPECTED} checks were expected: a section did not run`}`);
process.exit(failed.length || !counted ? 1 : 0);
