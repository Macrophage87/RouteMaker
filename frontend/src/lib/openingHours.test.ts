import { test } from "node:test";
import assert from "node:assert/strict";
import { clockText, hoursClean, hoursNow, hoursText, openAt, parseHours, regionClock } from "./openingHours.ts";

// The region's clock (America/New_York, EDT in October 2026), whatever zone the test runs in.
const at = (iso: string) => new Date(`${iso}-04:00`);
const WED_NOON = at("2026-10-14T12:00");
const WED_9PM = at("2026-10-14T21:00");
const WED_6AM = at("2026-10-14T06:00");
const SAT_LATE = at("2026-10-17T23:30");
const SUN_EARLY = at("2026-10-18T01:00");
const SUN_NOON = at("2026-10-18T12:00");

test("the region's clock, not the phone's", () => {
  assert.deepEqual(regionClock(WED_NOON), { day: 3, minute: 12 * 60 });
  // 03:30 UTC on Thursday is still Wednesday night in DC.
  assert.deepEqual(regionClock(new Date("2026-10-15T03:30:00Z")), { day: 3, minute: 23 * 60 + 30 });
});

test("parse: day ranges, several spans, off, 24/7; a later rule replaces an earlier one", () => {
  const week = parseHours("Mo-Fr 09:00-17:00; Sa 10:00-12:00,13:00-15:00; Su off")!;
  assert.deepEqual(week[1], [[540, 1020]]);
  assert.deepEqual(week[6], [[600, 720], [780, 900]]);
  assert.deepEqual(week[0], []);
  assert.deepEqual(parseHours("24/7")![3], [[0, 1440]]);
  assert.deepEqual(parseHours("Mo-Su 08:00-20:00; We off")![3], []);
  // Days that wrap round the week, and a day list.
  assert.deepEqual(parseHours("Fr-Mo 10:00-14:00")!.map((d) => d!.length), [1, 1, 0, 0, 0, 1, 1]);
  assert.deepEqual(parseHours("Mo,We 10:00-14:00")!.map((d) => d!.length), [0, 1, 0, 1, 0, 0, 0]);
  // No days: every day.
  assert.ok(parseHours("10:00-18:00")!.every((d) => d!.length === 1));
  // The spec's additional rule: a "," before a day.
  assert.deepEqual(parseHours("Mo-Fr 08:00-17:00, Sa 09:00-12:00")![6], [[540, 720]]);
});

test("parse: holidays are left out; what is not read is null", () => {
  assert.deepEqual(parseHours("PH off; Mo-Fr 09:00-17:00")![3], [[540, 1020]]);
  assert.deepEqual(parseHours("Mo-Fr 09:00-17:00; PH 10:00-12:00")![3], [[540, 1020]]);
  assert.deepEqual(parseHours("Mo-Fr,PH 09:00-17:00")![1], [[540, 1020]]);
  assert.equal(parseHours("Mo-Fr sunrise-sunset"), null);
  assert.equal(parseHours("Apr-Oct Mo-Fr 09:00-17:00"), null);
  assert.equal(parseHours("by appointment"), null);
  assert.equal(parseHours(""), null);
  // A day's rule that cannot be read leaves that day unknown, not closed.
  assert.equal(parseHours("Mo-Fr 09:00-17:00; Sa 10:00+")![6], null);
});

test("parse: a tag cut at 80 characters has its last rule's days unknown", () => {
  const cut = "Mo 16:00-22:00; Tu-Th 11:30-14:00,16:00-22:00; Fr 11:30-14:00,16:00-23:00; Sa 11";
  assert.equal(cut.length, 80);
  const week = parseHours(cut)!;
  assert.equal(week[6], null);
  assert.deepEqual(week[5], [[690, 840], [960, 1380]]);
  // Even a last rule that reads: it may have lost a span.
  const whole = "Mo-Th 07:00-11:00,16:00-22:00; Fr 07:00-11:00,16:00-23:00; Sa 07:00-14:00,16:00-22:00";
  assert.equal(parseHours(whole.slice(0, 80))![6], null);
});

test("open now, and when it changes", () => {
  assert.equal(openAt("Mo-Sa 10:00-19:00; Su off", WED_NOON), true);
  assert.equal(openAt("Mo-Sa 10:00-19:00; Su off", SUN_NOON), false);
  assert.equal(openAt("24/7", SUN_NOON), true);
  assert.equal(openAt("10:00-12:00,13:00-18:00", WED_NOON), false);
  assert.equal(openAt("Sa 22:00-02:00", SAT_LATE), true);
  assert.equal(openAt("Sa 22:00-02:00", SUN_EARLY), true);
  assert.equal(openAt("Mo-Fr sunrise-sunset", WED_NOON), null);
  assert.equal(openAt("PH off; Mo-Fr 09:00-17:00", WED_NOON), true);
  assert.deepEqual(hoursNow("Mo-Fr 09:00-17:00", WED_NOON), { open: true, changeIn: 300, changeAt: { day: 3, minute: 1020 }, always: false });
  // Open through midnight into the next day's span: it closes at the second span's end.
  assert.equal(hoursNow("Mo-Su 00:00-02:00,18:00-24:00", WED_9PM)!.changeAt!.minute, 120);
  assert.equal(hoursNow("Mo-Su 00:00-24:00", WED_NOON)!.always, true);
  // Unknown today: nothing claimed.
  const cut = "Mo 16:00-22:00; Tu-Th 11:30-14:00,16:00-22:00; Fr 11:30-14:00,16:00-23:00; Sa 11";
  assert.equal(hoursNow(cut, at("2026-10-17T12:00")), null);
  // Known today, closed, and the next opening is today.
  assert.deepEqual(hoursNow(cut, WED_6AM)!.changeAt, { day: 3, minute: 690 });
});

test("words: open now · closes, closed now · opens, the 24-hour clock in AM and PM", () => {
  assert.equal(clockText(22 * 60), "10 PM");
  assert.equal(clockText(7 * 60 + 30), "7:30 AM");
  assert.equal(clockText(0), "midnight");
  assert.equal(clockText(12 * 60), "noon");
  assert.equal(hoursText("Mo-Th 07:00-11:00,16:00-22:00", WED_9PM), "Open now · closes 10 PM");
  assert.equal(hoursText("Mo-Th 07:00-11:00,16:00-22:00", WED_NOON), "Closed now · opens 4 PM");
  assert.equal(hoursText("Mo-Su 11:00-22:00", WED_6AM), "Closed now · opens 11 AM");
  assert.equal(hoursText("Mo-Su 11:00-22:00", at("2026-10-14T23:00")), "Closed now · opens 11 AM tomorrow");
  assert.equal(hoursText("Mo-Fr 09:00-17:00", at("2026-10-17T12:00")), "Closed now · opens Mon 9 AM");
  assert.equal(hoursText("24/7", WED_NOON), "Open 24 hours");
  assert.equal(hoursText("Mo-Fr 09:00-17:00; Sa,Su off", SUN_NOON), "Closed now · opens 9 AM tomorrow");
  // A place closed all week has no opening to say.
  assert.equal(hoursText("off", WED_NOON), "Closed now");
});

test("words: hours that cannot be read now are cleaned up, never raw", () => {
  assert.equal(hoursClean("Mo-Th 07:00-11:00,16:00-22:00"), "Mon–Thu 7–11 AM, 4–10 PM");
  assert.equal(hoursClean("Mo-Fr 09:00-17:00; Sa 10:00-14:00; Su off; PH off"), "Mon–Fri 9 AM–5 PM; Sat 10 AM–2 PM; Sun closed");
  assert.equal(hoursClean("Fr-Sa 11:00-01:00"), "Fri–Sat 11 AM–1 AM");
  assert.equal(hoursClean("Apr-Oct Mo-Fr 09:00-17:00"), "Apr–Oct Mon–Fri 9 AM–5 PM");
  assert.equal(hoursClean("Mo-Fr 12:00-15:00"), "Mon–Fri noon–3 PM");
  assert.equal(hoursClean("24/7"), "Open 24 hours");
  // A tag cut short: its broken end goes, and "…" says so.
  assert.equal(
    hoursClean("Mo-Th 07:00-11:00,16:00-22:00; Fr 07:00-11:00,16:00-23:00; Sa 07:00-14:00,16:00-"),
    "Mon–Thu 7–11 AM, 4–10 PM; Fri 7–11 AM, 4–11 PM; Sat 7 AM–2 PM…",
  );
  assert.equal(hoursText("Mo-Fr sunrise-sunset", WED_NOON), "Hours: Mon–Fri sunrise–sunset");
  // Saturday is the cut rule, so on a Saturday the hours are shown cleaned.
  assert.match(hoursText("Mo-Th 07:00-11:00,16:00-22:00; Fr 07:00-11:00,16:00-23:00; Sa 07:00-14:00,16:00-", at("2026-10-17T12:00")), /^Hours: Mon–Thu 7–11 AM/);
});
