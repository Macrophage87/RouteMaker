// OWNER-DECISIONS 241, 2026-10-03: "Cargo with people yes. In general, even adults wouldn't
// enjoy more stressful roads if they aren't in control of the ride. Let's also call it
// passengers, as people bring dogs too." The rider-visible name is "Cargo with passengers"
// (it was "carrying people"); the id, "people", is what links, saved plans and the API carry,
// so it does not change. This holds the new name in the interface, the old one out of every
// string a rider can see or hear, and the id where it was.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { CARRYINGS, carryingWords, startDials } from "./lib/dials.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { PRESETS } from "./lib/presets.ts";
import { rideText } from "./lib/gpxText.ts";

const srcDir = fileURLToPath(new URL("./", import.meta.url));

/** Every non-test source file the interface is made of, with its text. */
function interfaceSources(dir: string = srcDir): Array<{ path: string; text: string }> {
  const out: Array<{ path: string; text: string }> = [];
  for (const name of readdirSync(dir)) {
    const path = `${dir}${name}`;
    if (statSync(path).isDirectory()) {
      if (name !== "node_modules" && name !== "rail-data") out.push(...interfaceSources(`${path}/`));
    } else if (/\.(ts|tsx|js|mjs|css|html|json)$/.test(name) && !/\.test\.(ts|mjs)$/.test(name)) {
      out.push({ path, text: readFileSync(path, "utf8") });
    }
  }
  out.push({ path: "index.html", text: readFileSync(new URL("../index.html", import.meta.url), "utf8") });
  return out;
}

const OLD_NAME = /carrying[\s_-]+people/i;

test("the interface's source never says 'carrying people' again", () => {
  const sources = interfaceSources();
  assert.ok(sources.length > 50, "the scan found the interface's files");
  const found = sources.filter((s) => OLD_NAME.test(s.text)).map((s) => s.path);
  assert.deepEqual(found, []);
});

test("the load choice is named Cargo with passengers, and its id is still 'people'", () => {
  const load = CARRYINGS.find((c) => c.id === "people");
  assert.equal(load?.label, "Cargo with passengers");
  assert.deepEqual(CARRYINGS.map((c) => c.id), ["cargo", "people"]);
  assert.doesNotMatch(JSON.stringify(CARRYINGS), OLD_NAME);
  assert.match(load?.hint ?? "", /pets/, "dogs are passengers too");
});

test("a sentence names it as the label does, never as 'carrying people'", () => {
  assert.equal(carryingWords("people"), "cargo with passengers");
  assert.equal(carryingWords("cargo"), "carrying cargo");
  const said = rideText({
    preset: "cargo",
    dials: { stress: 80, hills: -60, when: "weekend", carrying: "people", assist: false },
  });
  assert.match(said, /; cargo with passengers\./);
  assert.doesNotMatch(said, OLD_NAME);
});

test("the Cargo Bike card's words cover passengers", () => {
  const card = PRESETS.find((p) => p.id === "cargo");
  assert.match(card?.description ?? "", /cargo or with passengers/);
  assert.doesNotMatch(card?.description ?? "", OLD_NAME);
});

test("the picker's group is named for cargo or passengers, and the load buttons use the labels", () => {
  const picker = readFileSync(new URL("./RideTypePicker.tsx", import.meta.url), "utf8");
  assert.match(picker, /aria-label=\{`\$\{option\.label\}: cargo or passengers`\}/);
  assert.match(picker, /\{load\.label\}/);
  assert.match(picker, /carrying\.label\.toLowerCase\(\)/);
});

test("links and saved plans still say people: the id is the same", () => {
  const points: [number, number][] = [[-77.04, 38.91], [-77.01, 38.89]];
  const hash = encodePlan(points, "cargo", startDials("cargo", "people"));
  assert.match(hash, /carrying=people/);
  assert.equal(decodePlan(hash).dials?.carrying, "people");
  const old = "#p=-77.04000,38.91000;-77.01000,38.89000&preset=cargo&v=2&stress=80&hills=-60&carrying=people";
  assert.equal(decodePlan(old).dials?.carrying, "people");
});
