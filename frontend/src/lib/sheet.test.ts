// The panel's decisions, as properties: what opens a hidden sheet, what comes
// first in it on a phone, what takes the focus, which key cancels.
import { test } from "node:test";
import assert from "node:assert/strict";
import { focusesPlanButton, isCancelKey, opensSheet, sheetOrder, type StatusKind } from "./sheet.ts";

const KINDS: StatusKind[] = ["idle", "loading", "waiting", "ok", "error", "confirm"];
const NEEDS_THE_RIDER: StatusKind[] = ["error", "confirm"];

test("a question or an error opens a hidden sheet; nothing else does", () => {
  for (const kind of KINDS) {
    assert.equal(opensSheet(kind), NEEDS_THE_RIDER.includes(kind), kind);
  }
});

test("every order is the same three sections, once each", () => {
  for (const narrow of [false, true]) {
    for (const kind of KINDS) {
      for (const hasRoute of [false, true]) {
        const order = sheetOrder(narrow, kind, hasRoute);
        assert.deepEqual([...order].sort(), ["points", "presets", "route"]);
      }
    }
  }
});

test("on a desktop the sections never move", () => {
  const first = sheetOrder(false, "idle", false);
  assert.notEqual(first[0], "route");
  for (const kind of KINDS) {
    for (const hasRoute of [false, true]) {
      assert.deepEqual(sheetOrder(false, kind, hasRoute), first, `${kind} ${hasRoute}`);
    }
  }
});

test("on a phone a route, a question or an error comes first; otherwise the route is last", () => {
  for (const kind of KINDS) {
    assert.equal(sheetOrder(true, kind, true)[0], "route", `route showing, ${kind}`);
    const order = sheetOrder(true, kind, false);
    if (NEEDS_THE_RIDER.includes(kind)) assert.equal(order[0], "route", kind);
    else assert.equal(order.at(-1), "route", kind);
  }
});

test("a route that comes first keeps the other two in their desktop order", () => {
  const desktop = sheetOrder(false, "ok", true).filter((s) => s !== "route");
  assert.deepEqual(sheetOrder(true, "ok", true).slice(1), desktop);
});

test("the long-ride question takes the focus only once the sheet is open", () => {
  for (const kind of KINDS) {
    for (const open of [false, true]) {
      assert.equal(focusesPlanButton(kind, open), kind === "confirm" && open, `${kind} ${open}`);
    }
  }
});

test("Escape cancels the long-ride question; other keys do not", () => {
  assert.equal(isCancelKey("Escape"), true);
  for (const key of ["Enter", " ", "Tab", "e", "Backspace", ""]) assert.equal(isCancelKey(key), false, key);
});
