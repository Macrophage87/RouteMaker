import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { licenceNotices } from "./src/licences/notices.mjs";
import { railFixtures } from "./src/lib/railFixturesPlugin.mjs";

// `npm run build` writes dist/, which the deploy step copies to
// <DATA_ROOT>/frontend for Caddy to serve at / (docs/DEPLOYMENT.md, "The
// public front end"). No sourcemaps: PLAN.md keeps the admin path out of the
// bundle and its sourcemaps, and the simplest way to keep that true is to ship
// none.
//
// `npm run dev` is for working on the UI only. The base map is refused to any
// origin but the site's own (Caddyfile, /basemap/*), so the dev server proxies
// /basemap, /api and /tiles to a stack and rewrites Origin and Referer to that
// stack's own. DEV_STACK names it; the default is the local stack on :80.
const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
const stack = (env?.DEV_STACK ?? "http://localhost").replace(/\/$/, "");

const toStack = {
  target: stack,
  changeOrigin: true,
  headers: { Origin: stack, Referer: `${stack}/` },
};

const frontendRoot = new URL(".", import.meta.url).pathname;

export default defineConfig({
  // licenceNotices completes what build.license writes (src/licences/notices.mjs);
  // railFixtures refuses rail fixtures that no longer fit (src/lib/railFixturesPlugin.mjs).
  plugins: [react(), licenceNotices(frontendRoot), railFixtures(`${frontendRoot}src/rail-data`)],
  // MapLibre's worker imports a chunk it shares with the main bundle.
  worker: { format: "es" },
  build: {
    outDir: "dist",
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 2000,
    // The bundled packages' licences, which MIT, ISC and BSD-3-Clause all ask
    // to travel with redistributed copies; served at /licenses.txt and linked
    // from the map's credits. Completed by licenceNotices above: the text for
    // packages that ship none, and the packages inside maplibre-gl's bundle.
    license: { fileName: "licenses.txt" },
  },
  server: { proxy: { "/api": toStack, "/tiles": toStack, "/basemap": toStack } },
});
