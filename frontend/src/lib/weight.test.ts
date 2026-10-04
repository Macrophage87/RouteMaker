// The rider and bike weight, kept private (OWNER-DECISIONS 313-318): the panel's line, the
// worksheet, what is kept and where, and that the number never leaves the dialog.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  BLANK,
  DEFAULT_NAME,
  WEIGHT_NOTHING,
  WEIGHT_PURPOSE,
  WEIGHT_ROUGH,
  WEIGHT_NOT_A_NUMBER,
  WEIGHT_STORAGE_KEY,
  WeightStore,
  daysSince,
  defaultSplit,
  editPart,
  editTotal,
  lbOf,
  migrate,
  poundsToKg,
  savedNotice,
  setAgo,
  toStored,
  weightLine,
  withWeight,
  worksheetKg,
  type StoredWeight,
} from "./weight.ts";
import { WeightSetting, totalSaid, weightDialogBody } from "./weightDialog.ts";
import { PASSENGERS_WEIGHT_KG, SYSTEM_WEIGHT_KG, SYSTEM_WEIGHT_MAX_KG, SYSTEM_WEIGHT_MIN_KG, dialFields, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { writeGpx } from "./gpx.ts";

const NOW = new Date(2026, 9, 4, 15, 0).getTime();
const DAY = 24 * 60 * 60 * 1000;
const SPLIT = defaultSplit(null);
const SAVED: StoredWeight = { name: DEFAULT_NAME, totalKg: 93.4, parts: { riderKg: 78.4, bikeKg: 15, cargoKg: 0 }, setAt: NOW - 3 * DAY };

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v), removeItem: (k: string) => void data.delete(k) };
}

// ---- 314, 315: the line, never the number ------------------------------------------

test("the panel's line says whether a weight is set and when, never its value (314)", () => {
  assert.equal(weightLine(null, NOW), "Rider and bike weight: not set, defaults used");
  assert.equal(weightLine({ ...SAVED, setAt: NOW - 60 * 1000 }, NOW), "Rider and bike weight: set today");
  assert.equal(weightLine({ ...SAVED, setAt: NOW - DAY }, NOW), "Rider and bike weight: set 1 day ago");
  assert.equal(weightLine(SAVED, NOW), "Rider and bike weight: set 3 days ago");
  // Calendar days: late last night is "1 day ago", earlier today "today".
  const midnight = new Date(2026, 9, 4, 0, 0).getTime();
  assert.equal(setAgo(midnight - 60 * 1000, NOW), "set 1 day ago");
  assert.equal(setAgo(midnight + 60 * 1000, NOW), "set today");
  assert.equal(daysSince(NOW + DAY, NOW), 0, "a clock set back is not negative");
  for (const w of [SAVED, { ...SAVED, setAt: NOW }]) assert.doesNotMatch(weightLine(w, NOW), /\d+(\.\d)? ?(lb|kg)|93|206/);
});

test("the line names a loadout other than the one a signed-out rider has (315)", () => {
  assert.equal(weightLine({ ...SAVED, name: "Touring, loaded" }, NOW), "Rider and bike: Touring, loaded, set 3 days ago");
  assert.equal(weightLine({ ...SAVED, name: DEFAULT_NAME }, NOW), "Rider and bike weight: set 3 days ago");
});

// ---- 316, 317: the worksheet ------------------------------------------------------

test("blank parts take the ride type's defaults, which sum to its default total", () => {
  assert.deepEqual(defaultSplit(null), { riderKg: 75, bikeKg: 15, cargoKg: 0 });
  assert.deepEqual(defaultSplit("cargo"), { riderKg: 75, bikeKg: 15, cargoKg: 0 });
  assert.deepEqual(defaultSplit("people"), { riderKg: 75, bikeKg: 30, cargoKg: 15 });
  for (const carrying of [null, "cargo", "people"] as const) {
    const s = defaultSplit(carrying);
    assert.equal(s.riderKg + s.bikeKg + s.cargoKg, carrying === "people" ? PASSENGERS_WEIGHT_KG : SYSTEM_WEIGHT_KG);
  }
});

test("a part typed recomputes the Total, blanks at their defaults", () => {
  let sheet = editPart(BLANK, "rider", "180", SPLIT);
  assert.equal(sheet.mode, "parts");
  assert.equal(worksheetKg(sheet, SPLIT), 96.6, "180 lb (81.6 kg) + the default 15 kg bike");
  assert.equal(sheet.total, String(lbOf(96.6)));
  sheet = editPart(sheet, "cargo", "22", SPLIT);
  assert.equal(worksheetKg(sheet, SPLIT), 106.6);
  sheet = editPart(sheet, "bike", "abc", SPLIT);
  assert.equal(worksheetKg(sheet, SPLIT), null);
  assert.equal(sheet.total, "", "not a number: no total");
  assert.equal(worksheetKg(BLANK, SPLIT), undefined, "nothing entered");
});

test("a Total typed replaces the parts, and only the total is kept", () => {
  const parts = editPart(BLANK, "rider", "180", SPLIT);
  const total = editTotal("200");
  assert.deepEqual({ ...total }, { ...BLANK, total: "200", mode: "total" }, "the parts are cleared");
  assert.equal(worksheetKg(total, SPLIT), 90.7);
  const kept = toStored(total, SPLIT, NOW);
  assert.deepEqual(kept, { name: DEFAULT_NAME, totalKg: 90.7, setAt: NOW });
  // A part edited afterwards takes over again.
  assert.equal(editPart(total, "bike", "40", SPLIT).mode, "parts");
  const fromParts = toStored(parts, SPLIT, NOW);
  assert.deepEqual(fromParts, { name: DEFAULT_NAME, totalKg: 96.6, parts: { riderKg: 81.6, bikeKg: 15, cargoKg: 0 }, setAt: NOW });
});

test("Save refuses only nothing entered and an entry that is not a number, in neutral words", () => {
  assert.deepEqual(toStored(BLANK, SPLIT, NOW), { refused: WEIGHT_NOTHING });
  assert.deepEqual(toStored(editTotal("heavy"), SPLIT, NOW), { refused: WEIGHT_NOT_A_NUMBER });
  assert.equal(WEIGHT_NOT_A_NUMBER, "Enter numbers only, in pounds, or Cancel.");
  assert.equal(poundsToKg(" 198 lb "), 89.8);
});

const kgTotal = (kg: number) => editTotal(String(Math.round(kg * 2.20462 * 10) / 10));

test("everyone's total is taken: 25 to 700 kg (55 to 1,543 lb) as entered, outside it the nearer limit, silently (OWNER-DECISIONS 337, 338, 352)", () => {
  assert.equal(SYSTEM_WEIGHT_MIN_KG, 25);
  assert.equal(SYSTEM_WEIGHT_MAX_KG, 700);
  // 48 kg (a 90 lb rider on a 16 lb bike), 90 kg and a pedicab's 600 kg pass through.
  for (const kg of [48, 90, 450, 600]) assert.deepEqual(toStored(kgTotal(kg), SPLIT, NOW), { name: DEFAULT_NAME, totalKg: kg, setAt: NOW }, `${kg} kg`);
  for (const kg of [25, 700]) assert.equal((toStored(kgTotal(kg), SPLIT, NOW) as StoredWeight).totalKg, kg);
  // Outside: the nearer limit, and nothing says so (352: "include silently").
  assert.deepEqual(toStored(kgTotal(10), SPLIT, NOW), { name: DEFAULT_NAME, totalKg: 25, setAt: NOW });
  assert.deepEqual(toStored(kgTotal(900), SPLIT, NOW), { name: DEFAULT_NAME, totalKg: 700, setAt: NOW });
  // From the parts too, which are then not kept (they no longer make the total).
  assert.deepEqual(toStored(editPart(editPart(BLANK, "rider", "2000", SPLIT), "bike", "40", SPLIT), SPLIT, NOW), { name: DEFAULT_NAME, totalKg: 700, setAt: NOW });
  // What is sent is the limit, in whole kilograms.
  assert.equal(dialFields(withWeight(startDials("trailmaxxing"), toStored(kgTotal(10), SPLIT, NOW) as StoredWeight)).system_weight_kg, 25);
  assert.equal(dialFields(withWeight(startDials("trailmaxxing"), toStored(kgTotal(900), SPLIT, NOW) as StoredWeight)).system_weight_kg, 700);
});

/** The dialog's Save and Cancel buttons, from its markup's last element. */
function buttons(body: ReturnType<typeof weightDialogBody>) {
  const actions = (body.at(-1) as { props: { children: Array<{ props: { onClick: () => void; children: string } } | null> } }).props.children.filter(Boolean) as Array<{
    props: { onClick: () => void; children: string };
  }>;
  return (name: string) => actions.find((b) => b.props.children === name)!.props.onClick;
}

test("after every Save and Cancel the fields are blank again, and no typed figure stays in the closed dialog (the review's S2, 313, 317(b))", () => {
  for (const [typed, kgs] of [["200", ["200", "90.7", "91 kg"]], ["1700", ["1700", "771", "700 kg", "1543"]]] as const) {
    for (const press of ["Save", "Cancel"]) {
      const calls: StoredWeight[] = [];
      let sheet = editPart(BLANK, "rider", typed, SPLIT);
      let said = "x";
      let closed = 0;
      const props = { open: true, saved: null, remembered: false, split: SPLIT, onSave: (w: StoredWeight) => void calls.push(w), onClear: () => {}, onClose: () => void (closed += 1), now: () => NOW };
      const set = { sheet: (s: typeof sheet) => void (sheet = s), remember: () => {}, refused: (t: string) => void (said = t) };
      const before = renderToStaticMarkup(createElement("dialog", null, ...weightDialogBody("w", props, { sheet, remember: false, refused: "" }, set)));
      assert.ok(before.includes(typed), "the premise: while typing, the figure is in the dialog");
      buttons(weightDialogBody("w", props, { sheet, remember: false, refused: "" }, set))(press)();
      assert.deepEqual(sheet, BLANK, `${press}: the fields are blank again`);
      assert.equal(said, "", `${press}: and nothing is said, no limit either (352)`);
      if (press === "Save") assert.equal(calls.length, 1);
      else assert.equal(closed, 1);
      const saved = calls[0] ?? null;
      const after = renderToStaticMarkup(createElement("dialog", null, ...weightDialogBody("w", { ...props, saved }, { sheet, remember: false, refused: said }, set)));
      for (const n of kgs) assert.ok(!after.includes(n), `${press} ${typed} lb: ${n} is not in the dialog`);
      assert.doesNotMatch(after, /plan with|designed for/, "no limit note anywhere");
    }
  }
});

test("the polite total says what the worksheet comes to, pounds first", () => {
  assert.equal(totalSaid(BLANK, SPLIT), "Total: nothing entered; the defaults, 198 lb (90 kg), are used.");
  assert.equal(totalSaid(editTotal("200"), SPLIT), "Total: 200 lb (91 kg).");
  assert.equal(totalSaid(editTotal("x"), SPLIT), "Total: not a number yet.");
});

// ---- 317(b), 318: the dialog never shows a saved number --------------------------

function dialogHtml(saved: StoredWeight | null, sheet = BLANK) {
  const props = { open: true, saved, remembered: true, split: SPLIT, onSave: () => {}, onClear: () => {}, onClose: () => {}, now: () => NOW };
  const body = weightDialogBody("w", props, { sheet, remember: true, refused: "" }, { sheet: () => {}, remember: () => {}, refused: () => {} });
  return renderToStaticMarkup(createElement("dialog", { "aria-labelledby": "w-title", "aria-describedby": "w-purpose w-rough" }, ...body));
}

test("the dialog leads with the two lines that are its description, and labels every field (318)", () => {
  const html = dialogHtml(null);
  assert.equal(WEIGHT_PURPOSE, "Optional. Used only to work out your route, for how hard hills feel. It is never displayed, and never put in shared links or downloads.");
  assert.equal(WEIGHT_ROUGH, "A rough estimate is fine. Within 20 lb (10 kg) or so makes no real difference.");
  assert.ok(html.indexOf(WEIGHT_PURPOSE) < html.indexOf("Rider, lb (kg)"), "the lines come first");
  assert.match(html, /<p id="w-purpose">Optional\./);
  assert.match(html, /<p id="w-rough">A rough estimate/);
  // Pounds first, kilograms in brackets (316), and the kilograms a figure comes to in the field's description.
  for (const [id, label] of [["w-rider", "Rider, lb (kg)"], ["w-bike", "Bike, lb (kg)"], ["w-cargo", "Cargo, lb (kg)"], ["w-total", "Total, lb (kg)"]]) {
    assert.ok(html.includes(`<label for="${id}">${label}</label><input id="${id}"`), label);
    assert.match(html, new RegExp(`id="${id}"[^>]*aria-describedby="${id}-kg ${id}-hint"`), `${label}: its kilograms are described`);
    assert.match(html, new RegExp(`<span class="weight-kg" id="${id}-kg">`), `${label}: not hidden from a screen reader`);
  }
  assert.match(html, /<p class="weight-total" role="status" aria-live="polite">Total: /);
  assert.match(html, /Remember on this device/);
  assert.match(html, /<p class="dial-rule" aria-live="assertive"><\/p>/);
  assert.doesNotMatch(html, />Clear</, "nothing saved: nothing to clear");
});

test("a saved weight is said to exist, with its date, and its numbers are never in the dialog (317(b))", () => {
  const html = dialogHtml(SAVED);
  assert.ok(html.includes(savedNotice(SAVED, NOW)));
  assert.equal(savedNotice(SAVED, NOW), "A weight is saved (set 3 days ago). Enter new values to replace it, or Clear to use the defaults.");
  for (const id of ["w-rider", "w-bike", "w-cargo", "w-total"]) assert.match(html, new RegExp(`id="${id}"[^>]*value=""`), `${id} starts blank`);
  for (const n of ["93.4", "93", "206", "78.4", "173"]) assert.ok(!html.includes(n), `the saved ${n} is not in the dialog`);
  assert.match(html, />Save</);
  assert.match(html, />Clear</);
  assert.match(html, />Cancel</);
});

test("the panel shows the line and Change, never the number, and the closed dialog holds no saved value", () => {
  const html = renderToStaticMarkup(createElement(WeightSetting, { saved: SAVED, remembered: true, split: SPLIT, onSave: () => {}, onClear: () => {}, now: () => NOW }));
  assert.match(html, /<p class="weight-line" id="[^"]+-line">Rider and bike weight: set 3 days ago<\/p>/);
  assert.match(html, /<button type="button" class="secondary" aria-label="Change rider and bike weight" aria-describedby="[^"]+-line">Change<\/button>/);
  assert.match(html, /<dialog class="weight-dialog" aria-modal="true" aria-labelledby="[^"]+-title" aria-describedby="[^"]+-purpose [^"]+-rough">/);
  for (const n of ["93.4", "93", "206", "78.4", "173"]) assert.ok(!html.includes(n), `the saved ${n} is nowhere in the page`);
});

test("Save, Clear and Cancel call through; Save refuses in words and keeps the dialog open", () => {
  const calls: string[] = [];
  let refusedWith = "";
  const props = {
    open: true,
    saved: SAVED,
    remembered: false,
    split: SPLIT,
    onSave: (w: StoredWeight, remember: boolean) => void calls.push(`save ${w.totalKg} ${remember}`),
    onClear: () => void calls.push("clear"),
    onClose: () => void calls.push("cancel"),
    now: () => NOW,
  };
  const buttons = (sheet: typeof BLANK) =>
    (weightDialogBody("w", props, { sheet, remember: true, refused: "" }, { sheet: () => {}, remember: () => {}, refused: (t) => void (refusedWith = t) }).at(-1) as { props: { children: Array<{ props: { onClick: () => void; children: string } } | null> } }).props.children.filter(Boolean) as Array<{ props: { onClick: () => void; children: string } }>;
  const click = (sheet: typeof BLANK, name: string) => buttons(sheet).find((b) => b.props.children === name)!.props.onClick();
  click(BLANK, "Save");
  assert.equal(refusedWith, WEIGHT_NOTHING);
  assert.deepEqual(calls, []);
  click(editTotal("200"), "Save");
  click(BLANK, "Clear");
  click(BLANK, "Cancel");
  assert.deepEqual(calls, ["save 90.7 true", "clear", "cancel"]);
});

// ---- where it is kept ------------------------------------------------------------

test("signed out, it is kept in this browser only when the rider ticks Remember, else for this visit; Clear forgets it", () => {
  const storage = memory();
  const store = new WeightStore(storage);
  assert.equal(store.load(NOW), null);
  store.save(SAVED, false);
  assert.deepEqual(store.load(NOW), SAVED, "this visit");
  assert.equal(storage.data.has(WEIGHT_STORAGE_KEY), false, "not in the browser");
  assert.equal(new WeightStore(storage).load(NOW), null, "a new visit has none");
  store.save(SAVED, true);
  assert.deepEqual(JSON.parse(storage.data.get(WEIGHT_STORAGE_KEY)!), SAVED);
  assert.deepEqual(new WeightStore(storage).load(NOW), SAVED, "a new visit finds it");
  assert.equal(new WeightStore(storage).remembered(), true);
  store.save(SAVED, false);
  assert.equal(storage.data.has(WEIGHT_STORAGE_KEY), false, "unticked: taken out of the browser");
  store.save(SAVED, true);
  store.clear();
  assert.equal(store.load(NOW), null);
  assert.equal(storage.data.has(WEIGHT_STORAGE_KEY), false);
});

test("storage that throws or is missing never breaks it: it lasts the visit", () => {
  const throwing = { getItem: () => { throw new Error("SecurityError"); }, setItem: () => { throw new Error("SecurityError"); }, removeItem: () => { throw new Error("SecurityError"); } };
  const store = new WeightStore(throwing as never);
  assert.equal(store.load(NOW), null);
  assert.equal(store.save(SAVED, true), false);
  assert.deepEqual(store.load(NOW), SAVED);
  store.clear();
  assert.equal(new WeightStore(null).load(NOW), null);
});

test("an earlier stored value is read in today's shape: a bare kilogram figure, {kg}, {totalKg} and an ISO date", () => {
  assert.deepEqual(migrate("90.7", NOW), { name: DEFAULT_NAME, totalKg: 90.7, setAt: NOW });
  assert.deepEqual(migrate(JSON.stringify({ kg: 100 }), NOW), { name: DEFAULT_NAME, totalKg: 100, setAt: NOW });
  assert.deepEqual(migrate({ systemWeightKg: 95.04, setAt: "2026-10-01T12:00:00Z" }, NOW), { name: DEFAULT_NAME, totalKg: 95, setAt: Date.parse("2026-10-01T12:00:00Z") });
  assert.deepEqual(migrate(JSON.stringify(SAVED), NOW), SAVED);
  assert.deepEqual(migrate({ name: "", totalKg: 80, parts: { riderKg: "x" }, setAt: 5 }, NOW), { name: DEFAULT_NAME, totalKg: 80, setAt: 5 });
  assert.equal(migrate("300", NOW)?.totalKg, 300, "in today's wider range");
  assert.deepEqual(migrate({ totalKg: 450, limit: "max", setAt: 5 }, NOW), { name: DEFAULT_NAME, totalKg: 450, setAt: 5 }, "an old limit flag is dropped (352)");
  assert.equal(migrate("600", NOW)?.totalKg, 600, "a pedicab's total (352)");
  for (const bad of ["{", "800", JSON.stringify({ totalKg: 20 }), null, 7]) assert.equal(migrate(bad, NOW), null, String(bad));
  const storage = memory({ [WEIGHT_STORAGE_KEY]: "88" });
  assert.equal(new WeightStore(storage).load(NOW)?.totalKg, 88);
});

// ---- 313: never in a link or a download; only the total reaches the planner -------

test("only the total reaches the planner, in whole kilograms, and the defaults with none set", () => {
  const dials = startDials("trailmaxxing");
  assert.equal(dialFields(withWeight(dials, SAVED)).system_weight_kg, 93);
  assert.equal("system_weight_kg" in dialFields(withWeight(dials, null)), false);
  assert.equal("systemWeightKg" in withWeight({ ...dials, systemWeightKg: 120 }, null), false, "a stray one is dropped");
});

test("the weight is never in a shared link, and an old link's is ignored (313)", () => {
  const points: [number, number][] = [[-77.0063, 38.8973], [-77.01, 38.9]];
  const hash = encodePlan(points, "trailmaxxing", withWeight(startDials("trailmaxxing"), SAVED));
  assert.doesNotMatch(hash, /weight|93/);
  assert.equal(decodePlan(`${hash}&sysweight=110`).dials.systemWeightKg, undefined);
});

test("the weight is never in a downloaded GPX file, even from a route planned with one (313)", () => {
  const points: [number, number][] = [[-77.0063, 38.8973], [-77.01, 38.9]];
  const gpx = writeGpx({
    name: "Ride",
    description: "d",
    attribution: ["© OpenStreetMap contributors (ODbL)"],
    preset: "trailmaxxing",
    planPoints: points,
    geometry: points,
    dials: { stress: 100, hills: 0, when: "weekend", carrying: null, system_weight_kg: 93 } as never,
  });
  assert.doesNotMatch(gpx, /weight|93\b|kg/i);
});

test("every open starts blank, whatever is saved, with the Remember tick as this browser has it (317(b))", async () => {
  const { openedState } = await import("./weightDialog.ts");
  assert.deepEqual(openedState({ saved: SAVED, remembered: true }), { sheet: BLANK, remember: true, refused: "" });
  assert.deepEqual(openedState({ saved: null, remembered: false }), { sheet: BLANK, remember: false, refused: "" });
});

test("the Cargo field takes a large load: a trailer of 400 lb is fine, and only the total is capped (OWNER-DECISIONS 339)", () => {
  // 180 lb rider + 30 lb bike + 400 lb cargo = 610 lb (276.6 kg, the sum of the parts to a tenth): taken as it is, with its parts.
  let sheet = editPart(BLANK, "rider", "180", SPLIT);
  sheet = editPart(sheet, "bike", "30", SPLIT);
  sheet = editPart(sheet, "cargo", "400", SPLIT);
  assert.equal(sheet.total, "610");
  const kept = toStored(sheet, SPLIT, NOW) as StoredWeight;
  assert.equal(kept.limit, undefined);
  assert.equal(kept.totalKg, 276.6);
  assert.deepEqual(kept.parts, { riderKg: 81.6, bikeKg: 13.6, cargoKg: 181.4 });
  // Over the cap: the total is the limit, silently (352).
  const over = toStored(editPart(sheet, "cargo", "1500", SPLIT), SPLIT, NOW) as StoredWeight;
  assert.deepEqual(over, { name: DEFAULT_NAME, totalKg: 700, setAt: NOW });
  assert.doesNotMatch(savedNotice(over, NOW), /plan with|designed for|1,?54\d|700/);
});

test("no part has a limit of its own, only that it is a non-negative number; only the total is clamped (OWNER-DECISIONS 340)", () => {
  // A 400 lb rider, a 120 lb bike, 0 cargo: taken as entered (236.8 kg), parts and all.
  let sheet = editPart(BLANK, "rider", "400", SPLIT);
  sheet = editPart(sheet, "bike", "120", SPLIT);
  sheet = editPart(sheet, "cargo", "0", SPLIT);
  const kept = toStored(sheet, SPLIT, NOW) as StoredWeight;
  assert.equal(kept.limit, undefined);
  assert.deepEqual(kept.parts, { riderKg: 181.4, bikeKg: 54.4, cargoKg: 0 });
  // Any one part as large as it is: the total alone decides the clamp.
  assert.equal((toStored(editPart(BLANK, "rider", "5000", SPLIT), SPLIT, NOW) as StoredWeight).totalKg, 700);
  assert.equal((toStored(editPart(BLANK, "bike", "1", SPLIT), SPLIT, NOW) as StoredWeight).limit, undefined, "a 1 lb bike with the default rider is fine");
  // Negative or not a number: not saved, in the same neutral words.
  for (const text of ["-5", "-0.5", "abc", "1e3", "12,5"]) {
    assert.deepEqual(toStored(editPart(BLANK, "cargo", text, SPLIT), SPLIT, NOW), { refused: WEIGHT_NOT_A_NUMBER }, text);
    assert.deepEqual(toStored(editTotal(text), SPLIT, NOW), { refused: WEIGHT_NOT_A_NUMBER }, `total ${text}`);
  }
  // Nothing anywhere judges a weight.
  const words = [WEIGHT_NOTHING, WEIGHT_NOT_A_NUMBER, savedNotice(SAVED, NOW), dialogHtml(null)].join(" ");
  assert.doesNotMatch(words, /unusual|sensible|unrealistic|too (heavy|light|high|low)|heavy|light|invalid|extreme|normal/i);
  assert.doesNotMatch(dialogHtml(null), /\b(min|max)="/, "no bounds on any field");
});
