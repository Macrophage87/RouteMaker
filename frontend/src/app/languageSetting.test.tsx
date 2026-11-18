// Settings > Display > Language: the draft note says how to report a wrong word, with the link where the language's
// own grammar puts it (the owner, 2026-11-12: "Tell us on Discord"); English shows no note.
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "../testSupport/render.ts";
import { setCatalogForTest, setLanguageForTest } from "../lib/i18n.ts";
import { BETA_DISCORD_URL } from "../lib/betaBanner.ts";
import { LanguageSetting } from "./LanguageSetting.tsx";

test("a draft language's note links to Discord to report a wrong word", async () => {
  setCatalogForTest("ko", { "Spot a wrong word? Tell us on {discord}.": "잘못된 단어가 있나요? {discord}에서 알려 주세요." });
  setLanguageForTest("ko");
  try {
    const screen = await render(<LanguageSetting />);
    const link = screen.get("link", /^Discord/);
    assert.equal(link.getAttribute("href"), BETA_DISCORD_URL);
    assert.match(screen.text(), /잘못된 단어가 있나요\? Discord.*에서 알려 주세요\./);
  } finally {
    setLanguageForTest("en");
  }
});

test("English shows no draft note", async () => {
  const screen = await render(<LanguageSetting />);
  assert.equal(screen.all("link").length, 0);
  assert.doesNotMatch(screen.text(), /Draft translation|Tell us on/);
});
