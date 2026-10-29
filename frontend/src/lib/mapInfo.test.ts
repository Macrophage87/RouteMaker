// The map's info panel (Stephen 2026-10-19): Plan's how-to and the documentation's short version, behind the "i".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DOCS_LINKS, helpExpanded, infoLines, mapInfo, wrapCredits } from "./mapInfo.ts";

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("Help on a phone: where to start and what the colors mean, in a finger's words (P8)", () => {
  const phone = mapInfo(true);
  assert.ok(phone.startsWith("<p><strong>Where to?</strong> Search or tap a chip, then Start ride.</p>"));
  assert.match(phone, /<p>Line colors: green calm <span aria-hidden="true">→<\/span><span class="visually-hidden">to<\/span> red busy\.<\/p>/);
  assert.doesNotMatch(phone, /click/i, "no click on a phone");
  // The accessibility mode pointer is kept for a screen reader, not shown.
  assert.match(phone, /<p class="visually-hidden">For keyboard or screen reader use, turn on accessibility mode \(the first button on the page, or in Settings\)\.<\/p>/);
  // The long text is in the documentation now, not here.
  assert.doesNotMatch(phone, /LTS 1|planned-work permits|<li>/);
});

test("a computer keeps its click, and shows the accessibility mode pointer", () => {
  const desk = mapInfo(false);
  assert.ok(desk.startsWith(`<p><strong>Where to?</strong> ${infoLines(false).start}</p>`));
  assert.match(infoLines(false).start, /click the map/);
  assert.match(desk, /<p>For keyboard or screen reader use, turn on accessibility mode \(the first button on the page, or in Settings\)\.<\/p>/);
  for (const html of [desk, mapInfo(true)]) {
    // Two sentences at most in any paragraph shown (P8: no walls of text).
    for (const para of html.split("</p>")) assert.ok((para.replace(/<[^>]+>/g, "").match(/[.?!](\s|$)/g) ?? []).length <= 2, para);
  }
});

test("then a link to each documentation page", () => {
  assert.deepEqual(DOCS_LINKS.map((l) => l.href), ["/about/using.html", "/about/how-it-works.html", "/about/ride-types.html", "/about/stress.html", "/about/routing.html", "/about/architecture.html"]);
  for (const touch of [true, false]) {
    for (const link of DOCS_LINKS) assert.ok(mapInfo(touch).includes(`<a href="${link.href}">${link.text}</a>`), link.href);
  }
});

test("plain markup: no handlers, no styles", () => {
  for (const html of [mapInfo(true), mapInfo(false)]) {
    const tags = [...html.matchAll(/<([a-z]+)/g)].map((m) => m[1]);
    assert.ok(tags.every((t) => ["p", "strong", "span", "a"].includes(t)), tags.join());
    assert.doesNotMatch(html, /\son[a-z]+=|style=/);
  }
});

// A stand-in for the few DOM parts wrapCredits uses: elements with a class, children and a parent.
class Node {
  className = "";
  innerHTML = "";
  children: Node[] = [];
  parent: Node | null = null;
  attributes: Record<string, string> = {};
  constructor(className = "") {
    this.className = className;
  }
  get classList() {
    return { contains: (name: string) => this.className.split(" ").includes(name) };
  }
  setAttribute(name: string, value: string) {
    this.attributes[name] = value;
  }
  querySelector(selector: string): Node | null {
    for (const child of this.children) {
      if (selector === `.${child.className}`) return child;
      const deeper = child.querySelector(selector);
      if (deeper) return deeper;
    }
    return null;
  }
  append(...nodes: Node[]) {
    for (const node of nodes) {
      node.parent = this;
      this.children.push(node);
    }
  }
  replaceWith(node: Node) {
    const siblings = this.parent!.children;
    siblings[siblings.indexOf(this)] = node;
    node.parent = this.parent;
  }
}

test("the info panel goes over MapLibre's credits in one body, once, and the credits' element is kept", () => {
  const control = new Node("maplibregl-ctrl-attrib");
  const button = new Node("maplibregl-ctrl-attrib-button");
  const inner = new Node("maplibregl-ctrl-attrib-inner");
  control.append(button, inner);
  const doc = { createElement: () => new Node() as unknown as HTMLDivElement };
  assert.equal(wrapCredits(control as unknown as HTMLElement, doc, true), true);
  assert.deepEqual(control.children.map((c) => c.className), ["maplibregl-ctrl-attrib-button", "map-info-body"]);
  const body = control.children[1];
  assert.deepEqual(body.children.map((c) => c.className), ["map-info", "maplibregl-ctrl-attrib-inner"]);
  assert.equal(body.children[0].innerHTML, mapInfo(true), "a phone's words where the pointer is a finger");
  assert.equal(body.children[1], inner, "the same element MapLibre writes the credits into");
  assert.equal((button as unknown as { textContent: string }).textContent, "Help", "the i says what it opens");
  assert.equal(button.attributes["aria-expanded"], "false", "collapsed at the start, and says so");
  control.className = "maplibregl-ctrl-attrib maplibregl-compact maplibregl-compact-show";
  helpExpanded(control, button);
  assert.equal(button.attributes["aria-expanded"], "true");
  assert.equal(wrapCredits(control as unknown as HTMLElement, doc), false, "not twice");
  assert.equal(wrapCredits(null, doc), false);
});

test("the map wraps its credits after collapsing them, behind an i named for the panel", () => {
  const view = src("../MapView.tsx");
  assert.match(view, /customAttribution: MAP_ATTRIBUTION \}\), "bottom-right"\);\s*const credits = [^;]+;\s*collapseCredits\(credits\);[\s\S]{0,300}wrapCredits\(credits\);/);
  assert.match(view, /"AttributionControl\.ToggleAttribution": t\("Help: map info and credits"\)/);
  // A ride starts with the panel closed, so it never covers the rider's dot.
  assert.match(view, /if \(!props\.rideLabels\) return;\s*collapseCredits\(container\.current\?\.querySelector<HTMLElement>\("\.maplibregl-ctrl-attrib"\) \?\? null\);/);
  // A documentation link keeps the plan for the page's "Back to the map", as StressPageLink does.
  assert.match(view, /a\[href\^="\/about\/"\][\s\S]{0,120}rememberPlanForPage\(tabSession\(\), window\.location\.hash\)/);
});

test("Plan shows the how-to in accessibility mode only; otherwise a screen reader still hears it there (Stephen 2026-10-20: simpler)", () => {
  const planner = src("../app/Planner.tsx");
  assert.match(planner, /<p className=\{accessMode \? "hint" : "visually-hidden"\}>\{searchLede\(loopVias, accessMode\)\}<\/p>/);
  assert.match(planner, /<p className=\{accessMode \? "hint" : "visually-hidden"\}>\{loneStartHint\(preset, loopVias, accessMode\)\}<\/p>/);
  // The loop's hint is the box's description, never shown.
  assert.match(planner, /<p className="visually-hidden loop-hint" id=\{loopHintId\}>/);
});
