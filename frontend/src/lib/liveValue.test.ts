// fe-perf-1: the rider's GPS fix and the elevation chart's scrub point in their own stores, so a fix re-renders the
// map, not App (lib/liveValue.ts, lib/rideViewKept.ts, app/LiveMap.tsx).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { liveValue } from "./liveValue.ts";
import { rideViewKept } from "./rideViewKept.ts";
import type { RideView } from "../RideMode.tsx";
import type { RouteResponse } from "./api.ts";

test("a live value tells its listeners of a change, once, and not of the same value again", () => {
  const live = liveValue<number | null>(null);
  let told = 0;
  const stop = live.subscribe(() => told++);
  live.set(1);
  live.set(1);
  assert.equal(live.get(), 1);
  assert.equal(told, 1);
  stop();
  live.set(2);
  assert.equal(told, 1, "unsubscribed");
  assert.equal(live.get(), 2);
});

const route = {} as RouteResponse;
const view = (over: Partial<RideView> = {}): RideView => ({
  route,
  other: null,
  rider: { point: [-77, 38.9], headingDeg: 90, accuracyM: 5 },
  vehicle: null,
  stops: [{ point: [-77.01, 38.91], number: 1, name: "Union Market" }],
  lettered: null,
  onLettered: undefined,
  ...over,
});

test("a new fix alone keeps the ride's view, so App does not re-render", () => {
  const was = view();
  assert.equal(rideViewKept(was, view({ rider: { point: [-77.001, 38.9], headingDeg: 92, accuracyM: 4 } })), true);
  // The stops ahead worked out again with the same stops: kept.
  assert.equal(rideViewKept(was, view({ stops: [{ point: [-77.01, 38.91], number: 1, name: "Union Market" }] })), true);
});

test("anything else the ride shows is a new view", () => {
  const was = view();
  assert.equal(rideViewKept(was, view({ route: {} as RouteResponse })), false);
  assert.equal(rideViewKept(was, view({ other: [[-77, 38.9]] })), false);
  assert.equal(rideViewKept(was, view({ stops: [] })), false, "a stop passed");
  assert.equal(rideViewKept(was, view({ stops: [{ point: [-77.01, 38.91], number: 1, name: "Other" }] })), false);
  assert.equal(rideViewKept(was, view({ lettered: [] })), false);
  assert.equal(rideViewKept(was, view({ onLettered: () => {} })), false);
  assert.equal(rideViewKept(null, was), false);
  assert.equal(rideViewKept(was, null), false);
  assert.equal(rideViewKept(null, null), true);
});

test("App keeps the rider and the scrub point out of its own state, and the map reads them from their stores", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /rideRider\.set\(view\?\.rider \?\? null\);\s*setRideViewState\(\(was\) => \(rideViewKept\(was, view\) \? was : view\)\);/);
  assert.match(app, /const \[roamRider\] = useState\(\(\) => liveValue<LiveRider>\(null\)\);/);
  assert.match(app, /const \[scrubPoint\] = useState\(\(\) => liveValue<LonLat \| null>\(null\)\);/);
  assert.doesNotMatch(app, /rideView\??\.rider/, "App reads no rider from its own state");
  assert.doesNotMatch(app, /<MapView\b/, "the map is drawn through LiveMap");
  const live = readFileSync(new URL("../app/LiveMap.tsx", import.meta.url), "utf8");
  assert.match(live, /const rider = useLiveValue\(riderFrom \?\? NO_RIDER\);\s*const scrubPoint = useLiveValue\(scrubFrom\);/);
});
