/** Novice and Nervous's transit offer (v0.7.0): where only a busy road connects. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { NOVICE_TRANSIT_CHOICES, busiestSaid, noviceOfferText, noviceTransitSaid } from "./noviceOffer.ts";
import { dialFields, fitDials, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";

const note = { busy_m: 640, busiest: { name: "16th Street Northwest", metres: 640, level: 3 }, over_ceiling: true, transit: true };

test("the offer names the busy road, US units first, and only on Novice and Nervous", () => {
  assert.equal(
    noviceOfferText({ novice: note }, "novice"),
    "Only a busy road connects here: 16th Street Northwest (LTS 3) for 0.4 mi (0.6 km). Transit or bikeshare can carry you past it.",
  );
  assert.equal(noviceOfferText({ novice: { ...note, transit: false } }, "novice"), null);
  assert.equal(noviceOfferText({ novice: null }, "novice"), null);
  assert.equal(noviceOfferText({ novice: note }, "default"), null);
  assert.equal(busiestSaid({ ...note, busiest: { name: null, metres: 640, level: 5 } }), "a busy road (Avoid) for 0.4 mi (0.6 km)");
  assert.equal(busiestSaid({ ...note, busiest: null }), "busy roads for 0.4 mi (0.6 km)");
  assert.deepEqual(NOVICE_TRANSIT_CHOICES.map((c) => c.preset), ["bike-transit", "bikeshare-transit"]);
  assert.match(noviceTransitSaid("Own bike + transit"), /^Own bike \+ transit, with the bike legs planned for a novice rider\./);
});

test("the transit ride types carry the novice legs in the request and the link; others never do", () => {
  const dials = fitDials("bike-transit", { ...startDials("bike-transit"), noviceLegs: true });
  assert.equal(dials.noviceLegs, true);
  assert.equal(dialFields(dials).novice_legs, true);
  assert.equal(fitDials("default", { ...startDials("default"), noviceLegs: true }).noviceLegs, undefined);
  assert.equal("novice_legs" in dialFields(startDials("bike-transit")), false);
  const hash = encodePlan([[-77.0, 38.9], [-77.1, 38.9]], "bikeshare-transit", fitDials("bikeshare-transit", { noviceLegs: true }));
  assert.match(hash, /novice=1/);
  assert.equal(decodePlan(hash).dials.noviceLegs, true);
});

test("the route summary shows the offer with the warnings, in Go and in Plan", () => {
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /<NoviceTransitOffer route=\{route\} preset=\{preset\} onTake=\{go\.onNoviceTransit\} \/>/);
  assert.match(panel, /role="group" aria-labelledby=\{id\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /choosePreset\(id, \{ \.\.\.chooseRideType\(id, null, dials\), noviceLegs: true \}\);/);
});
