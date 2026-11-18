// Go's ride type chips (app/Sheets.tsx RideChips), as the rider sees them: the ride type in use first, then "Ride type
// & settings", so both are on a 390 px screen without a sideways swipe (the 2026-11-12 backlog, Go item 12).
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "../testSupport/render.ts";
import { RideChips } from "./Sheets.tsx";
import type { PresetId } from "../lib/presets.ts";

const IDS: PresetId[] = ["cargo", "bike-transit", "bikeshare-transit"];

test("the ride type in use, then Ride type & settings, then the other chips", async () => {
  const opened: HTMLElement[] = [];
  const screen = await render(<RideChips ids={IDS} preset="cargo" onPick={() => {}} more={(opener) => opened.push(opener)} />);
  const buttons = screen.all("button");
  assert.equal(buttons.length, 4);
  assert.equal(buttons[0].getAttribute("aria-pressed"), "true");
  assert.match(buttons[0].textContent ?? "", /Cargo/);
  assert.equal(buttons[1].textContent, "Ride type & settings");
  await click(buttons[1]);
  assert.deepEqual(opened, [buttons[1]]);
  assert.ok(!screen.text().includes("More ride types"));
});

test("a chip picks its ride type; with the sliders moved, the chip in use says so, all of it heard", async () => {
  const picked: PresetId[] = [];
  const screen = await render(<RideChips ids={IDS} preset="cargo" onPick={(id) => picked.push(id)} more={() => {}} changed />);
  const [inUse, , transit] = screen.all("button");
  assert.match(inUse.textContent ?? "", /\(changed\)/);
  assert.match(screen.text(), /settings changed from this ride type's start/);
  await click(transit);
  assert.deepEqual(picked, ["bike-transit"]);
});

test("without More, only the chips", async () => {
  const screen = await render(<RideChips ids={IDS} preset="cargo" onPick={() => {}} />);
  assert.equal(screen.all("button").length, 3);
});
