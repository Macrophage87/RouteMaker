/**
 * My routes (v0.7.0 plan, item 3): a signed-in rider's saved routes, in Plan's Settings and Go's Menu. Each row
 * opens the route as it was saved, renames it, exports it as GPX, or deletes it (after a second press). The
 * list is read when the section is shown and again after each change. In Plan a row also lists the route's
 * versions (Versions, like Rename, opens under the row) and restores one as the latest, which opens it.
 */
import { useEffect, useId, useState } from "react";
import { Icon } from "./Icon.tsx";
import {
  MAX_SAVED,
  MY_ROUTES,
  NAME_MAX,
  NONE_SAVED,
  RESTORED_SAID,
  RESTORE_FAILED,
  countLine,
  deleteRoute,
  listRoutes,
  listVersions,
  readRoute,
  renameRoute,
  restoreVersion,
  rowDetails,
  versionDetails,
  type SavedRoute,
  type SavedSummary,
  type SavedVersion,
} from "./lib/savedRoutes.ts";

export interface MyRoutesProps {
  /** Bumped by the page after a save, so the list is read again. */
  version: number;
  /** Opens a route; `said` is the line to announce in place of "Opened ...". */
  onOpen: (route: SavedRoute, said?: string) => void;
  onExport: (route: SavedRoute) => void;
  announce: (text: string) => void;
  /** Plan only: each row lists its versions and restores one. Go's Menu is unchanged. */
  versions?: boolean;
}

export function MyRoutes({ version, onOpen, onExport, announce, versions = false }: MyRoutesProps) {
  const headingId = useId();
  const [routes, setRoutes] = useState<SavedSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [renaming, setRenaming] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  // The row whose versions are shown, and them (null while read, or when they could not be).
  const [showing, setShowing] = useState<{ id: number; list: SavedVersion[] | null; failed: boolean } | null>(null);
  const showVersions = (id: number) => {
    if (showing?.id === id) {
      setShowing(null);
      return;
    }
    setShowing({ id, list: null, failed: false });
    void listVersions(window.location.origin, id).then((list) =>
      setShowing((now) => (now?.id === id ? { id, list, failed: list === null } : now)),
    );
  };
  const restore = (r: SavedSummary, v: SavedVersion) => {
    if (v.id === null) return;
    void restoreVersion(window.location.origin, r.id, v.id).then((route) => {
      if (!route) {
        announce(RESTORE_FAILED);
        return;
      }
      setShowing(null);
      setReload((n) => n + 1);
      onOpen(route, RESTORED_SAID(r.name, v));
    });
  };

  useEffect(() => {
    let live = true;
    void listRoutes(window.location.origin).then((found) => {
      if (!live) return;
      setFailed(found === null);
      setRoutes(found ?? []);
    });
    return () => {
      live = false;
    };
  }, [version, reload]);

  const full = async (id: number): Promise<SavedRoute | null> => {
    const route = await readRoute(window.location.origin, id);
    if (!route) announce("That route could not be read; try again shortly.");
    return route;
  };

  return (
    <section aria-labelledby={headingId} className="my-routes">
      <h4 id={headingId}>{MY_ROUTES}</h4>
      {failed && <p className="notice">Your saved routes could not be read; try again shortly.</p>}
      {routes && routes.length === 0 && !failed && <p className="hint">{NONE_SAVED}</p>}
      {routes && routes.length > 0 && (
        <>
          <p className="hint">{countLine(routes.length, MAX_SAVED)}</p>
          <ul role="list" className="my-routes-list">
            {routes.map((r) => (
              <li key={r.id} className="my-route">
                {renaming === r.id ? (
                  <form
                    className="my-route-rename"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const next = name.trim();
                      if (!next) return;
                      void renameRoute(window.location.origin, r.id, next).then((ok) => {
                        announce(ok ? `Renamed to "${next}".` : "The name was not changed; try again shortly.");
                        setRenaming(null);
                        setReload((n) => n + 1);
                      });
                    }}
                  >
                    <label>
                      New name
                      <input type="text" value={name} maxLength={NAME_MAX} onChange={(e) => setName(e.target.value)} autoFocus />
                    </label>
                    <button type="submit">Rename</button>
                    <button type="button" className="secondary" onClick={() => setRenaming(null)}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      className="link my-route-open"
                      onClick={() => void full(r.id).then((route) => route && onOpen(route))}
                      aria-describedby={`my-route-${r.id}`}
                    >
                      {r.name}
                    </button>
                    <span id={`my-route-${r.id}`} className="hint my-route-details">
                      {rowDetails(r)}
                    </span>
                    <span className="my-route-actions">
                      <button type="button" className="secondary icon-button" aria-label={`Export ${r.name} as GPX`} onClick={() => void full(r.id).then((route) => route && onExport(route))}>
                        <Icon name="download" />
                        <span aria-hidden="true">GPX</span>
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        aria-label={`Rename ${r.name}`}
                        onClick={() => {
                          setName(r.name);
                          setRenaming(r.id);
                        }}
                      >
                        Rename
                      </button>
                      {versions && (
                        <button
                          type="button"
                          className="secondary"
                          aria-label={`Versions of ${r.name}`}
                          aria-expanded={showing?.id === r.id}
                          aria-controls={`my-route-versions-${r.id}`}
                          onClick={() => showVersions(r.id)}
                        >
                          Versions
                        </button>
                      )}
                      <button
                        type="button"
                        className="secondary"
                        aria-label={deleting === r.id ? `Press again to delete ${r.name}` : `Delete ${r.name}`}
                        onClick={() => {
                          if (deleting !== r.id) {
                            setDeleting(r.id);
                            return;
                          }
                          void deleteRoute(window.location.origin, r.id).then((ok) => {
                            announce(ok ? `Deleted "${r.name}".` : "The route was not deleted; try again shortly.");
                            setDeleting(null);
                            setReload((n) => n + 1);
                          });
                        }}
                      >
                        {deleting === r.id ? "Delete?" : "Delete"}
                      </button>
                    </span>
                    {versions && showing?.id === r.id && (
                      <div id={`my-route-versions-${r.id}`} className="my-route-versions">
                        {showing.failed ? (
                          <p className="notice">The versions could not be read; try again shortly.</p>
                        ) : showing.list === null ? (
                          <p className="loading">Reading the versions…</p>
                        ) : (
                          <ol className="my-route-version-list" aria-label={`Versions of ${r.name}, newest first`}>
                            {showing.list.map((v, i) => (
                              <li key={v.id ?? "latest"}>
                                <span className="hint">
                                  {i === 0 ? "Latest: " : ""}
                                  {versionDetails(v)}
                                </span>
                                {v.id !== null && (
                                  <button type="button" className="secondary" aria-label={`Restore the version from ${versionDetails(v)}`} onClick={() => restore(r, v)}>
                                    Restore
                                  </button>
                                )}
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
