// Plan's keyboard shortcuts (lib/planKeys.ts) and their "?" sheet, as the rider sees them: rendered, not read as source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { useState } from "react";
import { click, render } from "./testSupport/render.ts";
import { PlanKeysDialog } from "./PlanKeysDialog.tsx";
import { characterKey, keyFreeAt, planKeyFor, pointRowAt, readPlanKeys, stepPoint, writePlanKeys } from "./lib/planKeys.ts";

const key = (k: string, mods: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }> = {}) =>
  planKeyFor({ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...mods });

test("each key of the spec asks for its action, and a key with Ctrl, Cmd or Alt is left alone", () => {
  assert.deepEqual(key("/"), { kind: "search" });
  assert.deepEqual(key("r"), { kind: "reverse" });
  assert.deepEqual(key("L"), { kind: "loop" });
  assert.deepEqual(key("Enter"), { kind: "route" });
  assert.deepEqual(key("s"), { kind: "save" });
  assert.deepEqual(key("e"), { kind: "export" });
  assert.deepEqual(key("Delete"), { kind: "remove" });
  assert.deepEqual(key("["), { kind: "previous" });
  assert.deepEqual(key("]"), { kind: "next" });
  assert.deepEqual(key("1"), { kind: "fold", index: 0 });
  assert.deepEqual(key("5"), { kind: "fold", index: 4 });
  assert.equal(key("6"), null);
  assert.deepEqual(key("?", { shiftKey: true }), { kind: "help" });
  assert.equal(key("s", { ctrlKey: true }), null, "Ctrl+S is the browser's");
  assert.equal(key("z", { metaKey: true }), null);
  assert.equal(key("Enter", { ctrlKey: true }), null, "Ctrl+Enter is the plan panel's");
  assert.equal(key("r", { altKey: true }), null);
  assert.equal(key("i"), null, "I is the map's road info");
  assert.equal(key("Backspace"), null, "Backspace is not a shortcut");
  assert.equal(key("R", { shiftKey: true }), null);
  assert.deepEqual(key("/", { shiftKey: true }), { kind: "search" }, "Shift+7 types / on a German keyboard");
  assert.deepEqual(key("[", { ctrlKey: true, altKey: true }), { kind: "previous" }, "AltGr+8 types [ there");
  assert.equal(key("[", { ctrlKey: true }), null);
});

test("the off switch covers the character keys only; Enter and Delete stay (WCAG 2.1.4)", () => {
  assert.equal(characterKey({ kind: "reverse" }), true);
  assert.equal(characterKey({ kind: "help" }), true);
  assert.equal(characterKey({ kind: "fold", index: 0 }), true);
  assert.equal(characterKey({ kind: "route" }), false);
  assert.equal(characterKey({ kind: "remove" }), false);
});

test("no shortcut acts in a text box or a map card, Enter leaves a button its own press, and Delete only a point's row", async () => {
  const screen = await render(
    <div>
      <input aria-label="From" />
      <button type="button">Swap</button>
      <ol className="points">
        <li>
          <button type="button">Remove start</button>
        </li>
        <li>
          <span className="point-steps">
            <button type="button">Up</button>
          </span>
        </li>
        <li>
          <button type="button">Remove end</button>
        </li>
      </ol>
      <div className="maplibregl-popup">
        <button type="button">Go around it</button>
      </div>
      <p>Plain text</p>
    </div>,
  );
  const box = screen.container.querySelector("input");
  const swap = screen.button("Swap");
  const plain = screen.container.querySelector("p");
  assert.equal(keyFreeAt({ kind: "reverse" }, box), false);
  assert.equal(keyFreeAt({ kind: "search" }, box), false);
  assert.equal(keyFreeAt({ kind: "route" }, swap), false);
  assert.equal(keyFreeAt({ kind: "reverse" }, swap), true);
  assert.equal(keyFreeAt({ kind: "route" }, plain), true);
  assert.equal(keyFreeAt({ kind: "export" }, screen.button("Go around it")), false, "a closure card's button");
  assert.equal(keyFreeAt({ kind: "remove" }, screen.button("Remove end")), true);
  assert.equal(pointRowAt(screen.button("Remove start")), 0);
  assert.equal(pointRowAt(screen.button("Remove end")), 2, "the row's place in the list is the point's");
  assert.equal(pointRowAt(screen.button("Up")), null, "a stop being moved is not removed");
  assert.equal(keyFreeAt({ kind: "remove" }, screen.button("Up")), false);
  assert.equal(keyFreeAt({ kind: "remove" }, swap), false, "Delete away from the list removes nothing");
  assert.equal(keyFreeAt({ kind: "remove" }, plain), false);
  assert.equal(keyFreeAt({ kind: "remove" }, document.body), false);
});

test("[ and ] step through the points, from either end when none is picked yet", () => {
  assert.equal(stepPoint(null, 3, 1), 0);
  assert.equal(stepPoint(null, 3, -1), 2);
  assert.equal(stepPoint(0, 3, 1), 1);
  assert.equal(stepPoint(2, 3, 1), 2, "stays on the last");
  assert.equal(stepPoint(0, 3, -1), 0, "stays on the first");
  assert.equal(stepPoint(null, 0, 1), null);
});

test("the switch is kept on this device, on unless turned off, and a refusing store leaves it on", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readPlanKeys(store), true);
  writePlanKeys(false, store);
  assert.equal(readPlanKeys(store), false);
  writePlanKeys(true, store);
  assert.equal(readPlanKeys(store), true);
  const refusing = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(readPlanKeys(refusing), true);
  assert.doesNotThrow(() => writePlanKeys(false, refusing));
});

function Sheet({ onSwitch }: { onSwitch: (on: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Keyboard shortcuts
      </button>
      <PlanKeysDialog
        open={open}
        on={on}
        onSwitch={(next) => {
          setOn(next);
          onSwitch(next);
        }}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

test("the sheet lists every key with what it does, and its switch turns the single keys off", async () => {
  const switched: boolean[] = [];
  const screen = await render(<Sheet onSwitch={(on) => switched.push(on)} />);
  assert.equal(screen.all("dialog").length, 0, "closed at first");
  await click(screen.button("Keyboard shortcuts"));
  const sheet = screen.dialog("Keyboard shortcuts");
  const keys = [...sheet.querySelectorAll("kbd")].map((k) => k.textContent);
  for (const k of ["/", "Enter", "R", "L", "[", "]", "Delete", "S", "E", "1", "5", "?"]) assert.ok(keys.includes(k), k);
  assert.match(sheet.textContent ?? "", /Reverse the points/);
  assert.match(sheet.textContent ?? "", /Download the route as GPX/);
  const toggle = sheet.querySelector<HTMLInputElement>("input[type=checkbox]");
  assert.ok(toggle);
  assert.equal(toggle.checked, true);
  await click(toggle);
  assert.deepEqual(switched, [false]);
  assert.equal(sheet.querySelector<HTMLInputElement>("input[type=checkbox]")?.checked, false);
  await click(screen.button("Close"));
  assert.equal(screen.all("dialog").length, 0, "Close puts it away");
});
