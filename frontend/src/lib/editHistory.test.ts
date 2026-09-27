// Undo for the point list, and the key that asks for it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { EditHistory, UNDO_LIMIT, isUndoKey, typesText } from "./editHistory.ts";

test("undo gives back the list as it was before each edit, newest first", () => {
  const history = new EditHistory<string[]>();
  history.record(["a"]);
  history.record(["a", "b"]);
  assert.equal(history.size, 2);
  assert.deepEqual(history.undo(), ["a", "b"]);
  assert.deepEqual(history.undo(), ["a"]);
  assert.equal(history.undo(), undefined);
  assert.equal(history.size, 0);
});

test("nothing to undo is not an error", () => {
  const history = new EditHistory<number>();
  assert.equal(history.canUndo, false);
  assert.equal(history.undo(), undefined);
  history.record(1);
  assert.equal(history.canUndo, true);
});

test("the oldest edits are forgotten past the limit, the newest kept", () => {
  const history = new EditHistory<number>(3);
  for (let i = 1; i <= 5; i += 1) history.record(i);
  assert.equal(history.size, 3);
  assert.deepEqual([history.undo(), history.undo(), history.undo(), history.undo()], [5, 4, 3, undefined]);
});

test("the default limit keeps at least one level, and a limit below one keeps one", () => {
  assert.ok(UNDO_LIMIT >= 1);
  const history = new EditHistory<number>(0);
  history.record(1);
  history.record(2);
  assert.equal(history.size, 1);
  assert.equal(history.undo(), 2);
});

test("clear forgets everything (a new plan from a link)", () => {
  const history = new EditHistory<number>();
  history.record(1);
  history.clear();
  assert.equal(history.canUndo, false);
});

const key = (k: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; shiftKey: boolean; altKey: boolean }> = {}) => ({
  key: k,
  ctrlKey: false,
  metaKey: false,
  shiftKey: false,
  altKey: false,
  ...mods,
});

test("Ctrl+Z and Cmd+Z are undo, with either case of z", () => {
  assert.equal(isUndoKey(key("z", { ctrlKey: true })), true);
  assert.equal(isUndoKey(key("z", { metaKey: true })), true);
  assert.equal(isUndoKey(key("Z", { ctrlKey: true })), true);
});

test("Z alone, redo's Shift, and Alt combinations are not undo", () => {
  assert.equal(isUndoKey(key("z")), false);
  assert.equal(isUndoKey(key("z", { ctrlKey: true, shiftKey: true })), false);
  assert.equal(isUndoKey(key("z", { ctrlKey: true, altKey: true })), false);
  assert.equal(isUndoKey(key("y", { ctrlKey: true })), false);
});

test("a text field keeps its own undo; buttons, radios and the map do not", () => {
  assert.equal(typesText({ tagName: "TEXTAREA" }), true);
  assert.equal(typesText({ tagName: "INPUT", type: "text" }), true);
  assert.equal(typesText({ tagName: "INPUT", type: "search" }), true);
  assert.equal(typesText({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(typesText({ tagName: "INPUT", type: "radio" }), false);
  assert.equal(typesText({ tagName: "INPUT", type: "checkbox" }), false);
  assert.equal(typesText({ tagName: "BUTTON" }), false);
  assert.equal(typesText({ tagName: "CANVAS" }), false);
  assert.equal(typesText(null), false);
});
