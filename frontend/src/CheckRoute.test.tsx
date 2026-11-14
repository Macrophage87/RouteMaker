// Check a route (CheckRoute.tsx), as the rider sees it: an opened file's busiest stretches, each calmer way, Use this way.
// Rendered (testSupport/render.ts) on a made-up route; no rider's file.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, render } from "./testSupport/render.ts";
import { CheckRoute } from "./CheckRoute.tsx";
import type { RouteResponse, RouteResult, StressSpan } from "./lib/api.ts";
import { startDials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";

const LINE: LonLat[] = Array.from({ length: 400 }, (_, i) => [-77.05 + i * 0.000128, 38.9]);
const span = (from_m: number, to_m: number, tier: number): StressSpan => ({ from_m, to_m, tier, facility: null });

function route(spans: StressSpan[], extra: Partial<RouteResponse> = {}): RouteResponse {
  return {
    geometry: { type: "LineString", coordinates: LINE },
    distance_m: 4400,
    duration_s: 900,
    stress_spans: spans,
    description: [
      { kind: "stretch", from_m: 0, to_m: 1000, street: "Side Street", tier: 2 },
      { kind: "stretch", from_m: 1000, to_m: 2000, street: "Big Road", tier: 4 },
      { kind: "stretch", from_m: 2000, to_m: 4400, street: "Side Street", tier: 2 },
    ],
    follows_file: true,
    ...extra,
  } as unknown as RouteResponse;
}

const calm: RouteResult = {
  ok: true,
  route: route([span(0, 1500, 1)], { distance_m: 1800, geometry: { type: "LineString", coordinates: [LINE[90], [-77.0, 38.905], LINE[190]] }, description: [] }),
};

/** Let the calmer ways' requests answer. */
const settle = () => act(async () => new Promise((resolve) => setTimeout(resolve, 0)));

test("a busy stretch is listed by its street, with its calmer way and Use this way, said once when all are looked for", async () => {
  const used: { street: string | null; way: LonLat[] }[] = [];
  const asked: number[] = [];
  const screen = await render(
    <CheckRoute
      route={route([span(0, 1000, 2), span(1000, 2000, 4), span(2000, 4400, 2)])}
      preset="default"
      dials={startDials("default")}
      getMap={() => null}
      plan={async (_points, _preset, dials) => {
        asked.push(dials.stress);
        return calm;
      }}
      onUse={(stretch, way) => used.push({ street: stretch.street, way })}
    />,
  );
  assert.ok(screen.get("heading", "Busiest stretches"));
  assert.ok(screen.button(/^Big Road: 0\.6 mi.*LTS 4 at worst$/));
  await settle();
  assert.deepEqual(asked, [100], "one calmer way, planned at the calmest setting");
  assert.match(screen.text(), /Calmer way: .* longer, LTS 1 at worst\./);
  assert.ok(screen.get("status", "1 busiest stretches listed, 1 with a calmer way round."));
  await click(screen.button("Use this way"));
  assert.equal(used.length, 1);
  assert.equal(used[0].street, "Big Road");
  assert.equal(used[0].way.length, 3);
});

test("a calm route says so at once, and offers nothing to press", async () => {
  const screen = await render(
    <CheckRoute route={route([span(0, 4400, 2)])} preset="default" dials={startDials("default")} getMap={() => null} plan={async () => calm} />,
  );
  assert.match(screen.text(), /Nothing on this route is busier than LTS 2\.5\./);
  assert.equal(screen.all("button", "Use this way").length, 0);
});

test("no calmer way nearby is said, and Use this way is not offered", async () => {
  const screen = await render(
    <CheckRoute
      route={route([span(1000, 2000, 4)])}
      preset="default"
      dials={startDials("default")}
      getMap={() => null}
      plan={async () => ({ ...calm, route: { ...calm.route, stress_spans: [span(0, 1500, 4)] } }) as RouteResult}
      onUse={() => {}}
    />,
  );
  await settle();
  assert.match(screen.text(), /No calmer way round nearby\./);
  assert.equal(screen.all("button", "Use this way").length, 0);
});
