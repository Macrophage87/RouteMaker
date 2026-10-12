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
  STEPS_LABEL,
  TRACK_WORK,
  closedName,
  drawOf,
  optionChosenSaid,
  optionText,
  transitAttribution,
  transitFeatures,
  transitMarkers,
  transitOf,
  transitSaid,
  transitTime,
  withTransitOption,
} from "./transit.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

// The shape POST /api/route answers for Own Bike + Transit (core.transit.block), trimmed.
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
  assert.match(said, /^Own Bike \+ Transit planned: About 28 min door to door, scheduled\. Riding the whole way: about 32 min/);
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

test("the options are lettered, quickest first, with riding the whole way among them", () => {
  assert.equal(OPTIONS_LABEL, "Trips, quickest first");
  assert.equal(optionText(PLAN.options[0], 0), "A. Ride, Metro to Federal Triangle (Orange Line), ride: about 28 min");
  assert.equal(optionText(PLAN.options[1], 1), "B. Ride the whole way: about 32 min");
  assert.equal(optionChosenSaid(PLAN.options[1]), "Planning Ride the whole way, about 32 min.");
  assert.ok(PLAN.options.some((o) => o.direct));
  const summary = src("TransitSummary.tsx");
  assert.match(summary, /<ol className="transit-options" aria-label=\{OPTIONS_LABEL\}>/);
  assert.match(summary, /aria-pressed=\{option\.chosen\}/);
  assert.match(summary, /\{TRACK_WORK\}/);
  assert.equal(TRACK_WORK, "Scheduled service; check for track work.");
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

test("the credits carry the schedule's source, and the operator's on Bikeshare + Transit", () => {
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
  assert.match(summary, /<h3 id=\{`\$\{id\}-heading`\}>\{label\}<\/h3>/);
  assert.match(summary, /plan\.riding_quicker \? "transit-compare notice"/);
  // The panel's time is the door-to-door total, named for a screen reader, not the first ride's.
  const panel = src("app/RoutePanel.tsx");
  assert.match(panel, /const timeName = transit \? \(transit\.direct \? "Door-to-door time" : "Door-to-door time, scheduled"\) : "Moving time";/);
  assert.match(panel, /\{!go\.peek && transitFold\}/);
  // No Start ride on a transit plan, whose line is only the first ride, unless it is riding your own bike the whole way.
  assert.match(panel, /const wholeRide = !transit \|\| \(transit\.direct && transit\.mode === "bike-transit"\);/);
  assert.match(panel, /const rideable = !bikeshare && wholeRide && route\.distance_m <= RIDE_MAX_M;/);
  // The map's markers are images with their whole text equivalent, not buttons.
  const map = src("MapView.tsx");
  assert.match(map, /element\.className = "transit-marker";\n\s*element\.setAttribute\("role", "img"\);\n\s*element\.setAttribute\("aria-label", stop\.label\);/);
});
