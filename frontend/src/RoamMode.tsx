/**
 * Roam (lib/roam.ts; the owner, 2026-10-22: "Add a free ride mode on go. Basically just show the map and the roads
 * upcoming. Let people detour still to bathroom food water etc", "or call it roam"): a ride with no destination,
 * started from Go's one Roam button while Go has none.
 *
 * - The map follows the rider, track-up as a ride's does (App's follow and heading-up, shared with Ride mode).
 * - The card: the road the rider is on and the next roads ahead, each with its stress level as the map colours it,
 *   read from the map's own tiles on the phone. Fewer words on screen; a screen reader and the voice hear the road
 *   as it changes, in whole words.
 * - The side buttons, Ride's (the audit's P13, approved 2026-10-28: "Roam matches Ride"): Where am I? (re-centring),
 *   Large text, Broadcast, Nearby (water, restroom, food, repair or a search: the three nearest by bike, each with Ride
 *   here, which starts an ordinary ride there; ending that ride comes back to Roam; Detour before, but Roam has no
 *   route to detour from), 311 (one tap logs, as in a ride), and the compass.
 * - End roam, slid as End ride is, so a bump does not end it.
 *
 * Privacy (the owner, 2026-10-22: nothing kept on the server): the position stays on the phone. Only a Nearby search
 * (POST /api/nearest) and the ride it starts send where the rider is, in a POST body, as Ride mode's detours do; a 311
 * pick sent to DC 311 sends its point, as a ride's does; and while the rider broadcasts, the position and trail go to
 * /api/rides as any broadcast's do, kept 2 minutes there.
 */
import { BROADCAST_HOLD_HINT } from "./lib/broadcastQr.ts";
import { t } from "./lib/i18n.ts";
import { railWord } from "./lib/railWords.ts";
import { useHold } from "./lib/useHold.ts";
import { NOTHING_DISMISSED, RIDE_WEATHER_MS, alertKey, alertSaid, alertUrgent, dismissWeather, newAlerts, rainLine, rainSays, rainStage, roamPoints, weatherToShow } from "./lib/weather.ts";
import { useWeather } from "./useWeather.ts";
import { WeatherLines } from "./WeatherLines.tsx";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon.tsx";
import { LiveRegion, SAID_311_MS, SlideToEnd, loggedSaid, rideVoice } from "./RideMode.tsx";
import { REPORT_SENT, report311Enabled, sendReport311, type ReportKind } from "./lib/report311.ts";
import { entryText, report311Log } from "./lib/report311Log.ts";
import { RIDE_311_NAME, RIDE_311_TEXT, Ride311Menu } from "./lib/ride311.ts";
import { currentTiers } from "./stressStyle.js";
import { useStressStyle } from "./useStressStyle.ts";
import { haversineM, insideCoverage, type LonLat } from "./lib/geo.ts";
import type { FoodPlace } from "./lib/food.ts";
import type { Dials } from "./lib/dials.ts";
import type { PresetId } from "./lib/presets.ts";
import type { WaterPoint } from "./lib/waterRestrooms.ts";
import { WATER_CAUTION } from "./lib/waterRestrooms.ts";
import { LOCATE_MESSAGES } from "./lib/geolocation.ts";
import { IosLocationHelp } from "./IosLocationHelp.tsx";
import { POOR_FIX_M, weighFix, type GpsWeakness, type RideFix } from "./lib/navigate.ts";
import { RIDE_TEXT_BUTTON, ScreenWake, phoneKind, toScreenReader, wakeSaid, type RidePrefs, type RideTextSize } from "./lib/rideOutput.ts";
import { ScreenSleepNote } from "./ScreenSleepNote.tsx";
import { useRailFit } from "./lib/railFit.ts";
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
  detourLettered,
  detourShowName,
  detourShownSaid,
  findDetour,
  type DetourAsk,
  type DetourDeps,
  type DetourFound,
} from "./lib/detourSearch.ts";
import type { RepairPlace } from "./lib/repair.ts";
import { placeLetter, type LetteredPlace } from "./lib/letteredPlaces.ts";
import {
  END_ROAM_NAME,
  NO_NAMED_ROAD,
  NO_ROAD_YET,
  OUTSIDE_MAP,
  ROAM_DETOUR_HELP,
  ROAM_BROADCAST_NAME,
  ROAM_GPS_WEAK,
  ROAM_NAME,
  ROAM_NEARBY_NAME,
  ROAM_NO_PLACE_311,
  aheadRow,
  aheadSaid,
  HeadingTrack,
  mapLines,
  onRoadSaid,
  roadsAhead,
  roamLight,
  roamReportPlace,
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

/**
 * The level's swatch, in the map's colours, the same colour and edge as the road's line on the map beside it. The
 * words ("LTS 4") are for screen readers only (the audit's P13, approved 2026-10-28: "Replace 'LTS 4' next to the street
 * name with the colour swatch alone"); `hidden` leaves them out where the row says them already.
 */
function TierBadge({ tier, hidden = false }: { tier: number | null; hidden?: boolean }) {
  useStressStyle();
  const words = roamTier(tier);
  if (!words) return null;
  const look = (currentTiers() as Array<{ tier: number; color: string; casing: string }>).find((t) => t.tier === tier);
  return (
    <span className="roam-tier" aria-hidden={hidden || undefined}>
      <span className="roam-swatch" aria-hidden="true" style={look ? { background: look.color, borderColor: look.casing } : undefined} />
      {!hidden && <span className="visually-hidden">, {words}</span>}
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
  textSize = "normal",
  onTextSize = () => undefined,
  preset,
  dials,
  water,
  food,
  repair = noPlaces,
  geocode = noSearch,
  onView,
  onLettered = () => undefined,
  onShowPlace = () => undefined,
  onDetour,
  onEnd,
  onLocationOff,
  onBroadcast = null,
  onBroadcastHold = null,
  passingOn = false,
  broadcasting = false,
  geoEnv,
}: {
  getMap: () => RoamMap | null;
  prefs: RidePrefs;
  follow: boolean;
  onFollow: (on: boolean) => void;
  headingUp: boolean;
  onHeadingUp: (on: boolean) => void;
  /** Large text (Ride's button and Settings' switch, the same choice): the card half the screen, its words larger. */
  textSize?: RideTextSize;
  onTextSize?: (size: RideTextSize) => void;
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
  /** Nearby's places for the map's lettered pins, and what a pin's press does; null for none (2026-10-28). */
  onLettered?: (pins: { places: LetteredPlace[]; pick: (index: number) => void } | null) => void;
  /** A Nearby row's Show on map: the map frames the place and the rider. */
  onShowPlace?: (point: LonLat) => void;
  /** Ride here: a ride from `here` to the place starts; null, else the words to say why not. */
  onDetour: (here: LonLat, place: NearestPlace) => Promise<string | null>;
  onEnd: () => void;
  /** The watch stopped for good (the location blocked, or none on this page): Roam ends, and Go says why (P11). */
  onLocationOff?: (reason: "denied" | "insecure" | "unsupported") => void;
  /** Broadcast (Stephen 2026-10-22): opens the share sheet with a link others follow; answers what to say. Null where
   * this browser has no share sheet. */
  onBroadcast?: (() => Promise<string>) | null;
  /** Broadcast held (or right-clicked): its link as a QR code (lib/broadcastQr.ts); answers what to say. */
  onBroadcastHold?: (() => Promise<string>) | null;
  /** Following someone's broadcast: Broadcast passes their link on (they stay its leader). */
  passingOn?: boolean;
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
  const offRef = useRef(onLocationOff);
  offRef.current = onLocationOff;
  const [fix, setFix] = useState<RideFix | null>(null);
  const fixRef = useRef<RideFix | null>(null);
  const [gps, setGps] = useState<string>(WAITING_FOR_GPS);
  const [roads, setRoads] = useState<RoadsAhead | null>(null);
  const [heading, setHeading] = useState<number | null>(null);
  const [polite, setPolite] = useState({ text: "", count: 0 });
  const [toast, setToast] = useState("");
  const railRef = useRef<HTMLDivElement>(null);
  const railFit = useRailFit(railRef);
  // The screen-on note, as Ride mode's (ScreenSleepNote): one line, the phone's own steps behind its How.
  const [wakeNote, setWakeNote] = useState("");
  const phone = useMemo(() => phoneKind(), []);

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
  // The screen lock held or not: shown, and said once each time it changes (as Ride mode's noteWake).
  const wakeTold = useRef("");
  const noteWake = useCallback(
    (held: boolean) => {
      const note = wake.noteFor(held);
      if (note && note !== wakeTold.current) say(wakeSaid(note, phone));
      wakeTold.current = note;
      setWakeNote(note);
    },
    [wake, say, phone],
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
      (reason) => {
        if (reason === "denied" || reason === "insecure" || reason === "unsupported") offRef.current?.(reason);
        setGps(reason === "timeout" ? WAITING_FOR_GPS : LOCATE_MESSAGES[reason]);
      },
    );
    void wake.hold().then(noteWake);
    headingRef.current?.focus();
    return () => {
      stop();
      void wake.letGo();
    };
  }, [env, wake, noteWake]);
  // The browser lets the lock go whenever the page is hidden (a pocket lock, an app switch), as in a ride: asked again
  // when it is in front again, and when the browser lets it go mid-roam (lib/rideOutput.ts ScreenWake.whenLost).
  useEffect(() => {
    wake.whenLost(noteWake);
    const onVisibility = () => {
      if (document.visibilityState === "visible") void wake.again().then(noteWake);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      wake.whenLost(null);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [wake, noteWake]);

  // The rider on the map, and the roads ahead worked out again as they move (at most every AHEAD_EVERY_MS).
  const last = useRef<{ at: number; point: LonLat } | null>(null);
  const pending = useRef<{ name: string | null; count: number }>({ name: null, count: 0 });
  const saidRoad = useRef<string | null | undefined>(undefined);
  // The heading kept between fixes that give none (lib/roam.ts HeadingTrack), so the card and the arrow hold steady.
  const track = useRef(new HeadingTrack()).current;
  const headingKept = useRef<number | null>(null);
  // Poor fixes (POOR_FIX_M, a Wi-Fi or cell guess) move the marker but are not read for roads or said, as Ride's cues;
  // only poor ones for GPS_WEAK_MS, the rider is told once (ROAM_GPS_WEAK, lib/navigate.ts weighFix).
  const weakness = useRef<GpsWeakness>({ goodAt: Date.now(), weak: false });
  const [weakGps, setWeakGps] = useState(false);
  useEffect(() => {
    if (!fix) return;
    const weighed = weighFix(weakness.current, fix.accuracyM, fix.at);
    weakness.current = weighed;
    setWeakGps(weighed.weak);
    if (weighed.sayNow) say(ROAM_GPS_WEAK);
    if (fix.accuracyM > POOR_FIX_M) {
      onView({ point: fix.point, headingDeg: headingKept.current, accuracyM: fix.accuracyM });
      return;
    }
    const h = track.step(fix.point, fix.headingDeg);
    headingKept.current = h;
    setHeading(h);
    onView({ point: fix.point, headingDeg: h, accuracyM: fix.accuracyM });
    // Outside the map (P11): no roads to read; said once, as the card shows it.
    if (!insideCoverage(fix.point)) {
      if (saidRoad.current !== OUTSIDE_MAP) say(`${OUTSIDE_MAP}.`);
      saidRoad.current = OUTSIDE_MAP;
      return;
    }
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
    // Only poor fixes a while: the road last read may be behind the rider, so it is not said as where they are.
    if (weakGps) {
      answer(ROAM_GPS_WEAK);
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
  // A row's Show on map (as Ride's Detour and Find food's, 2026-10-28): the menu closes with its list and its pins kept;
  // reopening shows the same list, the focus on that row's Show on map. Any other close takes the pins away.
  const shownRow = useRef<number | null>(null);
  const [pinsKept, setPinsKept] = useState(false);
  const foundRows = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (!detourOpen) {
      if (shownRow.current === null) setPinsKept(false);
      return;
    }
    const row = shownRow.current;
    shownRow.current = null;
    const back = row === null ? null : foundRows.current?.querySelectorAll("li")[row]?.querySelector<HTMLButtonElement>("button");
    if (back) back.focus();
    else detourHeading.current?.focus();
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

  // Large text (Ride's button, the same choice as Settings' switch): the change said as an answer, as Ride's is.
  const cycleText = () => {
    const next = textSize === "large" ? "normal" : "large";
    onTextSize(next);
    answer(next === "large" ? t("Large text on") : t("Large text off"));
  };

  // 311, as in a ride (lib/ride311.ts; the audit's P13): one tap logs the problem with the road ridden and the GPS
  // point; in DC, where the server has DC's key, it is sent there too and checked off. One side menu open at a time.
  const [menu311, setMenu311] = useState(false);
  const menu311Id = useId();
  const menu311Heading = useRef<HTMLHeadingElement>(null);
  const button311 = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (menu311) menu311Heading.current?.focus();
  }, [menu311]);
  const openMenu = (which: "detour" | "311" | null) => {
    setDetourOpen(which === "detour");
    setMenu311(which === "311");
  };
  // Nearby's places, lettered on the map as its rows, while the menu is open and after a row's Show on map; a pin
  // pressed opens Nearby on its row. Gone with the list, and at End roam.
  const letters = useMemo(() => detourLettered(found), [found]);
  const pinsShown = detourOpen || pinsKept ? letters : null;
  const openOnRow = useRef((index: number) => void index);
  openOnRow.current = (index: number) => {
    if (detourOpen) {
      foundRows.current?.querySelectorAll("li")[index]?.querySelector<HTMLButtonElement>("button")?.focus();
      return;
    }
    shownRow.current = index;
    openMenu("detour");
  };
  useEffect(() => {
    onLettered(pinsShown ? { places: pinsShown, pick: (index) => openOnRow.current(index) } : null);
  }, [pinsShown, onLettered]);
  useEffect(() => () => onLettered(null), [onLettered]);
  const showFound = (item: Nearby, index: number) => {
    shownRow.current = index;
    setPinsKept(true);
    setDetourOpen(false);
    detourButton.current?.focus();
    // Following stops, as a pan by hand stops it: Where am I? or 30 s untouched brings it back (lib/idleRecentre.ts).
    onFollow(false);
    onShowPlace(item.place.point);
    answer(detourShownSaid(item, index));
  };
  const close311 = () => {
    setMenu311(false);
    button311.current?.focus();
  };
  const [serverOn311, setServerOn311] = useState(false);
  useEffect(() => {
    let current = true;
    void report311Enabled(window.location.origin).then((on) => {
      if (current) setServerOn311(on);
    });
    return () => {
      current = false;
    };
  }, []);
  // What the pick did, shown under the 311 button for SAID_311_MS and said through the rider's outputs.
  const [said311, setSaid311] = useState("");
  useEffect(() => {
    if (!said311) return;
    const timer = window.setTimeout(() => setSaid311(""), SAID_311_MS);
    return () => window.clearTimeout(timer);
  }, [said311]);
  const tell311 = (text: string) => {
    if (gone.current) return;
    setSaid311(text);
    say(text);
  };
  const pick311 = (kind: ReportKind) => {
    close311();
    const here = fixRef.current?.point;
    if (!here) {
      tell311(ROAM_NO_PLACE_311);
      return;
    }
    const place = roamReportPlace(here, roads);
    const entry = report311Log().add(kind, place);
    if (serverOn311 && entry.where === "dc") {
      setSaid311(t("Sending to DC 311…"));
      void sendReport311(window.location.origin, kind, place, entryText(entry)).then((sent) => {
        if (sent) report311Log().setReported(entry.id, true);
        tell311(sent ? REPORT_SENT : loggedSaid(entry));
      });
    } else tell311(loggedSaid(entry));
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
  const broadcastHoldId = useId();
  const broadcastHold = useHold(
    onBroadcastHold
      ? () =>
          void onBroadcastHold().then((said) => {
            if (said && !gone.current) answer(said);
          })
      : null,
  );

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

  const slideHint = () => answer(t("Slide it to the right to end roam."));
  const on = roads?.on ?? null;
  // Outside the area the map covers (P11): its own head line, in place of a road and "Start riding".
  const outside = fix !== null && !insideCoverage(fix.point);
  return (
    <section className={`ride roam${textSize === "large" ? " ride-large" : ""}`} aria-labelledby="ride-heading">
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
        {(gps || weakGps) && <p className="hint ride-gps">{gps || ROAM_GPS_WEAK}</p>}
        <IosLocationHelp notice={gps} />
        <div className="roam-now">
          {/* The road ridden large; its level beside it, in the map's colours and its words. */}
          <p className="cue-text roam-road">
            {outside ? OUTSIDE_MAP : roads === null ? NO_ROAD_YET : on ? on.name : NO_NAMED_ROAD}
            {!outside && on && <TierBadge tier={on.tier} />}
          </p>
          {!outside && roads !== null && roads.ahead.length > 0 && (
            <ol className="roam-ahead" aria-label={t("Roads ahead")}>
              {/* One line each, at most ROADS_AHEAD (the audit's P13): Ride's short street words, the distance, the
                  swatch; the whole of it in words for screen readers. */}
              {roads.ahead.map((road) => {
                const row = aheadRow(road);
                return (
                  <li key={road.name}>
                    <span className="visually-hidden">{row.said}</span>
                    <span className="roam-ahead-name" aria-hidden="true">{row.name}</span>
                    <span className="roam-ahead-far" aria-hidden="true">
                      {` · ${row.us}`}
                    </span>
                    {row.metric && (
                      <span className="roam-ahead-metric" aria-hidden="true">
                        <span>{` ${row.metric}`}</span>
                      </span>
                    )}
                    <TierBadge tier={road.tier} hidden />
                  </li>
                );
              })}
            </ol>
          )}
          {!outside && roads !== null && heading === null && <p className="cue-more">{t("Start riding to see the roads ahead.")}</p>}
          <WeatherLines report={weatherShown} riding now={Date.now()} onDismiss={() => { setWeatherDismissed((d) => dismissWeather(weatherShown, d)); headingRef.current?.focus({ preventScroll: true }); }} />
          <ScreenSleepNote note={wakeNote} kind={phone} />
        </div>
      </div>
      <div className="ride-middle">
        <button type="button" className="ride-compass" aria-pressed={!headingUp} aria-label={t("North up")} title={t("North up")} onClick={() => onHeadingUp(!headingUp)}>
          <svg viewBox="0 0 40 40" width="40" height="40" aria-hidden="true">
            <path d="M20 5 L25 20 L20 17 L15 20 Z" className="ride-compass-north" />
            <path d="M20 35 L15 20 L20 23 L25 20 Z" className="ride-compass-south" />
          </svg>
        </button>
        {toast && !detourOpen && !menu311 && (
          <div className="ride-toast">
            <p>{toast}</p>
          </div>
        )}
        {/* Each button's word under it, or beside its icon where the map is short, as Ride mode's (lib/railFit.ts). */}
        <div ref={railRef} className={`ride-rail ride-rail-${railFit}`} role="group" aria-label={t("Roam buttons")}>
          <button
            type="button"
            ref={whereRef}
            className={`ride-round${follow ? "" : " ride-round-alert"}`}
            onClick={whereAmI}
            aria-label={follow ? t("Where am I?") : t("Where am I? The map stopped following you")}
            title={t("Where am I?")}
          >
            <Icon name="locate" size={24} />
            <span className="ride-word" aria-hidden="true">{railWord("Locate")}</span>
          </button>
          {/* Large text on and off, as in a ride, shown pressed while on. */}
          <button
            type="button"
            className="ride-round ride-text-size"
            onClick={cycleText}
            aria-pressed={textSize === "large"}
            aria-label={RIDE_TEXT_BUTTON}
            title={RIDE_TEXT_BUTTON}
          >
            <Icon name="textsize" size={24} />
          </button>
          {onBroadcast && (
            <button
              type="button"
              className={`ride-round broadcast-hold${broadcasting ? " ride-round-on" : ""}`}
              onClick={() => void broadcast()}
              {...broadcastHold}
              aria-describedby={onBroadcastHold ? broadcastHoldId : undefined}
              aria-label={broadcasting ? `${ROAM_BROADCAST_NAME}: on. Share the link again` : passingOn ? `${ROAM_BROADCAST_NAME}: pass on the link to this ride` : `${ROAM_BROADCAST_NAME}: share a link others follow you with`}
              title={ROAM_BROADCAST_NAME}
            >
              <Icon name="broadcast" size={24} />
              <span className="ride-word" aria-hidden="true">{railWord("Share live")}</span>
            </button>
          )}
          {onBroadcast && onBroadcastHold && (
            <span id={broadcastHoldId} className="visually-hidden">
              {BROADCAST_HOLD_HINT}
            </span>
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
              aria-label={t("Nearby: {summary}", { summary: DETOUR_SUMMARY.toLowerCase() })}
              title={ROAM_NEARBY_NAME}
              aria-expanded={detourOpen}
              aria-controls={detourId}
              data-idle-close
              onClick={() => openMenu(detourOpen ? null : "detour")}
            >
              <Icon name="detour" size={24} />
              <span className="ride-word" aria-hidden="true">{railWord("Detour")}</span>
            </button>
            <div id={detourId} className="ride-menu" role="group" aria-labelledby={`${detourId}-heading`} hidden={!detourOpen}>
              <div className="ride-menu-head">
                <h3 id={`${detourId}-heading`} ref={detourHeading} tabIndex={-1}>
                  {ROAM_NEARBY_NAME}
                </h3>
                <button
                  type="button"
                  className="secondary ride-menu-close"
                  onClick={() => {
                    setDetourOpen(false);
                    detourButton.current?.focus();
                  }}
                >
                  {t("Close")}
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
                  <ol role="list" aria-labelledby={`${detourId}-found`} ref={foundRows}>
                    {found.items.map((item, i) => (
                      <li key={item.place.id}>
                        {/* The row's words describe its Ride here, so three waters are told apart by how far each is; the
                            letter is its pin's on the map. */}
                        <span id={`${detourId}-place-${i}`}>
                          <strong aria-hidden="true">{placeLetter(i)}.</strong> {nearbyShort(item)}
                        </span>
                        <span className="actions">
                          <button type="button" className="secondary" aria-label={detourShowName(item, i)} onClick={() => showFound(item, i)}>
                            {t("Show on map")}
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            aria-label={t("Ride here: {place}", { place: item.place.title })}
                            aria-describedby={`${detourId}-place-${i}`}
                            onClick={() => void rideThere(item)}
                          >
                            {t("Ride here")}
                          </button>
                        </span>
                      </li>
                    ))}
                  </ol>
                  {found.kind === "water" && <p className="hint">{WATER_CAUTION}</p>}
                    {found.attribution && <p className="hint">{t("Search: {credits}", { credits: found.attribution.join("; ") })}</p>}
                </div>
              )}
              <p className="hint">{ROAM_DETOUR_HELP}</p>
            </div>
          </div>
          {/* 311, as in a ride (lib/ride311.ts): one tap opens the problems, one more logs it; the menu beside the buttons. */}
          <div
            className="ride-311"
            onKeyDown={(event) => {
              if (event.key === "Escape" && menu311) {
                event.preventDefault();
                close311();
              }
            }}
          >
            <button
              type="button"
              ref={button311}
              className="ride-311-button"
              aria-label={RIDE_311_NAME}
              aria-expanded={menu311}
              aria-controls={menu311Id}
              data-idle-close
              onClick={() => openMenu(menu311 ? null : "311")}
            >
              <Icon name="flag" size={18} />
              <span aria-hidden="true">{RIDE_311_TEXT}</span>
            </button>
            <Ride311Menu
              id={menu311Id}
              open={menu311}
              place={fix ? roamReportPlace(fix.point, roads) : null}
              headingRef={menu311Heading}
              onPick={pick311}
              onClose={close311}
            />
            {said311 && !menu311 && (
              <div className="ride-311-said">
                {/* Shown, not a live region: it is said through the rider's own outputs (tell311). */}
                <p>{said311}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
