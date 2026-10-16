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

test("the image is an iPhone Pro's portrait screen, the top 28% and bottom 12% kept for the lock screen", () => {
  assert.equal(LOCK_WIDTH, 1179);
  assert.equal(LOCK_HEIGHT, 2556);
  assert.equal(CLEAR_TOP, 716);
  assert.equal(CLEAR_BOTTOM, 307);
});

test("one image for a short route: every line clear of both bands and inside the width", () => {
  const pages = lockScreenLayout(sampleRoute(), measure);
  assert.equal(pages.length, 1);
  assert.equal(pages[0].part, null);
  assert.equal(pages[0].cues, cueRows(sampleRoute(), "strip").length);
  for (const l of pages[0].lines) {
    assert.ok(l.y - l.px >= CLEAR_TOP, `${l.text} in the clock's band`);
    assert.ok(l.y <= LOCK_HEIGHT - CLEAR_BOTTOM, `${l.text} in the controls' band`);
    assert.ok(l.x >= 0 && l.x + measure(l.text, l.px, l.weight) <= LOCK_WIDTH, `${l.text} off the side`);
  }
  const texts = pages[0].lines.map((l) => l.text);
  // Title and distance small at the top, the credits at the bottom, the cues large between.
  assert.equal(texts[0], "Default route, 1.9 mi (3.0 km)");
  assert.ok(texts.includes("17th St NW") && texts.includes("mi (0.5 km)") && texts.includes("Avoid-rated"));
  const credit = pages[0].lines.filter((l) => /Route data/.test(l.text));
  assert.equal(credit.length, 1);
  const cueLines = pages[0].lines.filter((l) => l.px >= 60);
  assert.ok(cueLines.every((l) => l.y > pages[0].cueTop && l.y <= pages[0].cueBottom));
  assert.ok(credit[0].y > Math.max(...cueLines.map((l) => l.y)));
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
    assert.ok(p.cues >= 1);
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
