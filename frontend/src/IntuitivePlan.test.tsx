// The intuitiveness review of v0.30.0 in Plan (Stephen, 2026-11-21): one stress table with each level's share and
// distance, one-line directions with the full sentences a tick away, and Save route signed out keeping the route on
// this device. Rendered and looked at as the rider sees it (testSupport/render.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { FacilityBreakdown } from "./FacilityBreakdown.tsx";
import { RouteDescription } from "./RouteDescription.tsx";
import { SaveRoute } from "./SaveRoute.tsx";
import { RouteSummary, StressFigure, type PlanEdited, type RouteActionsProps } from "./app/RoutePanel.tsx";
import type { RouteResponse, StressSpan } from "./lib/api.ts";
import { stressSegments } from "./lib/stressBar.ts";

const span = (from_m: number, to_m: number, tier: number): StressSpan => ({ from_m, to_m, tier, facility: null });
const SPANS = [span(0, 3000, 1), span(3000, 4000, 3)];

const LEFT = "0.0 mi (0.0 km), for 1.9 mi (3.0 km): Start on Calm Street, low stress (LTS 1).";
const RIGHT = "1.9 mi (3.0 km), for 0.6 mi (1.0 km): Right onto Busy Avenue at a signal (Higher stress junction), moderate stress (LTS 3).";

function route(): RouteResponse {
  return {
    geometry: { type: "LineString", coordinates: [[-77.05, 38.9], [-77.0, 38.9]] },
    distance_m: 4000,
    duration_s: 900,
    stress_spans: SPANS,
    stress_m: { "1": 3000, "3": 1000 },
    facility_m: { none: 4000 },
    attribution: [],
    description: [
      { kind: "stretch", from_m: 0, to_m: 3000, street: "Calm Street", tier: 1, turn: null, text: LEFT },
      {
        kind: "stretch",
        from_m: 3000,
        to_m: 4000,
        street: "Busy Avenue",
        tier: 3,
        turn: { movement: "right", onto: "Busy Avenue", control: "signal", severity: "orange" },
        text: RIGHT,
      },
    ],
  } as unknown as RouteResponse;
}

test("Plan's stress bar has no LTS percentages line under it; the fold's one table has each level's share and distance", async () => {
  const bar = await render(<StressFigure segments={stressSegments(route().stress_m ?? {})} />);
  assert.doesNotMatch(bar.text(), /LTS 1: 75%/, "the bar's text line is gone");
  await bar.unmount();
  const table = await render(<FacilityBreakdown route={route()} part="figures" />);
  assert.match(table.text(), /75% · 1\.9 mi/);
  assert.match(table.text(), /25% · 0\.6 mi/);
});

test("Directions: one line a step, its turn, street and length, busy levels in words; Full detail gives the sentences", async () => {
  try {
    localStorage.clear();
  } catch {
    // no storage: the default view
  }
  await render(<RouteDescription route={route()} fold />);
  (document.querySelector("details.route-description") as HTMLDetailsElement).open = true;
  const steps = [...document.querySelectorAll(".description-list > li")].map((li) => li.textContent?.trim());
  assert.deepEqual(steps, ["Calm Street · 1.9 mi", "Right onto Busy Avenue · 0.6 mi · LTS 3, busy junction"]);
  await click(document.querySelector(".description-view input")!);
  const full = [...document.querySelectorAll(".description-list > li")].map((li) => li.textContent?.trim());
  assert.deepEqual(full, [LEFT, RIGHT]);
});

test("Signed out, Save route keeps the route on this device and offers Sign in to sync; no sign-in wall", async () => {
  let kept = 0;
  const screen = await render(
    <SaveRoute
      label="Save route"
      bar
      defaultName={() => "A to B"}
      onSave={null}
      signIn={() => {}}
      keepHere={async () => {
        kept++;
        return { said: "Kept for offline: A to B, with the map along it.", kept: true };
      }}
    />,
  );
  await click(screen.button("Save route"));
  await new Promise((done) => setTimeout(done, 0));
  assert.equal(kept, 1);
  assert.match(screen.text(), /Kept for offline: A to B/);
  assert.ok(screen.get("link", "Sign in to sync"));
  assert.equal(document.querySelector(".save-route-form"), null, "no form of sign-in and GPX buttons");
});

test("A keep that fails says so, with no Sign in to sync on it", async () => {
  const screen = await render(
    <SaveRoute label="Save route" bar defaultName={() => "A to B"} onSave={null} signIn={() => {}} keepHere={async () => ({ said: "The route could not be kept.", kept: false })} />,
  );
  await click(screen.button("Save route"));
  await new Promise((done) => setTimeout(done, 0));
  assert.match(screen.text(), /could not be kept/);
  assert.equal(screen.all("link", "Sign in to sync").length, 0);
});

function card(edited: PlanEdited | null) {
  const noop = () => {};
  const actions: RouteActionsProps = {
    shown: route(), routedPoints: [], routedLoop: false, federalRoute: [], copyLink: noop, linkNote: "", shareImage: noop, linkSpoken: "",
    keepShown: false, keepForOffline: async () => undefined, keeping: false, keepSpoken: { text: "", count: 0 }, linkSaid: "", downloadRoute: noop, save: null, savedNote: null,
  };
  return render(
    <RouteSummary
      route={route()} answer={null} choice={0} around={false} onAround={noop} points={[[-77.05, 38.9], [-77.0, 38.9]]} federal={[]} narrow={false}
      ride={{ onStart: noop, startRef: { current: null } }} onSelectJunction={noop} onScrub={noop} picker={null} pickerCount={0} rideSize={0}
      onEnding={noop} water={null} climbs={null} actions={actions} mode="plan" preset="default" go={{ onGroupRideNoTrails: noop, peek: false, full: false, options: null }}
      edited={edited}
    />,
  );
}

test("Plan's route card after an edit: Update route where Start was, the figures marked as before the change", async () => {
  let updated = 0;
  const screen = await card({ label: "Update route", onUpdate: () => updated++, busy: false, why: null });
  assert.equal(screen.all("button", /^Start/).length, 0, "no Start for a route that no longer matches the plan");
  assert.equal(screen.all("button", "Download GPX").length, 0);
  assert.match(screen.text(), /The figures are for the route before your change/);
  await click(screen.button("Update route"));
  assert.equal(updated, 1);
  await screen.unmount();
  const routing = await card({ label: "Routing…", onUpdate: null, busy: true, why: null });
  assert.equal(routing.button("Routing…").getAttribute("aria-disabled"), "true", "kept while routing, so the focus stays");
  await routing.unmount();
  const fresh = await card(null);
  assert.ok(fresh.all("button", /^Start/).length > 0, "Start is back once the route is current");
});
