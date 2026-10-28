/**
 * The installable app's parts of the page (WEB-NAV-plan.md section 8, phases P2-P4):
 *
 * - `useAppStatus`: the service worker's "new version ready" (lib/appWorker.ts) and the network's
 *   online and offline, with what each says. `AppStatusBar` shows them at the top of the panel;
 *   App's own live region (outside the panel, so it is heard with the sheet hidden) says them.
 * - `InstallOffer`: "Install RouteMaker" (Chrome, Edge, Android), the iOS line, or "installed"
 *   (lib/installOffer.ts), in Settings and in More tips. Never a pop-up.
 * - `KeptRoutes`: Settings' list of the routes kept for offline, each with Open and Remove
 *   (lib/offlineRoutes.ts, lib/offlineKeep.ts).
 *
 * Accessibility: every control is a real button with its words in text, 44 px high (the panel's own
 * rule); nothing takes the focus on its own; after a press that removes the control pressed, the
 * focus goes to the next sensible place (the next row's Remove, or the section's heading), never to the
 * page's top. What changes is said once, politely, through `onSay` (App's live region with its count).
 */
import { createElement, useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type RefObject } from "react";
import { AppWorker, OFFLINE_SAID, ONLINE_SAID, UPDATE_READY, UPDATE_RELOAD, UPDATE_RELOAD_NAME, browserWorkerEnv, updateOffered } from "./lib/appWorker.ts";
import {
  DISMISSED_SAID,
  INSTALLED_NOTE,
  INSTALLED_SAID,
  INSTALL_HEADING,
  INSTALL_LABEL,
  INSTALL_WHY,
  IOS_INSTALL,
  installOffer,
  installState,
  isStandalone,
  promptInstall,
  subscribeInstall,
} from "./lib/installOffer.ts";
import { removeKept } from "./lib/offlineKeep.ts";
import { matchSaid, matching } from "./lib/routeSearch.ts";
import { KEPT_HEADING, KEPT_HOW, KEPT_NONE, KEPT_NONE_SHORT, KEPT_PRIVATE, focusAfterRemove, keptDetail, removeFailedSaid, removedSaid, sortKept, storageNote, type KeptRoute } from "./lib/offlineRoutes.ts";
import { listKept, persisted } from "./lib/offlineRouteStore.ts";
import { InfoButton } from "./SettingRow.tsx";
import { t } from "./lib/i18n.ts";

// ---- The new version and the network --------------------------------------------------------------

let worker: AppWorker | null = null;
let workerReady = false;
const readyListeners = new Set<() => void>();

/** One worker client for the page (React's strict mode runs effects twice; the registration is once). */
function startWorker(): AppWorker {
  if (!worker) {
    worker = new AppWorker(browserWorkerEnv(), (ready) => {
      workerReady = ready;
      readyListeners.forEach((listener) => listener());
    });
    void worker.start();
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") worker?.check();
    });
  }
  return worker;
}

/** Run `start` once the page has loaded and the browser is idle (or at once, if it already is); returns a cancel. */
export function whenSettled(start: () => void, win: Window = window): () => void {
  let cancelled = false;
  let idle: number | null = null;
  const go = () => {
    if (cancelled) return;
    if (typeof win.requestIdleCallback === "function") idle = win.requestIdleCallback(() => !cancelled && start(), { timeout: 5000 });
    else idle = win.setTimeout(() => !cancelled && start(), 0);
  };
  if (win.document.readyState === "complete") go();
  else win.addEventListener("load", go, { once: true });
  return () => {
    cancelled = true;
    win.removeEventListener("load", go);
    if (idle !== null) {
      if (typeof win.cancelIdleCallback === "function") win.cancelIdleCallback(idle);
      win.clearTimeout(idle);
    }
  };
}

const subscribeReady = (listener: () => void) => {
  readyListeners.add(listener);
  return () => readyListeners.delete(listener);
};

function useOnline(): boolean {
  return useSyncExternalStore(
    (listener) => {
      window.addEventListener("online", listener);
      window.addEventListener("offline", listener);
      return () => {
        window.removeEventListener("online", listener);
        window.removeEventListener("offline", listener);
      };
    },
    () => navigator.onLine !== false,
  );
}

export interface AppStatus {
  updateShown: boolean;
  offline: boolean;
  reload: () => void;
}

/**
 * The page's status as an installable app. `onSay` is told, once each: a new version ready (held
 * during a ride, said when it ends), offline, and back online (both shown, not said, during a ride:
 * Ride mode says what a lost signal means for the ride itself).
 */
export function useAppStatus(riding: boolean, onSay: (text: string) => void, offlineSaid: () => string = () => OFFLINE_SAID): AppStatus {
  // After the page has loaded, when the browser is idle: the worker's install downloads the build, which
  // would otherwise compete with the map's style and first tiles (review fe-perf-6).
  useEffect(() => whenSettled(() => void startWorker()), []);
  const ready = useSyncExternalStore(subscribeReady, () => workerReady);
  const online = useOnline();
  const updateShown = updateOffered(ready, riding);
  const said = useRef({ update: false, offline: false });
  useEffect(() => {
    if (updateShown && !said.current.update) {
      said.current.update = true;
      onSay(`${UPDATE_READY} The ${UPDATE_RELOAD} button is at the top of the planner.`);
    }
  }, [updateShown, onSay]);
  useEffect(() => {
    if (!online && !said.current.offline) {
      said.current.offline = true;
      if (!riding) onSay(offlineSaid());
    } else if (online && said.current.offline) {
      said.current.offline = false;
      if (!riding) onSay(ONLINE_SAID);
    }
    // `riding` is read, not watched: a ride starting or ending says nothing about the network.
  }, [online, onSay]);
  const reload = useCallback(() => startWorker().apply(), []);
  return { updateShown, offline: !online, reload };
}

/**
 * At the top of the panel: offline, and the new version with its Reload. Empty, it is not drawn. `offline`: the
 * offline line as the page has it (lib/appWorker.ts offlineLine), null where something else says it.
 */
export function AppStatusBar({ status, offline = status.offline ? OFFLINE_SAID : null }: { status: AppStatus; offline?: string | null }) {
  const offlineShown = status.offline ? offline : null;
  if (!status.updateShown && !offlineShown) return null;
  return (
    <div className="app-status">
      {offlineShown && <p className="app-offline">{offlineShown}</p>}
      {status.updateShown && (
        <div className="app-update">
          <p id="app-update-text">{UPDATE_READY}</p>
          <button type="button" aria-label={UPDATE_RELOAD_NAME} onClick={status.reload}>
            {UPDATE_RELOAD}
          </button>
        </div>
      )}
    </div>
  );
}

// ---- The install offer -----------------------------------------------------------------------------

function useInstall() {
  const [, setVersion] = useState(0);
  useEffect(() => subscribeInstall(() => setVersion((v) => v + 1)), []);
  return installOffer(installState());
}

/**
 * The offer, under its own heading (Settings) or as a short block (More tips, `compact`). `onSay`
 * hears the outcome of the browser's dialog; the focus then goes to the heading (the button it was on
 * is gone) in Settings, or stays in the tips' block on its note.
 */
export function InstallOffer({ idBase, compact = false, onSay }: { idBase: string; compact?: boolean; onSay: (text: string) => void }) {
  const offer = useInstall();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const noteRef = useRef<HTMLParagraphElement>(null);
  // What the browser's dialog ended with, kept on screen where the button was (it is gone after a press).
  const [said, setSaid] = useState("");
  if (offer === "none" && !said) return null;
  if (compact && offer === "installed" && !said) return null;
  const press = async () => {
    const outcome = await promptInstall();
    const text = outcome === "accepted" ? INSTALLED_SAID : outcome === "dismissed" ? DISMISSED_SAID : "";
    if (!text) return;
    setSaid(text);
    onSay(text);
    window.setTimeout(() => (compact ? noteRef : headingRef).current?.focus(), 0);
  };
  // Installed (here or by the browser's own menu), the press's outcome gives way to the plain note.
  const note = offer === "installed" ? (said === INSTALLED_SAID ? said : INSTALLED_NOTE) : offer === "none" ? said : "";
  const body = (
    <>
      {offer === "button" && (
        <>
          {!compact && <p className="hint">{INSTALL_WHY}</p>}
          <button type="button" className="install-app" onClick={() => void press()}>
            {INSTALL_LABEL}
          </button>
        </>
      )}
      {offer === "ios" && (
        <p className="hint install-ios">
          {compact ? t("To install RouteMaker: ") : `${INSTALL_WHY} `}
          {IOS_INSTALL}
        </p>
      )}
      {note && (
        <p className="hint install-note" ref={noteRef} tabIndex={-1}>
          {note}
        </p>
      )}
    </>
  );
  if (compact) return <div className="install-offer install-offer-tips">{body}</div>;
  return (
    <section aria-labelledby={`${idBase}-heading`} className="install-offer">
      <h3 id={`${idBase}-heading`} ref={headingRef} tabIndex={-1}>
        {INSTALL_HEADING}
      </h3>
      {body}
    </section>
  );
}

// ---- The routes kept for offline -------------------------------------------------------------------

/**
 * Settings' list. `version` is bumped by App when a route is kept, so the list reads the store again;
 * `onOpen` opens a kept route's plan (with no signal, the planner shows the kept answer).
 */
export function KeptRoutes({
  version,
  onOpen,
  onSay,
  headingRef,
  compact = false,
  filter = "",
  level = 3,
}: {
  version: number;
  onOpen: (route: KeptRoute) => void;
  onSay: (text: string) => void;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  /** The Save and load sheet: the how and the privacy note behind an (i) by the heading. */
  compact?: boolean;
  /** Words from the sheet's search: only the routes whose titles hold them are listed. */
  filter?: string;
  /** Its heading's level: 4 under Your routes' heading. */
  level?: 3 | 4;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const [routes, setRoutes] = useState<KeptRoute[] | null>(null);
  const [kept, setKept] = useState<boolean | null>(null);
  const [removed, setRemoved] = useState(0);
  const ownHeading = useRef<HTMLHeadingElement>(null);
  const heading = headingRef ?? ownHeading;
  const removeRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const focusNext = useRef<ReturnType<typeof focusAfterRemove> | null>(null);
  const id = useId();
  useEffect(() => {
    let current = true;
    void listKept().then((all) => current && setRoutes(sortKept(all)));
    void persisted().then((p) => current && setKept(p));
    return () => {
      current = false;
    };
  }, [version, removed]);
  useEffect(() => {
    const target = focusNext.current;
    if (target === null || routes === null) return;
    focusNext.current = null;
    if (target === "heading") heading.current?.focus();
    else removeRefs.current[target.row]?.focus();
  }, [routes, heading]);
  const remove = async (route: KeptRoute, index: number) => {
    const removed = await removeKept(route.id).then(
      () => true,
      () => false,
    );
    if (!removed) {
      // Still in the list, and the focus stays on its Remove.
      onSay(removeFailedSaid(route.title));
      return;
    }
    // The focus goes by the rows shown (the search may hide some); the count said is of every kept route.
    focusNext.current = focusAfterRemove(index, matching(routes ?? [route], filter, (r) => r.title).length - 1);
    onSay(removedSaid(route.title, (routes?.length ?? 1) - 1));
    setRemoved((n) => n + 1);
  };
  return (
    <section aria-labelledby={`${id}-heading`} className="kept-routes">
      <div className="setting-line">
        {createElement(level === 4 ? "h4" : "h3", { id: `${id}-heading`, ref: heading, tabIndex: -1 }, KEPT_HEADING)}
        {compact && <InfoButton open={infoOpen} onToggle={() => setInfoOpen((was) => !was)} controls={`${id}-info`} about={t("routes kept for offline")} />}
      </div>
      {compact && (
        <p className="hint setting-info" id={`${id}-info`} hidden={!infoOpen}>
          {KEPT_HOW} {KEPT_PRIVATE} {storageNote(kept, isStandalone())}
        </p>
      )}
      {routes !== null && routes.length > 0 && (
        <p className="hint" role="status">
          {matchSaid(matching(routes, filter, (r) => r.title).length, routes.length, filter)}
        </p>
      )}
      {routes === null ? (
        <p className="hint">{t("Reading the routes kept on this device…")}</p>
      ) : routes.length === 0 ? (
        <p className="hint">{compact ? KEPT_NONE_SHORT : KEPT_NONE}</p>
      ) : matching(routes, filter, (r) => r.title).length === 0 ? null : (
        <ul className="kept-list">
          {matching(routes, filter, (r) => r.title).map((route, index) => (
            <li key={route.id} className="kept-route">
              <p className="kept-title" id={`${id}-title-${index}`}>
                {route.title}
              </p>
              <p className="hint kept-detail" id={`${id}-detail-${index}`}>
                {keptDetail(route)}
              </p>
              <div className="kept-actions">
                <button type="button" className="secondary" aria-describedby={`${id}-detail-${index}`} onClick={() => onOpen(route)}>
                  Open<span className="visually-hidden"> {route.title}</span>
                </button>
                <button
                  type="button"
                  className="secondary"
                  ref={(button) => {
                    removeRefs.current[index] = button;
                  }}
                  onClick={() => void remove(route, index)}
                >
                  Remove<span className="visually-hidden"> {route.title}</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!compact && (
        <p className="hint">
          {KEPT_PRIVATE} {storageNote(kept, isStandalone())}
        </p>
      )}
    </section>
  );
}
