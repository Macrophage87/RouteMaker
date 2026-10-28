/**
 * Settings > Account's AI assistants (lib/assistantApps.ts): the apps connected through the site's own connector, each
 * with Disconnect (the owner, 2026-10-19), and a link to how to connect one (the owner, 2026-10-25, retiring the
 * save-only key). Folded to one line so Settings stays short for the many riders who never use it.
 */
import { useEffect, useRef, useState } from "react";
import {
  APPS_HELP,
  APPS_LABEL,
  APPS_READ_FAILED,
  DISCONNECTED,
  DISCONNECT_ASK,
  DISCONNECT_FAILED,
  DOCS_LINK,
  DOCS_WORDS,
  appSummary,
  assistantsSummary,
  disconnectApp,
  readApps,
  type ConnectedApp,
} from "./lib/assistantApps.ts";
import { t } from "./lib/i18n.ts";

export function AssistantAppsSetting({ origin = window.location.origin }: { origin?: string }) {
  const [apps, setApps] = useState<ConnectedApp[] | null | undefined>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const status = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    let live = true;
    void readApps(origin).then((read) => {
      if (live) setApps(read);
    });
    return () => {
      live = false;
    };
  }, [origin]);

  const disconnect = async (app: ConnectedApp) => {
    if (!window.confirm(DISCONNECT_ASK)) return;
    setBusy(true);
    const left = await disconnectApp(origin, app.id);
    setBusy(false);
    if (!left) return setSaid(DISCONNECT_FAILED);
    setApps(left);
    setSaid(DISCONNECTED);
    // The pressed button's row is gone: keep focus on the line that says what happened.
    status.current?.focus();
  };

  return (
    <details className="assistant-key">
      <summary>
        {APPS_LABEL}
        <span className="setting-value">
          <span className="visually-hidden">: </span>
          {apps === null ? "…" : apps === undefined ? "?" : assistantsSummary(apps)}
        </span>
      </summary>
      <p className="hint">
        {APPS_HELP} <a href={DOCS_LINK}>{DOCS_WORDS}</a>
      </p>
      {apps === undefined ? (
        <p className="hint">{APPS_READ_FAILED}</p>
      ) : apps && apps.length > 0 ? (
        <ul className="assistant-apps">
          {apps.map((app) => (
            <li key={app.id}>
              <span>{appSummary(app)}</span>
              <button type="button" className="secondary" disabled={busy} aria-label={t("Disconnect {app}", { app: appSummary(app) })} onClick={() => void disconnect(app)}>
                {t("Disconnect")}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="hint" role="status" tabIndex={-1} ref={status}>
        {said}
      </p>
    </details>
  );
}
