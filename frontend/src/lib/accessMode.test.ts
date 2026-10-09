// Accessibility mode's logic (OWNER-DECISIONS 455; lib/accessMode.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ACCESS_HELP,
  ACCESS_MODE_KEY,
  ACCESS_LABEL,
  ACCESS_SENTENCE,
  ACCESS_SENTENCE_WHERE,
  accessModeSaid,
  accessModeToggle,
  browserStore,
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

test("the switch's name is constant (aria-pressed carries the state); the announcement says where it went", () => {
  assert.equal(ACCESS_LABEL, "Accessibility mode");
  // The whole text: its second half is the only place a screen reader learns where Map tools went (mutation U18).
  assert.equal(accessModeSaid(true), "Accessibility mode on. Map tools is by the map's zoom buttons.");
  assert.equal(accessModeSaid(false), "Accessibility mode off. Map tools is hidden.");
});

test("a press: only the first button turning it on moves the focus to Map tools (455a(2)), and it says the new state", () => {
  assert.deepEqual(accessModeToggle(false, true), { next: true, said: accessModeSaid(true), focusTools: true });
  assert.deepEqual(accessModeToggle(false, false), { next: true, said: accessModeSaid(true), focusTools: false });
  assert.deepEqual(accessModeToggle(true, true), { next: false, said: accessModeSaid(false), focusTools: false });
  assert.deepEqual(accessModeToggle(true, false), { next: false, said: accessModeSaid(false), focusTools: false });
});

test("the owner's sentence (455a(4)), with where the switch is outside More tips, and once in More tips' own line", () => {
  assert.equal(ACCESS_SENTENCE, "For keyboard or screen reader use, turn on accessibility mode.");
  assert.equal(ACCESS_SENTENCE_WHERE, "For keyboard or screen reader use, turn on accessibility mode (the first button on the page, or in More tips).");
  assert.equal(
    ACCESS_HELP,
    "For keyboard or screen reader use, turn on accessibility mode. It adds Map tools by the map's zoom buttons and is kept on this device. It is also the first button on the page.",
  );
});

/** Runs `body` with globalThis.localStorage replaced by `descriptor`, then puts the original back. */
function withLocalStorage(descriptor: PropertyDescriptor, body: () => void) {
  const before = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, ...descriptor });
  try {
    body();
  } finally {
    if (before) Object.defineProperty(globalThis, "localStorage", before);
    else delete (globalThis as { localStorage?: unknown }).localStorage;
  }
}

test("the browser's storage: reaching it throws (blocked site data) or it is not there - off, nothing throws (mutation U4)", () => {
  const throwing: PropertyDescriptor = {
    get(): never {
      throw new Error("SecurityError");
    },
  };
  for (const descriptor of [throwing, { value: undefined, writable: true }]) {
    withLocalStorage(descriptor, () => {
      assert.equal(browserStore(), null);
      assert.equal(readAccessMode(), false);
      assert.equal(writeAccessMode(true), false);
    });
  }
});

test("the browser's storage when it works: the defaults use it", () => {
  const store = memory();
  withLocalStorage({ value: store, writable: true }, () => {
    assert.equal(browserStore(), store);
    assert.equal(writeAccessMode(true), true);
    assert.equal(store.data.get(ACCESS_MODE_KEY), "on");
    assert.equal(readAccessMode(), true);
  });
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
  // Shown only in More tips, which says where the switch is once, in its own line (the spec review's SF4).
  assert.doesNotMatch(mapToolsWays(false).addPoint + mapToolsWays(false).roadAndAdd, /first button/);
});
