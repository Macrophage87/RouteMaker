// A broadcast by QR code (Stephen 2026-10-26: "Also offer the ability to broadcast a route from a QR code. A long press
// would show a popup with the QR code"; "Also allow participants to share that same code as well"): holding Broadcast
// (beside Start, on the ride screen, in Roam) shows its link as a QR code for riders nearby to scan with their camera.
// The link is the one Broadcast's share sheet sends (one per ride: "if you press and share multiple times in the same
// ride, it's the same link"); a rider following passes on the link they opened, so all who scan it follow its leader.
// The words only: the code itself is drawn by lib/broadcastQrCode.ts, which only the dialog loads, so the QR encoder
// and the share card stay out of the first load (the v0.27.0 size budget).
import { t } from "./i18n.ts";

/** How long Broadcast is held before the QR code shows (a right-click, or the keyboard's menu key, shows it at once). */
export const HOLD_MS = 500;
/** The key that holds it (useHold), named to screen readers as the button's shortcut. */
export const HOLD_KEY = "Shift+F10";

export const BROADCAST_QR_HEADING = t("Scan to follow");
export const BROADCAST_QR_LEAD = t("Riders nearby point their phone's camera at this code to open the ride and follow its leader.");
export const BROADCAST_QR_NAME = t("QR code for the live link");
export const BROADCAST_QR_START = t("Start ride");
export const BROADCAST_QR_CLOSE = t("Close");
/** Said with each Broadcast button, so the hold is found by those who do not see it. */
export const BROADCAST_HOLD_HINT = t("Hold it, right-click it, or press Shift+F10 for a QR code to scan instead.");
