// The intuitiveness review of v0.30.0 (Stephen, 2026-11-21: "1, 2, 3, 4 ..."): Ride settings opens on the four a
// rider changes most, the rest a tap away under Advanced; Done is one press back to the route; Create custom asks for
// the name first and its Save is the way out; the ride's summary offers Make Go's default. Rendered and looked at as
// the rider sees it (testSupport/render.ts).
import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { act, useState } from "react";
import { click, render, type } from "./testSupport/render.ts";
import { RideSection } from "./app/Planner.tsx";
import { RideSummaryCard } from "./RideSummaryCard.tsx";
import { startDials } from "./lib/dials.ts";
import { ownNow, reloadOwn, requestCreate } from "./lib/ownRideTypes.ts";
import { statsStart } from "./lib/rideStats.ts";

beforeEach(() => {
  localStorage.clear();
  reloadOwn();
});

/** The words of the controls, in page order, outside any closed fold. */
function shownLabels(root: Element): string[] {
  const out: string[] = [];
  for (const el of Array.from(root.querySelectorAll(".dial-label > span:first-child, .surface label.select-setting > span:first-child, .when-pick > span, details.dials-advanced > summary"))) {
    if (el.closest("details:not([open])") && el.tagName !== "SUMMARY") continue;
    out.push((el.textContent ?? "").trim());
  }
  return out;
}

test("Ride settings opens on Traffic, Hills, Surface and When; speed, waits, turns and sharing are under Advanced", async () => {
  const screen = await render(<RideSection preset="default" dials={startDials("default")} choosePreset={() => {}} commitDials={() => {}} route={null} typeCard popout ridingSpeed={{ mph: null, onChange: () => {} }} />);
  await click(screen.button(/Adjust$/));
  const dialog = document.querySelector("dialog.plan-ride-settings")!;
  assert.deepEqual(shownLabels(dialog), ["Traffic", "Hills", "Surface", "When", "Advanced"]);
  const advanced = dialog.querySelector<HTMLDetailsElement>("details.dials-advanced")!;
  assert.equal(advanced.open, false, "folded until asked for");
  for (const inside of ["Riding speed", "Waiting at lights and stops", "Sharp turns", "Share ride settings"]) {
    assert.ok(advanced.textContent?.includes(inside), `${inside} is under Advanced`);
  }
  assert.ok(advanced.textContent?.includes("Keep to roads"), "Keep to roads is under Advanced");
});

test("Advanced stays open, the focus kept, when Keep to roads is ticked and then unticked", async () => {
  function Section() {
    const [dials, setDials] = useState(startDials("default"));
    return <RideSection preset="default" dials={dials} choosePreset={() => {}} commitDials={setDials} route={null} typeCard popout />;
  }
  const screen = await render(<Section />);
  await click(screen.button(/Adjust$/));
  const advanced = document.querySelector<HTMLDetailsElement>("details.dials-advanced")!;
  await click(advanced.querySelector("summary")!);
  assert.equal(advanced.open, true);
  const roads = () => document.querySelector<HTMLInputElement>(".trails-off input")!;
  roads().focus();
  await click(roads());
  assert.equal(roads().checked, true);
  roads().focus();
  await click(roads());
  assert.equal(roads().checked, false);
  assert.equal(advanced.open, true, "still open with every setting back to the ride type's own");
  assert.equal(document.activeElement, roads());
});

test("the Surface choices say what they let in: Paved and gravel, not Gravel", async () => {
  const screen = await render(<RideSection preset="default" dials={startDials("default")} choosePreset={() => {}} commitDials={() => {}} route={null} typeCard popout />);
  await click(screen.button(/Adjust$/));
  const select = document.querySelector<HTMLSelectElement>(".surface label.select-setting select")!;
  assert.equal(select.selectedOptions[0]?.textContent, "Paved and gravel");
  assert.ok(![...select.options].some((o) => o.textContent === "Gravel"));
});

test("Done closes Ride settings and does the screen's own finish too (Go's Ride sheet closes with it)", async () => {
  let done = 0;
  const screen = await render(<RideSection preset="default" dials={startDials("default")} choosePreset={() => {}} commitDials={() => {}} route={null} typeCard popout onDone={() => done++} />);
  await click(screen.button(/Adjust$/));
  await click(screen.button("Done"));
  assert.equal(document.querySelector("dialog.plan-ride-settings")?.hasAttribute("open"), false);
  assert.equal(done, 1);
});

test("Create custom opens on the name, ready to type over; Save is the one way out and lands back on the route", async () => {
  let done = 0;
  const screen = await render(<RideSection preset="fast" dials={startDials("fast")} choosePreset={() => {}} commitDials={() => {}} route={null} typeCard popout onDone={() => done++} />);
  await act(async () => requestCreate());
  const dialog = document.querySelector("dialog.plan-ride-settings")!;
  assert.ok(dialog.hasAttribute("open"));
  const box = dialog.querySelector<HTMLInputElement>(".own-ride-create-wrap input")!;
  assert.equal(document.activeElement, box, "the name has the focus");
  assert.equal(box.value, "My Fast");
  assert.deepEqual([box.selectionStart, box.selectionEnd], [0, "My Fast".length], "selected, to type over");
  // The name comes before the settings it names.
  const traffic = dialog.querySelector(".dial")!;
  assert.ok(box.compareDocumentPosition(traffic) & Node.DOCUMENT_POSITION_FOLLOWING, "name first, then Traffic");
  assert.ok(dialog.querySelector(".plan-ride-settings-body:has(.own-ride-create-wrap.naming)"), "Done is hidden while naming (styles.css)");
  await type(box, "Commute");
  await click(screen.button("Save"));
  await act(async () => new Promise((r) => setTimeout(r, 20)));
  assert.equal(ownNow().list[0]?.name, "Commute");
  assert.equal(dialog.hasAttribute("open"), false, "saved is done");
  assert.equal(done, 1, "and in Go, the Ride sheet closes too");
});

test("the ride's summary offers Make Go's default, then says Go starts on it", async () => {
  let set = 0;
  const props = { stats: statsStart(Date.now() - 600_000), endedAt: Date.now(), onDone: () => {}, onUndo: () => {}, onReports: () => {} };
  const screen = await render(<RideSummaryCard {...props} goDefault={{ name: "Cargo Bike", set: false, onSet: () => set++ }} />);
  await click(screen.button("Make Go's default: Cargo Bike"));
  assert.equal(set, 1);
  await screen.rerender(<RideSummaryCard {...props} goDefault={{ name: "Cargo Bike", set: true, onSet: () => set++ }} />);
  assert.match(screen.text(), /Go starts on Cargo Bike\./);
  assert.equal(screen.all("button", /Go's default/).length, 0);
  await screen.rerender(<RideSummaryCard {...props} goDefault={null} />);
  assert.doesNotMatch(screen.text(), /Go's default|Go starts on/, "nothing where it is already Go's");
});
