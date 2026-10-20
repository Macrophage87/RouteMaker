"""The 311 log (core.report_log; Stephen, 2026-10-20): the account's copy (GET and POST
/api/me/report311-log), its checks, and which 311 website takes a point (GET
/api/report311/where): DC from its own boundary, elsewhere the county or city Photon names.
"""

from __future__ import annotations

import pytest
from test_accounts import addr, send, signed_in

from core import geocode, report_log
from core.models import Report311Log

db = pytest.mark.django_db(transaction=True)


def entry(**changes) -> dict:
    return {
        "id": "mabc123-1a2b3c4d",
        "kind": "pothole",
        "lat": 38.9126,
        "lon": -77.00709,
        "place": "on R Street Northeast",
        "note": "",
        "at": "2026-10-20T16:00:00.000Z",
        "changed": "2026-10-20T16:00:00.000Z",
        "where": "dc",
        "reported": None,
        **changes,
    }


class TestLogChecks:
    def test_a_good_log(self) -> None:
        assert report_log.log_problem([entry(), entry(id="b", where=None)]) is None
        assert report_log.log_problem([]) is None

    @pytest.mark.parametrize(
        "bad",
        [
            entry(id="no spaces"),
            entry(kind="graffiti"),
            entry(lat="38.9"),
            entry(lat=float("nan")),
            entry(lon=-200),
            entry(place="x" * 201),
            entry(note="x" * 501),
            entry(at="yesterday"),
            entry(where="atlantis"),
            entry(reported="soon"),
            {**entry(), "secret": 1},
        ],
    )
    def test_a_bad_entry_is_refused(self, bad) -> None:
        assert report_log.log_problem([bad])

    def test_the_size_is_counted_in_utf8_bytes(self) -> None:
        # A note in another script counts its bytes, not the six of an escaped \\u for each.
        notes = [entry(id=f"e{n}", note="é" * 500) for n in range(100)]
        assert report_log.log_bytes(notes) < report_log.LOG_MAX_BYTES
        assert report_log.log_problem(notes) is None

    def test_the_cap_drops_the_oldest_archived_first(self) -> None:
        old = entry(id="old", at="2026-10-01T00:00:00.000Z", reported="2026-10-02T00:00:00.000Z")
        new = [
            entry(id=f"e{n}", at=f"2026-10-20T{n // 60:02d}:{n % 60:02d}:00.000Z")
            for n in range(report_log.ENTRIES_MAX)
        ]
        kept = report_log.cap_log([*new, old])
        assert len(kept) == report_log.ENTRIES_MAX and "old" not in {e["id"] for e in kept}

    def test_the_whole_log(self) -> None:
        assert report_log.log_problem({"entries": []})
        assert report_log.log_problem([entry(), entry()]) == "Two entries have the same id."
        many = [entry(id=f"e{n}") for n in range(report_log.ENTRIES_MAX + 1)]
        assert "at most" in report_log.log_problem(many)


class TestWhichSite:
    @pytest.mark.parametrize(
        ("state", "county", "city", "expected"),
        [
            ("District of Columbia", "", "Washington", "dc"),
            ("Maryland", "Montgomery County", "Bethesda", "moco"),
            ("Maryland", "Prince George’s County", "", "pg"),
            ("Maryland", "Baltimore County", "Towson", "baltimore-county"),
            ("Maryland", "Baltimore", "Baltimore", "baltimore-city"),
            ("Maryland", "", "Baltimore", "baltimore-city"),
            ("Maryland", "Calvert County", "", "md"),
            ("Virginia", "Arlington County", "", "arlington"),
            ("Virginia", "Fairfax County", "Annandale", "va"),
            ("Virginia", "City of Fairfax", "Fairfax", "fairfax-city"),
            ("Virginia", "Alexandria", "Alexandria", "alexandria"),
            ("Virginia", "Falls Church", "", "falls-church"),
            ("Virginia", "Loudoun County", "Leesburg", "va"),
            ("Virginia", "Manassas Park", "", "manassas-park"),
            ("Pennsylvania", "Adams County", "", None),
        ],
    )
    def test_photon_s_names(self, state, county, city, expected) -> None:
        assert report_log.jurisdiction(state, county, city) == expected

    def test_dc_by_its_own_boundary_without_photon(self, monkeypatch) -> None:
        def no_photon(*_args, **_kwargs):
            raise AssertionError("DC needs no lookup")

        monkeypatch.setattr(geocode, "area", no_photon)
        assert report_log.where(38.9126, -77.00709, lang="en") == "dc"

    def test_elsewhere_from_photon(self, monkeypatch) -> None:
        monkeypatch.setattr(
            geocode,
            "area",
            lambda lat, lon, lang: {"state": "Maryland", "county": "Montgomery County", "city": ""},
        )
        assert report_log.where(38.9851, -77.0957, lang="en") == "moco"
        monkeypatch.setattr(geocode, "area", lambda lat, lon, lang: None)
        assert report_log.where(38.9851, -77.0957, lang="en") is None

    def test_every_site_id_is_one_the_page_knows(self) -> None:
        from pathlib import Path

        page = (
            Path(__file__).resolve().parents[1] / "frontend" / "src" / "lib" / "report311Log.ts"
        ).read_text()
        for site in report_log.JURISDICTION_IDS - {"none"}:
            assert f'"{site}"' in page or f"{site}:" in page, site


@db
class TestWhereEndpoint:
    def test_an_id_and_nothing_kept(self, client, monkeypatch) -> None:
        monkeypatch.setattr(
            geocode,
            "area",
            lambda lat, lon, lang: {"state": "Virginia", "county": "Arlington County", "city": ""},
        )
        r = client.get("/api/report311/where?lat=38.88&lon=-77.1", **addr())
        assert r.status_code == 200 and r.json() == {"where": "arlington"}
        r = client.get("/api/report311/where?lat=38.9126&lon=-77.00709", **addr())
        assert r.json() == {"where": "dc"}

    def test_outside_the_map_is_refused(self, client) -> None:
        assert client.get("/api/report311/where?lat=40.7&lon=-74.0", **addr()).status_code == 400

    def test_photon_down(self, client, monkeypatch) -> None:
        def down(*_args, **_kwargs):
            raise geocode.Unavailable("down")

        monkeypatch.setattr(geocode, "area", down)
        r = client.get("/api/report311/where?lat=38.98&lon=-77.09", **addr())
        assert r.status_code == 502


@db
class TestAccountLog:
    def test_signed_out_is_refused(self, client) -> None:
        assert client.get("/api/me/report311-log", **addr()).status_code == 401

    def test_saved_and_read_back(self) -> None:
        client, user, csrf = signed_in()
        assert client.get("/api/me/report311-log", **addr()).json()["entries"] is None
        r = send(client, "post", "/api/me/report311-log", {"entries": [entry()]}, csrf)
        assert r.status_code == 200
        assert client.get("/api/me/report311-log", **addr()).json()["entries"] == [entry()]
        assert Report311Log.objects.get(user=user).entries == [entry()]

    def test_a_write_needs_the_csrf_token(self) -> None:
        client, user, _csrf = signed_in()
        r = send(client, "post", "/api/me/report311-log", {"entries": [entry()]}, None)
        assert r.status_code == 403
        assert not Report311Log.objects.filter(user=user).exists()

    def test_a_bad_log_is_refused(self) -> None:
        client, user, csrf = signed_in()
        r = send(client, "post", "/api/me/report311-log", {"entries": [entry(kind="x")]}, csrf)
        assert r.status_code == 400 and r.json()["error"]
        assert not Report311Log.objects.filter(user=user).exists()

    def test_another_account_sees_only_its_own(self) -> None:
        owner, _u, csrf = signed_in()
        send(owner, "post", "/api/me/report311-log", {"entries": [entry()]}, csrf)
        other, _o, _c = signed_in()
        assert other.get("/api/me/report311-log", **addr()).json()["entries"] is None

    def test_each_account_has_its_own_owner_tag(self) -> None:
        # The page keeps the tag with its copy, and never merges one account's copy into another's.
        one, _u, _c = signed_in()
        two, _o, _c2 = signed_in()
        a = one.get("/api/me/report311-log", **addr()).json()["owner"]
        assert a == one.get("/api/me/report311-log", **addr()).json()["owner"]
        assert a != two.get("/api/me/report311-log", **addr()).json()["owner"]
        assert len(a) == 24

    def test_a_save_merges_by_entry_so_an_old_copy_drops_nothing(self) -> None:
        client, user, csrf = signed_in()
        pothole = entry(id="pothole-1")
        five, six = "2026-10-20T17:00:00.000Z", "2026-10-20T18:00:00.000Z"
        tree = entry(id="tree-1", kind="tree", at=five, changed=five)
        send(client, "post", "/api/me/report311-log", {"entries": [pothole]}, csrf)
        # The phone logs a tree; then a desktop with only the pothole checks the pothole off.
        send(client, "post", "/api/me/report311-log", {"entries": [tree, pothole]}, csrf)
        done = entry(id="pothole-1", reported=six, changed=six)
        r = send(client, "post", "/api/me/report311-log", {"entries": [done]}, csrf)
        assert r.status_code == 200
        kept = Report311Log.objects.get(user=user).entries
        assert [e["id"] for e in kept] == ["tree-1", "pothole-1"]
        assert kept[1]["reported"] == six
        assert r.json()["entries"] == kept
        # An older change does not undo a newer one.
        send(client, "post", "/api/me/report311-log", {"entries": [pothole]}, csrf)
        assert Report311Log.objects.get(user=user).entries[1]["reported"] == six

    def test_it_goes_with_the_account(self) -> None:
        client, user, csrf = signed_in()
        send(client, "post", "/api/me/report311-log", {"entries": [entry()]}, csrf)
        user.is_deleted = True
        user.save()
        assert not Report311Log.objects.filter(user=user).exists()
