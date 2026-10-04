/** The routes to choose from (OWNER-DECISIONS 265). */
import assert from "node:assert/strict";
import test from "node:test";
import type { RouteResponse } from "./api.ts";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  announceHow,
  calmestOf,
  candidateRoute,
  candidateRows,
  candidatesHint,
  distanceAgainstFirst,
  rankName,
  routesOf,
  statsLine,
  statsOf,
} from "./candidates.ts";
import { CandidatePicker, candidateFieldset } from "./candidatePicker.ts";
import { announceRoute } from "./summary.ts";

function body(over: Partial<RouteResponse> = {}): RouteResponse {
  return {
    preset: "trailmaxxing",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [] },
    distance_m: 93_000,
    duration_s: 20_000,
    climb_m: 300,
    descent_m: 300,
    stress_m: { "1": 50_000, "2": 30_000, "3": 11_000, "4": 400, "5": 20 },
    facility_m: { path: 38_000, protected: 3_000 },
    intersections: [
      { severity: "red" },
      { severity: "orange" },
      { severity: "orange" },
    ] as never,
    effort_m: 150_000,
    attribution: [],
    ...over,
  } as RouteResponse;
}

const ALT = body({ rank: 2, distance_m: 95_000, stress_m: { "3": 10_000, "4": 100 }, intersections: [] });

test("one route has no candidates and no picker", () => {
  assert.deepEqual(routesOf(null), []);
  assert.equal(candidateRows(body()), null);
  assert.equal(candidateRows(body({ candidates: [] })), null);
  assert.equal(candidateRows(body({ candidates: null })), null);
  assert.deepEqual(announceHow(body(), 0, false), {});
  assert.deepEqual(announceHow(body(), 0, true), {});
  assert.equal(renderToStaticMarkup(createElement(CandidatePicker, { answer: body(), choice: 0, onChoose: () => {} })), "");
  assert.equal(candidateRoute(null, 0), null);
});

test("the answer is first and its candidates follow in rank order", () => {
  const answer = body({ rank: 1, candidates: [ALT, body({ rank: 3 })] });
  assert.deepEqual(
    routesOf(answer).map((r) => r.rank),
    [1, 2, 3],
  );
  assert.equal(candidateRoute(answer, 0), answer);
  assert.equal(candidateRoute(answer, 1), ALT);
  assert.equal(candidateRoute(answer, 7), answer, "out of range is the answer");
  assert.equal(candidateRoute(answer, -1), answer);
});

test("each row's name is short: its rank with a separator, its distance, and how that differs from Route 1 (the a11y review's SF2)", () => {
  const rows = candidateRows(body({ rank: 1, candidates: [ALT] }))!;
  assert.equal(rows.length, 2);
  // Route 1 here has more heavy-traffic road than Route 2, so it is not called the calmest (the spec review's NIT1).
  assert.equal(rows[0].name, "Route 1: 57.8 mi (93.0 km)");
  assert.equal(rows[1].name, "Route 2: 59.0 mi (95.0 km), 1.2 mi (2.0 km) more than Route 1");
  for (const row of rows) assert.match(row.name, /^Route \d+[:,]/);
  assert.equal(rankName(3), "Route 3:");
  assert.equal(rankName(1), "Route 1:");
  assert.equal(rankName(1, true), "Route 1, the calmest:");
  assert.equal(rankName(2, true), "Route 2:", "only Route 1 is ever called the calmest");
});

test("Route 1 is called the calmest only when no other has less of any stress figure", () => {
  const calm = body({ rank: 1, stress_m: { "3": 1_000 }, intersections: [], candidates: [body({ rank: 2, stress_m: { "3": 2_000, "4": 50 } })] });
  assert.equal(candidateRows(calm)![0].name, "Route 1, the calmest: 57.8 mi (93.0 km)");
  const one = statsOf(body(), 1);
  assert.equal(calmestOf(one, [one]), true);
  for (const better of [{ lts4M: 0 }, { red: 0 }, { lts3M: 0 }, { orange: 0 }]) {
    assert.equal(calmestOf(one, [one, { ...one, ...better }]), false, JSON.stringify(better));
  }
  assert.equal(calmestOf(one, [one, { ...one, distanceM: 1 }]), true, "distance is not stress");
});

test("the difference from Route 1 is said in words, miles first, either way, and as the same where it is", () => {
  assert.equal(distanceAgainstFirst(11_600, 11_200), "0.2 mi (0.4 km) more than Route 1");
  assert.equal(distanceAgainstFirst(10_800, 11_200), "0.2 mi (0.4 km) less than Route 1");
  assert.equal(distanceAgainstFirst(11_230, 11_200), "the same distance as Route 1");
});

test("the description has the figures in words, miles first, in plain words, and leaves out the ones that are zero", () => {
  const rows = candidateRows(body({ rank: 1, candidates: [ALT] }))!;
  assert.match(rows[0].line, /^0\.3 mi \(0\.4 km\) of heavy-traffic or best-avoided roads, 6\.8 mi \(11\.0 km\) of busy roads/);
  assert.doesNotMatch(rows[0].line, /LTS/, "plain words");
  assert.match(rows[0].line, /1 very high stress junction, 2 higher stress junctions/);
  assert.match(rows[0].line, /25\.5 mi \(41\.0 km\) on trails and protected lanes/);
  assert.match(rows[0].line, /climb 984 ft \(300 m\)/);
  assert.match(rows[0].line, /effort equal to 93\.2 mi \(150\.0 km\) on the flat/);
  // Route 2 has no junctions: nothing is said of them.
  assert.doesNotMatch(rows[1].line, /junction/);
  assert.doesNotMatch(rows[1].line, /(^|, )0 /);
  const bare = statsLine({ ...statsOf(body(), 1), lts4M: 0, lts3M: 0, red: 0, orange: 0, trailM: 0, climbM: 0, effortM: null });
  assert.equal(bare, "");
  assert.equal(statsLine({ ...statsOf(body(), 1), lts4M: 50, lts3M: 0, red: 0, orange: 0, trailM: 0, climbM: 0, effortM: null }), "", "under 0.05 mi reads as 0.0 mi: left out");
});

test("LTS 4 and Avoid count together, and trail is path plus protected", () => {
  const stats = statsOf(body(), 1);
  assert.equal(stats.lts4M, 420);
  assert.equal(stats.trailM, 41_000);
  assert.equal(stats.red, 1);
  assert.equal(stats.orange, 2);
  assert.equal(stats.effortM, 150_000);
  assert.equal(statsOf(body({ effort_m: undefined, facility_m: undefined, intersections: null }), 1).effortM, null);
  assert.doesNotMatch(statsLine(statsOf(body({ effort_m: null }), 1)), /effort equal/);
});

test("choosing one is said as chosen with its place; arrival says how many others there are (the a11y review's N4)", () => {
  const answer = body({ rank: 1, candidates: [ALT] });
  assert.deepEqual(announceHow(answer, 0, false), { others: 1 });
  assert.deepEqual(announceHow(answer, 1, true), { chosen: { rank: 2, of: 2 } });
  assert.deepEqual(announceHow(answer, 9, true), { chosen: { rank: 2, of: 2 } });
  assert.deepEqual(announceHow(answer, 0, true), { chosen: { rank: 1, of: 2 } });
  const chosen = announceRoute(candidateRoute(answer, 1)!, [], announceHow(answer, 1, true));
  assert.match(chosen, /^Route 2 of 2 chosen: 59\.0 mi/);
  assert.doesNotMatch(chosen, /Route planned/, "nothing was planned");
  assert.doesNotMatch(chosen, /to choose from/);
  const arrival = announceRoute(answer, [], announceHow(answer, 0, false));
  assert.match(arrival, /^Route planned: 57\.8 mi/);
  assert.match(arrival, /1 other route to choose from, under Routes to choose from\.$/);
  const three = body({ rank: 1, candidates: [ALT, body({ rank: 3 })] });
  assert.match(announceRoute(three, [], announceHow(three, 0, false)), /2 other routes to choose from, under Routes to choose from\.$/);
});

test("each says how far over the rider's target it is, and only when it is (OWNER-DECISIONS 271)", () => {
  const answer = body({
    rank: 1,
    calm_search: { rate: 10, rounds: 1, excluded: 1, limited: null, target_distance_m: 92_000, over_target_m: 1_000 },
    candidates: [{ ...ALT, over_target_m: 3_000 }, body({ rank: 3, over_target_m: 0 })],
  });
  const rows = candidateRows(answer)!;
  assert.match(rows[0].line, /^0\.6 mi \(1\.0 km\) over your target, 0\.3 mi/);
  assert.match(rows[1].line, /^1\.9 mi \(3\.0 km\) over your target, /);
  assert.doesNotMatch(rows[2].line, /over your target/);
  assert.equal(statsOf(body(), 1).overTargetM, null);
  assert.doesNotMatch(statsLine(statsOf(body(), 1)), /target/);
});

test("the shared hint mentions the target only when one is set, and does not ask the rider to look at the map", () => {
  const set = body({ calm_search: { rate: 10, rounds: 1, excluded: 1, limited: null, target_distance_m: 92_000 } });
  assert.equal(candidatesHint(set), "Each is about as calm as the first, and no further over your target distance. The map shows the one chosen, and the route description below follows it.");
  assert.equal(candidatesHint(body()), "Each is about as calm as the first. The map shows the one chosen, and the route description below follows it.");
  assert.doesNotMatch(candidatesHint(set), /scenery|see there/);
});

/** The picker as the page has it, and each radio's attributes. */
function picker(answer: RouteResponse, choice = 0) {
  const html = renderToStaticMarkup(createElement(CandidatePicker, { answer, choice, onChoose: () => {} }));
  const radios = [...html.matchAll(/<input ([^>]*)\/>/g)].map((m) => Object.fromEntries([...m[1].matchAll(/([a-z-]+)="([^"]*)"/g)].map((a) => [a[1], a[2]])));
  /** The text of the element with this id. */
  const byId = (id: string) => {
    const at = html.indexOf(`id="${id}"`);
    if (at < 0) return undefined;
    const open = html.indexOf(">", at);
    return html.slice(open + 1, html.indexOf("<", open));
  };
  return { html, radios, byId };
}

test("the picker: a fieldset described by the hint once, each radio named by its short name and described by its own figures", () => {
  const answer = body({ rank: 1, candidates: [ALT, body({ rank: 3, distance_m: 90_000 })] });
  const { html, radios, byId } = picker(answer, 1);
  const fieldset = /<fieldset class="candidates" aria-describedby="([^"]+)">/.exec(html);
  assert.ok(fieldset, html.slice(0, 200));
  assert.equal(byId(fieldset[1]), candidatesHint(answer), "the group's description is the hint");
  assert.match(html, /<legend>Routes to choose from<\/legend>/);
  assert.equal(radios.length, 3);
  const rows = candidateRows(answer)!;
  radios.forEach((radio, i) => {
    assert.equal(radio.type, "radio");
    assert.equal(byId(radio["aria-labelledby"]), rows[i].name, `radio ${i + 1}'s name`);
    assert.equal(byId(radio["aria-describedby"]), rows[i].line, `radio ${i + 1}'s description`);
    assert.notEqual(radio["aria-describedby"], fieldset[1], "not the shared hint");
  });
  assert.equal(new Set(radios.map((r) => r.name)).size, 1, "one group");
  assert.deepEqual(radios.map((r) => "checked" in r), [false, true, false]);
  assert.match(rows[2].name, /^Route 3: 55\.9 mi \(90\.0 km\), 1\.9 mi \(3\.0 km\) less than Route 1$/);
});

test("the picker tells the app which was chosen", () => {
  const answer = body({ rank: 1, candidates: [ALT] });
  const got: number[] = [];
  const fieldset = candidateFieldset("c", { answer, choice: 0, onChoose: (i) => void got.push(i) })!;
  const labels = (fieldset.props.children as unknown[]).flat().filter((c) => (c as { type?: string })?.type === "label") as Array<{ props: { children: Array<{ props: { onChange?: () => void } }> } }>;
  labels[1].props.children[0].props.onChange?.();
  labels[0].props.children[0].props.onChange?.();
  assert.deepEqual(got, [1, 0]);
});
