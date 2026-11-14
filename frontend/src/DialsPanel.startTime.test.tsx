// Plan's Leave at (lib/startTime.ts; the owner, 2026-11-13: Plan only), as the rider sees it in When: rendered.
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render, type } from "./testSupport/render.ts";
import { DialsPanel } from "./DialsPanel.tsx";
import { startDials, type Dials } from "./lib/dials.ts";
import { wallClock } from "./lib/startTime.ts";

/** A When radio by the words of the label it sits in (the helper names an input by its own text, which a wrapped radio has none of). */
function radio(screen: { container: HTMLElement }, words: string | RegExp): HTMLInputElement {
  const found = [...screen.container.querySelectorAll<HTMLInputElement>('input[type="radio"]')].filter((input) => {
    const text = (input.closest("label")?.textContent ?? "").replace(/\s+/g, " ").trim();
    return typeof words === "string" ? text === words : words.test(text);
  });
  assert.equal(found.length, 1, String(words));
  return found[0];
}

const leaveAtCount = (screen: { container: HTMLElement }) =>
  [...screen.container.querySelectorAll("label")].filter((l) => l.textContent?.trim().startsWith("Leave at")).length;

async function panel(dials: Dials, startTime = true) {
  const commits: Dials[] = [];
  const screen = await render(<DialsPanel preset="default" dials={dials} onCommit={(d) => commits.push(d)} startTime={startTime} />);
  return { screen, commits };
}

test("Go's When has no Leave at; Plan's has it, and no time box until it is picked", async () => {
  const go = await panel(startDials("default"), false);
  assert.equal(leaveAtCount(go.screen), 0);
  await go.screen.unmount();
  const { screen, commits } = await panel(startDials("default"));
  assert.equal(screen.container.querySelectorAll('input[type="datetime-local"]').length, 0);
  await click(radio(screen, "Leave at"));
  assert.equal(commits.length, 1);
  // Our default: the next whole hour, in Washington's time.
  assert.match(commits[0].startAt ?? "", /^\d{4}-\d{2}-\d{2}T\d{2}:00$/);
  assert.equal(commits[0].when, null);
});

test("with a start set, the box shows it; a time typed in the past stays as typed with a hint, and is not planned", async () => {
  const later = wallClock(Date.now() + 2 * 86_400_000).slice(0, 11) + "08:00";
  const { screen, commits } = await panel({ ...startDials("default"), startAt: later });
  assert.ok(radio(screen, "Leave at").matches(":checked"));
  const box = screen.container.querySelector<HTMLInputElement>('input[type="datetime-local"]')!;
  assert.equal(box.value, later);
  await type(box, "2020-01-01T08:00");
  assert.equal(commits.length, 0, "a past time is not planned");
  assert.equal(box.value, "2020-01-01T08:00", "what is typed is not put back");
  assert.equal(box.getAttribute("aria-invalid"), "true");
  assert.match(screen.text(), /Pick a time from now to a year ahead\./);
  const next = wallClock(Date.now() + 3 * 86_400_000).slice(0, 11) + "09:30";
  await type(box, next);
  assert.equal(commits.at(-1)?.startAt, next);
  assert.doesNotMatch(screen.text(), /Pick a time/);
});

test("Now and the ride-time bands take the start time away", async () => {
  const later = wallClock(Date.now() + 2 * 86_400_000).slice(0, 11) + "08:00";
  const { screen, commits } = await panel({ ...startDials("default"), startAt: later });
  await click(radio(screen, /^Now/));
  assert.equal(commits.at(-1)?.startAt, undefined);
  await click(radio(screen, "Weekend"));
  assert.equal(commits.at(-1)?.startAt, undefined);
  assert.equal(commits.at(-1)?.when, "weekend");
});
