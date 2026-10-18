import { test } from "node:test";
import assert from "node:assert/strict";
import { matchSaid, matching, noMatch } from "./routeSearch.ts";

const names = ["Dupont to Glen Echo", "Café loop", "Baltimore by MARC"];

test("the search keeps the routes holding every word, in any order, case and accents ignored", () => {
  assert.deepEqual(matching(names, "", (n) => n), names);
  assert.deepEqual(matching(names, "  ", (n) => n), names);
  assert.deepEqual(matching(names, "echo dupont", (n) => n), ["Dupont to Glen Echo"]);
  assert.deepEqual(matching(names, "CAFE", (n) => n), ["Café loop"]);
  assert.deepEqual(matching(names, "marc dupont", (n) => n), []);
  assert.equal(noMatch(" towpath "), 'No routes match "towpath".');
});

test("while searched, each list says politely how many of its routes match; nothing when blank", () => {
  assert.equal(matchSaid(3, 12, ""), "");
  assert.equal(matchSaid(3, 12, " loop "), '3 of 12 match "loop".');
  assert.equal(matchSaid(0, 12, "loop"), 'No routes match "loop".');
});
