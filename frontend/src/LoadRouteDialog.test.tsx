// Load route's rows, as the rider sees them (backlog 2026-11-12, Plan item 9: "Saved routes you can tell apart at
// 50+"): each saved route's sketch beside its name, and its figures line. Go's Saved routes is this same popup.
import { afterEach, test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
import { LoadRouteDialog } from "./LoadRouteDialog.tsx";
import type { SavedSummary } from "./lib/savedRoutes.ts";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function route(id: number, name: string, figures: SavedSummary["figures"]): SavedSummary {
  return { id, name, source: "plan", distance_m: 7600, preset: "default", created_at: "2026-10-15T12:00:00Z", updated_at: "2026-10-15T12:00:00Z", tags: [], archived_at: null, figures };
}

async function dialogWith(routes: SavedSummary[]) {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/me/routes") ? { routes, max: 200 } : { drafts: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  const screen = await render(
    <LoadRouteDialog open onClose={() => {}} signedIn signIn={null} preset="default" onGpx={() => {}} onOpenSaved={() => {}} onOpenDraft={() => {}} onOpenKept={() => {}} />,
  );
  // The list is read after the first paint.
  for (let i = 0; i < 20 && !screen.text().includes(routes[0].name); i++) await new Promise((r) => setTimeout(r, 5));
  return screen;
}

test("a saved route's row shows its sketch and its miles, climb and quiet share", async () => {
  const screen = await dialogWith([route(1, "Hilly Rockville loop", { sketch: [[0, 80], [40, 20], [100, 50]], climb_m: 81, quiet_pct: 78 })]);
  const row = screen.button(/^Hilly Rockville loop/);
  assert.match(row.textContent ?? "", /4\.7 mi \(7\.6 km\), 266 ft \(81 m\) climb, 78% quiet · Default/);
  const sketch = row.querySelector("svg.route-sketch");
  assert.ok(sketch, "the sketch is drawn in the row");
  assert.equal(sketch.getAttribute("aria-hidden"), "true", "the name and figures say it; a screen reader skips the picture");
  assert.equal(sketch.querySelector("polyline")?.getAttribute("points"), "0,80 40,20 100,50");
});

test("a route without figures (an older server, a file's line) shows its distance and no picture", async () => {
  const screen = await dialogWith([route(2, "Old commute", null)]);
  const row = screen.button(/^Old commute/);
  assert.equal(row.querySelector("svg"), null);
  assert.match(row.textContent ?? "", /4\.7 mi \(7\.6 km\) · Default/);
  assert.doesNotMatch(row.textContent ?? "", /climb|quiet/);
});
