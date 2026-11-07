/**
 * Load route's popup (lib/loadRoute.ts): the platform's modal <dialog>, as Start ride's computer question is. Signed
 * out, Sign in with Discord comes first (the owner, 2026-10-22: "If not signed in to discord prompt that too"); then
 * Open GPX file and the rider's routes, one tap each. Escape or Close goes back to the control that opened it (Plan's
 * Load route, or Go's More > Saved routes).
 *
 * Organizing (the owner, 2026-11-07: "Load route is getting too unwieldy. Maybe add the ability to add tags ... as well
 * as ways to find and organize them. Put an 'archive' button on the view"): the search finds tags as well as names; a
 * row of the tags in use filters the list in one tap; each saved route has an Archive button, with Undo for a few
 * seconds; and "Archived (n)" under the list opens the archived ones, each openable and with Restore.
 */
import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { DiscordLogo } from "./DiscordLogo.tsx";
import { Icon } from "./Icon.tsx";
import {
  LOAD_ALL,
  LOAD_ARCHIVE,
  LOAD_ARCHIVED_TITLE,
  LOAD_ARCHIVED_WHY,
  LOAD_BACK,
  LOAD_RESTORE,
  LOAD_UNDO,
  archivedLink,
  archivedSaid,
  searchText,
  withTag,
  GPX_BACK,
  GPX_CHOOSE,
  GPX_EXACT,
  GPX_EXACT_HINT,
  GPX_HOW,
  GPX_RIDE,
  GPX_SNAP,
  GPX_SNAP_HINT,
  LOAD_CLOSE,
  LOAD_FAILED,
  LOAD_GPX,
  LOAD_NONE,
  LOAD_ROUTE,
  LOAD_SEARCH,
  LOAD_SIGN_IN,
  SEARCH_FROM,
  gpxRideTypes,
  gpxStartRide,
  loadRows,
  type GpxChoice,
  type LoadRow,
} from "./lib/loadRoute.ts";
import { listKept } from "./lib/offlineRouteStore.ts";
import { sortKept, type KeptRoute } from "./lib/offlineRoutes.ts";
import { matchSaid, matching } from "./lib/routeSearch.ts";
import type { PresetId } from "./lib/presets.ts";
import { changeRoute, listRoutes, readRoute, tagsInUse, type SavedRoute, type SavedSummary } from "./lib/savedRoutes.ts";
import { t } from "./lib/i18n.ts";

/** How long Undo stays after Archive. */
const UNDO_MS = 8000;

export interface LoadRouteDialogProps {
  open: boolean;
  onClose: () => void;
  signedIn: boolean;
  /** Signed out, where the server signs riders in: keeps the plan across the round trip. Null where it does not. */
  signIn: ((event: MouseEvent<HTMLAnchorElement>) => void) | null;
  /** The page's ride type, offered first for a file. */
  preset: PresetId;
  /** Opens the file picker of Save & load's GPX panel, which opens the file as Open GPX… there does, as chosen here. */
  onGpx: (choice: GpxChoice) => void;
  onOpenSaved: (route: SavedRoute) => void;
  onOpenKept: (route: KeptRoute) => void;
}

export function LoadRouteDialog({ open, onClose, signedIn, signIn, preset, onGpx, onOpenSaved, onOpenKept }: LoadRouteDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const [saved, setSaved] = useState<SavedSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [kept, setKept] = useState<KeptRoute[]>([]);
  const [filter, setFilter] = useState("");
  const [said, setSaid] = useState("");
  // One tag picked from the chips (null: All), the archived list shown or not, and the route just archived (Undo).
  const [tag, setTag] = useState<string | null>(null);
  const [archivedView, setArchivedView] = useState(false);
  const [undo, setUndo] = useState<{ id: number; name: string } | null>(null);
  const undoTimer = useRef<number | undefined>(undefined);
  // Open GPX file asks first (the owner, 2026-10-22): the ride type, and snapped to roads or exactly as drawn.
  const [gpx, setGpx] = useState<GpxChoice | null>(null);
  const gpxFirst = useRef<HTMLSelectElement>(null);
  const gpxOpener = useRef<HTMLButtonElement>(null);
  const radios = useId();
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      dialog.showModal?.();
      // The first of the big buttons: Sign in with Discord signed out, else Open GPX file.
      dialog.querySelector<HTMLElement>(".load-route-top a, .load-route-top button")?.focus();
    } else if (!open && opener.current) {
      // Closed here, or already by Choose file (before the picker): the focus goes back to Load route either way.
      if (dialog.open) dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
      opener.current = null;
    }
  }, [open]);
  // Read each time it opens: a route saved or kept since is listed.
  useEffect(() => {
    if (!open) return;
    let live = true;
    setFilter("");
    setSaid("");
    setGpx(null);
    setTag(null);
    setArchivedView(false);
    setUndo(null);
    setFailed(false);
    setSaved(signedIn ? null : []);
    if (signedIn)
      void listRoutes(window.location.origin).then((found) => {
        if (!live) return;
        setFailed(found === null);
        setSaved(found ?? []);
      });
    void listKept().then((all) => live && setKept(sortKept(all)));
    return () => {
      live = false;
    };
  }, [open, signedIn]);
  // The focus follows the step: into the questions, and back to Open GPX file.
  const asked = gpx !== null;
  const stepped = useRef(false);
  useEffect(() => {
    if (!open) {
      stepped.current = false;
      return;
    }
    if (asked) gpxFirst.current?.focus();
    else if (stepped.current) gpxOpener.current?.focus();
    stepped.current = true;
  }, [asked, open]);
  useEffect(() => () => window.clearTimeout(undoTimer.current), []);
  const live = (saved ?? []).filter((r) => !r.archived_at);
  const archivedCount = (saved ?? []).length - live.length;
  const tags = tagsInUse(live);
  // A tag no route carries any more (its last one archived) lets go, back to All.
  const picked = tag !== null && tags.some((x) => x.toLocaleLowerCase() === tag.toLocaleLowerCase()) ? tag : null;
  const rows = loadRows(saved ?? [], kept, archivedView);
  const shown = matching(withTag(rows, archivedView ? null : picked), filter, searchText);
  /** The route as the server now has it, in the list; null puts back what it was (a failed change). */
  const replaceSaved = (next: SavedSummary) => setSaved((all) => (all ?? []).map((r) => (r.id === next.id ? next : r)));
  const setArchived = (row: Extract<LoadRow, { kind: "saved" }>, archived: boolean) => {
    const before = (saved ?? []).find((r) => r.id === row.id);
    if (!before) return;
    // At once, as the mockup the owner approved shows it; put back if the server says no.
    replaceSaved({ ...before, archived_at: archived ? new Date().toISOString() : null, replaced_by: archived ? before.replaced_by : null });
    window.clearTimeout(undoTimer.current);
    setUndo(archived ? { id: row.id, name: row.name } : null);
    if (archived) undoTimer.current = window.setTimeout(() => setUndo(null), UNDO_MS);
    setSaid(archived ? "" : t("Restored {name}.", { name: row.name }));
    void changeRoute(window.location.origin, row.id, { archived }).then((now) => {
      if (now) replaceSaved(now);
      else {
        replaceSaved(before);
        setUndo(null);
        setSaid(t("That could not be changed; try again shortly."));
      }
    });
  };
  const undoArchive = () => {
    const row = rows.find((r) => r.kind === "saved" && r.id === undo?.id) ?? loadRows(saved ?? [], [], true).find((r) => r.kind === "saved" && r.id === undo?.id);
    if (row?.kind === "saved") setArchived(row, false);
    setUndo(null);
  };
  const pick = (row: LoadRow) => {
    if (row.kind === "kept") {
      onOpenKept(row.kept);
      return;
    }
    setSaid(`Opening ${row.name}…`);
    void readRoute(window.location.origin, row.id).then((route) => {
      if (route) onOpenSaved(route);
      else setSaid("That route could not be read; try again shortly.");
    });
  };
  return (
    <dialog
      ref={dialogRef}
      className="load-route-dialog"
      aria-labelledby={headingId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open && gpx && (
        <form
          className="load-route-gpx-ask"
          onSubmit={(event) => {
            event.preventDefault();
            // The modal goes first: while it is open the page's file input is inert, and some browsers then open no picker.
            dialogRef.current?.close();
            onGpx(gpx);
          }}
          onKeyDown={(event) => {
            // Escape steps back to the list, not out of the popup.
            if (event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              setGpx(null);
            }
          }}
        >
          <h2 id={headingId}>{LOAD_GPX}</h2>
          <label className="load-route-field">
            {GPX_RIDE}
            <select ref={gpxFirst} value={gpx.preset} onChange={(event) => setGpx({ ...gpx, preset: event.target.value as PresetId })}>
              {gpxRideTypes().map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <fieldset className="load-route-field load-route-how">
            <legend>{GPX_HOW}</legend>
            {[
              { exact: false, label: GPX_SNAP, hint: GPX_SNAP_HINT },
              { exact: true, label: GPX_EXACT, hint: GPX_EXACT_HINT },
            ].map((o) => (
              <label key={o.label} className="load-route-radio">
                <input type="radio" name={radios} checked={gpx.exact === o.exact} onChange={() => setGpx({ ...gpx, exact: o.exact })} aria-describedby={`${radios}-${o.exact}`} />
                <span>
                  <span className="load-route-name">{o.label}</span>
                  <span className="load-route-detail" id={`${radios}-${o.exact}`}>
                    {o.hint}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          <div className="load-route-top">
            <button type="submit" className="load-route-gpx">
              <Icon name="file" size={20} />
              {GPX_CHOOSE}
            </button>
          </div>
          <div className="closure-choices">
            <button type="button" className="secondary" onClick={() => setGpx(null)}>
              {GPX_BACK}
            </button>
          </div>
        </form>
      )}
      {open && !gpx && (
        <>
          <h2 id={headingId}>{archivedView ? LOAD_ARCHIVED_TITLE : LOAD_ROUTE}</h2>
          {!archivedView && (
            <div className="load-route-top">
              {!signedIn && signIn && (
                <a
                  className="button save-route-sign-in load-route-sign-in"
                  href="/auth/login"
                  onClick={signIn}
                >
                  <DiscordLogo />
                  {t("Sign in with Discord")}
                </a>
              )}
              <button
                type="button"
                className={signedIn || !signIn ? "load-route-gpx" : "secondary load-route-gpx"}
                ref={gpxOpener}
                onClick={() => setGpx({ preset: gpxStartRide(preset), exact: false })}
              >
                <Icon name="file" size={20} />
                {LOAD_GPX}
              </button>
            </div>
          )}
          {!archivedView && !signedIn && signIn && <p className="hint load-route-why">{LOAD_SIGN_IN}.</p>}
          {archivedView && <p className="hint">{LOAD_ARCHIVED_WHY}</p>}
          {rows.length > SEARCH_FROM && (
            <input type="search" className="route-search" aria-label={LOAD_SEARCH} placeholder={LOAD_SEARCH} value={filter} onChange={(event) => setFilter(event.target.value)} />
          )}
          {!archivedView && tags.length > 0 && (
            <div className="load-route-tags" role="group" aria-label={t("Tags")}>
              {[null, ...tags].map((x) => (
                <button key={x ?? ""} type="button" className="load-route-tag" aria-pressed={picked === x} onClick={() => setTag(x)}>
                  {x ?? LOAD_ALL}
                </button>
              ))}
            </div>
          )}
          <div role="status" aria-live="polite">
            {failed && <p className="notice">{LOAD_FAILED}</p>}
            {signedIn && saved === null && <p className="loading">{t("Reading your routes…")}</p>}
            {signedIn && saved !== null && !failed && !archivedView && rows.length === 0 && archivedCount === 0 && <p className="hint">{LOAD_NONE}</p>}
            {filter && <p className="hint">{matchSaid(shown.length, rows.length, filter)}</p>}
            {said && <p className="hint">{said}</p>}
            {undo && !archivedView && (
              <p className="notice load-route-undo">
                <span>{archivedSaid(undo.name)}</span>
                <button type="button" className="link" onClick={undoArchive}>
                  {LOAD_UNDO}
                </button>
              </p>
            )}
          </div>
          {shown.length > 0 && (
            <ul role="list" className="load-route-list" aria-labelledby={headingId}>
              {shown.map((row) => (
                <li key={row.key} className="load-route-item">
                  <button type="button" className="load-route-row" onClick={() => pick(row)}>
                    <span className="load-route-name">{row.name}</span>
                    <span className="load-route-detail">
                      {row.detail}
                      {row.kind === "saved" && row.replacedBy && <span className="load-route-replaced"> · {t("replaced by {name}", { name: row.replacedBy })}</span>}
                      {row.kind === "saved" &&
                        row.tags.map((x) => (
                          <span key={x} className="load-route-tag-mark">
                            {x}
                          </span>
                        ))}
                    </span>
                  </button>
                  {row.kind === "saved" &&
                    (row.archived ? (
                      <button type="button" className="secondary load-route-restore" aria-label={t("Restore {name}", { name: row.name })} onClick={() => setArchived(row, false)}>
                        {LOAD_RESTORE}
                      </button>
                    ) : (
                      <button type="button" className="secondary load-route-archive" aria-label={t("Archive {name}", { name: row.name })} title={LOAD_ARCHIVE} onClick={() => setArchived(row, true)}>
                        <Icon name="archive" size={22} />
                      </button>
                    ))}
                </li>
              ))}
            </ul>
          )}
          {!archivedView && archivedCount > 0 && (
            <button type="button" className="link load-route-archived" onClick={() => setArchivedView(true)}>
              {archivedLink(archivedCount)}
            </button>
          )}
          <div className="closure-choices">
            {archivedView ? (
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setArchivedView(false);
                  setFilter("");
                }}
              >
                {LOAD_BACK}
              </button>
            ) : (
              <button type="button" className="secondary" onClick={onClose}>
                {LOAD_CLOSE}
              </button>
            )}
          </div>
        </>
      )}
    </dialog>
  );
}
