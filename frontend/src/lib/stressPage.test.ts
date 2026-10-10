// The rider-facing page on how traffic-stress ratings work (OWNER-DECISIONS 461): a static page in
// public/, served by both edges at STRESS_PAGE. Its structure is held here; the browser a11y suite
// (scripts/a11y/check.mjs) checks it at 320 px.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { STRESS_PAGE } from "./stressLegend.ts";

// The road panel's words for each level (src/core/segment_info.py, TIER_WORDS; OWNER-DECISIONS 441l).
const PANEL_WORDS = [
  "Comfortable for everyone",
  "Fine for adults",
  "For experienced cyclists",
  "High stress: busy, fast traffic",
  "Avoid",
];

const page = readFileSync(new URL(`../../public${STRESS_PAGE}`, import.meta.url), "utf8");
const text = page.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

test("the page is a whole document in English, with a title and a viewport", () => {
  assert.match(page, /^<!doctype html>\n<html lang="en">/);
  assert.match(page, /<title>[^<]+<\/title>/);
  assert.match(page, /<meta name="viewport" content="width=device-width, initial-scale=1">/);
});

// The one link off the site: the full sources page on GitHub (the owner, r4). Following a link
// is a navigation, which the content security policy does not govern; nothing is loaded from it.
const LITERATURE_URL = "https://github.com/Macrophage87/RouteMaker/blob/main/docs/stress/literature.md";

test("it runs no script and loads nothing from another host (the app's content security policy)", () => {
  assert.doesNotMatch(page, /<script/i);
  assert.doesNotMatch(page, /\bsrc="(https?:)?\/\//i);
  assert.doesNotMatch(page, /@import|url\(/i);
  const external = [...page.matchAll(/\bhref="((?:https?:)?\/\/[^"]*)"/gi)].map((m) => m[1]);
  assert.deepEqual(external, [LITERATURE_URL], "exactly one external href, the sources page on GitHub");
});

test("the GitHub link opens in the same tab and says where it goes, not the bare address", () => {
  const links = [...page.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].filter((m) => m[1].includes(LITERATURE_URL));
  assert.equal(links.length, 1);
  const [, attrs, inner] = links[0];
  assert.equal(attrs.trim(), `href="${LITERATURE_URL}"`, "an <a> with only its href: no target, no title");
  const name = inner.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  assert.equal(name, "Traffic stress: our sources and where we differ (on GitHub)");
  assert.doesNotMatch(name, /https?:|github\.com|\.md\b/i, "the name is words, not a URL or a file path");
});

test("one h1, and no heading skips a level", () => {
  const levels = [...page.matchAll(/<h([1-6])[\s>]/g)].map((m) => Number(m[1]));
  assert.equal(levels.filter((l) => l === 1).length, 1);
  assert.equal(levels[0], 1);
  for (let i = 1; i < levels.length; i++) assert.ok(levels[i] <= levels[i - 1] + 1, `h${levels[i - 1]} then h${levels[i]}`);
});

test("it has the landmarks a screen reader moves by, and a skip link to the content", () => {
  for (const tag of ["header", "nav", "main", "footer"]) assert.match(page, new RegExp(`<${tag}[\\s>]`), tag);
  assert.match(page, /<a class="skip" href="#main">/);
  assert.match(page, /<main id="main">/);
  for (const [, id] of page.matchAll(/href="#([^"]+)"/g)) assert.match(page, new RegExp(`id="${id}"`), `#${id}`);
});

// Each level's map colors in words, pinned verbatim (the mutation re-check's N6b).
const MAP_WORDS = [
  "On the map: a thin, solid light green line with a dark green edge.",
  "On the map: long green dashes with a dark blue edge.",
  "On the map: short yellow dashes on orange, with a black edge.",
  "On the map: very long orange dashes on red, with a black edge, in a wider line.",
  "On the map: red dashes and dots on black, the widest line.",
];

test("every swatch is hidden from a screen reader, and each level is named in the road panel's words beside it", () => {
  const swatches = [...page.matchAll(/<svg[^>]*>/g)].map((m) => m[0]);
  assert.equal(swatches.length, 5);
  for (const svg of swatches) assert.match(svg, /aria-hidden="true"/);
  for (const words of PANEL_WORDS) assert.ok(text.includes(words), words);
});

test("each level is said whole, with a stop after its name, the legend's words marked, and its map color in words", () => {
  const items = [...page.matchAll(/<li>\s*<svg[\s\S]*?<\/svg>\s*<span>([\s\S]*?)<\/span>\s*<\/li>/g)].map((m) => m[1]);
  assert.equal(items.length, 5);
  items.forEach((item, i) => {
    const name = item.match(/^<strong>([^<]+)<\/strong> /)?.[1] ?? "";
    assert.ok(name.endsWith(`${PANEL_WORDS[i]}.`), name);
    assert.match(item, /<\/strong> Map legend: "/, "the legend's words are labelled as such");
    // The accessibility review's SF2: the color of each swatch in words, for a pilot's "the orange one".
    assert.ok(item.endsWith(MAP_WORDS[i]), `${i}: ${item}`);
    assert.match(item, /On the map: [^.]*\b(green|blue|yellow|orange|red|black)\b[^.]*\.$/, item);
  });
  assert.match(text, /The High contrast switch/, "the control's own label (accessibilitySwitch.ts)");
  assert.doesNotMatch(text, /accessibility switch/i, "Accessibility mode (455) does not change the colors");
});

test("closed ways: rated singletrack everywhere, other mountain-bike trails open on Gravel and Mountain Goat (presets.OFFROAD_PRESETS)", () => {
  assert.match(text, /rated mountain-bike singletrack/);
  assert.match(text, /Other natural-surface mountain-bike trails are closed on most ride types\. They are open on Gravel and Mountain Goat\./);
  assert.doesNotMatch(text, /mountain-bike-only trails/);
});

test("the cost table: one short-named region, a short caption, and LTS 1 and 2 said once above it", () => {
  assert.doesNotMatch(page, /<section [^>]*aria-labelledby/, "plain sections: the h2s give the headings, not 10 more regions");
  const regions = [...page.matchAll(/<div [^>]*role="region"[^>]*>/g)].map((m) => m[0]);
  assert.deepEqual(regions, ['<div class="table-wrap" tabindex="0" role="region" aria-label="Cost table, scrolls sideways">']);
  assert.match(page, /<caption>Calm miles per mile, at each ride type's starting slider<\/caption>/);
  assert.match(text, /Their level adds nothing at LTS 1 or 2\. A quiet street counts as 1\./);
  assert.match(text, /Traffic-free paths and protected bike lanes count for less, and painted bike lanes a little less \(except on Mass Ride\)/);
  assert.doesNotMatch(text, /always count as about 1/);
  // The LTS 4 hold is one combined figure against the router's first route (the spec re-check's R2).
  assert.match(text, /more LTS 4, Avoid and very high stress crossings, counted together, than the router's own first route/);
  assert.doesNotMatch(page, /<th scope="col">LTS 1 and 2<\/th>/);
});

test("it says where it differs from the literature, and links the full list", () => {
  assert.match(page, /<h2 id="why-differ">Why our ratings differ from the studies<\/h2>/);
  assert.match(page, /<li><a href="#why-differ">Why our ratings differ from the studies<\/a><\/li>/);
  // The accessibility re-check's SF1: one heading starting "Sources", not two.
  const h2s = [...page.matchAll(/<h2[^>]*>([^<]+)<\/h2>/g)].map((m) => m[1]);
  assert.equal(h2s.filter((h) => /^Sources/.test(h)).length, 1, h2s.join(" | "));
  assert.doesNotMatch(page, /<code>docs\/stress\/literature\.md<\/code>/);
  assert.match(text, /We add an Avoid level/);
  // The rush-hour change is built (OWNER-DECISIONS 468a, 469c-469e), so it is no longer "planned".
  assert.match(text, /We also chose the size of the rush-hour change ourselves, because the one study behind it is small\./);
  assert.doesNotMatch(text, /planned rush-hour|planned crossing costs/);
});

test("the sources list: one list under Sources, one item for each source, plain text titles", () => {
  const section = page.match(/<h2 id="sources">Sources<\/h2>\s*<ul>([\s\S]*?)<\/ul>/)?.[1] ?? "";
  assert.ok(section, "a list straight under the Sources heading");
  assert.equal((page.match(/<h2 id="sources">/g) ?? []).length, 1);
  assert.doesNotMatch(section, /<a\b/, "titles are plain text: the page's one external link is the GitHub one");
  const items = [...section.matchAll(/<li>([\s\S]*?)<\/li>/g)].map((m) => m[1].replace(/\s+/g, " "));
  for (const source of [
    /^The method: Mekuria, Furth and Nixon, "Low-Stress Bicycling and Network Connectivity", Mineta Transportation Institute Report 11-19 \(2012\)\.$/,
    /^Later versions of the method: Peter Furth, Level of Traffic Stress criteria, version 2\.0 \(2017\) and version 2\.2 \(2022\)\.$/,
    /Oregon Department of Transportation, Analysis Procedures Manual, version 2, chapter 14\./,
    /Montgomery County Planning Department, Bicycle Master Plan, Appendix D/,
    /^Route choice in Portland: Broach, Dill and Gliebe, "Where do cyclists ride\?/,
    /^Route choice in Eugene: Zimmermann, Mai and Frejinger, /,
    /^Turns in Copenhagen: Skov-Petersen, Barkow, Lundhede and Jacobsen, /,
    /^Stress at rush hour: Caviedes and Figliozzi, /,
  ]) {
    assert.equal(items.filter((i) => source.test(i)).length, 1, String(source));
  }
});

test("the Census credit names the dataset (docs/SOURCES.md: TIGER/Line 2024, 2020 Urban Areas)", () => {
  assert.match(text, /Urban areas, for default speeds: U\.S\. Census Bureau, TIGER\/Line Shapefiles \(2024\), 2020 Urban Areas\./);
  assert.doesNotMatch(page, /<abbr/);
});

test("US units first, metric in brackets", () => {
  assert.match(text, /1 mile \[1\.6 km\]/);
  // Junction costs are in calm miles first, then [km; ft] (OWNER-DECISIONS 467; option C, 468).
  assert.match(text, /0\.30 calm miles \[0\.49 km; 1,600 ft\]/);
  assert.doesNotMatch(text, /\b\d+ (m|km)\b(?![^[]*\])/, "a metric figure outside brackets");
  // And every US figure has its metric (the accessibility review's N6): "20 mph" alone fails.
  // Junction costs in calm miles count too (a rate, "calm miles per mile", has no metric).
  const figures = [
    ...text.matchAll(/\b\d[\d,.]*(?: to \d[\d,.]*)? (?:extra )?(?:mph|feet|miles?)\b(.{0,2})/g),
    ...text.matchAll(/\b\d[\d,.]*(?: to \d[\d,.]*)? calm miles\b(?! per)(.{0,2})/g),
  ];
  assert.ok(figures.length >= 8, String(figures.length));
  for (const m of figures) assert.equal(m[1], " [", `metric missing after "${m[0]}"`);
});

test("US spelling, as the app's own text", () => {
  assert.doesNotMatch(text, /colour|neighbour|behaviour|centre|metre/i);
});

test("the sources are credited in text", () => {
  for (const credit of [
    "OpenStreetMap contributors",
    "DC Open Data",
    "VDOT",
    "Montgomery County Planning Department",
    "Open Baltimore",
    "U.S. Census Bureau",
    "Furth",
    "Broach, Dill and Gliebe",
    "Eugene",
    "RouteMaker Mass Ride model",
  ]) {
    assert.ok(text.includes(credit), credit);
  }
});

// Half steps are not built, so the page gives them as planned. The crossing costs and their time
// bands (OWNER-DECISIONS 467, 468, 468a, 469c-469e) are built, so they are described under Junction
// warnings in the present tense and are no longer in the planned section.
test("what is not built is marked planned", () => {
  assert.match(page, /<h2 id="planned">Half steps \(planned\)<\/h2>/);
  assert.match(text, /Planned, not built yet\./);
  assert.match(page, /<h3>Half steps<\/h3>/);
  assert.doesNotMatch(page, /<h3>Crossing costs<\/h3>/);
  const junctions = page.match(/<h2 id="junctions">[\s\S]*?<\/section>/)?.[0].replace(/\s+/g, " ") ?? "";
  assert.match(junctions, /count for more at weekday rush hours \(7 to 10 AM and 4 to 7 PM\), a little less on weekend days, and less again at night \(9 PM to 7 AM, every day\)/);
  assert.doesNotMatch(junctions, /[Pp]lanned|will cost/);
  assert.doesNotMatch(text, /proposed but not yet confirmed|proposed rush-hour/);
  assert.doesNotMatch(text, /Its details are still to be confirmed|single setting/);
});

// The rolling stress chart is built (PR #34; OWNER-DECISIONS 460.12, 461d, 461e): the page says so,
// outside the planned section, and no longer calls it planned.
test("the stress chart is described as built, not planned", () => {
  assert.match(page, /<li><a href="#stress-chart">The stress chart<\/a><\/li>/);
  assert.match(page, /<h2 id="stress-chart">The stress chart<\/h2>/);
  const chart = page.match(/<h2 id="stress-chart">[\s\S]*?<\/section>/)?.[0] ?? "";
  assert.doesNotMatch(chart, /[Pp]lanned|will show/, "the built chart is in the present tense");
  assert.match(chart, /calm miles per mile/);
  assert.match(chart, /1 mile \[1\.6 km\]|mile \[1\.6 km\]/, "US units first, metric in brackets");
  assert.match(chart, /except Mass Ride/);
  assert.match(chart, /an estimate/);
  assert.doesNotMatch(text, /stress chart \(planned\)|A stress number and a rolling stress chart/);
});

// The page names the app's own controls (accessibility review r5, SF2): the chart's slider and the
// tables' disclosure. Both names are read from the app's source too, so a rename there breaks this
// test rather than leaving a blind rider looking for a control that is no longer called that.
test("the stress chart's control names on the page are the app's own", () => {
  const chart = (page.match(/<h2 id="stress-chart">[\s\S]*?<\/section>/)?.[0] ?? "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  const app = readFileSync(new URL("../ElevationChart.tsx", import.meta.url), "utf8");
  for (const name of ["Elevation and rolling stress along the route", "Climbs and rolling stress as tables"]) {
    assert.ok(chart.includes(`"${name}"`), `the page quotes "${name}"`);
    assert.ok(app.includes(`"${name}"`), `ElevationChart.tsx still uses "${name}"`);
  }
  assert.match(chart, /slider named "Elevation and rolling stress along the route"/);
  assert.match(chart, /Tab to it and use the arrow keys/);
  assert.match(chart, /every half mile \[0\.8 km\]/);
  assert.doesNotMatch(chart, /the road,/, "the slider reads the stretch's stress, not a road name");
});
