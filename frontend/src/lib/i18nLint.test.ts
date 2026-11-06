/**
 * Text a rider sees that is not passed through t() (the 2026-10-28 audit, P9): lib/i18n.test.ts checks the phrases
 * the code marks, so a plain JSX text child or a plain aria-label slipped past it and showed English on a Spanish
 * page. This reads every component file (src/**\/*.tsx) with the parser Vite already uses and fails on
 *   - JSX text with a letter in it: <p>Saved</p>
 *   - a string with a letter as a JSX child: <p>{"Saved"}</p>, <p>{`Saved ${n}`}</p>
 *   - a string with a letter in aria-label, title, placeholder or alt: aria-label="Close", title={`Map ${n}`}
 *   - a string with a letter passed to announce, setNotice, say and the like (SAYERS): announce(`Opening ${name}.`)
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
 * The calls whose first argument is said or shown to the rider (the 2026-10-29 review: a sentence passed straight to
 * announce() or setNotice() was English on a Spanish page): a plain string there, or in either branch of a `?:`, is
 * reported as "said".
 */
const SAYERS = new Set(["announce", "announceExtra", "setNotice", "setNoticeSaying", "say", "sayDetour", "showToast", "answer", "tell", "notify"]);

/**
 * Go and Ride's components, where a constant passed by name is read too (the 2026-11-04 review: "Ride ended" shown as
 * {RIDE_SUMMARY_TITLE} and "Still riding." said as announce(STILL_RIDING_SAID) were English in every language): a
 * NAME shown, put in one of PROPS or passed to a SAYER must be a constant worded through t(), not a plain string.
 */
const BY_NAME = new Set([
  "App.tsx",
  "app/Go.tsx",
  "app/Sheets.tsx",
  "app/RoutePanel.tsx",
  "RideMode.tsx",
  "RideGroup.tsx",
  "RoamMode.tsx",
  "RideSummaryCard.tsx",
  "DepartureTimer.tsx",
  "StartOnComputerDialog.tsx",
  "PlaceSearch.tsx",
  "WeatherLines.tsx",
  "OnBoardCard.tsx",
  "TransitSummary.tsx",
]);

/**
 * What may stay as written, by file (relative to src/) and its text, with why. A whole file is "*". An entry that
 * no longer matches anything fails the test too, so the list stays short.
 */
const ALLOWED: readonly { file: string; text: string; why: string }[] = [
  { file: "ReviewMode.tsx", text: "*", why: "the reviewers' screen (signed-in reviewers only), English as the review tools are" },
  { file: "ClosureReview.tsx", text: "*", why: "the reviewers' closure list (signed-in reviewers only), English as the review tools are" },
  { file: "App.tsx", text: "v", why: "the version's prefix, v0.15.1" },
  { file: "App.tsx", text: "RouteMaker", why: "the app's name (PLANNER_TITLE)" },
  { file: "AheadGraph.tsx", text: "LTS", why: "the stress ribbon's gutter label: LTS is the same in every language (lib/aheadGraph.ts levelWords)" },
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

/** Every module (.ts and .tsx, not tests nor the catalogs), for the constants a component may show by name. */
function modules(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "i18n" ? [] : modules(path);
    return /\.tsx?$/.test(name) && !name.includes(".test.") ? [path] : [];
  });
}

/**
 * The constants written as a plain string or template (`const NAME = "..."`), by name and file, and the files that
 * define each name at all: `t("...")` and anything else is not plain.
 */
function constantsIn(files: readonly { file: string; source: string }[]): { plain: Map<string, Map<string, string>>; defined: Map<string, Set<string>> } {
  const plain = new Map<string, Map<string, string>>();
  const defined = new Map<string, Set<string>>();
  for (const { file, source } of files) {
    for (const m of source.matchAll(/(?:^|\n)\s*(?:export )?const ([A-Z][A-Z0-9_]*)\b(?:: [^=\n]+)? =/g)) {
      if (!defined.has(m[1])) defined.set(m[1], new Set());
      defined.get(m[1])!.add(file);
    }
    for (const m of source.matchAll(/(?:^|\n)\s*(?:export )?const ([A-Z][A-Z0-9_]*)\b(?:: [^=\n]+)? =\s*(["'`])((?:(?!\2)[^\\]|\\[^])*)\2\s*;/g)) {
      if (!plain.has(m[1])) plain.set(m[1], new Map());
      plain.get(m[1])!.set(file, m[2] === "`" ? m[3].replace(/\$\{[^}]*\}/g, "${…}") : m[3]);
    }
  }
  return { plain, defined };
}

/**
 * A resolver for one file: a NAME's plain text where it names a plain constant (this file's own, else the one
 * every file that defines it agrees is plain), null otherwise.
 */
function plainConstants(consts: ReturnType<typeof constantsIn>, file: string): (name: string) => string | null {
  return (name) => {
    const texts = consts.plain.get(name);
    if (!texts) return null;
    const own = texts.get(file);
    if (own !== undefined) return own;
    if (consts.defined.get(name)?.has(file)) return null;
    const where = [...(consts.defined.get(name) ?? [])];
    return where.length > 0 && where.every((f) => texts.has(f)) ? texts.get(where[0])! : null;
  };
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

/** A call's function name: announce(...) and announcer.current?.say(...) alike. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function calleeName(callee: any): string | null {
  if (callee?.type === "Identifier") return callee.name;
  if (callee?.type === "MemberExpression" && callee.property?.type === "Identifier") return callee.property.name;
  return null;
}

/**
 * An argument's possible values: each branch of a `?:` (nested too), both sides of `||` and `??` (`a || "Home"` shows
 * "Home"), the right of `&&`, else the argument itself.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function branchesOf(node: any): any[] {
  if (!node) return [];
  if (node.type === "ConditionalExpression") return [...branchesOf(node.consequent), ...branchesOf(node.alternate)];
  if (node.type === "LogicalExpression") return node.operator === "&&" ? branchesOf(node.right) : [...branchesOf(node.left), ...branchesOf(node.right)];
  if (node.type === "ParenthesizedExpression") return branchesOf(node.expression);
  return [node];
}

/** A shown value and, where it is `a || "…"`, `a ?? "…"` or `a && "…"`, the words it falls back to (nested too). */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function fallbacksOf(node: any): any[] {
  if (node?.type !== "LogicalExpression") return node ? [node] : [];
  return node.operator === "&&" ? fallbacksOf(node.right) : [...fallbacksOf(node.left), ...fallbacksOf(node.right)];
}

/**
 * What one component file shows untranslated; `file` is its name in the report. With `named`, a constant shown or said
 * by its NAME counts as its text (BY_NAME).
 */
function untranslated(source: string, file: string, named: ((name: string) => string | null) | null = null): Found[] {
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
  // A plain constant shown or said by its NAME, in either branch of a `?:` (BY_NAME).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const byName = (node: any, where: string) => {
    if (!named) return;
    for (const branch of branchesOf(node)) {
      const text = branch?.type === "Identifier" ? named(branch.name) : null;
      if (text !== null) add(branch.start, text, `${where} ${branch.name}`);
    }
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
      for (const branch of fallbacksOf(node.expression)) {
        const text = stringOf(branch);
        if (text !== null) add(branch.start, text, "text");
      }
      byName(node.expression, "text");
    } else if (node.type === "JSXAttribute" && node.name?.type === "JSXIdentifier" && PROPS.has(node.name.name)) {
      const value = node.value?.type === "JSXExpressionContainer" ? node.value.expression : node.value;
      for (const branch of fallbacksOf(value)) {
        const text = stringOf(branch);
        if (text !== null) add(branch === value ? node.start : branch.start, text, node.name.name);
      }
      byName(value, node.name.name);
    } else if (node.type === "CallExpression" && SAYERS.has(calleeName(node.callee) ?? "")) {
      for (const branch of branchesOf(node.arguments?.[0])) {
        const text = stringOf(branch);
        if (text !== null) add(branch.start, text, "said");
      }
      byName(node.arguments?.[0], "said");
    }
    for (const key of Object.keys(node)) if (key !== "start" && key !== "end") walk(node[key], node);
  };
  walk(parseAst(source, { lang: "tsx" }, file), null);
  return found;
}

const allowed = (f: Found) => ALLOWED.some((a) => a.file === f.file && (a.text === "*" || a.text === f.text));

test("rider-visible text in components goes through t(): no plain JSX text or aria-label, title, placeholder, alt", () => {
  const nameOf = (path: string) => relative(SRC, path).split("\\").join("/");
  const consts = constantsIn(modules(SRC).map((path) => ({ file: nameOf(path), source: readFileSync(path, "utf8") })));
  const components = sources(SRC);
  assert.deepEqual([...BY_NAME].filter((file) => !components.some((path) => nameOf(path) === file)), [], "BY_NAME lists components that are gone");
  const all = components.flatMap((path) => untranslated(readFileSync(path, "utf8"), nameOf(path), BY_NAME.has(nameOf(path)) ? plainConstants(consts, nameOf(path)) : null));
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

test("the lint finds plain text, plain props, plain string children and plain said sentences, and leaves t() and symbols alone", () => {
  const sample = [
    "export const A = () => (",
    '  <p title="Plain title" aria-label={t("Marked")} alt={`Photo ${1}`}>',
    "    Plain text {t(\"Marked\")} {\"Plain child\"} {\" \"} · 3 ›",
    "    <input placeholder={`${n}`} />",
    "  </p>",
    ");",
    "announce(ok ? t(\"Marked\") : `Plain said ${n}`);",
    "ride.current?.say(\"Plain member said\", true);",
    "setNotice(LINE);",
    'const B = () => <p title={name ?? "Plain fallback title"}>{fix || "Plain fallback"} {shown && "Plain when"} {fix || t("Marked")}</p>;',
  ].join("\n");
  const found = untranslated(sample, "sample.tsx").map((f) => [f.line, f.where, f.text]);
  assert.deepEqual(found, [
    [2, "title", "Plain title"],
    [2, "alt", "Photo ${…}"],
    [3, "text", "Plain text"],
    [3, "text", "Plain child"],
    [7, "said", "Plain said ${…}"],
    [8, "said", "Plain member said"],
    [10, "title", "Plain fallback title"],
    [10, "text", "Plain fallback"],
    [10, "text", "Plain when"],
  ]);
});

test("in Go and Ride a constant shown or said by its name must be worded through t(), wherever it is defined", () => {
  const consts = constantsIn([
    { file: "lib/words.ts", source: 'export const TITLE = "Ride ended";\nexport const DONE = t("Done");\nexport const TOO_LONG =\n  `Up to ${MAX} only.`;\nexport const MARK = "·";' },
    { file: "lib/other.ts", source: 'export const DONE = "Done";' },
    {
      file: "sample.tsx",
      source: 'const NOTICE = "Outside the map.";\nconst TRANSLATED = t("Inside");',
    },
  ]);
  const sample = [
    'const NOTICE = "Outside the map.";',
    'const TRANSLATED = t("Inside");',
    "export const A = () => (",
    "  <h2 aria-label={TITLE}>{TITLE} {DONE} {MARK} {TRANSLATED}</h2>",
    ");",
    "setNotice(NOTICE);",
    "ride.current?.answer(ok ? TOO_LONG : TRANSLATED);",
    "tell(UNKNOWN);",
  ].join("\n");
  const found = untranslated(sample, "sample.tsx", plainConstants(consts, "sample.tsx")).map((f) => [f.line, f.where, f.text]);
  assert.deepEqual(found, [
    [4, "aria-label TITLE", "Ride ended"],
    [4, "text TITLE", "Ride ended"],
    [6, "said NOTICE", "Outside the map."],
    [7, "said TOO_LONG", "Up to ${…} only."],
  ]);
  // Outside Go and Ride (no resolver) a name is not read.
  assert.deepEqual(untranslated(sample, "sample.tsx"), []);
});

test("Go and Ride's words that stand in for a missing name are translated too: Home, the point on the map, a closure (2026-11-05 review)", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /home\.label \|\| t\("Home"\)/);
  assert.doesNotMatch(app, /home\.label \|\| "Home"/);
  assert.match(app, /\?\? t\("the point on the map"\)/);
  assert.match(app, /c\.road \?\? c\.title \?\? t\("a closure"\)/);
});
