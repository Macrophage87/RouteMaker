/**
 * Settings > Account's Garmin and Wahoo connections (lib/garminLink.ts, lib/wahooLink.ts): each folded to one line,
 * like AI assistants, for the many riders who never use them. Open, it says what connecting does and offers Connect
 * (a link: the service's consent is a page) or Disconnect, which asks first. Back from the service, it opens by
 * itself and says what happened.
 */
import { useEffect, useState } from "react";
import * as garminLink from "./lib/garminLink.ts";
import * as wahooLink from "./lib/wahooLink.ts";
import { t } from "./lib/i18n.ts";

/** What one service's line needs: its words, where Connect goes, and its two requests. */
interface Service {
  label: string;
  help: string;
  connectPath: string;
  disconnectAsk: string;
  disconnected: string;
  readFailed: string;
  className: string;
  read: (origin: string) => Promise<garminLink.GarminState | undefined>;
  disconnect: (origin: string) => Promise<garminLink.GarminState | null>;
}

const GARMIN: Service = {
  label: garminLink.GARMIN_LABEL,
  help: garminLink.GARMIN_HELP,
  connectPath: garminLink.CONNECT_PATH,
  disconnectAsk: garminLink.DISCONNECT_ASK,
  disconnected: garminLink.DISCONNECTED,
  readFailed: garminLink.READ_FAILED,
  className: "garmin-link",
  read: (origin) => garminLink.readGarmin(origin),
  disconnect: (origin) => garminLink.disconnectGarmin(origin),
};

const WAHOO: Service = {
  label: wahooLink.WAHOO_LABEL,
  help: wahooLink.WAHOO_HELP,
  connectPath: wahooLink.CONNECT_PATH,
  disconnectAsk: wahooLink.DISCONNECT_ASK,
  disconnected: wahooLink.DISCONNECTED,
  readFailed: wahooLink.READ_FAILED,
  className: "garmin-link wahoo-link",
  read: (origin) => wahooLink.readWahoo(origin),
  disconnect: (origin) => wahooLink.disconnectWahoo(origin),
};

type Props = { origin?: string; returned?: string | null };

export function GarminSetting(props: Props) {
  return <ConnectionSetting service={GARMIN} {...props} />;
}

export function WahooSetting(props: Props) {
  return <ConnectionSetting service={WAHOO} {...props} />;
}

function ConnectionSetting({ service, origin = window.location.origin, returned = null }: Props & { service: Service }) {
  const [state, setState] = useState<garminLink.GarminState | null | undefined>(undefined);
  // Empty at first and filled after mount, so a screen reader hears what the service's return said: a live region
  // announces changes, not the text it was created with.
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (returned) setSaid(returned);
  }, [returned]);

  useEffect(() => {
    let live = true;
    void service.read(origin).then((read) => {
      if (!live) return;
      if (read === undefined) {
        setState(null);
        // Kept beside what the return said, not over it.
        setSaid(returned ? `${returned} ${service.readFailed}` : service.readFailed);
      } else setState(read);
    });
    return () => {
      live = false;
    };
  }, [service, origin, returned]);

  // Nothing to offer and nothing to end (not set up here, not read yet, or not readable): nothing shown. A rider
  // already connected always sees Disconnect, even where Connect is not offered.
  if (!state?.available && !state?.connected && !returned) return null;

  const disconnect = async () => {
    if (!window.confirm(service.disconnectAsk)) return;
    setBusy(true);
    const after = await service.disconnect(origin);
    setBusy(false);
    if (!after) return setSaid(garminLink.FAILED);
    setState(after);
    setSaid(service.disconnected);
  };

  return (
    <details className={`assistant-key ${service.className}`} open={returned !== null}>
      <summary>
        {service.label}
        <span className="setting-value">
          <span className="visually-hidden">: </span>
          {garminLink.garminSummary(state)}
        </span>
      </summary>
      <p className="hint">{service.help}</p>
      {state?.connected ? (
        <div className="assistant-key-actions">
          <button type="button" className="secondary" disabled={busy} onClick={() => void disconnect()}>
            {t("Disconnect")}
          </button>
        </div>
      ) : (
        state?.available && (
          // A link, as Sign in with Discord is: it leaves for the service's page and comes back here.
          <p className="hint sign-in-line">
            <a href={service.connectPath}>{t("Connect {service}", { service: service.label })}</a>
          </p>
        )
      )}
      <p className="hint" role="status">
        {said}
      </p>
    </details>
  );
}
