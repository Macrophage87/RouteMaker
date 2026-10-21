import { test } from "node:test";
import assert from "node:assert/strict";
import { COMPUTER_OK_KEY, askBeforeStart, looksLikePhone, rememberStartAnyway } from "./startOnComputer.ts";

const store = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
};

test("a phone is a finger as the main pointer; no matchMedia is not a phone", () => {
  assert.equal(looksLikePhone((q) => ({ matches: q === "(pointer: coarse)" })), true);
  assert.equal(looksLikePhone(() => ({ matches: false })), false);
  assert.equal(looksLikePhone(null), false);
});

test("Start ride asks on a computer until Start anyway, then not again in the tab; never on a phone", () => {
  const s = store();
  assert.equal(askBeforeStart(true, s), false);
  assert.equal(askBeforeStart(false, s), true);
  rememberStartAnyway(s);
  assert.equal(s.getItem(COMPUTER_OK_KEY), "yes");
  assert.equal(askBeforeStart(false, s), false);
  // No storage (a private window): asks each time, and Start anyway does not throw.
  assert.equal(askBeforeStart(false, null), true);
  rememberStartAnyway(null);
});
