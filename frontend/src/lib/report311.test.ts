// Report to DC 311 from Ride mode (OWNER-DECISIONS 369, 370, 465): the message, the place words and
// the sms: link's two syntaxes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RideModel } from "./navigate.ts";
import {
  DC_311_SHORT_CODE,
  PLACE_NEAR_M,
  REPORT_KINDS,
  REPORT_NOTE_MAX,
  REPORT_OTHER_HINT,
  REPORT_READY,
  REPORT_SENT,
  canText,
  gpsWords,
  isUnnamed,
  keywordOf,
  onlineHint,
  pickWay,
  placeWords,
  report311Enabled,
  reportPlace,
  reportText,
  sendReport311,
  smsHref,
  type ReportPlace,
} from "./report311.ts";
import { parseTrailMiles } from "./trailMiles.ts";

// ---- One tap (v0.7.0, "Go riding fixes" item 3): tap 311, tap the problem, sent ----

test("a pick goes to the server where it sends, else to the text app on a phone, else the report to copy", () => {
  assert.equal(pickWay(true, true), "server");
  assert.equal(pickWay(true, false), "server");
  assert.equal(pickWay(false, true), "sms");
  assert.equal(pickWay(false, false), "form");
  assert.equal(REPORT_SENT, "Sent to DC 311.");
  assert.equal(REPORT_READY, "Ready to send in Messages.");
});

test("the text for a pick has the problem, the place and the GPS position filled in, and no note before it", () => {
  const tree = reportText("tree", JUNCTION, "", true) ?? "";
  assert.equal(tree, `Downed tree. Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`);
  const href = smsHref(reportText("pothole", JUNCTION, "", true) ?? "", "iPhone", 5);
  assert.ok(href.startsWith("sms:32311&body=POTHOLE%20Location%3A%20on%20Q%20Street"), href);
  assert.ok(decodeURIComponent(href).includes(J_GPS));
});

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
  assert.equal(await sendReport311("https://x", "pothole", JUNCTION, "", send.fn), true);
  assert.equal(send.calls[0].init?.method, undefined);
  const body = JSON.parse(String(send.calls[1].init?.body));
  assert.equal(send.calls[1].init?.method, "POST");
  assert.deepEqual(body, { kind: "pothole", lat: 38.91057, lon: -77.0389, description: `Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`, ticket: "t1" });
  // Off, refused or no signal: not sent, and the pick falls back to the text message.
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

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const ANDROID = "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36";
const IPAD = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const DESKTOP = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";

test("DC's published keywords: POTHOLE and STREETLIGHT; anything else has none (ouc.dc.gov/service/text-311)", () => {
  assert.equal(DC_311_SHORT_CODE, "32311");
  assert.deepEqual(
    REPORT_KINDS.map((k) => k.keyword),
    ["POTHOLE", null, null, null, "STREETLIGHT", null],
  );
});

test("the owner's list (2026-10-11): Pothole first, then a downed tree, a vehicle in a bike lane, a roadway or bikeway obstructed, in the owner's words; Streetlight out and Something else kept", () => {
  assert.deepEqual(
    REPORT_KINDS.map((k) => k.label),
    ["Pothole", "Downed tree", "Vehicle parked in a bike lane", "Roadway or bikeway obstructed", "Streetlight out", "Something else"],
  );
  assert.equal(REPORT_KINDS[0].kind, "pothole", "Pothole is first, the default");
  for (const k of REPORT_KINDS) assert.ok(k.label.length <= 30, `short enough for a phone: ${k.label}`);
  assert.equal(new Set(REPORT_KINDS.map((k) => k.kind)).size, REPORT_KINDS.length);
});

test("a kind with no keyword names the problem first, so DC knows what it is without a note", () => {
  assert.equal(reportText("tree", JUNCTION), `Downed tree. Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`);
  assert.equal(
    reportText("bikeLane", JUNCTION, "white van"),
    `Vehicle parked in a bike lane. Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}. white van.`,
  );
  assert.equal(reportText("obstruction", TRAIL), `Roadway or bikeway obstructed. Location: on Metropolitan Branch Trail, Washington, DC. ${T_GPS}.`);
  // The text form is the same words: these kinds have no keyword to put first.
  assert.equal(reportText("tree", JUNCTION, "", true), reportText("tree", JUNCTION));
  // Something else still relies on the note.
  assert.equal(reportText("other", JUNCTION), `Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`);
});

test("the hint beside DC 311 online names its request where one is known, and none is guessed for an obstruction", () => {
  assert.equal(onlineHint("pothole"), null);
  assert.equal(onlineHint("streetlight"), null);
  assert.match(onlineHint("tree") ?? "", /Tree Inspection and Tree Removal/);
  assert.match(onlineHint("bikeLane") ?? "", /parking requests include Parking Enforcement/);
  // No source says a vehicle in a bike lane is a Parking Enforcement request, so the hint does not say so.
  assert.doesNotMatch(onlineHint("bikeLane") ?? "", /is a Parking Enforcement request/);
  for (const kind of ["tree", "bikeLane", "obstruction", "other"] as const) {
    assert.ok(onlineHint(kind)?.startsWith(REPORT_OTHER_HINT), kind);
  }
  assert.doesNotMatch(onlineHint("obstruction") ?? "", /request is|is a .* request/);
  assert.match(onlineHint("other") ?? "", /note/);
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
  const text = reportText("pothole", far, "", true) ?? "";
  assert.equal(text, `POTHOLE Location: on a path, Washington, DC. ${gpsWords(far.point)}.`);
  assert.doesNotMatch(text, /miles|of unnamed|unnamed path,? about/);
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
  assert.equal(
    reportText("pothole", far, "", true),
    `POTHOLE Location: on Metropolitan Branch Trail at about mile 2.2, Washington, DC. ${gpsWords(far.point)}.`,
    "the mile and the coordinates, side by side",
  );
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

test("the copy for DC 311 online: the place in DC and its GPS position, then the note, with no text keyword", () => {
  assert.equal(reportText("pothole", JUNCTION), `Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`);
  assert.equal(reportText("streetlight", TRAIL, "out"), `Location: on Metropolitan Branch Trail, Washington, DC. ${T_GPS}. out.`);
  assert.equal(reportText("pothole", { words: null, point: JUNCTION.point }), `Location: Washington, DC. ${J_GPS}.`, "no words: the coordinates stand alone");
  assert.equal(keywordOf("pothole"), "POTHOLE");
  assert.equal(keywordOf("other"), null);
});

test("the text: the keyword first, then the place in DC and its GPS position, then the note, tidied and capped", () => {
  assert.equal(reportText("pothole", JUNCTION, "", true), `POTHOLE Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`);
  assert.equal(
    reportText("streetlight", TRAIL, "  out on the  east side ", true),
    `STREETLIGHT Location: on Metropolitan Branch Trail, Washington, DC. ${T_GPS}. out on the east side.`,
  );
  assert.equal(reportText("other", JUNCTION, "Tree down across the lane!"), `Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}. Tree down across the lane!`);
  assert.equal(reportText("pothole", null), null, "no place, no message");
  const long = reportText("other", JUNCTION, "x".repeat(400), true) ?? "";
  assert.ok(long.endsWith(`${"x".repeat(REPORT_NOTE_MAX)}.`), long);
  assert.ok(long.includes(J_GPS), "the note is capped; the coordinates never are");
});

test("every report carries the coordinates and never says unnamed's far distance", () => {
  for (const { kind } of REPORT_KINDS) {
    for (const place of [JUNCTION, TRAIL, UNNAMED]) {
      for (const sms of [false, true]) {
        const text = reportText(kind, place, "", sms) ?? "";
        assert.match(text, /GPS 3\d\.\d{5}, -7\d\.\d{5}/, text);
        assert.doesNotMatch(text, /miles? \w+ of/);
      }
    }
  }
});

test("sms: link: iOS reads the body after &, Android after ? (369)", () => {
  const body = `POTHOLE Location: on Q Street Northwest near R Street Northwest, Washington, DC. ${J_GPS}.`;
  assert.equal(smsHref(body, IPHONE), `sms:32311&body=${encodeURIComponent(body)}`);
  assert.equal(smsHref(body, IPAD, 5), `sms:32311&body=${encodeURIComponent(body)}`, "an iPad says it is a Mac, with touch");
  assert.equal(smsHref(body, ANDROID), `sms:32311?body=${encodeURIComponent(body)}`);
});

test("a phone can text; a desktop goes to DC 311 online (370)", () => {
  assert.equal(canText(IPHONE), true);
  assert.equal(canText(ANDROID), true);
  assert.equal(canText(IPAD, 5), true);
  assert.equal(canText(IPAD, 0), false, "a Mac without touch is a desktop");
  assert.equal(canText(DESKTOP), false);
});

test("Ride mode never looks the position up for the report (plan section 7)", () => {
  const source = readFileSync(new URL("./report311.ts", import.meta.url), "utf8") + readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Neither imports the place search's reverse lookup nor the road panel's (both put a position in a URL).
  assert.doesNotMatch(source, /from "\.\/(lib\/)?(geocode|roadInfo)\.ts"/);
  assert.doesNotMatch(source, /fetch\(/);
});
