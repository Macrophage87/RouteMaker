// Go's stress figure (app/RoutePanel.tsx StressFigure), as the rider sees it: the line under the bar names the worst
// stretch's street, and a tap on the bar shows that stretch on the map (the 2026-11-12 backlog, Go item 9). Rendered on
// a made-up route.
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "../testSupport/render.ts";
import { StressFigure } from "./RoutePanel.tsx";
import type { RouteResponse, StressSpan } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { stressSegments } from "../lib/stressBar.ts";

const LINE: LonLat[] = Array.from({ length: 400 }, (_, i) => [-77.05 + i * 0.000128, 38.9]);
const span = (from_m: number, to_m: number, tier: number): StressSpan => ({ from_m, to_m, tier, facility: null });

function route(spans: StressSpan[], street: string | null = "Big Road"): RouteResponse {
  const metres: Record<string, number> = {};
  for (const s of spans) metres[String(s.tier)] = (metres[String(s.tier)] ?? 0) + s.to_m - s.from_m;
  return {
    geometry: { type: "LineString", coordinates: LINE },
    distance_m: 4400,
    duration_s: 900,
    stress_spans: spans,
    stress_m: metres,
    facility_m: { none: 4400 },
    description: [
      { kind: "stretch", from_m: 0, to_m: 1000, street: "Side Street", tier: 2 },
      { kind: "stretch", from_m: 1000, to_m: 2000, street, tier: 4 },
      { kind: "stretch", from_m: 2000, to_m: 4400, street: "Side Street", tier: 2 },
    ],
  } as unknown as RouteResponse;
}

const BUSY = [span(0, 1000, 2), span(1000, 2000, 4), span(2000, 4400, 2)];

function figure(r: RouteResponse, onWorst?: (line: LonLat[]) => void) {
  return render(<StressFigure segments={stressSegments(r.stress_m ?? {})} go={{ route: r, peek: false, onWorst }} />);
}

test("the line names the worst stretch's street, and a tap on the bar shows that stretch", async () => {
  const shown: LonLat[][] = [];
  const screen = await figure(route(BUSY), (line) => shown.push(line));
  assert.match(screen.text(), /busy road for 0\.6 mi \(1\.0 km\), worst on Big Road/);
  const bar = screen.all("button")[0];
  assert.equal(document.getElementById(bar.getAttribute("aria-describedby") ?? "")?.textContent, "Shows the busiest stretch on the map.");
  await click(bar);
  assert.equal(shown.length, 1);
  const lons = shown[0].map((p) => p[0]);
  // The stretch is the route's second 1,000 m: about a quarter to a half of the way along LINE.
  assert.ok(Math.min(...lons) > LINE[80][0] && Math.max(...lons) < LINE[200][0], "only the busy stretch, not the whole route");
});

test("an unnamed worst stretch still shows on a tap; the line says only how much", async () => {
  const shown: LonLat[][] = [];
  const screen = await figure(route(BUSY, null), (line) => shown.push(line));
  assert.match(screen.text(), /busy road for 0\.6 mi \(1\.0 km\)(?!, worst)/);
  await click(screen.all("button")[0]);
  assert.equal(shown.length, 1);
});

test("a calm route's bar is not a button: there is no busy stretch to show", async () => {
  const screen = await figure(route([span(0, 4400, 2)]), () => assert.fail("nothing to show"));
  assert.equal(screen.all("button").length, 0);
  assert.doesNotMatch(screen.text(), /worst on/);
});
