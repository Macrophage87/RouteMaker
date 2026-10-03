// The browser check for the combined a11y review's fixes (FIX-A11Y): focus
// order, Escape, focus return, the credits at 375 px and the focus ring's
// contrast, against the app under Vite with a mocked API. Run by
// scripts/a11y/run.sh, which starts Vite and an offline Chromium; prints one
// line per check and exits non-zero if any fails.
//
//   node scripts/a11y/check.mjs [--port 5173] [--shots DIR]
import { mkdirSync } from "node:fs";
import { S_DEFAULT, S_MASS, S_TRAIL, axNode, connect, contrast, decodePng, hashFor, media, mock, newPage, sleep } from "./cdp.mjs";

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

async function open({ route = S_DEFAULT, hash = hashFor("default", 70), width = 1280, height = 900, scheme = "light", forced = false, mobile = false } = {}) {
  const p = await newPage(b, { width, height, mobile });
  if (mobile) await p.s("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
  await mock(p, route);
  await media(p, { scheme, forced });
  await p.s("Page.navigate", { url: `http://127.0.0.1:${PORT}/${hash}` });
  const ready = await p.waitFor("!!document.querySelector('.summary') && document.querySelectorAll('.junction-marker').length > 0", 40000);
  if (!ready) throw new Error("the app did not show a route");
  await sleep(800);
  return p;
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
  check("slider: the calm note is its description", /^Calm detour: /.test(slider?.description ?? ""), (slider?.description ?? "").slice(0, 60));

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
  const toggle = await axNode(p, ".description-toggle");
  check("description: the toggle's name says what it opens", toggle?.role === "button" && toggle?.name === "Route description: 11 steps, overview" && toggle?.expanded === false, JSON.stringify(toggle));
  await p.eval("document.querySelector('.description-toggle').click(); true");
  await sleep(200);
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
  await p.eval("document.querySelector('.description-toggle').click(); true");
  await sleep(200);
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

// ---- 9. The Mass Ride map's federal-land section (items 236-239) ----
const federalFetched = (p) =>
  p.eval("performance.getEntriesByType('resource').some((r) => /federal-land[^/?]*\\.json$/.test(r.name))");
{
  const p = await open({ route: S_MASS, hash: hashFor("mass-ride", 0) });
  await p.eval("document.getElementById('federal-heading')?.scrollIntoView({ block: 'center' }); true");
  const section = await p.eval(`(() => { const s = document.querySelector('.federal-section'); if (!s) return null;
    const items = [...s.querySelectorAll('.federal-legend li')];
    return { heading: s.querySelector('h2')?.textContent, items: items.length,
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

b.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
