/**
 * The private-beta notice (OWNER-DECISIONS 360, FOLLOWUP-BETA-DEPLOY): a small
 * strip that says routing may still use paths where bikes are not allowed until
 * the next map update. It is for the friends-and-family beta server only, so it
 * is off unless the build was made with VITE_BETA=1 (scripts/beta/ship-data.sh
 * maps BETA=1 onto that); the local site is byte-for-byte unchanged without it.
 *
 * A status message, not a dialog: it takes nothing over, never traps focus, and
 * the rider can ignore it. "Dismiss" hides it for this tab's session only
 * (sessionStorage), so it comes back in a new visit. Written with createElement,
 * like CandidatePicker, so a test renders it. The logic lives here, apart from
 * the component, so the flag and the storage are testable on their own.
 */
import { createElement as h, useState, type ReactElement } from "react";
import type { StorageLike } from "./signIn.ts";

export const BETA_BANNER_TEXT =
  "Beta: routes may still use some paths where bikes aren't allowed until the next map update. Please report anything odd.";

export const BETA_DISMISS_KEY = "routemaker.beta-banner-dismissed";

/** Whether this build is the beta build: VITE_BETA is "1" (or "true"), nothing else. */
export function isBetaBuild(flag: unknown): boolean {
  return flag === "1" || flag === "true";
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

/** After the strip goes, focus would fall to the page; send it to the planner, as the skip link does. */
function focusPlanner(): void {
  if (typeof document === "undefined") return;
  document.getElementById("route-planner")?.focus();
}

interface Props {
  /** Whether this is a beta build; App passes isBetaBuild(import.meta.env.VITE_BETA). */
  enabled: boolean;
  /** Test seam: the storage to remember the dismissal in. Defaults to this tab's sessionStorage. */
  storage?: StorageLike | null;
}

export function BetaBanner(props: Props): ReactElement | null {
  const storage = props.storage === undefined ? tabStorage() : props.storage;
  const [hidden, setHidden] = useState(() => betaDismissed(storage));
  if (!props.enabled || hidden) return null;
  return h(
    "div",
    { className: "beta-banner", role: "status", "data-testid": "beta-banner" },
    h("p", null, BETA_BANNER_TEXT),
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
