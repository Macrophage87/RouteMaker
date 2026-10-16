// Where the focus goes when a Ride mode block or an Undo/Redo button goes under it (reviews a11y-2, a11y-3).
import { test } from "node:test";
import assert from "node:assert/strict";
import { afterHistoryStep, blockOf, rescueRideFocus } from "./rideFocus.ts";

const on = { off: false, show311: true };
const off = { off: true, show311: false };

test("blockOf: the block that holds the focus, by containment", () => {
  const button311 = {};
  const keep = {};
  const blocks = { "311": { contains: (n: unknown) => n === button311 }, off: { contains: (n: unknown) => n === keep } };
  assert.equal(blockOf(button311, blocks), "311");
  assert.equal(blockOf(keep, blocks), "off");
  assert.equal(blockOf({}, blocks), null);
  assert.equal(blockOf(button311, { "311": null, off: null }), null);
  assert.equal(blockOf(null, blocks), null);
});

test("rescueRideFocus: going off route with the focus on 311 rescues it; with the focus elsewhere, nothing moves", () => {
  assert.equal(rescueRideFocus({ focusWasIn: "311", before: on, now: off, focusLost: true }), true);
  // The urgent off-route cue is not talked over: a focus that is fine stays.
  assert.equal(rescueRideFocus({ focusWasIn: null, before: on, now: off, focusLost: true }), false, "the focus was not in the 311 block");
  assert.equal(rescueRideFocus({ focusWasIn: "311", before: on, now: off, focusLost: false }), false, "the focus was not lost");
  assert.equal(rescueRideFocus({ focusWasIn: "off", before: on, now: off, focusLost: true }), false, "the off-route buttons came, not went");
});

test("rescueRideFocus: back on route with the focus on Re-plan or Keep rescues it; leaving DC with it on 311 too", () => {
  assert.equal(rescueRideFocus({ focusWasIn: "off", before: off, now: { off: false, show311: false }, focusLost: true }), true);
  assert.equal(rescueRideFocus({ focusWasIn: "311", before: on, now: { off: false, show311: false }, focusLost: true }), true);
  assert.equal(rescueRideFocus({ focusWasIn: "311", before: off, now: on, focusLost: true }), false);
});

test("afterHistoryStep: the other button, else the heading, only when the pressed one is unusable and the focus lost", () => {
  const body = { id: "body" };
  const undo = { id: "undo", ok: false };
  const redo = { id: "redo", ok: true };
  const usable = (e: { ok?: boolean }) => e.ok === true;
  assert.equal(afterHistoryStep({ button: undo, other: redo }, body, body, usable), "other");
  assert.equal(afterHistoryStep({ button: undo, other: redo }, undo, body, usable), "other", "still on the disabled button");
  assert.equal(afterHistoryStep({ button: undo, other: null }, body, body, usable), "heading");
  assert.equal(afterHistoryStep({ button: undo, other: { ok: false } }, null, body, usable), "heading");
  assert.equal(afterHistoryStep({ button: redo, other: undo }, body, body, usable), "stay", "the pressed one still works");
  assert.equal(afterHistoryStep({ button: undo, other: redo }, { id: "search" }, body, usable), "stay", "the focus is somewhere fine");
});
