// Small stylesheet fixes from the 2026-10-16 review (UI-3, UI-5, UI-6, UI-8, UI-9), read as source.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

/** The bodies of every `@media (query) { ... }`, by matching braces. */
function mediaBodies(query: string): string[] {
  const out: string[] = [];
  for (let start = css.indexOf(`@media ${query}`); start >= 0; start = css.indexOf(`@media ${query}`, start + 1)) {
    const open = css.indexOf("{", start);
    let depth = 0;
    for (let i = open; i < css.length; i += 1) {
      if (css[i] === "{") depth += 1;
      if (css[i] === "}" && --depth === 0) {
        out.push(css.slice(open + 1, i));
        break;
      }
    }
  }
  return out;
}

/** The declarations of the rules whose selector list is exactly `selector`, in `source`. */
function declared(source: string, selector: string): string {
  return [...source.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => m[1].replace(/\/\*[\s\S]*?\*\//g, "").trim() === selector)
    .map((m) => m[2])
    .join(";");
}

test("UI-3: on a phone, Go's full sheet leaves room for the taller bar with a destination", () => {
  const phone = mediaBodies("(max-width: 720px)").join("\n");
  assert.match(declared(phone, ".app.go-mode:has(.go-destination) .panel.go-panel.go-full"), /max-height:\s*calc\(100% - 114px\)/);
});

test("UI-5: a sheet's header, with its Back button, stays in view as the sheet scrolls", () => {
  const header = declared(css, ".sheet-header");
  assert.match(header, /position:\s*sticky/);
  assert.match(header, /top:\s*0/);
  assert.match(header, /background:\s*var\(--bg\)/);
});

test("UI-6: in forced colours a pressed toggle has a ring of its own, and the focus ring stays", () => {
  const forced = mediaBodies("(forced-colors: active)").join("\n");
  assert.match(declared(forced, '[aria-pressed="true"]:not(:focus-visible)'), /outline:\s*3px solid ButtonText/);
});

test("UI-8: rules for classes nothing uses are gone", () => {
  for (const name of [".tagline", ".federal-status", ".alert-more-body"]) assert.ok(!css.includes(name), name);
});

test("UI-9: the section tools row centres its buttons", () => {
  assert.match(declared(css, ".section-tools"), /align-items:\s*center/);
});
