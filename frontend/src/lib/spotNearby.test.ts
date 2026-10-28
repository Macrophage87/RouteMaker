// Go's tapped-spot card (Stephen, 2026-10-28: "show the address and what's near", "label them"; lib/spotNearby.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { FoodPlace } from "./food.ts";
import type { RepairPlace } from "./repair.ts";
import type { SightPlace } from "./places.ts";
import type { WaterPoint } from "./waterRestrooms.ts";
import type { Station } from "./railStations.ts";
import {
  DROPPED_PIN,
  foodSpotPlaces,
  metroSpotPlaces,
  repairSpotPlaces,
  sightSpotPlaces,
  spotAddress,
  spotAwayText,
  spotCountLine,
  spotFarLine,
  spotNearby,
  spotRowName,
  waterSpotPlaces,
  type SpotPlace,
} from "./spotNearby.ts";

const SPOT: LonLat = [-77.0369, 38.9072];
// About 111 m of latitude per 0.001°.
const north = (m: number): LonLat => [SPOT[0], SPOT[1] + m / 111_000];

const place = (id: string, kind: SpotPlace["kind"], m: number): SpotPlace => ({
  id,
  kind,
  point: north(m),
  name: id,
  kindText: "",
  label: null,
  icon: "pin",
  words: (far) => ({ title: id, lines: [far] }),
});

test("spot nearby: the nearest of each kind within a mile, nearest first, at most six", () => {
  const places = [
    place("cafe-far", "food", 300),
    place("cafe", "food", 100),
    place("tap", "water", 200),
    place("loo", "restroom", 50),
    place("stand", "repair", 400),
    place("metro", "metro", 900),
    place("museum", "sight", 1200),
    place("far-away", "water", 5000),
  ];
  const rows = spotNearby(SPOT, places);
  assert.deepEqual(rows.map((r) => r.id), ["loo", "cafe", "tap", "stand", "metro", "museum"]);
  assert.ok(Math.abs(rows[0].metres - 50) < 2);
  assert.equal(spotNearby(SPOT, places, undefined, 5).length, 5);
});

test("spot nearby: where few kinds are near, the next nearest of any kind fill it to four", () => {
  const rows = spotNearby(SPOT, [place("a", "food", 100), place("b", "food", 200), place("c", "food", 300), place("d", "food", 400), place("e", "food", 500)]);
  assert.deepEqual(rows.map((r) => r.id), ["a", "b", "c", "d"]);
  assert.deepEqual(spotNearby(SPOT, [place("far", "food", 3000)]), [], "nothing within a mile: nothing");
});

test("spot nearby: the card's line, a row's name and the card's distance, miles first", () => {
  assert.equal(spotCountLine(5), "5 places nearby, shown on the map.");
  assert.equal(spotCountLine(1), "1 place nearby, shown on the map.");
  const rows = spotNearby(SPOT, [{ ...place("Peet's Coffee", "food", 322), kindText: "Café" }]);
  assert.equal(spotRowName(rows[0]), "Peet's Coffee, Café, 0.2 mi (0.3 km)");
  assert.equal(spotFarLine(322), "0.2 mi (0.3 km) from the spot you tapped.");
  assert.equal(spotAwayText(north(3380), SPOT), "2.1 mi (3.4 km) away", "how far the spot is from the rider");
  assert.equal(spotAwayText(SPOT, null), "", "no location, no distance");
});

test("spot nearby: named places are labelled on the map; water, restrooms and repair stands are icons alone", () => {
  const water: WaterPoint[] = [
    { id: "n1", lon: SPOT[0], lat: SPOT[1], water: "p", name: "Scott Circle" },
    { id: "n2", lon: SPOT[0], lat: SPOT[1], water: "n" },
    { id: "n3", lon: SPOT[0], lat: SPOT[1], toilet: "f" },
  ];
  const w = waterSpotPlaces(water);
  assert.deepEqual(
    w.map((p) => [p.kind, p.name, p.kindText, p.label, p.icon]),
    [
      ["water", "Scott Circle", "Water", null, "water"],
      ["restroom", w[1].name, "", null, "wc"],
    ],
    "untreated water is left out; an unnamed point is named by what it is",
  );
  const food = foodSpotPlaces([
    { id: "f1", lon: SPOT[0], lat: SPOT[1], name: "Peet's", kind: "cafe", cuisine: [], website: "https://example.org" } as unknown as FoodPlace,
    { id: "f2", lon: SPOT[0], lat: SPOT[1], name: "", kind: "cafe", cuisine: [] } as unknown as FoodPlace,
  ]);
  assert.deepEqual([food[0].name, food[0].label, food[0].icon], ["Peet's", "Peet's", "food"]);
  assert.equal(food[1].label, null, "an unnamed café: its icon alone");
  const words = food[0].words("0.1 mi (0.2 km) from the spot you tapped.", new Date());
  assert.equal(words.title, "Peet's");
  assert.equal(words.lines.at(-1), "0.1 mi (0.2 km) from the spot you tapped.");
  assert.equal(words.website, "https://example.org");
  const repair = repairSpotPlaces([
    { id: "r1", kind: "stand", lon: SPOT[0], lat: SPOT[1], name: "Dupont stand" } as RepairPlace,
    { id: "r2", kind: "shop", lon: SPOT[0], lat: SPOT[1], name: "BicycleSPACE" } as RepairPlace,
  ]);
  assert.deepEqual(repair.map((r) => [r.name, r.kindText, r.label]), [
    ["Dupont stand", "Repair stand", null],
    ["BicycleSPACE", "Bike shop", "BicycleSPACE"],
  ]);
  assert.equal(repair[0].words("far.", new Date()).title, "Repair stand, Dupont stand");
  const sight = sightSpotPlaces([{ id: "s1", lon: SPOT[0], lat: SPOT[1], category: "museum", name: "Phillips Collection" } as SightPlace]);
  assert.deepEqual([sight[0].name, sight[0].kindText, sight[0].label], ["Phillips Collection", "Museum or gallery", "Phillips Collection"]);
  const dupont: Station = { id: "metro-1", name: "Dupont Circle", point: [-77.0434, 38.9096], metro: ["red"], penn: false, elevators: [], osmElevators: [], entrances: [] };
  const metro = metroSpotPlaces([dupont, { ...dupont, id: "marc-1", name: "Odenton", metro: [] }]).find((m) => m.name === "Dupont Circle");
  assert.ok(metro, "Dupont Circle is a Metro station");
  assert.equal(metro.label, "Dupont Circle");
  assert.match(metro.kindText, /^Metro: /);
});

test("spot address: the geocoder's name and the rest of its label; never coordinates", () => {
  const ok = (name: string, label: string) => ({ ok: true as const, attribution: [], places: [{ name, label, lon: 0, lat: 0, kind: "street" }] });
  assert.deepEqual(spotAddress(ok("Connecticut Avenue Northwest", "Connecticut Avenue Northwest, Dupont Circle, Washington")), {
    heading: "Connecticut Avenue Northwest",
    area: "Dupont Circle, Washington",
  });
  assert.deepEqual(spotAddress(ok("near White House", "near White House, Ward 2, Washington")), { heading: "Near White House", area: "Ward 2, Washington" });
  assert.deepEqual(spotAddress({ ok: false, status: 0 }, "Scott Circle"), { heading: "Scott Circle", area: "" });
  assert.deepEqual(spotAddress({ ok: false, status: 503 }), { heading: DROPPED_PIN, area: "" });
  assert.deepEqual(spotAddress({ ok: true, attribution: [], places: [] }), { heading: "Dropped pin", area: "" });
});
