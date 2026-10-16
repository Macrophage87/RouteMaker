import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { requestRoute, type TransitDeparture } from "./api.ts";
import {
  CLOSE_S,
  MILESTONES_S,
  clockOf,
  countdown,
  departureText,
  labelSide,
  mapLabel,
  milestone,
  milestoneSaid,
  missedSaid,
  mmss,
  noteArrived,
} from "./departure.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

// The shape POST /api/route gives an infrequent departure (core.transit.departure): planned at
// 7:00 am, arriving at Union Station 7:36, the 7:42 MARC, 6 min spare, the next at 8:15.
const DEPARTURE: TransitDeparture = {
  step: 2,
  system: "MARC",
  vehicle: "the MARC Penn Line",
  board_at: "Union Station",
  departs: "7:42 am",
  departs_at: "2026-10-13T07:42:00-04:00",
  arrive_at: "2026-10-13T07:36:00-04:00",
  next: "8:15 am",
  next_at: "2026-10-13T08:15:00-04:00",
  spare_s: 360,
  close: false,
  planned_at: "2026-10-13T07:00:00-04:00",
  point: [-77.0063, 38.8973],
  label: "MARC 7:42 am scheduled · 6 min spare",
  source: "scheduled",
};
const at = (clock: string) => Date.parse(`2026-10-13T${clock}-04:00`);

test("the departure is said plainly: which, when, from where, when you arrive, and the one after", () => {
  assert.equal(
    departureText(DEPARTURE),
    "MARC Penn Line 7:42 am scheduled from Union Station. You arrive 7:36 am (6 min spare). Next after that: 8:15 am scheduled.",
  );
  assert.match(departureText({ ...DEPARTURE, next: null, next_at: null }), /No later one within the hour\.$/);
  assert.equal(clockOf("2026-10-13T13:05:00-04:00"), "1:05 pm");
  assert.equal(clockOf("2026-10-13T00:10:00-04:00"), "12:10 am");
});

test("the spare time counts down from the plan's moment; under 5 min is cutting it close, under none a miss", () => {
  assert.equal(CLOSE_S, 300);
  const start = countdown(DEPARTURE, at("07:00:00"));
  assert.equal(start.spareS, 360);
  assert.equal(start.toDepartS, 42 * 60);
  assert.equal(start.close, false);
  // A minute and a half later: 4:30 to spare, cutting it close.
  const later = countdown(DEPARTURE, at("07:01:30"));
  assert.equal(later.spareS, 270);
  assert.equal(later.close, true);
  assert.equal(later.missed, false);
  const gone = countdown(DEPARTURE, at("07:06:01"));
  assert.equal(gone.missed, true);
  // Before the plan's moment nothing is spent.
  assert.equal(countdown(DEPARTURE, at("06:50:00")).spareS, 360);
});

test("TB-6: the countdown runs from when the answer arrived, so a wrong phone clock neither misses nor overstates", () => {
  // A phone 10 minutes fast: the answer arrives at 7:10 by its clock. Fresh, the plan still has 6 min to spare.
  const fast = { ...DEPARTURE };
  noteArrived(fast, at("07:10:00"));
  const fresh = countdown(fast, at("07:10:00"));
  assert.equal(fresh.spareS, 360);
  assert.equal(fresh.missed, false, "not marked missed at once");
  assert.equal(fresh.toDepartS, 42 * 60);
  assert.equal(countdown(fast, at("07:11:30")).spareS, 270);
  assert.equal(mapLabel(fast, at("07:11:30")), "MARC 7:42 am scheduled · in 40:30 · 04:30 spare");
  // A phone 10 minutes slow: 7 minutes after the answer it is missed, though the phone says 6:57.
  const slow = { ...DEPARTURE };
  noteArrived(slow, at("06:50:00"));
  assert.equal(countdown(slow, at("06:56:01")).missed, true, "no spare time shown for a train gone");
  // With no arrival noted, as before: against the plan's moment.
  assert.equal(countdown({ ...DEPARTURE }, at("07:10:00")).missed, true);
});

test("TB-6: requestRoute notes when a plan with a departure arrived", async () => {
  const route = {
    distance_m: 1,
    duration_s: 1,
    geometry: { type: "LineString", coordinates: [] },
    stress_m: {},
    attribution: [],
    transit: { departure: { ...DEPARTURE } },
  };
  const result = await requestRoute([[-77.04, 38.91], [-77.01, 38.89]], "mass-ride", {
    fetchImpl: async () => new Response(JSON.stringify(route), { status: 200, headers: { "Content-Type": "application/json" } }),
  });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  const departure = result.route.transit!.departure!;
  // Arrived now by this clock, whatever the plan's own moment says: next to nothing is spent yet.
  assert.ok(countdown(departure, Date.now()).spareS > 359);
});

test("the timer reads mm:ss, never below zero", () => {
  assert.equal(mmss(249), "04:09");
  assert.equal(mmss(0), "00:00");
  assert.equal(mmss(-5), "00:00");
  assert.equal(mmss(3723), "1:02:03");
});

test("the map's label is the plan's words, and the countdown when cutting it close", () => {
  assert.equal(mapLabel(DEPARTURE, at("07:00:00")), "MARC 7:42 am scheduled · 6 min spare");
  assert.equal(mapLabel(DEPARTURE, at("07:01:30")), "MARC 7:42 am scheduled · in 40:30 · 04:30 spare");
  assert.equal(mapLabel(DEPARTURE, at("07:07:00")), "MARC 7:42 am scheduled · missed");
});

test("the label sits above the stop, or below when the start or end marker is near and above it", () => {
  assert.equal(labelSide({ x: 100, y: 100 }, []), "above");
  assert.equal(labelSide({ x: 100, y: 100 }, [{ x: 300, y: 40 }]), "above");
  assert.equal(labelSide({ x: 100, y: 100 }, [{ x: 110, y: 70 }]), "below");
  assert.equal(labelSide({ x: 100, y: 100 }, [{ x: 105, y: 130 }]), "above");
  // The nearer of the two decides.
  assert.equal(labelSide({ x: 100, y: 100 }, [{ x: 100, y: 140 }, { x: 100, y: 90 }]), "below");
});

test("milestones are said once each at 10, 5 and 2 minutes, and a miss says what happens next", () => {
  assert.deepEqual([...MILESTONES_S], [600, 300, 120]);
  assert.equal(milestone(601, 600), 600);
  assert.equal(milestone(600, 599), null);
  assert.equal(milestone(305, 299), 300);
  assert.equal(milestone(121, 119), 120);
  assert.equal(milestone(119, 100), null);
  assert.equal(milestoneSaid(DEPARTURE, 300), "MARC 7:42 am scheduled leaves in 5 minutes.");
  assert.equal(missedSaid(DEPARTURE), "You may miss the MARC 7:42 am scheduled. Planning the next departure.");
  // Live times (v0.7) will say so with the same words.
  assert.equal(milestoneSaid({ ...DEPARTURE, source: "live" }, 300), "MARC 7:42 am live leaves in 5 minutes.");
});

test("the countdown is not a live region, and the map's label is hidden from screen readers", () => {
  const timer = src("DepartureTimer.tsx");
  assert.doesNotMatch(timer, /aria-live|role="(status|timer|alert)"/);
  assert.match(timer, /if \(before === null \|\| !state\.close\) return;/, "milestones only when cutting it close");
  const map = src("MapView.tsx");
  assert.match(map, /element\.className = "departure-label";\n\s*element\.setAttribute\("aria-hidden", "true"\);/);
  // At Go's peek the panel folds away, but a compact countdown stays mounted (milestones, a miss).
  assert.match(src("app/RoutePanel.tsx"), /\{go\.peek && transit\?\.departure && \(\s*<DepartureTimer\s*compact/);
  // Frequent services carry no departure, so no timer: the panel shows one only when the API gives it.
  assert.match(src("TransitSummary.tsx"), /\{plan\.departure && <DepartureTimer/);
});
