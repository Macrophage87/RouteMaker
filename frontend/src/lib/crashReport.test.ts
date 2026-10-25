import { test } from "node:test";
import assert from "node:assert/strict";
import { crashReport, errorText, KEPT_ERRORS, logError, safeFragment, type LoggedError } from "./crashReport.ts";

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
