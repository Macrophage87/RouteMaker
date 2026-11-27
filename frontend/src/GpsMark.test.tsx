import assert from "node:assert/strict";
import { test } from "node:test";
import { GpsMark, gpsMarkText } from "./GpsMark.tsx";
import { render, spokenText } from "./testSupport/render.ts";

test("the mark shows the rider's spot, latitude first, to about a metre", async () => {
  const screen = await render(<GpsMark point={[-77.0234149, 38.8871234]} />);
  const mark = screen.container.querySelector(".ride-gps-mark");
  assert.equal(mark?.textContent, "38.88712, -77.02341");
  // Screen readers have Where am I?; the numbers are for screenshots only.
  assert.equal(mark?.getAttribute("aria-hidden"), "true");
  assert.equal(spokenText(screen.container).includes("38.88712"), false);
});

test("no fix yet, or a broken one: no mark", async () => {
  for (const point of [null, [Number.NaN, 38.9] as [number, number]]) {
    const screen = await render(<GpsMark point={point} />);
    assert.equal(screen.container.querySelector(".ride-gps-mark"), null);
  }
});

test("the text reads as a map search box takes it", () => {
  assert.equal(gpsMarkText([-76.6, 39.3]), "39.30000, -76.60000");
});
