// The panel's points list, rendered (MERGE-SEARCH re-check R16).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PointsList } from "./pointsList.ts";
import type { PointRow } from "./geocode.ts";

const ROWS: PointRow[] = [
  { role: "Start", place: { name: "Lincoln Memorial", label: "Lincoln Memorial, Washington" }, coords: "38.8893, -77.0502" },
  { role: "Via 1", place: undefined, coords: "38.9000, -77.0200" },
  { role: "End", place: undefined, coords: "38.8978, -77.0074" },
];

function render(rows: readonly PointRow[]): string {
  return renderToStaticMarkup(createElement(PointsList, { rows, onRemove: () => {}, removeRef: () => {} }));
}

const cells = (html: string, cls: string) =>
  [...html.matchAll(new RegExp(`<span class="${cls}"[^>]*>([^<]*)</span>`, "g"))].map((m) => m[1]);

test("each row names its point's role, then its place or its coordinates", () => {
  const html = render(ROWS);
  assert.deepEqual(cells(html, "point-name"), ["Start", "Via 1", "End"]);
  assert.deepEqual(cells(html, "place-name"), ["Lincoln Memorial"]);
  assert.deepEqual(cells(html, "coords"), ["38.8893, -77.0502", "38.9000, -77.0200", "38.8978, -77.0074"]);
  assert.match(html, /title="Lincoln Memorial, Washington \(38\.8893, -77\.0502\)"/);
});

test("each Remove button says which point it removes", () => {
  const labels = [...render(ROWS).matchAll(/aria-label="([^"]*)"/g)].map((m) => m[1]);
  assert.deepEqual(labels, ["Remove Start", "Remove Via 1", "Remove End"]);
});

test("App shows the list from pointRows, with its removal and focus wiring", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /<PointsList\s+rows=\{pointRows\(points, namer\)\}\s+onRemove=\{removeAt\}/);
  assert.match(app, /removeRefs\.current\[index\] = button;/);
});

test("each Remove button removes its own point, and hands its own row's button for the focus", () => {
  // Round-1 mutants F13 and F14: every button removing point 0, or every
  // button registered as point 0's, passed a test that only rendered markup.
  const removed: number[] = [];
  const refs: Array<[number, unknown]> = [];
  const list = PointsList({
    rows: ROWS,
    onRemove: (index) => removed.push(index),
    removeRef: (index, button) => refs.push([index, button]),
  }) as unknown as { props: { children: Array<{ props: { children: unknown[] } }> } };
  const items = list.props.children;
  assert.equal(items.length, ROWS.length);
  items.forEach((item, index) => {
    const button = item.props.children.at(-1) as { props: { onClick: () => void; ref: (b: unknown) => void } };
    button.props.onClick();
    const stand_in = { index };
    button.props.ref(stand_in);
    assert.deepEqual(removed.at(-1), index);
    assert.deepEqual(refs.at(-1), [index, stand_in]);
  });
  assert.deepEqual(removed, [0, 1, 2]);
});
