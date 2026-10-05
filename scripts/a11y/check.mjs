// The browser check for the combined a11y review's fixes (FIX-A11Y): focus
// order, Escape, focus return, the credits at 375 px and the focus ring's
// contrast, against the app under Vite with a mocked API. Run by
// scripts/a11y/run.sh, which starts Vite and an offline Chromium; prints one
// line per check and exits non-zero if any fails.
//
//   node scripts/a11y/check.mjs [--port 5173] [--shots DIR]
import { mkdirSync } from "node:fs";
import { S_CHOICES, S_DEFAULT, S_MASS, S_OVER, S_TRAIL, axNode, connect, contrast, decodePng, hashFor, media, mock, newPage, sleep } from "./cdp.mjs";

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
async function open({ route = S_DEFAULT, hash = hashFor("default", 70), width = 1280, height = 900, scheme = "light", forced = false, mobile = false, delayMs = 0, delayFrom = 2, stressTiles = true, ride = true, junctions = true } = {}) {
  const p = await newPage(b, { width, height, mobile });
  if (mobile) await p.s("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await mock(p, route, { delayMs, delayFrom, stressTiles });
  await media(p, { scheme, forced });
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

// ---- 1. Focus order: the skip link first, and it skips the map ----
{
  const p = await open({ route: S_TRAIL, hash: hashFor("trailmaxxing", 100) });
  await p.eval("document.activeElement?.blur(); true");
  await p.tab();
  const first = await focused(p);
  const skip = await p.eval("(() => { const e = document.querySelector('.skip-link'); const r = e.getBoundingClientRect(); return { focused: document.activeElement === e, visible: r.top >= 0 && r.bottom <= innerHeight && r.width > 40 }; })()");
  check("focus order: the first Tab stop is the skip link, and it shows", skip.focused && skip.visible, first);
  await p.shot(`${SHOTS}/skip-link_focused.png`, { x: 0, y: 0, width: 420, height: 90 });
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
  await p.eval("window.__said = []; const live = document.querySelector('p.visually-hidden[role=status]'); new MutationObserver(() => { const t = live.textContent.trim(); if (t) window.__said.push(t); }).observe(live, { childList: true, subtree: true, characterData: true }); true");
  await p.eval("document.querySelector('.loop-toggle input').focus(); true");
  await p.key(" ", "Space", 32);
  await sleep(700);
  const on = await axNode(p, ".loop-toggle input");
  const hint = await p.eval("(() => { const h = document.getElementById(document.querySelector('.loop-toggle input').getAttribute('aria-describedby')); const r = h.getBoundingClientRect(); return { text: h.textContent, visible: r.height > 0 && getComputedStyle(h).visibility !== 'hidden' }; })()");
  check("loop first: checked with no point, the hint is visible text, \"Place the starting point, then a stop or two along the way.\"", on?.checked === true && hint.visible && hint.text === FIRST_HINT, JSON.stringify(hint));
  check("loop first: the box is described by it", on?.description === FIRST_HINT, JSON.stringify(on?.description));
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
  await p.close();
}

b.close();
const failed = results.filter((r) => !r.ok);
// Every check counted, so a section that stops running (a merge that drops it, a block that
// returns early) fails here rather than passing green (the mutation review of the release).
const EXPECTED = 182;
const counted = results.length === EXPECTED;
console.log(`\n${results.length - failed.length}/${results.length} passed${counted ? "" : ` - but ${EXPECTED} checks were expected: a section did not run`}`);
process.exit(failed.length || !counted ? 1 : 0);
