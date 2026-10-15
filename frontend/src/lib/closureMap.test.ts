// Closures on the map (v0.7.0, lib/closureMap.ts): what is drawn, what the markers are called, what the card says,
// and the per-plan "Route through anyway" with its Undo.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ROUTE_THROUGH_LABEL,
  UNDO_BYPASS_LABEL,
  bypassFor,
  bypassPlanKey,
  closureCard,
  closureFeatures,
  closureMarkerName,
  closuresOf,
  noticeCard,
  noticeMarkerName,
  parkNoticesOf,
  toggleBypass,
  type ClosureItem,
  type ClosureNotice,
} from "./closureMap.ts";
import { checkClosures } from "./closureCheck.ts";

function item(over: Partial<ClosureItem> = {}): ClosureItem {
  return {
    id: "mpd-1845231-0",
    source: "mpd",
    source_name: "MPD traffic advisory, Sep 4",
    url: "https://mpdc.dc.gov/node/1845231",
    kind: "closed",
    severity: "red",
    title: "Constitution Avenue NW closed, 14th Street NW to 18th Street NW",
    road: "Constitution Avenue NW",
    when_text: "Closed today 4:30 am to 1:30 pm",
    start: null,
    end: null,
    effect: "routed_round",
    delay_s: 240,
    effect_text: "Detour adds about 4 min",
    can_bypass: true,
    bypassed: false,
    from_m: null,
    to_m: null,
    point: [-77.04, 38.892],
    line: [
      [-77.032, 38.892],
      [-77.042, 38.892],
    ],
    ...over,
  };
}

const PARK: ClosureNotice = {
  id: "nps-1",
  source: "nps",
  source_name: "NPS alerts",
  title: "Beach Drive closed between Broad Branch Road and Joyce Road",
  text: "Use the Western Ridge Trail.",
  url: "https://www.nps.gov/rocr/planyourvisit/conditions.htm",
  area: "rocr",
  area_name: "Rock Creek Park",
  point: [-77.0525, 38.9406],
  category: "Park Closure",
  when_text: "Posted Oct 12",
};

test("the route's closures and park notices are read from work_zones, and nothing from an older answer", () => {
  assert.deepEqual(closuresOf(null), []);
  assert.deepEqual(closuresOf({ work_zones: null }), []);
  const route = { work_zones: { closures: [item()], notices: [PARK, { ...PARK, id: "mpd-x", point: null }] } };
  assert.equal(closuresOf(route).length, 1);
  assert.deepEqual(parkNoticesOf(route).map((n) => n.id), ["nps-1"], "a District-wide notice has no marker");
});

test("closed stretches are drawn red, blocked lanes amber, 'may still apply' dashed, and a bypassed one only as its marker", () => {
  const data = closureFeatures([
    item(),
    item({ id: "dc-2", kind: "lane", severity: "amber" }),
    item({ id: "dc-3", effect: "may_still_apply" }),
    item({ id: "dc-4", bypassed: true, effect: "bypassed" }),
  ]);
  assert.deepEqual(
    data.features.map((f) => [f.properties.id, f.properties.severity, f.properties.maybe]),
    [
      ["mpd-1845231-0", "red", 0],
      ["dc-2", "amber", 0],
      ["dc-3", "red", 1],
    ],
  );
});

test("a marker's name says what it is and what it does to the route", () => {
  assert.equal(
    closureMarkerName(item()),
    "Road closed: Constitution Avenue NW closed, 14th Street NW to 18th Street NW. Detour adds about 4 min",
  );
  assert.match(closureMarkerName(item({ kind: "lane", effect_text: "No effect on your route" })), /^Bike lane blocked: /);
  assert.match(closureMarkerName(item({ bypassed: true })), /^Routed through closure: /);
  assert.equal(noticeMarkerName(PARK), "Check before you go, Rock Creek Park: Beach Drive closed between Broad Branch Road and Joyce Road");
});

test("the card: what, the source linked, when, the delay, and Route through anyway or Undo", () => {
  const card = closureCard(item());
  assert.equal(card.heading, "Road closed");
  assert.deepEqual(card.source, { name: "Source: MPD traffic advisory, Sep 4", url: "https://mpdc.dc.gov/node/1845231" });
  assert.equal(card.when, "Closed today 4:30 am to 1:30 pm");
  assert.equal(card.effect, "Detour adds about 4 min");
  assert.deepEqual(card.action, { label: ROUTE_THROUGH_LABEL, bypass: true });
  assert.deepEqual(closureCard(item({ bypassed: true, effect: "bypassed" })).action, { label: UNDO_BYPASS_LABEL, bypass: false });
  assert.equal(closureCard(item({ effect: "none", effect_text: "No effect on your route" })).action, null, "nothing to bypass off the route");
  assert.equal(closureCard(item({ kind: "lane", can_bypass: false, effect: "on_route" })).action, null);
  assert.equal(noticeCard(PARK).action, null);
  assert.equal(noticeCard(PARK).source.name, "Source: NPS alerts (Park Closure)");
});

test("Route through anyway is per plan: kept while the start and end stay, forgotten on a new one, undone one by one", () => {
  const plan = bypassPlanKey([
    [-77.05, 38.9],
    [-77.0, 38.95],
    [-77.02, 38.89],
  ]);
  let bypass = toggleBypass(null, plan, "b", true);
  bypass = toggleBypass(bypass, plan, "a", true);
  assert.deepEqual(bypassFor(bypass, plan), ["a", "b"]);
  assert.deepEqual(bypassFor(bypass, bypassPlanKey([[-77.05, 38.9], [-77.03, 38.89]])), [], "another plan sees none");
  bypass = toggleBypass(bypass, plan, "b", false);
  assert.deepEqual(bypassFor(bypass, plan), ["a"], "Undo restores the closure");
  assert.equal(bypassPlanKey([[-77, 38.9]]), "");
});

test("the closure check sends the plan's When and its bypassed closures, and reads the notices", async () => {
  let sent: unknown = null;
  const post = (async (_url: string, init: { body: string }) => {
    sent = JSON.parse(init.body);
    return { ok: true, json: async () => ({ closures: [], unchecked: null, notices: [PARK], ride_at: "2026-10-17T13:00:00+00:00" }) };
  }) as unknown as typeof fetch;
  const line = [
    [-77.05, 38.9],
    [-77.0, 38.95],
  ];
  const found = await checkClosures("https://x.example", line, post, { when: "weekend", bypass: ["a"] });
  assert.deepEqual(sent, { line, when: "weekend", bypass: ["a"] });
  assert.equal(found?.notices?.[0].id, "nps-1");
  await checkClosures("https://x.example", line, post);
  assert.deepEqual(sent, { line }, "the first contract's body where there is nothing to add");
});
