// A build of the app for scripts/perf/rideProfile.mjs: production React with its profiling timers on, and names
// kept (no minifying), so the profile names each component and its time as a rider's phone would run it.
//
//   (in frontend/) node node_modules/vite/bin/vite.js build --config scripts/vite.profile.mjs
//   node node_modules/vite/bin/vite.js preview --config scripts/vite.profile.mjs --port 4174
import { mergeConfig } from "vite";
import base from "../vite.config.ts";

const frontend = new URL("../", import.meta.url).pathname;
export default mergeConfig(
  // The size budget is for the shipped build; this one is larger on purpose.
  { ...base, plugins: base.plugins.filter((p) => p?.name !== "size-budget") },
  {
    root: frontend,
    resolve: { alias: [{ find: /^react-dom\/client$/, replacement: "react-dom/profiling" }] },
    build: { outDir: `${frontend}dist-profile`, minify: false },
  },
);
