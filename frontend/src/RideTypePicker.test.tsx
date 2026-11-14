// Plan's ride type picker, as the rider sees it: rendered (testSupport/render.ts), not read as source. Replaces the
// source-text checks of the picker in passengersName.test.ts and cargoLoadsGrid.test.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { RideTypePicker } from "./RideTypePicker.tsx";
import { CARRYINGS, startDials, type Dials } from "./lib/dials.ts";
import type { PresetId } from "./lib/presets.ts";

async function picker(preset: PresetId = "default", dials: Dials = startDials(preset)) {
  const chosen: Array<{ preset: PresetId; dials: Dials }> = [];
  const screen = await render(<RideTypePicker preset={preset} dials={dials} onChoose={(p, d) => chosen.push({ preset: p, dials: d })} />);
  return { screen, chosen };
}

test("one button shows the ride type in use, and Change opens the ride types", async () => {
  const { screen } = await picker("default");
  assert.equal(screen.all("dialog").length, 0, "closed at first");
  const opener = screen.button(/^Default.*Change$/);
  assert.equal(opener.getAttribute("aria-haspopup"), "dialog");
  await click(opener);
  assert.ok(screen.dialog("Choose a ride type"));
});

test("Cargo Bike's loads are a group named for cargo or passengers, each button named by its label", async () => {
  const { screen } = await picker("default");
  await click(screen.button(/Change$/));
  const loads = screen.get("group", "Cargo Bike: cargo or passengers");
  const names = [...loads.querySelectorAll("button")].map((b) => b.textContent ?? "");
  for (const load of CARRYINGS) assert.ok(names.some((n) => n.startsWith(load.label)), load.label);
});

test("each load shows its short summary, and a screen reader hears the full hint once", async () => {
  const { screen } = await picker("default");
  await click(screen.button(/Change$/));
  const passengers = CARRYINGS.find((c) => c.id === "people")!;
  const button = screen.button(new RegExp(`^${passengers.label}`));
  assert.equal(button.querySelector('[aria-hidden="true"]')?.textContent, passengers.summary, "the summary shows");
  assert.equal(button.textContent?.split(passengers.hint).length, 2, "the full hint is there once, for the screen reader");
});

test("choosing Cargo with passengers chooses Cargo Bike carrying people, and closes the ride types", async () => {
  const { screen, chosen } = await picker("default");
  await click(screen.button(/Change$/));
  await click(screen.button(/^Cargo with passengers/));
  assert.equal(chosen.length, 1);
  assert.equal(chosen[0].preset, "cargo");
  assert.equal(chosen[0].dials.carrying, "people");
  assert.equal(screen.all("dialog").length, 0);
});

test("the button names the load in use in the interface's words", async () => {
  const { screen } = await picker("cargo", startDials("cargo", "people"));
  assert.match(screen.button(/Change$/).textContent ?? "", /, cargo with passengers/);
  assert.doesNotMatch(screen.text(), /carrying people/i);
});
