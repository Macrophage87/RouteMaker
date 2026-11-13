/**
 * Node module hooks that let `node --test` import the interface's own .tsx files, so a test can render a component
 * and check what the rider sees (render.ts) instead of reading its source as text. Registered by register.mjs, which
 * `npm test` loads with --import.
 *
 * - .tsx: compiled with the transform Vite itself uses (vite's transformWithOxc, React's automatic JSX runtime).
 *   Plain .ts keeps Node's own type stripping, as before.
 * - import.meta.env: Vite fills it at build time; under Node it is a test build's (DEV, MODE "test", no beta).
 * - Stylesheets, fonts and images: an empty module (a component's `import "./x.css"` has no behaviour to test).
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { transformWithOxc } from "vite";

const ASSET = /\.(css|woff2?|ttf|png|jpe?g|svg|webp|gif)(\?.*)?$/;

/** import.meta.env as a test sees it. */
const TEST_ENV = '({ DEV: true, PROD: false, MODE: "test", BASE_URL: "/", VITE_APP_VERSION: "test" })';

export async function load(url, context, nextLoad) {
  if (ASSET.test(url) && url.startsWith("file:")) return { format: "module", source: "export default '';", shortCircuit: true };
  if (!url.startsWith("file:") || !/\.tsx(\?.*)?$/.test(url)) return nextLoad(url, context);
  const path = fileURLToPath(url);
  const text = (await readFile(path, "utf8")).replaceAll("import.meta.env", TEST_ENV);
  const out = await transformWithOxc(text, path, { lang: "tsx", jsx: { runtime: "automatic" } });
  return { format: "module", source: out.code, shortCircuit: true };
}
