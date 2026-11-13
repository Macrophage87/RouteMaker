// The parts loaded on first use (app/later.tsx): nothing shows until their code is in, a dialog once opened stays
// mounted, and the idle preload fetches each part once.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { render } from "../testSupport/render.ts";
import { Later, Once, later, preloadLater } from "./later.tsx";

let loads = 0;
let release: () => void = () => {};
const arrived = new Promise<void>((resolve) => (release = resolve));
const Part = later(async () => {
  loads += 1;
  await arrived;
  return function Part({ word }: { word: string }) {
    return <p>{word}</p>;
  };
});

test("a later part shows nothing until its code is in, then shows; the idle preload fetches it once, in the background", async () => {
  let idle: (() => void) | null = null;
  preloadLater((run) => (idle = run));
  assert.equal(loads, 0, "nothing loads until the page is idle");
  const screen = await render(
    <Later>
      <Part word="Roam" />
    </Later>,
  );
  assert.equal(screen.text(), "", "nothing while the part's code arrives");
  idle!();
  preloadLater(() => assert.fail("the preload runs once"));
  await act(async () => {
    release();
    await arrived;
  });
  assert.equal(screen.text(), "Roam");
  assert.equal(loads, 1, "rendering and the preload share one load");
});

test("Once renders a part from the first time it is wanted, and keeps it mounted after", async () => {
  const shown = (when: boolean) => (
    <Once when={when}>
      <Part word="Share card" />
    </Once>
  );
  const screen = await render(shown(false));
  assert.equal(screen.text(), "", "never wanted: not rendered, so its code is not fetched for it");
  await screen.rerender(shown(true));
  await act(async () => {
    await arrived;
  });
  assert.equal(screen.text(), "Share card");
  await screen.rerender(shown(false));
  assert.equal(screen.text(), "Share card", "closed: still mounted, as the dialog was before it was split out");
});
