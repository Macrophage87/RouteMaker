/**
 * Roam (lib/roam.ts; the owner, 2026-10-22: "Add a free ride mode on go. Basically just show the map and the roads
 * upcoming. Let people detour still to bathroom food water etc", "or call it roam"): a ride with no destination,
 * started from Go's one Roam button while Go has none.
 *
 * - The map follows the rider, track-up as a ride's does (App's follow and heading-up, shared with Ride mode).
 * - The card: the road the rider is on and the next roads ahead, each with its stress level as the map colours it,
 *   read from the map's own tiles on the phone. Fewer words on screen; a screen reader and the voice hear the road
 *   as it changes, in whole words.
 * - The side buttons: Where am I? (re-centring), Detour (water, restroom, food, repair or a search: the three nearest by bike, each with
 *   Ride here, which starts an ordinary ride there; ending that ride comes back to Roam), and the compass.
 * - End roam, slid as End ride is, so a bump does not end it.
 *
 * Privacy (the owner, 2026-10-22: nothing kept on the server): the position stays on the phone. Only a Detour search
 * (POST /api/nearest) and the ride it starts send where the rider is, in a POST body, as Ride mode's detours do; and
 * while the rider broadcasts, the position and trail go to /api/rides as any broadcast's do, kept 2 minutes there.
 */
import { NOTHING_DISMISSED, RIDE_WEATHER_MS, alertKey, alertSaid, alertUrgent, dismissWeather, newAlerts, rainLine, rainSays, rainStage, roamPoints, weatherToShow } from "./lib/weather.ts";
import { useWeather } from "./useWeather.ts";
import { WeatherLines } from "./WeatherLines.tsx";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon.tsx";
import { LiveRegion, SlideToEnd, rideVoice } from "./RideMode.tsx";
import { currentTiers } from "./stressStyle.js";
import { useStressStyle } from "./useStressStyle.ts";
import { haversineM, type LonLat } from "./lib/geo.ts";
import type { FoodPlace } from "./lib/food.ts";
import type { Dials } from "./lib/dials.ts";
import type { PresetId } from "./lib/presets.ts";
import type { WaterPoint } from "./lib/waterRestrooms.ts";
import { WATER_CAUTION } from "./lib/waterRestrooms.ts";
import { LOCATE_MESSAGES } from "./lib/geolocation.ts";
import type { RideFix } from "./lib/navigate.ts";
import { ScreenWake, toScreenReader, type RidePrefs } from "./lib/rideOutput.ts";
import { WAITING_FOR_GPS, watchRide, type RideGeoEnv } from "./lib/rideWatch.ts";
import { rideGeoEnv, rideWake, speaksAloud } from "./lib/nativeShell.ts";
import { NO_FIX_YET, STILL_SEARCHING, nearbyShort, requestNearest, type Nearby, type NearestPlace } from "./lib/nearest.ts";
import {
  DETOUR_CHOICES,
  DETOUR_SEARCH_BUTTON,
  DETOUR_SEARCH_HINT,
  DETOUR_SEARCH_LABEL,
  DETOUR_SUMMARY,
  detourFindingSaid,
  findDetour,
  type DetourAsk,
  type DetourDeps,
  type DetourFound,
} from "./lib/detourSearch.ts";
import type { RepairPlace } from "./lib/repair.ts";
import {
  END_ROAM_NAME,
  NO_NAMED_ROAD,
  NO_ROAD_YET,
  ROAM_DETOUR_HELP,
  ROAM_BROADCAST_NAME,
  ROAM_NAME,
  aheadSaid,
  aheadShown,
  HeadingTrack,
  mapLines,
  onRoadSaid,
  roadsAhead,
  roamLight,
  roamTier,
  type RoadsAhead,
  type RoamMap,
} from "./lib/roam.ts";

/** No repair stands or place search given (a test's roam): those detours say they are unavailable. */
const noPlaces = async () => null;
const noSearch: DetourDeps["geocode"] = async () => ({ ok: false, status: 0 });

/** How often the card is worked out again at most, and how far the rider moves before it is anyway. */
const AHEAD_EVERY_MS = 2_000;
const AHEAD_MOVED_M = 15;
/** A new road is said once it has been the road for this many readings in a row (GPS wanders at a junction). */
const SAME_READINGS = 2;

/** The level's swatch, in the map's colours (a shape and its words too: never colour alone). */
function TierBadge({ tier }: { tier: number | null }) {
  useStressStyle();
  const words = roamTier(tier);
  if (!words) return null;
  const look = (currentTiers() as Array<{ tier: number; color: string; casing: string }>).find((t) => t.tier === tier);
  return (
    <span className="roam-tier">
      <span className="roam-swatch" aria-hidden="true" style={look ? { background: look.color, borderColor: look.casing } : undefined} />
      {words}
    </span>
  );
}

export function RoamMode({
  getMap,
  prefs,
  follow,
  onFollow,
  headingUp,
  onHeadingUp,
  preset,
  dials,
  water,
  food,
  repair = noPlaces,
  geocode = noSearch,
  onView,
  onDetour,
  onEnd,
  onBroadcast = null,
  broadcasting = false,
  geoEnv,
}: {
  getMap: () => RoamMap | null;
  prefs: RidePrefs;
  follow: boolean;
  onFollow: (on: boolean) => void;
  headingUp: boolean;
  onHeadingUp: (on: boolean) => void;
  /** The ride type and settings Go has: a detour's search and its ride use them. */
  preset: PresetId;
  dials: Dials;
  water: () => Promise<WaterPoint[] | null>;
  food: () => Promise<FoodPlace[] | null>;
  /** The repair stands and bike shops, loaded if they are not yet; for the detours. */
  repair?: () => Promise<RepairPlace[] | null>;
  /** The place search, through the page's one geocoding gate; for Detour's search box. */
  geocode?: DetourDeps["geocode"];
  /** The rider, for the map's arrow, accuracy circle and follow camera. */
  onView: (rider: { point: LonLat; headingDeg: number | null; accuracyM: number } | null) => void;
  /** Ride here: a ride from `here` to the place starts; null, else the words to say why not. */
  onDetour: (here: LonLat, place: NearestPlace) => Promise<string | null>;
  onEnd: () => void;
  /** Broadcast (Stephen 2026-10-22): opens the share sheet with a link others follow; answers what to say. Null where
   * this browser has no share sheet. */
  onBroadcast?: (() => Promise<string>) | null;
  /** The rider leads a broadcast now. */
  broadcasting?: boolean;
  geoEnv?: RideGeoEnv;
}) {
  const env = useRef(geoEnv ?? rideGeoEnv()).current;
  const wake = useRef(new ScreenWake(rideWake())).current;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const whereRef = useRef<HTMLButtonElement>(null);
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const [fix, setFix] = useState<RideFix | null>(null);
  const fixRef = useRef<RideFix | null>(null);
  const [gps, setGps] = useState<string>(WAITING_FOR_GPS);
  const [roads, setRoads] = useState<RoadsAhead | null>(null);
  const [heading, setHeading] = useState<number | null>(null);
  const [polite, setPolite] = useState({ text: "", count: 0 });
  const [toast, setToast] = useState("");

  // Said through the rider's outputs (Settings > Ride mode): the screen reader's region, the voice, or both.
  // `urgent` interrupts the voice (an Extreme or Severe weather warning).
  const say = useCallback((text: string, urgent = false) => {
    if (!text) return;
    const output = prefsRef.current.output;
    if (toScreenReader(output) || output === "neither") setPolite((s) => ({ text, count: s.count + 1 }));
    if (speaksAloud(output, document.visibilityState === "hidden")) rideVoice.speak(text, urgent);
  }, []);
  const answer = useCallback(
    (text: string) => {
      setToast(text);
      say(text);
    },
    [say],
  );
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 6_000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // The watch and the screen kept on, from the Roam press to End roam (or a detour's ride, which has its own).
  useEffect(() => {
    const stop = watchRide(
      env,
      (next) => {
        fixRef.current = next;
        setFix(next);
        setGps("");
      },
      (reason) => setGps(reason === "timeout" ? WAITING_FOR_GPS : LOCATE_MESSAGES[reason]),
    );
    void wake.hold();
    headingRef.current?.focus();
    return () => {
      stop();
      void wake.letGo();
    };
  }, [env, wake]);

  // The rider on the map, and the roads ahead worked out again as they move (at most every AHEAD_EVERY_MS).
  const last = useRef<{ at: number; point: LonLat } | null>(null);
  const pending = useRef<{ name: string | null; count: number }>({ name: null, count: 0 });
  const saidRoad = useRef<string | null | undefined>(undefined);
  // The heading kept between fixes that give none (lib/roam.ts HeadingTrack), so the card and the arrow hold steady.
  const track = useRef(new HeadingTrack()).current;
  useEffect(() => {
    if (!fix) return;
    const h = track.step(fix.point, fix.headingDeg);
    setHeading(h);
    onView({ point: fix.point, headingDeg: h, accuracyM: fix.accuracyM });
    const was = last.current;
    if (was && fix.at - was.at < AHEAD_EVERY_MS && haversineM(was.point, fix.point) < AHEAD_MOVED_M) return;
    last.current = { at: fix.at, point: fix.point };
    const map = getMap();
    if (!map) return;
    const lines = mapLines(map, fix.point);
    const found = roadsAhead(fix.point, h, lines.roads, lines.stress);
    setRoads(found);
    // A new road is said once it holds (GPS wanders at a junction), with what is ahead on it.
    const name = found.on?.name ?? null;
    pending.current = pending.current.name === name ? { name, count: pending.current.count + 1 } : { name, count: 1 };
    if (pending.current.count >= SAME_READINGS && saidRoad.current !== name) {
      saidRoad.current = name;
      say([onRoadSaid(found.on), aheadSaid(found.ahead)].filter(Boolean).join(" "));
    }
  }, [fix, getMap, onView, say, track]);
  useEffect(() => () => onView(null), [onView]);

  // Where am I? (as Ride mode's): the road and the roads ahead said now, and the map following again.
  const whereAmI = () => {
    onFollow(true);
    if (!fixRef.current) {
      answer(gps || WAITING_FOR_GPS);
      return;
    }
    answer([onRoadSaid(roads?.on ?? null), aheadSaid(roads?.ahead ?? [])].filter(Boolean).join(" "));
  };

  // Detour (Ride mode's: water, restroom, food, repair and a search box, lib/detourSearch.ts): the three nearest by
  // bike, then Ride here.
  const detourId = useId();
  const [detourOpen, setDetourOpen] = useState(false);
  const detourButton = useRef<HTMLButtonElement>(null);
  const detourHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (detourOpen) detourHeading.current?.focus();
  }, [detourOpen]);
  const [detourStatus, setDetourStatus] = useState("");
  const [found, setFound] = useState<DetourFound | null>(null);
  const [query, setQuery] = useState("");
  const busy = useRef(false);
  // Ended (End roam, or a detour's ride started): a search answering late says and shows nothing.
  const gone = useRef(false);
  useEffect(() => {
    gone.current = false;
    return () => {
      gone.current = true;
    };
  }, []);
  const sayDetour = (text: string) => {
    if (gone.current) return;
    setDetourStatus(text);
    say(text);
  };
  const find = async (ask: DetourAsk) => {
    if (busy.current) {
      sayDetour(STILL_SEARCHING);
      return;
    }
    const here = fixRef.current;
    if (!here) {
      sayDetour(NO_FIX_YET);
      return;
    }
    busy.current = true;
    setFound(null);
    sayDetour(detourFindingSaid(ask));
    try {
      const outcome = await findDetour(
        {
          here: here.point,
          water,
          food,
          repair,
          geocode,
          request: (from: LonLat, places: readonly NearestPlace[]) => requestNearest(from, places, preset, { ...dials, loop: false }),
        },
        ask,
      );
      if (gone.current) return;
      if (outcome.found) setFound(outcome.found);
      sayDetour(outcome.said);
    } finally {
      busy.current = false;
    }
  };
  const rideThere = async (item: Nearby) => {
    const here = fixRef.current?.point;
    if (!here) {
      sayDetour(NO_FIX_YET);
      return;
    }
    if (busy.current) {
      sayDetour(STILL_SEARCHING);
      return;
    }
    busy.current = true;
    sayDetour(`Finding a way to ${item.place.title}.`);
    try {
      const why = await onDetour(here, item.place);
      if (why) sayDetour(why);
    } finally {
      busy.current = false;
    }
  };

  // Sunrise and sunset (Stephen 2026-10-22: "Also add sunrise and sunset"): the next of each at the rider, in the
  // heading's corner as Ride mode shows them, worked out again each minute.
  const [minute, setMinute] = useState(() => Math.floor(Date.now() / 60_000));
  useEffect(() => {
    const timer = window.setInterval(() => setMinute(Math.floor(Date.now() / 60_000)), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const lightAt = fix ? `${fix.point[0].toFixed(2)},${fix.point[1].toFixed(2)}` : null;
  const light = useMemo(() => {
    if (lightAt === null) return null;
    const [lon, lat] = lightAt.split(",").map(Number);
    return roamLight(minute * 60_000, [lon, lat]);
  }, [lightAt, minute]);

  // Weather where the rider is (lib/weather.ts, Stephen 2026-10-24), as a ride checks it: every 5 minutes, a new NWS
  // alert or rain coming said and shown under the roads ahead until dismissed.
  const weather = useWeather(
    fix ? "roam" : null,
    () => (fixRef.current ? roamPoints(fixRef.current.point) : null),
    RIDE_WEATHER_MS,
  );
  const weatherSaid = useRef({ alerts: new Set<string>(), rain: "" });
  const [weatherDismissed, setWeatherDismissed] = useState(NOTHING_DISMISSED);
  useEffect(() => {
    if (!weather) return;
    const said = weatherSaid.current;
    const fresh = newAlerts(weather, said.alerts);
    for (const alert of fresh) {
      said.alerts.add(alertKey(alert));
      say(alertSaid(alert, Date.now()), alertUrgent(alert));
    }
    if (rainSays(said.rain, weather.rain) && weather.rain) say(rainLine(weather.rain, weather.alongM, true));
    said.rain = rainStage(weather.rain);
  }, [weather, say]);
  const weatherShown = weatherToShow(weather, weatherDismissed);

  const broadcastBusy = useRef(false);
  const broadcast = async () => {
    if (!onBroadcast || broadcastBusy.current) return;
    broadcastBusy.current = true;
    try {
      const said = await onBroadcast();
      if (said && !gone.current) answer(said);
    } finally {
      broadcastBusy.current = false;
    }
  };

  // A broadcast's riders and Alert sit just under the card, never over the road names (its height changes as they do).
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const card = cardRef.current;
    const app = card?.closest<HTMLElement>(".app");
    if (!card || !app || typeof ResizeObserver === "undefined") return;
    const place = () => app.style.setProperty("--roam-card-bottom", `${Math.round(card.getBoundingClientRect().bottom - app.getBoundingClientRect().top)}px`);
    const watch = new ResizeObserver(place);
    watch.observe(card);
    place();
    return () => {
      watch.disconnect();
      app.style.removeProperty("--roam-card-bottom");
    };
  }, []);

  const slideHint = () => answer(`Slide ${END_ROAM_NAME} to the right to end it.`);
  const on = roads?.on ?? null;
  return (
    <section className="ride roam" aria-labelledby="ride-heading">
      <LiveRegion said={polite} urgent={false} />
      <div ref={cardRef} className="cue-card">
        <div className="ride-top">
          <h2 id="ride-heading" ref={headingRef} tabIndex={-1} className={light ? "ride-heading ride-light" : "ride-heading"}>
            {light ? (
              <>
                <span className="visually-hidden">{ROAM_NAME}</span>
                <span className="ride-light-lines" aria-hidden="true">
                  {light.shown.map((line) => (
                    <span key={line}>{line}</span>
                  ))}
                </span>
              </>
            ) : (
              ROAM_NAME
            )}
          </h2>
          {light && <p className="visually-hidden">{light.said}</p>}
          <div className="ride-top-actions">
            <SlideToEnd onEnd={onEnd} onTap={slideHint} name={END_ROAM_NAME} />
          </div>
        </div>
        {gps && <p className="hint ride-gps">{gps}</p>}
        <div className="roam-now">
          {/* The road ridden large; its level beside it, in the map's colours and its words. */}
          <p className="cue-text roam-road">
            {roads === null ? NO_ROAD_YET : on ? on.name : NO_NAMED_ROAD}
            {on && <TierBadge tier={on.tier} />}
          </p>
          {roads !== null && roads.ahead.length > 0 && (
            <ol className="roam-ahead" aria-label="Roads ahead">
              {roads.ahead.map((road) => (
                <li key={road.name}>
                  <span className="roam-ahead-name">{road.name}</span>
                  <span className="roam-ahead-far">{aheadShown(road)}</span>
                  <TierBadge tier={road.tier} />
                </li>
              ))}
            </ol>
          )}
          {roads !== null && heading === null && <p className="cue-more">Start riding to see the roads ahead.</p>}
          <WeatherLines report={weatherShown} riding now={Date.now()} onDismiss={() => setWeatherDismissed((d) => dismissWeather(weatherShown, d))} />
        </div>
      </div>
      <div className="ride-middle">
        <button type="button" className="ride-compass" aria-pressed={!headingUp} aria-label="North up" title="North up" onClick={() => onHeadingUp(!headingUp)}>
          <svg viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">
            <path d="M20 5 L25 20 L20 17 L15 20 Z" className="ride-compass-north" />
            <path d="M20 35 L15 20 L20 23 L25 20 Z" className="ride-compass-south" />
          </svg>
        </button>
        {toast && !detourOpen && (
          <div className="ride-toast">
            <p>{toast}</p>
          </div>
        )}
        <div className="ride-rail" role="group" aria-label="Roam buttons">
          <button
            type="button"
            ref={whereRef}
            className={`ride-round${follow ? "" : " ride-round-alert"}`}
            onClick={whereAmI}
            aria-label={follow ? "Where am I?" : "Where am I? The map stopped following you"}
            title="Where am I?"
          >
            <Icon name="locate" size={24} />
          </button>
          {onBroadcast && (
            <button
              type="button"
              className={`ride-round${broadcasting ? " ride-round-on" : ""}`}
              onClick={() => void broadcast()}
              aria-label={broadcasting ? `${ROAM_BROADCAST_NAME}: on. Share the link again` : `${ROAM_BROADCAST_NAME}: share a link others follow you with`}
              title={ROAM_BROADCAST_NAME}
            >
              <Icon name="broadcast" size={24} />
            </button>
          )}
          <div
            className="ride-pop ride-detour"
            onKeyDown={(event) => {
              if (event.key === "Escape" && detourOpen) {
                event.preventDefault();
                setDetourOpen(false);
                detourButton.current?.focus();
              }
            }}
          >
            <button
              type="button"
              ref={detourButton}
              className="ride-round"
              aria-label={`Detour: ${DETOUR_SUMMARY.toLowerCase()}`}
              title="Detour"
              aria-expanded={detourOpen}
              aria-controls={detourId}
              onClick={() => setDetourOpen(!detourOpen)}
            >
              <Icon name="detour" size={24} />
            </button>
            <div id={detourId} className="ride-menu" role="group" aria-labelledby={`${detourId}-heading`} hidden={!detourOpen}>
              <div className="ride-menu-head">
                <h3 id={`${detourId}-heading`} ref={detourHeading} tabIndex={-1}>
                  Detour
                </h3>
                <button
                  type="button"
                  className="secondary ride-menu-close"
                  onClick={() => {
                    setDetourOpen(false);
                    detourButton.current?.focus();
                  }}
                >
                  Close
                </button>
              </div>
              <div className="actions nearest-kinds">
                {DETOUR_CHOICES.map(({ kind, label, icon }) => (
                  <button key={kind} type="button" className="secondary" onClick={() => void find({ kind })}>
                    <Icon name={icon} size={20} />
                    {label}
                  </button>
                ))}
              </div>
              <form
                className="detour-search"
                role="search"
                onSubmit={(event) => {
                  event.preventDefault();
                    // The focus moves to Find, so a phone's keyboard goes and does not cover the list that comes.
                    event.currentTarget.querySelector<HTMLButtonElement>("button[type=submit]")?.focus();
                  void find({ query });
                }}
              >
                <label htmlFor={`${detourId}-search`}>{DETOUR_SEARCH_LABEL}</label>
                <span className="detour-search-row">
                  <input
                    id={`${detourId}-search`}
                    type="search"
                    enterKeyHint="search"
                    autoComplete="off"
                    placeholder={DETOUR_SEARCH_HINT}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                  <button type="submit" className="secondary">
                    <Icon name="search" size={20} />
                    {DETOUR_SEARCH_BUTTON}
                  </button>
                </span>
              </form>
              <p className="hint nearest-status">{detourStatus}</p>
              {found && found.items.length > 0 && (
                <div className="nearest-list">
                  <h4 id={`${detourId}-found`}>{found.heading}</h4>
                  <ol role="list" aria-labelledby={`${detourId}-found`}>
                    {found.items.map((item, i) => (
                      <li key={item.place.id}>
                        {/* The row's words describe its Ride here, so three waters are told apart by how far each is. */}
                        <span id={`${detourId}-place-${i}`}>{nearbyShort(item)}</span>
                        <span className="actions">
                          <button
                            type="button"
                            className="secondary"
                            aria-label={`Ride here: ${item.place.title}`}
                            aria-describedby={`${detourId}-place-${i}`}
                            onClick={() => void rideThere(item)}
                          >
                            Ride here
                          </button>
                        </span>
                      </li>
                    ))}
                  </ol>
                  {found.kind === "water" && <p className="hint">{WATER_CAUTION}</p>}
                    {found.attribution && <p className="hint">Search: {found.attribution.join("; ")}</p>}
                </div>
              )}
              <p className="hint">{ROAM_DETOUR_HELP}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
