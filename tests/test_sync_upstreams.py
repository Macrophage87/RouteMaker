"""`manage.py sync_upstreams`: the settings rows follow the tile links.

The beta moves its links itself (`scripts/beta/receive-data.sh files`) and never swaps, so
nothing there wrote `valhalla_upstream`; with no `mtb` or `offroad` row the API planned
Mountain Bike, Gravel and Mountain Goat on the standard graph with both routers up.
"""

from __future__ import annotations

import os
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from django.core.management import call_command

from core import routing
from core.models import ValhallaUpstream
from pipeline import promotion
from pipeline.variants import Variant

pytestmark = pytest.mark.django_db

UPSTREAMS = {v.value: f"http://valhalla-{v.value}:8002" for v in Variant}


def _link(tiles: Path, variant: str, current: str, previous: str | None = None) -> None:
    folder = tiles / variant
    folder.mkdir(parents=True, exist_ok=True)
    for name, target in (("current", current), ("previous", previous)):
        link = folder / name
        if link.is_symlink():
            link.unlink()
        if target is not None:
            (folder / target).mkdir(exist_ok=True)
            os.symlink(target, link)


def _rows() -> dict[str, tuple[str, str, str]]:
    return {
        r.variant: (r.url, r.build_id, r.previous_build_id) for r in ValhallaUpstream.objects.all()
    }


def test_the_rows_are_written_from_the_links(tmp_path) -> None:
    _link(tmp_path, "standard", "B2", "B1")
    _link(tmp_path, "mtb", "B2")
    (tmp_path / "offroad").mkdir()  # no link: what prepare_data_root leaves

    promotion.sync_upstreams(tmp_path, UPSTREAMS)

    assert _rows() == {
        "standard": (UPSTREAMS["standard"], "B2", "B1"),
        "mtb": (UPSTREAMS["mtb"], "B2", ""),
    }


def test_stale_rows_are_updated_and_a_variant_without_current_loses_its_row(tmp_path) -> None:
    # The beta's rows as found on 2026-10-28: home's first load, one build for every variant.
    for variant in ("standard", "no-trail", "ebike", "weekend"):
        ValhallaUpstream.objects.create(
            variant=variant, url="old", build_id="20261003T142804Z", previous_build_id="X"
        )
    for variant in ("standard", "no-trail", "ebike", "offroad", "mtb"):
        _link(tmp_path, variant, "20261028T002217Z", "20261025T224412Z")

    promotion.sync_upstreams(tmp_path, UPSTREAMS)

    rows = _rows()
    assert "weekend" not in rows
    assert set(rows) == {"standard", "no-trail", "ebike", "offroad", "mtb"}
    for variant, row in rows.items():
        assert row == (UPSTREAMS[variant], "20261028T002217Z", "20261025T224412Z")


def test_a_second_run_writes_nothing(tmp_path) -> None:
    _link(tmp_path, "mtb", "B2", "B1")
    promotion.sync_upstreams(tmp_path, UPSTREAMS)
    stamp = ValhallaUpstream.objects.get(variant="mtb").updated_at

    promotion.sync_upstreams(tmp_path, UPSTREAMS)

    assert ValhallaUpstream.objects.get(variant="mtb").updated_at == stamp


def test_one_failing_write_leaves_every_row_as_it_was(tmp_path) -> None:
    ValhallaUpstream.objects.create(
        variant="standard", url="old", build_id="A", previous_build_id=""
    )
    for variant in ("standard", "mtb", "offroad"):
        _link(tmp_path, variant, "B2", "B1")
    before = _rows()
    real_create = ValhallaUpstream.objects.create

    def create(**kwargs):
        if kwargs["variant"] == "offroad":
            raise RuntimeError("the database went away")
        return real_create(**kwargs)

    with mock.patch.object(ValhallaUpstream.objects, "create", side_effect=create):
        with pytest.raises(RuntimeError):
            promotion.sync_upstreams(tmp_path, UPSTREAMS)

    assert _rows() == before


def test_mountain_bike_is_served_once_its_row_is_synced(
    tmp_path, settings, weekend_rows_read
) -> None:
    settings.TILES_DIR = tmp_path
    _link(tmp_path, "mtb", "B2")
    assert not routing._is_promoted(Variant.MTB.value)

    out = StringIO()
    call_command("sync_upstreams", stdout=out)

    assert routing._is_promoted(Variant.MTB.value)
    assert "mtb: B2 (previous none), was no row" in out.getvalue()
    assert "offroad: no row" in out.getvalue()
