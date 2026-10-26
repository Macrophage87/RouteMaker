// Cargo Bike's two choices in Plan's ride type dialog (Stephen 2026-10-25, "Fill this space"): the card takes
// two grid rows so the next ride type moves up beside the choices; each choice shows a few words, and a screen
// reader hears the full sentence once.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CARRYINGS } from "./lib/dials.ts";

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
// node --test runs no .tsx, so the picker is read as source, as passengersName.test.ts does.
const picker = readFileSync(new URL("./RideTypePicker.tsx", import.meta.url), "utf8");

test("each load has a short summary, shorter than its full hint", () => {
  for (const load of CARRYINGS) {
    assert.ok(load.summary.length > 0 && load.summary.length < load.hint.length, load.id);
  }
});

test("the Cargo Bike card spans two rows of the dialog's grid, on a subgrid", () => {
  const rule = css.match(/\.ride-types \.ride-type-card\.with-loads \{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /grid-row: span 2/);
  assert.match(rule, /grid-template-rows: subgrid/);
  assert.match(css, /\.ride-type-loads button \{[^}]*align-content: start/);
});

test("the choices show the summary hidden from screen readers, which hear the full hint once", () => {
  assert.match(picker, /carries\(option\.id\) && "with-loads"/);
  const loads = picker.slice(picker.indexOf('className="ride-type-loads"'));
  assert.match(loads, /\{full \? \(\s*<span className="hint">\{load\.hint\}<\/span>/);
  assert.match(loads, /<span className="hint" aria-hidden="true">\s*\{load\.summary\}\s*<\/span>\s*<span className="visually-hidden">\{load\.hint\}<\/span>/);
});
