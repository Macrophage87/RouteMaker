// Barriers on a Cargo or Tandem route (backlog 2026-11-12 item 12; OWNER-DECISIONS 345): the impassable one no way
// round was found for is a warning, the others a list; a gap with no width mapped is said as unmapped; nothing is said
// on other ride types or where the answer has no barrier list.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { BarrierItem, BarrierReading, BarrierRound } from "./api.ts";
import {
  BARRIER_LEVELS,
  BARRIER_PRESETS,
  barrierFeatures,
  barrierIcon,
  barrierIconName,
  barrierList,
  barrierNote,
  barrierAvoidFor,
  barrierAvoidPoints,
  barrierCard,
  barrierMarkName,
  barrierMarks,
  toggleBarrierAvoid,
} from "./barriers.ts";
import { setCatalogForTest, setLanguageForTest } from "./i18n.ts";
import { CATALOG as FR } from "../i18n/fr.ts";

function item(
  word: BarrierItem["word"],
  over: Partial<BarrierItem> = {},
): BarrierItem {
  return {
    kind: word,
    word,
    lon: -77,
    lat: 38.9,
    width_m: null,
    width_mapped: true,
    impassable: false,
    at_m: 0,
    ...over,
  };
}

function reading(items: BarrierItem[], data = true): BarrierReading {
  return {
    data,
    counts: {},
    impassable: items.filter((i) => i.impassable).length,
    unmapped_width: 0,
    items,
  };
}

test("only Cargo and Tandem", () => {
  assert.deepEqual([...BARRIER_PRESETS], ["cargo", "tandem"]);
  const barriers = reading([item("gate")]);
  assert.equal(barrierNote({ preset: "default", barriers }), null);
  assert.notEqual(barrierNote({ preset: "tandem", barriers }), null);
});

test("the list groups each kind, counts past one, and keeps unmapped gaps apart", () => {
  const list = barrierList([
    item("gate"),
    item("bollard", { width_mapped: false }),
    item("bollard", { width_mapped: false }),
    item("bollard", { width_m: 1.3 }),
    item("stile"),
  ]);
  assert.equal(list, "stile, bollard, bollard ×2 (width not mapped), gate");
});

function round(limited: BarrierRound["limited"]): BarrierRound {
  return { rounds: 1, impassable: 1, limited, in_the_way: [] };
}

test("an impassable barrier left on the route is a warning naming only those, worded by what the round found", () => {
  const barriers = reading([item("gate"), item("stile", { impassable: true })]);
  assert.deepEqual(
    barrierNote({
      preset: "cargo",
      barriers,
      barrier_round: round("no_way_round"),
    }),
    {
      warn: true,
      text: "No way round found: stile on this route. A cargo bike or tandem may not get through.",
      short: "Barrier in the way.",
    },
  );
  assert.equal(
    barrierNote({ preset: "cargo", barriers, barrier_round: round("at_stop") })
      ?.text,
    "stile by your start, a stop or the end. A cargo bike or tandem may not get through.",
  );
  // A drawn or followed line, a first route or a round cut short never looked: said plainly.
  for (const barrier_round of [null, undefined, round("time")]) {
    assert.equal(
      barrierNote({ preset: "cargo", barriers, barrier_round })?.text,
      "stile on this route. A cargo bike or tandem may not get through.",
    );
  }
});

test("otherwise a hint listing them", () => {
  const note = barrierNote({
    preset: "cargo",
    barriers: reading([item("cycle_barrier", { width_mapped: false })]),
  });
  assert.equal(note?.warn, false);
  assert.equal(note?.text, "On this route: cycle barrier (width not mapped).");
});

test("nothing where the route has none, or where no barrier list was loaded", () => {
  assert.equal(barrierNote({ preset: "tandem", barriers: reading([]) }), null);
  assert.equal(
    barrierNote({
      preset: "tandem",
      barriers: reading([item("stile", { impassable: true })], false),
    }),
    null,
  );
  assert.equal(barrierNote({ preset: "tandem", barriers: undefined }), null);
});

test("said in the rider's language", () => {
  setCatalogForTest("fr", FR);
  setLanguageForTest("fr");
  try {
    const note = barrierNote({
      preset: "tandem",
      barriers: reading([item("steps", { impassable: true })]),
      barrier_round: round("no_way_round"),
    });
    assert.equal(
      note?.text,
      "Aucun autre chemin trouvé : marches sur cet itinéraire. Un vélo cargo ou un tandem risque de ne pas passer.",
    );
  } finally {
    setLanguageForTest("en");
  }
});

test("the map marks each barrier on a Cargo or Tandem route, red where it cannot pass", () => {
  const barriers = reading([
    item("gate"),
    item("stile", { impassable: true, lon: -77.01, lat: 38.91 }),
  ]);
  assert.deepEqual(
    barrierFeatures({ preset: "default", barriers }).features,
    [],
  );
  assert.deepEqual(
    barrierFeatures({
      preset: "cargo",
      barriers: reading([item("stile")], false),
    }).features,
    [],
  );
  const marks = barrierFeatures({ preset: "tandem", barriers }).features;
  assert.deepEqual(
    marks.map((f) => [
      f.properties.level,
      f.properties.label,
      f.geometry.coordinates,
    ]),
    [
      ["noted", "gate", [-77, 38.9]],
      ["blocked", "stile", [-77.01, 38.91]],
    ],
  );
  assert.deepEqual(BARRIER_LEVELS.map(barrierIconName), [
    "barrier-blocked",
    "barrier-noted",
    "barrier-avoided",
  ]);
});

test("the mark is an octagon with a bar: transparent corners, the bar's colour at the centre", () => {
  const icon = barrierIcon("blocked", 1, 22);
  const px = (x: number, y: number) =>
    Array.from(
      icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 4),
    );
  assert.equal(icon.width, 22);
  assert.equal(px(0, 0)[3], 0, "a corner is cut off");
  assert.deepEqual(px(11, 11).slice(0, 3), [255, 255, 255], "the white bar");
  assert.deepEqual(px(11, 5).slice(0, 3), [0xb9, 0x1c, 0x1c], "the red fill");
  // The others carry an "!" instead: told apart by shape, not colour alone.
  const noted = barrierIcon("noted", 1, 22);
  const at = (x: number, y: number) =>
    Array.from(
      noted.data.slice(
        (y * noted.width + x) * 4,
        (y * noted.width + x) * 4 + 3,
      ),
    );
  assert.deepEqual(at(11, 8), [0x11, 0x18, 0x27], "the stroke of the !");
  assert.deepEqual(
    at(6, 11),
    [0xf5, 0x9e, 0x0b],
    "amber where the bar would be",
  );
});

// "Go around" (the owner, 2026-11-13: "Put the bollard on the map, and offer them a go around.").

test("a mark's card offers Go around, except where the barrier is planned round already", () => {
  const bollard = item("bollard", { width_mapped: false });
  assert.deepEqual(barrierCard(bollard, false, true), {
    heading: "bollard (width not mapped)",
    text: "Width not mapped: it may be too narrow for your bike.",
    action: { label: "Go around", avoid: true },
  });
  assert.equal(barrierCard(item("gate"), false, true).text, "Check it fits your bike.");
  // A stile is planned round for a cargo bike or tandem anyway: no button.
  assert.equal(barrierCard(item("stile", { impassable: true }), false, true).action, null);
  // Gone round: Undo, saying whether a way round was found.
  assert.deepEqual(barrierCard(bollard, true, false), {
    heading: "bollard (width not mapped)",
    text: "Your route goes around it.",
    action: { label: "Undo: go through it", avoid: false },
  });
  assert.equal(barrierCard(bollard, true, true).text, "No way round found.");
  assert.equal(barrierMarkName(bollard), "Barrier: bollard (width not mapped)");
});

test("going around is this plan's only, one entry a barrier, and Undo takes it out", () => {
  const a = item("bollard", { lon: -77.000001, lat: 38.9 });
  const b = item("cycle_barrier", { lon: -77.01, lat: 38.91 });
  let avoid = toggleBarrierAvoid(null, "plan-1", a, true);
  avoid = toggleBarrierAvoid(avoid, "plan-1", b, true);
  avoid = toggleBarrierAvoid(avoid, "plan-1", a, true);
  assert.deepEqual(barrierAvoidPoints(barrierAvoidFor(avoid, "plan-1")), [
    [-77.01, 38.91],
    [-77.000001, 38.9],
  ]);
  // A new start or end forgets them, with the same empty list each time.
  assert.equal(barrierAvoidFor(avoid, "plan-2").length, 0);
  assert.equal(barrierAvoidFor(avoid, "plan-2"), barrierAvoidFor(null, "plan-1"));
  avoid = toggleBarrierAvoid(avoid, "plan-1", a, false);
  assert.deepEqual(barrierAvoidPoints(barrierAvoidFor(avoid, "plan-1")), [[-77.01, 38.91]]);
});

test("a gone-round barrier: hollow off the route, red where no way round was found, and the line says so", () => {
  const bollard = item("bollard", { width_mapped: false });
  const gone = item("cycle_barrier", { lon: -77.01, lat: 38.91 });
  const route = { preset: "cargo" as const, barriers: reading([bollard, item("gate", { lon: -77.02 })]) };
  assert.deepEqual(
    barrierMarks(route, [bollard, gone]).map((m) => [m.item.word, m.level, m.avoided, m.onRoute]),
    [
      ["bollard", "blocked", true, true],
      ["gate", "noted", false, true],
      ["cycle_barrier", "avoided", true, false],
    ],
  );
  // Never on another ride type.
  assert.deepEqual(barrierMarks({ preset: "default", barriers: route.barriers }, [gone]), []);
  // The route's line counts the one still in the way as in the way.
  const note = barrierNote(route, [bollard]);
  assert.equal(note?.warn, true);
  assert.match(note?.text ?? "", /^bollard \(width not mapped\) on this route/);
});

test("the gone-round mark is hollow: white inside a dark rim", () => {
  const icon = barrierIcon("avoided", 1, 22);
  const px = (x: number, y: number) =>
    Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 3));
  assert.deepEqual(px(11, 11), [255, 255, 255], "white at the centre");
  assert.deepEqual(px(11, 2), [0x37, 0x41, 0x51], "the dark rim");
});
