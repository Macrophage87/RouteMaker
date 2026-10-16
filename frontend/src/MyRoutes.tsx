/**
 * My routes (v0.7.0 plan, item 3): a signed-in rider's saved routes, in Plan's Settings and Go's Menu. Each row
 * opens the route as it was saved, renames it, exports it as GPX, or deletes it (after a second press). The
 * list is read when the section is shown and again after each change.
 *
 * In Plan, the rider's shared links follow (lib/sharedRoutes.ts): each is its link, with New link (a new link for
 * the same route, the old one turned off, copied where the browser allows) and Turn off (after a second press, as
 * Delete is). Go's Menu shows the saved routes only.
 */
import { useEffect, useId, useState } from "react";
import { Icon } from "./Icon.tsx";
import {
  MAX_SAVED,
  MY_ROUTES,
  NAME_MAX,
  NONE_SAVED,
  countLine,
  deleteRoute,
  listRoutes,
  readRoute,
  renameRoute,
  rowDetails,
  type SavedRoute,
  type SavedSummary,
} from "./lib/savedRoutes.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { NEW_LINK, SHARED_LINKS, TURN_OFF, keepSaid, listSharedLinks, regenerateSharedLink, revokeSharedLink, type SharedLink } from "./lib/sharedRoutes.ts";
import { formatDistance } from "./lib/format.ts";

export interface MyRoutesProps {
  /** Bumped by the page after a save, so the list is read again. */
  version: number;
  onOpen: (route: SavedRoute) => void;
  onExport: (route: SavedRoute) => void;
  announce: (text: string) => void;
  /** Plan only: the rider's shared links, to turn off or replace. */
  sharedLinks?: boolean;
  /** A link turned off or replaced: the page's Share forgets the id it last gave. */
  onSharedChange?: () => void;
}

export function MyRoutes({ version, onOpen, onExport, announce, sharedLinks = false, onSharedChange = () => {} }: MyRoutesProps) {
  const headingId = useId();
  const [routes, setRoutes] = useState<SavedSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [renaming, setRenaming] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const [reload, setReload] = useState(0);

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
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {sharedLinks && <SharedLinks version={version} announce={announce} onChange={onSharedChange} />}
    </section>
  );
}

function SharedLinks({ version, announce, onChange }: { version: number; announce: (text: string) => void; onChange: () => void }) {
  const headingId = useId();
  const [links, setLinks] = useState<SharedLink[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [turningOff, setTurningOff] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    void listSharedLinks(window.location.origin).then((found) => {
      if (!live) return;
      setFailed(found === null);
      setLinks(found ?? []);
    });
    return () => {
      live = false;
    };
  }, [version, reload]);

  // Nothing shared signed in yet: no heading, no list.
  if (!failed && (!links || links.length === 0)) return null;
  return (
    <section aria-labelledby={headingId} className="my-routes">
      <h4 id={headingId}>{SHARED_LINKS}</h4>
      {failed && <p className="notice">Your shared links could not be read; try again shortly.</p>}
      {links && links.length > 0 && (
        <ul role="list" className="my-routes-list">
          {links.map((l) => (
            <li key={l.id} className="my-route">
              <a className="my-route-open" href={l.link} aria-describedby={`shared-link-${l.id}`}>
                {l.name}
              </a>
              <span id={`shared-link-${l.id}`} className="hint my-route-details">
                {formatDistance(l.distance_m)}, {keepSaid(l)}
              </span>
              <span className="my-route-actions">
                <button
                  type="button"
                  className="secondary"
                  aria-label={`${NEW_LINK} for ${l.name}`}
                  onClick={() =>
                    void regenerateSharedLink(window.location.origin, l.id).then(async (fresh) => {
                      if (!fresh) {
                        announce("No new link was made; try again shortly.");
                        return;
                      }
                      onChange();
                      const copied = await copyText(fresh.link, navigator.clipboard, selectionCopy);
                      announce(copied ? `New link for "${l.name}" copied; the old link is turned off.` : `New link made for "${l.name}"; the old link is turned off.`);
                      setReload((n) => n + 1);
                    })
                  }
                >
                  {NEW_LINK}
                </button>
                <button
                  type="button"
                  className="secondary"
                  aria-label={turningOff === l.id ? `Press again to turn off the link for ${l.name}` : `${TURN_OFF} the link for ${l.name}`}
                  onClick={() => {
                    if (turningOff !== l.id) {
                      setTurningOff(l.id);
                      return;
                    }
                    void revokeSharedLink(window.location.origin, l.id).then((ok) => {
                      if (ok) onChange();
                      announce(ok ? `The link for "${l.name}" is turned off.` : "The link was not turned off; try again shortly.");
                      setTurningOff(null);
                      setReload((n) => n + 1);
                    });
                  }}
                >
                  {turningOff === l.id ? `${TURN_OFF}?` : TURN_OFF}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
