/**
 * Settings > Account's AI assistants (lib/assistantKey.ts): the AI assistant key, and the apps connected through the
 * site's own connector, each with Disconnect (the owner, 2026-10-19). Folded to one line so Settings stays short for
 * the many riders who never use it. Open, it says what the key does and offers one button to make (or
 * replace) it; the new key is shown once with Copy, and Remove sits beside a key that exists. Replacing or removing
 * asks first: either stops an assistant that uses the key.
 */
import { useEffect, useState } from "react";
import {
  APPS_HEADING,
  APPS_HELP,
  APPS_NONE,
  DISCONNECT_ASK,
  DISCONNECTED,
  KEY_FAILED,
  KEY_HELP,
  KEY_LABEL,
  KEY_READ_FAILED,
  KEY_REMOVED,
  KEY_SHOWN_ONCE,
  REMOVE_ASK,
  REPLACE_ASK,
  appSummary,
  assistantsSummary,
  disconnectApp,
  makeKey,
  readApps,
  readKey,
  removeKey,
  type ConnectedApp,
  type KeyInfo,
} from "./lib/assistantKey.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";

export function AssistantKeySetting({ origin = window.location.origin }: { origin?: string }) {
  const [key, setKey] = useState<KeyInfo | null | undefined>(undefined);
  const [secret, setSecret] = useState<string | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const [unread, setUnread] = useState(false);
  const [apps, setApps] = useState<ConnectedApp[]>([]);

  useEffect(() => {
    let live = true;
    void readApps(origin).then((read) => {
      if (live && read) setApps(read);
    });
    void readKey(origin).then((read) => {
      if (!live) return;
      if (read === undefined) {
        // Not read (offline, or too many requests): offer Make a key all the same, and say so.
        setUnread(true);
        setSaid(KEY_READ_FAILED);
        setKey(null);
      } else setKey(read);
    });
    return () => {
      live = false;
    };
  }, [origin]);

  const make = async () => {
    if ((key || unread) && !window.confirm(REPLACE_ASK)) return;
    setBusy(true);
    const made = await makeKey(origin);
    setBusy(false);
    if (!made) return setSaid(KEY_FAILED);
    setKey(made.key);
    setUnread(false);
    setSecret(made.secret);
    setSaid(KEY_SHOWN_ONCE);
  };
  const remove = async () => {
    if (!window.confirm(REMOVE_ASK)) return;
    setBusy(true);
    const done = await removeKey(origin);
    setBusy(false);
    if (!done) return setSaid(KEY_FAILED);
    setKey(null);
    setSecret(null);
    setSaid(KEY_REMOVED);
  };
  const disconnect = async (app: ConnectedApp) => {
    if (!window.confirm(DISCONNECT_ASK)) return;
    setBusy(true);
    const left = await disconnectApp(origin, app.id);
    setBusy(false);
    if (!left) return setSaid(KEY_FAILED);
    setApps(left);
    setSaid(DISCONNECTED);
  };
  const copy = async () => {
    if (!secret) return;
    const copied = await copyText(secret, navigator.clipboard, selectionCopy);
    setSaid(copied ? "Key copied." : "Select the key and copy it.");
  };

  return (
    <details className="assistant-key">
      <summary>
        {KEY_LABEL}
        <span className="setting-value">
          <span className="visually-hidden">: </span>
          {key === undefined ? "…" : assistantsSummary(key, apps)}
        </span>
      </summary>
      <p className="hint">{KEY_HELP}</p>
      {secret && (
        <div className="assistant-key-secret">
          <input type="text" readOnly value={secret} aria-label="Your new AI assistant key" onFocus={(e) => e.currentTarget.select()} />
          <button type="button" className="secondary" onClick={() => void copy()}>
            Copy
          </button>
        </div>
      )}
      <div className="assistant-key-actions">
        <button type="button" className="secondary" disabled={busy || key === undefined} onClick={() => void make()}>
          {key ? "Replace key" : "Make a key"}
        </button>
        {key && (
          <button type="button" className="secondary" disabled={busy} onClick={() => void remove()}>
            Remove
          </button>
        )}
      </div>
      <h4 className="assistant-apps-heading">{APPS_HEADING}</h4>
      <p className="hint">{APPS_HELP}</p>
      {apps.length === 0 ? (
        <p className="hint">{APPS_NONE}</p>
      ) : (
        <ul className="assistant-apps">
          {apps.map((app) => (
            <li key={app.id}>
              <span>{appSummary(app)}</span>
              <button type="button" className="secondary" disabled={busy} aria-label={`Disconnect ${app.name}`} onClick={() => void disconnect(app)}>
                Disconnect
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="hint" role="status">
        {said}
      </p>
    </details>
  );
}
