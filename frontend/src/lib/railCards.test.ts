// The stations' hover card and tap card, run against a stand-in view.
import { test } from "node:test";
import assert from "node:assert/strict";
import { RailCards, type CardHandle } from "./railCards.ts";

function setup() {
  const calls: string[] = [];
  const cards: Array<CardHandle & { open: boolean }> = [];
  const view = {
    key: (found: string) => found,
    showHover: (found: string, hint: boolean) => calls.push(`hover:${found}${hint ? "+line" : ""}`),
    hideHover: () => calls.push("hide"),
    openCard: (found: string) => {
      calls.push(`card:${found}`);
      const card = {
        open: true,
        isOpen: () => card.open,
        remove: () => {
          if (card.open) calls.push(`closed:${found}`);
          card.open = false;
        },
      };
      cards.push(card);
      return card;
    },
  };
  return { rail: new RailCards<string>(view), calls, cards };
}

test("the hover card is built once per station, and again when the line hint changes", () => {
  const { rail, calls } = setup();
  rail.hover("a");
  rail.hover("a");
  rail.hover("a", true);
  rail.hover("b", true);
  rail.hover(null);
  rail.hover(null);
  assert.deepEqual(calls, ["hover:a", "hover:a+line", "hover:b+line", "hide"]);
});

test("no hover card while a station's card is open", () => {
  const { rail, calls } = setup();
  rail.open("a");
  calls.length = 0;
  rail.hover("b");
  assert.ok(!calls.some((c) => c.startsWith("hover:")), calls.join());
});

test("opening a card takes the hover card away and closes the card before it", () => {
  const { rail, calls } = setup();
  rail.hover("a");
  rail.open("a");
  rail.open("b");
  assert.deepEqual(calls, ["hover:a", "hide", "card:a", "closed:a", "card:b"]);
  assert.equal(rail.cardOpen(), true);
});

test("a card that closed itself (Escape, its close button, an action) is not open", () => {
  const { rail, cards } = setup();
  rail.open("a");
  assert.equal(rail.cardOpen(), true);
  cards[0].remove();
  assert.equal(rail.cardOpen(), false, "the next click is not swallowed by a card that is gone");
  assert.equal(rail.close(), false);
});

test("close says whether a card was open, and closes it", () => {
  const { rail, cards } = setup();
  assert.equal(rail.close(), false);
  rail.open("a");
  assert.equal(rail.close(), true);
  assert.equal(cards[0].open, false);
  assert.equal(rail.cardOpen(), false);
});

test("after a card closes, hovering the same station shows its hover card again", () => {
  const { rail, calls } = setup();
  rail.open("a");
  rail.hover("a");
  rail.close();
  calls.length = 0;
  rail.hover("a");
  assert.deepEqual(calls, ["hover:a"]);
});

test("after a card closes itself, hovering the same station shows its hover card again", () => {
  // Escape, its close button or an action removes the card; RailCards is not told.
  const { rail, calls, cards } = setup();
  rail.open("a");
  rail.hover("a");
  cards[0].remove();
  calls.length = 0;
  rail.hover("a");
  assert.deepEqual(calls, ["hover:a"]);
});
