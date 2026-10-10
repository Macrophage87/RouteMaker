// Rider-marked hazards on the Mass Ride map (FOLLOWUP-MASSRIDE-MAP part 3; OWNER-DECISIONS 325-327).
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import {
  HAZARD_LEGEND_NOTE,
  HAZARD_WORDS,
  HazardLegend,
  fetchHazardReports,
  fetchHazards,
  hazardForWay,
  hazardLegendText,
  hazardLines,
  hazardOnPiece,
  hazardPanelText,
  hazardProblem,
  hazardReportLine,
  hazardSaid,
  hazardsSaid,
  reviewHazard,
  sendHazard,
  type HazardCollection,
} from "./massHazards.ts";
import { HAZARD_REVIEW, STRESS_REVIEW } from "./reviewSources.ts";
import { announceRoute } from "./summary.ts";
import { descriptionText, gpxDescriptionText } from "./routeDescription.ts";
import type { MassHazardSpan, RouteResponse } from "./api.ts";
import { infoSaid, refreshedSaid, type InfoRequest, type InfoState } from "./roadInfo.ts";

const LAYER: HazardCollection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      id: 101,
      geometry: { type: "LineString", coordinates: [] },
      properties: { way: 101, level: "warning", level_name: "Warning", words: HAZARD_WORDS.warning, reason: "Doors open into the lane.", road: "Oak Street" },
    },
  ],
};

const SPANS: MassHazardSpan[] = [
  { from_m: 966, to_m: 1288, level: "warning", level_name: "Warning", words: HAZARD_WORDS.warning, reason: "Doors open into the lane.", road: "Oak Street" },
  { from_m: 3219, to_m: 3250, level: "caution", level_name: "Caution", words: HAZARD_WORDS.caution, reason: "Potholes.", road: "Elm Street" },
];

function fakeFetch(answer: { status: number; body: unknown }, seen: { url: string; init: RequestInit }[] = []) {
  return (async (url: string, init: RequestInit = {}) => {
    seen.push({ url, init });
    return new Response(JSON.stringify(answer.body), { status: answer.status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
}

test("every level is said in words, the look too, never by the rail alone", () => {
  assert.equal(hazardLegendText("caution"), "Caution: riders have had problems here; take care. Drawn as dotted black rails on both sides of the road.");
  assert.equal(hazardLegendText("warning"), "Warning: riders have had serious problems here. Drawn as dash-dot black rails on both sides of the road.");
  const html = renderToStaticMarkup(createElement(HazardLegend));
  assert.match(html, /aria-label="Rider-marked hazards"/);
  assert.match(html, /dotted black rails/);
  assert.match(html, /dash-dot black rails/);
  // The swatches are hidden from a screen reader; the words are what is read.
  assert.equal((html.match(/<svg[^>]*aria-hidden="true"/g) ?? []).length, 2);
  assert.ok(html.includes(HAZARD_LEGEND_NOTE.replace(/'/g, "&#x27;")));
});

test("the road panel finds the hazard on its way and says it with its reason", () => {
  const found = hazardForWay(LAYER, 101);
  assert.ok(found);
  assert.equal(hazardPanelText(found!), "Warning: riders have had serious problems here. Riders' reason: Doors open into the lane.");
  assert.equal(hazardSaid(found), "Rider-marked hazard: Warning.");
  assert.equal(hazardForWay(LAYER, 102), null);
  assert.equal(hazardForWay(null, 101), null);
  assert.equal(hazardSaid(null), "");
});

test("a piece marked Avoid names no hazard, even where the rest of its way has one", () => {
  assert.equal(hazardOnPiece(LAYER, { osm_way_id: 101, tier: 3 })?.level, "warning");
  assert.equal(hazardOnPiece(LAYER, { osm_way_id: 101, tier: 5 }), null, "there the map shows only Avoid");
  assert.equal(hazardOnPiece(LAYER, null), null);
});

test("hazards that come after the road's answer are said again with it, before the federal area", () => {
  const ready = { kind: "ready", info: { found: true, title: "Oak Street", tier: 3, open: true, osm_way_id: 101, distance_m: 2, sections: [], attribution: [] } } as InfoState;
  const spot: InfoRequest = { point: [-77.04, 38.91], origin: "centre" };
  const hazard = hazardSaid(hazardOnPiece(LAYER, { osm_way_id: 101, tier: 3 }));
  assert.equal(refreshedSaid(spot, spot, ready, "", hazard), `${infoSaid(ready)} Rider-marked hazard: Warning.`);
  assert.equal(refreshedSaid(spot, spot, ready, "Federal.", hazard), `${infoSaid(ready)} Rider-marked hazard: Warning. Federal.`);
});

test("the directions list the route's hazards in riding order, miles first and kilometres in brackets", () => {
  const lines = hazardLines({ mass_hazards: SPANS });
  assert.deepEqual(lines, [
    "2 rider-marked hazards on this route, in riding order:",
    "Warning on Oak Street, 0.6 to 0.8 mi (1.0 to 1.3 km): riders have had serious problems here. Riders' reason: Doors open into the lane.",
    "Caution on Elm Street, 2.0 mi (3.2 km), for 100 ft (31 m): riders have had problems here; take care. Riders' reason: Potholes.",
  ]);
  assert.deepEqual(hazardLines({ mass_hazards: [] }), []);
  assert.deepEqual(hazardLines({ mass_hazards: null }), []);
  assert.deepEqual(hazardLines({}), []);
});

test("the route's announcement names them (polite, with the route), and says nothing where there are none", () => {
  const route = {
    preset: "mass-ride",
    distance_m: 5000,
    duration_s: 1500,
    climb_m: 10,
    stress_spans: [],
    mass_hazards: SPANS,
  } as unknown as RouteResponse;
  const said = announceRoute(route, []);
  assert.match(said, /This route passes 2 rider-marked hazards: Warning on Oak Street, Caution on Elm Street\. The directions list them\./);
  assert.equal(hazardsSaid({ mass_hazards: SPANS.slice(0, 1) }), "This route passes 1 rider-marked hazard: Warning on Oak Street. The directions list it.");
  assert.equal(hazardsSaid({ mass_hazards: null }), null);
  assert.doesNotMatch(announceRoute({ ...route, mass_hazards: null } as RouteResponse, []), /hazard/);
});

test("the copied and downloaded description and the GPX carry the hazards", () => {
  const route = { preset: "mass-ride", distance_m: 5000, description: [], mass_hazards: SPANS } as unknown as RouteResponse;
  assert.match(descriptionText(route), /2 rider-marked hazards on this route, in riding order:\nWarning on Oak Street/);
  assert.match(gpxDescriptionText(route), /Caution on Elm Street/);
});

test("the layer is read from its own endpoint, and a failure draws none", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  assert.deepEqual(await fetchHazards("https://x.test", fakeFetch({ status: 200, body: LAYER }, seen)), LAYER);
  assert.equal(seen[0].url, "https://x.test/api/mass-hazards");
  assert.equal(seen[0].init.cache, undefined);
  await fetchHazards("https://x.test", fakeFetch({ status: 200, body: LAYER }, seen), true);
  assert.equal(seen[1].init.cache, "no-cache", "after an approval the browser's minute of cache is skipped");
  assert.equal(await fetchHazards("https://x.test", fakeFetch({ status: 500, body: {} })), null);
  assert.equal(await fetchHazards("https://x.test", fakeFetch({ status: 200, body: { nope: 1 } })), null);
});

test("the form checks the level and the reason first, and sends the way, the road's point, the level and the reason with the token", async () => {
  assert.deepEqual(hazardProblem(null, "x"), { field: "level", message: "Choose Caution or Warning." });
  assert.equal(hazardProblem("caution", "  ")?.field, "reason");
  assert.equal(hazardProblem("caution", "x".repeat(501))?.field, "reason");
  assert.equal(hazardProblem("warning", "x".repeat(500)), null);
  const seen: { url: string; init: RequestInit }[] = [];
  const sent = await sendHazard(
    "https://x.test",
    { osm_way_id: 101, lat: 38.91, lon: -77.04, level: "warning", reason: "Doors." },
    "tok",
    fakeFetch({ status: 200, body: { id: 1, message: "Thanks." } }, seen),
  );
  assert.deepEqual(sent, { kind: "sent", message: "Thanks." });
  assert.equal(seen[0].url, "https://x.test/api/mass-hazards");
  assert.deepEqual(JSON.parse(String(seen[0].init.body)), { osm_way_id: 101, lat: 38.91, lon: -77.04, level: "warning", reason: "Doors." });
  assert.equal((seen[0].init.headers as Record<string, string>)["X-CSRFToken"], "tok");
  const refused = await sendHazard(
    "https://x.test",
    { osm_way_id: 101, lat: 0, lon: 0, level: "caution", reason: "x" },
    null,
    fakeFetch({ status: 400, body: { error: "This road is marked Avoid already.", field: "level" } }),
  );
  assert.deepEqual(refused, { kind: "refused", status: 400, message: "This road is marked Avoid already.", field: "level" });
});

test("the admin's review lists the reports with the suggestions' three actions, at its own endpoints", async () => {
  const seen: { url: string; init: RequestInit }[] = [];
  const item = { id: 3, osm_way_id: 101, road: "Oak Street", lat: 38.899, lon: -77.029, level: "warning" as const, level_name: "Warning", words: "", reason: "r", status: "pending" as const, created_at: "", sent_at: null };
  assert.deepEqual(await fetchHazardReports("https://x.test", fakeFetch({ status: 200, body: { hazards: [item] } }, seen)), [item]);
  assert.equal(seen[0].url, "https://x.test/api/mass-hazards/open");
  for (const action of ["approve", "delete", "discord"] as const) {
    await reviewHazard("https://x.test", 3, action, "tok", fakeFetch({ status: 200, body: { message: "ok" } }, seen));
    assert.equal(seen.at(-1)!.url, `https://x.test/api/mass-hazards/3/${action}`);
  }
  assert.equal(hazardReportLine(item), "Oak Street: mark as Warning (riders have had serious problems here)");
  assert.equal(HAZARD_REVIEW.line(item), hazardReportLine(item));
  assert.equal(HAZARD_REVIEW.stress, false);
  assert.equal(STRESS_REVIEW.stress, true);
  assert.notEqual(HAZARD_REVIEW.heading, STRESS_REVIEW.heading);
});
