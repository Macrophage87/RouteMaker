import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import { dotsKey, dotsOffScreen, everyoneFrame, everyoneShown, everyoneStep, openBox, type EveryoneState } from "./seeEveryone.ts";

// A flat screen: one degree is 100 px, longitude to the right, latitude up.
const toScreen = (at: LonLat) => ({ x: at[0] * 100, y: 1000 - at[1] * 100 });

test("the open map is the map less the ride's panels", () => {
  assert.deepEqual(openBox(400, 800, { top: 160, bottom: 120, left: 40, right: 90 }), { left: 40, top: 160, right: 310, bottom: 680 });
});

test("See everyone is offered only when a dot is out of the open map", () => {
  const open = openBox(400, 800, { top: 160, bottom: 120, left: 40, right: 90 });
  // Every dot in the open part: nothing to offer.
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
  // Only shown while needed: a dot out of view as the map follows the rider, or the view on.
  assert.match(read("../app/useSeeEveryone.ts"), /shown: everyoneShown\(state, any, follow\)/);
  assert.match(read("../app/useSeeEveryone.ts"), /if \(follow\) dispatch\(\{ kind: "following" \}\);/);
  assert.match(read("../SeeEveryoneButton.tsx"), /if \(!everyone\?\.shown\) return null;/);
  const { readdirSync } = await import("node:fs");
  for (const file of readdirSync(new URL("../i18n/", import.meta.url))) {
    const catalog = read(`../i18n/${file}`);
    for (const phrase of ["See everyone on the ride", "Everyone"]) assert.match(catalog, new RegExp(`"${phrase}":`), `${file}: ${phrase}`);
  }
});

test("the view: offered when a dot is out of view, on by a press, kept on screen as it goes off", () => {
  let s: EveryoneState = { on: false, offScreen: false };
  // Every dot in view while following: nothing offered.
  assert.equal(everyoneShown(s, true, true), false);
  s = everyoneStep(s, { kind: "checked", offScreen: true });
  assert.equal(everyoneShown(s, true, true), true);
  // Pressed: on (the map stops following); framed, its check finds every dot in view, and it stays shown, pressed.
  s = everyoneStep(s, { kind: "press" });
  s = everyoneStep(s, { kind: "checked", offScreen: false });
  assert.deepEqual(s, { on: true, offScreen: false });
  assert.equal(everyoneShown(s, true, false), true);
  // Pressed again: off, and still shown as the map goes back to the rider (never gone under the press)...
  s = everyoneStep(s, { kind: "press" });
  assert.equal(everyoneShown(s, true, true), true);
  // ...until the follow camera's next move checks: every dot in view now, so it goes.
  s = everyoneStep(s, { kind: "checked", offScreen: false });
  assert.equal(everyoneShown(s, true, true), false);
});

test("the view ends with Where am I? or the idle recentre, a move by hand, or the last dot gone", () => {
  const on: EveryoneState = { on: true, offScreen: false };
  assert.deepEqual(everyoneStep(on, { kind: "following" }), { on: false, offScreen: true });
  assert.equal(everyoneStep(on, { kind: "hand-move" }).on, false);
  // Moved by hand, the map does not follow: nothing offered until it does again.
  assert.equal(everyoneShown(everyoneStep({ on: true, offScreen: true }, { kind: "hand-move" }), true, false), false);
  assert.deepEqual(everyoneStep(on, { kind: "dots-gone" }), { on: false, offScreen: false });
  assert.equal(everyoneShown(on, false, false), false);
  // Following already (off): following changes nothing.
  const off: EveryoneState = { on: false, offScreen: false };
  assert.equal(everyoneStep(off, { kind: "following" }), off);
});
