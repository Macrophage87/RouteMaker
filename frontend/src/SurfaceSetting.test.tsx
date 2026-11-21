// The Surface setting in Ride settings (the owner, 2026-11-21: "a surface setting: paved only, gravel, easy MTB, and then
// MTB2-4 as max"): one picker, in Plan's popup and Go's settings alike, rendered and looked at as the rider sees it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, render } from "./testSupport/render.ts";
import { RideSection } from "./app/Planner.tsx";
import { dialFields, fitDials, offersStopsAndTurns, startDials, type Dials } from "./lib/dials.ts";
import { panelView } from "./lib/dialsPanel.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { choose } from "./lib/rideTypeDialog.ts";
import { rideSummary } from "./lib/rideSummary.ts";
import { dialsComment } from "./lib/gpx.ts";
import { PRESETS, type PresetId } from "./lib/presets.ts";

async function section(preset: PresetId, popout: boolean, dials: Dials = startDials(preset)) {
  const commits: Dials[] = [];
  const screen = await render(
    <RideSection preset={preset} dials={dials} choosePreset={() => {}} commitDials={(next) => commits.push(next)} route={null} typeCard={popout} popout={popout} />,
  );
  // A test that renders more than once opens the newest.
  if (popout) await click(screen.all("button", /^Ride settings.*Adjust$/).at(-1)!);
  return { screen, commits };
}

/** The Surface picker, by the name in its label, or undefined. */
function picker(): HTMLSelectElement | undefined {
  return [...document.querySelectorAll<HTMLSelectElement>("label.select-setting select")].findLast(
    (el) => el.closest("label")?.querySelector(".setting-name")?.textContent === "Surface",
  );
}

function choices(select: HTMLSelectElement): string[] {
  return [...select.options].map((option) => option.textContent ?? "");
}

async function pick(select: HTMLSelectElement, value: string) {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

test("Default offers Paved only, Gravel and Easy MTB trails, at Gravel to start, in Plan and in Go", async () => {
  for (const popout of [true, false]) {
    await section("default", popout);
    const select = picker();
    assert.ok(select, `Surface is there (${popout ? "Plan" : "Go"})`);
    assert.deepEqual(choices(select), ["Paved only", "Gravel", "Easy MTB trails"]);
    assert.equal(select.value, "gravel");
    assert.equal([...document.querySelectorAll("label.toggle")].some((l) => l.textContent?.trim() === "Easy MTB trails"), false, "no separate Easy MTB switch");
  }
});

test("a ride type without Easy MTB offers Paved only and Gravel", async () => {
  await section("fast", true);
  assert.deepEqual(choices(picker()!), ["Paved only", "Gravel"]);
});

test("Road Bike (always paved) and Mountain Bike (its hardest trail level) have no Surface picker; nor walks, runs, share bikes or transit", async () => {
  await section("road-bike", true);
  assert.equal(picker(), undefined);
  for (const preset of PRESETS) {
    const offered = panelView(preset.id, startDials(preset.id)).surface !== null;
    assert.equal(offered, offersStopsAndTurns(preset.id) && preset.id !== "road-bike" && preset.id !== "mountain-bike", preset.id);
  }
});

test("choosing Paved only plans again with it, and it travels in the link, the request, a GPX file and the summary", async () => {
  const { commits } = await section("default", true);
  await pick(picker()!, "paved");
  const dials = commits.at(-1)!;
  assert.equal(dials.paved, true);
  assert.equal(dials.easyMtb, undefined);
  assert.equal(dialFields(fitDials("default", dials)).paved, true);
  const hash = encodePlan([], "default", fitDials("default", dials));
  assert.match(hash, /paved=1/);
  assert.equal(fitDials("default", decodePlan(hash).dials).paved, true);
  assert.match(dialsComment(dials), /paved=1/);
  assert.match(rideSummary("default", dials), /paved only/);
  // Shown back as chosen.
  await section("default", true, dials);
  assert.equal(picker()!.value, "paved");
});

test("Paved only and Easy MTB trails are never both: picking one takes the other off", async () => {
  const { commits } = await section("trailmaxxing", true, { ...startDials("trailmaxxing"), paved: true });
  await pick(picker()!, "easy-mtb");
  assert.equal(commits.at(-1)!.easyMtb, true);
  assert.equal(commits.at(-1)!.paved, undefined);
  await pick(picker()!, "gravel");
  assert.equal(commits.at(-1)!.easyMtb, undefined);
  assert.equal(commits.at(-1)!.paved, undefined);
  // A link with both plans paved.
  const both = fitDials("default", { ...startDials("default"), paved: true, easyMtb: true });
  assert.equal(both.paved, true);
  assert.equal(both.easyMtb, undefined);
});

test("with Keep to roads on, Easy MTB trails is not offered and the (i) says why", async () => {
  const dials = { ...startDials("default"), trailsOff: true, easyMtb: true };
  await section("default", true, dials);
  const select = picker()!;
  assert.deepEqual(choices(select), ["Paved only", "Gravel"]);
  assert.equal(select.value, "gravel");
  const info = document.getElementById(select.getAttribute("aria-describedby")!)!;
  assert.match(info.textContent ?? "", /Easy MTB trails: Not used while Keep to roads is on\./);
});

test("it is the rider's: kept through a change of ride type where taken, and by Back to this ride type's settings", async () => {
  const paved = { ...startDials("default"), paved: true };
  assert.equal(choose("fast", null, paved).paved, true);
  assert.equal(fitDials("road-bike", choose("road-bike", null, paved)).paved, undefined, "Road Bike is paved anyway");
  assert.equal(fitDials("mountain-bike", choose("mountain-bike", null, paved)).paved, undefined);
  const { screen, commits } = await section("default", true, { ...paved, stress: 20 });
  await click(screen.all("button", "Back to this ride type's settings").at(-1)!);
  assert.equal(commits.at(-1)!.paved, true);
});
