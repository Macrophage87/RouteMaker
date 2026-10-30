// A map card's "close" handler never asks the card for its element: MapLibre takes the element away
// before it says "close" (Popup.remove), so getElement() is undefined there and the throw, from a
// React effect's clean-up, blanked the whole page (Stephen 2026-10-25: "The website is just going
// completely black at random intervals"). The element is held when the card opens instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SOURCES = ["./MapView.tsx", "./app/mapOverlay.ts", "./climbInteraction.ts", "./railInteraction.ts"];

/** The body of each `.on("close", () => { ... })`, by matching braces. */
function closeHandlers(source: string): string[] {
  const out: string[] = [];
  for (let at = source.indexOf('.on("close"'); at >= 0; at = source.indexOf('.on("close"', at + 1)) {
    const open = source.indexOf("{", at);
    let depth = 0;
    for (let i = open; i < source.length; i += 1) {
      if (source[i] === "{") depth += 1;
      else if (source[i] === "}" && --depth === 0) {
        out.push(source.slice(open, i + 1));
        break;
      }
    }
  }
  return out;
}

test("no popup close handler reads getElement()", () => {
  let seen = 0;
  for (const name of SOURCES) {
    for (const body of closeHandlers(readFileSync(new URL(name, import.meta.url), "utf8"))) {
      seen += 1;
      assert.ok(!body.includes("getElement()"), `${name}: ${body}`);
    }
  }
  assert.ok(seen >= 4, `close handlers found: ${seen}`);
});

test("one Escape closes one thing: a map card ignores an Escape a sheet or dialog handled, and its own hands the focus back (a11y-10)", () => {
  for (const name of ["./waterInteraction.ts", "./federalInteraction.ts", "./climbInteraction.ts"]) {
    const source = readFileSync(new URL(name, import.meta.url), "utf8");
    const onKey = source.slice(source.indexOf("const onKey = (event: KeyboardEvent) => {"), source.indexOf('window.addEventListener("keydown", onKey);'));
    assert.match(onKey, /if \(event\.key === "Escape"[^)]*&& !event\.defaultPrevented\) close\(\);/, name);
  }
  for (const name of ["./waterInteraction.ts", "./federalInteraction.ts"]) {
    const source = readFileSync(new URL(name, import.meta.url), "utf8");
    assert.match(source, /if \(key\.key !== "Escape"\) return;\s*key\.preventDefault\(\);\s*close\(\);\s*map\.getCanvas\(\)\.focus\(\);/, name);
  }
});
