/**
 * Review's closures (v0.7.0 closures; lib/closureReview.ts), for a reviewer: riders' closure reports (from the short
 * Suggest form's "Closed" reason) to confirm or reject, and the closures reviewers confirmed, in force or to come, to
 * end early. Nothing shows for anyone else.
 *
 * Built like SuggestionReview.tsx: a Show button reads the list; each item's heading names its road and every
 * button is described by it; Confirm closure opens the closure form (ClosureEntry.tsx) under the report; Reject and
 * End now ask first ("Yes, reject" / "Keep it"); every result is a sentence in the section's polite status region,
 * always in the page; after an action the list is read again and the focus goes to its part's heading.
 */
import { useEffect, useId, useState } from "react";
import { ClosureEntry } from "./ClosureEntry.tsx";
import { CLOSURES_HEADING, endClosure, fetchClosureReview, rejectReport, type ClosureReviewList } from "./lib/closureReview.ts";
import { fetchMe } from "./lib/stressEditor.ts";
import { mapLink } from "./lib/suggestions.ts";

export function ClosureReview() {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const [reviewer, setReviewer] = useState(false);
  const [list, setList] = useState<ClosureReviewList | null>(null);
  const [problem, setProblem] = useState("");
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  // The report whose closure form is open, and the item asking "Yes / Keep it".
  const [confirming, setConfirming] = useState<number | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [focusNext, setFocusNext] = useState<string | null>(null);
  const origin = window.location.origin;

  useEffect(() => {
    void fetchMe(origin).then((me) => setReviewer(me.can_review_closures));
  }, [origin]);

  useEffect(() => {
    if (focusNext === null) return;
    document.getElementById(focusNext)?.focus();
    setFocusNext(null);
  }, [focusNext, list, asking, confirming]);

  if (!reviewer) return null;

  const load = async (after?: string) => {
    const next = await fetchClosureReview(origin);
    if (typeof next === "string") {
      setProblem(next);
      return;
    }
    setProblem("");
    setList(next);
    if (after) setFocusNext(after);
  };

  // After an action: the list again, and the focus on the section's heading of what is left.
  const done = (message: string, ok: boolean, focus: string) => {
    setSaid(message);
    setAsking(null);
    setConfirming(null);
    if (ok) void load(focus);
  };

  const reports = list?.reports ?? [];
  const closures = list?.closures ?? [];
  return (
    <section aria-labelledby={id("heading")} className="suggestion-review closure-review">
      <h3 id={id("heading")}>{CLOSURES_HEADING}</h3>
      <p className="hint">
        Riders' closure reports wait here to confirm or reject, with the closures reviewers confirmed. A confirmed closure is routed round and named
        on routes as the agencies' closures are; end it here when it reopens. Mark a road closed from its road panel.
      </p>
      <p role="status" className="suggestion-review-said">
        {said}
      </p>
      <button type="button" className="secondary" onClick={() => void load()}>
        {list === null ? "Show closures" : "Refresh closures"}
      </button>
      {problem && <p role="alert">{problem}</p>}
      {list !== null && (
        <>
          <h4 id={id("reports")} tabIndex={-1}>
            Closure reports
          </h4>
          {reports.length === 0 && <p>No closure reports are waiting.</p>}
          {reports.length > 0 && (
            <ul className="suggestion-list" aria-labelledby={id("reports")}>
              {reports.map((r) => {
                const head = id(`r${r.id}`);
                return (
                  <li key={r.id} className="suggestion-item suggestion-item-closure">
                    <h5 id={head} tabIndex={-1}>
                      {r.road}: reported closed
                    </h5>
                    <p className="suggestion-reason">
                      <span className="road-info-label">Rider's reason:</span> {r.reason}
                    </p>
                    <p>
                      <a href={mapLink(origin, r)} aria-describedby={head}>
                        Show on map
                      </a>
                    </p>
                    {confirming === r.id ? (
                      <ClosureEntry
                        origin={origin}
                        wayId={r.osm_way_id}
                        title={r.road}
                        report={{ id: r.id, reason: r.reason_fixed }}
                        onClose={() => {
                          setConfirming(null);
                          setFocusNext(id(`c${r.id}`));
                        }}
                        onDone={(message) => done(message, true, id("reports"))}
                      />
                    ) : (
                      <div className="stress-editor-buttons">
                        <button type="button" id={id(`c${r.id}`)} aria-describedby={head} onClick={() => setConfirming(r.id)}>
                          Confirm closure
                        </button>
                        <button
                          type="button"
                          id={id(`x${r.id}`)}
                          className="secondary"
                          aria-describedby={head}
                          aria-expanded={asking === `r${r.id}`}
                          onClick={() => {
                            setAsking(`r${r.id}`);
                            setFocusNext(id(`yr${r.id}`));
                          }}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                    {asking === `r${r.id}` && (
                      <div className="suggestion-confirm" role="group" aria-labelledby={id(`qr${r.id}`)}>
                        <p id={id(`qr${r.id}`)}>Reject this report? It is deleted.</p>
                        <div className="stress-editor-buttons">
                          <button
                            type="button"
                            id={id(`yr${r.id}`)}
                            aria-describedby={head}
                            aria-disabled={busy ? true : undefined}
                            onClick={() => {
                              if (busy) return;
                              setBusy(true);
                              void rejectReport(origin, r.id).then((outcome) => {
                                setBusy(false);
                                done(outcome.message, outcome.kind === "done", id("reports"));
                              });
                            }}
                          >
                            Yes, reject
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => {
                              setAsking(null);
                              setFocusNext(id(`x${r.id}`));
                            }}
                          >
                            Keep it
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          <h4 id={id("closures")} tabIndex={-1}>
            Confirmed closures
          </h4>
          {closures.length === 0 && <p>No confirmed closures are in force or to come.</p>}
          {closures.length > 0 && (
            <ul className="suggestion-list" aria-labelledby={id("closures")}>
              {closures.map((c) => {
                const head = id(`k${c.id}`);
                return (
                  <li key={c.id} className="suggestion-item suggestion-item-closure">
                    <h5 id={head} tabIndex={-1}>
                      {c.road}
                    </h5>
                    <p className="suggestion-detail">{c.when_text}.</p>
                    <p className="suggestion-reason">
                      <span className="road-info-label">Reason:</span> {c.reason}
                    </p>
                    {c.point && (
                      <p>
                        <a href={mapLink(origin, { lon: c.point[0], lat: c.point[1] })} aria-describedby={head}>
                          Show on map
                        </a>
                      </p>
                    )}
                    <div className="stress-editor-buttons">
                      <button
                        type="button"
                        id={id(`e${c.id}`)}
                        className="secondary"
                        aria-describedby={head}
                        aria-expanded={asking === `k${c.id}`}
                        onClick={() => {
                          setAsking(`k${c.id}`);
                          setFocusNext(id(`yk${c.id}`));
                        }}
                      >
                        End now
                      </button>
                    </div>
                    {asking === `k${c.id}` && (
                      <div className="suggestion-confirm" role="group" aria-labelledby={id(`qk${c.id}`)}>
                        <p id={id(`qk${c.id}`)}>End this closure now? New plans use the road again.</p>
                        <div className="stress-editor-buttons">
                          <button
                            type="button"
                            id={id(`yk${c.id}`)}
                            aria-describedby={head}
                            aria-disabled={busy ? true : undefined}
                            onClick={() => {
                              if (busy) return;
                              setBusy(true);
                              void endClosure(origin, c.id).then((outcome) => {
                                setBusy(false);
                                done(outcome.message, outcome.kind === "done", id("closures"));
                              });
                            }}
                          >
                            Yes, end it
                          </button>
                          <button
                            type="button"
                            className="secondary"
                            onClick={() => {
                              setAsking(null);
                              setFocusNext(id(`e${c.id}`));
                            }}
                          >
                            Keep it
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
