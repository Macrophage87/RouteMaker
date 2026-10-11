// The ride time the map follows (lib/rideTime.ts), as routemaker.ridetime.when_at works it out.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { federalHolidays, mapWhen, whenAt } from "./rideTime.ts";

test("the weekend, rush hours and the rest, in the region's time", () => {
  assert.equal(whenAt(new Date("2026-10-03T13:00:00Z")), "weekend"); // Saturday 09:00 EDT
  assert.equal(whenAt(new Date("2026-10-04T23:00:00Z")), "weekend"); // Sunday 19:00 EDT
  assert.equal(whenAt(new Date("2026-09-28T12:30:00Z")), "weekday_rush"); // Monday 08:30 EDT
  assert.equal(whenAt(new Date("2026-09-28T11:00:00Z")), "weekday_rush"); // 07:00 EDT, the start
  assert.equal(whenAt(new Date("2026-09-28T14:00:00Z")), "weekday_offpeak"); // 10:00 EDT, the end
  assert.equal(whenAt(new Date("2026-09-28T21:30:00Z")), "weekday_rush"); // 17:30 EDT
  assert.equal(whenAt(new Date("2026-09-28T23:00:00Z")), "weekday_offpeak"); // 19:00 EDT
  // Friday 20:30 EDT is 00:30 on Saturday in UTC: still a weekday here.
  assert.equal(whenAt(new Date("2026-10-03T00:30:00Z")), "weekday_offpeak");
  // Night, 21:00 to 07:00 on any day (OWNER-DECISIONS 469c), as the API reads it.
  assert.equal(whenAt(new Date("2026-10-03T03:30:00Z")), "night"); // Friday 23:30 EDT
  assert.equal(whenAt(new Date("2026-09-29T01:00:00Z")), "night"); // Monday 21:00 EDT, the start
  assert.equal(whenAt(new Date("2026-09-29T00:59:00Z")), "weekday_offpeak"); // 20:59 EDT
  assert.equal(whenAt(new Date("2026-09-28T10:59:00Z")), "night"); // Monday 06:59 EDT
  assert.equal(whenAt(new Date("2026-10-04T03:00:00Z")), "night"); // Saturday 23:00 EDT
  // In winter the region is five hours behind: Monday 08:30 EST.
  assert.equal(whenAt(new Date("2026-12-07T13:30:00Z")), "weekday_rush");
});

test("a federal holiday is the weekend, as observed", () => {
  const h2026 = federalHolidays(2026);
  for (const day of ["2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25"]) {
    assert.ok(h2026.has(day), day);
  }
  assert.equal(h2026.size, 11);
  assert.equal(whenAt(new Date("2026-09-07T12:30:00Z")), "weekend"); // Labor Day, 08:30
  assert.equal(whenAt(new Date("2026-07-03T16:00:00Z")), "weekend"); // July 4th observed on the Friday
  assert.ok(federalHolidays(2027).has("2027-12-24"), "Christmas on a Saturday is observed the Friday before");
});

test("the map follows the ride time chosen, and the moment's for 'when I'm planning'", () => {
  const monday = new Date("2026-09-28T16:00:00Z");
  assert.equal(mapWhen("weekend", monday), "weekend");
  assert.equal(mapWhen(null, monday), "weekday_offpeak");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /when=\{mapWhen\(dials\.when \?\? null\)\}/);
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /setStressWhen\(map, props\.when\);\s*\}, \[props\.when\]\);/);
  assert.match(view, /addStressOverlay\(map, origin, callbacks\.current\.stressVisible, callbacks\.current\.when\)/);
});
