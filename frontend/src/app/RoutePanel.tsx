// The planner's Route section (moved out of App.tsx in UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx
// split"), laid out as the approved UI mockup of 2026-10-11 has it (reports/v0.5.0/ui-mockup.html): the
// totals in one line with Info beside them, the stress bar, one warning line with its count, one line for
// each note, Start with GPX, Link and More beside it, then one closed line for each fold. Go shows the same
// route in a few lines: the time, the distance, the stress bar, the warning line and Start. App.tsx keeps
// the state and the effects; the questions, the errors and Start ride are as they were.
import { choiceColours } from "../lib/routeChoice.ts";
import { useId, useState, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from "react";
import { routeErrorShown, type BikeshareOption, type RouteError, type RouteResponse } from "../lib/api.ts";
import { placeLetter } from "../lib/letteredPlaces.ts";
import type { LonLat } from "../lib/geo.ts";
import { formatClimb, formatDistance, formatDuration } from "../lib/format.ts";
import { leaveNowArrival } from "../lib/arrival.ts";
import { presetLabel, presetSaid, type PresetId } from "../lib/presets.ts";
import { firstWordAndRest, t } from "../lib/i18n.ts";
import { NOVICE_TRANSIT_CHOICES, noviceOfferText, noviceTripLine, noviceTripShort, type NoviceTrip } from "../lib/noviceOffer.ts";
import { stressSegments, type StressSegment } from "../lib/stressBar.ts";
import { lightLine, type LightMark } from "../lib/lightTimes.ts";
import { weatherSaid, type WeatherReport } from "../lib/weather.ts";
import { WeatherLines } from "../WeatherLines.tsx";
import { calmSearchNote, detourShort, detourView, paceText, stillPlanningSaid, movedPointsNote, noviceWalksNote, walkInNote, walkInShort } from "../lib/summary.ts";
import { isCancelKey } from "../lib/sheet.ts";
import { useStressStyle } from "../useStressStyle.ts";
import { CandidatePicker } from "../lib/candidatePicker.ts";
import { candidateRows } from "../lib/candidates.ts";
import { loopNote, loopNoteShort } from "../lib/loop.ts";
import { mtbNotes } from "../lib/mtbMode.ts";
import { FacilityBreakdown } from "../FacilityBreakdown.tsx";
import { IntersectionList } from "../IntersectionList.tsx";
import { AvoidNotice } from "../AvoidNotice.tsx";
import { avoidItems, avoidNoticeFor } from "../lib/avoidJunctions.ts";
import { ElevationChart } from "../ElevationChart.tsx";
import { tripRoute } from "../lib/tripRides.ts";
import { chartKind, corkerFigure, corkerShort, foldName, usableProfile } from "../lib/profileChart.ts";
import { RouteDescription } from "../RouteDescription.tsx";
import { RIDE_TOO_LONG } from "../lib/navigate.ts";
import { ridesHidden } from "../lib/nativeShell.ts";
import { noBikeLine, restOffered, rideTripOf, rideable as rideableRoute, ridesLine } from "../lib/rideTrip.ts";
import { BikeshareSummary } from "../BikeshareSummary.tsx";
import { TransitSummary } from "../TransitSummary.tsx";
import { DepartureTimer } from "../DepartureTimer.tsx";
import { transitOf, transitTime, transitTimeName } from "../lib/transit.ts";
import { bikeshareOf, routeCredits } from "../lib/bikeshare.ts";
import { rideSizeOf, type Dials, type Ending } from "../lib/dials.ts";
import { CAPACITY_FOLD_TITLE, capacitySummary } from "../lib/massCapacity.ts";
import { CapacityFigures, CapacityShort, CapacityStats } from "../lib/massLegend.ts";
import { outsideDcNote } from "../lib/dcBoundary.ts";
import { SaveRoute, type SaveRouteProps } from "../SaveRoute.tsx";
import { SAVE_ROUTE, SAVE_SHORT } from "../lib/savedRoutes.ts";
import { Fold, QuickFigures } from "../Sidebar.tsx";
import { COPY_LINK, ROUTE_FOLDS, ROUTE_FOLD_GROUP, chartFoldOpen } from "../lib/sidebar.ts";
import { BROADCAST_ABOUT, BROADCAST_LABEL, SHARE_LABEL, SHARE_RIDE_LABEL } from "../lib/share.ts";
import { BROADCAST_HOLD_HINT } from "../lib/broadcastQr.ts";
import { useHold } from "../lib/useHold.ts";
import { SHARE_IMAGE_LABEL } from "../lib/shareCard.ts";
import {
  SHARE_DELETE_AFTER_LABEL,
  SHARE_KEEP_LABEL,
  SHARE_KEEP_OPTIONS,
  SHARE_RIDE_ABOUT,
  SHARE_ROUTE_ABOUT,
  SHARE_UNTIL_DAYS,
  dayFromToday,
  type ShareKeep,
  type ShareKeepChoice,
} from "../lib/sharedRoutes.ts";
import { calmPercent, calmWayShares, calmWaysLabel, groupRideLine, quickFigures, stressBarKey, stressBarLabel, stressPlainParts } from "../lib/quickFigures.ts";
import { facilityRows } from "../lib/facilityBar.ts";
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
  /** Opens Share as image (ShareCardDialog), in Plan's More. */
  shareImage: () => void;
  linkSpoken: string;
  keepShown: boolean;
  keepForOffline: () => Promise<void>;
  keeping: boolean;
  keepSpoken: { text: string; count: number };
  linkSaid: string;
  /** Download GPX through the page: closures checked first, an unedited opened file as it came (v0.7.0). */
  downloadRoute: () => void;
  /** Save route (signed in): Go's Save chip (Plan's is in the Route file sheet, ShareControls); null signed out. */
  save: Omit<SaveRouteProps, "label" | "chip"> | null;
  /** A reopened saved route's line about today's map, with Update route; null otherwise. */
  savedNote: ReactNode;
}

/** Go's few extra controls on the route: its route card, its ride types and the Routes chip. */
export interface GoRouteControls {
  /** The sheet is at its smallest (peek): the route's time, Start and the stress bar only. */
  peek: boolean;
  /** The sheet is at full height (or the page is wide, with no sheet): the elevation chart shows (review F8). */
  full: boolean;
  /**
   * A Bikeshare route's options, lettered A, B, C (lib/bikeshareOptions.ts), with the one the shown plan
   * rides (-1: none yet); a press re-plans that pair. Null off Bikeshare, or with one option.
   */
  options: { list: BikeshareOption[]; picked: number; busy: boolean; onPick: (index: number) => void } | null;
  /** Novice and Nervous's offer (v0.7.0, lib/noviceOffer.ts): plan the trip on this transit ride type instead. */
  onNoviceTransit?: (preset: PresetId) => void;
  /** Each offered option's trip, found in the background as the offer shows (App), by ride type. */
  noviceTrips?: Partial<Record<PresetId, NoviceTrip>>;
  /**
   * Go's route card (Go.tsx GoRouteCard) and its ride type chips, under the time and the stress bar and above Start
   * (edit-route redesign, Stephen 2026-10-18): what the route is and how it is ridden, each one press to change.
   */
  routeCard?: ReactNode;
  rides?: ReactNode;
  /** Go's climb figure is a button (P3): it opens Ride settings at the Hills slider. Left out, the figure is text. */
  onClimb?: (opener: HTMLElement) => void;
  /** The destination's name, for a route error's words ("No route to Safeway…"); null on a loop or with none. */
  place?: string | null;
  /** Go's "Add a stop" (Go.tsx GoAddStop), or null: under the route card, one tap away (Stephen 2026-10-18). */
  addStop?: ReactNode;
  /** A tap on Go's stress bar: Layers, with the Traffic stress section's colour key open (the owner's P1). */
  onStressKey?: (opener: HTMLButtonElement) => void;
}

/**
 * Novice and Nervous where only a busy road connects (v0.7.0): the road named, and beside the bike route, unasked,
 * "Own bike + transit" and "Bikeshare + transit", each a button with its one-line note (its time door to door, and
 * the busy stretch it avoids) as its description; nothing otherwise.
 */
function NoviceTransitOffer({
  route,
  preset,
  onTake,
  trips,
}: {
  route: RouteResponse;
  preset: PresetId;
  onTake?: (preset: PresetId) => void;
  trips?: Partial<Record<PresetId, NoviceTrip>>;
}) {
  const text = noviceOfferText(route, preset);
  const id = useId();
  if (!text || !onTake || !route.novice) return null;
  const note = route.novice;
  return (
    <div className="novice-offer" role="group" aria-labelledby={id}>
      <p id={id} className="notice">
        <Icon name="warn" size={16} />
        {text}
      </p>
      <ul className="novice-trips">
        {NOVICE_TRANSIT_CHOICES.map((choice) => (
          <li key={choice.preset}>
            <button type="button" className="chip" aria-describedby={`${id}-${choice.preset}`} onClick={() => onTake(choice.preset)}>
              {choice.label}
            </button>
            {/* Shown short; the whole line (time, and the road it avoids) is the button's description. */}
            <span className="novice-trip-note" aria-hidden="true">
              {noviceTripShort(trips?.[choice.preset])}
            </span>
            <span id={`${id}-${choice.preset}`} className="visually-hidden">
              {noviceTripLine(trips?.[choice.preset], note)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Go's Bikeshare options: one button each, lettered as on the map, named by the option's own words. */
function GoBikeOptions({ options }: { options: NonNullable<GoRouteControls["options"]> }) {
  const headingId = useId();
  return (
    <div className="go-bike-options" role="group" aria-labelledby={headingId}>
      <h3 id={headingId} className="go-bike-options-title">
        <Icon name="bikeshare" size={18} />
        {t("Bikeshare options")}
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

/** A route error: what went wrong and what to do (lib/api.ts routeErrorShown), with one Try again where it can help. */
function RouteErrorBox({ error, errorRef, retry, goPlace, offline }: { error: RouteError; errorRef: RefObject<HTMLDivElement | null>; retry: () => void; goPlace: string | null; offline: boolean }) {
  const shown = routeErrorShown(error, goPlace, offline);
  return (
    <div ref={errorRef} tabIndex={-1} className={`error error-${error.kind}`} role="alert">
      <p>
        {shown.title && <strong>{shown.title}.</strong>} {shown.message}
      </p>
      {shown.retry && (
        <button type="button" onClick={retry}>
          {t("Try again")}
        </button>
      )}
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
  /** Broadcast, beside Start: Share ride's link (the sharer leads), then the ride. Null without a share sheet. */
  // `onHold`: held (or right-clicked), its link as a QR code (lib/broadcastQr.ts).
  broadcastRide: { onPress: () => void; onHold: () => void; note: { text: string; count: number } } | null;
  startRideRef: RefObject<HTMLButtonElement | null>;
  rideSize: number | undefined;
  setDials: Dispatch<SetStateAction<Dials>>;
  waterStatus: WaterStatus;
  waterAlong: WaterAlong[] | null;
  addWaterStop: (item: WaterAlong) => void;
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
  /** The light times on the route near dawn or dusk (lib/lightTimes.ts), leaving now; empty otherwise. */
  light: readonly LightMark[];
  /** When the route shown ends leaving now (lib/arrival.ts leaveNowArriveMs), kept current each minute; else null. */
  arriveMs: number | null;
  /** Weather along the route, leaving now (lib/weather.ts), once checked; else null. */
  weather: WeatherReport | null;
  /** The planner out of reach while the page is offline: the error box says offline, the one message (P11). */
  offline?: boolean;
}

/** A transit plan's controls: plan another option, and the departure's milestones and a miss. */
export interface TransitControls {
  onPick: (key: string) => void;
  announce: (text: string) => void;
  onMissed: () => void;
  /** Ride the rest (lib/rideTrip.ts): a ride for the trip's last riding leg, after the transit. */
  onRideRest: () => void;
}

/** The planner's Route section: planning, the long-ride question, errors, the route summary and Start ride. */
export function RouteSection(props: RouteSectionProps) {
  const { stale, routeHeadingRef, status, announcement, slow, preset, dials, points, cancelLong, planButtonRef, confirmLong, errorRef, retry, shown, answer, choice, aroundAvoid, setAroundAvoid, routedPoints, federalRoute, narrow, setJunctionFocus, setScrubPoint, choose, startRide, broadcastRide, startRideRef, rideSize, setDials, waterStatus, waterAlong, addWaterStop, climbsOn, climbsStatus, climbsAlong, mode, actions, stations, go, transitControls, light, arriveMs, weather } = props;
  const goMode = mode === "go";
  return (
    <section key="route" aria-labelledby="route-heading" aria-busy={stale} className={goMode ? "route-section go-route" : "route-section"}>
      <h2 id="route-heading" ref={routeHeadingRef} tabIndex={-1} className={goMode ? "visually-hidden" : undefined}>
        {t("Route")}
      </h2>
      {status.kind === "loading" && <p className="loading">{announcement}</p>}
      {status.kind === "loading" && <progress className="planning" aria-label={t("Planning the route")} />}
      {/* What the route's live region says (routeStatus, outside the panel), shown here; a screen
          reader hears it there, so it is not read twice. */}
      <div className="status-shown" aria-hidden="true">
        {status.kind === "loading" && slow && <p className="loading">{stillPlanningSaid(preset, dials)}</p>}
        {status.kind === "waiting" && <p className="loading">{announcement}</p>}
      </div>
      {/* Read where it stands, not spoken: it never changes while shown (recheck N-new-2). */}
      {status.kind === "idle" && points.length < 2 && !goMode && <p className="hint">{t("No route yet.")}</p>}
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
          <p id="confirm-text">{status.error.message}{" "}{t("Plan it?")}</p>
          <div className="actions">
            <button type="button" ref={planButtonRef} onClick={confirmLong}>
              {t("Plan it")}
            </button>
            <button type="button" className="secondary" onClick={cancelLong}>
              {t("Cancel")}
            </button>
          </div>
        </div>
      )}
      {status.kind === "error" && (
        <RouteErrorBox error={status.error} errorRef={errorRef} retry={retry} goPlace={goMode ? (go.place ?? null) : null} offline={props.offline === true} />
      )}
      {/* Go keeps the trip under an error (P11): where to, and the ride types, one tap to try another. */}
      {status.kind === "error" && goMode && !go.peek && go.routeCard}
      {status.kind === "error" && goMode && !go.peek && go.rides && (
        <div className="go-route-rides">
          <p className="go-rides-label" aria-hidden="true">
            {t("Ride type")}
          </p>
          {go.rides}
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
              <CandidatePicker answer={answer} choice={choice} onChoose={choose} colours={goMode ? choiceColours(answer) : null} />
            )
          }
          pickerCount={candidateRows(answer)?.length ?? 0}
          ride={{ onStart: startRide, onBroadcast: broadcastRide?.onPress ?? null, onBroadcastHold: broadcastRide?.onHold ?? null, broadcastNote: broadcastRide?.note, startRef: startRideRef }}
          rideSize={rideSizeOf({ rideSize })}
          onEnding={(ending) => setDials((d) => ({ ...d, ending }))}
          water={waterStatus === "ready" ? { items: waterAlong, onAddStop: addWaterStop } : null}
          climbs={climbsOn && climbsStatus === "ready" ? climbsAlong : null}
          actions={{ ...actions, shown, routedPoints, federalRoute }}
          mode={mode}
          preset={preset}
          go={go}
          transitControls={{ ...transitControls, busy: stale }}
          light={light}
          arriveMs={arriveMs}
          weather={weather}
        />
      )}
    </section>
  );
}

/**
 * Under Share in the Route file sheet: how long the shared link's exact line is kept. A year after it was last opened is the
 * default; "Until a date" shows the date, starting a month out (the owner, 2026-10-16).
 */
function ShareKeepField({ value, onChange }: { value: ShareKeep; onChange: (keep: ShareKeep) => void }) {
  const id = useId();
  const choose = (keep: ShareKeepChoice) =>
    onChange({ keep, deleteAfter: keep === "until" && !value.deleteAfter ? dayFromToday(SHARE_UNTIL_DAYS) : value.deleteAfter });
  return (
    <div className="share-keep">
      <label htmlFor={`${id}-keep`}>{SHARE_KEEP_LABEL}</label>
      <select id={`${id}-keep`} value={value.keep} onChange={(event) => choose(event.target.value as ShareKeepChoice)}>
        {SHARE_KEEP_OPTIONS.map(([choice, label]) => (
          <option key={choice} value={choice}>
            {label}
          </option>
        ))}
      </select>
      {value.keep === "until" && (
        <>
          <label htmlFor={`${id}-date`}>{SHARE_DELETE_AFTER_LABEL}</label>
          <input id={`${id}-date`} type="date" min={dayFromToday(1)} value={value.deleteAfter} onChange={(event) => onChange({ ...value, deleteAfter: event.target.value })} />
        </>
      )}
    </div>
  );
}

/**
 * Save route, then Share (the owner, 2026-10-17: "the share button should be in files. Basically you save then you
 * share"): in the Route file sheet, under the file's own controls, for a planned route and an opened file alike. Share
 * is there only where the browser has a share sheet (Copy link, in Plan's route row, is always there); how long its
 * exact line is kept is chosen under it. What Share did (only a failure, or a line not kept) is said here, politely.
 */
export function ShareControls(props: {
  save: ReactNode;
  /** The browser has a share sheet: Share's keeping and its status line are there. */
  canShare: boolean;
  /** A route to share is shown: the Share buttons are there. */
  ready: boolean;
  /** Share route, or (ride) Share ride: the same link, ridden fixed with location sharing offered (RIDE_PARAM). */
  shareRoute: (ride: boolean) => void;
  shareKeep: ShareKeep;
  /** Plan only (Go keeps the default, one control per feature): how long the link is kept. */
  onShareKeep: ((keep: ShareKeep) => void) | null;
  shareSaid: { text: string; count: number };
  /** The location line (OWNER-DECISIONS 395): it describes Share, so it is read before the sheet opens. */
  linkNote: string;
}) {
  const { save, canShare, ready, shareRoute, shareKeep, onShareKeep, shareSaid, linkNote } = props;
  // What each button does (the owner, 2026-10-18: "Make that clear in a tooltip"): a phone has no hover, so Info
  // shows it; it is each button's description too, so a screen reader hears it on the button, and a mouse sees it
  // on hover (title).
  const [about, setAbout] = useState(false);
  const aboutId = useId();
  const note = linkNote ? " share-link-note" : "";
  return (
    <div className="share-controls">
      {save}
      {canShare && ready && (
        <div className="share-buttons">
          <button
            type="button"
            className="secondary share-route"
            onClick={() => shareRoute(false)}
            aria-describedby={`share-route-about${note}`}
            title={SHARE_ROUTE_ABOUT}
          >
            {SHARE_LABEL}
          </button>
          <button
            type="button"
            className="secondary share-ride"
            onClick={() => shareRoute(true)}
            aria-describedby={`share-ride-about${note}`}
            title={SHARE_RIDE_ABOUT}
          >
            {SHARE_RIDE_LABEL}
          </button>
          <button type="button" className="link icon-button info-button share-about-button" aria-expanded={about} aria-controls={aboutId} onClick={() => setAbout(!about)}>
            <Icon name="info" />
            <span className="visually-hidden">{t("About sharing")}</span>
          </button>
        </div>
      )}
      {canShare && ready && (
        <div id={aboutId} className="share-about" hidden={!about}>
          <p id="share-route-about" className="hint">
            {SHARE_ROUTE_ABOUT}
          </p>
          <p id="share-ride-about" className="hint">
            {SHARE_RIDE_ABOUT}
          </p>
        </div>
      )}
      {canShare && ready && linkNote && (
        <p id="share-link-note" className="hint link-note">
          {linkNote}
        </p>
      )}
      {canShare && ready && onShareKeep && <ShareKeepField value={shareKeep} onChange={onShareKeep} />}
      {canShare && (
        <p className="hint share-said" role="status">
          {shareSaid.text}
          {shareSaid.count % 2 === 1 ? " " : ""}
        </p>
      )}
    </div>
  );
}

/**
 * Start's row in Plan: Download GPX and Copy link as icon buttons beside it, and More (a disclosure)
 * holding Share as image and Keep for offline (the owner's choice 8; Save route and Share are in the Route file
 * sheet, ShareControls). The said lines stay outside More, so a press is heard however More stands.
 */
function RouteActions(props: RouteActionsProps & { start: ReactNode }) {
  const { copyLink, linkNote, shareImage, linkSpoken, keepShown, keepForOffline, keeping, keepSpoken, linkSaid, start, downloadRoute } = props;
  const [more, setMore] = useState(false);
  const moreId = useId();
  return (
    <div className="route-actions">
      <div className="route-actions-row">
        {start}
        <button type="button" className="secondary icon-button gpx-download" onClick={() => downloadRoute()} aria-label={t("Download GPX")}>
          <Icon name="download" />
          <span aria-hidden="true">GPX</span>
        </button>
        <button type="button" className="secondary icon-button copy-link" onClick={copyLink} aria-label={COPY_LINK} aria-describedby={linkNote ? "link-note" : undefined}>
          <Icon name="link" />
          <span aria-hidden="true">{t("Link")}</span>
        </button>
        {/* Always: Share as image is in it (Download works where the browser has no share sheet). */}
        <button type="button" className="secondary icon-button route-more" aria-expanded={more} aria-controls={moreId} onClick={() => setMore(!more)}>
          <Icon name="more" />
          <span>{t("More")}</span>
        </button>
      </div>
      <div id={moreId} className="route-more-body" hidden={!more}>
        {/* Its QR code's link keeps as chosen under Share (the Route file sheet). */}
        <button type="button" className="secondary share-image" onClick={shareImage} aria-haspopup="dialog">
          {SHARE_IMAGE_LABEL}
        </button>
        {keepShown && (
          <button type="button" className="secondary keep-offline" onClick={() => void keepForOffline()} aria-disabled={keeping} aria-describedby="keep-offline-said">
            {KEEP_LABEL}
          </button>
        )}
      </div>
      <span role="status" className="visually-hidden link-spoken">
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
  /**
   * Shown in the text's place where the whole sentence runs past a phone's line (the audit's P14), and allowed to wrap
   * rather than be cut: the text stays for screen readers, and in full in Info.
   */
  short?: string | null;
}

function noteLines(route: RouteResponse, points: LonLat[], light: readonly LightMark[] = [], goMode = false): NoteLine[] {
  const lines: NoteLine[] = [];
  // A point inside the National Zoo was moved to its bike racks (291(4)): shown here, and said with the route.
  const moved = movedPointsNote(route, points.length);
  if (moved) lines.push({ key: "moved", className: "notice moved-points", icon: "pin", text: moved });
  // The ride stops short of a point, and the rider walks the bike the rest (the API's `walk_in`).
  const walkIn = walkInNote(route);
  if (walkIn) lines.push({ key: "walk-in", className: "notice walk-in", icon: "pin", text: walkIn, short: walkInShort(route) });
  // Novice and Nervous walk the bike past a short busy stretch on the sidewalk (v0.11.0; the API's `novice.walks`).
  const pastBusy = noviceWalksNote(route);
  if (pastBusy) lines.push({ key: "novice-walks", className: "notice walk-in", icon: "pin", text: pastBusy });
  // A Mass Ride that leaves the District (OWNER-DECISIONS 418a): shown here, and said in the route's
  // live region with the rest of the route's sentence (lib/summary.ts announceRoute).
  const outsideDc = outsideDcNote(route);
  if (outsideDc) lines.push({ key: "outside", className: "notice mass-outside-dc", icon: "warn", text: outsideDc });
  // Go has no Traffic slider to point to: its line is the short one ("2.3× as far, to skip 0.8 mi of busy roads.").
  const detour = goMode ? detourShort(route, points) : detourView(route, points);
  if (detour) lines.push({ key: "detour", className: `notice detour detour-${detour.level}`, icon: "warn", text: detour.text });
  const calm = calmSearchNote(route);
  if (calm) lines.push({ key: "calm", className: "hint calm-search", icon: "info", text: calm });
  const loop = loopNote(route);
  if (loop) lines.push({ key: "loop", className: "hint loop-note", icon: "loop", text: loop, short: loopNoteShort(route) });
  // Mountain Bike (slice 6): what the trail rules could not hold, said first, then how much is trail.
  const mtb = mtbNotes(route.mtb);
  for (const text of mtb.warnings) lines.push({ key: `mtb-${text}`, className: "notice mtb-warning", icon: "warn", text });
  if (mtb.notes.length > 0) lines.push({ key: "mtb-note", className: "hint mtb-note", icon: "mtb", text: mtb.notes.join(" ") });
  // Near dawn or dusk: where the rider will be at each light time (lib/lightTimes.ts), one line, in Go too.
  const lightText = lightLine(light);
  if (lightText) lines.push({ key: "light", className: "hint light-times", icon: "sun", text: lightText });
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

/**
 * The stress bar and its key: patterns as well as colours, and the shares in words (312). In Go (the owner's P1,
 * 2026-10-28: "add paths and protected bike lanes to the chart") a slim strip under the bar marks the route's share on
 * a traffic-free path and on a protected lane, the line under them is plain words ("Mostly calm · 1.1 mi on paths and
 * protected lanes · busy road for 0.2 mi"), and a tap on the bar opens the colour key in Layers. A screen reader still
 * hears every share: the bar's name, and the strip's. `line` takes the key's place, or the plain words', where the ride
 * type says it its own way (Group Ride, lib/quickFigures.ts groupRideLine; the audit's P6).
 */
function StressFigure({ segments, go, line = null }: { segments: StressSegment[]; line?: string | null; go?: { route: RouteResponse; peek: boolean; onKey?: (opener: HTMLButtonElement) => void } }) {
  const keyHintId = useId();
  // One image to a screen reader, named with each share; the line under it says the same in text.
  const bar = (
    <div className="stress-bar" role="img" aria-label={stressBarLabel(segments)}>
      {segments
        .filter((s) => s.fraction > 0)
        .map((s) => (
          <span
            key={s.key}
            className={`stress-seg stress-seg-${s.key}`}
            style={{ width: `${s.fraction * 100}%`, backgroundColor: s.color, ["--seg-accent" as string]: s.casing }}
            title={t("{short}: {percent}%", { short: s.short, percent: s.percent })}
          />
        ))}
    </div>
  );
  if (!go) {
    return (
      <figure className="stress stress-main" aria-labelledby="stress-figure-caption">
        <figcaption id="stress-figure-caption" className="visually-hidden">
          {t("Traffic stress along the route")}
        </figcaption>
        {bar}
        {line ? (
          // Said too: the turns are not in the bar's name.
          <p className="stress-key group-ride-line">{line}</p>
        ) : (
          <p className="stress-key" aria-hidden="true">
            {stressBarKey(segments)}
          </p>
        )}
      </figure>
    );
  }
  // Painted lanes on busy roads count for neither, so the strip needs no Layers switch (lib/facilityBar.ts).
  const ways = calmWayShares(facilityRows(go.route.facility_m));
  const strip =
    ways.length > 0 ? (
      // A stress bar's border, and its colours kept in forced colours (styles.css), in the rails' colours.
      <div className="stress-bar calm-ways" role="img" aria-label={calmWaysLabel(ways)}>
        {ways.map((way) => (
          <span key={way.key} className={`stress-seg calm-way calm-way-${way.key}`} style={{ width: `${way.fraction * 100}%` }} />
        ))}
      </div>
    ) : null;
  const parts = line ? [line] : stressPlainParts(go.route);
  return (
    <figure className="stress stress-main stress-go" aria-labelledby="stress-figure-caption">
      <figcaption id="stress-figure-caption" className="visually-hidden">
        {t("Traffic stress along the route")}
      </figcaption>
      {go.onKey ? (
        <button type="button" className="stress-key-button" aria-describedby={keyHintId} onClick={(event) => go.onKey?.(event.currentTarget)}>
          {bar}
          {strip}
        </button>
      ) : (
        <>
          {bar}
          {strip}
        </>
      )}
      {go.onKey && (
        <span id={keyHintId} className="visually-hidden">
          {t("Shows the color key, in Layers.")}
        </span>
      )}
      {parts.length > 0 && (
        // At peek (the time, the bars and Start) it is said, not shown: the sheet fits without a scroll.
        <p className={go.peek ? "stress-key stress-plain visually-hidden" : "stress-key stress-plain"}>
          <span aria-hidden="true">{parts.join(" · ")}</span>
          <span className="visually-hidden">{`${parts.join(", ")}.`}</span>
        </p>
      )}
    </figure>
  );
}

const climbCount = (n: number) => (n === 1 ? t("1 climb") : t("{count} climbs", { count: n }));

/** " · arrive 8:27 AM" after the route's time: when the ride ends if it starts now, as the ride shows it. */
function ArriveAt({ arriveMs }: { arriveMs: number }) {
  const { shown, said } = leaveNowArrival(arriveMs);
  return (
    <span className="route-arrive">
      <span aria-hidden="true"> · {shown}</span>
      <span className="visually-hidden">, {said}</span>
    </span>
  );
}

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
  light = [],
  arriveMs = null,
  weather = null,
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
  ride: { onStart: () => void; onBroadcast?: (() => void) | null; onBroadcastHold?: (() => void) | null; broadcastNote?: { text: string; count: number }; startRef: RefObject<HTMLButtonElement | null> };
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
  /** The light times on the route near dawn or dusk (lib/lightTimes.ts): one line, the map marks' accessible form. */
  light?: readonly LightMark[];
  /** When the ride ends leaving now (lib/arrival.ts leaveNowArriveMs), shown after the route's time; null for none. */
  arriveMs?: number | null;
  /** Weather along the route (lib/weather.ts): the NWS alerts and rain coming, with the warnings. */
  weather?: WeatherReport | null;
}) {
  useStressStyle();
  const [info, setInfo] = useState(false);
  // Go offers the routes to choose from at once (the owner, 2026-10-11: "select a destination ... then offer
  // the options for routing to it"); Plan keeps them in their closed fold.
  const [routesOpen, setRoutesOpen] = useState(mode === "go");
  const infoId = useId();
  const routesId = useId();
  // Broadcast held (or right-clicked): its link as a QR code (lib/broadcastQr.ts).
  const broadcastHold = useHold(ride.onBroadcastHold);
  // A Mass Ride's panel is about riders per minute, in place of the LTS breakdown (OWNER-DECISIONS 325).
  const capacity = capacitySummary(route.stress_spans);
  // A transit option with no ride (P10): no stress bar (it was 100% not rated) and no distance ridden; a line says
  // which option rides instead.
  const noBike = noBikeLine(route);
  const segments = capacity || noBike ? [] : stressSegments(route.stress_m);
  // Group Ride: quiet roads and its turns, in place of the shares (the 2026-10-28 audit, P6).
  const groupLine = preset === "group-ride" ? groupRideLine(route) : null;
  const notes = noteLines(route, points, light, mode === "go");
  const pace = paceText(route);
  // A transit trip's rides joined (lib/tripRides.ts): the distance ridden, the climb and the chart are every ride's.
  const trip = tripRoute(route);
  const profile = usableProfile(trip);
  // The Avoid-rated junctions count with the rest, and keep the fold where the others could not be read.
  const avoidCount = avoidItems(route).length;
  const junctions = route.intersections == null ? (avoidCount > 0 ? avoidCount : null) : junctionItems(route).length + avoidCount;
  const bikeshare = bikeshareOf(route);
  // A transit ride type (lib/transit.ts): the line is the first ride; the trip, its total and its steps are `transit`.
  const transit = transitOf(route);
  const timeName = transit ? transitTimeName(transit) : t("Moving time");
  const timeText = transit ? transitTime(transit) : formatDuration(route.duration_s);
  const timeShown = (
    <>
      {timeText}
      {arriveMs != null && <ArriveAt arriveMs={arriveMs} />}
    </>
  );
  const calm = calmPercent(route.stress_m);
  // On a Bikeshare or transit plan Start ride follows the riding leg, the line (lib/rideTrip.ts: the walk to the dock
  // and the boarding are said around it); the bike computer rule is that leg's. One Start in the sheet, the route
  // row's (P10: the one that was also in Directions went; Plan's bar keeps its own at the top of the map).
  const rideable = rideableRoute(route);
  const goMode = mode === "go";
  // "Start ride" in Go; Plan shows its first word only ("Start", "Iniciar") and keeps the rest for a screen reader.
  const [startWord, rideWord] = firstWordAndRest(t("Start ride"));
  // "Elevation and climbs" (the mockup); a Mass Ride's three charts keep their own name.
  const elevationTitle = profile && chartKind(route) === "mass" ? foldName("mass") : ROUTE_FOLDS.elevation.title;
  // Start: the big button (Go), or the first of its row (Plan). In a browser, short rides only; a longer one goes to a bike computer (OD 255). The phone app rides any length.
  const start = rideable ? (
    <>
      <button type="button" className="start-button" ref={ride.startRef} onClick={ride.onStart} aria-describedby="start-ride-hint">
        <Icon name="play" />
        {startWord}
        <span className={goMode ? undefined : "visually-hidden"}>{rideWord}</span>
      </button>
      {/* Broadcast (Stephen 2026-10-22: "a small button next to start"): Go's one control for it; the share sheet
          opens, and the ride starts once the link is sent, with the sharer as its leader. */}
      {ride.onBroadcast && (
        <button type="button" className="secondary broadcast-button" onClick={ride.onBroadcast} {...broadcastHold} title={BROADCAST_ABOUT} aria-describedby="broadcast-about">
          <Icon name="broadcast" size={18} />
          {BROADCAST_LABEL}
        </button>
      )}
      {ride.onBroadcast && (
        <span id="broadcast-about" className="visually-hidden">
          {BROADCAST_ABOUT} {BROADCAST_HOLD_HINT}
        </span>
      )}
      {/* What went wrong (the route not ready, the sheet failed, the link without its leader), shown and said. */}
      {ride.onBroadcast && (
        <p className="hint broadcast-note" role="status">
          {ride.broadcastNote?.text}
          {(ride.broadcastNote?.count ?? 0) % 2 ? " " : ""}
        </p>
      )}
    </>
  ) : null;
  const startHint = rideable ? (
    // Said with Start, not shown under it: Plan's since Stephen 2026-10-20 ("it needs to be simpler, still a wall of
    // text"), Go's since the owner's P1 (2026-10-28: it was shown on every route).
    <p id="start-ride-hint" className="visually-hidden start-ride-hint">
      {t("Turn-by-turn directions on this phone, said as you chose.")}{ridesHidden() ? "" : t(" Keep the screen on and this page in front.")}
    </p>
  ) : noBike ? (
    <p className="hint no-bike-line">{noBike}</p>
  ) : !ridesLine(route) ? null : (
    <p className="hint start-ride-long">{RIDE_TOO_LONG}</p>
  );
  const alerts = (
    <>
      <RouteAlerts route={route} answer={answer} choice={choice} around={around} onAround={onAround} />
      <NoviceTransitOffer route={route} preset={preset} onTake={go.onNoviceTransit} trips={go.noviceTrips} />
      {/* Weather along the route (Stephen 2026-10-24): the NWS alerts, each linked to its notice, and rain coming. A
          notice only: Start never waits for it. Go shows the alerts under its totals (the owner's P1), and the rain here. */}
      <WeatherLines report={weather} riding={false} now={Date.now()} part={goMode ? "rain" : "all"} />
      {/* The same in words for a screen reader as it arrives, after the route (the region is always there). */}
      <p className="visually-hidden weather-status" role="status">
        {weatherSaid(weather, Date.now())}
      </p>
    </>
  );
  const alertCount = (avoidNoticeFor(answer, choice) ? 1 : 0) + facilityNoticeCount(route) + (weather?.alerts.length ?? 0);
  // The sources once, in Info (P10): the trip's schedules are among them, so its panel no longer says them again.
  const credit = (
    <>
      <p className="route-credit">{t("Route data: {sources}.", { sources: routeCredits(route).join("; ") })}</p>
      {transit?.live && <p className="route-credit">{t("Live departures: {credit}.", { credit: transit.live.credit })}</p>}
    </>
  );
  // What Info holds: the pace, the notes in full, how to reshape the line and the route's sources (the owner's choice 5).
  // Go's notes wrap on the sheet, so Info does not say them again; its sources are behind Data sources (the owner's P1).
  const infoBody = (
    <div id={infoId} className="route-info" hidden={!info}>
      {/* Go's Mass Ride: the four capacity figures, under the one line the sheet shows (P6); Plan shows them as they were. */}
      {goMode && <CapacityStats route={route} corkers={corkerFigure(route, profile, rideSize)} />}
      {bikeshare && <p className="hint">{t("These figures are for the ride between the docks. The walks are above.")}</p>}
      {transit && transit.scheduled && (
        <p className="hint">{t("The distance, climb and stress are for the first ride, the line on the map. The whole trip is in its steps.")}</p>
      )}
      {pace && <p className="hint pace">{t("Moving time at {pace}, without stops.", { pace })}</p>}
      {/* Go's sheet shows a note whole, so Info gives only the ones it shortened (P1 with P14). */}
      {notes
        .filter((note) => !goMode || note.short)
        .map((note) => (
          <p key={note.key} className="hint note-full">
            {note.text}
          </p>
        ))}
      {/* Riders often arrive by a shared link, straight into a route, and a
          phone has no hover to show the handle: say that the line moves. */}
      <p className="hint reshape">
        {narrow ? t("To reshape the route, press and hold the line, then drag it.") : t("To reshape the route, drag the line.")}
      </p>
      {goMode ? (
        <details className="route-credit-fold">
          <summary>{t("Data sources")}</summary>
          {credit}
        </details>
      ) : (
        credit
      )}
    </div>
  );
  const infoButton = (
    <button type="button" className="link icon-button info-button route-info-button" aria-expanded={info} aria-controls={infoId} onClick={() => setInfo(!info)}>
      <Icon name="info" />
      <span>{t("Info")}</span>
    </button>
  );
  const noteList =
    notes.length > 0 ? (
      <ul className="note-lines" role="list">
        {notes.map((note) => (
          <li key={note.key} className={`note-line ${note.className}${note.short ? " note-wrap" : ""}`}>
            <Icon name={note.icon} size={16} />
            {note.short ? (
              <>
                <span className="note-text" aria-hidden="true">
                  {note.short}
                </span>
                <span className="visually-hidden">{note.text}</span>
              </>
            ) : (
              <span className="note-text">{note.text}</span>
            )}
          </li>
        ))}
      </ul>
    ) : null;
  const bikeshareFold = bikeshare ? (
    // The bikeshare plan, as a fold kept open (the mockup's table: "Same: a fold, open").
    <Fold title={t("Bikeshare plan")} open className="bikeshare-fold" icon="bikeshare">
      <BikeshareSummary plan={bikeshare} onEnding={onEnding} />
    </Fold>
  ) : null;

  const transitFold = transit ? (
    // The trip, as a fold kept open: the step list is the plan (the owner, 2026-10-12: "a clear step list").
    <Fold title={t("{ride} trip", { ride: presetLabel(preset) })} said={t("{ride} trip", { ride: presetSaid(preset) })} open className="transit-fold" icon="train">
      <TransitSummary
        plan={transit}
        lineSpans={route.stress_spans}
        preset={preset}
        onPick={transitControls?.onPick}
        busy={transitControls?.busy}
        announce={transitControls?.announce}
        onMissed={transitControls?.onMissed}
        onRideRest={restOffered(rideTripOf(route, points)) ? transitControls?.onRideRest : undefined}
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
          <h3 className="visually-hidden">{t("Totals")}</h3>
          <dl className="stats totals go-totals">
            <div className="total-time">
              <dt className="visually-hidden">{timeName}</dt>
              <dd>{timeShown}</dd>
            </div>
            {!noBike && (
              <div className="stat-distance">
                <dt className="visually-hidden">{transit ? t("Distance ridden") : t("Distance")}</dt>
                <dd>{formatDistance(trip.distance_m)}</dd>
              </div>
            )}
            {go.peek && alertCount > 0 ? (
              <div className="total-alerts">
                <dt className="visually-hidden">{t("Warnings")}</dt>
                <dd>
                  <Icon name="warn" size={14} />
                  {alertCount === 1 ? t("1 alert") : t("{count} alerts", { count: alertCount })}
                </dd>
              </div>
            ) : noBike ? null : (
              <div className="total-climb">
                <dt className="visually-hidden">{t("Climb")}</dt>
                <dd>
                  {/* Styled as the figure (P3): a press opens the Hills slider, for a flatter (or hillier) route. */}
                  {go.onClimb ? (
                    <button type="button" className="go-climb" onClick={(event) => go.onClimb?.(event.currentTarget)} aria-describedby="go-climb-hint">
                      <Icon name="mountain" size={14} />
                      {formatClimb(trip.climb_m)}
                      <span id="go-climb-hint" hidden>
                        {t("Opens the Hills setting.")}
                      </span>
                    </button>
                  ) : (
                    <>
                      <Icon name="mountain" size={14} />
                      {formatClimb(trip.climb_m)}
                    </>
                  )}
                </dd>
              </div>
            )}
          </dl>
          {!go.peek && infoButton}
        </div>
        {/* An NWS alert, one line under the totals (the owner's P1: it sat after the ride types), red for Severe or
            Extreme; its notice behind the link. At peek the totals count it. */}
        {!go.peek && <WeatherLines report={weather} riding={false} now={Date.now()} part="alerts" />}
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
        {segments.length > 0 && <StressFigure segments={segments} line={groupLine} go={{ route, peek: go.peek, onKey: go.onStressKey }} />}
        {!go.peek && <CapacityShort route={route} corkers={corkerShort(route, profile, rideSize)} />}
        {!go.peek && go.routeCard}
        {!go.peek && go.addStop}
        {!go.peek && go.rides && (
          <div className="go-route-rides">
            {/* Shown, as the route card says what it edits; the chips' group is named "Ride type" for a screen reader. */}
            <p className="go-rides-label" aria-hidden="true">
              {t("Ride type")}
            </p>
            {go.rides}
          </div>
        )}
        {!go.peek && alerts}
        {!go.peek && noteList}
        {!go.peek && actions.savedNote}
        {/* The routes and Save; the ride type and Plan in detail moved (edit-route redesign): the ride types sit
            under the route card, and the Go/Plan switch at the top is Plan in detail. */}
        {!go.peek && (picker || actions.save) && (
          <div className="go-chips" role="group" aria-label={t("Route options")}>
            {picker && (
              <button type="button" className="chip go-routes-chip" aria-expanded={routesOpen} aria-controls={routesId} onClick={() => setRoutesOpen(!routesOpen)}>
                {t("{count} routes", { count: pickerCount })}
              </button>
            )}
            {/* Shown "Save", named "Save route" (review F15: one row at 390 px with the ride type, the routes and Plan). */}
            {actions.save && <SaveRoute {...actions.save} label={SAVE_ROUTE} shown={SAVE_SHORT} chip />}
          </div>
        )}
        {/* The elevation chart (Stephen 2026-10-13: "on Go, add an elevation chart to the map as well, even if
            relatively flat"), at the full sheet only (review F8: at half it made the sheet more than a screen), under
            the route's options; its key and tables stay in Plan. */}
        {go.full && profile && chartKind(route) !== "mass" && <ElevationChart route={trip} profile={profile} onScrub={onScrub} compact />}
        {!go.peek && picker && (
          <div id={routesId} className="go-routes" hidden={!routesOpen}>
            {picker}
          </div>
        )}
        {/* Start ride and Broadcast last, pinned to the sheet's bottom edge (sticky, styles.css), where a thumb
            reaches, at every size: at peek they were beside the totals, and Broadcast was cut off at 390 px. The
            page's one Start ride (the owner's P1, 2026-10-28: the map's bar had a second), last in the order as it
            is last on screen. */}
        {(start || startHint) && (
          <div className="actions start-ride go-start">
            {start}
            {startHint}
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
        <h3 className="visually-hidden">{t("Totals")}</h3>
        <dl className="stats totals">
          <div className="total-time">
            <dt className="visually-hidden">{timeName}</dt>
            <dd>{timeShown}</dd>
          </div>
          {/* No distance ridden or climb on a transit option with no ride (P10): "No bike on this option" says why. */}
          {!noBike && (
            <>
              <div className="stat-distance">
                <dt className="visually-hidden">{transit ? t("Distance ridden") : t("Distance")}</dt>
                <dd>{formatDistance(trip.distance_m)}</dd>
              </div>
              <div className="total-climb">
                <dt className="visually-hidden">{t("Climb")}</dt>
                <dd>
                  <span aria-hidden="true">↑ </span>
                  {formatClimb(trip.climb_m)}
                </dd>
              </div>
              <div className="total-descent">
                <dt className="visually-hidden">{t("Descent")}</dt>
                <dd>
                  <span aria-hidden="true">↓ </span>
                  {formatClimb(trip.descent_m)}
                </dd>
              </div>
            </>
          )}
        </dl>
        {infoButton}
      </div>
      {infoBody}
      {transitFold}
      <CapacityStats route={route} corkers={corkerFigure(route, profile, rideSize)} />
      {segments.length > 0 && <StressFigure segments={segments} />}
      {alerts}
      {noteList}
      {actions.savedNote}
      <div className="actions start-ride">
        <RouteActions {...actions} start={start} />
        {/* Plan streamline (Stephen 2026-10-17): the how-to is Start's description, out of sight; the too-long line shows. */}
        {rideable ? <div className="visually-hidden">{startHint}</div> : startHint}
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
          name={ROUTE_FOLD_GROUP}
        >
          {profile && <ElevationChart route={trip} profile={profile} onScrub={onScrub} rideSize={rideSize} />}
          {/* The climbs on the route (the Climbs layer's list), in this fold (the mockup's table). */}
          {climbs && <ClimbsAlongList items={climbs} headingId="climbs-along-planner-heading" level="h4" />}
        </Fold>
      )}
      {capacity && (
        // A Mass Ride's fold is about riders per minute, in place of the stress and facility figures (OWNER-DECISIONS 325).
        <Fold title={CAPACITY_FOLD_TITLE} heading={CAPACITY_FOLD_TITLE} open={ROUTE_FOLDS.facilities.open} icon="road" name={ROUTE_FOLD_GROUP}>
          <CapacityFigures route={route} />
        </Fold>
      )}
      {!capacity && (
        <Fold
          title={ROUTE_FOLDS.facilities.title}
          heading={ROUTE_FOLDS.facilities.title}
          open={ROUTE_FOLDS.facilities.open}
          icon="road"
          count={calm === null || noBike ? null : t("{percent}% quiet", { percent: calm })}
          className="facilities-fold"
          name={ROUTE_FOLD_GROUP}
        >
          {/* The four quick figures, first in the fold (the owner's choice 4). */}
          <QuickFigures figures={quickFigures(route)} />
          {segments.length > 0 && (
            <figure className="stress" aria-labelledby="stress-detail-caption">
              <figcaption id="stress-detail-caption">{t("Traffic stress, stretch by stretch")}</figcaption>
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
      <RouteDescription route={route} fold federal={federal} />
      {junctions !== null && (
        <Fold title={ROUTE_FOLDS.junctions.title} count={junctions} heading={ROUTE_FOLDS.junctions.title} open={ROUTE_FOLDS.junctions.open} icon="junction" name={ROUTE_FOLD_GROUP}>
          <IntersectionList route={route} onSelect={onSelectJunction} />
        </Fold>
      )}
      {picker && (
        <Fold title={ROUTE_FOLDS.choices.title} count={pickerCount} heading={ROUTE_FOLDS.choices.title} open={ROUTE_FOLDS.choices.open} icon="routes" name={ROUTE_FOLD_GROUP}>
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
          name={ROUTE_FOLD_GROUP}
        >
          <WaterAlongList items={water.items} onAddStop={water.onAddStop} headingId="water-along-planner-heading" level="h4" />
        </Fold>
      )}
    </div>
  );
}
