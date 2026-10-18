import { test } from "node:test";
import assert from "node:assert/strict";
import { matching, noMatch } from "./routeSearch.ts";

const names = ["Dupont to Glen Echo", "Café loop", "Baltimore by MARC"];

test("the search keeps the routes holding every word, in any order, case and accents ignored", () => {
  assert.deepEqual(matching(names, "", (n) => n), names);
  assert.deepEqual(matching(names, "  ", (n) => n), names);
  assert.deepEqual(matching(names, "echo dupont", (n) => n), ["Dupont to Glen Echo"]);
  assert.deepEqual(matching(names, "CAFE", (n) => n), ["Café loop"]);
  assert.deepEqual(matching(names, "marc dupont", (n) => n), []);
  assert.equal(noMatch(" towpath "), 'No routes match "towpath".');
});
