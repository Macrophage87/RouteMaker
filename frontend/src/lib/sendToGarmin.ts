/**
 * Send to Garmin (the owner, 2026-10-17: "Is it possible to push to garmin?", then "Share to Connect"): the route
 * shown as a FIT course with its turn cues (lib/course.ts, the Garmin Edge profile), handed to the phone so Garmin
 * Connect adds it as a course and syncs it to the Edge or watch. Garmin's own direct push (the Connect Developer
 * Program's Courses API) needs Garmin's approval and takes no new applicants, so the file goes through the phone:
 *
 * - In the phone app (mobile/): its RouteMakerFiles plugin hands the file to Garmin Connect when it takes it, the
 *   way Garmin Connect on Android imports a course file from a file manager, else offers it to the phone's apps.
 *   An app from before the plugin shows no button: a WebView neither shares nor saves a file a page makes.
 * - In a browser that can share the file (navigator.canShare with files; Chrome on Android shares no .fit, Safari
 *   does): the share sheet.
 * - Otherwise the file is saved, and the line says where to take it: Garmin Connect on a phone, Garmin Connect's
 *   website on a computer.
 *
 * Nothing goes to Garmin or to the server from here: the file is made in this browser and handed to the phone.
 */
import type { Course } from "./course.ts";
import { nativeBridge, type CapacitorBridge } from "./nativeShell.ts";

/** The phone app's plugin (mobile/android/.../FilesPlugin.java). */
export const FILES_PLUGIN = "RouteMakerFiles";
export const SEND_LABEL = "Send to Garmin";
export const FIT_TYPE = "application/vnd.ant.fit";

export const SENT_GARMIN = "Sent to Garmin Connect. Save it there and it syncs to your Garmin.";
export const SENT_CHOOSER = "Choose Garmin Connect. Not listed? Install it from Google Play, then send again.";
export const SENT_SHARE = "Course shared. Garmin Connect syncs it to your Garmin.";
export const SEND_CANCELLED = "Not sent.";
export const SENT_SAVED = "FIT course saved. Open it from your downloads and choose Garmin Connect.";
export const SENT_SAVED_COMPUTER = "FIT course saved. Import it at connect.garmin.com, under Courses.";
export const SEND_FAILED = "Could not hand the course on. Is Garmin Connect installed?";

/** What sending uses: the phone app's bridge, the browser's share sheet, and a download. */
export interface SendEnv {
  bridge: CapacitorBridge | null;
  nav: { share?: (data: { files: File[] }) => Promise<void>; canShare?: (data: { files: File[] }) => boolean } | undefined;
  save: (bytes: Uint8Array<ArrayBuffer>, type: string, fileName: string) => void;
  /** A touch screen: a saved file is opened on this phone, not imported on Garmin's website. */
  phone: boolean;
}

export function browserSendEnv(save: SendEnv["save"]): SendEnv {
  const phone = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
  return { bridge: nativeBridge(), nav: typeof navigator === "undefined" ? undefined : navigator, save, phone };
}

/** Base64 of the bytes, for the bridge (which carries JSON only). */
export function toBase64(bytes: Uint8Array): string {
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

function hasPlugin(bridge: CapacitorBridge): boolean {
  try {
    return bridge.isPluginAvailable?.(FILES_PLUGIN) === true;
  } catch {
    return false;
  }
}

function canShareFiles(nav: SendEnv["nav"], files: File[]): boolean {
  if (typeof nav?.share !== "function" || typeof nav.canShare !== "function") return false;
  try {
    return nav.canShare({ files }) === true;
  } catch {
    return false;
  }
}

/** Whether to offer Send to Garmin here: anywhere but the phone app from before the plugin. */
export function canSendToGarmin(bridge: CapacitorBridge | null = nativeBridge()): boolean {
  return bridge === null || hasPlugin(bridge);
}

/** Hand the FIT course's bytes to the phone, and return the one line saying what happened. */
export async function sendCourse(bytes: Uint8Array<ArrayBuffer>, fileName: string, env: SendEnv): Promise<string> {
  if (env.bridge) {
    try {
      const done = (await env.bridge.nativePromise(FILES_PLUGIN, "openWith", { name: fileName, data: toBase64(bytes) })) as { app?: string } | null;
      return done?.app === "garmin-connect" ? SENT_GARMIN : SENT_CHOOSER;
    } catch {
      return SEND_FAILED;
    }
  }
  const files = [new File([bytes], fileName, { type: FIT_TYPE })];
  if (canShareFiles(env.nav, files)) {
    try {
      await env.nav!.share!({ files });
      return SENT_SHARE;
    } catch (error) {
      if ((error as Error)?.name === "AbortError") return SEND_CANCELLED;
      // Refused (no gesture left after the closure check, say): saved instead.
    }
  }
  env.save(bytes, FIT_TYPE, fileName);
  return env.phone ? SENT_SAVED : SENT_SAVED_COMPUTER;
}

/** Whether fitting the course to the device left anything out: then its line (courseLine) is said too. */
export function courseTrimmed(course: Pick<Course, "trim">): boolean {
  const t = course.trim;
  return t.protectedOver || t.cuesKept < t.cuesBefore || t.pointsKept < t.pointsBefore || t.bytes > t.profile.maxBytes;
}
