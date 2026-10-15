// The planner's Route section (moved out of App.tsx in UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx
// split"), laid out as the approved UI mockup of 2026-10-11 has it (reports/v0.5.0/ui-mockup.html): the
// totals in one line with Info beside them, the stress bar, one warning line with its count, one line for
// each note, Start with GPX, Link and More beside it, then one closed line for each fold. Go shows the same
// route in a few lines: the time, the distance, the stress bar, the warning line and Start. App.tsx keeps
// the state and the effects; the questions, the errors and Start ride's question are as they were.
import { useId, useState, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from "react";
import type { BikeshareOption, RouteError, RouteResponse } from "../lib/api.ts";
import { placeLetter } from "../lib/letteredPlaces.ts";
import type { LonLat } from "../lib/geo.ts";
import { formatClimb, formatDistance, formatDuration } from "../lib/format.ts";
import { presetLabel, presetSaid, type PresetId } from "../lib/presets.ts";
import { PresetName } from "../lib/presetName.ts";
import { stressSegments, type StressSegment } from "../lib/stressBar.ts";
import { calmSearchNote, detourView, paceText, stillPlanningSaid, movedPointsNote } from "../lib/summary.ts";
import { isCancelKey } from "../lib/sheet.ts";
import { useStressStyle } from "../useStressStyle.ts";
import { CandidatePicker } from "../lib/candidatePicker.ts";
import { candidateRows } from "../lib/candidates.ts";
import { loopNote } from "../lib/loop.ts";
import { mtbNotes } from "../lib/mtbMode.ts";
import { FacilityBreakdown } from "../FacilityBreakdown.tsx";
import { IntersectionList } from "../IntersectionList.tsx";
import { AvoidNotice } from "../AvoidNotice.tsx";
import { avoidItems, avoidNoticeFor } from "../lib/avoidJunctions.ts";
import { ElevationChart } from "../ElevationChart.tsx";
import { chartKind, corkerFigure, foldName, usableProfile } from "../lib/profileChart.ts";
import { RouteDescription } from "../RouteDescription.tsx";
import { RIDE_SAFETY, RideSettingsFields } from "../RideMode.tsx";
import type { RidePrefs } from "../lib/rideOutput.ts";
import { RIDE_MAX_M, RIDE_TOO_LONG } from "../lib/navigate.ts";
import { BikeshareSummary } from "../BikeshareSummary.tsx";
import { TransitSummary } from "../TransitSummary.tsx";
import { DepartureTimer } from "../DepartureTimer.tsx";
import { transitOf, transitTime } from "../lib/transit.ts";
import { bikeshareOf, routeCredits } from "../lib/bikeshare.ts";
import { rideSizeOf, type Dials, type Ending } from "../lib/dials.ts";
import { CAPACITY_FOLD_TITLE, capacitySummary } from "../lib/massCapacity.ts";
import { CapacityFigures, CapacityStats } from "../lib/massLegend.ts";
import { outsideDcNote } from "../lib/dcBoundary.ts";
import { downloadGpx } from "../GpxPanel.tsx";
import { Fold, QuickFigures } from "../Sidebar.tsx";
import { COPY_LINK, ROUTE_FOLDS, chartFoldOpen } from "../lib/sidebar.ts";
import { SHARE_LABEL, SHARE_NAME } from "../lib/share.ts";
import { calmPercent, quickFigures, stressBarKey, stressBarLabel } from "../lib/quickFigures.ts";
import { junctionItems } from "../lib/intersectionMarkers.ts";
import type { WaterAlong, WaterStatus } from "../lib/waterRestrooms.ts";
import { WaterAlongList } from "../lib/waterLegend.ts";
import type { ClimbAlong, ClimbsStatus } from "../lib/climbs.ts";
import { ClimbsAlongList } from "../lib/climbsLegend.ts";
import { KEEP_LABEL } from "../lib/offlineRoutes.ts";
import { facilityNoticeCount, warningsLabel } from "../lib/routeNotices.ts";
import type { AppMode } from "../lib/appMode.ts";
import type { IconName } from "../lib/iconPaths.ts";
import { Icon } from "../Icon.tsx";

export type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "waiting"; seconds: number }
  | { kind: "ok" }
  | { kind: "error"; error: RouteError }
  | { kind: "confirm"; error: RouteError };

/** Download GPX, Copy link, Share and Keep for offline: beside Start in Plan (Share and Keep behind More). */
export interface RouteActionsProps {
  shown: RouteResponse;
  routedPoints: LonLat[];
  routedLoop: boolean;
  federalRoute: readonly string[];
  copyLink: () => void;
  linkNote: string;
  canShare: boolean;
  shareRoute: () => void;
  linkSpoken: string;
  keepShown: boolean;
  keepForOffline: () => Promise<void>;
  keeping: boolean;
  keepSpoken: { text: string; count: number };
  linkSaid: string;
}

/** Go's few extra controls on the route: its ride chip, the Routes chip and Plan in detail. */
export interface GoRouteControls {
  /** Opens the Ride sheet. */
  onRide: () => void;
  /** Switches to Plan, the route kept. */
  onPlan: () => void;
  /** The sheet is at its smallest (peek): the route's time, Start and the stress bar only. */
  peek: boolean;
  /**
   * A Bikeshare route's options, lettered A, B, C (lib/bikeshareOptions.ts), with the one the shown plan
   * rides (-1: none yet); a press re-plans that pair. Null off Bikeshare, or with one option.
   */
  options: { list: BikeshareOption[]; picked: number; busy: boolean; onPick: (index: number) => void } | null;
}

/** Go's Bikeshare options: one button each, lettered as on the map, named by the option's own words. */
function GoBikeOptions({ options }: { options: NonNullable<GoRouteControls["options"]> }) {
  const headingId = useId();
  return (
    <div className="go-bike-options" role="group" aria-labelledby={headingId}>
      <h3 id={headingId} className="go-bike-options-title">
        <Icon name="bikeshare" size={18} />
        Bikeshare options
      </h3>
      <ul role="list" className="go-bike-option-list">
        {options.list.map((option, index) => {
          const letter = placeLetter(index);
          return (
            <li key={`${option.pickup_station}>${option.dropoff_station}>${option.ending}`} className="lettered-row">
              <button type="button" className="go-bike-option" aria-pressed={index === options.picked} onClick={() => options.onPick(index)}>
                <span className="place-letter" aria-hidden="true">
                  <span>{letter}</span>
                </span>
                <span className="visually-hidden">{`${letter}: `}</span>
                <span className="go-bike-option-text">{option.text}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export interface RouteSectionProps {
  /** A re-plan is under way: the section is aria-busy. */
  stale: boolean;
  routeHeadingRef: RefObject<HTMLHeadingElement | null>;
  status: Status;
  announcement: string;
  slow: boolean;
  preset: PresetId;
  dials: Dials;
  points: LonLat[];
  cancelLong: () => void;
  planButtonRef: RefObject<HTMLButtonElement | null>;
  confirmLong: () => void;
  errorRef: RefObject<HTMLDivElement | null>;
  retry: () => void;
  shown: RouteResponse | null;
  answer: RouteResponse | null;
  choice: number;
  aroundAvoid: boolean;
  setAroundAvoid: (around: boolean) => void;
  routedPoints: LonLat[];
  federalRoute: readonly string[];
  narrow: boolean;
  setJunctionFocus: Dispatch<SetStateAction<{ index: number; nonce: number } | null>>;
  setScrubPoint: (point: LonLat | null) => void;
  choose: (index: number) => void;
  startRide: () => void;
  startRideRef: RefObject<HTMLButtonElement | null>;
  rideSize: number | undefined;
  setDials: Dispatch<SetStateAction<Dials>>;
  waterStatus: WaterStatus;
  waterAlong: WaterAlong[] | null;
  addWaterStop: (item: WaterAlong) => void;
  rideAsk: boolean;
  setRideAsk: (on: boolean) => void;
  backToRideOpener: () => void;
  ridePrefs: RidePrefs;
  changeRidePrefs: (next: RidePrefs) => void;
  rideStartFirstRef: RefObject<HTMLButtonElement | null>;
  beginRide: (prefs: RidePrefs) => void;
  /** The Climbs layer (lib/climbs.ts): the switch, its data's status and the climbs the route rides. */
  climbsOn: boolean;
  climbsStatus: ClimbsStatus;
  climbsAlong: ClimbAlong[] | null;
  /** Go or Plan (lib/appMode.ts). */
  mode: AppMode;
  /** Plan's Download GPX, Copy link and More, beside Start. */
  actions: Omit<RouteActionsProps, "shown" | "routedPoints" | "federalRoute">;
  /** Bikeshare's "Choose a station" fold (NearbyStations), or nothing. */
  stations: ReactNode;
  go: GoRouteControls;
  /** The transit ride types' options and departure (TransitSummary). */
  transitControls: TransitControls;
}

/** A transit plan's controls: plan another option, and the departure's milestones and a miss. */
export interface TransitControls {
  onPick: (key: string) => void;
  announce: (text: string) => void;
  onMissed: () => void;
}

/** The planner's Route section: planning, the long-ride question, errors, the route summary and Start ride's question. */
export function RouteSection(props: RouteSectionProps) {
  const { stale, routeHeadingRef, status, announcement, slow, preset, dials, points, cancelLong, planButtonRef, confirmLong, errorRef, retry, shown, answer, choice, aroundAvoid, setAroundAvoid, routedPoints, federalRoute, narrow, setJunctionFocus, setScrubPoint, choose, startRide, startRideRef, rideSize, setDials, waterStatus, waterAlong, addWaterStop, rideAsk, setRideAsk, backToRideOpener, ridePrefs, changeRidePrefs, rideStartFirstRef, beginRide, climbsOn, climbsStatus, climbsAlong, mode, actions, stations, go, transitControls } = props;
  const goMode = mode === "go";
  return (
    <section key="route" aria-labelledby="route-heading" aria-busy={stale} className={goMode ? "route-section go-route" : "route-section"}>
      <h2 id="route-heading" ref={routeHeadingRef} tabIndex={-1} className={goMode ? "visually-hidden" : undefined}>
        Route
      </h2>
      {status.kind === "loading" && <p className="loading">{announcement}</p>}
      {status.kind === "loading" && <progress className="planning" aria-label="Planning the route" />}
      {/* What the route's live region says (routeStatus, outside the panel), shown here; a screen
          reader hears it there, so it is not read twice. */}
      <div className="status-shown" aria-hidden="true">
        {status.kind === "loading" && slow && <p className="loading">{stillPlanningSaid(preset, dials)}</p>}
        {status.kind === "waiting" && <p className="loading">{announcement}</p>}
      </div>
      {/* Read where it stands, not spoken: it never changes while shown (recheck N-new-2). */}
      {status.kind === "idle" && points.length < 2 && !goMode && <p className="hint">No route yet.</p>}
      {status.kind === "confirm" && (
        <div
          className="confirm"
          role="alertdialog"
          aria-labelledby="confirm-title"
          aria-describedby="confirm-text"
          onKeyDown={(event) => {
            if (isCancelKey(event.key)) {
              event.preventDefault();
              cancelLong();
            }
          }}
        >
          <p id="confirm-title">
            <strong>{status.error.title}</strong>
          </p>
          <p id="confirm-text">{status.error.message} Plan it?</p>
          <div className="actions">
            <button type="button" ref={planButtonRef} onClick={confirmLong}>
              Plan it
            </button>
            <button type="button" className="secondary" onClick={cancelLong}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {status.kind === "error" && (
        <div ref={errorRef} tabIndex={-1} className={`error error-${status.error.kind}`} role="alert">
          <p>
            <strong>{status.error.title}.</strong> {status.error.message}
          </p>
          {["router-down", "timed-out", "bikeshare-unavailable", "server", "network", "rate-limited"].includes(status.error.kind) && (
            <button type="button" onClick={retry}>
              Try again
            </button>
          )}
        </div>
      )}
      {!goMode && stations}
      {shown && (
        <RouteSummary
          route={shown}
          answer={answer}
          choice={choice}
          around={aroundAvoid}
          onAround={setAroundAvoid}
          points={routedPoints}
          federal={federalRoute}
          narrow={narrow}
          onSelectJunction={(index) => setJunctionFocus((f) => ({ index, nonce: (f?.nonce ?? 0) + 1 }))}
          onScrub={setScrubPoint}
          picker={
            candidateRows(answer) === null ? null : (
              <CandidatePicker answer={answer} choice={choice} onChoose={choose} />
            )
          }
          pickerCount={candidateRows(answer)?.length ?? 0}
          ride={{ onStart: startRide, startRef: startRideRef }}
          rideSize={rideSizeOf({ rideSize })}
          onEnding={(ending) => setDials((d) => ({ ...d, ending }))}
          water={waterStatus === "ready" ? { items: waterAlong, onAddStop: addWaterStop } : null}
          climbs={climbsOn && climbsStatus === "ready" ? climbsAlong : null}
          actions={{ ...actions, shown, routedPoints, federalRoute }}
          mode={mode}
          preset={preset}
          go={go}
          transitControls={{ ...transitControls, busy: stale }}
        />
      )}
      {shown && rideAsk && (
        <div className="ride-ask" role="dialog" aria-labelledby="ride-ask-title" aria-describedby="ride-ask-safety"
          onKeyDown={(event) => {
            if (isCancelKey(event.key)) {
              event.preventDefault();
              setRideAsk(false);
              backToRideOpener();
            }
          }}
        >
          <h3 id="ride-ask-title" tabIndex={-1}>
            Start ride
          </h3>
          <p id="ride-ask-safety" className="hint">
            {RIDE_SAFETY}
          </p>
          <RideSettingsFields prefs={ridePrefs} onChange={changeRidePrefs} idBase="ride-ask" />
          <div className="actions">
            <button
              type="button"
              ref={rideStartFirstRef}
              onClick={() => {
                const prefs = { ...ridePrefs, chosen: true };
                changeRidePrefs(prefs);
                beginRide(prefs);
              }}
            >
              Start
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setRideAsk(false);
                backToRideOpener();
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * Start's row in Plan: Download GPX and Copy link as icon buttons beside it, and More (a disclosure)
 * holding Share and Keep for offline (the owner's choice 8). The said lines stay outside More, so a
 * press is heard however More stands.
 */
function RouteActions(props: RouteActionsProps & { start: ReactNode }) {
  const { shown, routedPoints, routedLoop, federalRoute, copyLink, linkNote, canShare, shareRoute, linkSpoken, keepShown, keepForOffline, keeping, keepSpoken, linkSaid, start } = props;
  const [more, setMore] = useState(false);
  const moreId = useId();
  const hasMore = canShare || keepShown;
  return (
    <div className="route-actions">
      <div className="route-actions-row">
        {start}
        <button type="button" className="secondary icon-button gpx-download" onClick={() => downloadGpx(shown, routedPoints, routedLoop, federalRoute)} aria-label="Download GPX">
          <Icon name="download" />
          <span aria-hidden="true">GPX</span>
        </button>
        <button type="button" className="secondary icon-button copy-link" onClick={copyLink} aria-label={COPY_LINK} aria-describedby={linkNote ? "link-note" : undefined}>
          <Icon name="link" />
          <span aria-hidden="true">Link</span>
        </button>
        {hasMore && (
          <button type="button" className="secondary icon-button route-more" aria-expanded={more} aria-controls={moreId} onClick={() => setMore(!more)}>
            <Icon name="more" />
            <span>More</span>
          </button>
        )}
      </div>
      {hasMore && (
        <div id={moreId} className="route-more-body" hidden={!more}>
          {canShare && (
            <button type="button" className="secondary share-route" onClick={shareRoute} aria-label={SHARE_NAME} aria-describedby={linkNote ? "link-note" : undefined}>
              {SHARE_LABEL}
            </button>
          )}
          {keepShown && (
            <button type="button" className="secondary keep-offline" onClick={() => void keepForOffline()} aria-disabled={keeping} aria-describedby="keep-offline-said">
              {KEEP_LABEL}
            </button>
          )}
        </div>
      )}
      <span role="status" className="visually-hidden">
        {linkSpoken}
      </span>
      {keepShown && (
        <p id="keep-offline-said" className="hint keep-said" role="status">
          {keepSpoken.text}
          {keepSpoken.count % 2 === 1 ? " " : ""}
        </p>
      )}
      {linkSaid && (
        <span className="hint link-said" aria-hidden="true">
          {linkSaid}
        </span>
      )}
      {linkNote && (
        <p id="link-note" className="hint link-note">
          {linkNote}
        </p>
      )}
    </div>
  );
}

/** The route's notes, one line each with an icon (the owner's choice 5), their full words behind Info. */
interface NoteLine {
  key: string;
  className: string;
  icon: IconName;
  text: string;
}

function noteLines(route: RouteResponse, points: LonLat[]): NoteLine[] {
  const lines: NoteLine[] = [];
  // A point inside the National Zoo was moved to its bike racks (291(4)): shown here, and said with the route.
  const moved = movedPointsNote(route, points.length);
  if (moved) lines.push({ key: "moved", className: "notice moved-points", icon: "pin", text: moved });
  // A Mass Ride that leaves the District (OWNER-DECISIONS 418a): shown here, and said in the route's
  // live region with the rest of the route's sentence (lib/summary.ts announceRoute).
  const outsideDc = outsideDcNote(route);
  if (outsideDc) lines.push({ key: "outside", className: "notice mass-outside-dc", icon: "warn", text: outsideDc });
  const detour = detourView(route, points);
  if (detour) lines.push({ key: "detour", className: `notice detour detour-${detour.level}`, icon: "warn", text: detour.text });
  const calm = calmSearchNote(route);
  if (calm) lines.push({ key: "calm", className: "hint calm-search", icon: "info", text: calm });
  const loop = loopNote(route);
  if (loop) lines.push({ key: "loop", className: "hint loop-note", icon: "loop", text: loop });
  // Mountain Bike (slice 6): what the trail rules could not hold, said first, then how much is trail.
  const mtb = mtbNotes(route.mtb);
  for (const text of mtb.warnings) lines.push({ key: `mtb-${text}`, className: "notice mtb-warning", icon: "warn", text });
  if (mtb.notes.length > 0) lines.push({ key: "mtb-note", className: "hint mtb-note", icon: "mtb", text: mtb.notes.join(" ") });
  return lines;
}

/**
 * The warning line (the owner's choice 5): the Avoid-rated junction first (AvoidNotice, an alert whose
 * whole sentence is read), with Avoid it beside it, and a count of the route's other warnings (the roads
 * best avoided, a traffic-tolerant ride, what the hills search found), listed behind it.
 */
function RouteAlerts({ route, answer, choice, around, onAround }: { route: RouteResponse; answer: RouteResponse | null; choice: number; around: boolean; onAround: (around: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const others = facilityNoticeCount(route);
  const hasAvoid = avoidNoticeFor(answer, choice) !== null;
  if (!hasAvoid && others === 0) return null;
  return (
    <div className="route-alerts">
      {/* First in the route's warnings and announced first (335): the route goes through an Avoid-rated junction. */}
      {hasAvoid && answer && <AvoidNotice answer={answer} choice={choice} around={around} onAround={onAround} />}
      {others > 0 && (
        <>
          <button type="button" className="secondary alert-more" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
            <Icon name="warn" size={16} />
            {warningsLabel(others, hasAvoid)}
          </button>
          <div id={id} className="alert-details" hidden={!open}>
            <FacilityBreakdown route={route} part="notices" />
          </div>
        </>
      )}
    </div>
  );
}

/** The stress bar and its key: patterns as well as colours, and the shares in words (312). */
function StressFigure({ segments }: { segments: StressSegment[] }) {
  return (
    <figure className="stress stress-main" aria-labelledby="stress-figure-caption">
      <figcaption id="stress-figure-caption" className="visually-hidden">
        Traffic stress along the route
      </figcaption>
      {/* One image to a screen reader, named with each share; the line under it says the same in text. */}
      <div className="stress-bar" role="img" aria-label={stressBarLabel(segments)}>
        {segments
          .filter((s) => s.fraction > 0)
          .map((s) => (
            <span
              key={s.key}
              className={`stress-seg stress-seg-${s.key}`}
              style={{ width: `${s.fraction * 100}%`, backgroundColor: s.color, ["--seg-accent" as string]: s.casing }}
              title={`${s.short}: ${s.percent}%`}
            />
          ))}
      </div>
      <p className="stress-key" aria-hidden="true">
        {stressBarKey(segments)}
      </p>
    </figure>
  );
}

const climbCount = (n: number) => (n === 1 ? "1 climb" : `${n} climbs`);

export function RouteSummary({
  route,
  answer,
  choice,
  around,
  onAround,
  points,
  federal,
  narrow,
  onSelectJunction,
  onScrub,
  picker,
  pickerCount,
  ride,
  rideSize,
  onEnding,
  water,
  climbs,
  actions,
  mode,
  preset,
  go,
  transitControls,
}: {
  route: RouteResponse;
  answer: RouteResponse | null;
  choice: number;
  around: boolean;
  onAround: (around: boolean) => void;
  points: LonLat[];
  /** A Mass Ride's federal-land lines for the description (lib/federalStops.ts federalLines, item 239). */
  federal: readonly string[];
  narrow: boolean;
  /** Ride mode's Start ride (WEB-NAV-plan.md Q1): offered beside the totals and with the directions. */
  ride: { onStart: () => void; startRef: RefObject<HTMLButtonElement | null> };
  onSelectJunction: (index: number) => void;
  /** The chart's scrub: the map point it reads, or null. */
  onScrub: (point: LonLat | null) => void;
  /** The routes to choose from (CandidatePicker), or null with one route. */
  picker: ReactNode;
  pickerCount: number;
  /** Mass Ride's anticipated ride size, riders (PLAN items 128, 139): the corker load's group length. */
  rideSize: number;
  onEnding: (ending: Ending) => void;
  transitControls?: TransitControls & { busy: boolean };
  /** Water and restrooms along the route, once loaded (listed with the map layer off too); else null. */
  water: { items: WaterAlong[] | null; onAddStop: (item: WaterAlong) => void } | null;
  /** The climbs the route rides, while the Climbs layer is on and loaded; else null. */
  climbs: ClimbAlong[] | null;
  actions: RouteActionsProps;
  mode: AppMode;
  preset: PresetId;
  go: GoRouteControls;
}) {
  useStressStyle();
  const [info, setInfo] = useState(false);
  // Go offers the routes to choose from at once (the owner, 2026-10-11: "select a destination ... then offer
  // the options for routing to it"); Plan keeps them in their closed fold.
  const [routesOpen, setRoutesOpen] = useState(mode === "go");
  const infoId = useId();
  const routesId = useId();
  // A Mass Ride's panel is about riders per minute, in place of the LTS breakdown (OWNER-DECISIONS 325).
  const capacity = capacitySummary(route.stress_spans);
  const segments = capacity ? [] : stressSegments(route.stress_m);
  const notes = noteLines(route, points);
  const pace = paceText(route);
  const profile = usableProfile(route);
  // The Avoid-rated junctions count with the rest, and keep the fold where the others could not be read.
  const avoidCount = avoidItems(route).length;
  const junctions = route.intersections == null ? (avoidCount > 0 ? avoidCount : null) : junctionItems(route).length + avoidCount;
  const bikeshare = bikeshareOf(route);
  // A transit ride type (lib/transit.ts): the line is the first ride; the trip, its total and its steps are `transit`.
  const transit = transitOf(route);
  const timeName = transit ? (transit.scheduled ? "Door-to-door time, scheduled" : "Door-to-door time") : "Moving time";
  const timeText = transit ? transitTime(transit) : formatDuration(route.duration_s);
  const calm = calmPercent(route.stress_m);
  // Start ride is offered with the directions too (plan Q1). Not on a Bikeshare plan: the route
  // is only the ride between the docks, so the walk to the first dock would read as off route.
  // Nor on a transit plan, whose line is only its first ride, unless the plan is riding your own bike
  // the whole way (its line is then the whole trip).
  const wholeRide = !transit || (transit.direct && transit.mode === "bike-transit");
  const rideable = !bikeshare && wholeRide && route.distance_m <= RIDE_MAX_M;
  const rideAction = rideable ? (
    <button type="button" className="secondary" onClick={ride.onStart}>
      Start ride
    </button>
  ) : null;
  const goMode = mode === "go";
  // "Elevation and climbs" (the mockup); a Mass Ride's three charts keep their own name.
  const elevationTitle = profile && chartKind(route) === "mass" ? foldName("mass") : ROUTE_FOLDS.elevation.title;
  // Start: the big button (Go), or the first of its row (Plan). Short rides only; a longer one goes to a bike computer (OD 255).
  const start = rideable ? (
    <button type="button" className="start-button" ref={ride.startRef} onClick={ride.onStart} aria-describedby="start-ride-hint">
      <Icon name="play" />
      Start<span className={goMode ? undefined : "visually-hidden"}> ride</span>
    </button>
  ) : null;
  const startHint = rideable ? (
    <p id="start-ride-hint" className="hint start-ride-hint">
      Turn-by-turn directions on this phone, said as you chose. Keep the screen on and this page in front.
    </p>
  ) : bikeshare || transit ? null : (
    <p className="hint start-ride-long">{RIDE_TOO_LONG}</p>
  );
  const alerts = <RouteAlerts route={route} answer={answer} choice={choice} around={around} onAround={onAround} />;
  const alertCount = (avoidNoticeFor(answer, choice) ? 1 : 0) + facilityNoticeCount(route);
  // What Info holds: the pace, the notes in full, how to reshape the line and the route's sources (the owner's choice 5).
  const infoBody = (
    <div id={infoId} className="route-info" hidden={!info}>
      {bikeshare && <p className="hint">These figures are for the ride between the docks. The walks are above.</p>}
      {transit && transit.scheduled && (
        <p className="hint">The distance, climb and stress are for the first ride, the line on the map. The whole trip is in its steps.</p>
      )}
      {pace && <p className="hint pace">Moving time at {pace}, without stops.</p>}
      {notes.map((note) => (
        <p key={note.key} className="hint note-full">
          {note.text}
        </p>
      ))}
      {/* Riders often arrive by a shared link, straight into a route, and a
          phone has no hover to show the handle: say that the line moves. */}
      <p className="hint reshape">
        {narrow ? "To reshape the route, press and hold the line, then drag it." : "To reshape the route, drag the line."}
      </p>
      <p className="route-credit">Route data: {routeCredits(route).join("; ")}.</p>
    </div>
  );
  const infoButton = (
    <button type="button" className="link icon-button info-button route-info-button" aria-expanded={info} aria-controls={infoId} onClick={() => setInfo(!info)}>
      <Icon name="info" />
      <span>Info</span>
    </button>
  );
  const noteList =
    notes.length > 0 ? (
      <ul className="note-lines" role="list">
        {notes.map((note) => (
          <li key={note.key} className={`note-line ${note.className}`}>
            <Icon name={note.icon} size={16} />
            <span className="note-text">{note.text}</span>
          </li>
        ))}
      </ul>
    ) : null;
  const bikeshareFold = bikeshare ? (
    // The bikeshare plan, as a fold kept open (the mockup's table: "Same: a fold, open").
    <Fold title="Bikeshare plan" open className="bikeshare-fold" icon="bikeshare">
      <BikeshareSummary plan={bikeshare} onEnding={onEnding} />
    </Fold>
  ) : null;

  const transitFold = transit ? (
    // The trip, as a fold kept open: the step list is the plan (the owner, 2026-10-12: "a clear step list").
    <Fold title={`${presetLabel(preset)} trip`} said={`${presetSaid(preset)} trip`} open className="transit-fold" icon="train">
      <TransitSummary
        plan={transit}
        preset={preset}
        onPick={transitControls?.onPick}
        busy={transitControls?.busy}
        announce={transitControls?.announce}
        onMissed={transitControls?.onMissed}
      />
    </Fold>
  ) : null;

  if (goMode) {
    // Go (the approved mockup's route sheets): the time big, the distance and climb in a line, Info, the
    // stress bar, the warning line, Start, then the ride, the routes and Plan in detail. At its smallest
    // (peek) the sheet keeps the time, Start and the stress bar, and counts the warnings.
    return (
      <div className={`summary go-summary${go.peek ? " peek" : ""}`}>
        {!go.peek && go.options && <GoBikeOptions options={go.options} />}
        {!go.peek && bikeshareFold}
        <div className="go-head">
          <h3 className="visually-hidden">Totals</h3>
          <dl className="stats totals go-totals">
            <div className="total-time">
              <dt className="visually-hidden">{timeName}</dt>
              <dd>{timeText}</dd>
            </div>
            <div className="stat-distance">
              <dt className="visually-hidden">{transit ? "First ride's distance" : "Distance"}</dt>
              <dd>{formatDistance(route.distance_m)}</dd>
            </div>
            {go.peek && alertCount > 0 ? (
              <div className="total-alerts">
                <dt className="visually-hidden">Warnings</dt>
                <dd>
                  <Icon name="warn" size={14} />
                  {alertCount === 1 ? "1 alert" : `${alertCount} alerts`}
                </dd>
              </div>
            ) : (
              <div className="total-climb">
                <dt className="visually-hidden">Climb</dt>
                <dd>
                  <Icon name="mountain" size={14} />
                  {formatClimb(route.climb_m)}
                </dd>
              </div>
            )}
          </dl>
          {go.peek ? start : infoButton}
        </div>
        {!go.peek && infoBody}
        {!go.peek && transitFold}
        {/* At peek the trip's panel is folded away, but an infrequent departure's countdown keeps
            running (and its milestones and a miss are still said): one compact line. */}
        {go.peek && transit?.departure && (
          <DepartureTimer
            compact
            departure={transit.departure}
            announce={transitControls?.announce}
            onMissed={transitControls?.onMissed}
          />
        )}
        {segments.length > 0 && <StressFigure segments={segments} />}
        {!go.peek && <CapacityStats route={route} corkers={corkerFigure(route, profile, rideSize)} />}
        {!go.peek && alerts}
        {!go.peek && noteList}
        {!go.peek && (
          <div className="actions start-ride go-start">
            {start}
            {startHint}
          </div>
        )}
        {/* The elevation chart, open whenever the sheet is bigger than peek (Stephen 2026-10-13: "on Go, add an
            elevation chart to the map as well, even if relatively flat"), under Start so it never pushes Start
            down; its key and tables stay in Plan. */}
        {!go.peek && profile && chartKind(route) !== "mass" && <ElevationChart route={route} profile={profile} onScrub={onScrub} compact />}
        {!go.peek && (
          <div className="go-chips" role="group" aria-label="Route options">
            <button type="button" className="chip go-ride-chip" onClick={go.onRide} aria-describedby="go-ride-hint">
              <Icon name="bike" size={18} />
              <PresetName id={preset} />
            </button>
            <span id="go-ride-hint" hidden>
              Opens the ride settings.
            </span>
            {picker && (
              <button type="button" className="chip go-routes-chip" aria-expanded={routesOpen} aria-controls={routesId} onClick={() => setRoutesOpen(!routesOpen)}>
                <Icon name="routes" size={18} />
                {`${pickerCount} routes`}
              </button>
            )}
            <button type="button" className="chip go-plan-chip" onClick={go.onPlan} aria-describedby="go-plan-hint">
              <Icon name="list" size={18} />
              Plan
            </button>
            <span id="go-plan-hint" hidden>
              Plan in detail: the full planner, with this route.
            </span>
          </div>
        )}
        {!go.peek && picker && (
          <div id={routesId} className="go-routes" hidden={!routesOpen}>
            {picker}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="summary">
      {bikeshareFold}
      {/* Headings for a screen reader's list, out of sight: the route's figures, then each fold (the a11y review's S5). */}
      <div className="totals-row">
        <h3 className="visually-hidden">Totals</h3>
        <dl className="stats totals">
          <div className="total-time">
            <dt className="visually-hidden">{timeName}</dt>
            <dd>{timeText}</dd>
          </div>
          <div className="stat-distance">
            <dt className="visually-hidden">{transit ? "First ride's distance" : "Distance"}</dt>
            <dd>{formatDistance(route.distance_m)}</dd>
          </div>
          <div className="total-climb">
            <dt className="visually-hidden">Climb</dt>
            <dd>
              <span aria-hidden="true">↑ </span>
              {formatClimb(route.climb_m)}
            </dd>
          </div>
          <div className="total-descent">
            <dt className="visually-hidden">Descent</dt>
            <dd>
              <span aria-hidden="true">↓ </span>
              {formatClimb(route.descent_m)}
            </dd>
          </div>
        </dl>
        {infoButton}
      </div>
      {infoBody}
      {transitFold}
      <CapacityStats route={route} corkers={corkerFigure(route, profile, rideSize)} />
      {segments.length > 0 && <StressFigure segments={segments} />}
      {alerts}
      {noteList}
      <div className="actions start-ride">
        <RouteActions {...actions} start={start} />
        {startHint}
      </div>
      {(profile || climbs) && (
        <Fold
          title={elevationTitle}
          heading={elevationTitle}
          icon="chart"
          count={climbs && climbs.length > 0 ? climbCount(climbs.length) : null}
          // Closed by default, on a computer too (the owner's choice 7).
          open={chartFoldOpen(narrow)}
          className="elevation-fold"
        >
          {profile && <ElevationChart route={route} profile={profile} onScrub={onScrub} rideSize={rideSize} />}
          {/* The climbs on the route (the Climbs layer's list), in this fold (the mockup's table). */}
          {climbs && <ClimbsAlongList items={climbs} headingId="climbs-along-planner-heading" level="h4" />}
        </Fold>
      )}
      {capacity && (
        // A Mass Ride's fold is about riders per minute, in place of the stress and facility figures (OWNER-DECISIONS 325).
        <Fold title={CAPACITY_FOLD_TITLE} heading={CAPACITY_FOLD_TITLE} open={ROUTE_FOLDS.facilities.open} icon="road">
          <CapacityFigures route={route} />
        </Fold>
      )}
      {!capacity && (
        <Fold
          title={ROUTE_FOLDS.facilities.title}
          heading={ROUTE_FOLDS.facilities.title}
          open={ROUTE_FOLDS.facilities.open}
          icon="road"
          count={calm === null ? null : `${calm}% quiet`}
          className="facilities-fold"
        >
          {/* The four quick figures, first in the fold (the owner's choice 4). */}
          <QuickFigures figures={quickFigures(route)} />
          {segments.length > 0 && (
            <figure className="stress" aria-labelledby="stress-detail-caption">
              <figcaption id="stress-detail-caption">Traffic stress, stretch by stretch</figcaption>
              <ul className="stress-list">
                {segments.map((s) => (
                  <li key={s.key}>
                    <span className={`swatch stress-seg-${s.key}`} style={{ backgroundColor: s.color, ["--seg-accent" as string]: s.casing }} aria-hidden="true" />
                    <span className="stress-name">{s.short}</span>
                    <span className="visually-hidden">, </span>
                    <span className="stress-pct">{s.percent}%</span>
                    <span className="visually-hidden">, </span>
                    <span className="stress-label">{s.label}</span>
                  </li>
                ))}
              </ul>
            </figure>
          )}
          <FacilityBreakdown route={route} part="figures" />
        </Fold>
      )}
      <RouteDescription route={route} fold rideAction={rideAction} federal={federal} />
      {junctions !== null && (
        <Fold title={ROUTE_FOLDS.junctions.title} count={junctions} heading={ROUTE_FOLDS.junctions.title} open={ROUTE_FOLDS.junctions.open} icon="junction">
          <IntersectionList route={route} onSelect={onSelectJunction} />
        </Fold>
      )}
      {picker && (
        <Fold title={ROUTE_FOLDS.choices.title} count={pickerCount} heading={ROUTE_FOLDS.choices.title} open={ROUTE_FOLDS.choices.open} icon="routes">
          {picker}
        </Fold>
      )}
      {water && (
        // Water and restrooms along the route: one closed fold here, no longer also in Layers (the mockup's table).
        <Fold
          title={ROUTE_FOLDS.water.title}
          count={water.items?.length ?? null}
          heading={ROUTE_FOLDS.water.title}
          open={ROUTE_FOLDS.water.open}
          icon="water"
          className="water-fold"
        >
          <WaterAlongList items={water.items} onAddStop={water.onAddStop} headingId="water-along-planner-heading" level="h4" />
        </Fold>
      )}
    </div>
  );
}
