// Report to DC 311 from Ride mode (OWNER-DECISIONS 369, 370, 465): the message, the place words and
// the sms: link's two syntaxes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RoutePlace } from "./navigate.ts";
import { DC_311_SHORT_CODE, REPORT_KINDS, REPORT_NOTE_MAX, canText, keywordOf, placeWords, reportText, smsHref } from "./report311.ts";

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
    ["POTHOLE", "STREETLIGHT", null],
  );
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
  for (const kind of ["pothole", "streetlight", "other"] as const) {
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
