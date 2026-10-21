// The owner, 2026-10-19: "Include an elevation profile of the trail if possible." The road panel's elevation
// part for a tapped mountain-bike trail: the request, the words, and what each state shows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TrailProfileBody, fetchTrailProfile, trailProfileSummary, trailProfileUrl, TRAIL_PROFILE_ERROR, type TrailProfile } from "./trailProfile.ts";
import { layersTurnedOn, rideTypeLayers } from "./presets.ts";

const PROFILE: TrailProfile = {
  way: 42,
  length_m: 960,
  gain_m: 36.6,
  loss_m: 24.4,
  max_grade_pct: 14,
  interval_m: 30,
  m: [0, 30, 60],
  elevation_m: [50, 52, null],
  grade_pct: [null, 6.7, null],
};

const answer = (status: number, body: unknown) => async () => ({ ok: status < 400, status, json: async () => body });

test("the profile is asked for by the trail's way", () => {
  assert.equal(trailProfileUrl(42), "/api/trails/42/profile");
});

test("an answer is ready, none or an error", async () => {
  assert.deepEqual(await fetchTrailProfile(42, undefined, answer(200, PROFILE)), { kind: "ready", profile: PROFILE });
  assert.deepEqual(await fetchTrailProfile(42, undefined, answer(404, { error: "x" })), { kind: "none" });
  assert.deepEqual(await fetchTrailProfile(42, undefined, answer(503, {})), { kind: "error" });
  assert.deepEqual(await fetchTrailProfile(42, undefined, answer(200, { ...PROFILE, elevation_m: [null, null, null] })), { kind: "error" });
});

test("the words: length, up, down and the steepest grade, US units first", () => {
  assert.equal(trailProfileSummary(PROFILE), "This section: 0.6 mi (1.0 km), up 120 ft (37 m), down 80 ft (24 m), steepest 14%.");
  assert.doesNotMatch(trailProfileSummary({ ...PROFILE, max_grade_pct: null }), /steepest/);
});

test("ready draws the chart named by its words; none shows nothing; an error says so", () => {
  const ready = renderToStaticMarkup(createElement(TrailProfileBody, { state: { kind: "ready", profile: PROFILE }, uid: "t1" }));
  assert.match(ready, /role="img"/);
  assert.match(ready, /aria-label="This section: 0.6 mi/);
  assert.equal(renderToStaticMarkup(createElement(TrailProfileBody, { state: { kind: "none" }, uid: "t1" })), "");
  assert.match(renderToStaticMarkup(createElement(TrailProfileBody, { state: { kind: "error" }, uid: "t1" })), new RegExp(TRAIL_PROFILE_ERROR));
});

// The owner, 2026-10-19: "When gravel or mtb are selected, show the trails and topo automatically" and
// "likewise do topo and climbs for mountain goat."
test("Gravel and Mountain Bike bring the trails and contours, Mountain Goat the contours and climbs", () => {
  assert.deepEqual(rideTypeLayers("gravel"), { mtb: true, topo: true, climbs: false });
  assert.deepEqual(rideTypeLayers("mountain-bike"), { mtb: true, topo: true, climbs: false });
  assert.deepEqual(rideTypeLayers("mountain-goat"), { mtb: false, topo: true, climbs: true });
  assert.deepEqual(rideTypeLayers("default"), { mtb: false, topo: false, climbs: false });
  // Only what the new ride type brings and the old one did not, so a layer the rider turned off stays off
  // between Gravel and Mountain Bike.
  assert.deepEqual(layersTurnedOn("default", "gravel"), { mtb: true, topo: true, climbs: false });
  assert.deepEqual(layersTurnedOn("gravel", "mountain-bike"), { mtb: false, topo: false, climbs: false });
  assert.deepEqual(layersTurnedOn("mountain-bike", "mountain-goat"), { mtb: false, topo: false, climbs: true });
});

test("a trail's chart says which way it runs where the answer has its ends (the owner, 2026-10-20)", () => {
  const html = renderToStaticMarkup(
    createElement(TrailProfileBody, { state: { kind: "ready", profile: { ...PROFILE, start: [-77.0, 38.91], end: [-77.0, 38.9] } }, uid: "t1" }),
  );
  assert.match(html, /Runs north to south\./);
  assert.match(html, /<tspan class="pc-compass">N <\/tspan>/);
  // An older answer, without them: no letters, as before.
  assert.doesNotMatch(renderToStaticMarkup(createElement(TrailProfileBody, { state: { kind: "ready", profile: PROFILE }, uid: "t1" })), /pc-compass/);
});
