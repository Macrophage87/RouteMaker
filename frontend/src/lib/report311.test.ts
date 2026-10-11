// Report to DC 311 from Ride mode (OWNER-DECISIONS 369, 370, 465): the message, the place words and
// the sms: link's two syntaxes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RoutePlace } from "./navigate.ts";
import { DC_311_SHORT_CODE, REPORT_KINDS, REPORT_NOTE_MAX, REPORT_OTHER_HINT, canText, keywordOf, onlineHint, placeWords, reportText, smsHref } from "./report311.ts";

const JUNCTION: RoutePlace = { kind: "junction", junction: { atM: 1000, streets: ["Q Street Northwest", "R Street Northwest"] } };
const TRAIL: RoutePlace = {
  kind: "trail",
  trail: "Metropolitan Branch Trail",
  junction: { atM: 300, streets: ["Rhode Island Avenue Northeast", "Metropolitan Branch Trail"] },
  metres: 1930,
  direction: "north",
};

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
  assert.equal(reportText("tree", JUNCTION), "Downed tree. Location: near Q Street Northwest and R Street Northwest, Washington, DC.");
  assert.equal(
    reportText("bikeLane", JUNCTION, "white van"),
    "Vehicle parked in a bike lane. Location: near Q Street Northwest and R Street Northwest, Washington, DC. white van.",
  );
  assert.equal(
    reportText("obstruction", TRAIL),
    "Roadway or bikeway obstructed. Location: on the Metropolitan Branch Trail, about 1.2 miles north of Rhode Island Avenue Northeast, Washington, DC.",
  );
  // The text form is the same words: these kinds have no keyword to put first.
  assert.equal(reportText("tree", JUNCTION, "", true), reportText("tree", JUNCTION));
  // Something else still relies on the note.
  assert.equal(reportText("other", JUNCTION), "Location: near Q Street Northwest and R Street Northwest, Washington, DC.");
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

test("the place in the route's street names, or the trail marker in US units (465)", () => {
  assert.equal(placeWords(JUNCTION), "near Q Street Northwest and R Street Northwest");
  assert.equal(placeWords(TRAIL), "on the Metropolitan Branch Trail, about 1.2 miles north of Rhode Island Avenue Northeast");
  assert.equal(placeWords({ kind: "street", street: "R Street Northwest" }), "on R Street Northwest");
  assert.equal(placeWords(null), null);
});

test("the copy for DC 311 online: the place in DC, then the note, with no text keyword", () => {
  assert.equal(reportText("pothole", JUNCTION), "Location: near Q Street Northwest and R Street Northwest, Washington, DC.");
  assert.equal(reportText("streetlight", TRAIL, "out"), "Location: on the Metropolitan Branch Trail, about 1.2 miles north of Rhode Island Avenue Northeast, Washington, DC. out.");
  assert.equal(keywordOf("pothole"), "POTHOLE");
  assert.equal(keywordOf("other"), null);
});

test("the text: the keyword first, then the place in DC, then the note, tidied and capped", () => {
  assert.equal(reportText("pothole", JUNCTION, "", true), "POTHOLE Location: near Q Street Northwest and R Street Northwest, Washington, DC.");
  assert.equal(
    reportText("streetlight", TRAIL, "  out on the  east side ", true),
    "STREETLIGHT Location: on the Metropolitan Branch Trail, about 1.2 miles north of Rhode Island Avenue Northeast, Washington, DC. out on the east side.",
  );
  assert.equal(reportText("other", JUNCTION, "Tree down across the lane!"), "Location: near Q Street Northwest and R Street Northwest, Washington, DC. Tree down across the lane!");
  assert.equal(reportText("pothole", null), null, "no place, no message");
  const long = reportText("other", JUNCTION, "x".repeat(400)) ?? "";
  assert.ok(long.endsWith(`${"x".repeat(REPORT_NOTE_MAX)}.`), long);
});

test("the message carries no coordinates (the position never leaves the phone in it)", () => {
  for (const { kind } of REPORT_KINDS) {
    const text = reportText(kind, TRAIL, "") ?? "";
    assert.doesNotMatch(text, /-?\d+\.\d{3,}/);
  }
});

test("sms: link: iOS reads the body after &, Android after ? (369)", () => {
  const body = "POTHOLE Location: near Q Street Northwest and R Street Northwest, Washington, DC.";
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
