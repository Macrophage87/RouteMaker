// Weather along the route (lib/weather.ts, Stephen 2026-10-24): the points sent, the check, and the words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  WEATHER_MAX_POINTS,
  alertLine,
  alertSaid,
  alertUrgent,
  checkWeather,
  newAlerts,
  rainLine,
  rainSays,
  rainStage,
  weatherPoints,
  type WeatherAlert,
  type WeatherRain,
} from "./weather.ts";

// About 22 km due north from the Mall, in 1 km steps.
const LINE = Array.from({ length: 23 }, (_, i) => [-77.03, 38.89 + i * 0.009]);
const PACE = 5; // metres a second

const alert = (over: Partial<WeatherAlert> = {}): WeatherAlert => ({
  id: "a1",
  event: "Severe Thunderstorm Warning",
  severity: "Severe",
  onset: "2026-10-24T21:30:00Z",
  ends: "2026-10-24T22:45:00Z",
  area: "District of Columbia",
  instruction: null,
  url: "https://forecast.weather.gov/MapClick.php?lat=38.90&lon=-77.03",
  ...over,
});
const NOW = Date.parse("2026-10-24T22:00:00Z"); // 6 PM in Washington

test("a point about every 5 miles, from where the rider is to the end, with the seconds until there", () => {
  const { points, alongM } = weatherPoints(LINE, 0, PACE);
  assert.equal(points.length, alongM.length);
  assert.ok(points.length >= 3 && points.length <= WEATHER_MAX_POINTS);
  assert.deepEqual(points[0], [-77.03, 38.89, 0]);
  const last = points[points.length - 1];
  assert.ok(Math.abs(last[1] - LINE[LINE.length - 1][1]) < 1e-6, "the end is sent");
  assert.equal(last[2], Math.round(alongM[alongM.length - 1] / PACE));
  for (let i = 1; i < alongM.length - 1; i++) assert.ok(Math.abs(alongM[i] - alongM[i - 1] - 8000) < 1, "8 km apart");
  // From 10 km along: the seconds count from there.
  const later = weatherPoints(LINE, 10_000, PACE);
  assert.equal(later.points[0][2], 0);
  assert.ok(later.points.length < points.length);
});

test("a long route is spread over at most the most points; no pace or no line sends nothing", () => {
  const long = Array.from({ length: 300 }, (_, i) => [-77.03, 38.0 + i * 0.009]);
  assert.equal(weatherPoints(long, 0, PACE).points.length, WEATHER_MAX_POINTS);
  assert.equal(weatherPoints(LINE, 0, 0).points.length, 0);
  assert.equal(weatherPoints([], 0, PACE).points.length, 0);
});

test("the check posts the points only and keeps where each is along", async () => {
  let sent: { url: string; body: unknown } | null = null;
  const post = (async (url: string, init: RequestInit) => {
    sent = { url, body: JSON.parse(String(init.body)) };
    return new Response(JSON.stringify({ alerts: [alert(), { bad: true }], rain: null, unchecked: [] }), { status: 200 });
  }) as unknown as typeof fetch;
  const out = await checkWeather("https://example.test", { points: [[-77.03, 38.9, 0]], alongM: [0] }, post);
  assert.deepEqual(sent, { url: "https://example.test/api/weather/check", body: { points: [[-77.03, 38.9, 0]] } });
  assert.equal(out?.alerts.length, 1, "a malformed alert is dropped");
  assert.deepEqual(out?.alongM, [0]);
  const down = (async () => new Response("", { status: 503 })) as unknown as typeof fetch;
  assert.equal(await checkWeather("https://example.test", { points: [[-77.03, 38.9, 0]], alongM: [0] }, down), null);
});

test("an alert in one line, at the region's clock", () => {
  assert.equal(alertLine(alert(), NOW), "Severe Thunderstorm Warning until 6:45 PM");
  assert.equal(alertLine(alert({ onset: "2026-10-24T23:00:00Z", ends: "2026-10-25T01:00:00Z", event: "Heat Advisory" }), NOW), "Heat Advisory from 7:00 PM to 9:00 PM");
  assert.equal(alertLine(alert({ ends: null }), NOW), "Severe Thunderstorm Warning");
  assert.equal(alertSaid(alert(), NOW), "Weather alert: Severe Thunderstorm Warning until 6:45 PM.");
});

test("only warnings rated Severe or Extreme interrupt", () => {
  assert.ok(alertUrgent(alert({ event: "Tornado Warning", severity: "Extreme" })));
  assert.ok(alertUrgent(alert()));
  assert.ok(!alertUrgent(alert({ event: "Tornado Watch" })));
  assert.ok(!alertUrgent(alert({ event: "Heat Advisory", severity: "Moderate" })));
});

const rain = (over: Partial<WeatherRain> = {}): WeatherRain => ({ index: 1, offset_s: 1600, starts_in_s: 2700, inches: 0.03, heavy: false, ...over });

test("rain in one line: when, and where on the route, miles first", () => {
  assert.equal(rainLine(rain(), [0, 8000], false), "Rain expected in about 45 min, near mile 5.0 (8.0 km).");
  assert.equal(rainLine(rain({ index: 0, starts_in_s: 300, heavy: true }), [0], true), "Heavy rain expected within 15 min, where you are.");
  assert.equal(rainLine(rain({ index: 0, starts_in_s: 0 }), [0], false), "Rain expected within 15 min, at the start.");
  assert.equal(rainLine(rain({ starts_in_s: 5400 }), [0, 8000], true), "Rain expected in about 1 h 30 min, near mile 5.0 (8.0 km).");
});

test("a ride says rain when it first comes, when it gets close, and when it turns heavy, not again each check", () => {
  assert.ok(rainSays("", rain()));
  assert.ok(!rainSays(rainStage(rain()), rain()));
  assert.ok(rainSays(rainStage(rain()), rain({ starts_in_s: 600 })));
  assert.ok(rainSays(rainStage(rain()), rain({ heavy: true })));
  assert.ok(!rainSays(rainStage(rain({ starts_in_s: 600 })), rain()), "further off again is not said");
  assert.ok(!rainSays(rainStage(rain()), null));
});

test("an alert is said once", () => {
  const report = { alerts: [alert(), alert({ id: "a2" })], rain: null, unchecked: [], alongM: [] };
  assert.deepEqual(newAlerts(report, new Set(["a1"])).map((a) => a.id), ["a2"]);
  assert.deepEqual(newAlerts(null, new Set()), []);
});

test("wired into Go and Plan (with the warnings), Ride mode and Roam; never in Start's path", () => {
  const panel = readFileSync(new URL("../app/RoutePanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /<WeatherLines report=\{weather\} riding=\{false\}/);
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /useWeather\(/);
  assert.match(ride, /<WeatherLines report=\{weatherShown\} riding/);
  const roam = readFileSync(new URL("../RoamMode.tsx", import.meta.url), "utf8");
  assert.match(roam, /useWeather\(/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const start = app.slice(app.indexOf("const startRideChecked"), app.indexOf("const [broadcastNote"));
  assert.doesNotMatch(start, /weather/i, "Start never waits on the weather");
  // The NWS link opens a new tab, named for a screen reader.
  const lines = readFileSync(new URL("../WeatherLines.tsx", import.meta.url), "utf8");
  assert.match(lines, /target="_blank" rel="noopener noreferrer" aria-label=\{nwsLinkName\(alert\)\}/);
});
