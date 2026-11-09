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
 *
 * An assistant's drafts (lib/drafts.ts; the owner, 2026-11-09: "They should be listed just like saved routes, just ones
 * that disappear") are rows of the same list, marked with the days they have left, each with Save in Archive's place.
 * The one last opened or made is on top ("most recent on top").
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
import { SAVED_SAID, SAVE_SHORT, changeRoute, listRoutes, readRoute, tagsInUse, type SavedRoute, type SavedSummary } from "./lib/savedRoutes.ts";
import { DRAFT_DELETE, deleteDraft, draftDeleteLabel, draftDeletedSaid, draftSaveLabel, listDrafts, saveDraft, type DraftSummary } from "./lib/drafts.ts";
import { readShared, type SharedRoute } from "./lib/sharedRoutes.ts";
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
  /** An assistant's draft, opened as its link opens it. */
  onOpenDraft: (route: SharedRoute) => void;
  /** A draft saved here (by its link's id). */
  onDraftSaved?: (id: string) => void;
  onOpenKept: (route: KeptRoute) => void;
}

export function LoadRouteDialog({ open, onClose, signedIn, signIn, preset, onGpx, onOpenSaved, onOpenDraft, onDraftSaved = () => {}, onOpenKept }: LoadRouteDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const [saved, setSaved] = useState<SavedSummary[] | null>(null);
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  // The draft whose Save is under way: pressed once.
  const [saving, setSaving] = useState<string | null>(null);
  // A draft just deleted: hidden at once, deleted on the server once Undo's time is up or the popup closes.
  const [gone, setGone] = useState<DraftSummary | null>(null);
  const goneRef = useRef<DraftSummary | null>(null);
  const goneTimer = useRef<number | undefined>(undefined);
  const goneUndo = useRef<HTMLButtonElement>(null);
  const flushGone = () => {
    window.clearTimeout(goneTimer.current);
    const draft = goneRef.current;
    goneRef.current = null;
    setGone(null);
    if (draft) void deleteDraft(window.location.origin, draft.id);
  };
  // Closed (or gone from the page) with Undo still offered: the delete goes through.
  useEffect(() => {
    if (!open) flushGone();
  }, [open]);
  useEffect(() => () => flushGone(), []);
  const [failed, setFailed] = useState(false);
  const [kept, setKept] = useState<KeptRoute[]>([]);
  const [filter, setFilter] = useState("");
  const [said, setSaid] = useState("");
  // One tag picked from the chips (null: All), the archived list shown or not, and the route just archived (Undo).
  const [tag, setTag] = useState<string | null>(null);
  const [archivedView, setArchivedView] = useState(false);
  const [undo, setUndo] = useState<{ id: number; name: string } | null>(null);
  const undoTimer = useRef<number | undefined>(undefined);
  // Each route's latest change: an older answer arriving after a newer one (Undo pressed before Archive's came back)
  // is ignored.
  const changes = useRef(new Map<number, number>());
  const undoRef = useRef<HTMLButtonElement>(null);
  const listEnd = useRef<HTMLButtonElement>(null);
  const archivedLinkRef = useRef<HTMLButtonElement>(null);
  // Where the focus goes once the pressed control has left: Undo after Archive, Back after Restore in Archived, and
  // the route's own Archive again after Undo.
  // Undo's own time running out while it has the focus sends it to the Archived link, never the page (review).
  const [refocus, setRefocus] = useState<"undo" | "back" | "archived" | "goneUndo" | `d${string}` | number | null>(null);
  useEffect(() => {
    if (refocus === null) return;
    if (refocus === "undo") undoRef.current?.focus();
    else if (refocus === "goneUndo") goneUndo.current?.focus();
    else if (typeof refocus === "string" && refocus.startsWith("d")) dialogRef.current?.querySelector<HTMLElement>(`[data-route="${refocus.slice(1)}"] .load-route-row`)?.focus();
    else if (refocus === "back") listEnd.current?.focus();
    else if (refocus === "archived") archivedLinkRef.current?.focus();
    else dialogRef.current?.querySelector<HTMLElement>(`[data-route="${refocus}"] .load-route-archive`)?.focus();
    setRefocus(null);
  }, [refocus]);
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
    setDrafts([]);
    setSaving(null);
    if (signedIn) {
      void listRoutes(window.location.origin).then((found) => {
        if (!live) return;
        setFailed(found === null);
        setSaved(found ?? []);
      });
      // A list that could not be read leaves only the saved routes: the drafts are also in the assistant's chat.
      void listDrafts(window.location.origin).then((found) => live && setDrafts(found ?? []));
    }
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
  const rows = loadRows(saved ?? [], kept, archivedView, drafts);
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
    if (archived)
      undoTimer.current = window.setTimeout(() => {
        if (undoRef.current && document.activeElement === undoRef.current) setRefocus("archived");
        setUndo(null);
      }, UNDO_MS);
    setSaid(archived ? "" : t("Restored {name}.", { name: row.name }));
    const turn = (changes.current.get(row.id) ?? 0) + 1;
    changes.current.set(row.id, turn);
    setRefocus(archived ? "undo" : archivedView ? "back" : row.id);
    void changeRoute(window.location.origin, row.id, { archived }).then((now) => {
      if (changes.current.get(row.id) !== turn) return;
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
  const deleteOne = (row: Extract<LoadRow, { kind: "draft" }>) => {
    const draft = drafts.find((d) => d.id === row.id);
    if (!draft) return;
    flushGone();
    setDrafts((all) => all.filter((d) => d.id !== row.id));
    goneRef.current = draft;
    setGone(draft);
    setSaid("");
    goneTimer.current = window.setTimeout(() => {
      // Undo leaving with the focus on it: to Close, never the page.
      if (goneUndo.current && document.activeElement === goneUndo.current) dialogRef.current?.querySelector<HTMLElement>(".closure-choices button")?.focus();
      flushGone();
    }, UNDO_MS);
    setRefocus("goneUndo");
  };
  const undoDelete = () => {
    window.clearTimeout(goneTimer.current);
    const draft = goneRef.current;
    goneRef.current = null;
    setGone(null);
    if (draft) {
      setDrafts((all) => [...all, draft]);
      setRefocus(`d${draft.id}`);
    }
  };
  const saveOne = (row: Extract<LoadRow, { kind: "draft" }>) => {
    if (saving) return;
    setSaving(row.id);
    setSaid(t("Saving {name}…", { name: row.name }));
    void saveDraft(window.location.origin, row.id).then((outcome) => {
      setSaving(null);
      if (outcome === null) {
        setDrafts((all) => all.filter((d) => d.id !== row.id));
        setSaid(t("That draft is gone."));
      } else if (outcome.ok) {
        setDrafts((all) => all.filter((d) => d.id !== row.id));
        setSaved((all) => [outcome.route, ...(all ?? [])]);
        onDraftSaved(row.id);
        setSaid(SAVED_SAID(outcome.route.name));
        setRefocus(outcome.route.id);
      } else setSaid(outcome.message);
    });
  };
  const pick = (row: LoadRow) => {
    if (row.kind === "kept") {
      onOpenKept(row.kept);
      return;
    }
    if (row.kind === "draft") {
      setSaid(`Opening ${row.name}…`);
      void readShared(window.location.origin, row.id).then((route) => {
        if (route && route !== "gone" && route !== "revoked") onOpenDraft(route);
        else if (route === null) setSaid("That route could not be read; try again shortly.");
        else {
          setDrafts((all) => all.filter((d) => d.id !== row.id));
          setSaid(t("That draft is gone."));
        }
      });
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
            {gone && !archivedView && (
              <p className="notice load-route-undo">
                <span>{draftDeletedSaid(gone.name)}</span>
                <button type="button" className="link" ref={goneUndo} onClick={undoDelete}>
                  {LOAD_UNDO}
                </button>
              </p>
            )}
            {undo && !archivedView && (
              <p className="notice load-route-undo">
                <span>{archivedSaid(undo.name)}</span>
                <button type="button" className="link" ref={undoRef} onClick={undoArchive}>
                  {LOAD_UNDO}
                </button>
              </p>
            )}
          </div>
          {shown.length > 0 && (
            <ul role="list" className="load-route-list" aria-labelledby={headingId}>
              {shown.map((row) => (
                <li key={row.key} className="load-route-item" data-route={row.kind === "saved" || row.kind === "draft" ? row.id : undefined}>
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
                  {row.kind === "draft" && (
                    <>
                      <button type="button" className="secondary load-route-save" aria-label={draftSaveLabel(row.name)} title={SAVE_SHORT} disabled={saving === row.id} onClick={() => saveOne(row)}>
                        <Icon name="save" size={22} />
                      </button>
                      <button type="button" className="secondary load-route-delete" aria-label={draftDeleteLabel(row.name)} title={DRAFT_DELETE} onClick={() => deleteOne(row)}>
                        <Icon name="trash" size={22} />
                      </button>
                    </>
                  )}
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
            <button type="button" className="link load-route-archived" ref={archivedLinkRef} onClick={() => setArchivedView(true)}>
              {archivedLink(archivedCount)}
            </button>
          )}
          <div className="closure-choices">
            {archivedView ? (
              <button
                type="button"
                className="secondary"
                ref={listEnd}
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
