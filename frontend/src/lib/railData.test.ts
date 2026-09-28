// railData.ts as the app loads it: Vite's ?raw imports served as text by a
// module load hook, so the wiring from the fixtures to the map is what is run.
import { test } from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register(
  "data:text/javascript," +
    encodeURIComponent(`
import { readFileSync } from "node:fs";
export async function load(url, context, next) {
  if (url.endsWith("?raw")) {
    const text = readFileSync(new URL(url.slice(0, -4)), "utf8");
    return { format: "module", source: "export default " + JSON.stringify(text), shortCircuit: true };
  }
  return next(url, context);
}`),
);

test("the shipped stations carry the line corrections, OSM's elevators and the bike entrance", async () => {
  const data = await import("./railData.ts");
  const named = (n: string) => data.RAIL_STATIONS.find((s) => s.name === n)!;
  assert.ok(data.RAIL_STATIONS.length > 100);
  assert.ok(named("New Carrollton").metro.includes("silver"));
  assert.ok(named("Greenbelt").metro.includes("yellow"));
  assert.ok(named("Wheaton").osmElevators.length > 0);
  const metroCenter = named("Metro Center");
  const point = data.stationBikeEntrance(metroCenter.id)!;
  assert.ok(metroCenter.elevators.some((e) => e[0] === point[0] && e[1] === point[1]));
  const wheaton = named("Wheaton");
  const wp = data.stationBikeEntrance(wheaton.id)!;
  assert.ok(wheaton.osmElevators.some((e) => e[0] === wp[0] && e[1] === wp[1]));
  assert.equal(data.stationById(metroCenter.id), metroCenter);
  assert.equal(data.stationBikeEntrance("nope"), null);
});
