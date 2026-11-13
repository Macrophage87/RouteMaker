/**
 * Riders' feedback from inside the app, with no Discord account (backlog 2026-11-12, "Ready for a dozen testers"; the
 * owner, 2026-11-12: text only, through the server, nothing kept there). The server (core.feedback) posts the words
 * and these few details to the owner's bug-reports forum: the version, a short browser name, the ride type, the
 * language, Go or Plan and whether it is the Android app. Never a place, never a screenshot (one can show where someone
 * is), never the full user-agent string.
 */
import { APP_VERSION } from "./appVersion.ts";

export const FEEDBACK_URL = "/api/feedback";
export const FEEDBACK_MIN = 3;
export const FEEDBACK_MAX = 2000;

export interface FeedbackDetails {
  version?: string;
  browser?: string;
  ride_type?: string;
  language?: string;
  mode?: string;
  app?: string;
}

/** "Chrome 131 on Android", "Safari 18 on iPhone", "Firefox 133 on Windows": a short name, never the whole string. */
export function shortBrowser(userAgent: string): string {
  const os = /iPhone|iPad/.test(userAgent)
    ? "iPhone"
    : /Android/.test(userAgent)
      ? "Android"
      : /Windows/.test(userAgent)
        ? "Windows"
        : /Mac OS X|Macintosh/.test(userAgent)
          ? "Mac"
          : /Linux/.test(userAgent)
            ? "Linux"
            : "another system";
  const found =
    /(Edg|EdgA|EdgiOS)\/(\d+)/.exec(userAgent) ??
    /(Firefox|FxiOS)\/(\d+)/.exec(userAgent) ??
    /(SamsungBrowser)\/(\d+)/.exec(userAgent) ??
    /(Chrome|CriOS)\/(\d+)/.exec(userAgent) ??
    /Version\/(\d+).*(Safari)/.exec(userAgent);
  if (!found) return `a browser on ${os}`;
  const names: Record<string, string> = { Edg: "Edge", EdgA: "Edge", EdgiOS: "Edge", FxiOS: "Firefox", CriOS: "Chrome", SamsungBrowser: "Samsung Internet" };
  const [name, major] = found[2] === "Safari" ? ["Safari", found[1]] : [names[found[1]] ?? found[1], found[2]];
  return `${name} ${major} on ${os}`;
}

export function feedbackDetails(input: { userAgent: string; rideType: string; language: string; mode: string; nativeApp: boolean }): FeedbackDetails {
  return {
    ...(APP_VERSION ? { version: APP_VERSION } : {}),
    browser: shortBrowser(input.userAgent),
    ride_type: input.rideType,
    language: input.language,
    mode: input.mode,
    app: input.nativeApp ? "Android app" : "web",
  };
}

/** Whether this server takes feedback (GET /api/feedback); false on any doubt, so no entry shows that cannot send. */
export async function feedbackOn(origin: string, fetcher: typeof fetch = fetch): Promise<boolean> {
  try {
    const answer = await fetcher(`${origin}${FEEDBACK_URL}`, { cache: "no-store", headers: { Accept: "application/json" } });
    if (!answer.ok) return false;
    return ((await answer.json()) as { enabled?: unknown }).enabled === true;
  } catch {
    return false;
  }
}

export type SendResult = "sent" | "busy" | "failed";

export async function sendFeedback(origin: string, text: string, details: FeedbackDetails, fetcher: typeof fetch = fetch): Promise<SendResult> {
  try {
    const answer = await fetcher(`${origin}${FEEDBACK_URL}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ text: text.trim().slice(0, FEEDBACK_MAX), details }),
    });
    if (answer.ok) return "sent";
    return answer.status === 429 ? "busy" : "failed";
  } catch {
    return "failed";
  }
}
