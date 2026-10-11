// Moved out of App.tsx unchanged (UI-CLEANUP step 4, docs/DEVELOPMENT.md "The App.tsx split"): the same
// elements, in the same order, with App's state and handlers passed in under the names App gives them,
// so the DOM, the focus and every announcement are as they were. App.tsx keeps the state and the effects.
import type { Dispatch, ReactNode, RefObject, SetStateAction } from "react";
import type { RouteError, RouteResponse } from "../lib/api.ts";
import type { LonLat } from "../lib/geo.ts";
import { formatClimb, formatDistance, formatDuration } from "../lib/format.ts";
import type { PresetId } from "../lib/presets.ts";
import { stressSegments } from "../lib/stressBar.ts";
import { calmSearchNote, detourView, paceText, stillPlanningSaid, movedPointsNote } from "../lib/summary.ts";
import { isCancelKey } from "../lib/sheet.ts";
import { useStressStyle } from "../useStressStyle.ts";
import { CandidatePicker } from "../lib/candidatePicker.ts";
import { candidateRows } from "../lib/candidates.ts";
import { loopNote } from "../lib/loop.ts";
import { FacilityBreakdown } from "../FacilityBreakdown.tsx";
import { IntersectionList } from "../IntersectionList.tsx";
import { AvoidNotice } from "../AvoidNotice.tsx";
import { avoidItems } from "../lib/avoidJunctions.ts";
import { ElevationChart } from "../ElevationChart.tsx";
import { chartKind, corkerFigure, foldName, usableProfile } from "../lib/profileChart.ts";
import { RouteDescription } from "../RouteDescription.tsx";
import { RIDE_SAFETY, RideSettingsFields } from "../RideMode.tsx";
import type { RidePrefs } from "../lib/rideOutput.ts";
import { RIDE_MAX_M, RIDE_TOO_LONG } from "../lib/navigate.ts";
import { BikeshareSummary } from "../BikeshareSummary.tsx";
import { bikeshareOf, routeCredits } from "../lib/bikeshare.ts";
import { rideSizeOf, type Dials, type Ending } from "../lib/dials.ts";
import { CAPACITY_FOLD_TITLE, capacitySummary } from "../lib/massCapacity.ts";
import { CapacityFigures, CapacityStats } from "../lib/massLegend.ts";
import { outsideDcNote } from "../lib/dcBoundary.ts";
import { downloadGpx } from "../GpxPanel.tsx";
import { Fold, QuickFigures } from "../Sidebar.tsx";
import { COPY_LINK, ROUTE_FOLDS, chartFoldOpen, foldTitle } from "../lib/sidebar.ts";
import { SHARE_LABEL, SHARE_NAME } from "../lib/share.ts";
import { quickFigures, stressBarKey, stressBarLabel } from "../lib/quickFigures.ts";
import { junctionItems } from "../lib/intersectionMarkers.ts";
import type { WaterAlong, WaterStatus } from "../lib/waterRestrooms.ts";
import { WaterAlongList } from "../lib/waterLegend.ts";
import type { ClimbAlong, ClimbsStatus } from "../lib/climbs.ts";
import { ClimbsAlongList } from "../lib/climbsLegend.ts";
import { KEEP_LABEL } from "../lib/offlineRoutes.ts";

export type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "waiting"; seconds: number }
  | { kind: "ok" }
  | { kind: "error"; error: RouteError }
  | { kind: "confirm"; error: RouteError };

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
  waterOn: boolean;
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
}

/** The planner's Route section: planning, the long-ride question, errors, the route summary, water along it and Start ride's question. */
export function RouteSection(props: RouteSectionProps) {
  const { stale, routeHeadingRef, status, announcement, slow, preset, dials, points, cancelLong, planButtonRef, confirmLong, errorRef, retry, shown, answer, choice, aroundAvoid, setAroundAvoid, routedPoints, federalRoute, narrow, setJunctionFocus, setScrubPoint, choose, startRide, startRideRef, rideSize, setDials, waterOn, waterStatus, waterAlong, addWaterStop, rideAsk, setRideAsk, backToRideOpener, ridePrefs, changeRidePrefs, rideStartFirstRef, beginRide, climbsOn, climbsStatus, climbsAlong } = props;
  return (
    <section key="route" aria-labelledby="route-heading" aria-busy={stale}>
      <h2 id="route-heading" ref={routeHeadingRef} tabIndex={-1}>
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
      {status.kind === "idle" && points.length < 2 && <p className="hint">No route yet.</p>}
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
      {/* First in the panel and announced first (335): the route goes through an Avoid-rated junction. */}
      {shown && answer && <AvoidNotice answer={answer} choice={choice} around={aroundAvoid} onAround={setAroundAvoid} />}
      {shown && (
        <RouteSummary
          route={shown}
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
        />
      )}
      {shown && waterOn && waterStatus === "ready" && (
        <WaterAlongList items={waterAlong} onAddStop={addWaterStop} headingId="water-along-planner-heading" level="h3" />
      )}
      {shown && climbsOn && climbsStatus === "ready" && (
        <ClimbsAlongList items={climbsAlong} headingId="climbs-along-planner-heading" level="h3" />
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

/** Pinned under the scrolling part while a route is shown: Download GPX, Copy link, Share and Keep for offline. */
export function RouteActions(props: RouteActionsProps) {
  const { shown, routedPoints, routedLoop, federalRoute, copyLink, linkNote, canShare, shareRoute, linkSpoken, keepShown, keepForOffline, keeping, keepSpoken, linkSaid } = props;
  return (
    <div className="route-actions">
      <button type="button" onClick={() => downloadGpx(shown, routedPoints, routedLoop, federalRoute)}>
        Download GPX
      </button>
      <button type="button" className="secondary" onClick={copyLink} aria-describedby={linkNote ? "link-note" : undefined}>
        {COPY_LINK}
      </button>
      {canShare && (
        <button type="button" className="secondary" onClick={shareRoute} aria-label={SHARE_NAME} aria-describedby={linkNote ? "link-note" : undefined}>
          {SHARE_LABEL}
        </button>
      )}
      <span role="status" className="visually-hidden">
        {linkSpoken}
      </span>
      {keepShown && (
        <>
          <button type="button" className="secondary keep-offline" onClick={() => void keepForOffline()} aria-disabled={keeping} aria-describedby="keep-offline-said">
            {KEEP_LABEL}
          </button>
          <p id="keep-offline-said" className="hint keep-said" role="status">
            {keepSpoken.text}
            {keepSpoken.count % 2 === 1 ? " " : ""}
          </p>
        </>
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

export function RouteSummary({
  route,
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
}: {
  route: RouteResponse;
  points: LonLat[];
  /** A Mass Ride's federal-land lines for the description (lib/federalStops.ts federalLines, item 239). */
  federal: readonly string[];
  narrow: boolean;
  /** Ride mode's Start ride (WEB-NAV-plan.md Q1): offered under the figures and with the directions. */
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
}) {
  useStressStyle();
  // A Mass Ride's panel is about riders per minute, in place of the LTS breakdown (OWNER-DECISIONS 325).
  const capacity = capacitySummary(route.stress_spans);
  const segments = capacity ? [] : stressSegments(route.stress_m);
  const detour = detourView(route, points);
  const calmNote = calmSearchNote(route);
  const loopSaid = loopNote(route);
  // A Mass Ride that leaves the District (OWNER-DECISIONS 418a): shown here, and said in the route's
  // live region with the rest of the route's sentence (lib/summary.ts announceRoute).
  const outsideDc = outsideDcNote(route);
  // A point inside the National Zoo was moved to its bike racks (291(4)): shown here, and said with the route.
  const moved = movedPointsNote(route, points.length);
  const pace = paceText(route);
  // The sidebar's route view (OWNER-DECISIONS 312): the totals, the stress bar and four quick
  // figures in view; Elevation and stress (322; Riders per minute, corker load and elevation on a Mass Ride),
  // Stress and facilities, Directions, Junctions to watch and Routes to choose from as folds.
  const profile = usableProfile(route);
  // The Avoid-rated junctions count with the rest, and keep the fold where the others could not be read.
  const avoidCount = avoidItems(route).length;
  const junctions = route.intersections == null ? (avoidCount > 0 ? avoidCount : null) : junctionItems(route).length + avoidCount;
  const bikeshare = bikeshareOf(route);
  // Start ride is offered with the directions too (plan Q1). Not on a Bikeshare plan: the route
  // is only the ride between the docks, so the walk to the first dock would read as off route.
  const rideable = !bikeshare && route.distance_m <= RIDE_MAX_M;
  const rideAction = rideable ? (
    <button type="button" className="secondary" onClick={ride.onStart}>
      Start ride
    </button>
  ) : null;
  return (
    <div className="summary">
      {bikeshare && <BikeshareSummary plan={bikeshare} onEnding={onEnding} />}
      {moved && (
        <p className="notice moved-points" role="note">
          {moved}
        </p>
      )}
      {outsideDc && (
        <p className="notice mass-outside-dc" role="note">
          {outsideDc}
        </p>
      )}
      {detour && (
        <p className={`notice detour detour-${detour.level}`} role="note">
          {detour.text}
        </p>
      )}
      {calmNote && (
        <p className="hint calm-search" role="note">
          {calmNote}
        </p>
      )}
      {loopSaid && (
        <p className="hint loop-note" role="note">
          {loopSaid}
        </p>
      )}
      {/* Headings for a screen reader's list, out of sight: the route's figures, then each fold (the a11y review's S5). */}
      <h3 className="visually-hidden">Totals</h3>
      <dl className="stats totals">
        <div className="stat-distance">
          <dt>Distance</dt>
          <dd>{formatDistance(route.distance_m)}</dd>
        </div>
        <div>
          <dt>Moving time</dt>
          <dd>{formatDuration(route.duration_s)}</dd>
        </div>
        <div>
          <dt>Climb</dt>
          <dd>{formatClimb(route.climb_m)}</dd>
        </div>
        <div>
          <dt>Descent</dt>
          <dd>{formatClimb(route.descent_m)}</dd>
        </div>
      </dl>
      {bikeshare && <p className="hint">These figures are for the ride between the docks. The walks are above.</p>}
      {pace && <p className="hint pace">Moving time at {pace}, without stops.</p>}
      <CapacityStats route={route} corkers={corkerFigure(route, profile, rideSize)} />
      {segments.length > 0 && (
        <figure className="stress stress-main" aria-labelledby="stress-figure-caption">
          <figcaption id="stress-figure-caption">Traffic stress along the route</figcaption>
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
      )}
      <QuickFigures figures={quickFigures(route)} />
      {/* Start ride (WEB-NAV-plan.md Q1): short rides only; a longer one goes to a bike computer (OD 255). */}
      {rideable ? (
        <div className="actions start-ride">
          <button type="button" ref={ride.startRef} onClick={ride.onStart}>
            Start ride
          </button>
          <p className="hint">Turn-by-turn directions on this phone, said as you chose. Keep the screen on and this page in front.</p>
        </div>
      ) : bikeshare ? null : (
        <p className="hint start-ride-long">{RIDE_TOO_LONG}</p>
      )}
      <FacilityBreakdown route={route} part="notices" />
      {profile && (
        <Fold
          title={foldName(chartKind(route))}
          heading={foldName(chartKind(route))}
          // Offered collapsed on a small screen (OWNER-DECISIONS 322); open beside the map.
          open={chartFoldOpen(narrow)}
        >
          <ElevationChart route={route} profile={profile} onScrub={onScrub} rideSize={rideSize} />
        </Fold>
      )}
      {capacity && (
        // A Mass Ride's fold is about riders per minute, in place of the stress and facility figures (OWNER-DECISIONS 325).
        <Fold title={CAPACITY_FOLD_TITLE} heading={CAPACITY_FOLD_TITLE} open={ROUTE_FOLDS.facilities.open}>
          <CapacityFigures route={route} />
        </Fold>
      )}
      {!capacity && (
      <Fold title={ROUTE_FOLDS.facilities.title} heading={ROUTE_FOLDS.facilities.title} open={ROUTE_FOLDS.facilities.open}>
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
        <Fold title={foldTitle(ROUTE_FOLDS.junctions.title, junctions)} heading={ROUTE_FOLDS.junctions.title} open={ROUTE_FOLDS.junctions.open}>
          <IntersectionList route={route} onSelect={onSelectJunction} />
        </Fold>
      )}
      {picker && (
        <Fold title={foldTitle(ROUTE_FOLDS.choices.title, pickerCount)} heading={ROUTE_FOLDS.choices.title} open={ROUTE_FOLDS.choices.open}>
          {picker}
        </Fold>
      )}
      {/* Riders often arrive by a shared link, straight into a route, and a
          phone has no hover to show the handle: say that the line moves. */}
      <p className="hint reshape">
        {narrow
          ? "To reshape the route, press and hold the line, then drag it."
          : "To reshape the route, drag the line."}
      </p>
      <p className="route-credit">Route data: {routeCredits(route).join("; ")}.</p>
    </div>
  );
}
