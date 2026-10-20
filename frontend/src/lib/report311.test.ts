// A problem's place for 311 (OWNER-DECISIONS 369, 370, 465): the six problems, the place words and the GPS
// position, and the server's sender for DC. The log itself is report311Log.test.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RideModel } from "./navigate.ts";
import { PLACE_NEAR_M, REPORT_KINDS, REPORT_SENT, gpsWords, isUnnamed, placeWords, report311Enabled, reportPlace, sendReport311, type ReportPlace } from "./report311.ts";
import { parseTrailMiles } from "./trailMiles.ts";

function fakeFetch(answers: { status: number; body?: unknown; throws?: boolean }[]) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const next = answers.shift()!;
    if (next.throws) throw new TypeError("offline");
    return { ok: next.status >= 200 && next.status < 300, status: next.status, json: async () => next.body } as Response;
  }) as unknown as typeof fetch;
  return { fn, calls };
}

test("the server's sender: asked once whether it is on, and a report sent with the point and the words", async () => {
  const on = fakeFetch([{ status: 200, body: { enabled: true } }]);
  assert.equal(await report311Enabled("https://x", on.fn), true);
  assert.equal(on.calls[0].url, "https://x/api/report311");
  assert.equal(await report311Enabled("https://x", fakeFetch([{ status: 200, body: { enabled: false } }]).fn), false);
  assert.equal(await report311Enabled("https://x", fakeFetch([{ status: 0, throws: true }]).fn), false);

  // A fresh signed ticket is asked for first (GET), and sent back with the report (POST).
  const send = fakeFetch([{ status: 200, body: { enabled: true, ticket: "t1" } }, { status: 200, body: { sent: true, id: "1" } }]);
  assert.equal(REPORT_SENT, "Sent to DC 311.");
  assert.equal(await sendReport311("https://x", "pothole", JUNCTION, "Pothole. Location: on Q Street Northwest.", send.fn), true);
  assert.equal(send.calls[0].init?.method, undefined);
  const body = JSON.parse(String(send.calls[1].init?.body));
  assert.equal(send.calls[1].init?.method, "POST");
  assert.deepEqual(body, { kind: "pothole", lat: 38.91057, lon: -77.0389, description: "Pothole. Location: on Q Street Northwest.", ticket: "t1" });
  // Off, refused or no signal: not sent, and the entry stays on the checklist.
  assert.equal(await sendReport311("https://x", "pothole", JUNCTION, "", fakeFetch([{ status: 200, body: { enabled: false } }]).fn), false);
  const ticketed = { status: 200, body: { enabled: true, ticket: "t1" } };
  assert.equal(await sendReport311("https://x", "pothole", JUNCTION, "", fakeFetch([ticketed, { status: 503, body: { code: "dc311_off" } }]).fn), false);
  assert.equal(await sendReport311("https://x", "pothole", JUNCTION, "", fakeFetch([{ status: 0, throws: true }]).fn), false);
});

const JUNCTION: ReportPlace = { words: "on Q Street Northwest near R Street Northwest", point: [-77.0389012, 38.9105678] };
const TRAIL: ReportPlace = { words: "on Metropolitan Branch Trail", point: [-76.9951234, 38.9301234] };
const UNNAMED: ReportPlace = { words: "on an unnamed path", point: [-77.0512345, 38.9212345] };
const J_GPS = "GPS 38.91057, -77.03890";
const T_GPS = "GPS 38.93012, -76.99512";

/**
 * A straight line north along longitude -77.03, 3 km long: 14th Street Northwest to 1000 m, U Street
 * Northwest to 1500 m, an unnamed path to 3000 m (the API's "unnamed path").
 */
function model(): RideModel {
  const lat0 = 38.9;
  const coordinates: [number, number][] = [];
  const along: number[] = [];
  for (let m = 0; m <= 3000; m += 100) {
    coordinates.push([-77.03, lat0 + m / 111_195]);
    along.push(m);
  }
  return {
    coordinates,
    along: Float64Array.from(along),
    lengthM: 3000,
    cues: [],
    stretches: [
      { fromM: 0, toM: 1000, street: "14th Street Northwest", tier: 1, facility: "lane" },
      { fromM: 1000, toM: 1500, street: "U Street Northwest", tier: 1, facility: "lane" },
      { fromM: 1500, toM: 3000, street: "unnamed path", tier: 1, facility: "path" },
    ],
    paceMs: null,
  } as RideModel;
}

test("the owner's list (2026-10-11): Pothole first, then a downed tree, a vehicle in a bike lane, a roadway or bikeway obstructed, in the owner's words; Streetlight out and Something else kept", () => {
  assert.deepEqual(
    REPORT_KINDS.map((k) => k.label),
    ["Pothole", "Downed tree", "Vehicle parked in a bike lane", "Roadway or bikeway obstructed", "Streetlight out", "Something else"],
  );
  assert.equal(REPORT_KINDS[0].kind, "pothole", "Pothole is first, the default");
  for (const k of REPORT_KINDS) assert.ok(k.label.length <= 30, `short enough for a phone: ${k.label}`);
  assert.equal(new Set(REPORT_KINDS.map((k) => k.kind)).size, REPORT_KINDS.length);
});

test("GPS: latitude first, then longitude, 5 decimals (about 1 m), read as numbers", () => {
  assert.equal(gpsWords([-77.0123449, 38.9123451]), "GPS 38.91235, -77.01234");
  assert.equal(gpsWords([-77, 38.9]), "GPS 38.90000, -77.00000");
});

test("the place words: the way ridden, a cross street only when near, never a distance from a far junction", () => {
  assert.equal(placeWords("14th Street Northwest", "U Street Northwest"), "on 14th Street Northwest near U Street Northwest");
  assert.equal(placeWords("Capital Crescent Trail", null), "on Capital Crescent Trail");
  assert.equal(placeWords("an unnamed path", null), "on an unnamed path");
  assert.equal(placeWords(null, "U Street Northwest"), "near U Street Northwest");
  assert.equal(placeWords(null, null), null);
  assert.ok(isUnnamed("unnamed path") && isUnnamed("unnamed road") && isUnnamed("this part of the route") && isUnnamed(null));
  assert.ok(!isUnnamed("14th Street Northwest"));
  assert.ok(Math.abs(PLACE_NEAR_M * 3.28084 - 500) < 0.01, "500 ft");
});

test("reportPlace: the road at that point, a cross street within 500 ft, the same point's coordinates", () => {
  const m = model();
  const near = reportPlace(m, 950);
  assert.equal(near.words, "on 14th Street Northwest near U Street Northwest");
  assert.equal(gpsWords(near.point), `GPS ${(38.9 + 950 / 111_195).toFixed(5)}, -77.03000`);
  assert.equal(reportPlace(m, 1050).words, "on U Street Northwest near 14th Street Northwest", "the other street of the junction");
  assert.equal(reportPlace(m, 400).words, "on 14th Street Northwest", "the junction is 600 m off: no cross street");
  // The owner's case: far along an unnamed path, no "about 1.2 miles south of ...".
  const far = reportPlace(m, 2900);
  assert.equal(far.words, "on a path");
  assert.doesNotMatch(far.words ?? "", /miles|of unnamed|unnamed path,? about/);
  // The path's start is within 500 ft of its junction with U Street: named only from the U Street side.
  assert.equal(reportPlace(m, 1550).words, "on a path near U Street Northwest");
});

test("reportPlace on a trail: the trail's mile marker beside the road and the coordinates (465; Stephen, 2026-10-16)", () => {
  const m = model();
  m.stretches = [
    { fromM: 0, toM: 1000, street: "14th Street Northwest", tier: 1, facility: "lane" },
    { fromM: 1000, toM: 3000, street: "Metropolitan Branch Trail", tier: 1, facility: "path" },
  ];
  // The trail's line runs north with the route from its mile 0, 1,000 m south of the route's start.
  const line = { n: "Metropolitan Branch Trail", s: 1000, l: [[-77.03, 38.9], [-77.03, 38.9 + 3000 / 111_195]] };
  const computed = parseTrailMiles({ trails: [line], markers: [] });
  const far = reportPlace(m, 2500, computed);
  assert.equal(far.words, "on Metropolitan Branch Trail at about mile 2.2");
  // A posted marker within 500 ft is named as the post says it.
  const posted = parseTrailMiles({ trails: [line], markers: [{ id: "n9", x: -77.03, y: 38.9 + 2560 / 111_195, t: "Metropolitan Branch Trail", m: 2 }] });
  assert.equal(reportPlace(m, 2500, posted).words, "on Metropolitan Branch Trail at mile marker 2");
  // Near a cross street: both.
  assert.equal(reportPlace(m, 1100, computed).words, "on Metropolitan Branch Trail at about mile 1.3 near 14th Street Northwest");
  // A street, or no file yet: as before.
  assert.equal(reportPlace(m, 400, computed).words, "on 14th Street Northwest");
  assert.equal(reportPlace(m, 2500).words, "on Metropolitan Branch Trail");
  assert.equal(placeWords("Metropolitan Branch Trail", null, "mile marker 2"), "on Metropolitan Branch Trail at mile marker 2");
});

test("the place is never looked up by name: no place search or road panel lookup from the ride's 311", () => {
  const source = readFileSync(new URL("./report311.ts", import.meta.url), "utf8") + readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Neither imports the place search's reverse lookup nor the road panel's (both put a position in a URL).
  assert.doesNotMatch(source, /from "\.\/(lib\/)?(geocode|roadInfo)\.ts"/);
  assert.doesNotMatch(source, /fetch\(/);
  assert.doesNotMatch(source, /sms:|smsHref/, "no text message (2026-10-20)");
});
