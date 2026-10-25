/**
 * The error report behind the crash screen (CrashScreen.tsx; Stephen 2026-10-25: "Since this is a beta test, can you
 * have the reload screen offer a way to dump the error log or whatever for troubleshooting?"). The page keeps its
 * last few uncaught errors from the moment it loads (an error in a click handler leaves the page up but is often the
 * one before the crash), and the report puts them with the crash itself, the version, the browser and the plan's
 * settings, as plain text to copy into a bug report.
 *
 * Privacy: nothing leaves the device unless the rider pastes it somewhere. The link's places (its points, and
 * anything else not on SAFE_KEYS) are left out, and coordinates and tile numbers in the errors' own text, so a report
 * never says where someone rides.
 */
import { APP_VERSION } from "./appVersion.ts";

/** How many uncaught errors are kept, newest last. */
export const KEPT_ERRORS = 15;

export interface LoggedError {
  /** Epoch ms. */
  at: number;
  /** "error" (window.onerror) or "rejection" (an unhandled promise). */
  kind: "error" | "rejection";
  text: string;
}

const kept: LoggedError[] = [];

/**
 * An error's text with any place in it left out: a coordinate pair ("-77.01203,38.89853", "LngLat(-77.04, 38.91)",
 * "-77.04%2C38.91"), a number given as a lat or lon ("lat 38.90123"), a URL's query (a search's `q=` is the place
 * searched for) or a map tile's z/x/y (a failed tile's URL names the area it was for).
 */
export function withoutPlaces(text: string): string {
  return text
    .replace(/(https?:\/\/[^\s?#"'`<>]+)\?[^\s#"'`<>)]*/g, "$1?(query left out)")
    .replace(/-?\d{1,3}\.\d{2,}\s*(?:,|%2C)\s*-?\d{1,3}\.\d{2,}/gi, "(place left out)")
    .replace(/\b(lat|lon|lng|latitude|longitude)\b(["']?\s*[:=]?\s*)-?\d{1,3}\.\d+/gi, "$1$2(left out)")
    .replace(/\/\d{1,2}\/\d+\/\d+(?=[/.?]|$)/g, "/(tile left out)");
}

/** One error's text: its message and stack, or what it was turned into a string, without places. */
export function errorText(error: unknown): string {
  if (error instanceof Error) {
    const stack = error.stack ?? "";
    return withoutPlaces(stack.includes(error.message) ? stack : `${error.name}: ${error.message}\n${stack}`.trim());
  }
  try {
    return withoutPlaces(typeof error === "string" ? error : JSON.stringify(error) ?? String(error));
  } catch {
    return withoutPlaces(String(error));
  }
}

/** Keep one error (the oldest goes past KEPT_ERRORS). */
export function logError(kind: LoggedError["kind"], error: unknown, at = Date.now(), into: LoggedError[] = kept): void {
  into.push({ at, kind, text: errorText(error) });
  if (into.length > KEPT_ERRORS) into.splice(0, into.length - KEPT_ERRORS);
}

/** The errors kept so far, oldest first. */
export function loggedErrors(): readonly LoggedError[] {
  return kept;
}

interface ErrorTarget {
  addEventListener(type: "error", listener: (event: { error?: unknown; message?: string }) => void): void;
  addEventListener(type: "unhandledrejection", listener: (event: { reason?: unknown }) => void): void;
}

/** Keep the page's uncaught errors from now on (main.tsx, before the first render). */
export function watchErrors(win: ErrorTarget): void {
  win.addEventListener("error", (event) => logError("error", event.error ?? event.message ?? "Unknown error"));
  win.addEventListener("unhandledrejection", (event) => logError("rejection", event.reason ?? "Unknown rejection"));
}

/** The link's settings that say nothing about where: kept with their values; every other key is named only. */
const SAFE_KEYS = new Set(["preset", "v", "stress", "hills", "loop", "bike", "assist", "avoidgravel", "carrying", "novice", "targetmi", "trailsoff", "when", "line"]);

/** The link's fragment without its places: "#preset=default&stress=70&p=(left out)". */
export function safeFragment(hash: string): string {
  const body = hash.replace(/^#/, "");
  if (!body) return "(none)";
  const parts = body.split("&").map((part) => {
    const [key] = part.split("=", 1);
    return SAFE_KEYS.has(key) ? part : `${key}=(left out)`;
  });
  return `#${parts.join("&")}`;
}

export interface ReportInput {
  error: unknown;
  /** React's component stack, where the error was thrown in the page's parts. */
  componentStack?: string | null;
  at: number;
  hash: string;
  path: string;
  userAgent: string;
  logged: readonly LoggedError[];
  version?: string;
}

/** The report as plain text, to copy. */
export function crashReport(input: ReportInput): string {
  const version = input.version ?? APP_VERSION;
  const lines = [
    "RouteMaker error report",
    `Version: ${version || "(unknown)"}`,
    `Time: ${new Date(input.at).toISOString()}`,
    `Page: ${input.path} ${safeFragment(input.hash)}`,
    `Browser: ${input.userAgent}`,
    "",
    "Error:",
    errorText(input.error),
  ];
  const where = input.componentStack?.trim();
  if (where) lines.push("", "Where in the page:", where);
  if (input.logged.length > 0) {
    lines.push("", `Earlier errors (${input.logged.length}, oldest first):`);
    for (const e of input.logged) lines.push(`- ${new Date(e.at).toISOString()} ${e.kind}: ${e.text}`);
  }
  return lines.join("\n");
}
