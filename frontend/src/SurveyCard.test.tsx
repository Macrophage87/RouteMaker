// A survey spot's card, as the rider sees it (lib/surveySpots.ts; the owner, 2026-11-25), and the spots a ride passed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, render } from "./testSupport/render.ts";
import { SurveyCard } from "./SurveyCard.tsx";
import { SurveySection } from "./app/SurveySection.tsx";
import { spotsPassed, type SurveyMine, type SurveySpot } from "./lib/surveySpots.ts";

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
  let closed = 0;
  const screen = await render(
    <SurveyCard spot={spot} origin="" signedIn={signedIn} fetcher={fetcher} onSent={(_s, mine) => got.push(mine)} onClose={() => closed++} />,
  );
  await settle();
  return { screen, sent, got, closed: () => closed };
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
  const { screen, sent, got } = await card();
  await click(screen.get("radio", "Today"));
  await click(screen.button("Send"));
  await settle();
  assert.deepEqual(sent[0].body, { spot: "s101", answers: { when: "today" } });
  assert.deepEqual(got, [{ done: ["s101"], count: 1 }]);
  assert.match(screen.text(), /Thanks\. Your answers will help rate this road\./);
  assert.equal(screen.all("button", "Send").length, 0, "answered once");
  assert.ok(screen.button("Done"));
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
