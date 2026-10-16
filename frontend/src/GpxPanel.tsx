import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { RouteResponse } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import { writeGpx } from "./lib/gpx.ts";
import { REFINE_ROUNDS, nextFitStep, prunedCount, startFit, type Fit, type ImportedPlan } from "./lib/gpxPlan.ts";
import { gpxWorker, importGpx } from "./lib/gpxImport.ts";
import { exportFileName, exportOf, fidelityNotice, importSentences, presetNotice, prunedNotice } from "./lib/gpxText.ts";
import { showReference, showWaypoints } from "./lib/referenceLayer.ts";
import { MATCHING_SAID, MATCH_ACTION, MATCH_HINT, fitLine, matchFailedSaid, matchTrack, matchedPlan, matchedSaid } from "./lib/gpxMatch.ts";
import type { PresetId } from "./lib/presets.ts";
import { VIA_MARKS, viaIndices } from "./lib/pointKinds.ts";
import { fidelity } from "./lib/trackMatch.ts";
import type { FileDownload } from "./lib/gpxVerbatim.ts";
import { compileCourse, courseFileName, courseLine, type CourseFormat } from "./lib/course.ts";
import { DEFAULT_PROFILE, DEVICE_PROFILES, deviceProfile, type DeviceProfileId } from "./lib/deviceProfiles.ts";
import { writeFit } from "./lib/fit.ts";
import { writeTcx } from "./lib/tcx.ts";
import { cueSheetDocument, cueSheetFileName, cueSheetLine, type CueSheetKind } from "./lib/cueSheetPdf.ts";
import { lockCancelledLine, lockPartButton, lockPartLine, lockScreenFileNames, lockScreenLine, lockSharedLine } from "./lib/lockScreen.ts";
import { renderLockScreens } from "./app/lockScreenRender.ts";

export type GpxPanelProps = Props;

interface Props {
  /** The route on screen, or null. */
  route: RouteResponse | null;
  /** The points that route was planned through. */
  routedPoints: LonLat[];
  /** That route was planned as a loop the rider chose (OWNER-DECISIONS 374), as its points were named then. */
  loop?: boolean;
  /** The plan's points now. */
  points: LonLat[];
  /** Where the planner is with them (App's status). */
  planStatus: "idle" | "loading" | "waiting" | "ok" | "error" | "confirm";
  /** The file opened last, until the plan is cleared. */
  imported: ImportedPlan | null;
  onImport: (plan: ImportedPlan) => void;
  /** Replace the plan's points with a closer fit to the opened track. */
  onRefine: (points: LonLat[]) => void;
  getMap: () => MapLibreMap | null;
  /** A Mass Ride's federal-land lines, for the file's description (lib/federalStops.ts, item 239). */
  federal?: readonly string[];
  /**
   * Download GPX through the page (v0.7.0): closures are checked first, and an opened file not edited since
   * downloads as the file it came from. Without it, the route shown is written here.
   */
  onDownload?: (said: (line: string) => void) => void;
  /**
   * Download a FIT or TCX course or a PDF cue sheet through the page, closures checked first as for GPX; `said`
   * takes the line saying what was made. Given in Plan only: without it (Go) the section offers GPX alone.
   */
  onDownloadCourse?: (format: FileFormat, profile: DeviceProfileId, said: Said) => void;
  /**
   * Plan only: snap an opened track to the map's ways (lib/gpxMatch.ts) on the ride type now chosen, and open
   * the plan that follows the snapped line (`onMatched`, one edit). Without it (Go) the action is not offered.
   */
  match?: { preset: PresetId; onMatched: (plan: ImportedPlan) => void };
}

function samePoints(a: readonly LonLat[], b: readonly LonLat[]): boolean {
  return a.length === b.length && a.every((p, i) => p[0] === b[i][0] && p[1] === b[i][1]);
}

function bounds(line: readonly LonLat[]): [number, number, number, number] {
  let [west, south, east, north] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [lon, lat] of line) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [west, south, east, north];
}

/**
 * The route shown as a GPX file, built here from it (gpx.ts): its text and file name. What Download GPX saves and
 * what Share attaches (v0.7.0, "share the identical route").
 */
export function routeGpxFile(route: RouteResponse, routedPoints: LonLat[], loop: boolean, federal: readonly string[] = []): FileDownload {
  return { text: writeGpx(exportOf(route, routedPoints, loop, federal, viaIndices(routedPoints, VIA_MARKS.isVia))), fileName: exportFileName(route) };
}

/**
 * Download the route shown as a GPX file (routeGpxFile). Shared by this panel's Download GPX and the sidebar's
 * pinned one (App.tsx, OWNER-DECISIONS 312).
 */
export function downloadGpx(route: RouteResponse, routedPoints: LonLat[], loop: boolean, federal: readonly string[] = []): void {
  const file = routeGpxFile(route, routedPoints, loop, federal);
  const blob = new Blob([file.text], { type: "application/gpx+xml" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.fileName;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** Save bytes or text as a file (the browser's download). */
function saveFile(body: BlobPart, type: string, fileName: string): void {
  const blob = new Blob([body], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** The PDF cue sheets, by file type (lib/cueSheetPdf.ts). */
const PRINTS = { "pdf-sheet": "sheet", "pdf-strip": "strip" } as const satisfies Record<string, CueSheetKind>;

/** Every file type but GPX: the courses and the PDF cue sheets. */
export type FileFormat = CourseFormat | keyof typeof PRINTS | "png-lock";

/** Said where the lock-screen image could not be drawn (the canvas refused it). */
export const LOCK_IMAGE_FAILED = "Could not make the cue sheet image. Try again, or use the PDF handlebar strip.";

/** Save the lock-screen images one after another (a browser takes a moment between downloads), then say what was made. */
/** Lock-screen images not yet saved: a browser saves only one file per press, so each further part waits for one. */
export interface PartQueue {
  blobs: Blob[];
  names: string[];
  /** The index of the next part to save. */
  next: number;
  cues: number;
}

/** What a download says: a line, and for the lock-screen images any parts still to save. */
export type Made = string | { line: string; queue: PartQueue | null };
export type Said = (made: Made) => void;

/**
 * The lock-screen images: one is saved; several go to the share sheet together where the browser can share files
 * (a phone's, which is where they are wanted), and otherwise part 1 is saved and the button saves each next part.
 * The line says only what was actually saved or sent.
 */
async function downloadLockScreens(route: RouteResponse, vias: readonly number[]): Promise<Made> {
  try {
    const { pages, blobs } = await renderLockScreens(route, vias);
    const names = lockScreenFileNames(route, blobs.length);
    if (blobs.length === 1) {
      saveFile(blobs[0], "image/png", names[0]);
      return lockScreenLine(pages);
    }
    const cues = pages.reduce((n, p) => n + p.cues, 0);
    const queue = (next: number): PartQueue => ({ blobs, names, next, cues });
    const files = blobs.map((b, i) => new File([b], names[i], { type: "image/png" }));
    if (typeof navigator.canShare === "function" && navigator.canShare({ files })) {
      try {
        await navigator.share({ files });
        return { line: lockSharedLine(blobs.length, cues), queue: null };
      } catch (error) {
        if ((error as Error)?.name === "AbortError") return { line: lockCancelledLine(blobs.length), queue: queue(0) };
        // Refused (no gesture left after drawing, say): saved one at a time instead.
      }
    }
    saveFile(blobs[0], "image/png", names[0]);
    return { line: lockPartLine(1, blobs.length, cues), queue: queue(1) };
  } catch {
    return LOCK_IMAGE_FAILED;
  }
}

/**
 * Download the route shown as a FIT or TCX course fitted to a device profile (lib/course.ts), or as a PDF cue sheet
 * (lib/cueSheetPdf.ts), and return the one line saying what was made. Its cues are Ride's; its via points are not
 * cues, as in Ride.
 */
export function downloadCourse(route: RouteResponse, routedPoints: LonLat[], format: FileFormat, profile: DeviceProfileId): string | Promise<Made> {
  const vias = viaIndices(routedPoints, VIA_MARKS.isVia);
  if (format === "png-lock") return downloadLockScreens(route, vias);
  if (format === "pdf-sheet" || format === "pdf-strip") {
    const kind = PRINTS[format];
    const made = cueSheetDocument(route, kind, vias);
    saveFile(made.bytes, "application/pdf", cueSheetFileName(route, kind));
    return cueSheetLine(route, kind, vias, made.pages);
  }
  const course = compileCourse(route, deviceProfile(profile), format, vias);
  const fileName = courseFileName(route, format);
  if (format === "fit") saveFile(writeFit(course), "application/vnd.ant.fit", fileName);
  else saveFile(writeTcx(course), "application/vnd.garmin.tcx+xml", fileName);
  return courseLine(course);
}

export type ExportFormat = "gpx" | FileFormat;

/** What a GPX download says once it is saved: the route shown, the opened file as it came, or its track. */
export const GPX_SAID_ROUTE = "GPX track: the route shown, with its credits.";
export const GPX_SAID_OPENED = "GPX file: the file you opened, as it came.";
export const GPX_SAID_TRACK = "GPX track: the opened file's track, rerouted round the closures.";

const FORMAT_LABELS: Record<ExportFormat, string> = {
  gpx: "GPX track",
  fit: "FIT course, with turn cues",
  tcx: "TCX course, with turn cues",
  "pdf-sheet": "PDF cue sheet, to print",
  "pdf-strip": "PDF handlebar strip, to print",
  "png-lock": "Cue sheet image, for a phone lock screen",
};

/** What the button says it downloads. */
const FORMAT_WORDS: Record<ExportFormat, string> = { gpx: "GPX", fit: "FIT", tcx: "TCX", "pdf-sheet": "PDF", "pdf-strip": "PDF", "png-lock": "image" };

const isCourse = (format: ExportFormat): format is CourseFormat => format === "fit" || format === "tcx";

/** The file type and device chosen last, on this device only (a convenience: the defaults stand without it). */
const CHOICE_KEY = "routemaker.exportChoice";

function readChoice(): { format: ExportFormat; profile: DeviceProfileId } {
  try {
    const saved = JSON.parse(localStorage.getItem(CHOICE_KEY) ?? "null") as { format?: string; profile?: string } | null;
    const format = saved?.format && Object.hasOwn(FORMAT_LABELS, saved.format) ? (saved.format as ExportFormat) : "gpx";
    return { format, profile: deviceProfile(saved?.profile).id };
  } catch {
    return { format: "gpx", profile: DEFAULT_PROFILE };
  }
}

function keepChoice(format: ExportFormat, profile: DeviceProfileId): void {
  try {
    localStorage.setItem(CHOICE_KEY, JSON.stringify({ format, profile }));
  } catch {
    // Storage refused: the choice lasts for this page only.
  }
}

type Reading = { kind: "idle" } | { kind: "reading"; name: string } | { kind: "error"; message: string };

/**
 * Open and download GPX, signed out. Both happen in this browser: the opened
 * file is read here (gpxImport.ts) and the download is built here from the
 * route on screen (gpx.ts). Nothing is sent or saved.
 */
export function GpxPanel(props: Props) {
  const { route, routedPoints, points, planStatus, imported, onImport, onRefine, getMap, onDownload, onDownloadCourse, loop = false, federal = [] } = props;
  const [kept, setChoice] = useState(readChoice);
  // Go adds no control (the owner's rule): there, the file type is GPX and no choice is shown.
  const courses = onDownloadCourse !== undefined;
  const choice = courses ? kept : { ...kept, format: "gpx" as ExportFormat };
  const choose = (next: Partial<typeof choice>) => {
    const made = { ...kept, ...next };
    setChoice(made);
    keepChoice(made.format, made.profile);
  };
  // What the last course download fitted to the device, said in the status region below; a new route, another
  // file type or another device clears it.
  const [courseSaid, setCourseSaid] = useState<{ text: string; count: number } | null>(null);
  // Lock-screen images still to save, one per press of the same button ("Download part 2 of 6").
  const [parts, setParts] = useState<PartQueue | null>(null);
  useEffect(() => {
    setCourseSaid(null);
    setParts(null);
  }, [route, choice.format, choice.profile]);
  const sayCourse: Said = (made) => {
    setParts(typeof made === "string" ? null : made.queue && made.queue.next < made.queue.blobs.length ? made.queue : null);
    const text = typeof made === "string" ? made : made.line;
    setCourseSaid((s) => ({ text, count: (s?.count ?? 0) + 1 }));
  };
  const saveNextPart = (queue: PartQueue) => {
    saveFile(queue.blobs[queue.next], "image/png", queue.names[queue.next]);
    const saved = queue.next + 1;
    sayCourse({ line: lockPartLine(saved, queue.blobs.length, queue.cues), queue: { ...queue, next: saved } });
  };
  const input = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState<Reading>({ kind: "idle" });
  const [showTrack, setShowTrack] = useState(true);
  const [fit, setFit] = useState<Fit | null>(null);
  // Points fitting took out because the route looped round for them, said once fitting ends
  // and for as long as the plan is the points it ended with.
  const [pruned, setPruned] = useState<{ count: number; points: LonLat[] } | null>(null);

  // An opened track is fitted in steps (gpxPlan.ts, nextFitStep): when the
  // route for the fitted points arrives, points go where it missed the track,
  // then points it had to loop round for are taken out, and the planner
  // routes again each time; a step that leaves the fit no better is undone.
  // It stops when nothing is left to try, or the rider changes the plan
  // themselves - their change is never overwritten.
  useEffect(() => {
    if (!fit) return;
    // A refusal ends it too: the rider has the error to act on, not a loop.
    if (!imported || !samePoints(points, fit.points) || planStatus === "error") {
      setFit(null);
      return;
    }
    if (!route || !samePoints(routedPoints, fit.points)) return;
    // Fitted to the snapped line once the track is snapped, else to the file's own.
    const next = nextFitStep(fitLine(imported), fit, route.geometry.coordinates, route.leg_ends);
    if (!next) {
      setPruned({ count: prunedCount(fit), points: fit.points });
      setFit(null);
      return;
    }
    setFit(next);
    onRefine(next.points);
  }, [fit, imported, points, planStatus, route, routedPoints, onRefine]);

  // The file's own line, faint, under the route.
  const reference = imported && showTrack && imported.reference.length >= 2 ? imported.reference : null;
  useEffect(() => {
    const map = getMap();
    if (map) showReference(map, reference);
  }, [reference, getMap]);
  // Its named waypoints, with its line (the same switch), or on their own when it has no line to show.
  const marks = imported?.marks && (showTrack || imported.reference.length < 2) ? imported.marks : null;
  useEffect(() => {
    const map = getMap();
    if (map) showWaypoints(map, marks);
  }, [marks, getMap]);

  // Snapping the opened track to the map's ways (lib/gpxMatch.ts): said in the status region below. A new file
  // clears what was said about the last one.
  const snap = props.match;
  const importedRef = useRef(imported);
  importedRef.current = imported;
  const [snapping, setSnapping] = useState<{ kind: "running" } | { kind: "failed"; text: string } | null>(null);
  // Another file (its own text and line): the last one's line goes. The snapped plan keeps the file's.
  useEffect(() => setSnapping(null), [imported?.verbatim]);
  const snappable = snap && imported?.source === "track" && imported.reference.length >= 2 && !imported.matched;
  const snapTrack = async () => {
    if (!snap || !imported || snapping?.kind === "running") return;
    const file = imported;
    setSnapping({ kind: "running" });
    const outcome = await matchTrack(window.location.origin, file.reference, snap.preset);
    // Another file opened meanwhile: this answer is about the last one.
    if (importedRef.current?.verbatim !== file.verbatim) return;
    if (!outcome.ok) {
      setSnapping({ kind: "failed", text: matchFailedSaid(outcome.message) });
      return;
    }
    setSnapping(null);
    const next = matchedPlan(file, outcome.line, outcome.share);
    setPruned(null);
    setFit(startFit(next.points));
    // The action goes once the track is snapped: the focus it had moves to the track's switch beside it.
    if (document.activeElement === snapRef.current) trackSwitchRef.current?.focus();
    snap.onMatched(next);
  };
  const snapRef = useRef<HTMLButtonElement>(null);
  const trackSwitchRef = useRef<HTMLInputElement>(null);

  const match = useMemo(() => {
    if (!imported || imported.reference.length < 2 || !route || fit) return null;
    return fidelityNotice(fidelity(imported.reference, route.geometry.coordinates));
  }, [imported, route, fit]);

  const open = async (file: File) => {
    setReading({ kind: "reading", name: file.name });
    const outcome = await importGpx(file, typeof Worker === "function" ? gpxWorker : null);
    if (outcome.ok) {
      setReading({ kind: "idle" });
      setShowTrack(true);
      setFit(outcome.plan.source === "track" ? startFit(outcome.plan.points) : null);
      setPruned(null);
      onImport(outcome.plan);
      frame(outcome.plan);
    } else {
      setReading({ kind: "error", message: outcome.message });
    }
  };

  // An opened file is shown whole, beside the panel rather than under it.
  // MapView moves only when a route leaves the view, and a file opened over
  // a wider view would otherwise be a speck in it.
  const frame = (plan: ImportedPlan) => {
    const map = getMap();
    const line = plan.reference.length >= 2 ? plan.reference : plan.points;
    if (!map || line.length < 2) return;
    const panel = document.querySelector(".panel")?.getBoundingClientRect();
    const narrow = window.matchMedia("(max-width: 720px)").matches;
    const padding = narrow
      ? { top: 40, left: 30, right: 30, bottom: (panel?.height ?? 0) + 90 }
      : { top: 60, bottom: 60, right: 60, left: (panel?.right ?? 0) + 40 };
    const [west, south, east, north] = bounds(line);
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding, maxZoom: 15, duration: 600 },
    );
  };

  const download = () => {
    // The route was checked when part 1 was made; each further part is saved as it is.
    if (parts && choice.format === "png-lock") {
      saveNextPart(parts);
      return;
    }
    if (choice.format !== "gpx") {
      onDownloadCourse?.(choice.format, choice.profile, sayCourse);
      return;
    }
    if (onDownload) onDownload(sayCourse);
    else if (route) {
      downloadGpx(route, routedPoints, loop, federal);
      sayCourse(GPX_SAID_ROUTE);
    }
  };

  return (
    <section aria-labelledby="gpx-heading" className="gpx">
      {/* The GPX sheet's own heading names it (App.tsx); this one stays for the section's name. */}
      <h3 id="gpx-heading" className="visually-hidden">
        Route file
      </h3>
      {courses && (
        <div className="gpx-format">
          <label className="select-setting">
            File type
            <select value={choice.format} onChange={(event) => choose({ format: event.target.value as ExportFormat })}>
              {(Object.keys(FORMAT_LABELS) as ExportFormat[]).map((format) => (
                <option key={format} value={format}>
                  {FORMAT_LABELS[format]}
                </option>
              ))}
            </select>
          </label>
          {isCourse(choice.format) && (
            <label className="select-setting">
              Device
              <select value={choice.profile} onChange={(event) => choose({ profile: event.target.value as DeviceProfileId })}>
                {DEVICE_PROFILES.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
      <div className="actions">
        {/* aria-disabled, not disabled: the focus the file picker gives back stays here while the file
            is read, and a press then does nothing (review a11y-9). */}
        <button
          type="button"
          onClick={() => {
            if (reading.kind !== "reading") input.current?.click();
          }}
          aria-disabled={reading.kind === "reading" || undefined}
        >
          Open GPX…
        </button>
        <button type="button" onClick={download} disabled={choice.format === "gpx" ? !route && !imported?.verbatim : !route}>
          {parts ? lockPartButton(parts.next, parts.blobs.length) : `Download ${FORMAT_WORDS[choice.format]}`}
        </button>
      </div>
      <input
        ref={input}
        type="file"
        accept=".gpx,application/gpx+xml"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          // The same file can be opened again after a change.
          event.target.value = "";
          if (file) void open(file);
        }}
      />
      <div role="status" aria-live="polite">
        {courseSaid && (
          <p key={courseSaid.count} className="hint gpx-course">
            {courseSaid.text}
          </p>
        )}
        {reading.kind === "reading" && <p className="loading">Reading {reading.name}…</p>}
        {reading.kind === "error" && (
          <p className="notice gpx-error">
            <strong>Can't open that file.</strong> {reading.message}
          </p>
        )}
        {reading.kind === "idle" && imported && (
          <div className="gpx-import">
            {presetNotice(imported) && <p className="notice gpx-preset-gone">{presetNotice(imported)}</p>}
            {importSentences(imported).map((sentence) => (
              <p key={sentence} className="hint">
                {sentence}
              </p>
            ))}
            {fit && ["loading", "waiting", "ok"].includes(planStatus) && (
              <p className="loading gpx-fitting">
                {fit.phase === "prune"
                  ? "Checking for points the route loops round to reach…"
                  : fit.rounds === 0
                    ? "Routing the plan along the file's track…"
                    : `Adding points where the route left the track (round ${fit.rounds} of up to ${REFINE_ROUNDS})…`}
              </p>
            )}
            {match && pruned && pruned.count > 0 && samePoints(points, pruned.points) && (
              <p className="hint gpx-pruned">{prunedNotice(pruned.count)}</p>
            )}
            {match && <p className={match.warn ? "notice gpx-deviation" : "hint gpx-fidelity"}>{match.text}</p>}
            {snapping?.kind === "running" && <p className="loading gpx-snapping">{MATCHING_SAID}</p>}
            {snapping?.kind === "failed" && <p className="notice gpx-snap-failed">{snapping.text}</p>}
            {imported.matched && <p className="hint gpx-snapped">{matchedSaid(imported.matched)}</p>}
          </div>
        )}
      </div>
      {imported && imported.reference.length >= 2 && (
        <label className="toggle">
          <input ref={trackSwitchRef} type="checkbox" checked={showTrack} onChange={(event) => setShowTrack(event.target.checked)} />
          Show the file's track on the map
        </label>
      )}
      {snappable && (
        <div className="actions gpx-snap">
          {/* aria-disabled while it runs, so the focus stays here (as Open GPX… does). */}
          <button ref={snapRef} type="button" className="secondary" onClick={() => void snapTrack()} aria-disabled={snapping?.kind === "running" || undefined} aria-describedby="gpx-snap-hint">
            {MATCH_ACTION}
          </button>
          <p id="gpx-snap-hint" className="hint">
            {MATCH_HINT}
          </p>
        </div>
      )}
      <p className="hint">
        A file you open is read in this browser and never uploaded (unless you save it to your account, or snap it to
        the map's streets, which sends its line alone). Opened and not
        edited, the download is that file as it came; otherwise it is the route shown, with its credits: ©
        OpenStreetMap contributors (ODbL) and the traffic and elevation sources.
      </p>
      {(choice.format === "pdf-sheet" || choice.format === "pdf-strip") && (
        <p className="hint">
          A cue sheet is the route shown with Ride's cues, to print: the sheet on letter paper, the strip at actual size
          to cut out for the handlebar. Its credits are at the foot of every page.
        </p>
      )}
      {choice.format === "png-lock" && (
        <p className="hint">
          The cue sheet as a picture for your phone's lock screen, with the clock's space at the top left clear. A long
          route makes more than one, Part 1, Part 2 and on, downloaded one after another. Its credits are along the
          bottom.
        </p>
      )}
      {isCourse(choice.format) && (
        <p className="hint">
          A course is the route shown with Ride's turn cues, fitted to the device. TCX carries the credits in its notes;
          FIT has no place for them but its name, which has them where the device leaves room: route data ©
          OpenStreetMap contributors (ODbL).
        </p>
      )}
    </section>
  );
}
