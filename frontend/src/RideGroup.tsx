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
 *
 * A broadcast (Share ride or Broadcast, Stephen 2026-10-22: "the ride leader is the person who shared. Opening the
 * link will follow the leader and share the path"): the ride is the shared line's id. The sharer leads: shown from
 * the share on, on or off the route (they may re-route), while the page is in front. Those who open the link see
 * the leader at once, without answering the question, and the map follows the leader (until they move the map, or
 * while they ride themselves, when the ride follows them); the leader's path since the link opened is drawn from
 * the dots this page saw, kept in memory here only.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import { Icon } from "./Icon.tsx";
import type { LonLat } from "./lib/geo.ts";
import { LEADER_RING, RIDER_LAYERS, ROLE_COLOURS, roleSwatchPoints, showRideDots } from "./lib/rideDotsLayer.ts";
import {
  ALERT_KINDS,
  ROAM_ALERT_KINDS,
  ALERT_LABEL,
  ALERT_NOTE,
  BROADCAST_CONSENT_NOTE,
  CALL_911,
  CALL_911_HREF,
  CONFIRM_QUESTION,
  CONSENT_NO,
  CONSENT_NOTE,
  CONSENT_QUESTION,
  CONSENT_YES,
  DEFAULT_ROLE,
  FOLLOW_LEADER,
  FOLLOWING_SAID,
  LEADER_LABEL,
  LEADING_SAID,
  NOT_FOLLOWING_SAID,
  OTHER_MAX,
  POLL_EVERY_MS,
  POST_EVERY_MS,
  RIDE_ROLES,
  ROLE_QUESTION,
  SHARE_STOPPED_SAID,
  alertRefusal,
  alertText,
  broadcastRideId,
  roamRideId,
  awayWords,
  clearAlert,
  consentFor,
  countText,
  dotName,
  dotSaid,
  extendTrail,
  keepConsent,
  leaveRide,
  nearRoute,
  newToken,
  PATH_EVERY_MS,
  PATH_MIN_GAP_MS,
  pathDue,
  routeKeyOf,
  sendPath,
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
import { LISTENING_SAID, SPEAK_LABEL, listenOnce, speechSupported } from "./lib/speechInput.ts";

export interface RideGroupProps {
  type: RideLinkType;
  /** The link's points: the ride's identity. */
  points: readonly LonLat[];
  /** The route's line, for "near the route" and "behind you". */
  line: readonly LonLat[];
  getMap: () => MapLibreMap | null;
  /** The rider's position the page already has (Ride mode's, or Use my location), when it has one. */
  here: LonLat | null;
  /**
   * A broadcast ride: the shared line's id, the link's leader key, and whether this page is the sharer's (who leads).
   * Null: a Mass Ride or Group Ride by its points, as before.
   */
  broadcast?: { id: string; lead: string | null; leading: boolean; roam?: boolean } | null;
  /** This page is riding (Ride mode follows the rider, so the map does not follow the leader). */
  riding?: boolean;
  /** The route this page is riding now, re-routes included (the leader sends it to those following). */
  leaderRoute?: readonly LonLat[] | null;
}

const TICK_MS = 5000;

function visible(): boolean {
  return typeof document === "undefined" || document.visibilityState !== "hidden";
}

export function RideGroup({ type, points, line, getMap, here, broadcast = null, riding = false, leaderRoute = null }: RideGroupProps) {
  const leading = broadcast?.leading === true;
  const isBroadcast = broadcast !== null;
  // The leader key a follower reads with (the leader needs none: it does not see its own dot).
  const followKey = broadcast && !leading ? broadcast.lead : null;
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
  // Speak (lib/speechInput.ts): only where the browser turns speech into text; the words fill the box, Send sends.
  const [canSpeak] = useState(() => speechSupported());
  const stopListening = useRef<(() => void) | null>(null);
  const [listening, setListening] = useState(false);
  const speak = () => {
    if (listening) {
      stopListening.current?.();
      return;
    }
    // Said words go after any typed already.
    const typed = otherText.trim();
    const stop = listenOnce(
      (text) => setOtherText(typed ? `${typed} ${text}`.slice(0, OTHER_MAX) : text),
      (failed) => {
        stopListening.current = null;
        abortListening.current = null;
        setListening(false);
        if (failed) say(failed);
      },
      OTHER_MAX,
    );
    if (!stop) return;
    stopListening.current = stop.stop;
    abortListening.current = stop.abort;
    setListening(true);
    say(LISTENING_SAID);
  };
  // Closed or gone: dropped, not finished, so no late words land in a closed box.
  const abortListening = useRef<(() => void) | null>(null);
  useEffect(() => () => abortListening.current?.(), []);
  useEffect(() => {
    if (!otherOpen) abortListening.current?.();
  }, [otherOpen]);
  const [sent, setSent] = useState<number[]>([]);
  const [said, setSaid] = useState({ text: "", count: 0 });
  const [urgent, setUrgent] = useState({ text: "", count: 0 });
  const [dotInfo, setDotInfo] = useState("");
  const share = useRef({ lastNearAt: null as number | null, startedAt: Date.now(), lastPost: 0 });
  // The leader's own ridden path, in memory on this phone (sent with the route while riding).
  const [ownTrail, setOwnTrail] = useState<readonly LonLat[]>([]);
  const previousAlerts = useRef<RideAlert[]>([]);
  const ridersPanel = useId();
  const alertPanel = useId();
  const say = (text: string) => setSaid((s) => ({ text, count: s.count + 1 }));

  // The ride, and the rider's answer for it (asked when the link opens).
  const key = broadcast ? `${broadcast.roam ? "roam" : "broadcast"}|${broadcast.id}` : points.map((p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`).join(";");
  useEffect(() => {
    let live = true;
    void (broadcast ? (broadcast.roam ? roamRideId(broadcast.id) : broadcastRideId(broadcast.id)) : rideId(type, points)).then((id) => {
      if (!live) return;
      setRide(id);
      // The sharer leads: sharing is what they pressed (App.tsx keeps the answer as it shares; kept here too).
      let kept = consentFor(id);
      // A "No" the leader gave later, with Show me as a dot, stands (review: never switched back on by a remount).
      if (leading && kept === null) kept = keepConsent(id, "yes", Date.now(), undefined, undefined, "lead");
      if (leading) window.setTimeout(() => live && say(LEADING_SAID), 150);
      setConsent(kept);
      setAsked(kept !== null);
      setShareOn(kept?.answer === "yes");
      // The question, said once as it shows (a group, not a dialog: the page around it stays usable). Said
      // a moment later: the polite region mounts with the ride, and one mounted with its text is often not read.
      if (kept === null) window.setTimeout(() => live && say(CONSENT_QUESTION), 150);
    });
    return () => {
      live = false;
    };
    // The points' text is the ride's identity; the array itself changes on every render upstream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type, key, leading]);

  const answer = (yes: boolean) => {
    if (!ride) return;
    const kept = keepConsent(ride, yes ? "yes" : "no", Date.now(), undefined, undefined, pickedRole);
    setConsent(kept);
    setAsked(true);
    setShareOn(yes);
    share.current = { lastNearAt: null, startedAt: Date.now(), lastPost: 0 };
    say(yes ? `You are shown as a dot, ${roleLabel(kept.role)}, while ${isBroadcast ? "" : "you are near the route and "}the app is open.` : "You are not shown. You still see the others.");
  };
  const changeRole = (role: RideRole) => {
    if (!ride || !consent) return;
    setConsent(keepConsent(ride, consent.answer, Date.now(), undefined, undefined, role));
    // The new role goes with the next position as soon as the server takes one (the consent change re-runs the post).
    share.current.lastPost = postSoonAfter(share.current.lastPost);
    say(shareOn ? `You are shown as ${roleLabel(role)}; others see it within 15 seconds.` : `Your role is ${roleLabel(role)}, shown when you turn on Show me as a dot.`);
  };
  // A broadcast's follower sees the leader before answering: a token for reading only, which the server keeps
  // nothing of until it posts (core.ride_presence.read).
  const [watchToken] = useState(newToken);
  const token = consent?.token ?? (broadcast ? watchToken : null);

  // Seeing the others: every 15 s while the page is in front.
  const poll = useCallback(async () => {
    if (!ride || !token || !visible()) return;
    const got = await readRide(origin, ride, token, fetch, followKey);
    if (!got) return;
    setRead(got);
    setPolledAt(Date.now());
    const fresh = newAlerts(previousAlerts.current, got.alerts);
    previousAlerts.current = got.alerts;
    if (fresh.length) {
      // Essentials: said at once, whatever the announcement level, and felt.
      setUrgent((u) => ({ text: fresh.map((a) => alertText(a, line, myAlongRef.current, 0, meRef.current)).join(" "), count: u.count + 1 }));
      try {
        navigator.vibrate?.([200, 100, 200]);
      } catch {
        // No vibration here.
      }
    }
  }, [ride, token, origin, line, followKey]);
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
    // On a broadcast everyone shown is shown on or off the route while they ride: those following go where the leader
    // goes, and riders who get separated find each other. Not riding (the ride ended, or watching), the quarter-mile
    // rule and its 10-minute stop are back, so a dot never follows anyone home.
    // A broadcast from Roam has no route: one who said yes is shown while the app is open, riding or not.
    const near = (isBroadcast && (riding || line.length === 0)) || nearRoute(line, fix);
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
    if (leading && near) setOwnTrail((t) => extendTrail(t, fix));
  }, [fix, now, shareOn, ride, token, consent, line, origin, isBroadcast, riding, leading]);

  // The leader's route and ridden path, sent again about every 2 minutes and whenever the route changes (Stephen
  // 2026-10-22: "Rebroadcast the route every 2 min or when it changes, not keeping it on the server"), while riding.
  const pathSent = useRef({ at: 0, routeKey: "" });
  const routeNow = leaderRoute ?? line;
  const routeNowKey = routeKeyOf(routeNow);
  useEffect(() => {
    if (!leading || !riding || !shareOn || !front || !ride || !token) return;
    const t = Date.now();
    if (!pathDue(pathSent.current.at, pathSent.current.routeKey, routeNowKey, t)) return;
    pathSent.current = { at: t, routeKey: routeNowKey };
    // Not taken: tried again in about PATH_MIN_GAP_MS, before the server's 2 minutes run out.
    void sendPath(origin, ride, token, routeNow, ownTrail).then((ok) => {
      if (!ok && pathSent.current.at === t) pathSent.current = { at: t - PATH_EVERY_MS + PATH_MIN_GAP_MS, routeKey: "" };
    });
    // routeNow is named by its key; ownTrail goes with the next send as it is then.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leading, riding, shareOn, front, ride, token, origin, routeNowKey, now]);

  const me = fix ?? here;
  const meRef = useRef<LonLat | null>(null);
  meRef.current = me;
  // A broadcast from Roam has no route: places are said from you in a straight line (lib/rideGroup.ts awayWords).
  const noLine = line.length === 0;
  // On an out-and-back the last place along the route says which pass a position is on (yours, and each dot's).
  const myAlongRef = useRef<number | null>(null);
  const myAlong = me ? project(line, me, myAlongRef.current).alongM : null;
  myAlongRef.current = myAlong;
  const sinceS = Math.max(0, Math.floor((now - polledAt) / 1000));
  const previousDots = useRef<ShownDot[]>([]);
  const dots = useMemo(
    () => shownDots(line, read.dots, sinceS, { previous: previousDots.current, myAlongM: myAlongRef.current, anywhere: isBroadcast }),
    [line, read.dots, sinceS, isBroadcast],
  );
  previousDots.current = dots;
  // An alert lasts 2 minutes (core.ride_presence.ALERT_TTL_S: nothing stays on the server longer).
  const alerts = read.alerts.filter((a) => a.age_s + sinceS <= 120);
  // The key: the ride leader under "Ride leader" only, the others by role (lib/rideGroup.ts roleKey).
  const roleRows = roleKey(dots);
  const leaderInKey = dots.some((d) => d.leader);

  // Following the leader: the leader's dot, the path it has taken since this page opened, and the map kept on it.
  const leaderDot = followKey ? (dots.find((d) => d.leader) ?? null) : null;
  const leaderAt: LonLat | null = leaderDot ? [leaderDot.lon, leaderDot.lat] : null;
  const [trail, setTrail] = useState<readonly LonLat[]>([]);
  const [following, setFollowing] = useState(true);
  const leaderSpot = leaderAt ? `${leaderAt[0]},${leaderAt[1]}` : "";
  // The leader's phone's own route and path (sent every 2 minutes), else the path this page saw.
  const sentPath = followKey ? (read.leaderPath ?? null) : null;
  const shownTrail = sentPath && sentPath.trail.length >= trail.length ? sentPath.trail : trail;
  const shownRoute = sentPath?.route ?? [];
  useEffect(() => {
    if (!leaderAt) return;
    setTrail((t) => extendTrail(t, leaderAt));
    const map = getMap();
    if (following && !riding && map) map.easeTo({ center: leaderAt, duration: 800 });
    // The spot's text is the leader's reading; the array is new each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leaderSpot, following, riding, getMap]);
  const followingRef = useRef(following);
  followingRef.current = following;
  useEffect(() => {
    const map = getMap();
    if (!map || !followKey) return;
    // Moving, zooming or turning the map by hand stops following (a move the page makes has no originalEvent).
    const onMove = (event: { originalEvent?: unknown }) => {
      if (!event.originalEvent || !followingRef.current) return;
      setFollowing(false);
      say(NOT_FOLLOWING_SAID);
    };
    const kinds = ["dragstart", "zoomstart", "rotatestart"] as const;
    for (const kind of kinds) map.on(kind, onMove);
    return () => {
      for (const kind of kinds) map.off(kind, onMove);
    };
    // Tried again once the leader shows, where the map was not there at first.
  }, [getMap, followKey, leaderSpot !== ""]);

  // The map: dots and pins, drawn again as they age; a tap on a dot says its age.
  useEffect(() => {
    const map = getMap();
    if (map) showRideDots(map, dots, alerts, sinceS, Math.min(3, Math.max(1, Math.ceil(window.devicePixelRatio || 1))), shownTrail, shownRoute);
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
      const isLeader = f?.properties?.leader === true || f?.properties?.leader === "true";
      const away = line.length === 0 ? awayWords(meRef.current, coords) : undefined;
      const text = dotSaid(age, dotName(roleOf(f?.properties?.role), Number.isFinite(along) ? along : project(line, coords).alongM, myAlongRef.current, isLeader, away));
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
        <div className="ride-consent" role="group" aria-labelledby="ride-consent-q" aria-describedby="ride-consent-note">
          <p id="ride-consent-q" className="ride-consent-question">
            <strong>{CONSENT_QUESTION}</strong>
          </p>
          <p id="ride-consent-note" className="hint">
            {broadcast ? BROADCAST_CONSENT_NOTE : CONSENT_NOTE}
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
        <button type="button" className="chip ride-riders" aria-expanded={ridersOpen} data-idle-close aria-controls={ridersPanel} onClick={() => {
          setRidersOpen(!ridersOpen);
          if (!ridersOpen) setRidersSaidText(ridersSaid(dots, myAlong, noLine ? { here: me } : null));
        }}>
          <Icon name="user" size={18} />
          {countText(dots.length, !noLine)}
        </button>
        <button type="button" className="chip ride-alert-button" aria-expanded={alertOpen} data-idle-close aria-controls={alertPanel} aria-describedby={`${alertPanel}-note`} onClick={() => setAlertOpen(!alertOpen)}>
          <Icon name="warn" size={18} />
          {ALERT_LABEL}
        </button>
      </div>
      <div id={ridersPanel} className="ride-riders-panel" hidden={!ridersOpen}>
        <p role="status">{ridersSaidText}</p>
        {dotInfo && <p className="hint">{dotInfo}</p>}
        {followKey && (
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={following}
            onClick={() => {
              const next = !following;
              setFollowing(next);
              say(next ? FOLLOWING_SAID : NOT_FOLLOWING_SAID);
            }}
          >
            <span className="switch-label">{FOLLOW_LEADER}</span>
            <span className="switch-state" aria-hidden="true">
              {following ? "On" : "Off"}
            </span>
          </button>
        )}
        {(leaderInKey || roleRows.length > 0) && (
          <ul role="list" className="ride-role-key" aria-label="Roles on this ride">
            {leaderInKey && (
              <li>
                <LeaderSwatch />
                {LEADER_LABEL}
              </li>
            )}
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
              say(next ? (isBroadcast ? "You are shown as a dot while the app is open." : "You are shown as a dot while you are near the route.") : SHARE_STOPPED_SAID.off);
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
            {canSpeak && (
              <button type="button" className="secondary ride-speak" aria-pressed={listening} onClick={speak} data-idle-hold={listening || undefined}>
                <Icon name="mic" size={18} />
                {SPEAK_LABEL}
              </button>
            )}
            <button type="submit">Send</button>
            <button type="button" className="secondary" onClick={() => setOtherOpen(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <ul role="list" className="ride-alert-kinds">
            {(broadcast?.roam ? ROAM_ALERT_KINDS : ALERT_KINDS[type]).map((kind) => (
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
              <span>{alertText(a, line, myAlong, sinceS, me)}</span>
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

/** The leader's ring as the map draws it; decoration only. */
function LeaderSwatch() {
  return (
    <svg className="ride-role-swatch" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9.5" fill="#ffffff" stroke={LEADER_RING} strokeWidth="3" />
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
