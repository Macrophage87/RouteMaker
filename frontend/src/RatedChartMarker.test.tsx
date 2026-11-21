// A junction's mark on the charts, as the rider sees it, rendered (testSupport/render.ts): the rated dot where the
// raters set its level (the owner, 2026-11-15), the triangle or diamond where the model priced it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
import { CrossingMarker } from "./chartParts.tsx";

test("a rated junction's chart mark is a small colour dot named by its level", async () => {
  const screen = await render(
    <svg>
      <CrossingMarker severity="red" rated={4.5} x={10} y={10} />
      <CrossingMarker severity="red" rated={5} x={30} y={10} />
      <CrossingMarker severity="orange" x={50} y={10} />
    </svg>,
  );
  const dots = [...screen.container.querySelectorAll(".rated-dot")];
  assert.deepEqual(dots.map((d) => d.getAttribute("aria-label")), ["LTS 4.5", "Avoid"]);
  assert.deepEqual(dots.map((d) => d.textContent), ["", ""], "colour only: nothing written on the dot");
  assert.equal(screen.container.querySelectorAll("svg > path").length, 1, "the unrated one keeps its triangle");
});
