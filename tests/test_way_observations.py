"""The adapter for measured speeds and estimated counts (`pipeline.way_observations`), and
the rebuild passing them to the classifier (review r1, finding 14). No source is installed
today; the file here is synthetic."""

from __future__ import annotations

import json

import pytest

from pipeline import way_observations
from pipeline.way_observations import Observation, ObservationsRefused
from tests.test_arterial_stage import FIRST_ST_WAY, classify, make_context


def write(folder, ways, **extra):
    folder.mkdir(parents=True, exist_ok=True)
    document = {"version": 1, "source": "synthetic, for the test", "ways": ways, **extra}
    (folder / way_observations.FILE_NAME).write_text(json.dumps(document))


def test_no_file_is_no_observations(tmp_path) -> None:
    assert way_observations.load(tmp_path) == {}
    assert way_observations.load(None) == {}


def test_the_file_is_read_by_way(tmp_path) -> None:
    write(tmp_path, {"7": {"observed_speed_mph": 34.5}, "8": {"estimated_aadt": 2600}})
    assert way_observations.load(tmp_path) == {
        7: Observation(observed_speed_mph=34.5),
        8: Observation(estimated_aadt=2600),
    }


@pytest.mark.parametrize(
    "ways",
    [
        {"x": {}},
        {"7": {"observed_speed_mph": 0}},
        {"7": {"observed_speed_mph": 240}},
        {"7": {"observed_speed_mph": "34"}},
        {"7": {"estimated_aadt": -5}},
        {"7": {"speed": 30}},
        {"7": 30},
    ],
)
def test_a_bad_row_is_refused(tmp_path, ways) -> None:
    write(tmp_path, ways)
    with pytest.raises(ObservationsRefused):
        way_observations.load(tmp_path)


def test_a_file_must_say_its_source_and_version(tmp_path) -> None:
    write(tmp_path, {}, source=" ")
    with pytest.raises(ObservationsRefused, match="source"):
        way_observations.load(tmp_path)
    write(tmp_path, {}, version=2)
    with pytest.raises(ObservationsRefused, match="version 1"):
        way_observations.load(tmp_path)


def test_the_rebuild_reads_a_measured_speed_in_place_of_the_limit(tmp_path, monkeypatch) -> None:
    plain = make_context(tmp_path / "a", monkeypatch)
    classify(plain)
    before = plain.stress_by_way[FIRST_ST_WAY]
    assert before.observed_speed_mph is None and "25 mph" in before.rule

    context = make_context(tmp_path / "b", monkeypatch)
    write(context.reference_dir, {str(FIRST_ST_WAY): {"observed_speed_mph": 41.0}})
    classify(context)
    after = context.stress_by_way[FIRST_ST_WAY]
    assert after.observed_speed_mph == 41.0
    assert "40 mph" in after.rule and after.tier > before.tier
    # The limit is still what the junction model and the road panel are told.
    assert after.speed_mph == before.speed_mph
    # Every other way is untouched.
    others = [i for i in context.stress_by_way if i != FIRST_ST_WAY]
    assert all(context.stress_by_way[i] == plain.stress_by_way[i] for i in others)


def test_the_rebuild_reads_an_estimate_only_where_nothing_was_counted(
    tmp_path, monkeypatch
) -> None:
    context = make_context(tmp_path, monkeypatch)
    uncounted = next(w.osm_id for w in context.ways if w.osm_id not in context.aadt_by_way)
    write(
        context.reference_dir,
        {
            str(uncounted): {"estimated_aadt": 123},
            str(FIRST_ST_WAY): {"estimated_aadt": 123},
        },
    )
    classify(context)
    assert context.stress_by_way[uncounted].count_source == "supplied estimate"
    assert context.stress_by_way[uncounted].volume_aadt is None
    counted = context.stress_by_way[FIRST_ST_WAY]
    assert counted.count_source is None and counted.volume_aadt == 10665
