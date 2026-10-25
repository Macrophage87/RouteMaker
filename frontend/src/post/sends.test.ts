// Featured routes Send buttons: one press sends once, and what it did shows in a popup (post/sends.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { POPUP_MS, SEND_FAILED, SENDING_SAID, wireSends } from "./sends.ts";

function element(dataset: Record<string, string> = {}) {
  const handlers: (() => void)[] = [];
  const classes = new Set<string>();
  return {
    dataset,
    disabled: true,
    textContent: "",
    classList: {
      toggle: (name: string, on: boolean) => void (on ? classes.add(name) : classes.delete(name)),
      remove: (name: string) => void classes.delete(name),
      has: (name: string) => classes.has(name),
    },
    addEventListener: (_kind: string, run: () => void) => void handlers.push(run),
    click: () => handlers.forEach((run) => run()),
  };
}

function page(sends: Record<string, () => Promise<string>>) {
  const button = element({ send: "garmin" });
  const said = element();
  const timers: [() => void, number][] = [];
  const doc = { querySelectorAll: () => [button] } as unknown as Pick<Document, "querySelectorAll">;
  wireSends(doc, said as unknown as HTMLElement, sends, (run, ms) => timers.push([run, ms]));
  return { button, said, timers };
}

const settle = () => new Promise((done) => setImmediate(done));

test("a press sends once, the button stays off, and the outcome pops up until its time is up", async () => {
  let sent = 0;
  const { button, said, timers } = page({ garmin: async () => (sent++, "Sent to Garmin Connect.") });
  assert.equal(button.disabled, false);
  button.click();
  assert.equal(said.textContent, SENDING_SAID);
  assert.equal(said.classList.has("popup"), false);
  button.click();
  button.click();
  await settle();
  assert.equal(sent, 1);
  assert.equal(button.disabled, true);
  assert.equal(said.textContent, "Sent to Garmin Connect.");
  assert.equal(said.classList.has("popup"), true);
  assert.equal(timers[0][1], POPUP_MS);
  timers[0][0]();
  assert.equal(said.classList.has("popup"), false);
});

test("a failed send says so and turns the button back on", async () => {
  const { button, said } = page({ garmin: () => Promise.reject(new Error("no")) });
  button.click();
  await settle();
  assert.equal(said.textContent, SEND_FAILED);
  assert.equal(said.classList.has("popup"), true);
  assert.equal(button.disabled, false);
});

test("a tap puts the popup away", async () => {
  const { button, said } = page({ garmin: async () => "Saved." });
  button.click();
  await settle();
  said.click();
  assert.equal(said.classList.has("popup"), false);
});
