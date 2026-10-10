/**
 * The service worker's build step (WEB-NAV-plan.md section 8: "Vite writes the list of built files,
 * which a small build plugin turns into the precache list with a build id"). Build only: `npm run
 * dev` has no worker (the page registers one only in a production build, lib/appWorker.ts).
 *
 * - index.html gets `<meta name="routemaker-build" content="<id>">`. The id is a hash of the names of
 *   every file the build wrote (each hashed by its content) and of index.html itself, so any change
 *   to what is precached is a new id, and an unchanged build keeps its id (and its cache).
 * - dist/sw.js is swCore.mjs, made a plain script, with the id and the list of /assets/* appended.
 * - dist/sw-kill.js is swKill.mjs the same way (docs/OPERATIONS.md, the kill switch).
 *
 * No bundler: the two sources import nothing but each other (swPlugin.test.mjs holds that true),
 * so a plain script is the files themselves with their `import` lines and `export` words removed.
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const here = new URL(".", import.meta.url);

/** A worker source with its module syntax removed (imports of the other worker file only). */
export function plainScript(source) {
  return source
    .split("\n")
    .filter((line) => !/^import\s.+from\s+"\.\/sw(Core|Kill)\.mjs";\s*$/.test(line))
    .map((line) => line.replace(/^export\s+(?=(async\s+)?function|const)/, ""))
    .join("\n");
}

function read(name) {
  return readFileSync(new URL(name, here), "utf8");
}

/** dist/sw.js for a build. */
export function workerSource(buildId, assets) {
  return [
    `// RouteMaker's service worker, build ${buildId}. Written by frontend/src/sw/swPlugin.mjs from swCore.mjs: edit that.`,
    plainScript(read("swCore.mjs")),
    `installWorker(self, { buildId: ${JSON.stringify(buildId)}, assets: ${JSON.stringify(assets)} });`,
    "",
  ].join("\n");
}

/** dist/sw-kill.js. */
export function killSource() {
  return [
    "// RouteMaker's service worker kill switch. Written by frontend/src/sw/swPlugin.mjs from swKill.mjs: edit that.",
    "// docs/OPERATIONS.md says when to copy it over sw.js.",
    plainScript(read("swCore.mjs")),
    plainScript(read("swKill.mjs")),
    "installKillSwitch(self);",
    "",
  ].join("\n");
}

/** The build's id from the names of the files it wrote and index.html as written. */
export function buildIdFor(fileNames, html) {
  const hash = createHash("sha256");
  for (const name of [...fileNames].filter((n) => n !== "index.html").sort()) hash.update(`${name}\n`);
  hash.update(html);
  return hash.digest("hex").slice(0, 16);
}

/** The precache list: every file the build wrote under assets/, as the page asks for it. */
export function precacheList(fileNames) {
  return [...fileNames].filter((name) => name.startsWith("assets/")).sort().map((name) => `/${name}`);
}

export function appWorker() {
  return {
    name: "routemaker-app-worker",
    apply: "build",
    enforce: "post",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        const id = buildIdFor(Object.keys(ctx.bundle ?? {}), html);
        return [{ tag: "meta", attrs: { name: "routemaker-build", content: id }, injectTo: "head" }];
      },
    },
    generateBundle(_options, bundle) {
      const page = bundle["index.html"];
      const html = page && page.type === "asset" ? String(page.source) : "";
      const id = /<meta name="routemaker-build" content="([0-9a-f]{16})"/.exec(html)?.[1];
      if (!id) this.error("index.html has no routemaker-build id: the service worker cannot be written");
      const names = Object.keys(bundle);
      this.emitFile({ type: "asset", fileName: "sw.js", source: workerSource(id, precacheList(names)) });
      this.emitFile({ type: "asset", fileName: "sw-kill.js", source: killSource() });
    },
  };
}
