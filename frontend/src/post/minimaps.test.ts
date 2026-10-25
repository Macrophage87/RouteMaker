// Featured routes section minimaps: made near the screen, let go far from it (post/minimaps.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { MINIMAP_FAR, MINIMAP_NEAR, showMinimaps, type Observe } from "./minimaps.ts";

const LINE = [
  [0, 0],
  [1, 1],
];

function page(sections: string[]) {
  const hosts = sections.map((section) => ({ dataset: { section } }) as unknown as HTMLElement);
  return { hosts, doc: { querySelectorAll: () => hosts } as unknown as Pick<Document, "querySelectorAll"> };
}

function watcher() {
  const calls: Record<string, (entries: { target: Element; isIntersecting: boolean }[]) => void> = {};
  const watched: Record<string, Element[]> = {};
  const observe: Observe = (callback, margin) => {
    calls[margin] = callback;
    watched[margin] = [];
    return { observe: (el) => watched[margin].push(el) };
  };
  return { observe, calls, watched };
}

test("each host is drawn with the line its data-section names, and one with no line is left alone", () => {
  const { hosts, doc } = page(["1", "0", "7"]);
  const drawn: [HTMLElement, number[][]][] = [];
  const second = [
    [2, 2],
    [3, 3],
  ];
  showMinimaps(doc, [LINE, second], (host, line) => (drawn.push([host, line]), () => {}), null);
  assert.deepEqual(drawn, [
    [hosts[0], second],
    [hosts[1], LINE],
  ]);
});

test("a minimap is made near the screen once, and let go far from it to be made again on return", () => {
  const { hosts, doc } = page(["0"]);
  const { observe, calls, watched } = watcher();
  let made = 0;
  let gone = 0;
  showMinimaps(doc, [LINE], () => (made++, () => gone++), observe);
  assert.deepEqual(watched[MINIMAP_NEAR], hosts);
  assert.deepEqual(watched[MINIMAP_FAR], hosts);
  calls[MINIMAP_NEAR]([{ target: hosts[0], isIntersecting: true }]);
  calls[MINIMAP_NEAR]([{ target: hosts[0], isIntersecting: true }]);
  assert.equal(made, 1);
  calls[MINIMAP_FAR]([{ target: hosts[0], isIntersecting: false }]);
  assert.equal(gone, 1);
  calls[MINIMAP_NEAR]([{ target: hosts[0], isIntersecting: true }]);
  assert.equal(made, 2);
});

test("a map that cannot be made (no WebGL) leaves the page as it was", () => {
  const { doc } = page(["0"]);
  assert.doesNotThrow(() =>
    showMinimaps(doc, [LINE], () => {
      throw new Error("no WebGL");
    }, null),
  );
});
