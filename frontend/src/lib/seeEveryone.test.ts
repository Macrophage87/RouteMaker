import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import { dotsKey, dotsOffScreen, everyoneFrame, everyoneStep, openBox } from "./seeEveryone.ts";

// A flat screen: one degree is 100 px, longitude to the right, latitude up.
const toScreen = (at: LonLat) => ({ x: at[0] * 100, y: 1000 - at[1] * 100 });

test("the open map is the map less the ride's panels", () => {
  assert.deepEqual(openBox(400, 800, { top: 160, bottom: 120, left: 40, right: 90 }), { left: 40, top: 160, right: 310, bottom: 680 });
});

test("a point out of the open map is found (the view frames again once the rider leaves it)", () => {
  const open = openBox(400, 800, { top: 160, bottom: 120, left: 40, right: 90 });
  // Every point in the open part: nothing out of view.
  assert.equal(dotsOffScreen([[1, 5], [3, 4]], toScreen, open), false);
  // One past the side buttons, one under the ride's card, one off the map: each is out of view.
  assert.equal(dotsOffScreen([[1, 5], [3.5, 5]], toScreen, open), true);
  assert.equal(dotsOffScreen([[1, 5], [1, 9]], toScreen, open), true);
  assert.equal(dotsOffScreen([[1, 5], [-2, 5]], toScreen, open), true);
  // No dots: nothing out of view.
  assert.equal(dotsOffScreen([], toScreen, open), false);
});

test("the frame holds every dot and the rider", () => {
  assert.deepEqual(everyoneFrame([[1, 2], [3, 4]], [5, 6]), [[1, 2], [3, 4], [5, 6]]);
  assert.deepEqual(everyoneFrame([[1, 2]], null), [[1, 2]]);
});

test("the same dots in a new array keep their key; a moved dot changes it", () => {
  assert.equal(dotsKey([[1, 2], [3, 4]]), dotsKey([[1, 2], [3, 4]]));
  assert.notEqual(dotsKey([[1, 2], [3, 4]]), dotsKey([[1, 2], [3, 4.0001]]));
});

test("wired: the riders' dots reach App, the button sits on Ride's and Roam's side buttons, and every language has its words", async () => {
  const { readFileSync } = await import("node:fs");
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  const app = read("../App.tsx");
  // Both rides' groups (a route's and Roam's) say where their dots are.
  assert.equal(app.match(/onDots=\{setRideDots\}/g)?.length, 2);
  assert.match(app, /const everyone = useSeeEveryone\(\{/);
  for (const mode of ["../RideMode.tsx", "../RoamMode.tsx"]) assert.match(read(mode), /<SeeEveryoneButton everyone=\{everyone\} \/>/);
  // Always there while another rider's dot is on the map (Stephen 2026-10-30: "Always, when sharing"), never without one.
  assert.match(read("../app/useSeeEveryone.ts"), /const any = active && dots\.length > 0;/);
  assert.match(read("../app/useSeeEveryone.ts"), /return \{ shown: any, on, toggle, stop \};/);
  // While on, a change of the map's size frames everyone again.
  assert.match(read("../app/useSeeEveryone.ts"), /map\?\.on\("resize", refit\);[\s\S]*map\?\.off\("resize", refit\);/);
  assert.match(read("../app/useSeeEveryone.ts"), /if \(follow\) dispatch\(\{ kind: "following" \}\);/);
  assert.match(read("../SeeEveryoneButton.tsx"), /if \(!everyone\?\.shown\) return null;/);
  const { readdirSync } = await import("node:fs");
  for (const file of readdirSync(new URL("../i18n/", import.meta.url))) {
    const catalog = read(`../i18n/${file}`);
    for (const phrase of ["See everyone on the ride", "Everyone"]) assert.match(catalog, new RegExp(`"${phrase}":`), `${file}: ${phrase}`);
  }
});

test("the view: a press turns it on and off; Where am I?, the idle recentre, a move by hand or the last dot gone ends it", () => {
  assert.equal(everyoneStep(false, { kind: "press" }), true);
  assert.equal(everyoneStep(true, { kind: "press" }), false);
  for (const kind of ["following", "hand-move", "dots-gone"] as const) {
    assert.equal(everyoneStep(true, { kind }), false);
    assert.equal(everyoneStep(false, { kind }), false);
  }
});
