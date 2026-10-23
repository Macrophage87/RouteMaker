/**
 * Settings > Account's Garmin connection (lib/garminLink.ts): folded to one line, like AI assistants, for the many
 * riders who never use it. Open, it says what connecting does and offers Connect (a link: Garmin's consent is a
 * page) or Disconnect, which asks first. Back from Garmin, it opens by itself and says what happened.
 */
import { useEffect, useState } from "react";
import {
  CONNECT_PATH,
  DISCONNECTED,
  DISCONNECT_ASK,
  FAILED,
  GARMIN_HELP,
  GARMIN_LABEL,
  READ_FAILED,
  disconnectGarmin,
  garminSummary,
  readGarmin,
  type GarminState,
} from "./lib/garminLink.ts";

export function GarminSetting({ origin = window.location.origin, returned = null }: { origin?: string; returned?: string | null }) {
  const [state, setState] = useState<GarminState | null | undefined>(undefined);
  // Empty at first and filled after mount, so a screen reader hears what Garmin's return said: a live region
  // announces changes, not the text it was created with.
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (returned) setSaid(returned);
  }, [returned]);

  useEffect(() => {
    let live = true;
    void readGarmin(origin).then((read) => {
      if (!live) return;
      if (read === undefined) {
        setState(null);
        // Kept beside what the return said, not over it.
        setSaid(returned ? `${returned} ${READ_FAILED}` : READ_FAILED);
      } else setState(read);
    });
    return () => {
      live = false;
    };
  }, [origin, returned]);

  // Nothing to offer and nothing to end (not set up here, not read yet, or not readable): nothing shown. A rider
  // already connected always sees Disconnect, even where Connect is not offered.
  if (!state?.available && !state?.connected && !returned) return null;

  const disconnect = async () => {
    if (!window.confirm(DISCONNECT_ASK)) return;
    setBusy(true);
    const after = await disconnectGarmin(origin);
    setBusy(false);
    if (!after) return setSaid(FAILED);
    setState(after);
    setSaid(DISCONNECTED);
  };

  return (
    <details className="assistant-key garmin-link" open={returned !== null}>
      <summary>
        {GARMIN_LABEL}
        <span className="setting-value">
          <span className="visually-hidden">: </span>
          {garminSummary(state)}
        </span>
      </summary>
      <p className="hint">{GARMIN_HELP}</p>
      {state?.connected ? (
        <div className="assistant-key-actions">
          <button type="button" className="secondary" disabled={busy} onClick={() => void disconnect()}>
            Disconnect
          </button>
        </div>
      ) : (
        state?.available && (
          // A link, as Sign in with Discord is: it leaves for Garmin's page and comes back here.
          <p className="hint sign-in-line">
            <a href={CONNECT_PATH}>Connect Garmin</a>
          </p>
        )
      )}
      <p className="hint" role="status">
        {said}
      </p>
    </details>
  );
}
