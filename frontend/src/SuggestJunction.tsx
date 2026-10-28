/**
 * The road panel's "Suggest a junction change" (FOLLOWUP-STRESS-SUGGEST, OWNER-DECISIONS 232;
 * lib/junctionSuggest.ts): a rider the settings allow suggests a danger level for the junction, in plain
 * words (Avoid included), and/or that it is more or less dangerous than the map shows, with a reason.
 * Nothing changes on the map until an instance admin reviews it.
 *
 * Built like the road's form (SuggestChange.tsx): its heading takes the focus when it opens; each choice
 * is a native radio group in a fieldset named by its legend, so a group is one Tab stop and the arrow keys
 * move within it (the dialog's Tab trap keeps that, lib/rideTypeDialog.ts tabStops), each starting on its
 * "no answer" choice; a required reason in a labelled textarea; the result is a sentence in a polite
 * status region that is always in the page; an error is an alert that names the field and moves the focus
 * to it; Cancel and Escape close it and the panel returns the focus to its button.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { t } from "./lib/i18n.ts";
import { countText, csrfFromCookie } from "./lib/stressEditor.ts";
import {
  DIRECTION_WORDS,
  JUNCTION_DIRECTION_LEGEND,
  JUNCTION_LEVELS,
  JUNCTION_LEVEL_LEGEND,
  JUNCTION_PRIVACY,
  JUNCTION_REASON_MAX,
  JUNCTION_SUGGEST_HEADING,
  SHOWN_WORDS,
  junctionProblem,
  sendJunctionSuggestion,
  type Direction,
  type JunctionAt,
  type Shown,
} from "./lib/junctionSuggest.ts";
import { SUGGEST_REASON_LABEL, SUGGEST_SEND } from "./lib/suggestions.ts";

interface Props {
  origin: string;
  /** The junction the API found at the panel's spot: its node is what is sent, never the spot. */
  junction: JunctionAt;
  /** What the rider's route shows there (lib/junctionSuggest.ts shownNear); null with no route. */
  shown: Shown | null;
  onClose: () => void;
}

type Field = "level" | "direction" | "reason";

export function SuggestJunction({ origin, junction, shown, onClose }: Props) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [level, setLevel] = useState<number | null>(null);
  const [direction, setDirection] = useState<Direction | null>(null);
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState<{ field: Field | null; message: string } | null>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  // The field's own control: the checked radio of its group, or the textarea.
  const focusField = (field: Field) => {
    if (field === "reason") document.getElementById(id("reason"))?.focus();
    else document.querySelector<HTMLInputElement>(`#${CSS.escape(id(field))} input:checked`)?.focus();
  };

  const fail = (field: Field | null, message: string) => {
    setError({ field, message });
    setTimeout(() => {
      if (field) focusField(field);
    }, 0);
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending || sent) return;
    const problem = junctionProblem(level, direction, reason, shown);
    if (problem) {
      fail(problem.field, problem.message);
      return;
    }
    setError(null);
    setSending(true);
    const outcome = await sendJunctionSuggestion(
      origin,
      { lat: junction.lat, lon: junction.lon, level, direction, shown, reason: reason.trim() },
      csrfFromCookie(document.cookie),
    );
    setSending(false);
    if (outcome.kind === "refused") {
      const field = outcome.field === "level" || outcome.field === "direction" || outcome.field === "reason" ? outcome.field : null;
      fail(field, outcome.message);
      return;
    }
    setSent(true);
    setSaid(outcome.message);
    headingRef.current?.focus();
  };

  const invalid = (field: Field) => (error?.field === field ? true : undefined);
  const describedBy = (field: Field) => (error?.field === field ? id("error") : undefined);
  return (
    <section className="stress-editor suggest-change suggest-junction" aria-labelledby={id("title")}>
      <h3 id={id("title")} ref={headingRef} tabIndex={-1}>
        {JUNCTION_SUGGEST_HEADING}
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
            <span className="road-info-label">{t("This junction:")}</span> {junction.name}
          </p>
          <p className="stress-editor-now">{t("Now:")}{" "}{shown ? SHOWN_WORDS[shown] : t("not marked")}.</p>
          <fieldset
            id={id("level")}
            className="stress-editor-field suggest-junction-group"
            role="radiogroup"
            aria-labelledby={id("level-legend")}
            aria-invalid={invalid("level")}
            aria-describedby={describedBy("level")}
          >
            <legend id={id("level-legend")}>{JUNCTION_LEVEL_LEGEND}</legend>
            <label className="suggest-junction-choice">
              <input type="radio" name={id("level-choice")} checked={level === null} onChange={() => setLevel(null)} />
              {t("Not sure: only compare with the map")}
            </label>
            {JUNCTION_LEVELS.map((choice) => (
              <label key={choice.level} className="suggest-junction-choice">
                <input type="radio" name={id("level-choice")} checked={level === choice.level} onChange={() => setLevel(choice.level)} />
                {choice.words}
              </label>
            ))}
          </fieldset>
          <fieldset
            id={id("direction")}
            className="stress-editor-field suggest-junction-group"
            role="radiogroup"
            aria-labelledby={id("direction-legend")}
            aria-invalid={invalid("direction")}
            aria-describedby={describedBy("direction")}
          >
            <legend id={id("direction-legend")}>{JUNCTION_DIRECTION_LEGEND}</legend>
            <label className="suggest-junction-choice">
              <input type="radio" name={id("direction-choice")} checked={direction === null} onChange={() => setDirection(null)} />
              {t("No comparison")}
            </label>
            {(["more", "less"] as const).map((choice) => (
              <label key={choice} className="suggest-junction-choice">
                <input type="radio" name={id("direction-choice")} checked={direction === choice} onChange={() => setDirection(choice)} />
                {DIRECTION_WORDS[choice]}
              </label>
            ))}
          </fieldset>
          <div className="stress-editor-field">
            <label htmlFor={id("reason")}>{SUGGEST_REASON_LABEL}</label>
            <textarea
              id={id("reason")}
              rows={3}
              value={reason}
              required
              aria-required="true"
              aria-invalid={invalid("reason")}
              aria-describedby={`${id("reason-help")}${error?.field === "reason" ? ` ${id("error")}` : ""}`}
              onChange={(event) => setReason(event.target.value)}
            />
            <p id={id("reason-help")} className="hint">
              {JUNCTION_PRIVACY} {countText(reason.trim(), JUNCTION_REASON_MAX)}.
            </p>
          </div>
          <div className="stress-editor-buttons">
            <button type="submit" aria-disabled={sending ? true : undefined}>
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
