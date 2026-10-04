// OWNER-DECISIONS 321: "Make sure that the link text doesn't scream 'disability' in the
// parameters." Every link the page writes, across every ride type and option, and every
// value a link may carry for the stress palette, is scanned for words that reveal or hint
// at a disability or assistive need. Settings kept in this browser (the accessibility
// switch, the lane switch, federal land, the weight) are never in a link at all.
import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import { STARTS, WHENS, startDials, type Dials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { readFileSync } from "node:fs";
import { PALETTES, PALETTE_LINK_NAMES, neutralPaletteSearch, queryPalette, setAccessibility, setHighStressLanes } from "../stressStyle.js";
import type { LonLat } from "./geo.ts";

/** Substrings no name or value may hold, case-insensitively. */
const DENIED = [
  "blind",
  "lowvision",
  "low-vision",
  "low_vision",
  "visual",
  "impair",
  "disab",
  "accessib",
  "a11y",
  "stoker",
  "screenreader",
  "screen-reader",
  "screen_reader",
  "cvd",
  "colourblind",
  "colorblind",
  "colour-blind",
  "color-blind",
  "strong",
  "assistive",
  "deficien",
];
/** Whole tokens only: "sr" (a screen reader) would match inside other words as a substring. */
const DENIED_TOKENS = ["sr", "vi", "lv"];

/** Every name and value of a link's hash and query, as written. */
function partsOf(link: string): string[] {
  const [, query = "", hash = ""] = /^[^?#]*(?:\?([^#]*))?(?:#(.*))?$/.exec(link) ?? [];
  const out: string[] = [];
  for (const part of [query, hash]) {
    for (const [name, value] of new URLSearchParams(part)) out.push(name, value);
  }
  return out;
}

function offences(link: string): string[] {
  const found: string[] = [];
  for (const part of partsOf(link)) {
    const lower = part.toLowerCase();
    for (const word of DENIED) if (lower.includes(word)) found.push(`${word} in "${part}"`);
    for (const token of lower.split(/[^a-z0-9]+/)) if (DENIED_TOKENS.includes(token)) found.push(`token ${token} in "${part}"`);
  }
  return found;
}

test("the denylist itself catches what it is for, and not 'sr' inside a word", () => {
  assert.notDeepEqual(offences("#palette=cvd"), []);
  assert.notDeepEqual(offences("#view=accessible"), []);
  assert.notDeepEqual(offences("#sr=1"), []);
  assert.notDeepEqual(offences("?mode=Screen-Reader"), []);
  assert.deepEqual(offences("#p=1,2&preset=default&measure=1"), [], "'sr' inside a word is not the token");
  assert.deepEqual(offences("#view=read"), [], "the reading layout's flag (319-321) is neutral");
});

const POINT_SETS: LonLat[][] = [
  [],
  [[-77.04, 38.91], [-77.01, 38.89]],
  [[-77.04, 38.91], [-77.03, 38.9], [-77.02, 38.895], [-77.01, 38.89]],
  [[-77.04, 38.91], [-77.01, 38.89], [-77.04, 38.91]],
];

test("no link the page writes says anything of disability or assistive needs, for every ride type and option", () => {
  let links = 0;
  const failures: string[] = [];
  for (const preset of PRESETS) {
    const start = STARTS[preset.id];
    for (const carrying of start.carrying ? (["cargo", "people"] as const) : ([null] as const)) {
      for (const when of [null, ...WHENS.map((w) => w.id)]) {
        for (const stress of [0, 40, 70, 85, 100]) {
          for (const extras of [{}, { assist: true }, { avoidGravel: true }, { loop: true }, { targetDistanceM: 96_561 }, { avoidGravel: true, loop: true, targetDistanceM: 20_000, systemWeightKg: 93 }]) {
            for (const points of POINT_SETS) {
              const dials: Dials = { ...startDials(preset.id, carrying, when, true), stress, hills: start.seek ? 60 : -95, ...extras };
              for (const on of [false, true]) {
                setAccessibility(on, { remember: false });
                setHighStressLanes(on, { remember: false });
                const link = `https://routemaker.example/${encodePlan(points, preset.id, dials)}`;
                links += 1;
                for (const o of offences(link)) failures.push(`${preset.id}: ${o}`);
              }
            }
          }
        }
      }
    }
  }
  setAccessibility(false, { remember: false });
  setHighStressLanes(false, { remember: false });
  assert.ok(links > 1000, `${links} links`);
  assert.deepEqual([...new Set(failures)], []);
});

test("the switches kept in this browser never reach the link", () => {
  const points = POINT_SETS[1];
  const dials = startDials("mass-ride");
  const plain = encodePlan(points, "mass-ride", dials);
  try {
    setAccessibility(true, { remember: false });
    setHighStressLanes(true, { remember: false });
    assert.equal(encodePlan(points, "mass-ride", dials), plain);
  } finally {
    setAccessibility(false, { remember: false });
    setHighStressLanes(false, { remember: false });
  }
  assert.deepEqual(
    [...new URLSearchParams(plain.slice(1)).keys()].sort(),
    ["hills", "p", "preset", "stress", "v"],
    "only the plan itself",
  );
});

test("the palette's link values are neutral, and the older ones are still read, silently", () => {
  for (const [palette, name] of Object.entries(PALETTE_LINK_NAMES)) {
    assert.deepEqual(offences(`https://routemaker.example/?palette=${name}`), [], name);
    assert.equal(queryPalette(`?palette=${name}`), palette, `${name} names ${palette}`);
  }
  assert.deepEqual(Object.keys(PALETTE_LINK_NAMES).sort(), Object.keys(PALETTES).sort(), "every palette has a link name");
  assert.deepEqual(PALETTE_LINK_NAMES, { blended: "warm", twotone: "twotone", cvd: "cool" });
  // Links already shared keep working.
  assert.equal(queryPalette("?palette=cvd"), "cvd");
  assert.equal(queryPalette("?palette=blended"), "blended");
  assert.equal(queryPalette("?palette=strong"), null);
});

test("a link round-trips through the names it writes, and an old hint-carrying name changes nothing", () => {
  const points = POINT_SETS[2];
  const dials = { ...startDials("trailmaxxing"), loop: true, targetDistanceM: 50_000 };
  const plan = decodePlan(encodePlan(points, "trailmaxxing", dials));
  assert.equal(plan.preset, "trailmaxxing");
  assert.equal(plan.dials.loop, true);
  assert.deepEqual(decodePlan(`${encodePlan(points, "trailmaxxing", dials)}&a11y=1&sysweight=90`), plan);
});

test("an old link's palette value is renamed in the address bar on load, so it is not passed on (321; the release re-check's S4)", () => {
  assert.equal(neutralPaletteSearch("?palette=cvd"), "?palette=cool");
  assert.equal(neutralPaletteSearch("?palette=blended"), "?palette=warm");
  assert.equal(neutralPaletteSearch("?x=1&palette=cvd&y=2"), "?x=1&palette=cool&y=2", "only the value changes");
  for (const already of ["", "?palette=cool", "?palette=warm", "?palette=twotone", "?palette=nonsense", "?palette=__proto__", "?x=1"]) {
    assert.equal(neutralPaletteSearch(already), null, already || "(empty)");
  }
  // The renamed address names the same palette.
  for (const old of ["?palette=cvd", "?palette=blended"]) assert.equal(queryPalette(neutralPaletteSearch(old)!), queryPalette(old));
  // And no written name says anything the denylist forbids.
  for (const name of Object.values(PALETTE_LINK_NAMES)) assert.doesNotMatch(String(name), /cvd|blind|vision|access|a11y/i);
  // The page does it: App rewrites the address with replaceState, keeping the path and the plan.
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const search = neutralPaletteSearch\(window\.location\.search\);\s*if \(search !== null\) window\.history\.replaceState\(null, "", `\$\{window\.location\.pathname\}\$\{search\}\$\{window\.location\.hash\}`\);/);
});
