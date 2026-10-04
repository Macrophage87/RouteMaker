// The fixes of the combined accessibility review of integrate-2 (FIX-A11Y;
// OWNER-DECISIONS 220: blind stokers are a real audience), as far as they can be
// held without a browser: the stylesheet's rules, measured against the base
// map's own colours, and the wiring in the components. The behaviour in a
// browser is scripts/a11y/check.mjs's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LIGHT } from "@protomaps/basemaps";
import { contrastRatio } from "./stressStyle.js";
import { ROUTE_BLUE } from "./lib/routeColours.ts";
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";

const read = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
const css = read("./styles.css");
const mapView = read("./MapView.tsx");
const app = read("./App.tsx");
const dialsPanel = read("./DialsPanel.tsx");
const list = read("./IntersectionList.tsx");

/** The body of the first `@media (query) { ... }`, by matching braces. */
function mediaBody(source: string, query: string): string {
  const start = source.indexOf(`@media ${query}`);
  assert.ok(start >= 0, query);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, i);
    }
  }
  throw new Error(`unclosed ${query}`);
}

function rules(body: string): Array<{ selectors: string[]; declarations: string }> {
  return [...body.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim()).filter(Boolean),
    declarations: m[2],
  }));
}

const forced = mediaBody(css, "(forced-colors: active)");
const outside = rules(css.replace(forced, ""));
const declared = (selector: string) =>
  outside.filter((r) => r.selectors.includes(selector)).map((r) => r.declarations).join(";");
const rootRule = outside.find((r) => r.selectors.length === 1 && r.selectors[0] === ":root");
const custom = (name: string): string => {
  const m = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(rootRule?.declarations ?? "");
  assert.ok(m, name);
  return m[1].toLowerCase();
};

// 1.4.11: the base map is the light flavour in both themes, so the ring on it is one ring.
const MAP_FILLS = Object.entries(LIGHT as unknown as Record<string, unknown>)
  .filter((entry): entry is [string, string] => typeof entry[1] === "string" && /^#[0-9a-f]{6}$/i.test(entry[1]))
  .filter(([key]) => !/label/.test(key));

test("the map's focus ring is dark, with a white ring inside, and 3:1 or more against every fill of the base map", () => {
  const ring = custom("--map-focus");
  const inner = custom("--map-focus-inner");
  assert.ok(MAP_FILLS.length > 30, "the premise: the light flavour's fills");
  for (const [key, fill] of MAP_FILLS) {
    assert.ok(contrastRatio(ring, fill) >= 3, `${ring} on ${key} ${fill}: ${contrastRatio(ring, fill).toFixed(2)}`);
  }
  // The earth, where most markers sit: the review measured amber at 1.26:1.
  assert.ok(contrastRatio(ring, LIGHT.earth) >= 10);
  // The white inner ring is what shows against the dark things on the map.
  for (const dark of [ROUTE_BLUE, SEVERITY_COLOURS.red.fill, SEVERITY_COLOURS.red.stroke, ring]) {
    assert.ok(contrastRatio(inner, dark) >= 3, `${inner} on ${dark}`);
  }
});

test("the ring is the same in both themes: the dark theme does not redefine it, and nothing on the map uses --focus", () => {
  const dark = mediaBody(css, "(prefers-color-scheme: dark)");
  assert.doesNotMatch(dark, /--map-focus/);
  const on = [
    ".junction-marker:focus-visible",
    ".maplibregl-marker:focus-visible",
    ".maplibregl-ctrl button:focus-visible",
    ".maplibregl-ctrl-group button:focus:focus-visible",
    ".maplibregl-ctrl-attrib a:focus-visible",
    ".maplibregl-ctrl-attrib-button:focus-visible",
  ];
  for (const selector of on) {
    const body = declared(selector);
    assert.match(body, /outline:\s*3px solid var\(--map-focus\)/, selector);
    assert.match(body, /outline-offset:\s*2px/, selector);
    assert.match(body, /box-shadow:\s*0 0 0 2px var\(--map-focus-inner\)/, `${selector}: the white ring fills the offset`);
    assert.doesNotMatch(body, /--focus\b/, selector);
  }
  // The canvas's ring is inside it, dark on the light map (amber was about 1.3:1).
  assert.match(declared(".maplibregl-canvas:focus-visible"), /outline:\s*3px solid var\(--map-focus\)/);
});

test("a focused or hovered junction marker is drawn over one it overlaps", () => {
  assert.match(declared(".junction-marker:focus"), /z-index:\s*[1-9]/);
  assert.match(declared(".junction-marker:hover"), /z-index:\s*[1-9]/);
});

test("a junction row puts its reason on a line of its own, so it wraps at 320 px", () => {
  // minmax(0, ...) and no nowrap: with wider text spacing the severity and the
  // distance wrap inside the row too (a11y re-check of 2b0cf00, 1.4.12).
  assert.match(declared(".junction-item"), /grid-template-columns:\s*18px minmax\(0, auto\) minmax\(0, 1fr\)/);
  assert.match(declared(".junction-severity"), /white-space:\s*normal/);
  assert.match(declared(".junction-where"), /white-space:\s*normal/);
  assert.match(declared(".junction-reason"), /grid-column:\s*2 \/ -1/);
  assert.match(declared(".junction-reason"), /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(declared(".junction-reason"), /nowrap/);
});

test("the credits: the OpenStreetMap credit shows beside the collapsed i, and opened on a phone they scroll", () => {
  const collapsed = declared(".maplibregl-ctrl-attrib.maplibregl-compact:not(.maplibregl-compact-show)::before");
  assert.match(collapsed, /content:\s*"© OpenStreetMap"/);
  const phone = mediaBody(css, "(max-width: 720px)");
  const open = rules(phone).find((r) => r.selectors.includes(".maplibregl-ctrl-attrib.maplibregl-compact-show .maplibregl-ctrl-attrib-inner"));
  assert.ok(open, "a rule for the opened credits on a phone");
  assert.match(open.declarations, /max-height:/);
  assert.match(open.declarations, /overflow-y:\s*auto/);
});

test("the skip link is off screen until it has the focus", () => {
  assert.match(declared(".skip-link"), /transform:\s*translateY\(-200%\)/);
  assert.match(declared(".skip-link:focus"), /transform:\s*none/);
});

test("MapView: the credits start collapsed on a narrow map, below the scales", () => {
  assert.match(mapView, /attributionControl:\s*false/);
  const credits = mapView.indexOf("new maplibregl.AttributionControl({ compact: true");
  const scale = mapView.indexOf("new maplibregl.ScaleControl");
  assert.ok(credits > 0 && scale > credits, "added before the scales, so it is the bottom of the stack");
  assert.match(mapView, /collapseCredits\(container\.current\.querySelector\("\.maplibregl-ctrl-attrib"\)/);
});

test("MapView: the junction card is a named dialog, takes the focus only from a marker, and Escape closes it", () => {
  assert.match(mapView, /focusAfterOpen:\s*false/);
  assert.match(mapView, /setAttribute\("role", "dialog"\)/);
  assert.match(mapView, /setAttribute\("aria-label", cardName\(item\)\)/);
  assert.match(mapView, /setAttribute\("aria-label", CARD_CLOSE_LABEL\)/);
  assert.match(mapView, /if \(takeFocus\) close\?\.focus\(\)/);
  assert.match(mapView, /showJunctionCard\(map, item, cardTakesFocus\(opener\)\)/);
  assert.match(mapView, /openCard\(first, "marker"\)/);
  assert.match(mapView, /openCard\(found, "list"\)/);
  assert.match(mapView, /card\.on\("close"/);
  assert.match(mapView, /escapeClosesCard\(junctionCard\.current !== null/);
});

test("MapView: a group's zoom gives the focus to the first member's new marker", () => {
  assert.match(mapView, /focusAfterZoom\.current = document\.activeElement === element \? first\.index : null/);
  assert.match(mapView, /if \(wanted !== null\) markerFor\(wanted\)\?\.focus\(\)/);
  assert.match(mapView, /maxZoom: map\.getMaxZoom\(\)/);
});

test("MapView: a junction marker's name is its only text (no title read again as its description)", () => {
  const draw = mapView.slice(mapView.indexOf("const draw = () => {"), mapView.indexOf("draw();"));
  assert.ok(draw.length > 100);
  assert.doesNotMatch(draw, /\.title\s*=/);
  assert.match(draw, /dataset\.junctionIndex/);
});

test("the list rows carry their index, so a closing card can give the focus back to one", () => {
  assert.match(list, /data-junction-index=\{item\.index\}/);
  assert.match(mapView, /\.junction-item\[data-junction-index="\$\{index\}"\]/);
});

test("App: the skip link comes before the map, and the planner can take its focus", () => {
  const skip = app.indexOf('className="skip-link"');
  assert.ok(skip > 0 && skip < app.indexOf("<MapView"), "before the map in the page");
  assert.match(app, /id="route-planner"\s+tabIndex=\{-1\}/);
  assert.match(app, /skipToPlanner\(event, panelRef\.current\)/);
});

test("App: 'Planning...' is shown but not said, and the route is said once it settles, with its warnings", () => {
  const region = app.slice(app.indexOf('<div role="status" aria-live="polite" className="status-line">'));
  const end = region.indexOf("</div>");
  const live = region.slice(0, end);
  assert.doesNotMatch(live, /\{announcement\}<\/p>\}[\s\S]*status\.kind === "loading"|status\.kind === "loading" && <p className="loading">\{announcement\}/, "'Planning...' is not in the live region");
  assert.match(app, /\{status\.kind === "loading" && <p className="loading">\{announcement\}<\/p>\}\s*\{status\.kind === "loading" && <progress className="planning" aria-label="Planning the route" \/>\}\s*<div role="status"/, "shown, with a labelled progress bar, before the live region");
  // Only a slow plan is said, once (the a11y review's SF1).
  assert.match(live, /\{status\.kind === "loading" && slow && <p className="loading">\{stillPlanningSaid\(preset, dials\)\}<\/p>\}/);
  assert.match(app, /const slow = useLongerThan\(status\.kind === "loading", STILL_PLANNING_AFTER_MS\)/);
  assert.match(live, /routeSaid/);
  assert.match(app, /useSettled\(status\.kind === "ok" \? announcement : "", ANNOUNCE_SETTLE_MS\)/);
  assert.match(app, /announceRoute\(route, routedPoints, announceHow\(answer, choice, chosen\)\)/);
});

test("DialsPanel: the slider is named by its label alone, described by its note, and keys wait to rest", () => {
  assert.match(dialsPanel, /<span className="dial-now" aria-hidden="true">/);
  assert.match(dialsPanel, /aria-labelledby=\{nameId\}/);
  assert.match(dialsPanel, /aria-describedby=\{view\.note \? noteId : undefined\}/);
  assert.match(dialsPanel, /<p className="hint" id=\{noteId\}>/);
  assert.match(dialsPanel, /onKeyUp=\{\(\) => props\.onRelease\(true\)\}/);
  assert.match(dialsPanel, /onPointerUp=\{\(\) => props\.onRelease\(false\)\}/);
  assert.match(dialsPanel, /onBlur=\{\(\) => props\.onRelease\(false\)\}/);
  assert.match(dialsPanel, /if \(settle\) keys\.current\.later\(commitDraft\)/);
});

// OWNER-DECISIONS 233, 234: a Mass Ride's group of signalized crossings is a row that opens
// onto its crossings. The choice is a disclosure, not a card: a button with aria-expanded and
// aria-controls over a list, closed to begin with, the focus staying on it, nothing announced.
test("a group row is a disclosure button over a list of its crossings", () => {
  const group = list.slice(list.indexOf("function JunctionGroupRow"), list.indexOf("export function IntersectionList"));
  assert.match(group, /<button\s+type="button"/);
  assert.match(group, /aria-expanded=\{open\}/);
  assert.match(group, /aria-controls=\{listId\}/);
  assert.match(group, /id=\{listId\}/);
  assert.match(group, /useState\(false\)/, "closed to begin with");
  assert.match(group, /hidden=\{!open\}/);
  assert.doesNotMatch(group, /aria-live|role="status"|role="alert"/, "opening it announces nothing");
  assert.doesNotMatch(group, /\.focus\(\)/, "the focus stays on the button");
  assert.match(group, /aria-label="Crossings in this group, in route order"/);
});

test("a group's chevron is a shape the screen reader does not say, and its row names its severity in words", () => {
  const group = list.slice(list.indexOf("function JunctionGroupRow"), list.indexOf("export function IntersectionList"));
  assert.match(group, /<span aria-hidden="true">\{chevron\(open\)\} <\/span>/);
  assert.match(group, /group\.severityText/);
  assert.match(group, /group\.text/);
});

test("a group's members are the ordinary junction rows: they carry their index and open the ordinary card", () => {
  assert.match(list, /function JunctionButton/);
  assert.match(list, /data-junction-index=\{item\.index\}/);
  const group = list.slice(list.indexOf("function JunctionGroupRow"), list.indexOf("export function IntersectionList"));
  assert.match(group, /<JunctionButton item=\{item\} onSelect=\{onSelect\} \/>/);
});

test("a closed group's list is really hidden: [hidden] wins over the grid", () => {
  assert.match(declared(".junction-members[hidden]"), /display:\s*none/);
  assert.match(declared(".junction-members"), /display:\s*grid/);
});
