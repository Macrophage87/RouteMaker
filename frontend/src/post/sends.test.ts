// Featured routes Send buttons: a press under way is not sent again, and what it did shows in a popup
// (post/sends.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { POPUP_MS, SEND_FAILED, SENDING_SAID, wireSends } from "./sends.ts";

function element(dataset: Record<string, string> = {}) {
  const handlers: (() => void)[] = [];
  const attributes = new Map<string, string>();
  return {
    dataset,
    disabled: true,
    hidden: false,
    className: "",
    textContent: "",
    setAttribute: (name: string, value: string) => void attributes.set(name, value),
    getAttribute: (name: string) => attributes.get(name) ?? null,
    removeAttribute: (name: string) => void attributes.delete(name),
    addEventListener: (_kind: string, run: () => void) => void handlers.push(run),
    click: () => handlers.forEach((run) => run()),
  };
}

function page(sends: Record<string, () => Promise<string>>) {
  const button = element({ send: "garmin" });
  const said = element();
  const popup = element();
  const timers: [() => void, number][] = [];
  const doc = {
    querySelectorAll: () => [button],
    createElement: () => popup,
    body: { append: () => {} },
  } as unknown as Pick<Document, "querySelectorAll" | "createElement" | "body">;
  wireSends(doc, said as unknown as HTMLElement, sends, (run, ms) => timers.push([run, ms]));
  return { button, said, popup, timers };
}

const settle = () => new Promise((done) => setImmediate(done));

test("presses while a send is under way send nothing more, and the outcome pops up until its time is up", async () => {
  let sent = 0;
  const { button, said, popup, timers } = page({ garmin: async () => (sent++, "Sent to Garmin Connect.") });
  assert.equal(button.disabled, false);
  assert.equal(popup.getAttribute("aria-hidden"), "true");
  button.click();
  assert.equal(said.textContent, SENDING_SAID);
  assert.equal(popup.hidden, true);
  assert.equal(button.getAttribute("aria-disabled"), "true");
  button.click();
  button.click();
  await settle();
  assert.equal(sent, 1);
  assert.equal(said.textContent, "Sent to Garmin Connect.");
  assert.equal(popup.textContent, "Sent to Garmin Connect.");
  assert.equal(popup.hidden, false);
  // Said, so the button works again.
  assert.equal(button.getAttribute("aria-disabled"), null);
  assert.equal(timers[0][1], POPUP_MS);
  timers[0][0]();
  assert.equal(popup.hidden, true);
});

test("an older popup's time does not hide a newer one", async () => {
  const { button, popup, timers } = page({ garmin: async () => "Saved." });
  button.click();
  await settle();
  button.click();
  await settle();
  timers[0][0]();
  assert.equal(popup.hidden, false);
  timers[1][0]();
  assert.equal(popup.hidden, true);
});

test("a failed send says so and the button works again", async () => {
  const { button, said, popup } = page({ garmin: () => Promise.reject(new Error("no")) });
  button.click();
  await settle();
  assert.equal(said.textContent, SEND_FAILED);
  assert.equal(popup.hidden, false);
  assert.equal(button.getAttribute("aria-disabled"), null);
});

test("a tap puts the popup away", async () => {
  const { button, popup } = page({ garmin: async () => "Saved." });
  button.click();
  await settle();
  popup.click();
  assert.equal(popup.hidden, true);
});
