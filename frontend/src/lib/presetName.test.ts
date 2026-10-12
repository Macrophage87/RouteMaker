import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PresetName } from "./presetName.ts";

test("a name with emoji shows them aria-hidden and is said in words; a plain name is plain text", () => {
  assert.equal(
    renderToStaticMarkup(h(PresetName, { id: "bikeshare-transit" })),
    '<span aria-hidden="true">Bikeshare + 🚶🚆🚌</span><span class="visually-hidden">Bikeshare plus walk, train or bus</span>',
  );
  assert.equal(
    renderToStaticMarkup(h(PresetName, { id: "bike-transit", suffix: " trip" })),
    '<span aria-hidden="true">Own Bike + 🚆🚌 trip</span><span class="visually-hidden">Own bike plus train or bus trip</span>',
  );
  assert.equal(renderToStaticMarkup(h(PresetName, { id: "cargo" })), "Cargo Bike");
});

test("everywhere a ride type's name shows, it goes through PresetName or the spoken name", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  // Go's chips and the Ride sheet's, Go's ride chip, Plan's list and current type, the trip's heading.
  assert.match(read("../app/Sheets.tsx"), /<PresetName id=\{id\} \/>/);
  assert.match(read("../app/Sheets.tsx"), /<option key=\{p\.id\} value=\{p\.id\} aria-label=\{p\.spoken\}>/);
  assert.match(read("../app/RoutePanel.tsx"), /<PresetName id=\{preset\} \/>/);
  assert.match(read("../app/RoutePanel.tsx"), /said=\{`\$\{presetSaid\(preset\)\} trip`\}/);
  assert.match(read("../RideTypePicker.tsx"), /<PresetName id=\{option\.id\} \/>/);
  assert.match(read("../TransitSummary.tsx"), /<PresetName id=\{preset\} suffix=/);
  for (const file of ["../app/Sheets.tsx", "../app/RoutePanel.tsx", "../RideTypePicker.tsx", "../TransitSummary.tsx"]) {
    assert.doesNotMatch(read(file), /[^$]\{presetLabel\(/, file);
  }
});
