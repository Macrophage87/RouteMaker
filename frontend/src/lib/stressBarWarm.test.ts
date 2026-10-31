// The stress bar's half steps in the warm palette (?palette=blended), which the address picks when the page loads:
// this file has its own process (node --test), so it loads the palette before the modules read it.
import { test } from "node:test";
import assert from "node:assert/strict";

Object.defineProperty(globalThis, "location", { configurable: true, value: { search: "?palette=blended" } });

test("in the warm palette too, each half step in the bar is the route line's colour for it", async () => {
  const { currentPalette, HALF_PALETTES } = await import("../stressStyle.js");
  const { routeClasses } = await import("./routeColours.ts");
  const { stressSegments } = await import("./stressBar.ts");
  assert.equal(currentPalette(), "blended");
  const spans = [1, 2, 3, 4].map((tier, i) => ({ from_m: i * 100, to_m: i * 100 + 100, tier, facility: null, half: true }));
  const segments = stressSegments({}, spans);
  const classes = new Map(routeClasses().map((c) => [c.key as string, c]));
  for (const tier of [1, 2, 3, 4] as const) {
    const seg = segments.find((s) => s.key === `${tier}h`)!;
    assert.equal(seg.color, HALF_PALETTES.blended[tier].color, `${tier}.5`);
    assert.equal(seg.color, classes.get(`${tier}h`)!.color, `${tier}.5 as on the line`);
    assert.equal(seg.dash, undefined, "a colour of its own, no dash");
  }
});
