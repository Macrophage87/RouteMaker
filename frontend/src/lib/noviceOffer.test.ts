/** Novice and Nervous's transit offer (v0.7.0): where only a busy road connects. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  NOVICE_TRANSIT_CHOICES,
  busiestSaid,
  noviceOfferShown,
  noviceOfferText,
  noviceTransitDials,
  noviceTransitSaid,
  noviceTripLine,
  noviceTripShort,
  noviceTripOf,
  noviceTripPoints,
} from "./noviceOffer.ts";
import type { RouteResponse } from "./api.ts";
import { dialFields, fitDials, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";

const note = { busy_m: 640, busiest: { name: "16th Street Northwest", metres: 640, level: 3 }, over_ceiling: true, transit: true };

test("the offer names the busy road, US units first, and only on Novice and Nervous", () => {
  // Review F7: one short lead line; the road is named in each option's description (noviceTripLine, below).
  assert.equal(noviceOfferText({ novice: note }, "novice"), "Busy road ahead: transit can skip it.");
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

test("each option's one line: its time door to door and the busy stretch it avoids, or the long way round", () => {
  const avoid = "avoiding 16th Street Northwest (LTS 3) for 0.4 mi (0.6 km)";
  assert.equal(noviceTripLine({ kind: "found", minutes: 34 }, note), `About 34 min door to door, ${avoid}.`);
  assert.equal(noviceTripLine({ kind: "finding" }, note), `Finding a trip, ${avoid}.`);
  assert.equal(noviceTripLine(undefined, note), `Finding a trip, ${avoid}.`);
  assert.equal(noviceTripLine({ kind: "none" }, note), "No trip found just now; it would avoid 16th Street Northwest (LTS 3) for 0.4 mi (0.6 km).");
  // Over the 1.4 times cap with no busy road: the reason is the long way round, said as such.
  const capped = { busy_m: 0, busiest: null, over_ceiling: true, transit: true };
  assert.equal(noviceTripLine({ kind: "found", minutes: 20 }, capped), "About 20 min door to door, avoiding the long way round a calm route takes here.");
  // Review F7: the cap's lead is one short line too.
  assert.equal(noviceOfferText({ novice: capped }, "novice"), "Calm route is long here: transit can shorten it.");
  assert.equal(noviceTripShort({ kind: "found", minutes: 34 }), "About 34 min");
  assert.equal(noviceTripShort(undefined), "Finding…");
  assert.equal(noviceTripShort({ kind: "none" }), "None now");
});

test("the trips are asked start to end, on each transit ride type with its novice legs, and read for their minutes", () => {
  assert.deepEqual(noviceTripPoints(["a", "b", "c"]), ["a", "c"]);
  assert.equal(noviceTransitDials("bikeshare-transit").noviceLegs, true);
  assert.deepEqual(noviceTripOf({ ok: true, route: { transit: { minutes: 41 } } as unknown as RouteResponse }), { kind: "found", minutes: 41 });
  assert.deepEqual(noviceTripOf({ ok: true, route: { transit: null } as unknown as RouteResponse }), { kind: "none" });
  assert.deepEqual(noviceTripOf({ ok: false }), { kind: "none" });
  assert.equal(noviceOfferShown({ novice: note }, "novice"), true);
  assert.equal(noviceOfferShown({ novice: note }, "bike-transit"), false);
});

test("the route summary shows the offer with the warnings, in Go and in Plan, the trips found unasked", () => {
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /<NoviceTransitOffer route=\{route\} preset=\{preset\} onTake=\{go\.onNoviceTransit\} trips=\{go\.noviceTrips\} \/>/);
  assert.match(panel, /role="group" aria-labelledby=\{id\}/);
  // Each button is described by its one line.
  assert.match(panel, /aria-describedby=\{`\$\{id\}-\$\{choice\.preset\}`\}/);
  assert.match(panel, /\{noviceTripLine\(trips\?\.\[choice\.preset\], note\)\}/);
  // Review F7: the line is the description, out of sight; the short time is shown, hidden from a screen reader.
  assert.match(panel, /<span id=\{`\$\{id\}-\$\{choice\.preset\}`\} className="visually-hidden">\s*\{noviceTripLine/);
  assert.match(panel, /<span className="novice-trip-note" aria-hidden="true">\s*\{noviceTripShort\(trips\?\.\[choice\.preset\]\)\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /choosePreset\(id, \{ \.\.\.chooseRideType\(id, null, dials\), noviceLegs: true \}\);/);
  // Found as the offer shows, without a press: both ride types, keyed on the routed points.
  assert.match(app, /const noviceKey = noviceOfferShown\(shown, preset\) \? JSON\.stringify\(routedPoints\) : null;/);
  assert.match(app, /requestRoute\(ends, choice\.preset, \{ dials: noviceTransitDials\(choice\.preset\) \}\)/);
  assert.match(app, /noviceTrips: noviceTripsShown,/);
});
