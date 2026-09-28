// Undo and redo for the point list, and the keys that ask for them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { EditHistory, UNDO_LIMIT, isRedoKey, isUndoKey, step, typesText } from "./editHistory.ts";

test("undo gives back the list as it was before each edit, newest first", () => {
  const history = new EditHistory<string[]>();
  history.record(["a"]);
  history.record(["a", "b"]);
  assert.equal(history.size, 2);
  assert.deepEqual(history.undo(["a", "b", "c"]), ["a", "b"]);
  assert.deepEqual(history.undo(["a", "b"]), ["a"]);
  assert.equal(history.undo(["a"]), undefined);
  assert.equal(history.size, 0);
});

test("nothing to undo is not an error", () => {
  const history = new EditHistory<number>();
  assert.equal(history.canUndo, false);
  assert.equal(history.undo(0), undefined);
  assert.equal(history.canRedo, false, "an undo that undid nothing leaves nothing to redo");
  history.record(1);
  assert.equal(history.canUndo, true);
});

test("redo gives back what each undo replaced, and undo can take it away again", () => {
  const history = new EditHistory<number>();
  history.record(1); // 1 -> 2
  history.record(2); // 2 -> 3
  assert.equal(history.canRedo, false);
  assert.equal(history.undo(3), 2);
  assert.equal(history.undo(2), 1);
  assert.equal(history.canRedo, true);
  assert.equal(history.redo(1), 2);
  assert.equal(history.redo(2), 3);
  assert.equal(history.redo(3), undefined);
  assert.equal(history.canRedo, false);
  assert.equal(history.undo(3), 2, "a redone edit can be undone");
});

test("nothing to redo is not an error, and leaves undo as it was", () => {
  const history = new EditHistory<number>();
  history.record(1);
  assert.equal(history.redo(2), undefined);
  assert.equal(history.size, 1);
  assert.equal(history.undo(2), 1);
});

test("a new edit after an undo drops what could have been redone", () => {
  const history = new EditHistory<number>();
  history.record(1);
  history.record(2);
  history.undo(3);
  assert.equal(history.canRedo, true);
  history.record(2); // 2 -> 4, a different edit
  assert.equal(history.canRedo, false);
  assert.equal(history.redo(4), undefined);
  assert.equal(history.undo(4), 2);
});

test("the oldest edits are forgotten past the limit, the newest kept", () => {
  const history = new EditHistory<number>(3);
  for (let i = 1; i <= 5; i += 1) history.record(i);
  assert.equal(history.size, 3);
  assert.deepEqual([history.undo(6), history.undo(5), history.undo(4), history.undo(3)], [5, 4, 3, undefined]);
});

test("the default limit keeps at least one level, and a limit below one keeps one", () => {
  assert.ok(UNDO_LIMIT >= 1);
  const history = new EditHistory<number>(0);
  history.record(1);
  history.record(2);
  assert.equal(history.size, 1);
  assert.equal(history.undo(3), 2);
});

test("clear forgets everything, both ways (a new plan from a link)", () => {
  const history = new EditHistory<number>();
  history.record(1);
  history.record(2);
  history.undo(3);
  history.clear();
  assert.equal(history.canUndo, false);
  assert.equal(history.canRedo, false);
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

test("Ctrl+Shift+Z, Cmd+Shift+Z and Ctrl+Y are redo", () => {
  // With Shift held the browser reports the key as "Z".
  assert.equal(isRedoKey(key("Z", { ctrlKey: true, shiftKey: true })), true);
  assert.equal(isRedoKey(key("z", { metaKey: true, shiftKey: true })), true);
  assert.equal(isRedoKey(key("y", { ctrlKey: true })), true);
  assert.equal(isRedoKey(key("Y", { ctrlKey: true })), true);
});

test("undo's own keys, Y or Z alone, Ctrl+Shift+Y and Alt combinations are not redo", () => {
  assert.equal(isRedoKey(key("z", { ctrlKey: true })), false);
  assert.equal(isRedoKey(key("z", { metaKey: true })), false);
  assert.equal(isRedoKey(key("y")), false);
  assert.equal(isRedoKey(key("Z", { shiftKey: true })), false);
  assert.equal(isRedoKey(key("Y", { ctrlKey: true, shiftKey: true })), false);
  assert.equal(isRedoKey(key("Z", { ctrlKey: true, shiftKey: true, altKey: true })), false);
  assert.equal(isRedoKey(key("y", { ctrlKey: true, altKey: true })), false);
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

test("a step of undo goes back and a step of redo forwards", () => {
  const history = new EditHistory<number>();
  history.record(1); // 1 -> 2
  assert.equal(step(history, "redo", 2), undefined, "nothing to redo yet");
  assert.equal(step(history, "undo", 2), 1);
  assert.equal(step(history, "redo", 1), 2);
});
