// Accessibility mode's logic (OWNER-DECISIONS 455; lib/accessMode.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ACCESS_MODE_KEY,
  ACCESS_OFF_LABEL,
  ACCESS_ON_LABEL,
  accessModeLabel,
  accessModeSaid,
  mapToolsWays,
  readAccessMode,
  writeAccessMode,
  type KeyValueStore,
} from "./accessMode.ts";

function memory(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}
const refusing: KeyValueStore = {
  getItem() {
    throw new Error("blocked");
  },
  setItem() {
    throw new Error("blocked");
  },
};

test("off by default: nothing kept, no storage, or storage that refuses", () => {
  assert.equal(readAccessMode(memory()), false);
  assert.equal(readAccessMode(null), false);
  assert.equal(readAccessMode(refusing), false);
});

test("what is written is read back, and only 'on' means on", () => {
  const store = memory();
  assert.equal(writeAccessMode(true, store), true);
  assert.equal(store.data.get(ACCESS_MODE_KEY), "on");
  assert.equal(readAccessMode(store), true);
  assert.equal(writeAccessMode(false, store), true);
  assert.equal(readAccessMode(store), false);
  store.data.set(ACCESS_MODE_KEY, "yes");
  assert.equal(readAccessMode(store), false);
});

test("writing works without storage: it reports false and does not throw", () => {
  assert.equal(writeAccessMode(true, null), false);
  assert.equal(writeAccessMode(true, refusing), false);
});

test("the toggle's name is what pressing it does; the announcement says where it went", () => {
  assert.equal(accessModeLabel(false), "Turn on accessibility mode");
  assert.equal(accessModeLabel(true), "Turn off accessibility mode");
  assert.equal(ACCESS_ON_LABEL, accessModeLabel(false));
  assert.equal(ACCESS_OFF_LABEL, accessModeLabel(true));
  assert.match(accessModeSaid(true), /^Accessibility mode on\./);
  assert.match(accessModeSaid(false), /^Accessibility mode off\./);
});

test("the keyboard's ways name Map tools in both states, and say how to get it when it is off", () => {
  for (const on of [true, false]) {
    const w = mapToolsWays(on);
    assert.match(w.addPoint, /"Add point at map center" in Map tools/);
    assert.match(w.roadAndAdd, /Map tools .*Road info at map center and Add point at map center/);
  }
  assert.doesNotMatch(mapToolsWays(true).addPoint, /accessibility mode/);
  assert.match(mapToolsWays(false).addPoint, /^turn on accessibility mode/);
  assert.match(mapToolsWays(false).roadAndAdd, /^turn on accessibility mode/);
});
