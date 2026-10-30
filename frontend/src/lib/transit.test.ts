import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteResponse, TransitPlan } from "./api.ts";
import { describeError } from "./api.ts";
import { routeCredits } from "./bikeshare.ts";
import { announceRoute } from "./summary.ts";
import { loopView } from "./loop.ts";
import { dialFields, type Dials } from "./dials.ts";
import {
  OPTIONS_LABEL,
  busyText,
  STEPS_LABEL,
  TRACK_WORK,
  timesFromText,
  closedName,
  drawOf,
  optionChosenSaid,
  optionSaid,
  optionText,
  transitAttribution,
  transitFeatures,
  transitMarkers,
  transitOf,
  transitSaid,
  transitTime,
  transitTimeName,
  withTransitOption,
  tripCredits,
  tripNotes,
} from "./transit.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

// The shape POST /api/route answers for Own Bike + 🚆🚌 (core.transit.block), trimmed.
const PLAN: TransitPlan = {
  mode: "bike-transit",
  key: "ride>wmata-rail:eastern-market>federal-triangle>ride",
  direct: false,
  options: [
    { key: "ride>wmata-rail:eastern-market>federal-triangle>ride", label: "Ride, Metro to Federal Triangle (Orange Line), ride", total_s: 1677, minutes: 28, direct: false, chosen: true },
    { key: "direct", label: "Ride the whole way", total_s: 1900, minutes: 32, direct: true, chosen: false },
  ],
  total_s: 1677,
  minutes: 28,
  summary: "About 28 min door to door, scheduled.",
  bike_only_s: 1900,
  comparison: "Riding the whole way: about 32 min. Transit saves about 4 min.",
  riding_quicker: false,
  steps: [
    { mode: "ride", text: "Ride 4 min to Eastern Market.", seconds: 222, wait_s: 0, to: "Eastern Market", lines: [], with_bike: false, route_line: true, coordinates: [] },
    { mode: "enter", text: "About 4 min into the station by the elevator.", seconds: 240, wait_s: 0, to: null, lines: [], with_bike: true, route_line: false, coordinates: [] },
    {
      mode: "metro",
      text: "Board the Orange Line (every 10 min, scheduled; about 5 min wait); ride 10 min to Federal Triangle.",
      seconds: 600,
      wait_s: 300,
      to: "Federal Triangle",
      lines: ["Orange Line"],
      system: "Metro",
      departs: null,
      every_min: 10,
      source: "scheduled",
      with_bike: true,
      route_line: false,
      coordinates: [
        [-76.996, 38.8846],
        [-77.0051, 38.8851],
        [-77.0159, 38.8851],
      ],
    },
    { mode: "exit", text: "About 4 min out of the station by the elevator.", seconds: 240, wait_s: 0, to: null, lines: [], with_bike: true, route_line: false, coordinates: [] },
    {
      mode: "ride",
      text: "Ride 1 min to your destination.",
      seconds: 75,
      wait_s: 0,
      to: null,
      lines: [],
      with_bike: false,
      route_line: false,
      coordinates: [
        [-77.0281, 38.8932],
        [-77.03, 38.896],
      ],
    },
  ],
  notes: ["Metro: use the elevators and a car's end doors."],
  day_type: "weekday",
  band: "morning rush",
  holiday: false,
  bike_blackout: false,
  scheduled: true,
  credits: ["WMATA GTFS (scheduled times)"],
  departure: null,
};

const ROUTE = { attribution: ["© OpenStreetMap contributors"], bikeshare: null, transit: PLAN } as unknown as RouteResponse;

test("the total is said 'about' and 'scheduled', with riding the whole way beside it", () => {
  assert.equal(transitTime(PLAN), "about 28 min");
  assert.equal(transitOf(ROUTE), PLAN);
  assert.equal(transitOf({ transit: null }), null);
  const said = transitSaid(ROUTE)!;
  assert.match(said, /^Own bike plus train or bus planned: About 28 min door to door, scheduled\. Riding the whole way: about 32 min/);
  // The announcement is brief: the steps are in the panel's list, not read out on arrival.
  assert.ok(!said.includes("Board the Orange Line"));
  assert.equal(announceRoute(ROUTE), said);
  assert.match(transitSaid({ transit: { ...PLAN, bike_blackout: true } })!, /Bikes aren't allowed on Metro today\./);
});

test("the map draws every step past the route's own line, transit dashed apart from walks and rides", () => {
  const features = transitFeatures(PLAN).features;
  assert.deepEqual(
    features.map((f) => f.properties.draw),
    ["transit", "ride"],
  );
  assert.equal(transitFeatures(null).features.length, 0);
  assert.equal(drawOf({ mode: "walk" }), "walk");
  assert.equal(drawOf({ mode: "take" }), "walk");
  assert.equal(drawOf({ mode: "bus" }), "transit");
  assert.equal(drawOf({ mode: "enter" }), null);
});

test("each Metro and bus step has a text marker, so colour is not the only cue", () => {
  const markers = transitMarkers(PLAN);
  assert.equal(markers.length, 1);
  assert.equal(markers[0].badge, "Metro");
  assert.equal(markers[0].label, "Metro, Orange Line, to Federal Triangle");
  assert.deepEqual([markers[0].lon, markers[0].lat], [-77.0051, 38.8851]);
  const bus = transitMarkers({ ...PLAN, steps: [{ ...PLAN.steps[2], mode: "bus", system: "Metrobus", lines: ["B10"], to: "the stop at Union Station" }] });
  assert.equal(bus[0].badge, "Bus");
  assert.equal(bus[0].label, "Bus B10, to the stop at Union Station");
  // MARC and the Light RailLink are named by their system, dashed like Metro.
  const marc = transitMarkers({ ...PLAN, steps: [{ ...PLAN.steps[2], mode: "rail", system: "MARC", lines: ["Penn Line"], to: "Baltimore Penn Station" }] });
  assert.equal(marc[0].badge, "MARC");
  assert.equal(marc[0].label, "MARC, Penn Line, to Baltimore Penn Station");
  const light = transitMarkers({ ...PLAN, steps: [{ ...PLAN.steps[2], mode: "light-rail", system: "Light RailLink", lines: ["Light RailLink"], to: null }] });
  assert.equal(light[0].label, "Light RailLink");
  assert.equal(drawOf({ mode: "rail" }), "transit");
  assert.equal(drawOf({ mode: "subway" }), "transit");
});

test("the options are lettered, best first, with riding the whole way among them", () => {
  // Stephen, 2026-10-21: ranked by time with busy roads and junctions counted against a trip.
  assert.equal(OPTIONS_LABEL, "Trips, best first, counting busy roads");
  assert.equal(optionText(PLAN.options[0], 0), "A. Ride, Metro to Federal Triangle (Orange Line), ride: about 28 min");
  assert.equal(optionText(PLAN.options[1], 1), "B. Ride the whole way: about 32 min");
  assert.equal(optionChosenSaid(PLAN.options[1]), "Planning Ride the whole way, about 32 min.");
  assert.ok(PLAN.options.some((o) => o.direct));
  const summary = src("TransitSummary.tsx");
  assert.match(summary, /<ol className="transit-options" aria-label=\{OPTIONS_LABEL\}>/);
  assert.match(summary, /aria-pressed=\{option\.chosen\}/);
  assert.match(summary, /\{TRACK_WORK\}/);
  assert.equal(TRACK_WORK, "Scheduled service: check for track work and service alerts before you go.");
});

test("TB-13: the times are said as published timetables, Metro's typical service, or both, from the plan's credits", () => {
  const typical = "WMATA, wmata.com (typical service)";
  const marc = "MARC, Maryland Transit Administration";
  const base = { day_type: "weekday" as const, holiday: false };
  assert.equal(
    timesFromText({ ...base, credits: [typical] }),
    "Metro's times are its typical weekday service from wmata.com, not a timetable: its wait is half the usual time between trains.",
  );
  assert.doesNotMatch(timesFromText({ ...base, credits: [typical] }), /published timetables/);
  assert.match(timesFromText({ ...base, credits: [marc] }), /^Times are from each system's published timetables for this weekday: /);
  assert.doesNotMatch(timesFromText({ ...base, credits: [marc] }), /typical/);
  const both = timesFromText({ ...base, credits: [marc, typical] });
  assert.match(both, /published timetables for this weekday: [\s\S]* Metro's times are its typical service from wmata\.com/);
  assert.match(timesFromText({ day_type: "sunday", holiday: true, credits: [typical] }), /typical sunday \(a holiday\) service/);
  assert.match(src("TransitSummary.tsx"), /\{TRACK_WORK\} \{timesFromText\(plan\)\} \{liveTimesText\(plan\)\}/);
});

test("a chosen option goes with the request on a transit ride type, for the same trip only", () => {
  const dials = { stress: 40, hills: 0 } as Dials;
  const pick = { trip: "a|b", key: "direct" };
  assert.equal(withTransitOption(dials, "bike-transit", pick, "a|b").transitOption, "direct");
  assert.equal(dialFields(withTransitOption(dials, "bikeshare-transit", pick, "a|b")).transit_option, "direct");
  // Another trip, or another ride type, starts from the quickest.
  assert.equal(withTransitOption(dials, "bike-transit", pick, "a|c").transitOption, undefined);
  assert.equal(withTransitOption({ ...dials, transitOption: "direct" }, "commute", pick, "a|b").transitOption, undefined);
  assert.equal(withTransitOption(dials, "bike-transit", null, "a|b").transitOption, undefined);
});

test("the map's attribution is the plan's own timetables, not WMATA's alone", () => {
  assert.equal(transitAttribution(PLAN), "WMATA GTFS (scheduled times)");
  assert.equal(transitAttribution({ credits: ["MDOT MTA GTFS (scheduled times)"] }), "MDOT MTA GTFS (scheduled times)");
  assert.equal(transitAttribution(null), "");
  assert.doesNotMatch(src("MapView.tsx"), /attribution: "WMATA GTFS/);
});

test("a closed station is said in words, not by colour alone", () => {
  assert.equal(closedName({ name: "Camden Station", reason: "no MARC weekend service" }), "Camden Station, closed: no MARC weekend service");
});

test("the credits carry the schedule's source, and the operator's on Bikeshare + 🚶🚆🚌", () => {
  assert.deepEqual(routeCredits(ROUTE), ["© OpenStreetMap contributors", "WMATA GTFS (scheduled times)"]);
  const share = { ...ROUTE, transit: { ...PLAN, mode: "bikeshare-transit" } } as RouteResponse;
  assert.deepEqual(routeCredits(share), ["© OpenStreetMap contributors", "Capital Bikeshare", "WMATA GTFS (scheduled times)"]);
  const both = { ...ROUTE, transit: { ...PLAN, credits: ["WMATA GTFS (scheduled times)", "MDOT MTA GTFS (scheduled times)"] } } as RouteResponse;
  assert.deepEqual(routeCredits(both), ["© OpenStreetMap contributors", "WMATA GTFS (scheduled times)", "MDOT MTA GTFS (scheduled times)"]);
});

test("the API's refusals read as sentences: no transit plan, and no schedule installed", () => {
  const none = describeError(422, { error: "No Metro or bus is scheduled between these places at this time.", code: "no_transit" }, null);
  assert.equal(none.title, "No transit plan");
  assert.equal(none.message, "No Metro or bus is scheduled between these places at this time.");
  const down = describeError(503, { error: "Transit times are not available on this server right now.", code: "transit_unavailable" }, "30");
  assert.equal(down.title, "Transit times unavailable");
  assert.equal(down.noAutoResend, true);
});

test("a transit ride type has no loop", () => {
  assert.equal(loopView("bike-transit", true, []), null);
  assert.equal(loopView("bikeshare-transit", false, []), null);
});

test("the panel's steps are a labelled ordered list, with the total, comparison and notes as text", () => {
  const summary = src("TransitSummary.tsx");
  assert.equal(STEPS_LABEL, "Steps, in order");
  assert.match(summary, /<ol className="transit-steps" aria-label=\{STEPS_LABEL\}>/);
  assert.match(summary, /<h3 id=\{`\$\{id\}-heading`\}>\n\s*<PresetName id=\{preset\} suffix=\{`: \$\{plan\.summary\.replace/);
  assert.match(summary, /plan\.riding_quicker \? "transit-compare" : "transit-compare hint"/, "riding quicker is a plain line, not a warning box (P11)");
  // The panel's time is the door-to-door total, named for a screen reader, not the first ride's.
  const panel = src("app/RoutePanel.tsx");
  assert.match(panel, /const timeName = transit \? transitTimeName\(transit\) : t\("Moving time"\);/);
  assert.match(panel, /\{!go\.peek && transitFold\}/);
  // Start ride on a transit plan follows its first riding leg (lib/rideTrip.ts; rideTrip.test.ts).
  assert.match(panel, /const rideable = rideableRoute\(route\);/);
  // The map's markers are images with their whole text equivalent, not buttons.
  const map = src("MapView.tsx");
  assert.match(map, /element\.className = "transit-marker";\n\s*element\.setAttribute\("role", "img"\);\n\s*element\.setAttribute\("aria-label", stop\.label\);/);
});

test("a transit trip's row shows its legs as marks, and a screen reader hears them in words", () => {
  // Stephen, 2026-10-12: "🚶 4 min · 🚲 12 min · 🔴 18 min"; colour is never the only cue.
  const option = {
    label: "Walk, Metro to Metro Center (Red Line), walk",
    minutes: 34,
    legs: [
      { mode: "walk", minutes: 4 },
      { mode: "bikeshare", minutes: 12 },
      { mode: "metro", system: "Metro", lines: ["Red Line"], minutes: 18 },
    ],
  };
  assert.equal(optionText(option, 1), "B. 🚶 4 min · 🚲 12 min · 🔴 18 min: about 34 min");
  assert.equal(optionSaid(option, 1), "B. walk 4 minutes, bikeshare 12 minutes, Red Line 18 minutes: about 34 min");
  // Riding or walking the whole way keeps its words.
  const walk = { label: "Walk the whole way", minutes: 7, legs: [{ mode: "walk", minutes: 7 }] };
  assert.equal(optionText(walk, 0), "A. Walk the whole way: about 7 min");
  assert.equal(optionSaid(walk, 0), "A. Walk the whole way: about 7 min");
  // The button shows the marks aria-hidden and the words beside them.
  const summary = readFileSync(new URL("../TransitSummary.tsx", import.meta.url), "utf8");
  assert.match(summary, /<span aria-hidden="true">\n\s*\{optionText\(option, index\)\}\n\s*\{option\.elevator_out && <Icon name="elevator-out" size=\{16\} \/>\}\n\s*<\/span>\n\s*<span className="visually-hidden">\{optionSaid\(option, index\)\}<\/span>/);
});

test("each option says its busy riding after its time, and an elevator out in words", () => {
  // Stephen, 2026-10-21: "You'd say arrive in X min with x mi of busy roads etc."
  const option = { label: "Ride, Metro, ride", minutes: 34, busy_m: 644, legs: [{ mode: "ride", minutes: 4 }, { mode: "metro", system: "Metro", lines: ["Red Line"], minutes: 18 }] };
  assert.equal(optionText(option, 0), "A. 🚲 4 min · 🔴 18 min: about 34 min, 0.4 mi (0.6 km) busy");
  assert.equal(optionSaid(option, 0), "A. bike 4 minutes, Red Line 18 minutes: about 34 min, 0.4 mi (0.6 km) on busy roads");
  assert.equal(optionText({ ...option, busy_m: 40 }, 0), "A. 🚲 4 min · 🔴 18 min: about 34 min, no busy roads");
  assert.equal(optionText({ ...option, busy_m: null }, 0), "A. 🚲 4 min · 🔴 18 min: about 34 min");
  assert.equal(busyText(undefined, "shown"), "");
  assert.match(optionSaid({ ...option, elevator_out: true }, 0), /; an elevator is out on the way, so it is ranked lower$/);
});

test("the total's name says live where a departure is WMATA's prediction", () => {
  assert.equal(transitTimeName({ scheduled: true, live_times: true }), "Door-to-door time, with live departures");
  assert.equal(transitTimeName({ scheduled: true, live_times: false }), "Door-to-door time, scheduled");
  assert.equal(transitTimeName({ scheduled: true }), "Door-to-door time, scheduled");
  assert.equal(transitTimeName({ scheduled: false }), "Door-to-door time");
});

test("the notes say only the trip's own lines, and the times words once (P11)", () => {
  const step = (lines: string[]) => ({ lines }) as unknown as TransitPlan["steps"][number];
  const notes = [
    "VRE Manassas Line: no service at this time.",
    "MARC Penn Line: no bikes on board this train.",
    "Red: no weekend service.",
    "Scheduled service: check for track work and service alerts before you go.",
    "Departures marked live are WMATA's predictions; the time on board is scheduled.",
    "Bikes ride free off peak.",
  ];
  const red = { notes, scheduled: true, steps: [step([]), step(["Red"]), step([])] };
  assert.deepEqual(tripNotes(red), ["Red: no weekend service.", "Bikes ride free off peak."]);
  // Riding the whole way (no transit leg): every line's note still says why it is not on the plan.
  const ride = { notes: notes.slice(0, 3), scheduled: false, steps: [step([])] };
  assert.deepEqual(tripNotes(ride), notes.slice(0, 3));
  assert.deepEqual(tripCredits({ credits: ["WMATA GTFS (scheduled times)", "MARC GTFS", "WMATA GTFS (scheduled times)"] }), [
    "WMATA GTFS (scheduled times)",
    "MARC GTFS",
  ]);
});
