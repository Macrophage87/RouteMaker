// The road panel's pure half (OWNER-DECISIONS 441, 441a; lib/roadInfo.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_POINTS } from "./geo.ts";
import {
  LONG_PRESS_MS,
  LONG_PRESS_SLOP_PX,
  LongPress,
  NO_ROAD,
  OSM_EDIT_NOTE,
  STREET_VIEW_NOTE,
  STREET_VIEW_TEXT,
  INFO_HELP,
  infoHeading,
  infoSaid,
  isInfoKey,
  osmEditUrl,
  placeAtSpot,
  repeatsInfoAsk,
  requestAfterClose,
  spotActions,
  segmentInfoUrl,
  shownSections,
  shownSummary,
  streetViewPoint,
  streetViewUrl,
  subtitle,
  valueParts,
  wayRows,
  type SegmentInfo,
} from "./roadInfo.ts";

const INFO: SegmentInfo = {
  found: true,
  title: "Connecticut Avenue Northwest",
  tier: 3,
  open: true,
  osm_way_id: 101,
  distance_m: 2.1,
  kind: "Main road",
  summary: [
    { id: "stress", label: "Traffic stress", value: "LTS 3 · For experienced cyclists" },
    { id: "why", label: "Why", value: "30 mph, mixed traffic" },
    { id: "bikes", label: "Bikes", value: "Allowed" },
    { id: "mass", label: "Room for", value: "About 150 riders a minute" },
  ],
  attribution: ["© OpenStreetMap contributors (ODbL)"],
  sections: [
    { id: "road", heading: "Road or path", rows: [{ label: "Name", value: "Connecticut Avenue Northwest", source: "OpenStreetMap" }] },
    { id: "stress", heading: "Traffic stress", rows: [{ label: "Level", value: "LTS 3: For experienced cyclists", source: "RouteMaker classifier" }] },
    { id: "access", heading: "Bike access", rows: [{ label: "Bike access", value: "Open to bicycles", source: null }] },
    { id: "mass", heading: "Mass Ride capacity", rows: [{ label: "Usable width", value: "22 ft (6.7 m)", source: null }] },
  ],
};

test("the Street View link is Google's public URL for the spot, latitude first", () => {
  assert.equal(
    streetViewUrl([-77.0434, 38.9125]),
    "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=38.912500,-77.043400",
  );
  assert.equal(STREET_VIEW_TEXT, "Street View");
  assert.equal(STREET_VIEW_NOTE, "Opens in a new tab; Google gets this spot only if you follow the link.");
});

test("Edit in OSM opens OpenStreetMap's editor for the way, and is not offered without one", () => {
  assert.equal(osmEditUrl(INFO), "https://www.openstreetmap.org/edit?way=101");
  assert.equal(osmEditUrl({ ...INFO, osm_way_id: null }), null);
  assert.equal(osmEditUrl({ ...INFO, found: false }), null);
  assert.equal(osmEditUrl({ ...INFO, osm_way_id: -5 }), null);
  assert.equal(
    OSM_EDIT_NOTE,
    "Opens OpenStreetMap's editor for this way. Needs an OpenStreetMap account; don't copy from Google Street View.",
  );
});

test("the request carries the spot in its query only", () => {
  assert.equal(
    segmentInfoUrl("https://example.test", [-77.0434, 38.9125]),
    "https://example.test/api/segment-info?lat=38.912500&lon=-77.043400",
  );
});

test("the Mass Ride capacity shows only on the Mass Ride map", () => {
  assert.deepEqual(shownSections(INFO, false).map((s) => s.id), ["road", "stress", "access"]);
  assert.deepEqual(shownSections(INFO, true).map((s) => s.id), ["road", "stress", "access", "mass"]);
});

test("the Mass Ride room is a summary line only on the Mass Ride map", () => {
  assert.deepEqual(shownSummary(INFO, false).map((r) => r.id), ["stress", "why", "bikes"]);
  assert.deepEqual(shownSummary(INFO, true).map((r) => r.id), ["stress", "why", "bikes", "mass"]);
  assert.deepEqual(shownSummary({ ...INFO, summary: undefined }, true), [], "an older API has no summary");
});

test("the line under the heading gives the kind and where, briefly", () => {
  const ready = { kind: "ready" as const, info: INFO };
  assert.equal(subtitle(ready, "spot"), "Main road, nearest the spot you picked");
  assert.equal(subtitle(ready, "centre"), "Main road, nearest the map center");
  assert.equal(subtitle({ kind: "loading" }, "spot"), "Nearest the spot you picked");
  assert.deepEqual(valueParts("LTS 3 · For experienced cyclists"), ["LTS 3", "For experienced cyclists"]);
  assert.deepEqual(valueParts("Allowed"), ["Allowed"]);
});

test("the details give the way's id and its distance, feet first", () => {
  assert.deepEqual(wayRows(INFO), [
    { label: "OpenStreetMap way", value: "101", source: null },
    { label: "Distance from the spot", value: "10 ft (2 m)", source: null },
  ]);
});

test("the top row offers start, end and stop as the search does, each unavailable one with its reason", () => {
  const row = (count: number, loop = false) => spotActions(count, loop).map((a) => `${a.text}${a.unavailable ? ` (${a.unavailable})` : ""}`);
  assert.deepEqual(row(0), ["Set as start", "Set as end (Set a start first.)", "Add as stop (Set a start first.)"]);
  assert.deepEqual(row(1), ["Set as start", "Set as end", "Add as stop (Set an end first.)"]);
  assert.deepEqual(row(2), ["Set as start", "Set as end", "Add as stop"]);
  assert.deepEqual(row(MAX_POINTS), ["Set as start", "Set as end", `Add as stop (The route has the most points it can (${MAX_POINTS}).)`]);
  // A loop finishes at its start: no end to set, and a stop can follow the start alone.
  assert.deepEqual(row(1, true), ["Set as start", "Add as stop"]);
});

test("a top-row button places the spot as the search's choice would, and says so", () => {
  const a: [number, number] = [-77.05, 38.9];
  const b: [number, number] = [-77.0, 38.95];
  const spot: [number, number] = [-77.0434, 38.9125];
  assert.deepEqual(placeAtSpot([], spot, "start", false), { next: [spot], said: "Start set here." });
  assert.deepEqual(placeAtSpot([a, b], spot, "start", false), { next: [spot, b], said: "Start set here." });
  assert.deepEqual(placeAtSpot([a], spot, "end", false), { next: [a, spot], said: "End set here." });
  assert.deepEqual(placeAtSpot([a, b], spot, "end", false), { next: [a, spot], said: "End set here." });
  assert.deepEqual(placeAtSpot([a, b], spot, "via", false), { next: [a, spot, b], said: "Stop 1 set here." });
});

test("the help says where the summary and the details are", () => {
  assert.match(INFO_HELP, /^Right-click the map \(or press and hold on a phone\) for a short summary/);
  assert.match(INFO_HELP, /Details and sources/);
  assert.match(INFO_HELP, /press I for the road at the center/);
  // Map tools and both its actions by name (OWNER-DECISIONS 450), and the screen readers' browse mode (the a11y review's N7).
  assert.match(INFO_HELP, /open Map tools \(by the map's zoom buttons\) for Road info at map center and Add point at map center/);
  assert.match(INFO_HELP, /With NVDA or JAWS, I reaches the map only in focus mode/);
});

test("Street View opens on the road the panel describes (441o), else at the spot", () => {
  const spot: [number, number] = [-77.0434, 38.9125];
  assert.deepEqual(streetViewPoint({ ...INFO, on_way: [-77.04335, 38.91262] }, spot), [-77.04335, 38.91262]);
  assert.deepEqual(streetViewPoint({ ...INFO, on_way: undefined }, spot), spot, "an older API");
  assert.deepEqual(streetViewPoint({ ...INFO, on_way: [Number.NaN, 38.9] }, spot), spot);
  assert.deepEqual(streetViewPoint({ ...INFO, found: false, on_way: [-77, 38.9] }, spot), spot);
  assert.deepEqual(streetViewPoint(null, spot), spot, "still looking it up");
});

test("the live region says one short sentence: the name and the stress, and a closure", () => {
  assert.equal(infoSaid({ kind: "ready", info: INFO }), "Connecticut Avenue Northwest: LTS 3, for experienced cyclists.");
  const closed: SegmentInfo = {
    ...INFO,
    open: false,
    summary: [{ id: "stress", label: "Traffic stress", value: "LTS 4 · High stress: busy, fast traffic" }],
  };
  assert.equal(
    infoSaid({ kind: "ready", info: closed }),
    "Connecticut Avenue Northwest: LTS 4, high stress: busy, fast traffic. Bikes not allowed here.",
  );
  const avoid: SegmentInfo = { ...INFO, summary: [{ id: "stress", label: "Traffic stress", value: "Avoid" }] };
  assert.equal(infoSaid({ kind: "ready", info: avoid }), "Connecticut Avenue Northwest: Avoid.");
  const older: SegmentInfo = { ...INFO, summary: undefined };
  assert.equal(infoSaid({ kind: "ready", info: older }), "Connecticut Avenue Northwest: LTS 3, for experienced cyclists.");
  const none = { ...INFO, found: false, title: NO_ROAD, sections: [] };
  assert.equal(infoSaid({ kind: "ready", info: none }), "No road here.");
  assert.equal(infoHeading({ kind: "ready", info: none }), "No road here");
  assert.equal(infoSaid({ kind: "loading" }), "");
});

test("I asks for the road at the center; Ctrl+I and the like do not", () => {
  const key = (k: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) => ({
    key: k,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...mods,
  });
  assert.ok(isInfoKey(key("i")));
  assert.ok(isInfoKey(key("I")));
  assert.ok(!isInfoKey(key("i", { ctrlKey: true })));
  assert.ok(!isInfoKey(key("i", { metaKey: true })));
  assert.ok(!isInfoKey(key("j")));
});

function clock() {
  let now = 0;
  const timers: Array<{ at: number; run: () => void; id: number }> = [];
  let next = 1;
  return {
    schedule: (run: () => void, ms: number) => {
      const id = next++;
      timers.push({ at: now + ms, run, id });
      return id as unknown as ReturnType<typeof setTimeout>;
    },
    cancel: (id: ReturnType<typeof setTimeout>) => {
      const index = timers.findIndex((t) => t.id === (id as unknown as number));
      if (index >= 0) timers.splice(index, 1);
    },
    advance(ms: number) {
      now += ms;
      for (const t of timers.filter((t) => t.at <= now)) {
        timers.splice(timers.indexOf(t), 1);
        t.run();
      }
    },
  };
}

test("a finger held still fires once, at the press", () => {
  const c = clock();
  const fired: Array<{ x: number; y: number }> = [];
  const press = new LongPress((at) => fired.push(at), c.schedule, c.cancel);
  press.press(100, 200);
  press.move(103, 204);
  c.advance(LONG_PRESS_MS - 1);
  assert.equal(fired.length, 0);
  c.advance(1);
  assert.deepEqual(fired, [{ x: 100, y: 200 }]);
  assert.ok(!press.pending);
  c.advance(LONG_PRESS_MS * 2);
  assert.equal(fired.length, 1);
});

test("a pan, a lift or a second finger calls the long press off", () => {
  const c = clock();
  let fired = 0;
  const press = new LongPress(() => fired++, c.schedule, c.cancel);
  press.press(0, 0);
  press.move(LONG_PRESS_SLOP_PX + 1, 0);
  c.advance(LONG_PRESS_MS);
  assert.equal(fired, 0, "a drift past the slop is a pan");
  press.press(0, 0);
  press.cancel();
  c.advance(LONG_PRESS_MS);
  assert.equal(fired, 0, "a lift or a second finger");
});

test("a late close event ends only the request it closed, never a newer one", () => {
  const old = { point: [-77.03, 38.9] as [number, number], origin: "centre" as const };
  const newer = { point: [-77.03, 38.9] as [number, number], origin: "centre" as const };
  assert.equal(requestAfterClose(old, old), null, "the request that closed goes");
  // Escape, then I at once: the close event lands after the newer request is set.
  assert.equal(requestAfterClose(newer, old), newer, "the same spot asked again is a new request");
  assert.equal(requestAfterClose(null, old), null);
  assert.equal(requestAfterClose(newer, null), newer, "a close with nothing shown clears nothing");
});

test("only a pointer gesture repeats an ask; I straight after a right-click's panel is a new one", () => {
  assert.equal(repeatsInfoAsk("spot", 1300, 1000, 800), true, "a long press's contextmenu, 300 ms on");
  assert.equal(repeatsInfoAsk("spot", 1900, 1000, 800), false);
  assert.equal(repeatsInfoAsk("centre", 1300, 1000, 800), false, "Escape, then I, 300 ms after the right-click");
});
