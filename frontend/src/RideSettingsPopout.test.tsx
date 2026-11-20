// Plan's Ride settings popup (the owner, 2026-11-20: "Have it pop out to all ride parameters"), with Waiting at lights
// and stops, Sharp turns and Fewer turns among the settings; Go keeps its settings under the line, without those three. Rendered and
// looked at as the rider sees it (testSupport/render.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, nameOf, render } from "./testSupport/render.ts";
import { RideSection } from "./app/Planner.tsx";
import { dialFields, fitDials, startDials, type Dials } from "./lib/dials.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { choose } from "./lib/rideTypeDialog.ts";
import { settingsSummary } from "./lib/rideSummary.ts";
import type { PresetId } from "./lib/presets.ts";

async function section(preset: PresetId, popout: boolean, dials: Dials = startDials(preset)) {
  const commits: Dials[] = [];
  const screen = await render(
    <RideSection preset={preset} dials={dials} choosePreset={() => {}} commitDials={(next) => commits.push(next)} route={null} typeCard={popout} popout={popout} />,
  );
  return { screen, commits };
}

/** A switch by the words of the label it sits in. */
function toggle(name: string): HTMLInputElement | undefined {
  return [...document.querySelectorAll<HTMLLabelElement>("label.toggle")].find((label) => label.textContent?.trim() === name)?.querySelector("input") ?? undefined;
}

function slider(name: string): HTMLInputElement | undefined {
  return [...document.querySelectorAll<HTMLInputElement>('input[type="range"]')].find((el) => nameOf(el) === name);
}

test("in Plan, Adjust opens every ride setting in a popup named for the ride type, and Done closes it", async () => {
  const { screen } = await section("fast", true);
  assert.equal(screen.all("dialog").length, 0, "closed at first");
  const adjust = screen.button(/^Ride settings.*Adjust$/);
  assert.equal(adjust.getAttribute("aria-haspopup"), "dialog");
  await click(adjust);
  const popup = screen.dialog("Ride settings: Fast");
  for (const name of ["Traffic", "Hills", "Waiting at lights and stops"]) assert.ok(slider(name), `${name} is in the popup`);
  assert.ok(toggle("Fewer turns"));
  assert.ok(toggle("Keep to roads, not trails"));
  await click(screen.button("Done"));
  assert.equal(popup.hasAttribute("open"), false, "Done closes it");
});

test("Waiting at lights starts at the ride type's own weight and only goes up from there", async () => {
  await section("fast", true);
  const waits = slider("Waiting at lights and stops")!;
  assert.equal(waits.getAttribute("aria-valuetext"), "2x", "Fast weighs its waits twice");
  assert.equal(waits.min, "2");
  assert.equal(waits.max, "5");
  await section("default", true);
  const own = [...document.querySelectorAll<HTMLInputElement>('input[type="range"]')].filter((el) => nameOf(el) === "Waiting at lights and stops");
  assert.equal(own.at(-1)?.getAttribute("aria-valuetext"), "1x", "Default's own is 1x");
});

test("moving Waiting at lights to 4x and ticking Fewer turns plan again with them", async () => {
  const { screen, commits } = await section("default", true);
  await click(screen.button(/Adjust$/));
  const waits = slider("Waiting at lights and stops")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(waits), "value")?.set?.call(waits, "4");
    waits.dispatchEvent(new window.Event("input", { bubbles: true }) as unknown as Event);
    waits.dispatchEvent(new window.Event("pointerup", { bubbles: true }) as unknown as Event);
  });
  assert.equal(commits.at(-1)?.waitWeight, 4);
  await click(toggle("Fewer turns")!);
  assert.equal(commits.at(-1)?.fewerTurns, true);
});

test("Go keeps its settings under the line, without Waiting at lights or Fewer turns", async () => {
  const { screen } = await section("fast", false);
  const adjust = screen.button(/Adjust$/);
  assert.equal(adjust.getAttribute("aria-expanded"), "false");
  await click(adjust);
  assert.equal(screen.all("dialog").length, 0);
  assert.ok(slider("Traffic"));
  assert.equal(slider("Waiting at lights and stops"), undefined);
  assert.equal(toggle("Fewer turns"), undefined);
});

test("the settings ride in the link, the request and the line's words, and stay through a change of ride type", () => {
  const dials: Dials = { ...startDials("default"), waitWeight: 4, fewerTurns: true };
  const plan = decodePlan(`#${encodePlan([[-77.03, 38.9], [-77.0, 38.9]], "default", dials)}`.replace("##", "#"));
  assert.equal(plan.dials?.waitWeight, 4);
  assert.equal(plan.dials?.fewerTurns, true);
  const fields = dialFields(dials);
  assert.equal(fields.wait_weight, 4);
  assert.equal(fields.fewer_turns, true);
  assert.match(settingsSummary("default", dials), /waits count 4x · fewer turns$/);
  // At or below a ride type's own weight the setting is that ride type's: not kept, not said.
  assert.equal(fitDials("road-bike", { ...dials, waitWeight: 3 }).waitWeight, undefined);
  assert.equal(fitDials("default", { ...dials, waitWeight: 9 }).waitWeight, 5);
  // Half steps (the owner, 2026-11-20: "maybe put some fractional levels too, like half").
  assert.equal(fitDials("default", { ...dials, waitWeight: 2.5 }).waitWeight, 2.5);
  assert.equal(fitDials("default", { ...dials, waitWeight: 2.3 }).waitWeight, 2.5);
  assert.doesNotMatch(settingsSummary("fast", startDials("fast")), /waits/);
  const fast = choose("fast", null, dials);
  assert.equal(fast.waitWeight, 4);
  assert.equal(fast.fewerTurns, true);
  assert.equal(choose("walk", null, dials).waitWeight, undefined, "nothing to weigh on foot");
});

// Sharp turns (the owner, 2026-11-20: "I find sharp turns pretty fun, but I hate standing at lights"): a slider of its
// own, down to 0, apart from Waiting at lights.
test("Sharp turns has its own slider from 0 to 5, starting at the ride type's own weight", async () => {
  await section("road-bike", true);
  const road = slider("Sharp turns")!;
  assert.equal(road.getAttribute("aria-valuetext"), "3x", "Road Bike weighs sharp turns three times");
  assert.equal(road.min, "0");
  assert.equal(road.max, "5");
  assert.equal(road.step, "0.5", "half steps");
  await section("default", true);
  const own = [...document.querySelectorAll<HTMLInputElement>('input[type="range"]')].filter((el) => nameOf(el) === "Sharp turns");
  assert.equal(own.at(-1)?.getAttribute("aria-valuetext"), "1x", "Default's own is 1x");
});

test("moving Sharp turns to 0 plans again with it and leaves the waits alone", async () => {
  const { screen, commits } = await section("road-bike", true);
  await click(screen.button(/Adjust$/));
  const turns = slider("Sharp turns")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(turns), "value")?.set?.call(turns, "0");
    turns.dispatchEvent(new window.Event("input", { bubbles: true }) as unknown as Event);
    turns.dispatchEvent(new window.Event("pointerup", { bubbles: true }) as unknown as Event);
  });
  assert.equal(commits.at(-1)?.sharpTurnWeight, 0);
  assert.equal(commits.at(-1)?.waitWeight, undefined);
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(turns), "value")?.set?.call(turns, "1.5");
    turns.dispatchEvent(new window.Event("input", { bubbles: true }) as unknown as Event);
    turns.dispatchEvent(new window.Event("pointerup", { bubbles: true }) as unknown as Event);
  });
  assert.equal(commits.at(-1)?.sharpTurnWeight, 1.5);
  assert.equal(turns.getAttribute("aria-valuetext"), "1.5x");
});

test("Go has no Sharp turns slider", async () => {
  const { screen } = await section("road-bike", false);
  await click(screen.button(/Adjust$/));
  assert.equal(slider("Sharp turns"), undefined);
});

test("a sharp-turn weight rides in the link, the request and the line's words; 0 included", () => {
  const dials: Dials = { ...startDials("road-bike"), sharpTurnWeight: 0, waitWeight: 5 };
  const plan = decodePlan(`#${encodePlan([[-77.03, 38.9], [-77.0, 38.9]], "road-bike", dials)}`.replace("##", "#"));
  assert.equal(plan.dials?.sharpTurnWeight, 0);
  assert.equal(dialFields(dials).sharp_turn_weight, 0);
  assert.match(settingsSummary("road-bike", dials), /sharp turns count 0x/);
  // The ride type's own weight is not kept or said; a weight out of range is brought back in.
  assert.equal(fitDials("road-bike", { ...dials, sharpTurnWeight: 3 }).sharpTurnWeight, undefined);
  assert.equal(fitDials("default", { ...dials, sharpTurnWeight: 9 }).sharpTurnWeight, 5);
  const half = { ...dials, sharpTurnWeight: 0.5 };
  assert.equal(decodePlan(`#${encodePlan([[-77.03, 38.9], [-77.0, 38.9]], "road-bike", half)}`.replace("##", "#")).dials?.sharpTurnWeight, 0.5);
  assert.match(settingsSummary("road-bike", half), /sharp turns count 0.5x/);
  assert.doesNotMatch(settingsSummary("road-bike", startDials("road-bike")), /sharp turns/);
  assert.equal(choose("default", null, dials).sharpTurnWeight, 0, "kept through a change of ride type");
  assert.equal(choose("walk", null, dials).sharpTurnWeight, undefined, "nothing to weigh on foot");
});
