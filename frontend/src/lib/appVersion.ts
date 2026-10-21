/**
 * The app's version where riders see it (Stephen 2026-10-21: "in the route maker title, put the version number
 * so people know that it's updated"): next to Plan's heading, in the tab's title and in the map's Help panel.
 * It is frontend/package.json's version, put in at build time (vite.config.ts), so a release that bumps the
 * version (docs/BETA-RUNBOOK.md: pyproject.toml, routemaker.__version__ and package.json, which
 * tests/test_deploy_docs.py keeps in step) changes what riders see, with nothing else to edit. Empty outside a
 * Vite build (the unit tests), where nothing shows.
 */
export const APP_VERSION: string = import.meta.env?.VITE_APP_VERSION ?? "";

/** What a screen reader hears for it, and the Help panel's line: "RouteMaker version 0.10.1". */
export function versionSaid(version: string = APP_VERSION): string {
  return version ? `RouteMaker version ${version}` : "";
}

/** The tab's title: "RouteMaker 0.10.1" (just "RouteMaker" with no version). */
export function tabTitle(version: string): string {
  return version ? `RouteMaker ${version}` : "RouteMaker";
}
