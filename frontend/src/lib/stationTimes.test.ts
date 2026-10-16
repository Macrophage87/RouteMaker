import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { StationLineTime, StationLive, StationTimes } from "./api.ts";
import {
  SCHEDULED_WORD,
  TIMES_TTL_MS,
  cachedStationTimes,
  clearStationTimes,
  liveRows,
  requestStationTimes,
  stationCardRows,
  shownLines,
  stationTimeRows,
  stationTimesUrl,
} from "./stationTimes.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

const line = (over: Partial<StationLineTime>): StationLineTime => ({
  system: "Metro",
  line: "Red Line",
  station: "Union Station",
  kind: "every",
  every_min: 8,
  toward: null,
  time: null,
  at: null,
  today: true,
  ...over,
});

test("a frequent line says its interval, scheduled, with its emoji shown and words said", () => {
  const [row] = stationTimeRows([line({})]);
  assert.equal(row.shown, "🔴 Red Line: every 8 min, scheduled");
  assert.equal(row.spoken, "Red Line every 8 minutes, scheduled");
  const [light] = stationTimeRows([line({ system: "Light RailLink", line: "Light RailLink", every_min: 15 })]);
  assert.equal(light.shown, "🚈 Light RailLink: every 15 min, scheduled");
  const [subway] = stationTimeRows([line({ system: "Metro SubwayLink", line: "Metro SubwayLink", every_min: 1 })]);
  assert.equal(subway.spoken, "Metro SubwayLink every 1 minute, scheduled");
});

test("a commuter line says its next train each way on one line, with the destination and time", () => {
  const rows = stationTimeRows([
    line({ system: "MARC", line: "Penn Line", kind: "next", every_min: null, toward: "Baltimore Penn Station", time: "5:42 pm" }),
    line({ system: "MARC", line: "Penn Line", kind: "next", every_min: null, toward: "Union Station MARC", time: "6:10 pm" }),
    line({ system: "VRE", line: "Manassas Line", kind: "next", every_min: null, toward: "Broad Run", time: "6:05 pm" }),
  ]);
  assert.deepEqual(
    rows.map((r) => r.shown),
    ["🚆Penn to Baltimore Penn Station 5:42 pm, to Union Station 6:10 pm, scheduled", "🚆Manassas to Broad Run 6:05 pm, scheduled"],
  );
  assert.equal(rows[0].spoken, "MARC Penn Line to Baltimore Penn Station 5:42 pm, to Union Station 6:10 pm, scheduled");
  assert.equal(rows[1].spoken, "VRE Manassas Line to Broad Run 6:05 pm, scheduled");
});

test("no more trains is said plainly, and a line not running today says so", () => {
  const rows = stationTimeRows([
    line({ system: "MARC", line: "Penn Line", kind: "next", every_min: null, toward: "Perryville", time: "11:02 pm" }),
    line({ system: "MARC", line: "Penn Line", kind: "none", every_min: null, toward: "Union Station" }),
    line({ system: "MARC", line: "Camden Line", kind: "none", every_min: null, today: false }),
    line({ kind: "none", every_min: null, toward: "Glenmont" }),
  ]);
  assert.deepEqual(
    rows.map((r) => r.shown),
    [
      "🚆Penn to Perryville 11:02 pm, to Union Station: no more trains today, scheduled",
      "🚆Camden: no trains today",
      "🔴 Red Line: to Glenmont: no more trains today",
    ],
  );
  assert.equal(rows[1].spoken, "MARC Camden Line: no trains today");
  // A time is never shown without the word.
  for (const row of rows) if (/\d:\d\d/.test(row.shown)) assert.ok(row.shown.endsWith(SCHEDULED_WORD));
});

test("the map's toggles decide which systems' lines a card shows", () => {
  const lines = [line({}), line({ system: "MARC", line: "Penn Line" }), line({ system: "VRE", line: "Manassas Line" })];
  assert.deepEqual(
    shownLines(lines, { metro: false, marc: true }).map((l) => l.system),
    ["MARC", "VRE"],
  );
  assert.deepEqual(
    shownLines(lines, { metro: true, marc: false }).map((l) => l.system),
    ["Metro", "VRE"],
  );
});

test("a station's times are asked for once a minute, and none where the server has no timetable", async () => {
  clearStationTimes();
  const asked: string[] = [];
  const answer = { service_day: "2026-10-12", source: "scheduled", lines: [line({})] };
  const ok = async (url: string) => {
    asked.push(url);
    return new Response(JSON.stringify(answer), { status: 200 });
  };
  const point: [number, number] = [-77.0063, 38.8973];
  assert.equal(stationTimesUrl(point), "/api/transit/station-times?lon=-77.00630&lat=38.89730");
  const first = await requestStationTimes(point, { fetchImpl: ok, nowMs: 0 });
  assert.equal(first?.lines.length, 1);
  await requestStationTimes(point, { fetchImpl: ok, nowMs: TIMES_TTL_MS - 1 });
  assert.equal(asked.length, 1);
  assert.equal(cachedStationTimes(point, TIMES_TTL_MS + 1), undefined);
  // 503 (no timetable): no times, remembered for the minute.
  const busy = async () => new Response("{}", { status: 503 });
  assert.equal(await requestStationTimes(point, { fetchImpl: busy, nowMs: TIMES_TTL_MS + 1 }), null);
  assert.equal(cachedStationTimes(point, TIMES_TTL_MS + 2), null);
  // A body that is not times is none.
  clearStationTimes();
  const odd = async () => new Response(JSON.stringify({ lines: [{ kind: "soon" }] }), { status: 200 });
  assert.equal(await requestStationTimes(point, { fetchImpl: odd, nowMs: 0 }), null);
  clearStationTimes();
});

test("the station's card and the road panel's nearby station say the times, emoji hidden, words said", () => {
  const card = src("railInteraction.ts");
  assert.match(card, /shown\.setAttribute\("aria-hidden", "true"\)/);
  assert.match(card, /spoken\.className = "visually-hidden"/);
  // A closed station keeps its "closed" words and says no times.
  assert.match(card, /if \(!closed\) \{\s+const times = document\.createElement\("ul"\)/);
  assert.match(card, /requestStationTimes\(station\.point\)/);
  const panel = src("RoadInfoDialog.tsx");
  // The panel shows what the card shows: the toggles' systems, and no times for a closed station.
  assert.match(panel, /<StationTimesList station=\{station\} rail=\{rail\} closed=\{Boolean\(stationClosed\?\.\(station\)\)\} \/>/);
  assert.match(panel, /stationCardRows\(times, rail\)/);
  assert.match(card, /stationCardRows\(times, options\.visibility\(\)\)/);
  assert.match(panel, /if \(closed\) return;/);
  assert.match(src("App.tsx"), /rail=\{rail\}\s+stationClosed=\{railClosedReason\}/);
  assert.match(panel, /<span aria-hidden="true">\{row\.shown\}<\/span>/);
  // Nothing new to press: no button or toggle comes with the times.
  assert.doesNotMatch(src("lib/stationTimes.ts"), /button|checkbox/);
});

const LIVE: StationLive = {
  station: "Union Station",
  trains: [
    { line: "Red Line", toward: "Glenmont", minutes: [0], when: "boarding" },
    { line: "Red Line", toward: "Shady Grove", minutes: [1, 9], when: "1 min, 9 min" },
  ],
  elevators: [{ words: "Elevator out at Union Station: carry your bike on the stairs.", where: "Street to mezzanine" }],
  alerts: ["Red Line: Trains single tracking between Takoma and Silver Spring."],
  credit: "Data: WMATA",
  as_of: "2026-10-15T08:00:00-04:00",
};

test("a Metro line's live trains replace its timetable row, marked live, with WMATA's credit last", () => {
  const times: StationTimes = {
    service_day: "2026-10-15",
    source: "scheduled",
    lines: [line({}), line({ system: "MARC", line: "Penn Line", kind: "next", every_min: null, toward: "Perryville", time: "5:42 pm" })],
    live: LIVE,
  };
  const rows = stationCardRows(times, { metro: true, marc: true });
  assert.deepEqual(
    rows.map((r) => r.shown),
    [
      "🔴 Red Line: to Glenmont boarding; to Shady Grove 1 min, 9 min, live",
      "🚆Penn to Perryville 5:42 pm, scheduled",
      "⚠️ Elevator out at Union Station: carry your bike on the stairs.",
      "⚠️ Red Line: Trains single tracking between Takoma and Silver Spring.",
      "Data: WMATA",
    ],
  );
  assert.equal(rows[0].spoken, "Red Line to Glenmont boarding; to Shady Grove 1 minute, 9 minutes, live");
  // Every time is labelled: live or scheduled.
  for (const row of rows) if (/\d min|\d:\d\d/.test(row.shown) && !row.shown.startsWith("⚠️")) assert.match(row.shown, /(live|scheduled)$/);
});

test("with no live reading, or Metro hidden, the card is the timetable's", () => {
  const times: StationTimes = { service_day: "2026-10-15", source: "scheduled", lines: [line({})], live: null };
  assert.deepEqual(
    stationCardRows(times, { metro: true, marc: true }).map((r) => r.shown),
    ["🔴 Red Line: every 8 min, scheduled"],
  );
  assert.deepEqual(stationCardRows({ ...times, live: LIVE }, { metro: false, marc: true }), []);
  assert.deepEqual(liveRows(null), []);
  assert.deepEqual(stationCardRows(null, { metro: true, marc: true }), []);
});
