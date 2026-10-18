/**
 * Settings > Account's AI assistant key (lib/assistantKey.ts): one line naming the key, its (i), and one button to
 * make (or replace) it; the new key is shown once with Copy, and Remove sits beside a key that exists.
 */
import { useEffect, useState } from "react";
import { InfoButton } from "./SettingRow.tsx";
import { KEY_FAILED, KEY_HELP, KEY_LABEL, KEY_REMOVED, KEY_SHOWN_ONCE, keySummary, makeKey, readKey, removeKey, type KeyInfo } from "./lib/assistantKey.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";

export function AssistantKeySetting({ origin = window.location.origin }: { origin?: string }) {
  const [key, setKey] = useState<KeyInfo | null | undefined>(undefined);
  const [secret, setSecret] = useState<string | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);

  useEffect(() => {
    let live = true;
    void readKey(origin).then((read) => live && setKey(read));
    return () => {
      live = false;
    };
  }, [origin]);

  const make = async () => {
    setBusy(true);
    const made = await makeKey(origin);
    setBusy(false);
    if (!made) return setSaid(KEY_FAILED);
    setKey(made.key);
    setSecret(made.secret);
    setSaid(KEY_SHOWN_ONCE);
  };
  const remove = async () => {
    setBusy(true);
    const done = await removeKey(origin);
    setBusy(false);
    if (!done) return setSaid(KEY_FAILED);
    setKey(null);
    setSecret(null);
    setSaid(KEY_REMOVED);
  };
  const copy = async () => {
    if (!secret) return;
    const copied = await copyText(secret, navigator.clipboard, selectionCopy);
    setSaid(copied ? "Key copied." : "Select the key and copy it.");
  };

  return (
    <section aria-labelledby="settings-assistant-key-heading" className="assistant-key">
      <div className="setting-line">
        <h4 id="settings-assistant-key-heading">
          {KEY_LABEL}
          <span className="setting-value">
            <span className="visually-hidden">: </span>
            {key === undefined ? "…" : keySummary(key)}
          </span>
        </h4>
        <InfoButton open={infoOpen} onToggle={() => setInfoOpen((was) => !was)} controls="settings-assistant-key-info" about={KEY_LABEL} />
      </div>
      <p className="hint setting-info" id="settings-assistant-key-info" hidden={!infoOpen}>
        {KEY_HELP}
      </p>
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
      <p className="hint" role="status">
        {said}
      </p>
    </section>
  );
}
