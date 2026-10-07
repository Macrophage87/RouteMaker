// The road panel's pure half (OWNER-DECISIONS 441, 441a; lib/roadInfo.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LONG_PRESS_MS,
  LONG_PRESS_SLOP_PX,
  LongPress,
  NO_ROAD,
  STREET_VIEW_NOTE,
  infoHeading,
  infoSaid,
  isInfoKey,
  segmentInfoUrl,
  shownSections,
  streetViewUrl,
  type SegmentInfo,
} from "./roadInfo.ts";

const INFO: SegmentInfo = {
  found: true,
  title: "Connecticut Avenue Northwest",
  tier: 3,
  open: true,
  osm_way_id: 101,
  distance_m: 2.1,
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
  assert.equal(
    STREET_VIEW_NOTE,
    "Opens Google Street View in a new tab; this spot is sent to Google only if you follow the link.",
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

test("the live region says the name, the stress and the access in a sentence", () => {
  assert.equal(
    infoSaid({ kind: "ready", info: INFO }),
    "Road information: Connecticut Avenue Northwest. LTS 3: For experienced cyclists. Open to bicycles.",
  );
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
