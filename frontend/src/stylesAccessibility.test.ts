// The stylesheet's two accessibility blocks (OWNER-DECISIONS 209, 211): the
// strong borders and muted text that hang from the `.a11y` class on the root
// (the switch, not a media query), and the forced-colors block that keeps the
// swatches and markers legible in a system contrast theme (automatic).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { contrastRatio } from "./stressStyle.js";

const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

/** The body of the first `@media (query) { ... }`, by matching braces. */
function mediaBody(source: string, query: string, from = 0): string | null {
  const start = source.indexOf(`@media ${query}`, from);
  if (start < 0) return null;
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(open + 1, i);
    }
  }
  return null;
}

/** The rules of a block with no nesting: selector list and declarations. */
function rules(body: string): Array<{ selectors: string[]; declarations: string }> {
  return [...body.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({
    selectors: m[1].replace(/\/\*[\s\S]*?\*\//g, "").split(",").map((s) => s.trim()).filter(Boolean),
    declarations: m[2],
  }));
}

const forced = mediaBody(css, "(forced-colors: active)");

/** What the forced-colors block declares for `selector`, all rules that name it together. */
function forcedFor(selector: string): string {
  return rules(forced ?? "")
    .filter((r) => r.selectors.includes(selector))
    .map((r) => r.declarations)
    .join(";");
}

/** The legend and stress-bar swatches, and the junction markers drawn in HTML. */
const SWATCHES = [".legend svg", ".stress-list svg", ".swatch", ".stress-bar", ".stress-seg"];
const BORDERED = [".legend svg", ".stress-list svg", ".swatch", ".stress-bar"];
const MARKERS = [".junction-marker", ".junction-icon"];

test("the forced-colors block exists", () => {
  assert.ok(forced && forced.length > 100, "an @media (forced-colors: active) block");
});

test("in forced colours the swatches keep their own colours, so they still match the WebGL map", () => {
  for (const selector of SWATCHES) {
    assert.match(forcedFor(selector), /forced-color-adjust:\s*none/, selector);
  }
});

test("in forced colours each swatch has a system-colour border, and the bar's segments are divided", () => {
  for (const selector of BORDERED) {
    assert.match(forcedFor(selector), /border:\s*1px solid CanvasText/, selector);
  }
  assert.match(forcedFor(".stress-seg + .stress-seg"), /border-left:\s*1px solid CanvasText/);
});

test("in forced colours the switch's stronger swatch borders give way to the system's: every .a11y border rule is repeated there", () => {
  const outside = css.replace(forced ?? "", "");
  const a11yBorders = rules(outside)
    .filter((r) => /border/.test(r.declarations))
    .flatMap((r) => r.selectors)
    .filter((selector) => selector.startsWith(".a11y "));
  assert.deepEqual(a11yBorders.sort(), [".a11y .stress-bar", ".a11y .swatch"], "the premise: the switch strengthens these borders");
  for (const selector of a11yBorders) assert.match(forcedFor(selector), /border:\s*1px solid CanvasText/, selector);
});

test("in forced colours the junction markers keep their shape and the count its words, with a system outline", () => {
  for (const selector of MARKERS) assert.match(forcedFor(selector), /forced-color-adjust:\s*none/, selector);
  assert.match(forcedFor(".junction-marker"), /outline:\s*1px solid CanvasText/);
  assert.doesNotMatch(forcedFor(".junction-count"), /forced-color-adjust:\s*none/, "the count's text follows the system's colours");
});

test("the app's own panels, buttons and text follow the system's colours: nothing else opts out", () => {
  const optedOut = rules(css)
    .filter((r) => /forced-color-adjust:\s*none/.test(r.declarations))
    .flatMap((r) => r.selectors);
  const optedOutInForced = rules(forced ?? "")
    .filter((r) => /forced-color-adjust:\s*none/.test(r.declarations))
    .flatMap((r) => r.selectors);
  assert.deepEqual([...optedOutInForced].sort(), [...SWATCHES, ...MARKERS].sort());
  for (const selector of [".panel", "body", "button", ".switch", ".switch-state", ":focus-visible", ".map"]) {
    assert.ok(![...optedOut, ...optedOutInForced].includes(selector), `${selector} follows the system`);
  }
});

test("in forced colours buttons and the switch keep a visible border, and focus keeps a visible ring", () => {
  for (const selector of ["button", ".switch", ".switch-state"]) assert.match(forcedFor(selector), /border-color:\s*ButtonText/, selector);
  assert.match(forcedFor(":focus-visible"), /outline:\s*3px solid Highlight/);
  assert.match(forcedFor(".junction-marker:focus-visible"), /outline:\s*3px solid Highlight/, "a marker that opts out of forced colours still has the system's ring");
  assert.match(forcedFor(".switch[aria-checked=\"true\"] .switch-state"), /border-width:\s*3px/, "the switch's on state is told from off by its word and a heavier border, not a colour the system may replace");
  assert.doesNotMatch(forcedFor(".switch[aria-checked=\"true\"] .switch-state"), /background|(^|[;\s])color:/, "and sets no colour of its own that forced colours would override");
});

test("the premise: the selectors the forced-colors block names are in the app's markup", () => {
  const dir = fileURLToPath(new URL(".", import.meta.url));
  const sources: string[] = [];
  const walk = (d: string) => {
    for (const entry of readdirSync(d)) {
      const path = join(d, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(tsx|ts)$/.test(entry) && !/\.test\./.test(entry)) sources.push(readFileSync(path, "utf8"));
    }
  };
  walk(dir);
  const all = sources.join("\n");
  for (const name of ["legend", "swatch", "stress-bar", "stress-seg", "junction-marker", "junction-icon", "junction-count", "stress-list", "switch", "switch-state"]) {
    assert.ok(all.includes(name), `class ${name} is used`);
  }
  assert.match(all, /<svg width="44"/, "the stress legend's swatches are inline SVG in .legend");
});

/** A custom property's value in a rule body. */
const property = (body: string, name: string): string => {
  const m = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(body);
  assert.ok(m, `${name} in ${body.slice(0, 60)}`);
  return m[1].toLowerCase();
};

test("the accessibility class strengthens the panel's borders and muted text, by a class and not by a media query", () => {
  assert.equal(css.includes("prefers-contrast"), false, "the switch is the rider's; the stylesheet does not read the preference");
  const light = rules(css).find((r) => r.selectors.includes(":root.a11y"));
  assert.ok(light, ":root.a11y rule");
  const dark = rules(mediaBody(css, "(prefers-color-scheme: dark)", css.indexOf(":root.a11y")) ?? "").find((r) => r.selectors.includes(":root.a11y"));
  assert.ok(dark, "a dark :root.a11y rule");
  const plainLight = rules(css).find((r) => r.selectors.includes(":root"));
  const plainDark = rules(mediaBody(css, "(prefers-color-scheme: dark)") ?? "").find((r) => r.selectors.includes(":root"));
  assert.ok(plainLight && plainDark);
  for (const [strong, plain] of [[light, plainLight], [dark, plainDark]] as const) {
    const bg = property(plain.declarations, "--bg");
    // Muted text: AAA (7:1) and stronger than before; borders: well over the 3:1 non-text floor and stronger than before.
    assert.ok(contrastRatio(property(strong.declarations, "--text-muted"), bg) >= 7);
    assert.ok(contrastRatio(property(strong.declarations, "--text-muted"), bg) > contrastRatio(property(plain.declarations, "--text-muted"), bg));
    assert.ok(contrastRatio(property(strong.declarations, "--border"), bg) >= 4.5);
    assert.ok(contrastRatio(property(strong.declarations, "--border"), bg) > contrastRatio(property(plain.declarations, "--border"), bg));
  }
});

test("the plain borders and muted text are as they were: the strong ones apply only with the class", () => {
  assert.match(rules(css).find((r) => r.selectors.includes(":root"))?.declarations ?? "", /--border:\s*#cfd4dc/);
  assert.match(rules(css).find((r) => r.selectors.includes(":root"))?.declarations ?? "", /--text-muted:\s*#4b5260/);
});

test("the swatches' borders are the text colour with the class on", () => {
  const swatch = rules(css).find((r) => r.selectors.includes(".a11y .swatch"));
  assert.match(swatch?.declarations ?? "", /border-color:\s*var\(--text\)/);
  assert.ok(rules(css).some((r) => r.selectors.includes(".a11y .stress-bar")));
});
