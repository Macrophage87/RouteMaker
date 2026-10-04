// The private-beta notice (lib/betaBanner.ts): off unless the build says VITE_BETA=1,
// a status strip rather than a dialog, dismissible for the session, never trapping focus.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  BETA_BANNER_TEXT,
  BETA_DISMISS_KEY,
  BetaBanner,
  betaDismissed,
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

test("enabled, it says the agreed text in a role=status strip that is not a dialog", () => {
  const html = render({ enabled: true, storage: memory() });
  assert.match(html, /role="status"/);
  assert.ok(html.includes(BETA_BANNER_TEXT.replace("'", "&#x27;")), html);
  assert.doesNotMatch(html, /role="(alert)?dialog"|aria-modal|tabindex/i);
  assert.equal(BETA_BANNER_TEXT, "Beta: routes may still use some paths where bikes aren't allowed until the next map update. Please report anything odd.");
});

test("its dismiss control is a named button of its own, with the visible word in its name", () => {
  const html = render({ enabled: true, storage: memory() });
  assert.match(html, /<button type="button" aria-label="Dismiss beta notice">Dismiss<\/button>/);
  assert.equal(html.match(/<button/g)?.length, 1);
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

test("App wires it to the build flag and nothing else, so the local site is unchanged", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.equal(app.match(/<BetaBanner /g)?.length, 1);
  assert.match(app, /<BetaBanner enabled=\{isBetaBuild\(import\.meta\.env\.VITE_BETA\)\} \/>/);
});

test("the strip is styled to stay clear of the planner and to give the button a 44px target", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  const rule = css.match(/\.beta-banner button \{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /min-height: 44px/);
  assert.match(rule, /min-width: 44px/);
  assert.match(css, /\.beta-banner \{[^}]*position: absolute/);
});
