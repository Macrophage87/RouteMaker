// The Surface setting in Ride settings (the owner, 2026-11-21: "a surface setting: paved only, gravel, easy MTB, and then
// MTB2-4 as max"; "People here can and should be able to adjust to anything"): one picker, every level on every bike
// of the rider's own but Road Bike, in Plan's popup and Go's settings alike, rendered and looked at as the rider sees it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, render } from "./testSupport/render.ts";
import { RideSection } from "./app/Planner.tsx";
import { EASY_MTB_PRESETS, dialFields, fitDials, offersStopsAndTurns, startDials, type Dials } from "./lib/dials.ts";
import { panelView } from "./lib/dialsPanel.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { choose } from "./lib/rideTypeDialog.ts";
import { rideSummary } from "./lib/rideSummary.ts";
import { dialsComment } from "./lib/gpx.ts";
import { REACH_DEFAULT, reachBody } from "./lib/reach.ts";
import { rideDials } from "./lib/neighbours.ts";
import { PRESETS, type PresetId } from "./lib/presets.ts";

const ALL = ["Paved only", "Gravel", "Easy MTB trails", "MTB trails up to Level 2 (blue)", "MTB trails up to Level 3 (black)", "MTB trails up to Level 4 (red)"];

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
  return [...document.querySelectorAll<HTMLSelectElement>("label.select-setting select")]
    .filter((el) => el.closest("label")?.querySelector(".setting-name")?.textContent === "Surface")
    .at(-1);
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

test("Default offers every level, Paved only to MTB level 4, at Gravel to start, in Plan and in Go", async () => {
  for (const popout of [true, false]) {
    await section("default", popout);
    const select = picker();
    assert.ok(select, `Surface is there (${popout ? "Plan" : "Go"})`);
    assert.deepEqual(choices(select), ALL);
    assert.equal(select.value, "gravel");
    assert.equal([...document.querySelectorAll("label.toggle")].some((l) => l.textContent?.trim() === "Easy MTB trails"), false, "no separate Easy MTB switch");
  }
});

test("Mountain Bike's picker is its hardest level too, at level 2 to start, with Paved only and Gravel above it", async () => {
  await section("mountain-bike", true);
  const select = picker()!;
  assert.deepEqual(choices(select), ALL);
  assert.equal(select.value, "mtb-2");
  assert.equal(document.querySelectorAll('input[name="mtb-level"]').length, 0, "no second hardest-level control");
});

test("every bike of the rider's own has the picker but Road Bike; the trail levels where the planner takes them", () => {
  for (const preset of PRESETS) {
    const view = panelView(preset.id, startDials(preset.id)).surface;
    assert.equal(view !== null, offersStopsAndTurns(preset.id) && preset.id !== "road-bike", preset.id);
    if (!view) continue;
    const trails = preset.id === "mountain-bike" || EASY_MTB_PRESETS.includes(preset.id);
    assert.equal(view.options.length, trails ? 6 : 2, preset.id);
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
  // Reach's rings take no surface (the API's ReachIn refuses fields it does not know).
  assert.equal("paved" in reachBody([[-77.03, 38.9]], "default", fitDials("default", dials), REACH_DEFAULT), false);
  await section("default", true, dials);
  assert.equal(picker()!.value, "paved");
});

test("MTB level 3 on Fast: Easy MTB trails with the level, in the request, the link and the summary", async () => {
  const { commits } = await section("fast", true);
  await pick(picker()!, "mtb-3");
  const dials = fitDials("fast", commits.at(-1)!);
  assert.equal(dials.easyMtb, true);
  assert.equal(dials.mtbLevel, 3);
  const fields = dialFields(dials);
  assert.equal(fields.easy_mtb, true);
  assert.equal(fields.mtb_level, 3);
  assert.equal(fields.mtb_preferred, undefined);
  const back = fitDials("fast", decodePlan(encodePlan([], "fast", dials)).dials);
  assert.equal(back.mtbLevel, 3);
  assert.match(dialsComment(dials), /level=3/);
  assert.match(rideSummary("fast", dials), /MTB trails up to Level 3/);
  // Back down to Easy MTB trails drops the level (1 is its default).
  const again = await section("fast", true, dials);
  await pick(picker()!, "easy-mtb");
  assert.equal(again.commits.at(-1)!.mtbLevel, undefined);
  assert.equal(again.commits.at(-1)!.easyMtb, true);
  // Kept through a change to another ride type that takes it, dropped on one that does not.
  assert.equal(choose("trailmaxxing", null, dials).mtbLevel, 3);
  assert.equal(fitDials("ebike", choose("ebike", null, dials)).mtbLevel, undefined);
});

test("Gravel and Paved only on Mountain Bike plan with no mountain-bike trails (level 0), and hide the preferred level", async () => {
  const { commits } = await section("mountain-bike", true);
  assert.ok(document.querySelector('input[name="mtb-preferred"]'), "the preferred level shows with trails on");
  await pick(picker()!, "gravel");
  const gravel = fitDials("mountain-bike", commits.at(-1)!);
  assert.equal(gravel.mtbLevel, 0);
  assert.equal(dialFields(gravel).mtb_level, 0);
  assert.match(encodePlan([], "mountain-bike", gravel), /level=0/);
  assert.equal(fitDials("mountain-bike", decodePlan(encodePlan([], "mountain-bike", gravel)).dials).mtbLevel, 0);
  const second = await section("mountain-bike", true, gravel);
  assert.equal(picker()!.value, "gravel");
  const dialog = second.screen.all("dialog").at(-1)!;
  assert.equal(dialog.querySelector('input[name="mtb-preferred"]'), null, "no preferred level with no trails");
  await pick(picker()!, "paved");
  const paved = fitDials("mountain-bike", second.commits.at(-1)!);
  assert.equal(paved.mtbLevel, 0);
  assert.equal(paved.paved, true);
});

test("on Mountain Bike, a lower hardest level lowers the preferred one with it", async () => {
  const { commits } = await section("mountain-bike", true, { ...startDials("mountain-bike"), mtbLevel: 4, mtbPreferred: 4 });
  await pick(picker()!, "easy-mtb");
  const next = commits.at(-1)!;
  assert.equal(next.mtbLevel, 1);
  assert.equal(next.mtbPreferred, undefined, "lowered to 1, the default for that hardest level");
});

test("Paved only and the trails are never both: picking one takes the other off", async () => {
  const { commits } = await section("trailmaxxing", true, { ...startDials("trailmaxxing"), paved: true });
  await pick(picker()!, "mtb-4");
  assert.equal(commits.at(-1)!.easyMtb, true);
  assert.equal(commits.at(-1)!.paved, undefined);
  await pick(picker()!, "gravel");
  assert.equal(commits.at(-1)!.easyMtb, undefined);
  assert.equal(commits.at(-1)!.mtbLevel, undefined);
  const both = fitDials("default", { ...startDials("default"), paved: true, easyMtb: true, mtbLevel: 3 });
  assert.equal(both.paved, true);
  assert.equal(both.easyMtb, undefined);
  assert.equal(both.mtbLevel, undefined);
});

test("with Keep to roads on, the trail choices are not offered and the (i) says why", async () => {
  await section("default", true, { ...startDials("default"), trailsOff: true, easyMtb: true });
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
  const { screen, commits } = await section("default", true, { ...paved, stress: 20 });
  await click(screen.all("button", "Back to this ride type's settings").at(-1)!);
  assert.equal(commits.at(-1)!.paved, true);
});

test("on Mountain Bike, another hardest level keeps the preferred one where it still fits", async () => {
  const { commits } = await section("mountain-bike", true, { ...startDials("mountain-bike"), mtbLevel: 4, mtbPreferred: 3 });
  await pick(picker()!, "mtb-3");
  assert.equal(commits.at(-1)!.mtbLevel, 3);
  assert.equal(commits.at(-1)!.mtbPreferred, 3);
  const raised = await section("mountain-bike", true, { ...startDials("mountain-bike"), mtbLevel: 3, mtbPreferred: 3 });
  await pick(picker()!, "mtb-4");
  assert.equal(raised.commits.at(-1)!.mtbPreferred, 3);
});

test("Gravel and Mountain Goat take Paved only and Gravel: their off-road graph has the trails already", () => {
  for (const preset of ["gravel", "mountain-goat"] as const) {
    assert.deepEqual(panelView(preset, startDials(preset)).surface?.options.map(([value]) => value), ["paved", "gravel"]);
  }
});

test("a ride on the All paved option drops a harder trail level with Easy MTB trails, so its re-plans are taken", () => {
  const dials = { ...startDials("default"), easyMtb: true, mtbLevel: 3 };
  const shown = { preset: "default", neighbour: { kind: "paved", stress: dials.stress } } as unknown as Parameters<typeof rideDials>[1];
  const ride = rideDials(dials, shown);
  assert.equal(ride.paved, true);
  assert.equal(ride.easyMtb, undefined);
  assert.equal(ride.mtbLevel, undefined);
  const mtb = rideDials({ ...startDials("mountain-bike"), mtbLevel: 3 }, { ...shown!, preset: "mountain-bike" } as typeof shown);
  assert.equal(mtb.mtbLevel, 3, "Mountain Bike's level is its own");
});
