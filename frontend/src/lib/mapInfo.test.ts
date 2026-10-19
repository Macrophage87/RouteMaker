// The map's info panel (Stephen 2026-10-19): Plan's how-to and the documentation's short version, behind the "i".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DOCS_LINKS, INFO_POINTS, MAP_INFO } from "./mapInfo.ts";
import { MAP_ATTRIBUTION } from "./mapStyle.ts";
import { searchLede } from "./sidebar.ts";

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the info panel leads with Plan's how-to, the accessibility mode pointer included", () => {
  assert.ok(MAP_INFO.startsWith(`<div class="map-info"><p><strong>Plan a route.</strong> ${searchLede(false)}</p>`));
  assert.match(MAP_INFO, /turn on accessibility mode \(the first button on the page, or in Settings\)/);
});

test("then the documentation's short version, one line each, and a link to each page", () => {
  assert.equal(INFO_POINTS.length, 4);
  for (const point of INFO_POINTS) assert.ok(MAP_INFO.includes(`<li>${point}</li>`), point);
  assert.deepEqual(DOCS_LINKS.map((l) => l.href), ["/about/how-it-works.html", "/about/ride-types.html", "/about/stress.html", "/about/architecture.html"]);
  for (const link of DOCS_LINKS) assert.ok(MAP_INFO.includes(`<a href="${link.href}">${link.text}</a>`), link.href);
});

test("only markup MapLibre's sanitizer keeps: no handlers, no styles", () => {
  const tags = [...MAP_INFO.matchAll(/<([a-z]+)/g)].map((m) => m[1]);
  assert.ok(tags.every((t) => ["div", "p", "strong", "ul", "li", "a"].includes(t)), tags.join());
  assert.doesNotMatch(MAP_INFO, /\son[a-z]+=|style=/);
});

test("the map shows it before the credits, in one entry, behind an i named for it", () => {
  const view = src("../MapView.tsx");
  assert.match(view, /customAttribution: MAP_INFO \+ MAP_ATTRIBUTION/);
  assert.match(view, /"AttributionControl\.ToggleAttribution": "Map info and credits"/);
  // A documentation link keeps the plan for the page's "Back to the map", as StressPageLink does.
  assert.match(view, /a\[href\^="\/about\/"\][\s\S]{0,120}rememberPlanForPage\(tabSession\(\), window\.location\.hash\)/);
  assert.ok((MAP_INFO + MAP_ATTRIBUTION).includes(MAP_ATTRIBUTION));
});

test("Plan shows the how-to only in accessibility mode; otherwise a screen reader still hears it there", () => {
  assert.match(src("../app/Planner.tsx"), /<p className=\{accessMode \? "hint" : "visually-hidden"\}>\{searchLede\(loopVias, accessMode\)\}<\/p>/);
});
