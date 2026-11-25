// A survey spot's card, as the rider sees it (lib/surveySpots.ts; the owner, 2026-11-25), and the spots a ride passed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, render } from "./testSupport/render.ts";
import { SurveyCard } from "./SurveyCard.tsx";
import { SurveySection } from "./app/SurveySection.tsx";
import { RideSummaryCard } from "./RideSummaryCard.tsx";
import { statsStart } from "./lib/rideStats.ts";
import { spotsNear, spotsPassed, surveyIcon, type SurveyMine, type SurveySpot } from "./lib/surveySpots.ts";

const spot: SurveySpot = { id: "s101", road: "Ohio Drive Southwest", lon: -77.03, lat: 38.87 };
const QUESTIONS = [
  { key: "when", text: "When were you last here?", options: [{ value: "today", label: "Today" }, { value: "longer", label: "Longer ago" }] },
  { key: "traffic", text: "How busy was it?", options: [{ value: "quiet", label: "Quiet: a car now and then" }, { value: "not_sure", label: "Not sure" }] },
];

function server(answer: { status: number; body?: unknown } = { status: 200, body: { done: ["s101"], count: 1 } }) {
  const sent: { url: string; body: unknown }[] = [];
  const fetcher = async (url: string, init?: RequestInit) => {
    if (url.endsWith("/questions")) return new Response(JSON.stringify({ questions: QUESTIONS }), { status: 200 });
    sent.push({ url, body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify(answer.body ?? {}), { status: answer.status });
  };
  return { fetcher, sent };
}

async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

async function card(signedIn = true, answer?: { status: number; body?: unknown }) {
  const { fetcher, sent } = server(answer);
  const got: SurveyMine[] = [];
  const closed: boolean[] = [];
  const screen = await render(
    <SurveyCard spot={spot} origin="" signedIn={signedIn} fetcher={fetcher} onSent={(_s, mine) => got.push(mine)} onClose={(sent) => closed.push(sent)} />,
  );
  await settle();
  return { screen, sent, got, closed };
}

test("the card asks when first, then the spot's own questions", async () => {
  const { screen } = await card();
  assert.ok(screen.dialog("Survey: Ohio Drive Southwest"));
  const text = screen.text();
  assert.ok(text.indexOf("When were you last here?") < text.indexOf("How busy was it?"));
  assert.ok(screen.get("radio", "Not sure"));
});

test("Send without when says to answer it and sends nothing", async () => {
  const { screen, sent } = await card();
  await click(screen.button("Send"));
  await settle();
  assert.match(screen.text(), /Say when you were last here\./);
  assert.equal(sent.length, 0);
});

test("a sent answer says thanks and hands back the rider's count; skipped questions are not sent", async () => {
  const { screen, sent, got, closed } = await card();
  await click(screen.get("radio", "Today"));
  await click(screen.button("Send"));
  await settle();
  assert.deepEqual(sent[0].body, { spot: "s101", answers: { when: "today" } });
  assert.deepEqual(got, [{ done: ["s101"], count: 1 }]);
  assert.match(screen.text(), /Thanks\. Your answers will help rate this road\./);
  assert.equal(screen.all("button", "Send").length, 0, "answered once");
  await click(screen.button("Done"));
  assert.deepEqual(closed, [true], "Done after a send lets the next spot passed follow");
});

test("Cancel closes as not sent, so a ride's remaining spots stop there", async () => {
  const { screen, closed } = await card();
  await click(screen.button("Cancel"));
  assert.deepEqual(closed, [false]);
});

test("a spot already answered says so", async () => {
  const { screen } = await card(true, { status: 409 });
  await click(screen.get("radio", "Today"));
  await click(screen.button("Send"));
  await settle();
  assert.match(screen.text(), /You've already answered this spot\./);
});

test("signed out, the card asks the rider to sign in and has no questions", async () => {
  const { screen } = await card(false);
  assert.match(screen.text(), /Sign in to answer survey spots\./);
  assert.equal(screen.all("button", "Send").length, 0);
  assert.equal(screen.all("radio").length, 0);
});

test("the Layers section: its switch, hint and the rider's count", async () => {
  let on = false;
  const screen = await render(<SurveySection on={false} onChange={(v) => (on = v)} status="" count="Spots you have surveyed: 3. Answered on the day you rode there: 2." />);
  assert.match(screen.text(), /Survey spots/);
  await click(screen.get("switch", /Survey spots/));
  assert.equal(on, true);
});

test("a ride passes the spots its line comes within 40 m of, in the order passed", () => {
  const line: [number, number][] = [
    [-77.05, 38.87],
    [-77.0, 38.87],
  ];
  const near: SurveySpot = { ...spot, id: "near", lon: -77.02, lat: 38.8702 }; // about 22 m off
  const first: SurveySpot = { ...spot, id: "first", lon: -77.04, lat: 38.87 };
  const far: SurveySpot = { ...spot, id: "far", lon: -77.02, lat: 38.872 }; // about 220 m off
  assert.deepEqual(
    spotsPassed(line, [near, far, first]).map((s) => s.id),
    ["first", "near"],
  );
  assert.deepEqual(spotsPassed([], [near]), []);
});

test("the Layers list reaches a spot without the map: the nearest spots as buttons that open the card", async () => {
  const near: SurveySpot = { ...spot, id: "near", road: "Water Street Southwest", lon: -77.021, lat: 38.87 };
  const far: SurveySpot = { ...spot, id: "far", road: "Far Road", lon: -76.9, lat: 38.95 };
  assert.deepEqual(spotsNear([-77.02, 38.87], [far, near], 1).map((s) => s.id), ["near"]);
  const picked: string[] = [];
  const screen = await render(
    <SurveySection on onChange={() => {}} status="" count="" near={() => spotsNear([-77.02, 38.87], [far, near])} onPick={(s) => picked.push(s.id)} />,
  );
  await click(screen.button("Survey spots layers"));
  await click(screen.button("List spots near the map's centre"));
  await click(screen.button("Water Street Southwest"));
  assert.deepEqual(picked, ["near"]);
  await screen.rerender(
    <SurveySection on onChange={() => {}} status="" count="" near={() => spotsNear([-77.02, 38.87], [far, near])} spots={[far]} onPick={(s) => picked.push(s.id)} />,
  );
  assert.equal(screen.all("button", "Water Street Southwest").length, 0, "an answered spot leaves the list");
});

test("the marker is an orange '!' in a dark rim, clear around it", () => {
  const icon = surveyIcon(1, 26);
  const at = (x: number, y: number) => Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 4));
  assert.deepEqual(at(13, 8), [0xf9, 0x73, 0x16, 255], "the bar");
  assert.deepEqual(at(13, 21), [0xf9, 0x73, 0x16, 255], "the dot");
  assert.equal(at(13, 16)[3], 0, "a gap between them");
  assert.equal(at(2, 2)[3], 0, "nothing in the corner");
});

test("the ride's summary offers the spots it passed, and the line hands them over in order", async () => {
  const passed: SurveySpot[][] = [];
  const two = [spot, { ...spot, id: "s202", road: "4th Street Northeast" }];
  const props = { stats: statsStart(Date.now() - 600_000), endedAt: Date.now(), onDone: () => {}, onUndo: () => {}, onReports: () => {} };
  const screen = await render(<RideSummaryCard {...props} surveyPassed={two} onSurvey={(p) => passed.push(p)} />);
  await click(screen.button("You passed 2 survey spots. Answer them"));
  assert.deepEqual(passed[0].map((s) => s.id), ["s101", "s202"]);
  await screen.rerender(<RideSummaryCard {...props} surveyPassed={[]} onSurvey={() => {}} />);
  assert.equal(screen.all("button", /survey spot/).length, 0, "no line when it passed none");
});
