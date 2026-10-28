/**
 * The road panel's "Mark a hazard", on a Mass Ride only (FOLLOWUP-MASSRIDE-MAP part 3; OWNER-DECISIONS
 * 325-327; lib/massHazards.ts): a rider the settings allow marks the road piece Caution or Warning, with a
 * reason. Nothing changes on the map until an instance admin reviews it.
 *
 * Built like "Suggest a change" (SuggestChange.tsx): its heading takes the focus when it opens; the two
 * levels are a native radio group in a fieldset whose legend asks the question, each with its words; a
 * required reason, a labelled textarea with its count; the result is a sentence in a polite status region
 * that is always in the page; an error is an alert that names the field and moves the focus to it; Cancel
 * and Escape close it and the caller returns the focus to its button.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { csrfFromCookie, countText } from "./lib/stressEditor.ts";
import {
  HAZARD_LEVEL_LEGEND,
  HAZARD_PRIVACY,
  HAZARD_REASON_LABEL,
  HAZARD_REASON_MAX,
  HAZARD_REPORT_HEADING,
  HAZARD_SEND,
  HAZARD_WORDS,
  hazardProblem,
  sendHazard,
  type HazardLevel,
  type HazardProps,
} from "./lib/massHazards.ts";
import { t } from "./lib/i18n.ts";

interface Props {
  origin: string;
  wayId: number;
  title: string;
  /** The nearest point on the road ([lon, lat], the panel's `on_way`): checked by the server, then dropped. */
  point: [number, number];
  /** The hazard already on the map here, if any: said, so the rider knows what is marked. */
  current: HazardProps | null;
  onClose: () => void;
}

const LEVELS: HazardLevel[] = ["caution", "warning"];

export function HazardReport({ origin, wayId, title, point, current, onClose }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [level, setLevel] = useState<HazardLevel | null>(null);
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState<{ field: "reason" | "level" | null; message: string } | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const fail = (field: "reason" | "level" | null, message: string) => {
    setError({ field, message });
    setTimeout(() => {
      if (field === "level") document.getElementById(id("level-caution"))?.focus();
      else if (field) document.getElementById(id(field))?.focus();
    }, 0);
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending || sent) return;
    const problem = hazardProblem(level, reason);
    if (problem || level === null) {
      fail(problem?.field ?? "level", problem?.message ?? "Choose Caution or Warning.");
      return;
    }
    setError(null);
    setSending(true);
    const outcome = await sendHazard(
      origin,
      { osm_way_id: wayId, lat: point[1], lon: point[0], level, reason: reason.trim() },
      csrfFromCookie(document.cookie),
    );
    setSending(false);
    if (outcome.kind === "refused") {
      fail(outcome.field === "level" || outcome.field === "reason" ? outcome.field : null, outcome.message);
      return;
    }
    setSent(true);
    setSaid(outcome.message);
    headingRef.current?.focus();
  };

  return (
    <section className="stress-editor hazard-report" aria-labelledby={id("title")}>
      <h3 id={id("title")} ref={headingRef} tabIndex={-1}>
        {HAZARD_REPORT_HEADING}
      </h3>
      <p className="stress-editor-said" role="status">
        {said}
      </p>
      {error && (
        <p className="stress-editor-error" role="alert" id={id("error")}>
          {error.message}
        </p>
      )}
      {!sent && (
        <form onSubmit={onSubmit} noValidate aria-describedby={error ? id("error") : undefined}>
          <p className="stress-editor-now">{t("Now: {hazard}.", { hazard: current ? HAZARD_WORDS[current.level] : t("No hazard marked here") })}</p>
          <p className="stress-editor-extent">
            <span className="road-info-label">{t("This road piece:")}</span> {title}
          </p>
          <fieldset
            className="stress-editor-field hazard-levels"
            aria-invalid={error?.field === "level" ? true : undefined}
            aria-describedby={error?.field === "level" ? id("error") : undefined}
          >
            <legend>{HAZARD_LEVEL_LEGEND}</legend>
            {LEVELS.map((value) => (
              <label key={value} className="hazard-level">
                <input
                  type="radio"
                  name={id("level")}
                  id={id(`level-${value}`)}
                  value={value}
                  checked={level === value}
                  onChange={() => setLevel(value)}
                />{" "}
                {HAZARD_WORDS[value]}
              </label>
            ))}
          </fieldset>
          <div className="stress-editor-field">
            <label htmlFor={id("reason")}>{HAZARD_REASON_LABEL}</label>
            <textarea
              id={id("reason")}
              rows={3}
              value={reason}
              required
              aria-required="true"
              aria-invalid={error?.field === "reason" ? true : undefined}
              aria-describedby={`${id("reason-help")}${error?.field === "reason" ? ` ${id("error")}` : ""}`}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id={id("reason-help")} className="hint">
              {HAZARD_PRIVACY} {countText(reason.trim(), HAZARD_REASON_MAX)}.
            </p>
          </div>
          <div className="stress-editor-buttons">
            <button type="submit" aria-disabled={sending ? true : undefined}>
              {sending ? "Sending…" : HAZARD_SEND}
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              {t("Cancel")}
            </button>
          </div>
        </form>
      )}
      {sent && (
        <div className="stress-editor-buttons">
          <button type="button" className="secondary" onClick={onClose}>
            {t("Done")}
          </button>
        </div>
      )}
    </section>
  );
}
