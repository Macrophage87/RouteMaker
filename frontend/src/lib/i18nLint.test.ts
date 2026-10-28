/**
 * Text a rider sees that is not passed through t() (the 2026-10-28 audit, P9): lib/i18n.test.ts checks the phrases
 * the code marks, so a plain JSX text child or a plain aria-label slipped past it and showed English on a Spanish
 * page. This reads every component file (src/**\/*.tsx) with the parser Vite already uses and fails on
 *   - JSX text with a letter in it: <p>Saved</p>
 *   - a string with a letter as a JSX child: <p>{"Saved"}</p>, <p>{`Saved ${n}`}</p>
 *   - a string with a letter in aria-label, title, placeholder or alt: aria-label="Close", title={`Map ${n}`}
 * Fix one by putting it through t() (t("Saved"), t("Map {n}", { n })) and adding its Spanish to src/i18n/es.ts, or,
 * where it must stay as written (a brand, a symbol, a unit formatted elsewhere), by adding it to ALLOWED below with
 * the reason. Strings built in .ts modules are not read here: lib/i18n.test.ts and the modules' own tests cover those.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { parseAst } from "rolldown/parseAst";

const SRC = fileURLToPath(new URL("..", import.meta.url));

/** The props a screen reader says or a rider reads. */
const PROPS = new Set(["aria-label", "title", "placeholder", "alt"]);

/**
 * What may stay as written, by file (relative to src/) and its text, with why. A whole file is "*". An entry that
 * no longer matches anything fails the test too, so the list stays short.
 */
const ALLOWED: readonly { file: string; text: string; why: string }[] = [
  { file: "ReviewMode.tsx", text: "*", why: "the reviewers' screen (signed-in reviewers only), English as the review tools are" },
  { file: "ClosureReview.tsx", text: "*", why: "the reviewers' closure list (signed-in reviewers only), English as the review tools are" },
  { file: "App.tsx", text: "v", why: "the version's prefix, v0.14.0" },
  { file: "MyRoutes.tsx", text: "GPX", why: "the file format's name" },
  { file: "app/RoutePanel.tsx", text: "GPX", why: "the file format's name" },
  { file: "RailStations.tsx", text: "Metro", why: "the system's name" },
];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return name.endsWith(".tsx") && !name.includes(".test.") ? [path] : [];
  });
}

interface Found {
  file: string;
  line: number;
  text: string;
  where: string;
}

const LETTER = /\p{L}/u;

/** A string or template literal's text ("${…}" for each placeholder), or null for anything else. */
function stringOf(node: { type: string; value?: unknown; quasis?: { value: { cooked: string | null; raw: string } }[] } | null | undefined): string | null {
  if (!node) return null;
  if (node.type === "Literal" && typeof node.value === "string") return node.value;
  if (node.type === "TemplateLiteral" && node.quasis) return node.quasis.map((q) => q.value.cooked ?? q.value.raw).join("${…}");
  return null;
}

/** What one component file shows untranslated; `file` is its name in the report. */
function untranslated(source: string, file: string): Found[] {
  const lineStarts = [0];
  for (let i = 0; i < source.length; i += 1) if (source[i] === "\n") lineStarts.push(i + 1);
  const lineOf = (offset: number) => {
    let lo = 0;
    let hi = lineStarts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lineStarts[mid] <= offset) lo = mid;
      else hi = mid - 1;
    }
    return lo + 1;
  };
  const found: Found[] = [];
  const add = (start: number, text: string, where: string) => {
    const shown = text.replace(/\s+/g, " ").trim();
    // The line its first word is on, not the line break before it.
    const lead = text.length - text.trimStart().length;
    if (LETTER.test(shown.replace(/\$\{…\}/g, ""))) found.push({ file, line: lineOf(start + lead), text: shown, where });
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const walk = (node: any, parent: any): void => {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const child of node) walk(child, parent);
      return;
    }
    if (node.type === "JSXText") add(node.start, node.value, "text");
    else if (node.type === "JSXExpressionContainer" && (parent?.type === "JSXElement" || parent?.type === "JSXFragment")) {
      const text = stringOf(node.expression);
      if (text !== null) add(node.start, text, "text");
    } else if (node.type === "JSXAttribute" && node.name?.type === "JSXIdentifier" && PROPS.has(node.name.name)) {
      const value = node.value?.type === "JSXExpressionContainer" ? node.value.expression : node.value;
      const text = stringOf(value);
      if (text !== null) add(node.start, text, node.name.name);
    }
    for (const key of Object.keys(node)) if (key !== "start" && key !== "end") walk(node[key], node);
  };
  walk(parseAst(source, { lang: "tsx" }, file), null);
  return found;
}

const allowed = (f: Found) => ALLOWED.some((a) => a.file === f.file && (a.text === "*" || a.text === f.text));

test("rider-visible text in components goes through t(): no plain JSX text or aria-label, title, placeholder, alt", () => {
  const all = sources(SRC).flatMap((path) => untranslated(readFileSync(path, "utf8"), relative(SRC, path).split("\\").join("/")));
  const bad = all.filter((f) => !allowed(f));
  const lines = bad.map((f) => `  src/${f.file}:${f.line} ${f.where === "text" ? "text" : f.where} ${JSON.stringify(f.text)}`);
  assert.equal(
    bad.length,
    0,
    `${bad.length} rider-visible strings are not passed through t(). For each, wrap it in t("...") (places as {name}) and add its ` +
      `Spanish to src/i18n/es.ts, or, if it must stay as written, add it to ALLOWED in src/lib/i18nLint.test.ts with the reason:\n${lines.join("\n")}`,
  );
  // An allowance with nothing left to allow is taken out.
  const stale = ALLOWED.filter((a) => !all.some((f) => f.file === a.file && (a.text === "*" || a.text === f.text)));
  assert.deepEqual(stale, [], "ALLOWED entries that match nothing any more; remove them");
});

test("the lint finds plain text, plain props and plain string children, and leaves t() and symbols alone", () => {
  const sample = [
    "export const A = () => (",
    '  <p title="Plain title" aria-label={t("Marked")} alt={`Photo ${1}`}>',
    "    Plain text {t(\"Marked\")} {\"Plain child\"} {\" \"} · 3 ›",
    "    <input placeholder={`${n}`} />",
    "  </p>",
    ");",
  ].join("\n");
  const found = untranslated(sample, "sample.tsx").map((f) => [f.line, f.where, f.text]);
  assert.deepEqual(found, [
    [2, "title", "Plain title"],
    [2, "alt", "Photo ${…}"],
    [3, "text", "Plain text"],
    [3, "text", "Plain child"],
  ]);
});
