"""The connector's summary names the barriers on a Cargo or Tandem route (mcp/routemaker_mcp.py
`barriers_said`), as the page's line does (frontend/src/lib/barriers.ts; the owner, 2026-11-12:
"Exclude; line on Cargo+Tandem")."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if "routemaker_mcp" in sys.modules:
    mcp = sys.modules["routemaker_mcp"]
else:
    _spec = importlib.util.spec_from_file_location(
        "routemaker_mcp", Path(__file__).resolve().parents[1] / "mcp" / "routemaker_mcp.py"
    )
    mcp = importlib.util.module_from_spec(_spec)
    sys.modules["routemaker_mcp"] = mcp
    _spec.loader.exec_module(mcp)


def item(word: str, impassable: bool = False, mapped: bool = True) -> dict:
    return {"word": word, "impassable": impassable, "width_mapped": mapped}


def answer(preset: str, items: list, data: bool = True) -> dict:
    return {"preset": preset, "barriers": {"data": data, "items": items}}


def test_only_cargo_and_tandem() -> None:
    assert mcp.barriers_said(answer("default", [item("gate")])) is None
    assert mcp.barriers_said(answer("tandem", [item("gate")])) == "gate"


def test_the_list_and_unmapped_widths() -> None:
    said = mcp.barriers_said(
        answer(
            "cargo", [item("gate"), item("bollard", mapped=False), item("bollard", mapped=False)]
        )
    )
    assert said == "gate, bollard x2 (width not mapped)"


def test_an_impassable_barrier_left_on_the_route() -> None:
    body = answer("cargo", [item("gate"), item("stile", impassable=True)])
    plain = "stile on this route; a cargo bike or tandem may not get through"
    assert mcp.barriers_said(body) == plain
    body["barrier_round"] = {"limited": "no_way_round"}
    assert mcp.barriers_said(body) == "no way round found: " + plain
    body["barrier_round"] = {"limited": "at_stop"}
    assert mcp.barriers_said(body) == (
        "stile by the start, a stop or the end; a cargo bike or tandem may not get through"
    )


def test_nothing_without_a_barrier_list_or_barriers() -> None:
    assert mcp.barriers_said(answer("cargo", [item("stile", True)], data=False)) is None
    assert mcp.barriers_said(answer("cargo", [])) is None
    assert mcp.barriers_said({"preset": "cargo"}) is None
