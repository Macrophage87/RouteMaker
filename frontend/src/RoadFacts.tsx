/**
 * The facts behind a road's level, in the road panel (RoadInfoDialog.tsx; the owner, 2026-11-13:
 * "redesign the panel of each road to adequately reflect the available raw data when people look
 * at a spot"; mockups/road-panel-raw-data). An inverted pyramid: one plain sentence, how much of
 * the level rests on records ("Strong evidence: 4 of 5 from records", with a filled mark for each
 * record and a hollow one for each estimate), then one line a fact with its source and date. Each
 * fact's (i) opens its longer note in place: the full source, and how the level uses it.
 *
 * A road with little data shows hollow marks and "estimated" beside each estimate, so it looks thin.
 * The marks are never the only cue: the words say the same, and the marks are hidden from screen
 * readers, which hear "Traffic: 24,100 vehicles a day, from a record, DDOT count, 2023".
 */
import { useState } from "react";
import {
  evidenceMarks,
  FACT_KIND_WORDS,
  factInfoLabel,
  factSourceLine,
  type RoadEvidence,
  type RoadFact,
} from "./lib/roadInfo.ts";
import { t } from "./lib/i18n.ts";

export function RoadFacts({
  facts,
  evidence,
  plain,
  uid,
}: {
  facts: RoadFact[];
  evidence: RoadEvidence | null;
  plain: string | null;
  uid: string;
}) {
  const [open, setOpen] = useState<string | null>(null);
  if (facts.length === 0) return null;
  return (
    <div className="road-facts">
      {plain && <p className="road-facts-plain">{plain}</p>}
      {evidence && (
        <p className={`road-facts-evidence road-facts-evidence-${evidence.strength}`}>
          <span className="road-facts-marks" aria-hidden="true">
            {evidenceMarks(evidence).map((on, n) => (
              <span key={n} className={on ? "road-facts-mark road-facts-mark-on" : "road-facts-mark"} />
            ))}
          </span>
          <span>{evidence.words}</span>
        </p>
      )}
      <ul className="road-facts-list" aria-label={t("What the level rests on")}>
        {facts.map((fact) => {
          const noteId = `${uid}-fact-${fact.id}`;
          const shown = open === fact.id;
          return (
            <li key={fact.id} className={`road-facts-row road-facts-row-${fact.kind}`}>
              <span className={fact.kind === "record" ? "road-facts-mark road-facts-mark-on" : "road-facts-mark"} aria-hidden="true" />
              <span className="road-facts-text">
                <span className="road-info-label">{fact.label}:</span> <span className="road-facts-value">{fact.value}</span>
                {fact.kind === "estimated" ? (
                  <>
                    {" "}
                    <span className="road-facts-estimated">{FACT_KIND_WORDS.estimated}</span>
                  </>
                ) : (
                  <span className="visually-hidden">, {FACT_KIND_WORDS.record}</span>
                )}
                {factSourceLine(fact) && (
                  <span className="road-facts-source">
                    <span className="visually-hidden">, </span>
                    {factSourceLine(fact)}
                  </span>
                )}
                {shown && fact.detail && (
                  <span className="road-facts-detail" id={noteId}>
                    {fact.detail}
                  </span>
                )}
              </span>
              {fact.detail && (
                <button
                  type="button"
                  className="road-facts-info"
                  aria-label={factInfoLabel(fact)}
                  aria-expanded={shown}
                  aria-controls={shown ? noteId : undefined}
                  onClick={() => setOpen(shown ? null : fact.id)}
                >
                  i
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
