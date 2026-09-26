"""The self-hosted base map: what fetches it, and how the edge serves it.

PLAN.md "Base map": a PMTiles extract of the Protomaps daily build over the
coverage box, served by Caddy with HTTP range requests, glyphs and sprites
self-hosted beside it, and all three served only to requests whose `Origin` or
`Referer` is this site. The shared API contract puts them at
`/basemap/region.pmtiles`, `/basemap/fonts/...` and `/basemap/sprites/...`.

What is asserted here is read from the files: the mount, the directives on
the route, and the pins in the fetch script. What the route does when run is
in tests/test_basemap_edge.py, and what the fetch script does when run is in
tests/test_fetch_basemap.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from django.conf import settings

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
CADDY_VOLUMES: list[str] = COMPOSE["services"]["caddy"]["volumes"]
CADDYFILE = REPO / "Caddyfile"
CADDY_TEXT = CADDYFILE.read_text() if CADDYFILE.is_file() else ""
FETCH = REPO / "scripts" / "fetch_basemap.sh"
FETCH_TEXT = FETCH.read_text() if FETCH.is_file() else ""

SOURCE = "${DATA_ROOT}/basemap"


def basemap_mount() -> tuple[str, list[str]]:
    """The container path and the options of caddy's basemap mount."""
    for volume in CADDY_VOLUMES:
        host, _, rest = volume.partition(":")
        if host == SOURCE:
            path, _, options = rest.partition(":")
            return path, options.split(",") if options else []
    raise AssertionError(f"the caddy service mounts no {SOURCE}: {CADDY_VOLUMES}")


def code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


def block(opener: str) -> list[str]:
    """The non-comment lines inside the block whose opening line is `opener {`."""
    lines = code_lines(CADDY_TEXT)
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == f"{opener} {{"),
        None,
    )
    assert start is not None, f"the Caddyfile has no `{opener} {{` block"
    depth, body = 0, []
    for line in lines[start:]:
        depth += line.count("{") - line.count("}")
        body.append(line.strip())
        if depth == 0:
            break
    return body[1:-1]


def directives(body: list[str], name: str) -> list[str]:
    return [line.partition(" ")[2].strip() for line in body if line.partition(" ")[0] == name]


def matcher(body: list[str], name: str) -> str:
    """The definition of named matcher `@name` inside a block."""
    for line in body:
        keyword, _, rest = line.partition(" ")
        if keyword == f"@{name}":
            return rest
    raise AssertionError(f"no matcher @{name} is defined in {body}")


def basemap_block() -> list[str]:
    """The /basemap/* route. A function, so a missing block fails the tests
    that are about it rather than erroring the module out at collection."""
    return block("handle_path /basemap/*")


# --- compose ------------------------------------------------------------------


def test_caddy_mounts_the_basemap_directory_read_only() -> None:
    """The edge serves the files and has no business changing them; the fetch
    script and, later, the monthly refresh are the writers."""
    _, options = basemap_mount()
    assert "ro" in options, f"{SOURCE} is mounted into caddy writable: {CADDY_VOLUMES}"


# --- the Caddyfile route --------------------------------------------------------


def test_the_route_serves_the_mounted_directory() -> None:
    path, _ = basemap_mount()
    assert f"* {path}" in directives(basemap_block(), "root"), (
        f"/basemap/* is not rooted at caddy's mount of {SOURCE} ({path}): {basemap_block()}"
    )
    assert directives(basemap_block(), "file_server") == [""], (
        f"/basemap/* needs exactly one plain file_server - the one that answers "
        f"Range with 206 - and no browse: {basemap_block()}"
    )


def test_nothing_re_encodes_the_bytes_a_range_names() -> None:
    """A PMTiles reader asks for byte ranges of the file as stored and decodes
    the directory it gets back at those offsets; a compressing encoder on this
    path changes what the offsets mean. Neither the site nor the route may
    carry one."""
    assert not directives(basemap_block(), "encode"), (
        f"/basemap/* encodes its responses: {basemap_block()}"
    )
    site_level = [line for line in code_lines(CADDY_TEXT) if line.strip().startswith("encode")]
    assert not site_level, f"the Caddyfile encodes responses: {site_level}"


def test_only_the_three_contract_paths_are_served() -> None:
    """The directory also holds the fetch script's stamps and, mid-refresh, its
    work directory. The contract names three things, and anything else under
    /basemap/ is refused before the file server sees it."""
    unlisted = [
        rest
        for rest in directives(basemap_block(), "respond")
        if rest.startswith("@") and rest.split()[1:] == ["404"]
    ]
    assert len(unlisted) == 1, f"no single 404 for paths outside the contract: {basemap_block()}"
    definition = matcher(basemap_block(), unlisted[0].split()[0][1:])
    assert definition.startswith("not path "), definition
    assert set(definition.removeprefix("not path ").split()) == {
        "/region.pmtiles",
        "/fonts/*",
        "/sprites/*",
    }, definition


def test_a_request_from_another_origin_is_refused() -> None:
    """PLAN: served only to requests whose Origin or Referer matches the app
    host. The match is against the request's own scheme and host, so the one
    file serves the `:80` posture and a hostname alike without naming either."""
    refusals = [
        rest
        for rest in directives(basemap_block(), "respond")
        if rest.startswith("@") and rest.split()[1:] == ["403"]
    ]
    assert len(refusals) == 1, f"no single 403 for foreign requests: {basemap_block()}"
    definition = matcher(basemap_block(), refusals[0].split()[0][1:])
    assert definition.startswith("not expression"), (
        f"the refusal must be the negation of an allow-rule, so a request carrying "
        f"neither header is refused too: {definition}"
    )
    for needle in ("{header.Origin}", "{header.Referer}", "{scheme}", "{hostport}"):
        assert needle in definition, f"the allow-rule does not read {needle}: {definition}"
    # The Referer is compared as a prefix that ends in "/", or
    # http://site.evil.example/ would pass as http://site.
    assert re.search(r'\{hostport\}\s*\+\s*"/"', definition), definition


# --- the fetch script -----------------------------------------------------------


def pinned(name: str) -> str:
    found = re.search(rf'^{name}="?([^"\n]*)"?$', FETCH_TEXT, re.MULTILINE)
    assert found, f"scripts/fetch_basemap.sh pins no {name}"
    return found.group(1)


def test_the_extract_covers_the_coverage_box() -> None:
    west, south, east, north = (float(v) for v in pinned("BBOX").split(","))
    assert (west, south, east, north) == tuple(settings.COVERAGE_BBOX), (
        f"the basemap is extracted over {pinned('BBOX')}, the routing region is "
        f"{settings.COVERAGE_BBOX}"
    )


def test_every_download_is_pinned_and_checksummed() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned("PMTILES_VERSION"))
    assert re.fullmatch(r"[0-9a-f]{64}", pinned("PMTILES_SHA256"))
    assert re.fullmatch(r"[0-9a-f]{40}", pinned("ASSETS_COMMIT"))
    assert re.fullmatch(r"[0-9a-f]{64}", pinned("ASSETS_SHA256"))
    assert re.fullmatch(r"20\d{6}", pinned("PROTOMAPS_BUILD"))
