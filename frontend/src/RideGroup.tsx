/**
 * A Mass Ride or Group Ride link in Go (v0.7.0 plan; lib/rideGroup.ts has the rules and their tests): the other
 * riders as anonymous dots with a count, the one question about showing your own dot, and the Alert button.
 *
 * Go stays clean: two controls over the map and nothing else. "23 riders on the route" is a button that says the
 * count and the nearest rider ahead on request (not continuously) and holds the key of the roles on the ride, the
 * "Show me as a dot" switch and the rider's role (asked first in the one question, Participant chosen); Alert
 * opens the ride type's list. Alerts come as banners with their age in words, kept live, a pin at the sender's
 * spot, a vibration, and an assertive announcement at once (alerts are essentials, said even at Brief).
 *
 * Privacy: the watch runs only while the rider shares and the page is in front, and stops when it is hidden;
 * a position is sent only within a quarter mile of the route, in a POST body, and kept nowhere on the device.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import { Icon } from "./Icon.tsx";
import type { LonLat } from "./lib/geo.ts";
import { RIDER_LAYERS, ROLE_COLOURS, roleSwatchPoints, showRideDots } from "./lib/rideDotsLayer.ts";
import {
  ALERT_KINDS,
  ALERT_LABEL,
  ALERT_NOTE,
  CALL_911,
  CALL_911_HREF,
  CONFIRM_QUESTION,
  CONSENT_NO,
  CONSENT_NOTE,
  CONSENT_QUESTION,
  CONSENT_YES,
  DEFAULT_ROLE,
  OTHER_MAX,
  POLL_EVERY_MS,
  POST_EVERY_MS,
  RIDE_ROLES,
  ROLE_QUESTION,
  SHARE_STOPPED_SAID,
  alertRefusal,
  alertText,
  clearAlert,
  consentFor,
  countText,
  dotName,
  dotSaid,
  keepConsent,
  leaveRide,
  nearRoute,
  newAlerts,
  project,
  readRide,
  rideId,
  ridersSaid,
  roleKey,
  roleLabel,
  roleOf,
  sendAlert,
  sendPosition,
  shareStop,
  postSoonAfter,
  shownDots,
  type AlertKind,
  type RideAlert,
  type RideConsent,
  type RideLinkType,
  type RideRead,
  type RideRole,
  type ShownDot,
} from "./lib/rideGroup.ts";
import { browserRideEnv, watchRide } from "./lib/rideWatch.ts";

export interface RideGroupProps {
  type: RideLinkType;
  /** The link's points: the ride's identity. */
  points: readonly LonLat[];
  /** The route's line, for "near the route" and "behind you". */
  line: readonly LonLat[];
  getMap: () => MapLibreMap | null;
  /** The rider's position the page already has (Ride mode's, or Use my location), when it has one. */
  here: LonLat | null;
}

const TICK_MS = 5000;

function visible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

export function RideGroup({ type, points, line, getMap, here }: RideGroupProps) {
  const origin = window.location.origin;
  const [ride, setRide] = useState<string | null>(null);
  const [consent, setConsent] = useState<RideConsent | null>(null);
  const [asked, setAsked] = useState(false);
  // The role picked in the question, before it is answered: Participant, so one tap answers.
  const [pickedRole, setPickedRole] = useState<RideRole>(DEFAULT_ROLE);
  const [read, setRead] = useState<RideRead>({ dots: [], alerts: [] });
  const [polledAt, setPolledAt] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  const [fix, setFix] = useState<LonLat | null>(null);
  const [shareOn, setShareOn] = useState(false);
  const [ridersOpen, setRidersOpen] = useState(false);
  const [ridersSaidText, setRidersSaidText] = useState("");
  const [alertOpen, setAlertOpen] = useState(false);
  const [confirming, setConfirming] = useState<AlertKind | null>(null);
  const [otherText, setOtherText] = useState("");
  const [otherOpen, setOtherOpen] = useState(false);
  const [sent, setSent] = useState<number[]>([]);
  const [said, setSaid] = useState({ text: "", count: 0 });
  const [urgent, setUrgent] = useState({ text: "", count: 0 });
  const [dotInfo, setDotInfo] = useState("");
  const share = useRef({ lastNearAt: null as number | null, startedAt: Date.now(), lastPost: 0 });
  const previousAlerts = useRef<RideAlert[]>([]);
  const ridersPanel = useId();
  const alertPanel = useId();
  const say = (text: string) => setSaid((s) => ({ text, count: s.count + 1 }));

  // The ride, and the rider's answer for it (asked when the link opens).
  const key = points.map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`).join(";");
  useEffect(() => {
    let live = true;
    void rideId(type, points).then((id) => {
      if (!live) return;
      setRide(id);
      const kept = consentFor(id);
      setConsent(kept);
      setAsked(kept !== null);
      setShareOn(kept?.answer === "yes");
    });
    return () => {
      live = false;
    };
    // The points' text is the ride's identity; the array itself changes on every render upstream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, key]);

  const answer = (yes: boolean) => {
    if (!ride) return;
    const kept = keepConsent(ride, yes ? "yes" : "no", Date.now(), undefined, undefined, pickedRole);
    setConsent(kept);
    setAsked(true);
    setShareOn(yes);
    share.current = { lastNearAt: null, startedAt: Date.now(), lastPost: 0 };
    say(yes ? `You are shown as a dot, ${roleLabel(kept.role)}, while you are near the route and the app is open.` : "You are not shown. You still see the others.");
  };
  const changeRole = (role: RideRole) => {
    if (!ride || !consent) return;
    setConsent(keepConsent(ride, consent.answer, Date.now(), undefined, undefined, role));
    // The new role goes with the next position as soon as the server takes one (the consent change re-runs the post).
    share.current.lastPost = postSoonAfter(share.current.lastPost);
    say(shareOn ? `You are shown as ${roleLabel(role)}; others see it within 15 seconds.` : `Your role is ${roleLabel(role)}, shown when you turn on Show me as a dot.`);
  };
  const token = consent?.token ?? null;

  // Seeing the others: every 15 s while the page is in front.
  const poll = useCallback(async () => {
    if (!ride || !token || !visible()) return;
    const got = await readRide(origin, ride, token);
    if (!got) return;
    setRead(got);
    setPolledAt(Date.now());
    const fresh = newAlerts(previousAlerts.current, got.alerts);
    previousAlerts.current = got.alerts;
    if (fresh.length) {
      // Essentials: said at once, whatever the announcement level, and felt.
      setUrgent((u) => ({ text: fresh.map((a) => alertText(a, line, myAlongRef.current)).join(" "), count: u.count + 1 }));
      try {
        navigator.vibrate?.([200, 100, 200]);
      } catch {
        // No vibration here.
      }
    }
  }, [ride, token, origin, line]);
  useEffect(() => {
    if (!ride || !token) return;
    void poll();
    const id = window.setInterval(() => void poll(), POLL_EVERY_MS);
    const tick = window.setInterval(() => setNow(Date.now()), TICK_MS);
    const onShow = () => {
      if (visible()) void poll();
    };
    document.addEventListener("visibilitychange", onShow);
    return () => {
      window.clearInterval(id);
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", onShow);
    };
  }, [ride, token, poll]);

  // Sharing your own dot: a position watch only while sharing and in front.
  const [front, setFront] = useState(visible());
  useEffect(() => {
    const onVis = () => setFront(visible());
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);
  useEffect(() => {
    if (!shareOn || !front || !ride || !token) return;
    // Ride mode's one watcher (lib/rideWatch.ts), while sharing and in front only; a refusal turns sharing off.
    const stopWatch = watchRide(browserRideEnv(), (f) => setFix(f.point), (why) => {
      if (why === "denied" || why === "unsupported" || why === "insecure") setShareOn(false);
    });
    return () => {
      stopWatch();
      // In the background, or turned off: the dot goes at once rather than in 2 minutes.
      void leaveRide(origin, ride, token);
    };
  }, [shareOn, front, ride, token, origin]);
  useEffect(() => {
    if (!shareOn || !fix || !ride || !token || !consent) return;
    const t = Date.now();
    const near = nearRoute(line, fix);
    if (near) share.current.lastNearAt = t;
    const stop = shareStop({ on: true, since: consent.since, lastNearAt: share.current.lastNearAt, startedAt: share.current.startedAt }, t);
    if (stop) {
      setShareOn(false);
      if (stop === "ride-over") keepConsent(ride, "no");
      say(SHARE_STOPPED_SAID[stop]);
      return;
    }
    if (near && t - share.current.lastPost >= POST_EVERY_MS) {
      share.current.lastPost = t;
      void sendPosition(origin, ride, token, fix, consent.role);
    }
  }, [fix, now, shareOn, ride, token, consent, line, origin]);

  const me = fix ?? here;
  // On an out-and-back the last place along the route says which pass a position is on (yours, and each dot's).
  const myAlongRef = useRef<number | null>(null);
  const myAlong = me ? project(line, me, myAlongRef.current).alongM : null;
  myAlongRef.current = myAlong;
  const sinceS = Math.max(0, Math.floor((now - polledAt) / 1000));
  const previousDots = useRef<ShownDot[]>([]);
  const dots = useMemo(
    () => shownDots(line, read.dots, sinceS, { previous: previousDots.current, myAlongM: myAlongRef.current }),
    [line, read.dots, sinceS],
  );
  previousDots.current = dots;
  const alerts = read.alerts.filter((a) => a.age_s + sinceS <= 600);
  const roleRows = roleKey(dots);

  // The map: dots and pins, drawn again as they age; a tap on a dot says its age.
  useEffect(() => {
    const map = getMap();
    if (map) showRideDots(map, dots, alerts, sinceS, Math.min(3, Math.max(1, Math.ceil(window.devicePixelRatio || 1))));
  });
  useEffect(() => {
    const map = getMap();
    if (!map) return;
    const onTap = (event: MapLayerMouseEvent) => {
      const f = event.features?.[0];
      const coords = (f?.geometry as { coordinates?: LonLat } | undefined)?.coordinates;
      const age = Number(f?.properties?.age ?? 0);
      if (!coords) return;
      const along = Number(f?.properties?.along);
      const text = dotSaid(age, dotName(roleOf(f?.properties?.role), Number.isFinite(along) ? along : project(line, coords).alongM, myAlongRef.current));
      setDotInfo(text);
      say(text);
    };
    for (const layer of RIDER_LAYERS) map.on("click", layer, onTap);
    return () => {
      for (const layer of RIDER_LAYERS) map.off("click", layer, onTap);
      showRideDots(map, null);
    };
  }, [getMap, line]);

  const send = async (kind: AlertKind) => {
    if (!ride || !token) return;
    const refusal = alertRefusal(sent, Date.now());
    if (refusal) {
      say(refusal);
      return;
    }
    const at = me ?? (await currentPosition());
    if (!at) {
      say("Your location is needed to send an alert; allow it and try again.");
      return;
    }
    const outcome = await sendAlert(origin, ride, token, type, kind.id, otherText, at);
    setConfirming(null);
    setOtherOpen(false);
    if (!outcome.ok) {
      say(outcome.message);
      return;
    }
    setSent((s) => [...s, Date.now()]);
    setAlertOpen(false);
    setOtherText("");
    say(outcome.alert.count > 1 ? `Sent: ${kind.label}. ${outcome.alert.count} riders reported.` : `Sent to everyone on this ride: ${kind.label}.`);
    void poll();
  };
  const pick = (kind: AlertKind) => {
    if (kind.id === "other") setOtherOpen(true);
    else if (kind.confirm) setConfirming(kind);
    else void send(kind);
  };

  if (!ride) return null;
  return (
    <div className="ride-group">
      {!asked && (
        <div className="ride-consent" role="dialog" aria-labelledby="ride-consent-q" aria-describedby="ride-consent-note">
          <p id="ride-consent-q" className="ride-consent-question">
            <strong>{CONSENT_QUESTION}</strong>
          </p>
          <p id="ride-consent-note" className="hint">
            {CONSENT_NOTE}
          </p>
          {/* Compact here (Go's map stays clear): one labelled list, Participant chosen; the panel has the radio buttons. */}
          <label className="ride-role-select">
            {ROLE_QUESTION}{" "}
            <select value={pickedRole} onChange={(e) => setPickedRole(roleOf(e.target.value))}>
              {RIDE_ROLES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <div className="ride-consent-choices">
            <button type="button" onClick={() => answer(true)}>
              {CONSENT_YES}
            </button>
            <button type="button" className="secondary" onClick={() => answer(false)}>
              {CONSENT_NO}
            </button>
          </div>
        </div>
      )}
      <div className="ride-group-bar">
        <button type="button" className="chip ride-riders" aria-expanded={ridersOpen} aria-controls={ridersPanel} onClick={() => {
          setRidersOpen(!ridersOpen);
          if (!ridersOpen) setRidersSaidText(ridersSaid(dots, myAlong));
        }}>
          <Icon name="user" size={18} />
          {countText(dots.length)}
        </button>
        <button type="button" className="chip ride-alert-button" aria-expanded={alertOpen} aria-controls={alertPanel} aria-describedby={`${alertPanel}-note`} onClick={() => setAlertOpen(!alertOpen)}>
          <Icon name="warn" size={18} />
          {ALERT_LABEL}
        </button>
      </div>
      <div id={ridersPanel} className="ride-riders-panel" hidden={!ridersOpen}>
        <p role="status">{ridersSaidText}</p>
        {dotInfo && <p className="hint">{dotInfo}</p>}
        {roleRows.length > 0 && (
          <ul role="list" className="ride-role-key" aria-label="Roles on this ride">
            {roleRows.map((k) => (
              <li key={k.role}>
                <RoleSwatch role={k.role} />
                {k.label} ({k.count})
              </li>
            ))}
          </ul>
        )}
        {consent && (
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={shareOn}
            onClick={() => {
              const next = !shareOn;
              if (!ride) return;
              setConsent(keepConsent(ride, next ? "yes" : "no"));
              setShareOn(next);
              share.current = { lastNearAt: null, startedAt: Date.now(), lastPost: 0 };
              say(next ? "You are shown as a dot while you are near the route." : SHARE_STOPPED_SAID.off);
            }}
          >
            <span className="switch-label">Show me as a dot</span>
            <span className="switch-state" aria-hidden="true">
              {shareOn ? "On" : "Off"}
            </span>
          </button>
        )}
        {consent && <RolePicker name="ride-role" value={consent.role} onChange={changeRole} />}
      </div>
      <div id={alertPanel} className="ride-alert-panel" hidden={!alertOpen}>
        <p id={`${alertPanel}-note`} className="hint">
          {ALERT_NOTE}.
        </p>
        {confirming ? (
          <div role="group" aria-label={CONFIRM_QUESTION}>
            <p>
              <strong>{CONFIRM_QUESTION}</strong> {confirming.label}
            </p>
            <button type="button" onClick={() => void send(confirming)}>
              Send
            </button>
            <button type="button" className="secondary" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        ) : otherOpen ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (otherText.trim()) void send({ id: "other", label: "Other" });
            }}
          >
            <label>
              What is the issue? (up to {OTHER_MAX} characters)
              <input type="text" maxLength={OTHER_MAX} value={otherText} onChange={(e) => setOtherText(e.target.value)} autoFocus />
            </label>
            <button type="submit">Send</button>
            <button type="button" className="secondary" onClick={() => setOtherOpen(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <ul role="list" className="ride-alert-kinds">
            {ALERT_KINDS[type].map((kind) => (
              <li key={kind.id}>
                <button type="button" className="secondary" onClick={() => pick(kind)}>
                  {kind.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {alerts.length > 0 && (
        <ul role="list" className="ride-alert-banners" aria-label="Ride alerts">
          {alerts.map((a) => (
            <li key={a.id} className="ride-alert-banner">
              <Icon name="warn" size={18} />
              <span>{alertText(a, line, myAlong, sinceS)}</span>
              {a.call_911 && (
                <a className="call-911" href={CALL_911_HREF}>
                  {CALL_911}
                </a>
              )}
              {a.mine && ride && token && (
                <button type="button" className="secondary" onClick={() => void clearAlert(origin, ride, token, a.id).then(() => poll())}>
                  Clear
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {said.text}
        {said.count % 2 ? " " : ""}
      </p>
      <p className="visually-hidden" role="alert" aria-live="assertive">
        {urgent.text}
        {urgent.count % 2 ? " " : ""}
      </p>
    </div>
  );
}

/** The rider's role: four real radio buttons, named in words (the colour and shape are the map's). */
function RolePicker({ name, value, onChange }: { name: string; value: RideRole; onChange: (role: RideRole) => void }) {
  const id = useId();
  return (
    <fieldset className="ride-role">
      <legend>{ROLE_QUESTION}</legend>
      {RIDE_ROLES.map((r) => (
        <label key={r.id} className="toggle">
          <input type="radio" name={`${name}-${id}`} value={r.id} checked={value === r.id} onChange={() => onChange(r.id)} />
          <RoleSwatch role={r.id} />
          <span>{r.label}</span>
        </label>
      ))}
    </fieldset>
  );
}

/** A role's mark as the map draws it (lib/rideDotsLayer.ts), for the key and the choice; decoration only. */
function RoleSwatch({ role }: { role: RideRole }) {
  const points = roleSwatchPoints(role);
  const colour = ROLE_COLOURS[role];
  return (
    <svg className="ride-role-swatch" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {points ? (
        <polygon points={points} fill={colour} stroke="#ffffff" strokeWidth="2" strokeLinejoin="round" />
      ) : (
        <circle cx="12" cy="12" r="6.7" fill={colour} stroke="#ffffff" strokeWidth="2" />
      )}
    </svg>
  );
}

/** One position for an alert when the page has none: asked once, never watched. */
function currentPosition(): Promise<LonLat | null> {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve([p.coords.longitude, p.coords.latitude]),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 15_000 },
    );
  });
}
