/**
 * The road panel's short "Suggest a change" form, for anyone the full form is not open to (v0.7.0;
 * lib/suggestions.ts, core/signed_out_suggestions.py). The owner, 2026-10-13: "Just have the slider with
 * description and a brief panel of options with a catch all other."
 *
 * A native range input in half steps (1 to 4.5, and Avoid), its spoken value each level's description
 * ("Between 2 and 3: Fine for most confident adults"); the one-tap reasons as checkboxes in a fieldset,
 * "Other" opening a short text box; Send. Built like SuggestChange.tsx: the heading takes the focus, the
 * result is said in a status region, an error is an alert that moves the focus to its field. A hidden
 * honeypot field stays empty for a person (it is out of the tab order and the accessibility tree).
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { t } from "./lib/i18n.ts";
import { csrfFromCookie, countText } from "./lib/stressEditor.ts";
import {
  QUICK_NOTE,
  QUICK_OTHER_LABEL,
  QUICK_OTHER_MAX,
  QUICK_REASONS_LABEL,
  SUGGEST_HEADING,
  SUGGEST_LEVEL_LABEL,
  SUGGEST_SEND,
  fetchQuickTicket,
  quickProblem,
  quickValueText,
  sendQuick,
  type QuickTicket,
} from "./lib/suggestions.ts";

interface Props {
  origin: string;
  wayId: number;
  title: string;
  /** The road's level now (1 to 5 by halves). */
  current: number;
  /** The nearest point on the road ([lon, lat]), never the spot clicked. */
  point: [number, number];
  /** Whether the road data can hold a half step yet: whole steps only until it can. */
  halfSteps: boolean;
  onClose: () => void;
}

type Field = "step" | "reasons" | "other";

export function SuggestQuick({ origin, wayId, title, current, point, halfSteps, onClose }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [ticket, setTicket] = useState<QuickTicket | null>(null);
  const [step, setStep] = useState(current);
  const [reasons, setReasons] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const [website, setWebsite] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState<{ field: Field | null; message: string } | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
    let live = true;
    void fetchQuickTicket(origin, wayId).then((answer) => {
      if (live) setTicket(answer);
    });
    return () => {
      live = false;
    };
  }, [origin, wayId]);

  const fail = (field: Field | null, message: string) => {
    setError({ field, message });
    setTimeout(() => {
      if (field) document.getElementById(id(field === "reasons" ? "reason-0" : field))?.focus();
    }, 0);
  };

  const toggle = (key: string) => setReasons((now) => (now.includes(key) ? now.filter((k) => k !== key) : [...now, key]));

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending || sent) return;
    const problem = quickProblem(step, current, reasons, other);
    if (problem) {
      fail(problem.field, problem.message);
      return;
    }
    if (!ticket) {
      fail(null, t("Nothing was sent. Try again shortly."));
      return;
    }
    setError(null);
    setSending(true);
    const outcome = await sendQuick(
      origin,
      { osm_way_id: wayId, lat: point[1], lon: point[0], step, reasons, other: other.trim(), ticket: ticket.ticket, website },
      csrfFromCookie(document.cookie),
    );
    setSending(false);
    if (outcome.kind === "refused") {
      const field = outcome.field === "step" || outcome.field === "reasons" || outcome.field === "other" ? outcome.field : null;
      fail(field, outcome.message);
      return;
    }
    setSent(true);
    setSaid(outcome.message);
    headingRef.current?.focus();
  };

  const words = quickValueText(step);
  const reasonList = ticket?.reasons ?? [];
  return (
    <section className="stress-editor suggest-change suggest-quick" aria-labelledby={id("title")}>
      <h3 id={id("title")} ref={headingRef} tabIndex={-1}>
        {SUGGEST_HEADING}
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
          <p className="stress-editor-extent">
            <span className="road-info-label">{t("This road:")}</span> {title}. {t("Now:")} {quickValueText(current)}.
          </p>
          <div className="stress-editor-field">
            <label htmlFor={id("step")}>{SUGGEST_LEVEL_LABEL}</label>
            <div className="stress-editor-slider">
              <input
                id={id("step")}
                type="range"
                min={1}
                max={5}
                step={halfSteps ? 0.5 : 1}
                value={step}
                aria-valuetext={words}
                aria-invalid={error?.field === "step" ? true : undefined}
                onChange={(event) => setStep(Number(event.target.value))}
              />
              <output htmlFor={id("step")} className="stress-editor-output" aria-hidden="true">
                {words}
              </output>
            </div>
          </div>
          {reasonList.length > 0 && (
            <fieldset className="suggest-quick-reasons" aria-invalid={error?.field === "reasons" ? true : undefined}>
              <legend>{QUICK_REASONS_LABEL}</legend>
              {reasonList.map(([key, label], n) => (
                <label key={key} className="suggest-quick-reason">
                  <input id={id(`reason-${n}`)} type="checkbox" checked={reasons.includes(key)} onChange={() => toggle(key)} /> {label}
                </label>
              ))}
            </fieldset>
          )}
          {reasons.includes("other") && (
            <div className="stress-editor-field">
              <label htmlFor={id("other")}>{QUICK_OTHER_LABEL}</label>
              <textarea
                id={id("other")}
                rows={2}
                maxLength={QUICK_OTHER_MAX}
                value={other}
                aria-invalid={error?.field === "other" ? true : undefined}
                aria-describedby={id("other-count")}
                onChange={(event) => setOther(event.target.value)}
              />
              <p id={id("other-count")} className="hint">
                {countText(other.trim(), QUICK_OTHER_MAX)}.
              </p>
            </div>
          )}
          {/* A honeypot: a person never sees or fills it. */}
          <div className="visually-hidden" aria-hidden="true">
            <label htmlFor={id("website")}>{t("Website")}</label>
            <input id={id("website")} name="website" type="text" tabIndex={-1} autoComplete="off" value={website} onChange={(event) => setWebsite(event.target.value)} />
          </div>
          <p className="hint">{QUICK_NOTE}</p>
          <div className="stress-editor-buttons">
            <button type="submit" aria-disabled={sending || !ticket ? true : undefined}>
              {sending ? t("Sending…") : SUGGEST_SEND}
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
