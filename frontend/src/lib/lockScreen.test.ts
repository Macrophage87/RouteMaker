// The cue sheet as a phone lock-screen image (lib/lockScreen.ts): the layout keeps the clock's band at the top and
// the controls' band at the bottom clear, splits a long route into numbered images, and names no place.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { DescriptionEntry } from "./api.ts";
import { cueRows } from "./cueSheetPdf.ts";
import {
  CLEAR_BOTTOM,
  CLEAR_TOP,
  LOCK_HEIGHT,
  LOCK_WIDTH,
  lockScreenFileNames,
  lockScreenLayout,
  lockCancelledLine,
  lockPartButton,
  lockPartLine,
  lockScreenLine,
  lockSharedLine,
  wrapPx,
  type Measure,
} from "./lockScreen.ts";
import { sampleRoute } from "./courseRoute.test.fixture.ts";

/** A stand-in for the canvas: every character about half its size wide, a little more in bold. */
const measure: Measure = (text, px, weight) => Array.from(text).length * px * (weight === 700 ? 0.6 : 0.52);

function longRoute(turns: number) {
  const base = sampleRoute();
  const line = Array.from({ length: 3001 }, (_, i) => [base.geometry.coordinates[0][0] + i * 0.0001156, base.geometry.coordinates[0][1]] as [number, number]);
  const description = Array.from({ length: turns }, (_, k) => ({
    kind: "stretch",
    from_m: k * (29_000 / turns),
    to_m: (k + 1) * (29_000 / turns),
    from_mi: 0,
    to_mi: 0,
    street: `Street ${k} Northwest`,
    tier: 1,
    facility: null,
    turn: { movement: k % 2 ? "left" : "right", onto: `Street ${k} Northwest`, control: null, severity: null },
    text: `x: Turn onto Street ${k} Northwest.`,
  })) as DescriptionEntry[];
  return sampleRoute({ geometry: { type: "LineString", coordinates: line }, distance_m: 30000, description });
}

test("the image is an iPhone Pro's portrait screen, the top 20% and bottom 7% kept for the lock screen", () => {
  assert.equal(LOCK_WIDTH, 1179);
  assert.equal(LOCK_HEIGHT, 2556);
  assert.equal(CLEAR_TOP, 511);
  assert.equal(CLEAR_BOTTOM, 179);
});

test("a short route's cues on one image, the credits on a second: every line clear of both bands and inside the width", () => {
  const route = sampleRoute();
  const pages = lockScreenLayout(route, measure);
  assert.equal(pages.length, 2);
  assert.equal(pages[0].part, "Part 1 of 2");
  assert.equal(pages[0].cues, cueRows(route, "strip").length);
  for (const l of pages.flatMap((p) => p.lines)) {
    assert.ok(l.y - l.px >= CLEAR_TOP, `${l.text} in the clock's band`);
    assert.ok(l.y <= LOCK_HEIGHT - CLEAR_BOTTOM, `${l.text} in the controls' band`);
    assert.ok(l.x >= 0 && l.x + measure(l.text, l.px, l.weight) <= LOCK_WIDTH, `${l.text} off the side`);
  }
  const texts = pages[0].lines.map((l) => l.text);
  // Title and distance small at the top, the cues large under them.
  assert.equal(texts[0], "Default route, 1.9 mi (3.0 km)");
  assert.ok(texts.includes("17th St NW") && texts.includes("mi") && !texts.slice(2).some((t) => /km/.test(t)) && texts.includes("Avoid-rated"));
  assert.ok(!pages[0].lines.some((l) => /Route data/.test(l.text)));
  const cueLines = pages[0].lines.filter((l) => l.px >= 56);
  assert.ok(cueLines.every((l) => l.y > pages[0].cueTop && l.y <= pages[0].cueBottom));
  assert.ok(!JSON.stringify(pages).includes("Home"));
});

test("a long route is split into numbered images, every cue on one of them once, in order, none in the bands", () => {
  const route = longRoute(60);
  const pages = lockScreenLayout(route, measure);
  assert.ok(pages.length >= 3, `${pages.length} images`);
  assert.equal(
    pages.reduce((n, p) => n + p.cues, 0),
    cueRows(route, "strip").length,
  );
  pages.forEach((p, i) => {
    assert.equal(p.part, `Part ${i + 1} of ${pages.length}`);
    assert.ok(p.lines.some((l) => l.text === p.part));
    assert.ok(p.cues >= 1 || i === pages.length - 1);
    for (const l of p.lines) assert.ok(l.y - l.px >= CLEAR_TOP && l.y <= LOCK_HEIGHT - CLEAR_BOTTOM, l.text);
    assert.ok(Math.max(...p.rules) <= p.cueBottom);
  });
  const roads = pages.flatMap((p) => p.lines.map((l) => /^St (\d+) NW$/.exec(l.text)?.[1]).filter(Boolean).map(Number));
  // The start is on the first street, then each turn.
  assert.deepEqual(roads, [0, ...Array.from({ length: 60 }, (_, k) => k)]);
});

test("the images are named as the GPX export is, numbered when there are more than one", () => {
  assert.deepEqual(lockScreenFileNames(sampleRoute(), 1), ["routemaker-default-1_9mi-lock.png"]);
  assert.deepEqual(lockScreenFileNames(sampleRoute(), 2), ["routemaker-default-1_9mi-lock-1-of-2.png", "routemaker-default-1_9mi-lock-2-of-2.png"]);
  assert.equal(lockScreenLine([{ cues: 7 }]), "Cue sheet image: 7 cues on one image, for a phone lock screen.");
});

test("wrapping by pixels never loops on a glyph wider than the line", () => {
  assert.deepEqual(wrapPx("Connecticut Ave NW", 60, 400, 400, measure), ["Connecticut", "Ave NW"]);
  assert.deepEqual(wrapPx("WW", 100, 700, 10, measure), ["W", "W"]);
});

test("several images: the line says only what was saved or sent, and the button names the next part", () => {
  assert.equal(lockPartButton(1, 6), "Download part 2 of 6");
  assert.equal(lockPartLine(1, 6, 40), "Cue sheet image: part 1 of 6 saved (40 cues on 6 images). Press Download part 2 of 6 for the next.");
  assert.equal(lockPartLine(6, 6, 40), "Cue sheet image: part 6 of 6 saved (40 cues on 6 images). All 6 are saved.");
  assert.equal(lockSharedLine(3, 20), "Cue sheet image: 20 cues on 3 images, Part 1 of 3 to Part 3 of 3, sent to the share sheet together.");
  assert.equal(lockCancelledLine(3), "Cue sheet image: sharing cancelled, nothing saved. Press Download part 1 of 3 to save them one at a time.");
});

test("every cue has its picture beside it, and a stop is listed by its name and number", () => {
  const named = new Map([[1, "Coffee stop"]]);
  const pages = lockScreenLayout(sampleRoute(), measure, [], named);
  const rows = cueRows(sampleRoute(), "strip", [], named);
  const arrows = pages.flatMap((p) => p.arrows);
  assert.deepEqual(arrows.map((a) => a.arrow), rows.map((r) => r.arrow));
  assert.equal(arrows[0].arrow.kind, "start");
  assert.equal(arrows[arrows.length - 1].arrow.kind, "finish");
  assert.ok(arrows.some((a) => a.arrow.kind === "turn" && a.arrow.moves[0] === "left"));
  // Each picture sits inside its own row, clear of the miles and the words.
  for (const p of pages) {
    p.arrows.forEach((a, i) => {
      assert.ok(a.y >= p.rules[i] && a.y + a.size <= p.rules[i + 1], `picture ${i} outside its row`);
      assert.ok(a.x >= 56 + 230 - 20 && a.x + a.size <= LOCK_WIDTH);
    });
  }
  const texts = pages.flatMap((p) => p.lines.map((l) => l.text));
  assert.ok(texts.includes("Coffee stop") && texts.includes("Stop 1"));
  assert.ok(arrows.some((a) => a.arrow.kind === "stop" && a.arrow.number === 1));
  // Without its name, the stop is "Stop 1".
  const plain = lockScreenLayout(sampleRoute(), measure).flatMap((p) => p.lines.map((l) => l.text));
  assert.ok(plain.includes("Stop 1") && !plain.includes("Coffee stop"));
});

test("splits at stops only where the cues do not fit on one image: each leg its own, the stop on both", () => {
  // The owner, 2026-11-10: "Have splits at stops ... Unless it would fit in one ... The stop on the first page will be
  // repeated on the next".
  // The sample's cues fit on one image (the credits on their own after it): no split at its stop.
  const fits = lockScreenLayout(sampleRoute(), measure);
  assert.equal(fits.length, 2);
  const base = longRoute(16);
  const at = 8 * (29_000 / 16);
  const route = { ...base, description: [...base.description.slice(0, 8), { kind: "via", from_m: at, to_m: at, from_mi: 0, to_mi: 0, via: 1, text: "Stop 1." } as DescriptionEntry, ...base.description.slice(8)] };
  const pages = lockScreenLayout(route, measure);
  assert.ok(pages.length >= 2);
  const kinds = pages.map((p) => p.arrows.map((a) => a.arrow.kind));
  const ends = kinds.findIndex((k) => k[k.length - 1] === "stop");
  assert.ok(ends >= 0, "a page ends at the stop");
  assert.equal(kinds[ends + 1][0], "stop");
  assert.ok(kinds.slice(0, ends + 1).flat().filter((k) => k === "stop").length === 1);
  // The stop is counted once.
  assert.equal(pages.reduce((n, p) => n + p.cues, 0), cueRows(route, "strip").length);
});

test("a mile figure of 100 or more stays on one line", () => {
  // One turn at the start: the finish is about 150 mi on.
  const base = longRoute(1);
  // The same line stretched eightfold: about 150 mi.
  const line = base.geometry.coordinates.map(([lon, lat], i) => [lon + i * 0.0001156 * 7, lat] as [number, number]);
  const description = base.description.map((e) => ({ ...e, from_m: e.from_m * 8, to_m: e.to_m * 8 }));
  const pages = lockScreenLayout({ ...base, geometry: { type: "LineString", coordinates: line }, distance_m: 240_000, description }, measure);
  const texts = pages.flatMap((p) => p.lines.map((l) => l.text));
  assert.ok(texts.some((t) => /^1\d\d\.\d$/.test(t)), texts.join("|"));
  assert.ok(!texts.some((t) => /^1\d\d\.$/.test(t)));
});

test("the credits have an image of their own, last, a source to a line", () => {
  // The owner, 2026-11-10: "Have credits on the final image in the set, own set of lines" ... "let it go on an
  // additional one ... or just make that the default, so they are readable".
  for (const route of [sampleRoute(), longRoute(60)]) {
    const pages = lockScreenLayout(route, measure);
    assert.ok(pages.length >= 2);
    for (const p of pages.slice(0, -1)) assert.ok(!p.lines.some((l) => /Route data|OpenStreetMap|Planned with/.test(l.text)));
    const last = pages[pages.length - 1];
    assert.equal(last.cues, 0);
    assert.equal(last.part, `Part ${pages.length} of ${pages.length}`);
    const texts = last.lines.map((l) => l.text);
    assert.deepEqual(texts.slice(-4), ["Route data:", "© OpenStreetMap contributors (ODbL)", "USGS 3DEP", "Planned with RouteMaker."]);
    assert.ok(last.lines.filter((l) => l.text === "USGS 3DEP").every((l) => l.px >= 36 && l.y <= LOCK_HEIGHT - CLEAR_BOTTOM));
  }
});

test("the big figure is the distance from the cue before; the distance since the start is on the right", () => {
  // The owner, 2026-11-10: "put the total distance on the other side ... Distance since start".
  const pages = lockScreenLayout(sampleRoute(), measure);
  const lines = pages[0].lines;
  const rows = cueRows(sampleRoute(), "strip");
  const finish = rows[rows.length - 1];
  const before = rows[rows.length - 2];
  const legMi = ((finish.atM - before.atM) / 1609.344).toFixed(1);
  const totalMi = (finish.atM / 1609.344).toFixed(1);
  assert.ok(lines.some((l) => l.text === legMi && l.px === 80));
  const total = lines.find((l) => l.text === `${totalMi} mi`);
  assert.ok(total && total.x + measure(total.text, total.px, total.weight) <= LOCK_WIDTH - 56 + 1);
  assert.equal(lines.filter((l) => l.text === "total").length, rows.length);
});


test("a long list of credits still fits its image, in smaller type", () => {
  const route = { ...sampleRoute(), attribution: Array.from({ length: 30 }, (_, i) => `Source ${i + 1}`) };
  const pages = lockScreenLayout(route, measure);
  const last = pages[pages.length - 1];
  assert.ok(last.lines.some((l) => l.text === "Source 30"));
  for (const l of last.lines) assert.ok(l.y <= LOCK_HEIGHT - CLEAR_BOTTOM, l.text);
});
