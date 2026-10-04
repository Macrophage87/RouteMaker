/**
 * The private-beta notice (OWNER-DECISIONS 360 and 382, FOLLOWUP-BETA-DEPLOY): a small
 * notice that says routing may still use paths where bikes are not allowed until
 * the next map update. It is for the friends-and-family beta server only, so it
 * is off unless the build was made with VITE_BETA=1 (scripts/beta/ship-data.sh
 * --build-frontend sets it); the local site is byte-for-byte unchanged without it.
 *
 * Where to report (382): the notice names no channel, it says to tell the person
 * who gave you access. A "Report a problem" link appears only when the build was
 * given VITE_BETA_REPORT_URL (ship-data.sh --report-url), an https address such as
 * a future Discord invite, so adding one later needs no code change.
 *
 * A labelled region, not a dialog or a live region: it sits in the planner panel
 * under the header, so the skip link, heading navigation (H to "RouteMaker") and
 * landmark navigation ("Beta notice" in the landmarks list) all land beside it
 * (final review, accessibility S1). It takes nothing over, never traps focus, and
 * the rider can ignore it. "Dismiss" hides it for this tab's session only
 * (sessionStorage), so it comes back in a new visit. Written with createElement,
 * like CandidatePicker, so a test renders it. The logic lives here, apart from
 * the component, so the flag and the storage are testable on their own.
 */
import { createElement as h, useState, type ReactElement } from "react";
import type { StorageLike } from "./signIn.ts";

export const BETA_BANNER_TEXT =
  "Beta: routes may still use some paths where bikes aren't allowed until the next map update. If anything looks wrong, tell the person who gave you access.";

export const BETA_REPORT_LINK_TEXT = "Report a problem";

export const BETA_DISMISS_KEY = "routemaker.beta-banner-dismissed";

/** Whether this build is the beta build: VITE_BETA is "1" (or "true"), nothing else. */
export function isBetaBuild(flag: unknown): boolean {
  return flag === "1" || flag === "true";
}

/**
 * The report link from VITE_BETA_REPORT_URL, or null for no link: only an absolute https
 * address with a host and no user name or password in it. Anything else (unset, empty,
 * http, javascript:, a bare word) shows no link rather than a broken or unsafe one.
 */
export function betaReportUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text) return null;
  try {
    const url = new URL(text);
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** Whether the rider has dismissed the notice in this tab. Storage that throws counts as "not dismissed". */
export function betaDismissed(storage: StorageLike | null): boolean {
  try {
    return storage?.getItem(BETA_DISMISS_KEY) === "1";
  } catch {
    return false;
  }
}

/** Remembers the dismissal for this tab; a storage that refuses is not an error, the notice just returns next load. */
export function dismissBeta(storage: StorageLike | null): void {
  try {
    storage?.setItem(BETA_DISMISS_KEY, "1");
  } catch {
    /* private mode or blocked storage: dismissed for now, back on reload */
  }
}

function tabStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/** After the notice goes, focus would fall to the page; send it to the planner, as the skip link does. */
function focusPlanner(): void {
  if (typeof document === "undefined") return;
  document.getElementById("route-planner")?.focus();
}

interface Props {
  /** Whether this is a beta build; App passes isBetaBuild(import.meta.env.VITE_BETA). */
  enabled: boolean;
  /** The report link, already checked by betaReportUrl; null or absent for none. */
  reportUrl?: string | null;
  /** Test seam: the storage to remember the dismissal in. Defaults to this tab's sessionStorage. */
  storage?: StorageLike | null;
}

export function BetaBanner(props: Props): ReactElement | null {
  const storage = props.storage === undefined ? tabStorage() : props.storage;
  const [hidden, setHidden] = useState(() => betaDismissed(storage));
  if (!props.enabled || hidden) return null;
  const report = props.reportUrl
    ? h(
        "a",
        { href: props.reportUrl, target: "_blank", rel: "noopener noreferrer" },
        BETA_REPORT_LINK_TEXT,
        h("span", { className: "visually-hidden" }, " (opens in a new tab)"),
      )
    : null;
  return h(
    "section",
    { className: "beta-banner", "aria-label": "Beta notice", "data-testid": "beta-banner" },
    h("p", null, BETA_BANNER_TEXT, report ? " " : null, report),
    h(
      "button",
      {
        type: "button",
        "aria-label": "Dismiss beta notice",
        onClick: () => {
          dismissBeta(storage);
          setHidden(true);
          focusPlanner();
        },
      },
      "Dismiss",
    ),
  );
}
