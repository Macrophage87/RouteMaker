// Ride and Go's words in plain English (the owner, 2026-11-08, asked for the text in Ride and Go to be as simple as
// possible, so that fewer translation errors creep in): short plain words, one idea to a sentence, no idioms ("carry
// on", "ride off", "Ride on.", "hand on", "went without"), and the spoken cues as short as they can be. Each sentence
// below was reworded from the English on the left; every one of DC's languages has the new English, with the same
// {places}, and none still holds the old (lib/i18n.test.ts checks that each Go and Ride phrase has a translation).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ES } from "../i18n/es.ts";
import { LANGUAGES } from "./i18n.ts";
import { CUE_SHEET_SAID, OFF_ROUTE_SAID, REPLAN_FAILED, REPLAN_REJOIN, START_REACHED_SAID } from "./navigate.ts";
import { rideStayPausedSaid, roamStayPausedSaid } from "./ridePause.ts";
import { RESTART_AUTO_SAID } from "./rideStops.ts";
import { WAKE_LOST, WAKE_UNAVAILABLE } from "./rideOutput.ts";
import { DETOUR_HELP } from "./nearest.ts";
import { LEADING_SAID } from "./rideGroup.ts";
import { BROADCAST_NO_LEAD, BROADCAST_RIDE_NO_LEAD } from "./sharedRoutes.ts";
import { MY_GO_NOT_SAVED } from "./myGo.ts";
import { COMPUTER_LEAD } from "./startOnComputer.ts";

/** Before -> after, as said or shown. */
const REWORDED: readonly (readonly [string, string, string])[] = [
  ["Ride paused at your destination to save battery. It carries on when you ride off, or press Resume.", "Ride paused at your destination to save battery. It starts again when you move, or press Resume.", rideStayPausedSaid(true)],
  ["Ride paused at your destination to save battery. Press Resume to carry on.", "Ride paused at your destination to save battery. Press Resume to continue.", rideStayPausedSaid(false)],
  ["Roam paused to save battery. It carries on when you ride off, or press Resume.", "Roam paused to save battery. It starts again when you move, or press Resume.", roamStayPausedSaid(true)],
  ["Roam paused to save battery. Press Resume to carry on.", "Roam paused to save battery. Press Resume to continue.", roamStayPausedSaid(false)],
  ["At the start of the ride. Ride on.", "You are at the start of the ride.", START_REACHED_SAID],
  ["Riding on with the stops as marked.", "Continuing with the stops as marked.", RESTART_AUTO_SAID],
  ["Off the planned route; finding a new way.", "Off the planned route. Finding a new way.", OFF_ROUTE_SAID],
  ["No new route was found; the planned route is still shown.", "No new route found. The planned route is still shown.", REPLAN_FAILED],
  ["No new route was found; follow the way back to the planned route.", "No new route found. Ride back to the planned route.", REPLAN_REJOIN],
  ["GPS is still weak: the turns ahead are shown as a list, next turn first.", "GPS is still weak. The next turns are shown in a list.", CUE_SHEET_SAID],
  [
    "This browser cannot keep the screen on. Keep your screen on yourself for this ride.",
    "This browser cannot keep the screen on. Set your phone to keep it on for this ride.",
    WAKE_UNAVAILABLE,
  ],
  [
    "The screen may now turn off: the browser stopped keeping it on. Keep your screen on yourself for this ride.",
    "The screen may turn off now. Set your phone to keep it on for this ride.",
    WAKE_LOST,
  ],
  [
    "Detour here re-plans the ride from where you are through that place and on along the rest of the ride.",
    "Detour here plans a new route from where you are. It goes to that place, then back to the rest of your ride.",
    DETOUR_HELP,
  ],
  [
    "You lead this ride: those who open your link follow your dot while the app is open.",
    "You lead this ride. People who open your link can follow your dot while the app is open.",
    LEADING_SAID,
  ],
  [
    "The link went without you as its leader, so the ride did not start. Press Start to ride.",
    "The link was shared without you as its leader. The ride did not start. Press Start to ride.",
    BROADCAST_NO_LEAD,
  ],
  ["The link went without you as its leader. Press Share live to try again.", "The link was shared without you as its leader. Press Share live to try again.", BROADCAST_RIDE_NO_LEAD],
  ["My Go was not saved to your account; try again shortly. It still applies here.", "My Go was not saved to your account. Try again soon. It still works on this device.", MY_GO_NOT_SAVED],
  [
    "Start ride gives turn-by-turn directions as you ride, for a phone on your bike. On a computer it may not make sense.",
    "Start ride gives turn-by-turn directions as you ride. It is made for a phone on your bike, not a computer.",
    COMPUTER_LEAD,
  ],
];

/** Shown from .tsx screens (read as source: the test runner does not load JSX) and from a built ride trip. */
const IN_SOURCE: readonly (readonly [string, string, string])[] = [
  ["../RideMode.tsx", "Ride paused while the page was in the background. Press Resume to carry on.", "Ride paused while the page was in the background. Press Resume to continue."],
  ["../RoamMode.tsx", "Roam paused while the page was in the background. Press Resume to carry on.", "Roam paused while the page was in the background. Press Resume to continue."],
  ["./rideTrip.ts", "At the start of the ride. Ride on.", "You are at the start of the ride."],
];

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const catalogOf = async (lang: string): Promise<Record<string, string>> =>
  lang === "es" ? ES : ((await import(`../i18n/${lang}.ts`)) as { CATALOG: Record<string, string> }).CATALOG;

test("Ride and Go say the plain wording, not the idioms and joined sentences it replaced (the owner, 2026-11-08)", () => {
  for (const [, after, said] of REWORDED) assert.equal(said, after);
  for (const [path, before, after] of IN_SOURCE) {
    const text = src(path);
    assert.ok(text.includes(`t(${JSON.stringify(after)})`), `${path}: ${after}`);
    assert.ok(!text.includes(JSON.stringify(before)), `${path} still has: ${before}`);
  }
});

test("each of DC's languages has each reworded sentence, and none keeps the old English", async () => {
  const pairs = [...REWORDED.map(([before, after]) => [before, after] as const), ...IN_SOURCE.map(([, before, after]) => [before, after] as const)];
  for (const lang of LANGUAGES.filter((l) => l !== "en")) {
    const catalog = await catalogOf(lang);
    for (const [before, after] of pairs) {
      assert.ok(after in catalog && catalog[after].trim() !== "", `${lang}: ${after}`);
      assert.ok(!(before in catalog), `${lang} still has: ${before}`);
    }
  }
});

test("a reworded sentence keeps one idea to a sentence: no semicolons, and no 'carry on', 'ride off' or 'Ride on'", () => {
  const all = [...REWORDED.map(([, after]) => after), ...IN_SOURCE.map(([, , after]) => after)];
  for (const after of all) assert.doesNotMatch(after, /;|\bcarr(?:y|ies) on\b|\bride off\b|\bRid(?:e|ing) on\b|\bhand on\b|\bwent without\b/i, after);
});
