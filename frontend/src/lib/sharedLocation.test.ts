/** Open shared locations in RouteMaker (v0.7.0): links, coordinates, the share target and the geo: handler. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { decodeGeohash, launchShare, parseCoordinates, parseShared, readShared, sharedPlace, withoutShare, SHARED_FAILED, SHARED_UNREADABLE } from "./sharedLocation.ts";

const LINCOLN: [number, number] = [-77.050176, 38.8892686];

const near = (a: readonly number[] | undefined, b: readonly number[], eps = 1e-4) => {
  assert.ok(a, "a point");
  assert.ok(Math.abs(a[0] - b[0]) < eps && Math.abs(a[1] - b[1]) < eps, `${a} near ${b}`);
};
const pointOf = (text: string) => {
  const found = parseShared(text);
  return found?.kind === "point" ? found : null;
};

test("coordinates, latitude first, in the forms map apps copy", () => {
  near(parseCoordinates("38.8892686, -77.050176")!, LINCOLN);
  near(parseCoordinates("38.8892686 -77.050176")!, LINCOLN);
  near(parseCoordinates("38.8892686° N, 77.050176° W")!, LINCOLN);
  // A first number that cannot be a latitude is a longitude.
  near(parseCoordinates("-77.050176, 38.8892686")!, LINCOLN);
  assert.equal(parseCoordinates("12 34"), null, "a street number is not a place");
  assert.equal(parseCoordinates("95.1, 200.2"), null);
  assert.equal(parseCoordinates("1600 Pennsylvania Ave"), null);
});

test("geo: links, with a label or an address", () => {
  near(pointOf("geo:38.8892686,-77.050176")?.point, LINCOLN);
  near(pointOf("geo:38.8892686,-77.050176;u=35")?.point, LINCOLN);
  const labelled = pointOf("geo:0,0?q=38.8892686,-77.050176(Lincoln%20Memorial)");
  near(labelled?.point, LINCOLN);
  assert.equal(labelled?.name, "Lincoln Memorial");
  assert.deepEqual(parseShared("geo:0,0?q=1600+Pennsylvania+Ave+NW"), { kind: "query", text: "1600 Pennsylvania Ave NW" });
});

test("Google Maps links: the place's own point first, then the query, then the view", () => {
  const place = pointOf("https://www.google.com/maps/place/Lincoln+Memorial/@38.88,-77.06,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d38.8892686!4d-77.050176");
  near(place?.point, LINCOLN);
  assert.equal(place?.name, "Lincoln Memorial");
  near(pointOf("https://maps.google.com/?q=38.8892686,-77.050176")?.point, LINCOLN);
  near(pointOf("https://www.google.com/maps/search/?api=1&query=38.8892686%2C-77.050176")?.point, LINCOLN);
  near(pointOf("https://www.google.com/maps/dir/?api=1&destination=38.8892686,-77.050176")?.point, LINCOLN);
  near(pointOf("https://www.google.com/maps/dir/38.9,-77.0/38.8892686,-77.050176/@38.89,-77.03,14z")?.point, LINCOLN);
  near(pointOf("https://www.google.com/maps/@38.8892686,-77.050176,15z")?.point, LINCOLN);
  assert.deepEqual(parseShared("https://www.google.com/maps/search/?api=1&query=Lincoln+Memorial"), { kind: "query", text: "Lincoln Memorial" });
  // The EU consent page wraps the link.
  near(pointOf(`https://consent.google.com/m?continue=${encodeURIComponent("https://www.google.com/maps/@38.8892686,-77.050176,15z")}`)?.point, LINCOLN);
});

test("Apple Maps and Waze links", () => {
  const apple = pointOf("https://maps.apple.com/?ll=38.8892686,-77.050176&q=Lincoln%20Memorial");
  near(apple?.point, LINCOLN);
  assert.equal(apple?.name, "Lincoln Memorial");
  near(pointOf("https://maps.apple.com/place?coordinate=38.8892686,-77.050176&name=Lincoln%20Memorial")?.point, LINCOLN);
  near(pointOf("https://maps.apple.com/?daddr=38.8892686,-77.050176")?.point, LINCOLN);
  near(pointOf("https://www.waze.com/ul?ll=38.8892686%2C-77.050176&navigate=yes")?.point, LINCOLN);
  near(pointOf("https://www.waze.com/live-map/directions?to=ll.38.8892686%2C-77.050176")?.point, LINCOLN);
  // waze.com/ul/h<geohash>: "dqcjnk" is a cell about 0.6 mi (1 km) across near the Mall.
  near(pointOf("https://waze.com/ul/hdqcjnk")?.point, decodeGeohash("dqcjnk")!, 1e-9);
  near(decodeGeohash("dqcjq")!, [-77.04, 38.9], 0.1);
});

test("a shared text: the words before the link name the place; a short link waits for the server", () => {
  assert.deepEqual(parseShared("Lincoln Memorial https://maps.app.goo.gl/AbC123"), { kind: "short", url: "https://maps.app.goo.gl/AbC123", name: "Lincoln Memorial" });
  assert.deepEqual(parseShared("https://goo.gl/maps/AbC"), { kind: "short", url: "https://goo.gl/maps/AbC", name: undefined });
  const named = pointOf("Meet here: https://www.google.com/maps/@38.8892686,-77.050176,15z");
  assert.equal(named?.name, "Meet here");
  assert.equal(parseShared("https://example.com/maps/@38.9,-77.0"), null, "not a map site");
  assert.equal(parseShared("pizza"), null);
});

test("readShared follows a short link through the server and reads what it stands for", async () => {
  const asked: string[] = [];
  const server = async (url: string, init: RequestInit) => {
    asked.push(`${url} ${init.body}`);
    return { ok: true, json: async () => ({ url: "https://www.google.com/maps/place/Lincoln+Memorial/@38.8892686,-77.050176,17z" }) };
  };
  // The link's own place name wins over the words shared with it.
  const got = await readShared("Check this out https://maps.app.goo.gl/AbC123", server);
  assert.ok("place" in got);
  assert.equal(got.place.name, "Lincoln Memorial");
  near([got.place.lon, got.place.lat], LINCOLN);
  assert.deepEqual(asked, ['/api/share/resolve {"url":"https://maps.app.goo.gl/AbC123"}']);
  assert.deepEqual(await readShared("https://maps.app.goo.gl/x", async () => ({ ok: false, json: async () => ({}) })), { error: SHARED_FAILED });
  assert.deepEqual(await readShared("nothing here"), { error: SHARED_UNREADABLE });
  assert.deepEqual(await readShared("geo:0,0?q=Union+Station"), { query: "Union Station" });
});

test("a shared place is a search place, its coordinates as its label", () => {
  assert.deepEqual(sharedPlace(LINCOLN), { name: "Shared location", label: "38.88927, -77.05018", lon: LINCOLN[0], lat: LINCOLN[1], kind: "shared" });
});

test("the share target's and geo: handler's parameters, and the address bar after", () => {
  assert.equal(launchShare("?share_title=Lincoln+Memorial&share_text=https%3A%2F%2Fmaps.app.goo.gl%2Fx"), "Lincoln Memorial https://maps.app.goo.gl/x");
  assert.equal(launchShare("?geo=geo%3A38.9%2C-77.0"), "geo:38.9,-77.0");
  assert.equal(launchShare("?share_text=x&share_url=x"), "x");
  assert.equal(launchShare(""), null);
  assert.equal(withoutShare("https://example.org/?geo=geo%3A1%2C2&keep=1#plan=abc"), "/?keep=1#plan=abc");
});

test("the manifest: the Android share target and the desktop geo: handler", () => {
  const manifest = JSON.parse(readFileSync(new URL("../../public/manifest.webmanifest", import.meta.url), "utf8"));
  assert.deepEqual(manifest.share_target, {
    action: "/",
    method: "GET",
    params: { title: "share_title", text: "share_text", url: "share_url" },
  });
  assert.deepEqual(manifest.protocol_handlers, [{ protocol: "geo", url: "/?geo=%s" }]);
});

test("the search box reads a pasted link before it is cut, and the app opens a share in Go", () => {
  const search = readFileSync(new URL("../PlaceSearch.tsx", import.meta.url), "utf8");
  assert.match(search, /onPaste=\{\(event\) => \{[\s\S]*?if \(!parseShared\(text, near\(\)\)\) return;\s*event\.preventDefault\(\);/);
  assert.match(search, /const offered: Place\[\] = \[\.\.\.sharedItems, \.\.\.\(empty \? recent : places\)\];/);
  // Review F10: the link's status region is always mounted (not mounted with its words), and filled after.
  assert.match(search, /<p className=\{sharedSaid \? "hint" : "visually-hidden"\} role="status" aria-live="polite">\s*\{sharedSaid\}\s*<\/p>/);
  assert.doesNotMatch(search, /\{shared && "said" in shared && \(/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /useSharedLaunch\(\(place\) => \{\s*if \(modeRef\.current !== "go"\) changeMode\("go"\);\s*goToPlace\(place\);\s*\}, setNotice\);/);
});

test("latitude and longitude in degrees, minutes and seconds, as GPS units and map apps write them (2026-10-31)", () => {
  const eps = 1e-3;
  for (const text of [
    `38°53'21.4"N 77°03'00.6"W`,
    `38°53′21.4″N 77°03′00.6″W`,
    `38° 53' 21.4'' N, 77° 3' 0.6'' W`,
    `38° 53.357' N, 77° 3.010' W`,
    `N 38° 53.357 W 077° 03.010`,
    `N38 53 21.4 W77 3 0.6`,
    `38 53 21.4 N 77 3 0.6 W`,
    `77°03'00.6"W 38°53'21.4"N`,
    `38.8893°, -77.0502°`,
    `38.8893 N 77.0502 W`,
  ]) {
    near(parseCoordinates(text)!, LINCOLN, eps);
  }
  // Not coordinates: plain numbers with no mark or letter, minutes past 59, two latitudes, a sign and a letter.
  // Halves are never split inside a number (review): with no sign or letter, the second is east, as written.
  near(parseCoordinates(`38°53' 77°03'`)!, [77.05, 38.88333], eps);
  near(parseCoordinates(`38 deg 77 deg`)!, [77, 38], eps);
  for (const text of [`E 4 N 5`, `S 1 E 1`, `38 53 21 77 3 0`, `38° 61' N, 77° 3' W`, `38° N 39° S`, `-38° N, 77° W`, `12 34`, `1600 Pennsylvania Ave`]) {
    assert.equal(parseCoordinates(text), null, text);
  }
});

test("typed coordinates and plus codes are named by what was typed, not as a shared link", () => {
  const typed = parseShared("38.8892686, -77.050176");
  assert.equal(typed?.kind === "point" && typed.typed, "coordinates");
  assert.deepEqual(sharedPlace(LINCOLN, undefined, "coordinates"), {
    name: "38.88927, -77.05018",
    label: "38.88927, -77.05018",
    lon: LINCOLN[0],
    lat: LINCOLN[1],
    kind: "coordinates",
  });
  const code = parseShared("vxqx+p3 Washington, District of Columbia");
  assert.ok(code?.kind === "point");
  assert.equal(code.typed, "pluscode");
  assert.equal(code.name, "VXQX+P3");
  near(code.point, [-77.0023125, 38.8893125]);
  // A short code is placed near the point given: here, the map's west edge.
  const west = parseShared("J422+22", [-77.8, 39.5]);
  near(west?.kind === "point" ? west.point : undefined, [-77.8999375, 39.6000625]);
  assert.equal(sharedPlace(LINCOLN, "VXQX+P3", "pluscode").kind, "pluscode");
  // A link's point stays a shared location.
  const link = parseShared("geo:38.8892686,-77.050176");
  assert.equal(link?.kind === "point" && link.typed, undefined);
});

test("a plus code read through readShared becomes a place with no request", async () => {
  const read = await readShared("87C4VXQX+P3", () => Promise.reject(new Error("no request expected")));
  assert.ok("place" in read);
  assert.equal(read.place.name, "87C4VXQX+P3");
  assert.equal(read.place.kind, "pluscode");
});
