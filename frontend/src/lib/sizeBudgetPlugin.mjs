/**
 * A size budget that fails the build (backlog 2026-11-12, performance 4): the app chunk passed its own 1,200 KB
 * warning without anyone seeing it, because a warning stops nothing. This adds up what a phone downloads before Go
 * shows (the loader, App's chunk and every chunk either imports at once, and their stylesheets), gzipped as the
 * server sends them, and fails `npm run build` when that or the app chunk grows past its limit.
 *
 * Not counted: the language's catalog (English needs none; another language's is one lang-* file) the fonts'
 * files (a stylesheet asks for one only when text uses it), and data files fetched later (food, climbs).
 *
 * The limits are our default, set from the build measured when they were added (2026-11-13: 953 KB and 351 KB after Roam, the review tools, the share card and a ride's riders moved to first use) with a little headroom; lower them
 * when a change makes the first load smaller, raise them only on purpose, in the same PR as the change that needs it.
 */
import { gzipSync } from "node:zlib";
import { appPreloads } from "./appPreloadPlugin.mjs";

/** The limits, in KB (1,000 bytes) gzipped. Our default (2026-11-13), see the comment above. */
export const BUDGET_KB = {
  // The loader, React, MapLibre, App and what App imports at once, with their stylesheets.
  // 930 since v0.28.0: Ride mode moved to first use (39 KB less); with v0.28.0's other changes (Plan's chart tools among
  // them) the first load measured 923 KB. 935 since v0.30.0: the Ride settings popup in Go, the Surface picker and the
  // rider's own ride types (#1384, #1386, #1385) brought it to 930.1 KB. 940 since v0.30.1: the junction dots on the map,
  // the list, the chart and the ribbon (#1291) with #1401's accessibility fixes brought it to 935.8 KB.
  // 947 since v0.31.0: survey spots, Southwest Florida area, beach path (944.9 KB).
  firstLoad: 947,
  // App's own chunk. 329 since v0.28.0: 323 KB measured with Ride mode on first use (it was 356 before); 362 in v0.27.1.
  // 332 since v0.30.0: the intuitiveness review's Plan changes (#1398) on top of Ride settings, Surface and own ride
  // types brought it to 329.7 KB. 335 since v0.30.3: Go's route card at a tapped spot (#1420) brought it to 332.7 KB.
  // 341 since v0.31.0: survey spots, Southwest Florida area, beach path (338.5 KB).
  app: 341,
};

/** The chunks and stylesheets a first open downloads: the entry, what it imports at once, and App's (appPreloads). */
export function firstLoadFiles(bundle, entry = "index") {
  const chunks = Object.values(bundle).filter((file) => file.type === "chunk");
  const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
  const start = chunks.find((chunk) => chunk.isEntry && chunk.name === entry);
  const files = new Set();
  const walk = (chunk) => {
    if (!chunk || files.has(chunk.fileName)) return;
    files.add(chunk.fileName);
    for (const css of chunk.viteMetadata?.importedCss ?? []) files.add(css);
    for (const name of chunk.imports ?? []) walk(byName.get(name));
  };
  walk(start);
  for (const name of appPreloads(bundle)) walk(byName.get(name));
  return [...files].sort();
}

const gzipKb = (source) => gzipSync(typeof source === "string" ? Buffer.from(source) : source).length / 1000;

/** What the budget measures, in KB gzipped: the first load, App's chunk, and the first load's files. */
export function measure(bundle, appModule = /\/src\/App\.tsx$/) {
  const sizeOf = (fileName) => {
    const file = bundle[fileName];
    if (!file) return 0;
    return gzipKb(file.type === "chunk" ? file.code : file.source);
  };
  const files = firstLoadFiles(bundle);
  const app = Object.values(bundle).find((file) => file.type === "chunk" && appModule.test(file.facadeModuleId ?? ""));
  return {
    firstLoad: files.reduce((sum, name) => sum + sizeOf(name), 0),
    app: app ? sizeOf(app.fileName) : 0,
    files,
  };
}

/** The budget's breaches, as sentences; none when everything fits. */
export function overBudget(sizes, budget = BUDGET_KB) {
  return Object.entries(budget)
    .filter(([key, limit]) => sizes[key] > limit)
    .map(([key, limit]) => `${key} is ${sizes[key].toFixed(1)} KB gzipped, over its budget of ${limit} KB (src/lib/sizeBudgetPlugin.mjs)`);
}

/** The Vite plugin: measures the build and fails it when over budget (build only). */
export function sizeBudget() {
  return {
    name: "size-budget",
    apply: "build",
    generateBundle(_options, bundle) {
      // The post page's build has no App; only the app's own build is budgeted.
      if (!Object.values(bundle).some((file) => file.type === "chunk" && file.isEntry && file.name === "index")) return;
      const sizes = measure(bundle);
      this.info?.(`first load ${sizes.firstLoad.toFixed(1)} KB gzipped (budget ${BUDGET_KB.firstLoad}), App ${sizes.app.toFixed(1)} KB (budget ${BUDGET_KB.app})`);
      const breaches = overBudget(sizes);
      if (breaches.length > 0) this.error(breaches.join("; "));
    },
  };
}
