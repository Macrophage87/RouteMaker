// The stretch picked on Plan's chart, as the rider sees it (ChartStretch.tsx and ElevationChart.tsx's tools): its
// facts, Try to avoid this stretch, the way round's cost and Use this way; Enter centres the map, Shift with the arrow
// keys picks a stretch. Rendered (testSupport/render.ts) on a made-up route; no rider's file.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, press, render } from "./testSupport/render.ts";
import { ChartStretch } from "./ChartStretch.tsx";
import { ElevationChart } from "./ElevationChart.tsx";
import type { RouteProfile, RouteResponse, RouteResult, StressSpan } from "./lib/api.ts";
import { HILLS_MIN, startDials, type Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";

const LINE: LonLat[] = Array.from({ length: 400 }, (_, i) => [-77.05 + i * 0.000128, 38.9]);
const span = (from_m: number, to_m: number, tier: number): StressSpan => ({ from_m, to_m, tier, facility: null });
const profileOf = (elevation: number[]): RouteProfile => {
  const m = elevation.map((_, i) => i * 100);
  return { interval_m: 100, m, elevation_m: elevation, grade_pct: elevation.map((e, i) => (i === 0 ? 0 : e - elevation[i - 1])), climbs: [] } as RouteProfile;
};
// Flat to 1 km, a 9% climb from 2 to 3 km, flat after; Big Road (LTS 4) from 1 to 2 km.
const PROFILE = profileOf([...Array(21).fill(10), 19, 28, 37, 46, 55, 64, 73, 82, 91, 100, ...Array(14).fill(100)]);
const ROUTE = {
  geometry: { type: "LineString", coordinates: LINE },
  distance_m: 4400,
  duration_s: 900,
  stress_spans: [span(0, 1000, 2), span(1000, 2000, 4), span(2000, 4400, 2)],
  description: [
    { kind: "stretch", from_m: 0, to_m: 1000, street: "Side Street", tier: 2 },
    { kind: "stretch", from_m: 1000, to_m: 2000, street: "Big Road", tier: 4 },
    { kind: "stretch", from_m: 2000, to_m: 4400, street: "Hill Street", tier: 2 },
  ],
  profile: PROFILE,
} as unknown as RouteResponse;

const around = (tier: number, elevation: number[]): RouteResult => ({
  ok: true,
  route: { ...ROUTE, distance_m: 1700, stress_spans: [span(0, 1700, tier)], description: [], profile: profileOf(elevation), geometry: { type: "LineString", coordinates: [LINE[75], [-77.035, 38.905], LINE[195]] } } as unknown as RouteResponse,
});
const settle = () => act(async () => new Promise((resolve) => setTimeout(resolve, 0)));

function stretch(fromM: number, toM: number, answer: RouteResult, asked: Dials[], used: { street: string | null }[], cleared: { n: number } = { n: 0 }) {
  return (
    <ChartStretch
      route={ROUTE}
      profile={PROFILE}
      fromM={fromM}
      toM={toM}
      onClear={() => (cleared.n += 1)}
      preset="default"
      dials={startDials("default")}
      getMap={() => null}
      plan={async (_points, _preset, dials) => {
        asked.push(dials);
        return answer;
      }}
      onUse={(s) => used.push({ street: s.street })}
    />
  );
}

test("a busy stretch says its miles, climb and stress, and a way round at the calmest setting with its cost", async () => {
  const asked: Dials[] = [];
  const used: { street: string | null }[] = [];
  const screen = await render(stretch(1100, 1900, around(2, [10, 11, 12]), asked, used));
  assert.match(screen.text(), /Mile 0\.7 to 1\.2: 0\.5 mi .*LTS 4 at worst\./);
  await click(screen.button("Try to avoid this stretch"));
  assert.match(document.activeElement?.outerHTML ?? "", /pc-stretch-way/, "the focus goes to what is found, not the page");
  await settle();
  assert.equal(asked.length, 1);
  assert.equal(asked[0].stress, 100, "planned at the calmest traffic setting");
  assert.match(screen.text(), /Way round: 0\.\d mi \(\d\.\d km\) longer, LTS 2 at worst\./);
  await click(screen.button("Use this way"));
  assert.deepEqual(used, [{ street: "Big Road" }]);
});

test("a steep stretch is planned round with the fewest hills, and says the climb it saves", async () => {
  const asked: Dials[] = [];
  const screen = await render(stretch(2100, 2900, around(2, [10, 12, 14]), asked, []));
  assert.match(screen.text(), /steepest 9%/);
  await click(screen.button("Try to avoid this stretch"));
  await settle();
  assert.equal(asked[0].hills, HILLS_MIN);
  assert.equal(asked[0].stress, startDials("default").stress, "the plan's own traffic setting");
  assert.match(screen.text(), /ft \(\d+ m\) less climb/);
});

test("no better way round is said as such, with no Use this way", async () => {
  const screen = await render(stretch(1100, 1900, around(4, [10, 11, 12]), [], []));
  await click(screen.button("Try to avoid this stretch"));
  await settle();
  assert.match(screen.text(), /No better way round nearby\./);
  assert.equal(screen.all("button", "Use this way").length, 0);
});

test("a calm flat stretch offers no way round; Clear lets it go", async () => {
  const cleared = { n: 0 };
  const calm = await render(stretch(3500, 4300, around(1, [10]), [], [], cleared));
  assert.equal(calm.all("button", "Try to avoid this stretch").length, 0);
  await click(calm.button("Clear"));
  assert.equal(cleared.n, 1);
});

test("on Plan's chart, Enter centres the map there and Shift with the arrow keys picks a stretch; Escape lets it go", async () => {
  const centred: LonLat[] = [];
  const picked: [number, number][] = [];
  const screen = await render(
    <ElevationChart
      route={ROUTE}
      profile={PROFILE}
      tools={{
        onCentre: (p) => centred.push(p),
        stretch: (fromM, toM) => {
          picked.push([fromM, toM]);
          return <p>Picked {Math.round(fromM)} to {Math.round(toM)}</p>;
        },
      }}
    />,
  );
  const slider = screen.get("slider", /along the route/);
  await act(async () => slider.focus());
  await press(slider, "End");
  await press(slider, "Enter");
  assert.equal(centred.length, 1);
  assert.ok(Math.abs(centred[0][0] - LINE[399][0]) < 0.001, "centred at the route's end");
  await press(slider, "Home");
  await act(async () => {
    for (let i = 0; i < 3; i += 1) slider.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", shiftKey: true, bubbles: true, cancelable: true }) as unknown as Event);
  });
  assert.match(screen.text(), /Picked 0 to \d+/);
  const [from, to] = picked[picked.length - 1];
  assert.ok(from === 0 && to > 0);
  await press(slider, "Escape");
  assert.doesNotMatch(screen.text(), /Picked/);
  assert.match(slider.getAttribute("aria-describedby") ?? "", /keys/);
  assert.match(screen.text(), /Shift with the arrow keys picks a stretch/);
});

test("Go's chart and a chart without Plan's tools pick nothing and centre nothing", async () => {
  const screen = await render(<ElevationChart route={ROUTE} profile={PROFILE} />);
  const slider = screen.get("slider", /along the route/);
  await act(async () => slider.focus());
  await act(async () => {
    slider.dispatchEvent(new window.KeyboardEvent("keydown", { key: "ArrowRight", shiftKey: true, bubbles: true, cancelable: true }) as unknown as Event);
  });
  await press(slider, "Enter");
  assert.doesNotMatch(screen.text(), /picks a stretch/);
});
