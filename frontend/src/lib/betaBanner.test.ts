// The private-beta notice (lib/betaBanner.ts): off unless the build says VITE_BETA=1,
// a labelled region in the planner rather than a dialog, dismissible for the session,
// never trapping focus, naming no channel, with a report link only when one is configured.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  BETA_BANNER_TEXT,
  BETA_DISMISS_KEY,
  BETA_REPORT_LINK_TEXT,
  BetaBanner,
  betaDismissed,
  betaReportUrl,
  dismissBeta,
  isBetaBuild,
} from "./betaBanner.ts";
import type { StorageLike } from "./signIn.ts";

function memory(initial: Record<string, string> = {}): StorageLike & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v;
    },
    removeItem: (k) => {
      delete data[k];
    },
  };
}

const throwing: StorageLike = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
  removeItem: () => {
    throw new Error("blocked");
  },
};

const render = (props: Parameters<typeof BetaBanner>[0]) => renderToStaticMarkup(createElement(BetaBanner, props));

test("the flag is on for exactly '1' or 'true' and off for everything else, including unset", () => {
  assert.equal(isBetaBuild("1"), true);
  assert.equal(isBetaBuild("true"), true);
  for (const off of [undefined, "", "0", "false", "yes", 1, true, null]) assert.equal(isBetaBuild(off), false, String(off));
});

test("disabled, the banner renders nothing at all", () => {
  assert.equal(render({ enabled: false, storage: memory() }), "");
});

test("enabled, it is a region labelled 'Beta notice', not a live region or a dialog", () => {
  const html = render({ enabled: true, storage: memory() });
  assert.match(html, /^<section class="beta-banner" aria-label="Beta notice"/);
  assert.doesNotMatch(html, /role=|aria-live|aria-modal|tabindex/i);
  assert.ok(html.includes(BETA_BANNER_TEXT.replace("'", "&#x27;")), html);
});

test("the text names no channel: it says to tell the person who gave you access (OWNER-DECISIONS 382)", () => {
  assert.equal(
    BETA_BANNER_TEXT,
    "Beta: routes may still use some paths where bikes aren't allowed until the next map update. If anything looks wrong, tell the person who gave you access.",
  );
  assert.doesNotMatch(BETA_BANNER_TEXT, /discord|e-?mail|@|https?:/i);
});

test("its dismiss control is a named button of its own, with the visible word in its name", () => {
  const html = render({ enabled: true, storage: memory() });
  assert.match(html, /<button type="button" aria-label="Dismiss beta notice">Dismiss<\/button>/);
  assert.equal(html.match(/<button/g)?.length, 1);
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

test("with no report link there is no link at all; with one, it opens in a new tab and says so", () => {
  assert.doesNotMatch(render({ enabled: true, storage: memory() }), /<a /);
  assert.doesNotMatch(render({ enabled: true, reportUrl: null, storage: memory() }), /<a /);
  const html = render({ enabled: true, reportUrl: "https://discord.gg/abc123", storage: memory() });
  assert.match(
    html,
    /<a href="https:\/\/discord\.gg\/abc123" target="_blank" rel="noopener noreferrer">Report a problem<span class="visually-hidden"> \(opens in a new tab\)<\/span><\/a>/,
  );
  assert.equal(BETA_REPORT_LINK_TEXT, "Report a problem");
  assert.equal(html.match(/<a /g)?.length, 1);
});

test("a dismissal in this tab hides it, and an untouched tab still shows it", () => {
  const store = memory();
  assert.equal(betaDismissed(store), false);
  dismissBeta(store);
  assert.equal(store.data[BETA_DISMISS_KEY], "1");
  assert.equal(betaDismissed(store), true);
  assert.equal(render({ enabled: true, storage: store }), "");
  assert.notEqual(render({ enabled: true, storage: memory() }), "");
});

test("storage that throws or is missing never breaks the banner: it shows, and dismissing does not throw", () => {
  assert.equal(betaDismissed(throwing), false);
  assert.equal(betaDismissed(null), false);
  assert.doesNotThrow(() => dismissBeta(throwing));
  assert.doesNotThrow(() => dismissBeta(null));
  assert.notEqual(render({ enabled: true, storage: throwing }), "");
  assert.notEqual(render({ enabled: true, storage: null }), "");
});

test("App wires it to the build flags and nothing else, so the local site is unchanged", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.equal(app.match(/<BetaBanner\b/g)?.length, 1);
  assert.match(
    app,
    /<BetaBanner\s+enabled=\{isBetaBuild\(import\.meta\.env\.VITE_BETA\)\}\s+reportUrl=\{betaReportUrl\(import\.meta\.env\.VITE_BETA_REPORT_URL\)\}\s+\/>/,
  );
});

test("App puts it in the planner, under the header and before the planner's body (accessibility S1)", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const banner = app.indexOf("<BetaBanner");
  const aside = app.indexOf('id="route-planner"');
  const header = app.indexOf("</header>", aside);
  const body = app.indexOf('id="panel-body"', aside);
  assert.ok(aside > 0 && header > aside && body > header, "the planner's layout moved");
  assert.ok(banner > header && banner < body, "the banner must sit between the planner's header and body");
  assert.ok(app.indexOf("<a className=\"skip-link\"") < aside, "the skip link still comes first");
});

test("the notice flows inside the panel: no overlay, no z-index, a rem font size and a 44px button", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  const rules = [...css.matchAll(/\.beta-banner[^{]*\{([^}]*)\}/g)].map((m) => m[1]).join("\n");
  assert.ok(rules, "no .beta-banner rules");
  assert.doesNotMatch(rules, /position:\s*(absolute|fixed)|z-index/);
  assert.doesNotMatch(rules, /font-size:\s*[0-9.]+px/);
  assert.match(css, /\.beta-banner \{[^}]*font-size: 0\.875rem/);
  const button = css.match(/\.beta-banner button \{([^}]*)\}/)?.[1] ?? "";
  assert.match(button, /min-height: 44px/);
  assert.match(button, /min-width: 44px/);
});
