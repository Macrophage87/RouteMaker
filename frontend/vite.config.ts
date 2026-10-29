import { defineConfig } from "vite";
import pkg from "./package.json" with { type: "json" };
import react from "@vitejs/plugin-react";
import { licenceNotices } from "./src/licences/notices.mjs";
import { railFixtures } from "./src/lib/railFixturesPlugin.mjs";
import { appWorker } from "./src/sw/swPlugin.mjs";

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

// The app's version, shown by Plan's heading, in the tab's title and in Help (src/lib/appVersion.ts).
const appVersion: string = pkg.version;

export default defineConfig({
  // licenceNotices completes what build.license writes (src/licences/notices.mjs);
  // railFixtures refuses rail fixtures that no longer fit (src/lib/railFixturesPlugin.mjs); appWorker
  // writes the installable app's service worker, sw.js and its kill switch sw-kill.js (src/sw/swPlugin.mjs).
  plugins: [
    react(),
    licenceNotices(frontendRoot),
    railFixtures(`${frontendRoot}src/rail-data`),
    appWorker(),
    { name: "app-version-title", transformIndexHtml: (html) => html.replace("<title>RouteMaker</title>", `<title>RouteMaker ${appVersion}</title>`) },
  ],
  define: { "import.meta.env.VITE_APP_VERSION": JSON.stringify(appVersion) },
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
    rollupOptions: {
      // The app, and a Featured routes post's script (src/post/; core/route_posts.py), which the server's page names
      // as /post.js: a fixed name, revalidated on every load (Caddyfile @frontend), since the page cannot know a hash.
      input: { index: `${frontendRoot}index.html`, post: `${frontendRoot}src/post/main.ts` },
      // A language's catalog (src/i18n/<code>.ts, loaded by lib/i18n.ts on choosing it) is named lang-*, which the
      // service worker leaves out of the precache (swCore.mjs LAZY_ASSET): an install does not download all 19.
      output: {
        entryFileNames: (chunk) => (chunk.name === "post" ? "post.js" : "assets/[name]-[hash].js"),
        chunkFileNames: (chunk) => (/\/src\/i18n\/[a-z]+\.ts$/.test(chunk.facadeModuleId ?? "") ? "assets/lang-[name]-[hash].js" : "assets/[name]-[hash].js"),
      },
    },
  },
  server: { proxy: { "/api": toStack, "/tiles": toStack, "/basemap": toStack } },
});
