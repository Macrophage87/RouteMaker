import { test } from "node:test";
import assert from "node:assert/strict";
import { crashReport, errorText, KEPT_ERRORS, logError, safeFragment, withoutPlaces, type LoggedError } from "./crashReport.ts";

test("the link's places are left out of the report, its settings kept", () => {
  assert.equal(
    safeFragment("#p=-76.70929,39.15905;-77.01203,38.89853&preset=default&v=2&stress=70&hills=0&loop=1"),
    "#p=(left out)&preset=default&v=2&stress=70&hills=0&loop=1",
  );
  assert.equal(safeFragment("#follow=abc&stress=50"), "#follow=(left out)&stress=50");
  assert.equal(safeFragment(""), "(none)");
});

test("only the last few uncaught errors are kept, oldest first", () => {
  const into: LoggedError[] = [];
  for (let i = 0; i < KEPT_ERRORS + 3; i += 1) logError("error", new Error(`e${i}`), i, into);
  assert.equal(into.length, KEPT_ERRORS);
  assert.match(into[0].text, /e3\b/);
  assert.match(into.at(-1)!.text, new RegExp(`e${KEPT_ERRORS + 2}\\b`));
});

test("the report holds the version, the error, where in the page, and the earlier errors, without the places", () => {
  const error = new TypeError("Cannot read properties of undefined (reading 'contains')");
  const text = crashReport({
    error,
    componentStack: "\n    at MapView\n    at App",
    at: Date.UTC(2026, 9, 25, 11, 24),
    hash: "#p=-76.7,39.1;-77.0,38.8&stress=70",
    path: "/",
    userAgent: "Chrome",
    logged: [{ at: Date.UTC(2026, 9, 25, 11, 20), kind: "error", text: "TypeError: earlier" }],
    version: "0.12.2",
  });
  assert.match(text, /^RouteMaker error report\nVersion: 0\.12\.2\nTime: 2026-10-25T11:24:00\.000Z\nPage: \/ #p=\(left out\)&stress=70\n/);
  assert.ok(text.includes("reading 'contains'"));
  assert.ok(text.includes("Where in the page:\nat MapView"));
  assert.ok(text.includes("Earlier errors (1, oldest first):\n- 2026-10-25T11:20:00.000Z error: TypeError: earlier"));
  assert.ok(!text.includes("39.1"), "no place in the report");
});

test("an error that is not an Error is still written down", () => {
  assert.equal(errorText("plain"), "plain");
  assert.equal(errorText({ code: 3 }), '{"code":3}');
  assert.equal(errorText(undefined), "undefined");
});

test("coordinates and tile numbers in an error's own text are left out", () => {
  assert.equal(withoutPlaces("no route near -77.01203,38.89853 today"), "no route near (place left out) today");
  assert.equal(withoutPlaces("AJAXError: Not Found (404): https://x/tiles/stress/14/4686/6267.pbf"), "AJAXError: Not Found (404): https://x/tiles/stress/(tile left out).pbf");
  assert.equal(withoutPlaces("at index-C5wyiE6K.js:267:35304"), "at index-C5wyiE6K.js:267:35304", "a stack's line and column stay");
  assert.equal(errorText({ url: "/basemap/12/1171/1566.mvt" }), '{"url":"/basemap/(tile left out).mvt"}');
  assert.equal(withoutPlaces("Invalid LngLat(-77.04, 38.91)"), "Invalid LngLat((place left out))");
  assert.equal(withoutPlaces("bad point -77.04%2C38.91"), "bad point (place left out)");
  assert.equal(withoutPlaces('near lat 38.90123 lon -77.03456, {"lng":-77.1}'), 'near lat (left out) lon (left out), {"lng":(left out)}');
  assert.equal(withoutPlaces("Failed to fetch https://x/api/geocode?q=Union+Market&near=1 (500)"), "Failed to fetch https://x/api/geocode?(query left out) (500)");
  assert.equal(withoutPlaces("RouteMaker 0.12.2, maplibre 6.14.0"), "RouteMaker 0.12.2, maplibre 6.14.0", "version numbers stay");
});
