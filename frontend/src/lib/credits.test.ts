// OWNER-DECISIONS 301: "Even if the license doesn't require crediting them, sources need
// citing." Every source a rider sees the work of is cited on the map, exactly these lines,
// and the comparison data used only inside the project is named nowhere a rider sees.
// The API's own credits (routing.ATTRIBUTION, the geocode credit) are tests/test_credits.py's.
import { test } from "node:test";
import assert from "node:assert/strict";
import { MAP_ATTRIBUTION, MAP_CREDITS, SOURCE_CREDITS } from "./mapStyle.ts";

test("every source a rider sees is cited, exactly these, whatever its licence asks (OWNER-DECISIONS 301)", () => {
  const strip = (html: string) => html.replace(/<[^>]+>/g, "");
  assert.deepEqual(MAP_CREDITS.map(strip), [
    "© OpenStreetMap contributors (ODbL), © Protomaps",
    "Stress tiers use traffic volume, and routing the Central Business District boundary, from the District Department of Transportation (DDOT), adapted, CC BY 4.0",
    "Traffic volume: Virginia Department of Transportation (VDOT)",
    "Routing the Capitol grounds: Architect of the Capitol boundary, District of Columbia (Open Data DC), CC BY 4.0",
    "Street speeds, lanes, one-way streets, bike lanes, parking and traffic counts in the District: Roadway Block, District Department of Transportation (DDOT) / DC GIS (Open Data DC), adapted, CC BY 4.0",
    "Street speeds, one-way streets, bike facilities and trails in Baltimore: City of Baltimore, Open Baltimore",
    "Roads to avoid in Montgomery County: Bicycle Level of Traffic Stress, Montgomery County Planning Department",
    "Metro stations and entrances: District of Columbia (Open Data DC), CC BY 4.0",
    "Federal land on the Mass Ride map: National Parks, Reservations and Military Bases, District of Columbia (Open Data DC), adapted, CC BY 4.0",
    "Elevation and climb: U.S. Geological Survey 3D Elevation Program (3DEP)",
    "Place search: Photon (komoot), Apache 2.0",
  ]);
  assert.deepEqual(SOURCE_CREDITS, MAP_CREDITS.slice(-2));
  assert.ok(SOURCE_CREDITS.every((credit) => MAP_ATTRIBUTION.includes(credit)));
});

test("Arlington's and Alexandria's comparison data, internal only, is named nowhere a rider sees", async () => {
  const { readdirSync, readFileSync, statSync } = await import("node:fs");
  const { join } = await import("node:path");
  const root = new URL("..", import.meta.url).pathname;
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) {
        walk(path);
        continue;
      }
      // The code and the page, where a credit would be written; the data files hold place names (a station called Arlington Cemetery).
      if (/\.test\./.test(name) || !/\.(ts|tsx|js|mjs|css|html)$/.test(name)) continue;
      if (/Arlington|Alexandria/i.test(readFileSync(path, "utf8"))) offenders.push(path);
    }
  };
  walk(root);
  assert.deepEqual(offenders, []);
  assert.doesNotMatch(MAP_ATTRIBUTION, /Arlington|Alexandria/i);
});
