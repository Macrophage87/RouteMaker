"""The rider-facing documentation under frontend/public/about/ (the owner, 2026-10-19: "a full
set of documentation that can be linked to the website", "as many graphs and diagrams as
possible with links and citations throughout").

Static pages served under the app's CSP (Caddyfile @frontend), so: no scripts and nothing
loaded from another site; every diagram an image with a title and a description a screen
reader reads; every link inside the set and every citation resolves; nothing that names a
server.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ABOUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "about"
DOCS = (
    "how-it-works",
    "using",
    "accessibility",
    "routing",
    "ride-types",
    "mass-ride",
    "trails",
    "architecture",
    "assistants",
    "acknowledgements",
)
SET = (*DOCS, "stress")


def read(name: str) -> str:
    return (ABOUT / f"{name}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SET)
def test_each_page_is_a_plain_static_page_the_csp_allows(name: str) -> None:
    page = read(name)
    assert page.startswith('<!doctype html>\n<html lang="en">'), name
    assert len(re.findall(r"<h1>", page)) == 1
    assert "<script" not in page.lower()
    # Nothing from another site: no external stylesheet, image, frame or font.
    assert not re.search(r"<(link|img|iframe|source)\b[^>]*(href|src)=\"https?:", page), name
    assert not re.search(r"url\(\s*['\"]?https?:", page), name
    assert '<a class="skip" href="#main">' in page and 'id="main"' in page


@pytest.mark.parametrize("name", SET)
def test_each_page_names_the_whole_set_and_marks_itself(name: str) -> None:
    page = read(name)
    nav = re.search(
        r'<nav class="docs" aria-label="RouteMaker documentation">(.*?)</nav>', page, re.S
    )
    assert nav, name
    hrefs = re.findall(r'href="/about/([a-z-]+)\.html"', nav.group(1))
    assert sorted(hrefs) == sorted(SET), hrefs
    assert re.findall(r'href="/about/([a-z-]+)\.html" aria-current="page"', nav.group(1)) == [name]
    # Both "Back to the map" links go to a bare "/", where the app reads the kept plan.
    assert re.findall(r"<a [^>]*>Back to the map</a>", page) == [
        '<a class="back" href="/">Back to the map</a>',
        '<a href="/">Back to the map</a>',
    ]


@pytest.mark.parametrize("name", SET)
def test_every_link_resolves_and_leaves_the_site_only_over_https(name: str) -> None:
    page = read(name)
    ids = set(re.findall(r'\bid="([^"]+)"', page))
    for href in re.findall(r'href="([^"]+)"', page):
        if href.startswith("#"):
            assert href[1:] in ids, f"{name}: {href}"
        elif href.startswith("/about/"):
            path, _, frag = href.partition("#")
            target = ABOUT / Path(path).name
            assert target.is_file(), href
            if frag:
                assert f'id="{frag}"' in target.read_text(encoding="utf-8"), href
        elif href.startswith("/"):
            assert href in ("/", "/favicon.svg", "/licenses.txt", "/privacy"), href
        else:
            assert href.startswith("https://"), f"{name}: {href}"


@pytest.mark.parametrize("name", DOCS)
def test_every_diagram_is_an_image_with_a_title_and_a_description(name: str) -> None:
    page = read(name)
    svgs = re.findall(r"<svg\b([^>]*)>(.*?)</svg>", page, re.S)
    # The overview has one picture of the whole and links to the detail; the credits have none.
    if name not in ("acknowledgements", "how-it-works"):
        assert len(svgs) >= 4, f"{name}: diagrams"
    for attrs, inner in svgs:
        assert 'role="img"' in attrs and 'focusable="false"' in attrs, attrs
        t_id, d_id = re.search(r'aria-labelledby="(\S+) (\S+)"', attrs).groups()
        title = re.search(rf'<title id="{t_id}">([^<]+)</title>', inner)
        desc = re.search(rf'<desc id="{d_id}">([^<]+)</desc>', inner)
        assert title and desc, attrs
        # The description carries the content: a sentence or more, not a label.
        assert len(desc.group(1)) > 80, desc.group(1)
    # Each diagram sits in a scrollable figure a keyboard can reach; a phone layout, where there is
    # one, fits the width and needs no scrolling.
    narrow = page.count('<div class="fig-narrow">')
    assert page.count('<div class="fig-scroll') + narrow == len(svgs)
    assert page.count('tabindex="0" role="group" aria-label="Diagram') == len(svgs) - narrow


CITED = (
    "how-it-works",
    "using",
    "accessibility",
    "routing",
    "ride-types",
    "mass-ride",
    "trails",
    "architecture",
    "assistants",
    "stress",
)


@pytest.mark.parametrize("name", CITED)
def test_every_citation_has_its_source_and_every_source_is_cited(name: str) -> None:
    page = read(name)
    cited = {int(n) for n in re.findall(r'<a href="#ref-(\d+)"', page)}
    listed = [int(n) for n in re.findall(r'<li id="ref-(\d+)">', page)]
    assert listed == list(range(1, len(listed) + 1)) and listed, name
    assert cited == set(listed), (cited, listed)


def test_the_acknowledgements_credit_every_source_the_map_credits() -> None:
    page = read("acknowledgements")
    map_credits = json.loads((ABOUT.parent.parent / "src" / "lib" / "credits.json").read_text())
    names = (
        "OpenStreetMap",
        "Protomaps",
        "Open Data DC",
        "Virginia DOT",
        "Open Baltimore",
        "City of Alexandria",
        "Montgomery County Planning",
        "Maryland DOT State Highway",
        "USGS",
        "Census",
        "Photon",
        "Capital Bikeshare",
        "TOPS",
        "Metropolitan Police",
        "DDOT project traffic advisories",
        "AlertDC",
        "National Park Service",
    )
    # One name per map credit, in the same order: a new credit fails here until it is named.
    assert len(names) == len(map_credits)
    for credit in names:
        assert credit in page, credit


@pytest.mark.parametrize("name", SET)
def test_nothing_names_a_server(name: str) -> None:
    page = read(name)
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", page), "an IP address"
    named = r"internal-|home server|\.env\b|amazonaws\.com/(?!3d)|s3://|href=\"/(admin|review)"
    assert not re.search(named, page, re.I)
