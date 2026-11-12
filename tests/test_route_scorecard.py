"""The route scorecard's scoring, overlap, checks and comparison (routemaker.scorecard), and
the trip list's rules: public landmarks, well-formed, inside the map."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from routemaker import scorecard

ROOT = Path(__file__).resolve().parent.parent
TRIPS = ROOT / "fixtures" / "scorecard" / "trips.json"
MI = scorecard.METRES_PER_MILE


def line_east(lon0: float, lat: float, metres: float, step: float = 50.0) -> list[list[float]]:
    """A straight line due east, as [lon, lat] pairs."""
    k = 111_320.0 * 0.7771  # cos(38.9 degrees)
    n = int(metres / step)
    return [[lon0 + i * step / k, lat] for i in range(n + 1)]


def answer(**over) -> dict:
    base = {
        "distance_m": 2 * MI,
        "duration_s": 600.0,
        "junction_delay_s": 90.0,
        "geometry": {"type": "LineString", "coordinates": line_east(-77.0, 38.9, 2 * MI)},
        "stress_m": {
            "1": 1.5 * MI,
            "2": 0.25 * MI,
            "3": 0.2 * MI,
            "4": 0.04 * MI,
            "5": 0.01 * MI,
            "unknown": 0,
        },
        "facility_m": {
            "path": 1.0 * MI,
            "protected": 0,
            "lane": 0.5 * MI,
            "none": 0.5 * MI,
            "unknown": 0,
        },
        "stress_spans": [
            {"from_m": 0, "to_m": 800, "tier": 1, "facility": "path", "unpaved": True},
            {"from_m": 800, "to_m": 3218, "tier": 2, "facility": "lane", "unpaved": False},
        ],
        "intersections": [
            {"severity": "red"},
            {"severity": "orange"},
            {"severity": "orange"},
        ],
        "junctions_debug": [{"control": "signal"}, {"control": "stop"}, {"control": "signal"}],
        "description": [
            {"kind": "stretch", "turn": None},
            {"kind": "stretch", "turn": {"movement": "left"}},
            {"kind": "stretch", "turn": {"movement": "bear_right", "stay": True}},
            {"kind": "junction", "turn": {"movement": "right"}},
            {"kind": "stretch", "turn": {"movement": "straight"}},
            {"kind": "stretch", "turn": {"movement": "right"}},
        ],
        "detour": {"ratio": 1.2},
        "calm_search": None,
        "variant": "standard",
    }
    base.update(over)
    return base


def test_score_reads_every_figure():
    row = scorecard.score(answer())
    assert row["miles"] == pytest.approx(2.0)
    assert row["minutes"] == pytest.approx(10.0)
    # left and right; the "stay" fork, the junction entry and straight do not count.
    assert row["turns"] == 2
    assert row["turns_per_mi"] == pytest.approx(1.0)
    assert (row["red"], row["orange"], row["signals"]) == (1, 2, 2)
    assert row["junction_wait_min"] == pytest.approx(1.5)
    assert row["lts3_mi"] == pytest.approx(0.2)
    assert row["lts4_mi"] == pytest.approx(0.05)  # Avoid counts with LTS 4
    assert row["path_share"] == pytest.approx(0.5)
    assert row["unpaved_mi"] == pytest.approx(800 / MI)
    assert row["detour_ratio"] == pytest.approx(1.2)


def test_missing_parts_are_none_not_zero():
    row = scorecard.score(answer(intersections=None, junctions_debug=None, description=None))
    assert row["red"] is None and row["signals"] is None and row["turns"] is None
    assert row["turns_per_mi"] is None


def test_detour_falls_back_to_the_straight_line():
    body = {"points": [[-77.0, 38.9], [-77.0, 38.9 + 1609.344 / 110_574.0]]}
    row = scorecard.score(answer(detour=None), body)
    assert row["detour_ratio"] == pytest.approx(2.0, rel=0.01)


def test_overlap_same_parallel_and_partial():
    a = line_east(-77.0, 38.9, 2000)
    assert scorecard.overlap(a, a) == pytest.approx(1.0)
    # One street over (about 100 m north) is not the same route.
    b = [[lon, 38.9 + 100 / 110_574.0] for lon, _ in a]
    assert scorecard.overlap(a, b) == pytest.approx(0.0)
    # 15 m over (the other side of a wide road) still is.
    c = [[lon, 38.9 + 15 / 110_574.0] for lon, _ in a]
    assert scorecard.overlap(a, c) == pytest.approx(1.0)
    half = a[: len(a) // 2 + 1]
    assert scorecard.overlap(a, half) == pytest.approx(0.5, abs=0.05)
    assert scorecard.overlap(half, a) == pytest.approx(1.0)
    assert scorecard.overlap(None, a) is None


def test_plans_expand_presets_contrast_and_stability():
    trips = {
        "when": "weekday_rush",
        "contrast_presets": ["default", "fast"],
        "trips": [
            {
                "id": "t",
                "points": [[-77.0, 38.9], [-77.01, 38.91]],
                "presets": ["default", "trailmaxxing"],
                "contrast": True,
                "stability": True,
            },
            {"id": "u", "points": [[-77.0, 38.9], [-77.01, 38.91]], "presets": ["default"]},
        ],
    }
    out = scorecard.plans(trips, extra={"debug_junctions": True}, stress=70)
    keys = [p["key"] for p in out]
    assert keys == [
        "t|default|base",
        "t|trailmaxxing|base",
        "t|fast|base",
        "t|default|moved",
        "u|default|base",
    ]
    moved = out[3]["body"]["points"][0]
    shift = scorecard._haversine(moved, [-77.0, 38.9])
    assert shift == pytest.approx(scorecard.STABILITY_SHIFT_M, rel=0.01)
    assert all(p["body"]["when"] == "weekday_rush" and p["body"]["debug_junctions"] for p in out)
    # --stress moves Default only; the other ride types keep their own start.
    assert {p["preset"] for p in out if "stress" in p["body"]} == {"default"}
    assert all(p["body"]["stress"] == 70 for p in out if p["preset"] == "default")
    assert [
        p["key"] for p in scorecard.plans(trips, contrast=False, stability=False, only=["u"])
    ] == ["u|default|base"]


def _entries():
    return [
        {
            "key": "t|default|base",
            "trip": "t",
            "preset": "default",
            "variant": "base",
            "body": {"points": [[-77.0, 38.9], [-76.97, 38.9]]},
        },
        {
            "key": "t|fast|base",
            "trip": "t",
            "preset": "fast",
            "variant": "base",
            "body": {"points": [[-77.0, 38.9], [-76.97, 38.9]]},
        },
        {
            "key": "t|default|moved",
            "trip": "t",
            "preset": "default",
            "variant": "moved",
            "body": {"points": [[-77.0, 38.9004], [-76.97, 38.9]]},
        },
    ]


def test_run_checks_stability_and_contrast():
    ans = {k: {"status": 200, "body": answer()} for k in ("t|default|base", "t|fast|base")}
    far = line_east(-77.0, 38.9 + 300 / 110_574.0, 2 * MI)
    ans["t|default|moved"] = {"status": 200, "body": answer(geometry={"coordinates": far})}
    run = scorecard.run_of(_entries(), ans, {"label": "x"})
    (stab,) = run["checks"]["stability"]
    assert stab["stable"] is False
    (con,) = run["checks"]["contrast"]
    assert con["same"] is True and (con["a"], con["b"]) == ("default", "fast")


def test_compare_lists_what_a_rider_would_notice_and_nothing_smaller():
    entries = _entries()[:1]
    old = scorecard.run_of(entries, {"t|default|base": {"status": 200, "body": answer()}})
    small = answer(distance_m=2.1 * MI, duration_s=640.0)
    new = scorecard.run_of(entries, {"t|default|base": {"status": 200, "body": small}})
    assert scorecard.compare(old, new)["findings"] == {}

    worse = answer(
        distance_m=2.6 * MI,
        stress_m={"1": 1.0 * MI, "2": 0.6 * MI, "3": 0.6 * MI, "4": 0.04 * MI, "5": 0.01 * MI},
        intersections=[{"severity": "red"}, {"severity": "red"}],
        geometry={"coordinates": line_east(-77.0, 38.9 + 200 / 110_574.0, 2 * MI)},
        calm_search={"limited": "time"},
    )
    new = scorecard.run_of(entries, {"t|default|base": {"status": 200, "body": worse}})
    (lines,) = scorecard.compare(old, new)["findings"].values()
    text = "; ".join(lines)
    for expected in (
        "miles 2.00 -> 2.60",
        "red junctions 1 -> 2",
        "LTS 3 mi 0.20 -> 0.60",
        "calm search limited None -> time",
        "changed corridor",
    ):
        assert expected in text

    failed = scorecard.run_of(entries, {"t|default|base": {"status": 422, "body": {"error": "x"}}})
    (lines,) = scorecard.compare(old, failed)["findings"].values()
    assert lines[0].startswith("no longer plans (422")


def test_report_reads_old_to_new():
    entries = _entries()[:1]
    old = scorecard.run_of(
        entries, {"t|default|base": {"status": 200, "body": answer()}}, {"label": "v0.26.0"}
    )
    new = scorecard.run_of(
        entries,
        {"t|default|base": {"status": 200, "body": answer(distance_m=3 * MI)}},
        {"label": "branch"},
    )
    text = scorecard.report(new, old)
    assert "Compared with: v0.26.0" in text
    assert "2.00 -> 3.00" in text
    assert "our defaults, unmeasured" in text


# --- the trip list ---------------------------------------------------------------------------


def test_trip_list_is_well_formed_and_inside_the_map():
    data = json.loads(TRIPS.read_text())
    trips = data["trips"]
    assert 30 <= len(trips) <= 100
    ids = [t["id"] for t in trips]
    assert len(ids) == len(set(ids))
    settings = {t["setting"] for t in trips}
    assert {"urban", "suburban", "rural", "long"} <= settings
    for t in trips:
        assert t["presets"], t["id"]
        assert len(t["points"]) >= 2, t["id"]
        for lon, lat in t["points"]:
            # The map's box: DC to Baltimore, west to Harpers Ferry.
            assert -78.0 < lon < -76.3 and 38.6 < lat < 39.6, t["id"]
        assert t["from"] and t["to"], t["id"]
    plans = scorecard.plans(data)
    assert 50 <= len(plans) <= 200


def test_trip_list_names_no_homes_or_rides():
    text = json.dumps(json.loads(TRIPS.read_text())["trips"]).lower()
    for word in ("home", "house", "my ", "garmin", "commute"):
        assert word not in text, word


def test_queue_and_collect_round_trip(tmp_path):
    req = tmp_path / "queue" / "req"
    cmd = [sys.executable, str(ROOT / "scripts" / "route_scorecard.py")]
    subprocess.run(
        [
            *cmd,
            "queue",
            "--ref",
            "origin/main",
            "--label",
            "t",
            "--only",
            "mall",
            "--out",
            str(req),
        ],
        check=True,
        capture_output=True,
    )
    requests = sorted(req.glob("scorecard-*.json"))
    assert requests and not list(req.glob("*.plans.json"))  # the manifest stays out of req/
    manifest = tmp_path / "queue" / "t.plans.json"
    plans = json.loads(requests[0].read_text())["plans"]
    for plan in plans:
        # Labels the service accepts: letters, digits, spaces and .:+-
        assert all(c.isalnum() or c in " .:+-" for c in plan["label"])
        assert plan["body"]["debug_junctions"] is True and plan["full"] is True
    res = tmp_path / "queue" / "res"
    res.mkdir()
    (res / requests[0].name).write_text(
        json.dumps(
            {
                "status": "ok",
                "sha": "abc",
                "plans": [{"label": p["label"], "status": 200, "answer": answer()} for p in plans],
            }
        )
    )
    out = tmp_path / "run.json"
    subprocess.run(
        [*cmd, "collect", "--manifest", str(manifest), "--answers", str(res), "--out", str(out)],
        check=True,
        capture_output=True,
    )
    run = json.loads(out.read_text())
    assert run["meta"]["sha"] == "abc"
    assert all(r["status"] == 200 for r in run["rows"].values())


def test_collect_reads_only_its_own_run(tmp_path):
    """Two runs' answers in one folder (the service keeps them 48 h) never mix."""
    cmd = [sys.executable, str(ROOT / "scripts" / "route_scorecard.py")]
    req = tmp_path / "queue" / "req"
    res = tmp_path / "queue" / "res"
    res.mkdir(parents=True)
    for label, miles in (("old", 2.0), ("new", 3.0)):
        subprocess.run(
            [
                *cmd,
                "queue",
                "--ref",
                "origin/main",
                "--label",
                label,
                "--only",
                "mall",
                "--no-contrast",
                "--no-stability",
                "--out",
                str(req),
            ],
            check=True,
            capture_output=True,
        )
        for f in sorted(req.glob(f"scorecard-{label}-*.json")):
            plans = json.loads(f.read_text())["plans"]
            (res / f.name).write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "sha": label,
                        "plans": [
                            {
                                "label": p["label"],
                                "status": 200,
                                "answer": answer(distance_m=miles * MI),
                            }
                            for p in plans
                        ],
                    }
                )
            )
    out = tmp_path / "run.json"
    subprocess.run(
        [
            *cmd,
            "collect",
            "--manifest",
            str(tmp_path / "queue" / "old.plans.json"),
            "--answers",
            str(res),
            "--out",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    run = json.loads(out.read_text())
    assert run["meta"]["sha"] == "old"
    assert {round(r["miles"], 2) for r in run["rows"].values()} == {2.0}


def test_long_trips_go_alone_to_the_service():
    sys.path.insert(0, str(ROOT / "scripts"))
    import route_scorecard

    entries = [{"setting": "urban"}] * 9 + [{"setting": "long"}] + [{"setting": "urban"}] * 2
    sizes = [len(c) for c in route_scorecard._chunks(entries)]
    assert sizes == [8, 1, 3]


def test_crashed_plan_and_missing_distance():
    row = scorecard.score({"geometry": None})
    assert row["miles"] is None and row["minutes"] is None
    entries = _entries()[:1]
    never = scorecard.run_of(entries, {})
    now = scorecard.run_of(entries, {"t|default|base": {"status": 200, "body": answer()}})
    assert "plans again" not in "; ".join(
        sum(scorecard.compare(never, now)["findings"].values(), [])
    )


# --- the nightly run on the beta (alert.sh scorecard) ----------------------------------------


def _cli():
    sys.path.insert(0, str(ROOT / "scripts"))
    import route_scorecard

    return route_scorecard


class _Args:
    base_url = "http://127.0.0.1:8087"
    host = "beta.test"
    timeout = 5.0
    pause = 2.0
    budget_min = 90.0


def test_http_retries_a_busy_slot_once_and_stops_at_its_budget(tmp_path):
    cli = _cli()
    entries = [
        {
            "key": f"t{i}|default|base",
            "trip": f"t{i}",
            "preset": "default",
            "variant": "base",
            "body": {"points": [[-77.0, 38.9], [-76.97, 38.9]], "preset": "default"},
        }
        for i in range(3)
    ]
    calls, slept = [], []

    def post(url, body, host, timeout):
        calls.append((url, host))
        return (429, {"error": "busy"}) if len(calls) == 1 else (200, answer())

    ticks = iter([0, 0, 1, 1, 2, 2, 90 * 60 + 1, 90 * 60 + 1])
    run = cli.plan_http(
        entries,
        _Args(),
        tmp_path / "run.json",
        {},
        post=post,
        sleep=slept.append,
        clock=lambda: next(ticks),
    )
    assert calls[0] == ("http://127.0.0.1:8087/api/route", "beta.test")
    assert cli.BUSY_RETRY_S in slept
    assert [r["status"] for r in run["rows"].values()] == [200, 200, None]
    assert (
        json.loads((tmp_path / "run.json").read_text())["rows"]["t1|default|base"]["status"] == 200
    )


def _night(folder, stamp, miles, status=200):
    entries = [
        {
            "key": "t|default|base",
            "trip": "t",
            "preset": "default",
            "variant": "base",
            "body": {"points": [[-77.0, 38.9], [-76.97, 38.9]]},
        }
    ]
    body = answer(distance_m=miles * MI) if status == 200 else {"error": "down"}
    run = scorecard.run_of(entries, {"t|default|base": {"status": status, "body": body}})
    (folder / f"run-{stamp}.json").write_text(json.dumps(run))


def _findings(folder):
    out = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "route_scorecard.py"),
            "findings",
            "--dir",
            str(folder),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout


def test_findings_compare_with_the_last_good_night_and_skip_mixed_runs(tmp_path):
    _night(tmp_path, "20261110T0800Z", 2.0)
    assert _findings(tmp_path) == "", "one night: nothing to compare with"
    _night(tmp_path, "20261111T0800Z", 2.0, status=503)  # routers down
    first, *rest = _findings(tmp_path).splitlines()
    assert first == "20261111T0800Z" and "no longer plans (503" in "\n".join(rest)
    # The night after a bad one still compares with the last good night.
    _night(tmp_path, "20261112T0800Z", 3.0)
    text = _findings(tmp_path)
    assert text.startswith("20261112T0800Z\n") and "miles 2.00 -> 3.00" in text
    # A mixed run is never the newest run compared, nor a baseline.
    (tmp_path / "run-20261113T0800Z.mixed.json").write_text("{}")
    assert _findings(tmp_path).startswith("20261112T0800Z\n")
    # Older than a day: not posted again.
    old = time.time() - 21 * 3600
    for p in tmp_path.iterdir():
        os.utime(p, (old, old))
    assert _findings(tmp_path) == ""


def test_findings_fit_one_post(tmp_path):
    cli = _cli()
    entries = [
        {
            "key": f"trip-{i:02d}-with-a-long-name|default|base",
            "trip": f"trip-{i:02d}",
            "preset": "default",
            "variant": "base",
            "body": {"points": [[-77.0, 38.9], [-76.97, 38.9]]},
        }
        for i in range(30)
    ]
    for stamp, miles in (("20261110T0800Z", 2.0), ("20261111T0800Z", 3.0)):
        ans = {e["key"]: {"status": 200, "body": answer(distance_m=miles * MI)} for e in entries}
        (tmp_path / f"run-{stamp}.json").write_text(json.dumps(scorecard.run_of(entries, ans)))
    text = _findings(tmp_path)
    assert len(text) < 1800
    assert f"...and {30 - cli.MAX_LINES} more" in text


def test_nightly_keeps_a_bounded_history(tmp_path, monkeypatch):
    cli = _cli()
    for i in range(4):
        (tmp_path / f"run-2026110{i}T0800Z.json").write_text("{}")
    monkeypatch.setattr(cli, "plan_http", lambda *a, **k: {"rows": {}})
    cli.main(
        [
            "nightly",
            "--base-url",
            "http://x",
            "--dir",
            str(tmp_path),
            "--keep",
            "3",
            "--only",
            "mall",
        ]
    )
    kept = sorted(p.name for p in tmp_path.iterdir())
    assert len(kept) == 3 and "run-20261100T0800Z.json" not in kept
