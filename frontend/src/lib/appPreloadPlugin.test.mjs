// The start-up download (the 2026-10-29 review, frontend 10 and 15): App's chunks preloaded while the language loads,
// and MapLibre and React in chunks with no app code, so their names last across releases.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { appPreloads, vendorLeaks } from "./appPreloadPlugin.mjs";

const chunk = (fileName, over = {}) => ({ type: "chunk", fileName, name: fileName.replace(/^assets\/|-\w+\.js$/g, ""), imports: [], moduleIds: [], ...over });
const bundleOf = (...chunks) => Object.fromEntries(chunks.map((c) => [c.fileName, c]));

const BUNDLE = bundleOf(
  chunk("assets/index-1.js", { isEntry: true, name: "index", imports: ["assets/boot-1.js", "assets/react-1.js"], moduleIds: ["/f/src/main.tsx"] }),
  chunk("assets/boot-1.js", { imports: ["assets/runtime-1.js"], moduleIds: ["/f/src/lib/i18n.ts"] }),
  chunk("assets/runtime-1.js", { moduleIds: ["\0rolldown/runtime.js"] }),
  chunk("assets/react-1.js", { name: "react", imports: ["assets/runtime-1.js"], moduleIds: ["/f/node_modules/react/index.js"] }),
  chunk("assets/maplibre-1.js", { name: "maplibre", imports: ["assets/runtime-1.js"], moduleIds: ["/f/node_modules/maplibre-gl/dist/maplibre-gl.js"] }),
  chunk("assets/App-1.js", { facadeModuleId: "/f/src/App.tsx", imports: ["assets/boot-1.js", "assets/maplibre-1.js", "assets/summary-1.js"], moduleIds: ["/f/src/App.tsx"] }),
  chunk("assets/summary-1.js", { imports: ["assets/react-1.js"], moduleIds: ["/f/src/lib/summary.ts"] }),
  chunk("assets/lang-fr-1.js", { facadeModuleId: "/f/src/i18n/fr.ts", moduleIds: ["/f/src/i18n/fr.ts"] }),
  { type: "asset", fileName: "assets/App-1.css" },
);

test("index.html preloads App and what it imports at once, not what the loader already has, nor a language", () => {
  assert.deepEqual(appPreloads(BUNDLE), ["assets/App-1.js", "assets/maplibre-1.js", "assets/summary-1.js"]);
  assert.deepEqual(appPreloads(bundleOf(chunk("assets/index-1.js", { isEntry: true, name: "index" }))), [], "no App: nothing");
});

test("a vendor chunk that imports app code, itself or through another chunk, is named", () => {
  assert.deepEqual(vendorLeaks(BUNDLE), []);
  const leaky = { ...BUNDLE, "assets/runtime-1.js": chunk("assets/runtime-1.js", { moduleIds: ["\0rolldown/runtime.js", "/f/src/lib/i18n.ts"] }) };
  assert.deepEqual(vendorLeaks(leaky), ["assets/react-1.js", "assets/maplibre-1.js"]);
});

test("the build splits MapLibre and React out, keeps the loader's shared modules apart, and runs the preload", () => {
  const config = readFileSync(new URL("../../vite.config.ts", import.meta.url), "utf8");
  assert.match(config, /\{ name: "maplibre", test: /);
  assert.match(config, /\{ name: "react", test: /);
  assert.match(config, /\{ name: "boot", test: /);
  assert.match(config, /plugins: \[[\s\S]*appPreload\(\),[\s\S]*\]/);
  assert.doesNotMatch(config, /chunkSizeWarningLimit: 2000/);
  // The loader still imports App only once the catalog is in: the preload fetches, it does not run.
  const main = readFileSync(new URL("../main.tsx", import.meta.url), "utf8");
  assert.match(main, /void loadLanguage\(\)\s*\.then\(\(\) => Promise\.all\(\[import\("\.\/App\.tsx"\)/);
});
