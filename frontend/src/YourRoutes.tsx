/**
 * My routes, its own popup opened from the Save & load sheet (Stephen, 2026-11-12: "Put the load rides in a popout
 * and have save load be mostly about saving and exporting"), named by the popup's title (sheet-routes): one search box over the saved routes
 * (signed in) and the routes kept on this device for offline, which used to sit in Settings. Named My routes, as
 * everywhere (P12: it was "Your routes"); the saved ones under it are those on the account.
 */
import { useState } from "react";
import { KeptRoutes } from "./InstallableApp.tsx";
import { MyRoutes, type MyRoutesProps } from "./MyRoutes.tsx";
import type { KeptRoute } from "./lib/offlineRoutes.ts";
import { t } from "./lib/i18n.ts";

/** The popup's title (Sidebar.tsx SheetFrame: `${id}-title`), "My routes": one heading, not two. */
const LABELLED_BY = "sheet-routes-title";

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
  const [filter, setFilter] = useState("");
  if (!signedIn && !kept.shown) return null;
  return (
    <section aria-labelledby={LABELLED_BY} className="your-routes">
      <input type="search" className="route-search" aria-label={SEARCH_ROUTES} placeholder={SEARCH_ROUTES} value={filter} onChange={(event) => setFilter(event.target.value)} />
      {signedIn && <MyRoutes {...myRoutes} filter={filter} />}
      {kept.shown && <KeptRoutes version={kept.version} onOpen={kept.onOpen} onSay={kept.onSay} compact filter={filter} level={3} />}
    </section>
  );
}
