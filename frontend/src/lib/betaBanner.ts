/**
 * The private-beta notice (OWNER-DECISIONS 360 and 382, FOLLOWUP-BETA-DEPLOY): a small
 * "Beta" chip in the map's bottom-left corner that opens a short note saying routing may
 * still use paths where bikes are not allowed until the next map update. It is for the
 * friends-and-family beta server only, so it is off unless the build was made with
 * VITE_BETA=1 (scripts/beta/ship-data.sh --build-frontend sets it); the local site is
 * byte-for-byte unchanged without it.
 *
 * Where to report (382): the notice names no channel, it says to tell the person
 * who gave you access. A "Report a problem" link appears only when the build was
 * given VITE_BETA_REPORT_URL (ship-data.sh --report-url), an https address such as
 * a future Discord invite, so adding one later needs no code change.
 *
 * The owner found the old banner in the planner obtrusive (2026-10-12), so it is a corner
 * chip now: a disclosure button ("Beta notice", aria-expanded) that shows and hides the note,
 * a region labelled "Beta notice" right after it, so Tab reaches its link next. Not a dialog:
 * it takes nothing over and never traps focus. Escape, or the chip again, closes it and the
 * focus is (or stays) on the chip. Nothing to dismiss: a corner chip is small enough to leave.
 * Written with createElement, like CandidatePicker, so a test renders it.
 */
import { createElement as h, useId, useRef, useState, type ReactElement } from "react";

export const BETA_BANNER_TEXT =
  "Beta: routes may still use some paths where bikes aren't allowed until the next map update. If anything looks wrong, tell the person who gave you access.";

export const BETA_REPORT_LINK_TEXT = "Report a problem";

export const BETA_CHIP_TEXT = "Beta";

export const BETA_NOTICE_NAME = "Beta notice";

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

interface Props {
  /** Whether this is a beta build; App passes isBetaBuild(import.meta.env.VITE_BETA). */
  enabled: boolean;
  /** The report link, already checked by betaReportUrl; null or absent for none. */
  reportUrl?: string | null;
  /** Test seam: start with the note shown. */
  initiallyOpen?: boolean;
}

export function BetaChip(props: Props): ReactElement | null {
  const [open, setOpen] = useState(props.initiallyOpen === true);
  const chip = useRef<HTMLButtonElement>(null);
  const noteId = `beta-note-${useId().replace(/:/g, "")}`;
  if (!props.enabled) return null;
  const report = props.reportUrl
    ? h(
        "a",
        { href: props.reportUrl, target: "_blank", rel: "noopener noreferrer" },
        BETA_REPORT_LINK_TEXT,
        h("span", { className: "visually-hidden" }, " (opens in a new tab)"),
      )
    : null;
  return h(
    "div",
    {
      className: "beta-chip",
      "data-testid": "beta-chip",
      onKeyDown: (event: { key: string; preventDefault(): void; stopPropagation(): void }) => {
        if (event.key !== "Escape" || !open) return;
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
        chip.current?.focus();
      },
    },
    h(
      "button",
      {
        type: "button",
        ref: chip,
        className: "beta-chip-button",
        "aria-label": BETA_NOTICE_NAME,
        "aria-expanded": open,
        "aria-controls": noteId,
        onClick: () => setOpen(!open),
      },
      BETA_CHIP_TEXT,
    ),
    h(
      "section",
      { id: noteId, className: "beta-chip-note", "aria-label": BETA_NOTICE_NAME, hidden: !open },
      h("p", null, BETA_BANNER_TEXT, report ? " " : null, report),
    ),
  );
}
