/**
 * The private-beta notice (OWNER-DECISIONS 360 and 382, FOLLOWUP-BETA-DEPLOY): a small
 * "Beta" chip in the map's bottom-left corner that opens a short note saying routing may
 * still use paths where bikes are not allowed until the next map update. It is for the
 * friends-and-family beta server only, so it is off unless the build was made with
 * VITE_BETA=1 (scripts/beta/ship-data.sh --build-frontend sets it); the local site is
 * byte-for-byte unchanged without it.
 *
 * Where to report: the owner, 2026-10-25, "For reports in that box, also give the discord.
 * I'm not trying to gatekeep the discord." So the note links the public Discord invite
 * (replacing 382's "tell the person who gave you access"). A build given VITE_BETA_REPORT_URL
 * (ship-data.sh --report-url) still adds a "Report a problem" link to that address, unless it
 * is the Discord invite again. Below it are two buttons: "Sign up to test here!", the Android beta's how-to-join
 * page (owner, 2026-10-25; the page and a button since 2026-11-06), and the help guides.
 *
 * The owner found the old banner in the planner obtrusive (2026-10-12), so it is a corner
 * chip now: a disclosure button ("Beta notice", aria-expanded) that shows and hides the note,
 * a region labelled "Beta notice" right after it, so Tab reaches its link next. Not a dialog:
 * it takes nothing over and never traps focus. Escape, or the chip again, closes it and the
 * focus is (or stays) on the chip. Nothing to dismiss: a corner chip is small enough to leave.
 * Written with createElement, like CandidatePicker, so a test renders it.
 */
import { GUIDES_PAGE } from "./mapInfo.ts";
import { createElement as h, useId, useRef, useState, type ReactElement } from "react";
import { t } from "./i18n.ts";
import { installState } from "./installOffer.ts";

export const BETA_BANNER_TEXT = t("Beta: routes may still use some paths where bikes aren't allowed until the next map update. If anything looks wrong, tell us on");

export const BETA_DISCORD_TEXT = "Discord";

export const BETA_DISCORD_URL = "https://discord.gg/Qwz6BEt6gc";

export const BETA_SIGNUP_TEXT = t("Sign up to test here!");

/**
 * The Android beta's how-to-join page (Stephen 2026-11-06: "For sign up to test in Beta, send the webpage with
 * instructions to the Google group"): join the testers' Google Group, opt in on Play, install. Was the sign-up form.
 */
export const BETA_SIGNUP_URL = "/about/android-beta.html";

/**
 * On an iPhone or iPad, the welcome page's iPhone steps instead (Stephen 2026-11-13, "add those all in"): there is no
 * iPhone app yet, so the Android page's three steps do not apply; welcome.html says what to open and what a ride needs.
 */
export const BETA_SIGNUP_URL_IPHONE = "/about/welcome.html#iphone";

/** Where "Sign up to test here!" goes on this device. */
export function betaSignupUrl(ios: boolean): string {
  return ios ? BETA_SIGNUP_URL_IPHONE : BETA_SIGNUP_URL;
}

/** The help guides' button beside it (lib/mapInfo.ts GUIDES_PAGE, the page Help's button opens too). */
export const BETA_GUIDES_TEXT = t("Using RouteMaker");

export const BETA_REPORT_LINK_TEXT = t("Report a problem");

export const BETA_CHIP_TEXT = "Beta";

export const BETA_NOTICE_NAME = t("Beta notice");

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
  /** Send feedback (FeedbackBox.tsx), under the buttons; absent, nothing. */
  feedback?: ReactElement | null;
  /** Test seam: start with the note shown. */
  initiallyOpen?: boolean;
  /** Test seam: whether this is an iPhone or iPad; absent, lib/installOffer.ts installState() says. */
  ios?: boolean;
}

export function BetaChip(props: Props): ReactElement | null {
  const [open, setOpen] = useState(props.initiallyOpen === true);
  const chip = useRef<HTMLButtonElement>(null);
  const noteId = `beta-note-${useId().replace(/:/g, "")}`;
  if (!props.enabled) return null;
  const link = (href: string, text: string) =>
    h(
      "a",
      { href, target: "_blank", rel: "noopener noreferrer" },
      text,
      h("span", { className: "visually-hidden" }, ` ${t("(opens in a new tab)")}`),
    );
  const report = props.reportUrl && props.reportUrl !== BETA_DISCORD_URL ? link(props.reportUrl, BETA_REPORT_LINK_TEXT) : null;
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
      h("p", null, BETA_BANNER_TEXT, " ", link(BETA_DISCORD_URL, BETA_DISCORD_TEXT), ".", report ? " " : null, report),
      // Two buttons, so they stand out (Stephen 2026-11-06: "make both that and the link to documentation a button
      // inside the popout so it's more apparent"): signing up to test, and the help guides.
      h(
        "p",
        { className: "beta-chip-actions" },
        link(betaSignupUrl(props.ios ?? installState().ios), BETA_SIGNUP_TEXT),
        link(GUIDES_PAGE, BETA_GUIDES_TEXT),
      ),
      // Send feedback without a Discord account (the owner, 2026-11-12), where the server takes it.
      props.feedback ?? null,
    ),
  );
}
