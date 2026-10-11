/**
 * The instance admin's review of rider suggestions (OWNER-DECISIONS 460.5; lib/suggestions.ts), in the
 * Settings sheet. Nothing shows for anyone else. Roads' and junctions' suggestions (OWNER-DECISIONS 232;
 * lib/junctionSuggest.ts) are one list, oldest first; a list that did not load is named. The same review lists the riders' Mass Ride hazard
 * reports (FOLLOWUP-MASSRIDE-MAP part 3; lib/massHazards.ts), as a second section of its own: `source`
 * says which (lib/reviewSources.ts), and the actions, the focus and the words are the same for both.
 *
 * Each suggestion has the owner's three actions (2026-10-10): Approve now (applied at once, as the
 * editor's change), Delete, and Send to Discord, which shows the ready-to-paste plain-English poll in a
 * read-only text box with a Copy post button; the suggestion is marked as sent and stays in the list to
 * approve or delete later. Every action button's name says which road it is for (aria-describedby the
 * suggestion's heading); every result, "Copied" included, is a sentence in the section's polite status
 * region, which is always in the page. Status is said in words, never by colour alone.
 *
 * Delete asks first ("Yes, delete" / "Keep it"), and so does Approve now where an item carries a warning (a
 * junction level that would withdraw an approved Avoid junction: "Yes, approve" / "Don't approve"). After Approve now or Delete the suggestion leaves the
 * list and the focus goes to the next one's heading (the one before, at the end), or to the "No
 * suggestions are waiting" line when none is left: never to the top of the page.
 */
import { useEffect, useId, useRef, useState } from "react";
import { copyText, selectionCopy } from "./lib/sidebar.ts";
import { csrfFromCookie, fetchMe } from "./lib/stressEditor.ts";
import { COPIED, COPY_FAILED, COPY_POST, mapLink, type DiscordPost, type ReviewAction } from "./lib/suggestions.ts";
import { STRESS_REVIEW, itemKey, itemPlace, type ReviewItem, type ReviewSource } from "./lib/reviewSources.ts";

interface Props<T extends ReviewItem> {
  /** A change was approved: the map asks for its stress tiles again. */
  onStressChanged?: (generation: number) => void;
  /** Any approval (a hazard's: the Mass Ride map asks for its hazards again). */
  onApproved?: () => void;
  /** What is reviewed: the stress suggestions (the default) or the Mass Ride hazard reports. */
  source?: ReviewSource<T>;
}

export function SuggestionReview<T extends ReviewItem>({ onStressChanged, onApproved, source }: Props<T>) {
  const from = (source ?? STRESS_REVIEW) as unknown as ReviewSource<T>;
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const [admin, setAdmin] = useState(false);
  const [items, setItems] = useState<T[] | null>(null);
  const [problem, setProblem] = useState("");
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [posts, setPosts] = useState<Record<string, DiscordPost>>({});
  // The suggestion whose Delete is asking "Yes, delete / Keep it", and where the focus goes next.
  const [confirming, setConfirming] = useState<string | null>(null);
  // The suggestion whose Approve now is waiting on its warning's confirmation.
  const [warned, setWarned] = useState<string | null>(null);
  const [focusNext, setFocusNext] = useState<string | null>(null);
  // The list as last drawn: an action's answer arrives after a wait, when `items` captured at its
  // start may be out of date (a refresh, another action).
  const itemsNow = useRef<T[] | null>(null);
  itemsNow.current = items;
  const origin = window.location.origin;

  useEffect(() => {
    void fetchMe(origin).then((me) => setAdmin(me.can_change_lts));
  }, [origin]);

  useEffect(() => {
    if (focusNext === null) return;
    document.getElementById(focusNext)?.focus();
    setFocusNext(null);
  }, [focusNext, items, confirming, warned]);

  const load = async () => {
    const next = await from.fetch(origin);
    if (typeof next === "string") setProblem(next);
    else if (Array.isArray(next)) {
      setProblem("");
      setItems(next);
    } else {
      // Part of it came: shown, with a sentence naming the list that did not.
      setProblem(next.problem);
      setItems(next.items);
    }
  };

  if (!admin) return null;

  const act = async (item: T, action: ReviewAction) => {
    if (busy !== null) return;
    const key = itemKey(item);
    setBusy(key);
    const csrf = csrfFromCookie(document.cookie);
    if (action === "discord") {
      const r = await from.review<DiscordPost>(origin, item, "discord", csrf);
      setBusy(null);
      if (!r.ok) {
        setSaid(r.message);
        return;
      }
      setPosts((old) => ({ ...old, [key]: r.body }));
      setItems((old) => old?.map((s) => (itemKey(s) === key ? { ...s, status: "sent_to_discord" } : s)) ?? old);
      setSaid(`The post for ${itemPlace(item)} is ready to copy below. The ${from.noun} is marked as sent to Discord.`);
      return;
    }
    const r = await from.review<{ message: string; status: string; generation?: number | null }>(origin, item, action, csrf);
    setBusy(null);
    if (!r.ok) {
      setSaid(r.message);
      return;
    }
    setSaid(r.body.message);
    if (action === "approve") {
      if (from.stress && item.kind !== "junction" && typeof r.body.generation === "number") onStressChanged?.(r.body.generation);
      onApproved?.();
    }
    setConfirming(null);
    setWarned(null);
    const list = itemsNow.current ?? [];
    const at = list.findIndex((s) => itemKey(s) === key);
    const rest = list.filter((s) => itemKey(s) !== key);
    const next = rest[Math.min(Math.max(at, 0), rest.length - 1)];
    setItems((old) => old?.filter((s) => itemKey(s) !== key) ?? old);
    setFocusNext(next ? id(`s${itemKey(next)}`) : id("none"));
  };

  const copy = async (item: T) => {
    const post = posts[itemKey(item)];
    if (!post) return;
    const done = await copyText(post.post, navigator.clipboard, selectionCopy);
    // Said again on a second press: the region is cleared first so the same word is spoken again.
    setSaid("");
    setTimeout(() => setSaid(done ? `${COPIED}. The post for ${itemPlace(item)} is on the clipboard.` : COPY_FAILED), 50);
  };

  return (
    <section aria-labelledby={id("heading")} className={`suggestion-review ${from.key}-review`}>
      <h3 id={id("heading")}>{from.heading}</h3>
      <p className="hint">{from.intro}</p>
      <p role="status" className="suggestion-review-said">
        {said}
      </p>
      <button type="button" className="secondary" onClick={() => void load()}>
        {items === null ? from.show : from.refresh}
      </button>
      {problem && <p role="alert">{problem}</p>}
      {items !== null && items.length === 0 && (
        <p id={id("none")} tabIndex={-1}>
          {from.none}
        </p>
      )}
      {items !== null && items.length > 0 && (
        <ul className="suggestion-list" aria-label={from.listLabel}>
          {items.map((item) => {
            const key = itemKey(item);
            const head = id(`s${key}`);
            const post = posts[key];
            return (
              <li key={key} className={item.kind ? `suggestion-item suggestion-item-${item.kind}` : "suggestion-item"}>
                <h4 id={head} tabIndex={-1}>
                  {from.line(item)}
                </h4>
                <p className="suggestion-status">
                  {item.status === "sent_to_discord" ? "Sent to Discord; waiting for your decision." : "Waiting for review."}
                </p>
                {item.detail && <p className="suggestion-detail">{item.detail}</p>}
                <p className="suggestion-reason">
                  <span className="road-info-label">Rider's reason:</span> {item.reason}
                </p>
                {item.lat !== null && item.lon !== null && (
                  <p>
                    <a href={mapLink(origin, { lat: item.lat, lon: item.lon })} aria-describedby={head}>
                      Show on map
                    </a>
                  </p>
                )}
                <div className="stress-editor-buttons">
                  <button
                    type="button"
                    id={id(`a${key}`)}
                    aria-describedby={head}
                    aria-expanded={item.warning ? warned === key : undefined}
                    aria-disabled={busy !== null ? true : undefined}
                    onClick={() => {
                      if (!item.warning) {
                        void act(item, "approve");
                        return;
                      }
                      setWarned(key);
                      setConfirming(null); // one question open at a time
                      setFocusNext(id(`w${key}`));
                    }}
                  >
                    Approve now
                  </button>
                  <button type="button" className="secondary" aria-describedby={head} aria-disabled={busy !== null ? true : undefined} onClick={() => void act(item, "discord")}>
                    Send to Discord
                  </button>
                  <button
                    type="button"
                    id={id(`d${key}`)}
                    className="secondary"
                    aria-describedby={head}
                    aria-expanded={confirming === key}
                    aria-disabled={busy !== null ? true : undefined}
                    onClick={() => {
                      setConfirming(key);
                      setWarned(null); // one question open at a time
                      setFocusNext(id(`y${key}`));
                    }}
                  >
                    Delete
                  </button>
                </div>
                {item.warning && warned === key && (
                  <div className="suggestion-confirm" role="group" aria-labelledby={id(`wq${key}`)}>
                    <p id={id(`wq${key}`)}>{item.warning}</p>
                    <div className="stress-editor-buttons">
                      <button
                        type="button"
                        id={id(`w${key}`)}
                        aria-describedby={head}
                        aria-disabled={busy !== null ? true : undefined}
                        onClick={() => void act(item, "approve")}
                      >
                        Yes, approve
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setWarned(null);
                          setFocusNext(id(`a${key}`));
                        }}
                      >
                        Don't approve
                      </button>
                    </div>
                  </div>
                )}
                {confirming === key && (
                  <div className="suggestion-confirm" role="group" aria-labelledby={id(`q${key}`)}>
                    <p id={id(`q${key}`)}>{from.deleteQuestion}</p>
                    <div className="stress-editor-buttons">
                      <button
                        type="button"
                        id={id(`y${key}`)}
                        aria-describedby={head}
                        aria-disabled={busy !== null ? true : undefined}
                        onClick={() => void act(item, "delete")}
                      >
                        Yes, delete
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setConfirming(null);
                          setFocusNext(id(`d${key}`));
                        }}
                      >
                        Keep it
                      </button>
                    </div>
                  </div>
                )}
                {post && (
                  <div className="suggestion-post">
                    <label htmlFor={id(`p${key}`)}>Post for Discord ({post.characters} of 2,000 characters)</label>
                    <textarea id={id(`p${key}`)} readOnly rows={12} value={post.post} />
                    <button type="button" aria-describedby={head} onClick={() => void copy(item)}>
                      {COPY_POST}
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
