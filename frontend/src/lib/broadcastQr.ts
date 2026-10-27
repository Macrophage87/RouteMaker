// A broadcast by QR code (Stephen 2026-10-26: "Also offer the ability to broadcast a route from a QR code. A long press
// would show a popup with the QR code"; "Also allow participants to share that same code as well"): holding Broadcast
// (beside Start, on the ride screen, in Roam) shows its link as a QR code for riders nearby to scan with their camera.
// The link is the one Broadcast's share sheet sends (one per ride: "if you press and share multiple times in the same
// ride, it's the same link"); a rider following passes on the link they opened, so all who scan it follow its leader.
import qrcode from "qrcode-generator";
import { qrModules } from "./shareCard.ts";

/** How long Broadcast is held before the QR code shows (a right-click, or the keyboard's menu key, shows it at once). */
export const HOLD_MS = 500;
/** The key that holds it (useHold), named to screen readers as the button's shortcut. */
export const HOLD_KEY = "Shift+F10";

export const BROADCAST_QR_HEADING = "Scan to follow";
export const BROADCAST_QR_LEAD = "Riders nearby point their phone's camera at this code to open the ride and follow its leader.";
export const BROADCAST_QR_NAME = "QR code for the broadcast link";
export const BROADCAST_QR_START = "Start ride";
export const BROADCAST_QR_CLOSE = "Close";
/** Said with each Broadcast button, so the hold is found by those who do not see it. */
export const BROADCAST_HOLD_HINT = "Hold it, right-click it, or press Shift+F10 for a QR code to scan instead.";

/** The quiet zone round the code, in modules (the standard asks for 4). */
export const QR_MARGIN = 4;

/** The code as one SVG path on a square `size` modules wide, quiet zone included: crisp at any size. */
export function qrPath(link: string): { size: number; d: string } {
  // Level M: still read off a phone's screen in sunlight, and short enough for a link with its plan.
  const qr = qrcode(0, "M");
  qr.addData(link);
  qr.make();
  const modules = qrModules(qr);
  const parts: string[] = [];
  modules.forEach((row, r) => row.forEach((dark, c) => dark && parts.push(`M${c + QR_MARGIN} ${r + QR_MARGIN}h1v1h-1z`)));
  return { size: modules.length + QR_MARGIN * 2, d: parts.join("") };
}
