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
  sourceWord,
  wallClockOf,
} from "./departure.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";

// Spanish's catalog is fetched on choosing it (lib/i18n.ts loadLanguage), as the app does before it starts.
await loadLanguage("es");
/** Intl's clocks may space "7:42 AM" with a narrow no-break space. */
const plain = (text: string) => text.replace(/\s/gu, " ");

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
    plain(departureText(DEPARTURE)),
    "MARC Penn Line 7:42 AM scheduled from Union Station. You arrive 7:36 AM (6 min spare). Next after that: 8:15 AM scheduled.",
  );
  assert.match(departureText({ ...DEPARTURE, next: null, next_at: null }), /No later one within the hour\.$/);
  assert.equal(plain(departureText({ ...DEPARTURE, board_at: null })).split(".")[0], "MARC Penn Line 7:42 AM scheduled");
  assert.equal(plain(clockOf("2026-10-13T13:05:00-04:00", "en-US")), "1:05 PM");
  assert.equal(plain(clockOf("2026-10-13T00:10:00-04:00", "en-US")), "12:10 AM");
});

test("a departure's clock is the phone's own 12 or 24 hour clock, at the station's time, from the API's ISO time", () => {
  // A 24-hour phone, and the same moment written in UTC: still Washington's 7:42 pm.
  assert.equal(clockOf("2026-10-13T19:42:00-04:00", "en-GB"), "19:42");
  assert.equal(clockOf("2026-10-13T23:42:00Z", "en-GB"), "19:42");
  assert.equal(plain(clockOf("2026-10-13T23:42:00Z", "en-US")), "7:42 PM");
  assert.equal(clockOf("2026-10-13T19:42:00-04:00", "fr-FR"), "19:42");
  // The API's own English clock ("7:42 am") and map label are never shown.
  const odd = { ...DEPARTURE, departs: "SERVER CLOCK", next: "SERVER NEXT", label: "SERVER LABEL" };
  for (const text of [departureText(odd), mapLabel(odd, at("07:00:00")), milestoneSaid(odd, 300), missedSaid(odd)]) {
    assert.doesNotMatch(text, /SERVER|\bam\b|\bpm\b/);
  }
});

test("in Spanish the timer, its milestones, its miss and the map's label are Spanish, the source word too", () => {
  setLanguageForTest("es");
  try {
    assert.equal(sourceWord(DEPARTURE), "según horario");
    assert.equal(sourceWord({ source: "live" }), "en tiempo real");
    assert.match(plain(milestoneSaid(DEPARTURE, 300)), /^El MARC 7:42 a\.\s?m\. \(según horario\) sale en 5 minutos\.$/u);
    assert.match(plain(missedSaid(DEPARTURE)), /^Puede que pierdas el MARC 7:42 a\.\s?m\. \(según horario\)\. Planeando la siguiente salida\.$/u);
    assert.match(plain(mapLabel(DEPARTURE, at("07:01:30"))), /^MARC 7:42 a\.\s?m\. \(según horario\) · en 40:30 · 04:30 de sobra$/u);
    assert.match(plain(departureText(DEPARTURE)), /^MARC Penn Line 7:42 a\.\s?m\. \(según horario\) desde Union Station\. Llegada: 7:36 a\.\s?m\. \(6 min de sobra\)\. La siguiente: 8:15 a\.\s?m\. \(según horario\)\.$/u);
    assert.doesNotMatch(departureText(DEPARTURE), /scheduled|You arrive|Next after/);
    // A bus is named in Spanish too, not the server's "bus B10" (the 2026-11-05 review).
    assert.match(plain(departureText({ ...DEPARTURE, vehicle: "bus B10" })), /^Autobús B10 7:42 a\.\s?m\./u);
  } finally {
    setLanguageForTest("en");
  }
  assert.match(plain(departureText({ ...DEPARTURE, vehicle: "bus B10" })), /^Bus B10 7:42 AM/);
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
  assert.equal(plain(mapLabel(fast, at("07:11:30"))), "MARC 7:42 AM scheduled · in 40:30 · 04:30 spare");
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
  assert.equal(plain(mapLabel(DEPARTURE, at("07:00:00"))), "MARC 7:42 AM scheduled · 6 min spare");
  assert.equal(plain(mapLabel(DEPARTURE, at("07:01:30"))), "MARC 7:42 AM scheduled · in 40:30 · 04:30 spare");
  assert.equal(plain(mapLabel(DEPARTURE, at("07:07:00"))), "MARC 7:42 AM scheduled · missed");
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
  assert.equal(plain(milestoneSaid(DEPARTURE, 300)), "MARC 7:42 AM scheduled leaves in 5 minutes.");
  assert.equal(plain(missedSaid(DEPARTURE)), "You may miss the MARC 7:42 AM scheduled. Planning the next departure.");
  // Live times (v0.7) will say so with the same words.
  assert.equal(plain(milestoneSaid({ ...DEPARTURE, source: "live" }, 300)), "MARC 7:42 AM live leaves in 5 minutes.");
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

test("a time the API wrote in English words shows on the phone's own clock, as an ISO time does", () => {
  assert.equal(plain(wallClockOf("8:15 am", "en-US")), "8:15 AM");
  assert.equal(wallClockOf("8:15 pm", "en-GB"), "20:15");
  // Midnight and noon as clockOf shows them.
  assert.equal(wallClockOf("12:05 am", "en-GB"), clockOf("2026-11-05T00:05:00-05:00", "en-GB"));
  assert.equal(plain(wallClockOf("7:42 am", "en-US")), plain(clockOf("2026-11-05T07:42:00-05:00", "en-US")));
  assert.equal(wallClockOf("12:05 pm", "en-GB"), "12:05");
  assert.equal(plain(wallClockOf("8:15 pm", "fr")), "20:15");
  // Anything else as it came.
  assert.equal(wallClockOf("soon", "en-GB"), "soon");
  assert.equal(wallClockOf("13:05 pm", "en-GB"), "13:05 pm");
});
