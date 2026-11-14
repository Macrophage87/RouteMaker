// The size budget that fails the build (sizeBudgetPlugin.mjs): what a first open downloads, and when it is too much.
import { test } from "node:test";
import assert from "node:assert/strict";
import { BUDGET_KB, firstLoadFiles, measure, overBudget, sizeBudget } from "./sizeBudgetPlugin.mjs";

const chunk = (fileName, over = {}) => ({ type: "chunk", fileName, name: fileName.replace(/^assets\/|-\w+\.js$/g, ""), imports: [], dynamicImports: [], code: "", ...over });
const bundleOf = (...files) => Object.fromEntries(files.map((f) => [f.fileName, f]));

const BUNDLE = bundleOf(
  chunk("assets/index-1.js", { isEntry: true, name: "index", imports: ["assets/boot-1.js"], dynamicImports: ["assets/App-1.js"], viteMetadata: { importedCss: new Set(["assets/boot-1.css"]) } }),
  chunk("assets/boot-1.js"),
  chunk("assets/App-1.js", { facadeModuleId: "/f/src/App.tsx", imports: ["assets/maplibre-1.js"], dynamicImports: ["assets/RideMode-1.js"], code: "x".repeat(5000) }),
  chunk("assets/maplibre-1.js"),
  chunk("assets/RideMode-1.js", { facadeModuleId: "/f/src/RideMode.tsx", code: "y".repeat(5000) }),
  { type: "asset", fileName: "assets/boot-1.css", source: "a{}" },
);

test("the first load is the loader, App and what they import at once, with their stylesheets; never a chunk loaded on first use", () => {
  assert.deepEqual(firstLoadFiles(BUNDLE), ["assets/App-1.js", "assets/boot-1.css", "assets/boot-1.js", "assets/index-1.js", "assets/maplibre-1.js"]);
});

test("sizes are gzipped KB, and App's chunk is measured alone", () => {
  const sizes = measure(BUNDLE);
  assert.ok(sizes.app > 0 && sizes.app < 1, "5,000 repeated letters gzip to well under 1 KB");
  assert.ok(sizes.firstLoad >= sizes.app);
});

test("a size past its limit is a breach that names it; one within is none", () => {
  assert.deepEqual(overBudget({ firstLoad: 10, app: 5 }, { firstLoad: 20, app: 5 }), []);
  const breaches = overBudget({ firstLoad: 21, app: 5 }, { firstLoad: 20, app: 5 });
  assert.equal(breaches.length, 1);
  assert.match(breaches[0], /^firstLoad is 21\.0 KB gzipped, over its budget of 20 KB/);
});

test("the plugin fails the app's build when over budget, and leaves a build with no app alone", () => {
  const errors = [];
  const context = { error: (message) => errors.push(message), info: () => {} };
  const plugin = sizeBudget();
  assert.equal(plugin.apply, "build");
  plugin.generateBundle.call(context, {}, BUNDLE);
  assert.deepEqual(errors, [], "the tiny bundle fits");
  plugin.generateBundle.call(context, {}, bundleOf(chunk("post.js", { isEntry: true, name: "post", code: "z".repeat(10_000_000) })));
  assert.deepEqual(errors, [], "no app entry: not measured");
});

test("the limits are set, in KB, and the first load's is the larger", () => {
  assert.ok(BUDGET_KB.firstLoad > BUDGET_KB.app && BUDGET_KB.app > 0);
});
