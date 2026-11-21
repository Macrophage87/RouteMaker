// The rider's own ride types (the owner, 2026-11-21: "Let people save and name their own configuration dials"; "save as
// my own ride type is a good option") and Go's default from the ride type list ("make a button in the ride type list
// that will make it the default for go"). Rendered and looked at as the rider sees it (testSupport/render.ts).
import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, nameOf, render, type } from "./testSupport/render.ts";
import { RideSection } from "./app/Planner.tsx";
import { RideTypePicker } from "./RideTypePicker.tsx";
import { GoDefaultButton } from "./lib/rideTypeCards.ts";
import { startDials, type Dials } from "./lib/dials.ts";
import { matchingOwn, ownNow, ownPlan, ownSetup, parseOwn, readShareJson, reloadOwn, setGoOwn, setOwn, shareJson, withSaved } from "./lib/ownRideTypes.ts";
const ownPlanOf = (s: { preset: PresetId; dials: Dials }) => ownPlan(s.preset, s.dials);
import { applyToDevice, deviceSettings, parseSettings } from "./lib/accountSettings.ts";
import type { PresetId } from "./lib/presets.ts";

beforeEach(() => {
  localStorage.clear();
  reloadOwn();
});

const coffee: Dials = { ...startDials("fast"), waitWeight: 3, sharpTurnWeight: 0 };

test("the popup offers Save as my own ride type once a slider is moved, and the name it is saved under names the popup", async () => {
  const screen = await render(<RideSection preset="fast" dials={startDials("fast")} choosePreset={() => {}} commitDials={() => {}} route={null} typeCard popout />);
  await click(screen.button(/Adjust$/));
  assert.equal(screen.all("button", "Save as my own ride type").length, 0, "nothing to save at the ride type's own start");
  await screen.rerender(<RideSection preset="fast" dials={coffee} choosePreset={() => {}} commitDials={() => {}} route={null} typeCard popout />);
  await click(screen.button("Save as my own ride type"));
  const box = document.querySelector<HTMLInputElement>(".own-ride-save input")!;
  assert.equal(document.querySelector(`label[for="${box.id}"]`)?.textContent, "Name");
  assert.equal(box.value, "My Fast", "a name to start from");
  await type(box, "Saturday coffee ride");
  await click(screen.button("Save"));
  assert.ok(screen.dialog("Ride settings: Saturday coffee ride"), "the popup is named for it");
  assert.equal(screen.all("button", "Save as my own ride type").length, 0, "already one of the rider's own");
  assert.match(screen.text(), /Saved as Saturday coffee ride\./);
  // The ride type's button names it too.
  assert.ok(screen.button(/^Saturday coffee ride/));
  const kept = ownNow().list;
  assert.equal(kept.length, 1);
  assert.deepEqual(ownSetup(kept[0]).preset, "fast");
  assert.equal(ownSetup(kept[0]).dials.waitWeight, 3);
});

test("the ride type list shows My ride types first; picking one sets its ride type and every slider; Remove takes it off", async () => {
  setOwn(withSaved([], "Saturday coffee ride", "fast", coffee));
  const chosen: { preset: PresetId; dials: Dials }[] = [];
  const screen = await render(<RideTypePicker preset="default" dials={startDials("default")} onChoose={(preset, dials) => chosen.push({ preset, dials })} />);
  await click(screen.button(/^Default/));
  assert.ok(screen.get("heading", "My ride types"));
  const card = screen.button("Saturday coffee ride");
  assert.match(card.textContent ?? "", /Fast · .*waits count 3x/);
  await click(card);
  assert.equal(chosen.at(-1)?.preset, "fast");
  assert.equal(chosen.at(-1)?.dials.waitWeight, 3);
  assert.equal(chosen.at(-1)?.dials.sharpTurnWeight, 0);
  await click(screen.button(/^Default/));
  await click(screen.button("Remove Saturday coffee ride"));
  assert.equal(screen.all("heading", "My ride types").length, 0);
  assert.equal(ownNow().list.length, 0);
});

test("saving under a name already used replaces that one; names are folded and capped", () => {
  const one = withSaved([], "Coffee", "fast", coffee, "a1");
  const two = withSaved(one, "  coffee ", "gravel", startDials("gravel"), "b2");
  assert.equal(two.length, 1);
  assert.equal(two[0].id, "a1");
  assert.equal(ownSetup(two[0]).preset, "gravel");
  assert.equal(withSaved([], "x".repeat(60), "fast", coffee)[0].name.length, 40);
  assert.equal(matchingOwn(two, "gravel", startDials("gravel"))?.id, "a1");
  // A trip's own target is not part of the setup.
  assert.equal(matchingOwn(two, "gravel", { ...startDials("gravel"), targetDistanceM: 30000 })?.id, "a1");
  assert.deepEqual(parseOwn([{ id: "a1", name: "x", plan: "#preset=fast&q=1,2" }]), [], "never a route's points");
});

test("each card's Go button: pressed on what Go starts on, heard by name, and pressed again puts Go back on Default", async () => {
  const set: string[] = [];
  const go = { current: "cargo", onSet: (key: string) => set.push(key) };
  const screen = await render(
    <>
      <GoDefaultButton goKey="cargo" said="Cargo Bike" go={go} />
      <GoDefaultButton goKey="fast" said="Fast" go={go} />
      <GoDefaultButton goKey="mass-ride" said="Mass Ride" go={go} />
    </>,
  );
  const cargo = screen.button("Go starts on Cargo Bike");
  assert.equal(cargo.getAttribute("aria-pressed"), "true");
  assert.equal(cargo.textContent, "Go");
  assert.equal(screen.button("Go starts on Fast").getAttribute("aria-pressed"), "false");
  assert.equal(screen.all("button", /Mass Ride/).length, 0, "Mass Ride is never Go's");
  await click(screen.button("Go starts on Fast"));
  await click(cargo);
  assert.deepEqual(set, ["fast", "default"]);
});

test("the ride type list offers Go on every card, the rider's own too", async () => {
  setOwn(withSaved([], "Coffee", "fast", coffee, "a1"));
  const set: string[] = [];
  const screen = await render(<RideTypePicker preset="default" dials={startDials("default")} onChoose={() => {}} go={{ current: "own:a1", onSet: (k) => set.push(k) }} />);
  await act(async () => screen.button(/^Default/).click());
  assert.equal(screen.button("Go starts on Coffee").getAttribute("aria-pressed"), "true");
  await click(screen.all("button", "Go starts on Gravel")[0]);
  assert.deepEqual(set, ["gravel"]);
  assert.ok([...document.querySelectorAll("button")].some((b) => nameOf(b) === "Go starts on Default"));
});

test("own ride types and Go's choice of one follow the rider in the account's settings", () => {
  setOwn(withSaved([], "Coffee", "fast", coffee, "a1"));
  setGoOwn("a1");
  const doc = deviceSettings(null);
  assert.equal(doc.own?.[0].name, "Coffee");
  assert.equal(doc.goOwn, "a1");
  const back = parseSettings(JSON.parse(JSON.stringify(doc)))!;
  localStorage.clear();
  reloadOwn();
  applyToDevice(back);
  reloadOwn();
  assert.equal(ownNow().list[0]?.name, "Coffee");
  assert.equal(ownNow().goOwn, "a1");
});

// The owner, 2026-11-21: "In an advanced settings dropdown, have a share and load mechanism to send between people,
// like via JSON."
test("settings go out as plain JSON and come back the same; anything else is refused", () => {
  const text = shareJson("Coffee", "fast", { ...coffee, targetDistanceM: 30000 });
  const body = JSON.parse(text);
  assert.equal(body.kind, "routemaker-ride-settings");
  assert.equal(body.rideType, "fast");
  assert.equal(body.settings.waitWeight, 3);
  assert.equal(body.settings.targetDistanceM, undefined, "a trip's own target stays behind");
  const back = readShareJson(text)!;
  assert.equal(back.name, "Coffee");
  assert.equal(back.preset, "fast");
  assert.equal(ownPlanOf(back), ownPlanOf({ preset: "fast", dials: coffee }));
  assert.equal(readShareJson("not json"), null);
  assert.equal(readShareJson('{"kind":"other"}'), null);
  assert.equal(readShareJson('{"kind":"routemaker-ride-settings","rideType":"nope"}'), null);
  // Values out of range are brought in as a link's would be.
  const wild = readShareJson('{"kind":"routemaker-ride-settings","rideType":"default","settings":{"waitWeight":99,"stress":"x"}}')!;
  assert.equal(wild.dials.waitWeight, 5);
  assert.equal(wild.dials.stress, startDials("default").stress);
});

test("Advanced: settings pasted in and loaded are used at once and kept in My ride types", async () => {
  const chosen: { preset: PresetId; dials: Dials }[] = [];
  const screen = await render(
    <RideSection preset="default" dials={startDials("default")} choosePreset={(preset, dials) => chosen.push({ preset, dials })} commitDials={() => {}} route={null} typeCard popout />,
  );
  await click(screen.button(/Adjust$/));
  const fold = document.querySelector<HTMLDetailsElement>(".own-ride-share")!;
  assert.equal(fold.querySelector("summary")?.textContent, "Advanced");
  fold.open = true;
  await type(fold.querySelector("textarea")!, shareJson("Coffee", "fast", coffee));
  await click(screen.button("Load"));
  assert.equal(chosen.at(-1)?.preset, "fast");
  assert.equal(chosen.at(-1)?.dials.waitWeight, 3);
  assert.equal(ownNow().list[0]?.name, "Coffee");
  assert.match(screen.text(), /Loaded Coffee\. It is in My ride types\./);
  await type(fold.querySelector("textarea")!, "hello");
  await click(screen.button("Load"));
  assert.match(screen.text(), /These are not RouteMaker ride settings\./);
});
