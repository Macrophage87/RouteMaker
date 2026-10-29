import { test } from "node:test";
import assert from "node:assert/strict";
import { setCatalogForTest } from "./i18n.ts";
import { railWord } from "./railWords.ts";

test("the rail's short word where a language has one, else the phrase as translated", () => {
  setCatalogForTest("ru", { "Share live": "Делиться в реальном времени", Locate: "Где я" });
  assert.equal(railWord("Share live", "ru"), "Эфир");
  assert.equal(railWord("Locate", "ru"), "Где я");
  assert.equal(railWord("Share live", "en"), "Share live");
});
