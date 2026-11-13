// The parts loaded on first use (app/later.tsx): nothing shows until their code is in, a failed load shows nothing
// and is asked for again, a dialog once opened stays mounted, and the idle preload fetches each part once.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { render } from "../testSupport/render.ts";
import { Once, later, preloadLater } from "./later.tsx";

function Words({ word }: { word: string }) {
  return <p>{word}</p>;
}

/** A part whose loads the test answers by hand. */
function part() {
  const asked: Array<{ ok: () => Promise<void>; fail: () => Promise<void> }> = [];
  const Part = later(
    () =>
      new Promise<typeof Words>((resolve, reject) => {
        asked.push({
          ok: () => act(async () => resolve(Words)),
          fail: () => act(async () => reject(new Error("offline"))),
        });
      }),
  );
  return { Part, asked };
}

test("a later part shows nothing until its code is in, then shows; the idle preload fetches it once", async () => {
  const { Part, asked } = part();
  let idle: (() => void) | null = null;
  preloadLater((run) => (idle = run));
  const screen = await render(<Part word="Roam" />);
  assert.equal(screen.text(), "", "nothing while the part's code arrives");
  idle!();
  preloadLater(() => assert.fail("the preload runs once"));
  assert.equal(asked.length, 1, "rendering and the preload share one load");
  await asked[0].ok();
  assert.equal(screen.text(), "Roam");
});

test("a part whose code does not arrive shows nothing, never an error, and is asked for again once back online", async () => {
  const { Part, asked } = part();
  const screen = await render(<Part word="Riders" />);
  await asked[0].fail();
  assert.equal(screen.text(), "");
  await act(async () => {
    window.dispatchEvent(new window.Event("online"));
  });
  assert.equal(asked.length, 2, "asked again");
  await asked[1].ok();
  assert.equal(screen.text(), "Riders");
});

test("Once renders a part from the first time it is wanted, and keeps it mounted after", async () => {
  const shown = (when: boolean) => (
    <Once when={when}>
      <Words word="Share card" />
    </Once>
  );
  const screen = await render(shown(false));
  assert.equal(screen.text(), "", "never wanted: not rendered, so its code is not fetched for it");
  await screen.rerender(shown(true));
  assert.equal(screen.text(), "Share card");
  await screen.rerender(shown(false));
  assert.equal(screen.text(), "Share card", "closed: still mounted, as the dialog was before it was split out");
});
