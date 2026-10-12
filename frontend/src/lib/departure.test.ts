import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { TransitDeparture } from "./api.ts";
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
  label: "MARC 7:42 am · 6 min spare",
};
const at = (clock: string) => Date.parse(`2026-10-13T${clock}-04:00`);

test("the departure is said plainly: which, when, from where, when you arrive, and the one after", () => {
  assert.equal(
    departureText(DEPARTURE),
    "MARC Penn Line 7:42 am from Union Station. You arrive 7:36 am (6 min spare). Next after that: 8:15 am.",
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

test("the timer reads mm:ss, never below zero", () => {
  assert.equal(mmss(249), "04:09");
  assert.equal(mmss(0), "00:00");
  assert.equal(mmss(-5), "00:00");
  assert.equal(mmss(3723), "1:02:03");
});

test("the map's label is the plan's words, and the countdown when cutting it close", () => {
  assert.equal(mapLabel(DEPARTURE, at("07:00:00")), "MARC 7:42 am · 6 min spare");
  assert.equal(mapLabel(DEPARTURE, at("07:01:30")), "MARC 7:42 am · in 40:30 · 04:30 spare");
  assert.equal(mapLabel(DEPARTURE, at("07:07:00")), "MARC 7:42 am · missed");
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
  assert.equal(milestoneSaid(DEPARTURE, 300), "MARC 7:42 am leaves in 5 minutes.");
  assert.equal(missedSaid(DEPARTURE), "You may miss the 7:42 am MARC. Planning the next departure.");
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
