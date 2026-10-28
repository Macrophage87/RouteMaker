/**
 * Your routes, in the Save and load sheet (the owner, 2026-10-18: "the files tab (maybe call it save or
 * load) is where we should save the routes and search for them"): one search box over the saved routes
 * (signed in) and the routes kept on this device for offline, which used to sit in Settings.
 */
import { useId, useState } from "react";
import { KeptRoutes } from "./InstallableApp.tsx";
import { MyRoutes, type MyRoutesProps } from "./MyRoutes.tsx";
import type { KeptRoute } from "./lib/offlineRoutes.ts";
import { t } from "./lib/i18n.ts";

export const YOUR_ROUTES = t("Your routes");
export const SEARCH_ROUTES = t("Search your routes");

export function YourRoutes({
  signedIn,
  myRoutes,
  kept,
}: {
  signedIn: boolean;
  myRoutes: MyRoutesProps;
  /** The routes kept for offline: listed when one is kept or keeping is offered. */
  kept: { shown: boolean; version: number; onOpen: (route: KeptRoute) => void; onSay: (text: string) => void };
}) {
  const id = useId();
  const [filter, setFilter] = useState("");
  if (!signedIn && !kept.shown) return null;
  return (
    <section aria-labelledby={`${id}-heading`} className="your-routes">
      <h3 id={`${id}-heading`}>{YOUR_ROUTES}</h3>
      <input type="search" className="route-search" aria-label={SEARCH_ROUTES} placeholder={SEARCH_ROUTES} value={filter} onChange={(event) => setFilter(event.target.value)} />
      {signedIn && <MyRoutes {...myRoutes} filter={filter} />}
      {kept.shown && <KeptRoutes version={kept.version} onOpen={kept.onOpen} onSay={kept.onSay} compact filter={filter} level={4} />}
    </section>
  );
}
