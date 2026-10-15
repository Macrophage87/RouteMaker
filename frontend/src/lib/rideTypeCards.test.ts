// Go's More ride types as cards, each with its name and one short sentence (Stephen, 2026-10-15:
// "instead have a popout that has all these options and explains things more").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PRESETS, type PresetId } from "./presets.ts";
import { RideTypeCards } from "./rideTypeCards.ts";
import { filterRideGroups } from "./rideTypeGroups.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");

const render = (ids: readonly PresetId[], preset: PresetId) =>
  renderToStaticMarkup(createElement(RideTypeCards, { ids, preset, onPick: () => {}, idPrefix: "t" }));

test("every ride type has one short plain sentence, shorter than its full description", () => {
  for (const option of PRESETS) {
    const summary = option.summary;
    assert.ok(summary.length > 0 && summary.length <= 70, `${option.id}: ${summary.length} characters`);
    assert.match(summary, /^[A-Z][^.!?;()]*\.$/, `${option.id}: one sentence, no asides`);
    assert.ok(summary.length < option.description.length, `${option.id}: shorter than its description`);
  }
});

test("each card is one button: named by the ride type, described by its sentence", () => {
  const html = render(["default", "gravel"], "default");
  const buttons = html.match(/<button[^>]*>/g) ?? [];
  assert.equal(buttons.length, 2, "one control per card");
  assert.match(
    html,
    /<button type="button" aria-pressed="true" aria-labelledby="t-default-name" aria-describedby="t-default-about">/,
  );
  assert.match(html, /<strong id="t-default-name">Default<\/strong><span id="t-default-about" class="hint">Everyday riding on paths and quiet streets\.<\/span>/);
  assert.match(html, /aria-labelledby="t-gravel-name" aria-describedby="t-gravel-about"/);
  // Each id once, so each label and description points at exactly one element.
  const ids = [...html.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length);
});

test("the ride type in use is said, not only shown: pressed, and only that one", () => {
  const html = render(["default", "gravel", "fast"], "gravel");
  assert.equal(html.match(/aria-pressed="true"/g)?.length, 1);
  assert.equal(html.match(/aria-pressed="false"/g)?.length, 2);
  assert.match(html, /<li class="ride-type-card current"><button type="button" aria-pressed="true" aria-labelledby="t-gravel-name"/);
});

test("a name with emoji is said by its spoken name; the icon is never read", () => {
  const html = renderToStaticMarkup(
    createElement(RideTypeCards, { ids: ["bike-transit"], preset: "default", onPick: () => {}, idPrefix: "t", icon: () => "I" }),
  );
  assert.match(html, /<span class="ride-card-icon" aria-hidden="true">I<\/span>/);
  assert.match(html, /<strong id="t-bike-transit-name"><span aria-hidden="true">Own Bike \+ 🚆🚌<\/span><span class="visually-hidden">Own bike plus train or bus<\/span><\/strong>/);
});

test("the search finds a ride type by the words its card shows", () => {
  const found = filterRideGroups("parade pace").flatMap((g) => g.ids);
  assert.ok(found.includes("mass-ride"));
  assert.match(src("./rideTypeGroups.ts"), /\$\{option\.summary\}/);
});

test("Go's More ride types sheet shows the cards, not the chips", () => {
  const sheets = src("../app/Sheets.tsx");
  const go = sheets.slice(sheets.indexOf("export function RideGroupChips("), sheets.indexOf("export function RideChips("));
  assert.match(go, /<RideTypeCards ids=\{group\.ids\}/);
  assert.doesNotMatch(go, /<RideChips/);
});
