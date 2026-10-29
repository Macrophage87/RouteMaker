/**
 * Ends the start-up waterfall (the 2026-10-29 review, frontend 10 and 15): main.tsx imports App only once the
 * language's catalog is in (labels are worded as their modules load), and a browser fetches a dynamic import's
 * files only when the import runs. So the app's largest files started downloading only after index.html, then the
 * loader, then the catalog. This names App's chunk, and every chunk it imports statically, as a
 * <link rel="modulepreload"> in index.html: they download and parse while the catalog arrives, and still run only
 * when main.tsx imports them, in the same order as before.
 */

/** The bundle's file names App's chunk needs at once, itself first; none already preloaded by the entry, `entry`. */
export function appPreloads(bundle, appModule = /\/src\/App\.tsx$/, entry = "index") {
  const chunks = Object.values(bundle).filter((file) => file.type === "chunk");
  const app = chunks.find((chunk) => appModule.test(chunk.facadeModuleId ?? ""));
  if (!app) return [];
  const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
  const already = new Set();
  const start = chunks.find((chunk) => chunk.isEntry && chunk.name === entry);
  const markAlready = (chunk) => {
    for (const name of chunk.imports ?? []) {
      if (already.has(name)) continue;
      already.add(name);
      const next = byName.get(name);
      if (next) markAlready(next);
    }
  };
  if (start) {
    already.add(start.fileName);
    markAlready(start);
  }
  const wanted = [];
  const walk = (chunk) => {
    if (wanted.includes(chunk.fileName) || already.has(chunk.fileName)) return;
    wanted.push(chunk.fileName);
    for (const name of chunk.imports ?? []) {
      const next = byName.get(name);
      if (next) walk(next);
    }
  };
  walk(app);
  return wanted;
}

/**
 * The vendor chunks (vite.config.ts codeSplitting: `names`) that import app code, directly or through another chunk:
 * their names would then change with every app release, and a returning rider would download them again. The
 * bundler's own helpers land in whichever chunk holds the modules the same pages share, so a new module shared by the
 * loader, App and the post page can pull them back into app code.
 */
export function vendorLeaks(bundle, names = ["maplibre", "react"]) {
  const chunks = Object.values(bundle).filter((file) => file.type === "chunk");
  const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
  const appCode = (chunk) => (chunk.moduleIds ?? []).some((id) => !id.startsWith("\0") && !/[\\/]node_modules[\\/]/.test(id));
  const leaks = (chunk, seen) =>
    (chunk.imports ?? []).some((name) => {
      if (seen.has(name)) return false;
      seen.add(name);
      const next = byName.get(name);
      return next !== undefined && (appCode(next) || leaks(next, seen));
    });
  return chunks.filter((chunk) => names.includes(chunk.name) && (appCode(chunk) || leaks(chunk, new Set()))).map((chunk) => chunk.fileName);
}

/** The Vite plugin: index.html's modulepreload links for App's chunks (build only; the dev server has none). */
export function appPreload() {
  return {
    name: "app-preload",
    apply: "build",
    generateBundle(_options, bundle) {
      for (const file of vendorLeaks(bundle)) this.warn(`${file} imports app code, so its name will change with every release (vite.config.ts codeSplitting)`);
    },
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        if (!ctx.bundle) return [];
        return appPreloads(ctx.bundle).map((file) => ({
          tag: "link",
          attrs: { rel: "modulepreload", crossorigin: true, href: `/${file}` },
          injectTo: "head",
        }));
      },
    },
  };
}
