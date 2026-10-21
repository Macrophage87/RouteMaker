// The map's info panel (Stephen 2026-10-19): Plan's how-to and the documentation's short version, behind the "i".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DOCS_LINKS, INFO_POINTS, MAP_INFO, wrapCredits } from "./mapInfo.ts";
import { searchLede } from "./sidebar.ts";

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("the info panel leads with Plan's how-to, the accessibility mode pointer included", () => {
  assert.ok(MAP_INFO.startsWith(`<p><strong>Plan a route.</strong> ${searchLede(false)}</p>`));
  assert.match(MAP_INFO, /turn on accessibility mode \(the first button on the page, or in Settings\)/);
});

test("then the documentation's short version, one line each, and a link to each page", () => {
  assert.equal(INFO_POINTS.length, 4);
  for (const point of INFO_POINTS) assert.ok(MAP_INFO.includes(`<li>${point}</li>`), point);
  assert.deepEqual(DOCS_LINKS.map((l) => l.href), ["/about/using.html", "/about/how-it-works.html", "/about/ride-types.html", "/about/stress.html", "/about/routing.html", "/about/architecture.html"]);
  for (const link of DOCS_LINKS) assert.ok(MAP_INFO.includes(`<a href="${link.href}">${link.text}</a>`), link.href);
});

test("plain markup: no handlers, no styles", () => {
  const tags = [...MAP_INFO.matchAll(/<([a-z]+)/g)].map((m) => m[1]);
  assert.ok(tags.every((t) => ["p", "strong", "ul", "li", "a"].includes(t)), tags.join());
  assert.doesNotMatch(MAP_INFO, /\son[a-z]+=|style=/);
});

// A stand-in for the few DOM parts wrapCredits uses: elements with a class, children and a parent.
class Node {
  className = "";
  innerHTML = "";
  children: Node[] = [];
  parent: Node | null = null;
  constructor(className = "") {
    this.className = className;
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
  assert.equal(wrapCredits(control as unknown as HTMLElement, doc), true);
  assert.deepEqual(control.children.map((c) => c.className), ["maplibregl-ctrl-attrib-button", "map-info-body"]);
  const body = control.children[1];
  assert.deepEqual(body.children.map((c) => c.className), ["map-info", "maplibregl-ctrl-attrib-inner"]);
  assert.equal(body.children[0].innerHTML, MAP_INFO);
  assert.equal(body.children[1], inner, "the same element MapLibre writes the credits into");
  assert.equal((button as unknown as { textContent: string }).textContent, "Help", "the i says what it opens");
  assert.equal(wrapCredits(control as unknown as HTMLElement, doc), false, "not twice");
  assert.equal(wrapCredits(null, doc), false);
});

test("the map wraps its credits after collapsing them, behind an i named for the panel", () => {
  const view = src("../MapView.tsx");
  assert.match(view, /customAttribution: MAP_ATTRIBUTION \}\), "bottom-right"\);\s*const credits = [^;]+;\s*collapseCredits\(credits\);[\s\S]{0,300}wrapCredits\(credits\);/);
  assert.match(view, /"AttributionControl\.ToggleAttribution": "Help: map info and credits"/);
  // A documentation link keeps the plan for the page's "Back to the map", as StressPageLink does.
  assert.match(view, /a\[href\^="\/about\/"\][\s\S]{0,120}rememberPlanForPage\(tabSession\(\), window\.location\.hash\)/);
});

test("Plan shows the how-to in accessibility mode and for a loop; otherwise a screen reader still hears it there", () => {
  assert.match(src("../app/Planner.tsx"), /<p className=\{accessMode \|\| loopVias \? "hint" : "visually-hidden"\}>\{searchLede\(loopVias, accessMode\)\}<\/p>/);
});
