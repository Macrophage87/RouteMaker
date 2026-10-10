// The nearest stations to take a bike from or return one to (OWNER-DECISIONS 466, 466a): the
// words, the distance in US units first, the chosen station kept apart from the link, and the
// request.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { requestStations } from "./api.ts";
import { dialFields, startDials, type Dials } from "./dials.ts";
import { encodePlan } from "./planHash.ts";
import {
  activePins,
  chosenSaid,
  listPoint,
  stationDistance,
  stationLabel,
  stationsEmpty,
  stationsFreshness,
  stationsHeading,
  stationsLede,
  withStations,
  type NearbyStation,
  type Pins,
} from "./stations.ts";

const A = [-77.0063, 38.8973] as [number, number];
const B = [-77.0436, 38.9096] as [number, number];

function station(over: Partial<NearbyStation> = {}): NearbyStation {
  return {
    station_id: "s1",
    name: "Columbus Circle / Union Station",
    lon: -77.006,
    lat: 38.897,
    percent_full: 82,
    distance_m: 320,
    bikes: 9,
    ebikes: 2,
    docks: 2,
    ...over,
  };
}

test("a station reads as its name, the percentage full, its e-bikes and the distance, miles first (466a)", () => {
  assert.equal(stationLabel(station()), "Columbus Circle / Union Station, 82% full, 2 e-bikes, 0.2 mi (320 m)");
  assert.equal(
    stationLabel(station({ name: "20th & O St NW", percent_full: 24.6, ebikes: 1, distance_m: 1500 })),
    "20th & O St NW, 25% full, 1 e-bike, 0.9 mi (1.5 km)",
  );
  assert.equal(stationLabel(station({ ebikes: 0 })), "Columbus Circle / Union Station, 82% full, no e-bikes, 0.2 mi (320 m)");
});

test("distances: feet under a tenth of a mile, then miles to a tenth with metres in brackets", () => {
  assert.equal(stationDistance(0), "0 ft (0 m)");
  assert.equal(stationDistance(20), "66 ft (20 m)");
  assert.equal(stationDistance(60), "200 ft (60 m)");
  assert.equal(stationDistance(160), "520 ft (160 m)");
  assert.equal(stationDistance(161), "0.1 mi (160 m)");
  assert.equal(stationDistance(320), "0.2 mi (320 m)");
  assert.equal(stationDistance(994), "0.6 mi (990 m)");
  assert.equal(stationDistance(995), "0.6 mi (1.0 km)");
  assert.equal(stationDistance(1000), "0.6 mi (1.0 km)");
  assert.equal(stationDistance(2900), "1.8 mi (2.9 km)");
  assert.equal(stationDistance(Number.NaN), "distance unknown");
  assert.equal(stationDistance(-1), "distance unknown");
});

test("the headings and ledes name the criterion and say the rider chooses, and name no programme", () => {
  assert.match(stationsHeading("pickup"), /pick up/);
  assert.match(stationsHeading("dropoff"), /return/);
  assert.match(stationsLede("pickup"), /3 nearest stations at least 3\/4 full/);
  assert.match(stationsLede("dropoff"), /3 nearest stations at most 1\/4 full/);
  assert.match(stationsLede("pickup"), /Choose one/);
  const everything = [
    stationsHeading("pickup"),
    stationsHeading("dropoff"),
    stationsLede("pickup"),
    stationsLede("dropoff"),
    stationsEmpty("pickup", "live"),
    stationsEmpty("dropoff", "live"),
    stationsEmpty("pickup", "unknown"),
    stationsFreshness("live"),
    stationsFreshness("stale"),
    chosenSaid("pickup", station()),
    chosenSaid("dropoff", null),
  ].join(" ");
  assert.doesNotMatch(everything, /angel|capital|lyft|points?\b/i, "no programme name, no operator, no points");
});

test("an empty list says why, and an unknown availability says so", () => {
  assert.equal(stationsEmpty("pickup", "live"), "No station nearby is at least 3/4 full right now.");
  assert.equal(stationsEmpty("dropoff", "live"), "No station nearby is at most 1/4 full right now.");
  assert.match(stationsEmpty("pickup", "unknown"), /not available right now/);
  assert.match(stationsFreshness("stale"), /minute or two ago/);
  assert.match(stationsFreshness("live"), /Live counts/);
});

test("choosing and handing back a station are said", () => {
  assert.equal(chosenSaid("pickup", station()), "Columbus Circle / Union Station chosen for the pick-up.");
  assert.equal(chosenSaid("dropoff", station({ name: "Dupont" })), "Dupont chosen for the drop-off.");
  assert.equal(chosenSaid("pickup", null), "The pick-up station is chosen for you again.");
});

test("the lists are for the start (pick-up) and, once there is a second point, the end (drop-off)", () => {
  assert.equal(listPoint("pickup", []), null);
  assert.deepEqual(listPoint("pickup", [A]), A);
  assert.equal(listPoint("dropoff", [A]), null);
  assert.deepEqual(listPoint("dropoff", [A, B]), B);
  assert.deepEqual(listPoint("pickup", [A, B]), A);
});

test("a chosen station holds only while its point and the ride type stay", () => {
  const pins: Pins = { pickup: { id: "s1", name: "One", at: A }, dropoff: { id: "s2", name: "Two", at: B } };
  assert.deepEqual(activePins("bikeshare", [A, B], pins), pins);
  assert.deepEqual(activePins("bikeshare", [A], pins), { pickup: pins.pickup });
  assert.deepEqual(activePins("bikeshare", [[A[0] + 0.0001, A[1]], B], pins), { dropoff: pins.dropoff });
  assert.deepEqual(activePins("bikeshare", [A, [B[0], B[1] + 0.0001]], pins), { pickup: pins.pickup });
  assert.deepEqual(activePins("default", [A, B], pins), {}, "another ride type forgets them");
  assert.deepEqual(activePins("bikeshare", [], pins), {});
});

test("the request carries the chosen stations, and the link never does", () => {
  const dials: Dials = startDials("bikeshare", null, null, false, "ebike");
  const sent = withStations(dials, { pickup: { id: "s1", name: "One", at: A }, dropoff: { id: "s2", name: "Two", at: B } });
  assert.equal(sent.pickupStation, "s1");
  assert.equal(sent.dropoffStation, "s2");
  const fields = dialFields(sent);
  assert.equal(fields.pickup_station, "s1");
  assert.equal(fields.dropoff_station, "s2");
  // Nothing chosen: nothing sent, and an earlier choice is dropped from the dials.
  const cleared = withStations(sent, {});
  assert.equal("pickupStation" in cleared, false);
  assert.equal("pickup_station" in dialFields(cleared), false);
  // The link: stations change by the minute, so they are in no link.
  const hash = encodePlan([A, B], "bikeshare", sent);
  assert.doesNotMatch(hash, /s1|s2|station/i);
  assert.equal(hash, encodePlan([A, B], "bikeshare", dials));
});

test("a drop-off station is not sent with an ending outside a dock", () => {
  const ebike: Dials = { ...startDials("bikeshare", null, null, false, "ebike"), ending: "outside_dock" };
  const fields = dialFields(withStations(ebike, { dropoff: { id: "s2", name: "Two", at: B } }));
  assert.equal("dropoff_station" in fields, false);
});

test("a ride type other than Bikeshare never sends a station", () => {
  const fields = dialFields(withStations(startDials("default"), { pickup: { id: "s1", name: "One", at: A } }));
  assert.equal("pickup_station" in fields, false, "only Bikeshare dials carry a bike, and only they send stations");
});

// --- The request ---------------------------------------------------------------------------

test("the request is a POST with the point in the body, never in the address", async () => {
  let seen: { url: string; init: RequestInit } | null = null;
  const answer = { action: "pickup", availability: "live", stations: [station()], credit: "Capital Bikeshare" };
  const result = await requestStations(A, "pickup", {
    fetchImpl: async (url, init) => {
      seen = { url, init };
      return new Response(JSON.stringify(answer), { status: 200, headers: { "Content-Type": "application/json" } });
    },
  });
  assert.ok(result.ok && result.answer.stations.length === 1);
  assert.equal(seen!.url, "/api/bikeshare/stations", "no query string");
  assert.equal(seen!.init.method, "POST");
  assert.deepEqual(JSON.parse(seen!.init.body as string), { point: A, action: "pickup" });
});

test("failures are sentences for the rider", async () => {
  const reply = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });
  const rate = await requestStations(A, "dropoff", { fetchImpl: reply(429, { error: "slow down" }) });
  assert.ok(!rate.ok && /Too many requests/.test(rate.message));
  const down = await requestStations(A, "dropoff", { fetchImpl: reply(503, { code: "bikeshare_unavailable" }) });
  assert.ok(!down.ok && /not available right now/.test(down.message));
  const odd = await requestStations(A, "dropoff", { fetchImpl: reply(200, { nope: true }) });
  assert.ok(!odd.ok);
  const offline = await requestStations(A, "dropoff", {
    fetchImpl: async () => {
      throw new TypeError("offline");
    },
  });
  assert.ok(!offline.ok && /did not load/.test(offline.message));
});

// --- The component's wiring, held to the source ------------------------------------------------

const component = readFileSync(new URL("../NearbyStations.tsx", import.meta.url), "utf8");
const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

test("each station is a real button named as it is read, with aria-pressed for the chosen one", () => {
  assert.match(component, /<button[\s\S]*?type="button"[\s\S]*?aria-pressed=\{chosen\}[\s\S]*?\{stationLabel\(station\)\}/);
  assert.match(component, /<ul className="station-list"/);
  assert.match(component, /<li key=\{station\.station_id\}>/);
  assert.match(component, /role="status"/, "a polite status line");
  assert.match(component, /<h3 id=\{`\$\{id\}-heading`\}>\{stationsHeading\(action\)\}<\/h3>/);
  // The chosen badge is text, hidden from the reader because the button already says pressed.
  assert.match(component, /aria-hidden="true"[\s\S]*?Chosen/);
});

test("the lists are in the Bikeshare panel only and a choice is forgotten with its point", () => {
  assert.match(app, /preset === "bikeshare" && <NearbyStations points=\{points\} pins=\{stationChoice\} onChoose=\{chooseStation\} \/>/);
  assert.match(app, /activePins\(preset, points, stationPins\)/);
  assert.match(app, /withStations\(withWeight\(routeDials, weight\), stationChoice\)/);
  assert.doesNotMatch(app, /encodePlan\([^)]*stationPins/, "never in the link");
});

test("the chosen button is told apart by more than colour", () => {
  assert.match(css, /\.station-choice\[aria-pressed="true"\][\s\S]*?border: 3px solid/);
  assert.match(css, /\.station-choice[\s\S]*?min-height: 44px/);
});
