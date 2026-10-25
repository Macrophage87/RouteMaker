// The private-beta notice (lib/betaBanner.ts): off unless the build says VITE_BETA=1,
// a "Beta" chip in the map's bottom-left corner that shows and hides a labelled region
// (not a dialog), never trapping focus, linking the Discord for reports and, in small print,
// the sign-up form, with a further report link only when one is configured.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  BETA_BANNER_TEXT,
  BETA_DISCORD_URL,
  BETA_REPORT_LINK_TEXT,
  BETA_SIGNUP_TEXT,
  BETA_SIGNUP_URL,
  BetaChip,
  betaReportUrl,
  isBetaBuild,
} from "./betaBanner.ts";
import { appSource } from "../testSupport/appSource.mjs";

const render = (props: Parameters<typeof BetaChip>[0]) => renderToStaticMarkup(createElement(BetaChip, props));

test("the flag is on for exactly '1' or 'true' and off for everything else, including unset", () => {
  assert.equal(isBetaBuild("1"), true);
  assert.equal(isBetaBuild("true"), true);
  for (const off of [undefined, "", "0", "false", "yes", 1, true, null]) assert.equal(isBetaBuild(off), false, String(off));
});

test("disabled, it renders nothing at all", () => {
  assert.equal(render({ enabled: false }), "");
  assert.equal(render({ enabled: false, initiallyOpen: true, reportUrl: "https://discord.gg/abc123" }), "");
});

test("enabled, it is one 'Beta' chip: a disclosure button named 'Beta notice', closed at first", () => {
  const html = render({ enabled: true });
  assert.match(html, /^<div class="beta-chip" data-testid="beta-chip">/);
  const button = html.match(/<button[^>]*>[^<]*<\/button>/)?.[0] ?? "";
  assert.match(button, /^<button type="button" class="beta-chip-button" aria-label="Beta notice" aria-expanded="false" aria-controls="([^"]+)">Beta<\/button>$/);
  assert.equal(html.match(/<button/g)?.length, 1, "no Dismiss: nothing but the chip");
  assert.doesNotMatch(html, /Dismiss/);
  // The note is in the page, hidden, and the chip names it.
  const controls = button.match(/aria-controls="([^"]+)"/)?.[1];
  assert.match(html, new RegExp(`<section id="${controls}" class="beta-chip-note" aria-label="Beta notice" hidden="">`));
});

test("open, the note is a region labelled 'Beta notice' with the text, not a live region or a dialog", () => {
  const html = render({ enabled: true, initiallyOpen: true });
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /<section id="[^"]+" class="beta-chip-note" aria-label="Beta notice">/);
  assert.doesNotMatch(html, /role=|aria-live|aria-modal|tabindex/i);
  assert.ok(html.includes(BETA_BANNER_TEXT.replace("'", "&#x27;")), html);
});

test("Escape or the chip again closes it, and the focus goes back to the chip", () => {
  const source = readFileSync(new URL("./betaBanner.ts", import.meta.url), "utf8");
  assert.match(source, /onClick: \(\) => setOpen\(!open\)/);
  assert.match(source, /event\.key !== "Escape" \|\| !open[\s\S]*setOpen\(false\);\s*chip\.current\?\.focus\(\);/);
  assert.doesNotMatch(source, /sessionStorage|localStorage|getElementById/, "no dismissal to remember");
});

test("for reports it links the public Discord, and in small print the sign-up form (owner, 2026-10-25)", () => {
  assert.equal(
    BETA_BANNER_TEXT,
    "Beta: routes may still use some paths where bikes aren't allowed until the next map update. If anything looks wrong, tell us on",
  );
  assert.equal(BETA_DISCORD_URL, "https://discord.gg/Qwz6BEt6gc");
  assert.equal(BETA_SIGNUP_URL, "https://forms.gle/dipMsGpheyF3oQA59");
  assert.equal(BETA_SIGNUP_TEXT, "Sign up to test here!");
  const html = render({ enabled: true, initiallyOpen: true });
  const newTab = '<span class="visually-hidden"> (opens in a new tab)</span>';
  assert.ok(
    html.includes(
      `tell us on <a href="${BETA_DISCORD_URL}" target="_blank" rel="noopener noreferrer">Discord${newTab}</a>.</p>`,
    ),
    html,
  );
  assert.ok(
    html.includes(
      `<p class="beta-chip-signup"><a href="${BETA_SIGNUP_URL}" target="_blank" rel="noopener noreferrer">Sign up to test here!${newTab}</a></p>`,
    ),
    html,
  );
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /\.beta-chip-note \.beta-chip-signup \{[^}]*font-size: 0\.75rem;/, "small print, in rem");
});

test("the report link is an https address only; anything else gives no link", () => {
  assert.equal(betaReportUrl("https://discord.gg/abc123"), "https://discord.gg/abc123");
  assert.equal(betaReportUrl("  https://example.org/report?x=1  "), "https://example.org/report?x=1");
  for (const bad of [
    undefined,
    null,
    "",
    "   ",
    1,
    "http://example.org/",
    "javascript:alert(1)",
    "data:text/html,hi",
    "//example.org/",
    "example.org",
    "https://user:pw@example.org/",
    "https://",
  ]) {
    assert.equal(betaReportUrl(bad), null, String(bad));
  }
});

test("with no report link there is no Report a problem link; with one, it opens in a new tab and says so", () => {
  for (const reportUrl of [undefined, null, BETA_DISCORD_URL]) {
    const html = render({ enabled: true, initiallyOpen: true, reportUrl });
    assert.doesNotMatch(html, /Report a problem/, String(reportUrl));
    assert.equal(html.match(/<a /g)?.length, 2, "Discord and sign-up only");
  }
  const html = render({ enabled: true, initiallyOpen: true, reportUrl: "https://example.org/report" });
  assert.match(
    html,
    /<a href="https:\/\/example\.org\/report" target="_blank" rel="noopener noreferrer">Report a problem<span class="visually-hidden"> \(opens in a new tab\)<\/span><\/a>/,
  );
  assert.equal(BETA_REPORT_LINK_TEXT, "Report a problem");
  assert.equal(html.match(/<a /g)?.length, 3);
});

test("App wires it to the build flags and nothing else, so the local site is unchanged", () => {
  const app = appSource();
  assert.equal(app.match(/<BetaChip\b/g)?.length, 1);
  assert.doesNotMatch(app, /BetaBanner/);
  assert.match(
    app,
    /\{!riding && \(\s*<BetaChip\s+enabled=\{isBetaBuild\(import\.meta\.env\.VITE_BETA\)\}\s+reportUrl=\{betaReportUrl\(import\.meta\.env\.VITE_BETA_REPORT_URL\)\}\s+\/>\s*\)\}/,
  );
});

test("App puts it on the map, after the map's own controls and before the planner, not in the planner", () => {
  const app = appSource();
  const chip = app.indexOf("<BetaChip");
  assert.ok(app.indexOf("<MapView") < chip && app.indexOf('className="map-history"') < chip, "after the map and its controls");
  assert.ok(chip < app.indexOf("<aside"), "before the planner");
  assert.ok(app.indexOf("<a className=\"skip-link\"") < chip, "the skip link still comes first");
});

test("the chip sits in the map's free bottom-left corner: 44 px, a rem font size, clear of the panel and the credits", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /\.beta-banner/, "the old banner's rules are gone");
  const chip = css.match(/\.beta-chip \{([^}]*)\}/)?.[1] ?? "";
  assert.match(chip, /position: absolute;\s*left: calc\(var\(--panel-w\) \+ 24px\);\s*bottom: 10px;/);
  assert.match(chip, /font-size: 0\.875rem/);
  const rules = [...css.matchAll(/\.beta-chip[^{]*\{([^}]*)\}/g)].map((m) => m[1]).join("\n");
  assert.doesNotMatch(rules, /font-size:\s*[0-9.]+px/);
  const button = css.match(/\.beta-chip-button \{([^}]*)\}/)?.[1] ?? "";
  assert.match(button, /min-height: 44px/);
  assert.match(button, /min-width: 44px/);
  assert.match(button, /background: var\(--bg\);\s*color: var\(--text\);/, "theme colours, so light, dark and High contrast all pass");
  // The credits stop short of it on a computer; on a phone it rides above the sheet as they do.
  assert.match(css, /\.maplibregl-ctrl-bottom-right \.maplibregl-ctrl-attrib \{\s*box-sizing: border-box;\s*max-width: calc\(100vw - 510px - var\(--out-w, 0px\)\);/, "the padding counts inside the width, so the credits really stop short of the chip");
  for (const [sheet, bottom] of [
    [/\.app:has\(\.panel\.open\) \.beta-chip/, "calc(48% + 10px)"],
    [/\.app:has\(\.panel\.closed\) \.beta-chip/, "76px"],
    // Go's sheet is as tall as its content: the chip rides on its measured height (App, --go-sheet-h).
    [/\.app\.go-mode:has\(\.panel\.go-peek\) \.beta-chip/, "calc(var(--go-sheet-h, 34%) + 10px)"],
    [/\.app\.go-mode:has\(\.panel\.go-half\) \.beta-chip/, "calc(var(--go-sheet-h, 56%) + 10px)"],
  ] as const) {
    assert.match(css, new RegExp(`${sheet.source} \\{\\s*bottom: ${bottom.replace(/[()+%-]/g, "\\$&")};`));
  }
});
