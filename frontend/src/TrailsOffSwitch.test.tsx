// "Keep to roads, not trails" in Ride settings (OWNER-DECISIONS 463, 463b), rendered as the rider meets it: a real
// checkbox, labelled and described by its hint; Mass Ride's is always on and stays in the Tab order (aria-disabled, not
// disabled), and a press there changes nothing. (Was a source-text test in lib/trailsOff.test.ts.)
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { RideSection } from "./app/Planner.tsx";
import { startDials, type Dials } from "./lib/dials.ts";
import { TRAILS_OFF_HINT, TRAILS_OFF_LOCKED_HINT } from "./lib/dialsPanel.ts";
import type { PresetId } from "./lib/presets.ts";

async function open(preset: PresetId) {
  const commits: Dials[] = [];
  const screen = await render(
    <RideSection preset={preset} dials={startDials(preset)} choosePreset={() => {}} commitDials={(next) => commits.push(next)} route={null} typeCard popout />,
  );
  await click(screen.all("button", /^Ride settings.*Adjust$/).at(-1)!);
  const box = [...document.querySelectorAll<HTMLLabelElement>("label.toggle")]
    .filter((label) => label.textContent?.trim() === "Keep to roads, not trails")
    .at(-1)
    ?.querySelector<HTMLInputElement>('input[type="checkbox"]');
  assert.ok(box, "a checkbox in its label");
  return { box, commits };
}

test("a labelled checkbox described by its hint; a press plans with trails off", async () => {
  const { box, commits } = await open("default");
  assert.equal(document.getElementById(box.getAttribute("aria-describedby")!)?.textContent, TRAILS_OFF_HINT);
  assert.equal(box.checked, false);
  await click(box);
  assert.equal(commits.at(-1)?.trailsOff, true);
});

test("Mass Ride's is on, stays in the Tab order, says why, and a press changes nothing", async () => {
  const { box, commits } = await open("mass-ride");
  assert.equal(box.checked, true);
  assert.equal(box.disabled, false, "a disabled box leaves the Tab order");
  assert.equal(box.getAttribute("aria-disabled"), "true");
  assert.equal(document.getElementById(box.getAttribute("aria-describedby")!)?.textContent, TRAILS_OFF_LOCKED_HINT);
  await click(box);
  assert.equal(commits.length, 0);
});
