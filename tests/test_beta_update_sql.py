"""The beta's data update (scripts/beta/receive-data.sh db --update-data) against the real schema.

The update empties public tables that come from home (override, stress_edit, the stress tile
cache, the junction ratings, the Avoid junctions) and reloads them, while the beta's own rows that
point at them stay. PostgreSQL refuses a TRUNCATE of a table another table's foreign key points
at, even when both are empty, and a DELETE of a row still pointed at. Text checks on the script
did not catch the stress_suggestion -> stress_edit key migration 0016 added (the v0.4.0 beta
install failed on it), so these run the script's own statements against the test database, which
is migrated to the head migration.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.contrib.gis.geos import Point
from django.db import connection, transaction

from core.models import (
    AvoidJunction,
    JunctionOverride,
    JunctionSuggestion,
    Override,
    StressEdit,
    StressSuggestion,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = (REPO / "scripts" / "beta" / "receive-data.sh").read_text()

db = pytest.mark.django_db(transaction=True)


# The statements the update writes literally, in the order they appear in the script; the
# replace loop's DELETE is a printf template, so its tables are read from the loop instead.
STATEMENT = re.compile(
    r"UPDATE public\.\w+ SET \w+ = NULL WHERE \w+ IS NOT NULL;"
    r"|DELETE FROM public\.\w+;"
    r"|TRUNCATE public\.\w+(?:, public\.\w+)*;"
)


def statements() -> list[str]:
    found = STATEMENT.findall(SCRIPT)
    assert any(s.startswith("TRUNCATE") for s in found), "the update path is not where this looks"
    return found


def replaced() -> list[str]:
    loop = re.search(r"for t in ([a-z_ ]+); do", SCRIPT)
    assert loop, "the update path's replace loop is not where this test looks"
    return loop.group(1).split()


def emptied() -> list[str]:
    tables = re.findall(r"(?:DELETE FROM|TRUNCATE|,) public\.(\w+)", " ".join(statements()))
    return tables + replaced()


@db
def test_every_key_into_an_emptied_table_is_let_go_of_first() -> None:
    emptied_tables = emptied()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select src.relname, a.attname, dst.relname
            from pg_constraint c
            join pg_class src on src.oid = c.conrelid
            join pg_class dst on dst.oid = c.confrelid
            join pg_namespace n on n.oid = dst.relnamespace
            join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
            where c.contype = 'f' and n.nspname = 'public' and dst.relname = any(%s)
            """,
            [emptied_tables],
        )
        keys = cursor.fetchall()
    assert keys  # the catalog query found the keys it is meant to check
    detach = re.compile(r"UPDATE public\.(\w+) SET (\w+)")
    let_go = {m.groups() for m in map(detach.match, statements()) if m}
    missing = [
        f"{src}.{column} -> {dst}"
        for src, column, dst in keys
        if src not in emptied_tables and (src, column) not in let_go
    ]
    assert not missing, f"receive-data.sh --update-data would be refused by: {missing}"
    # A TRUNCATE is refused for any key into its tables from outside that same statement, even
    # with the column set to NULL: letting go is enough only for a DELETE.
    for truncate in (s for s in statements() if s.startswith("TRUNCATE")):
        together = re.findall(r"public\.(\w+)", truncate)
        refused = [f"{s}.{c} -> {d}" for s, c, d in keys if d in together and s not in together]
        assert not refused, f"{truncate} would be refused by: {refused}"


def beta_rows() -> tuple[StressSuggestion, JunctionSuggestion]:
    """The beta's own rows pointing at everything the update empties, as an approval leaves them."""
    old = Override.objects.create(
        kind="stress", osm_way_id=1, value={"tier": 3}, reason="r", evidence="e"
    )
    new = Override.objects.create(
        kind="stress", osm_way_id=1, value={"tier": 2}, reason="r", evidence="e"
    )
    Override.objects.filter(pk=old.pk).update(superseded_by=new)
    edit = StressEdit.objects.create(action="set", override=new, replaced=old)
    StressEdit.objects.create(action="undo", undoes=edit)
    road = StressSuggestion.objects.create(
        osm_way_id=1, lat=38.9, lon=-77.0, current_tier=3, tier=2, reason="r", edit=edit,
        status="approved",
    )  # fmt: skip
    at = Point(-77.0, 38.9, srid=4326)
    junction = JunctionSuggestion.objects.create(
        lon=-77.0, lat=38.9, node="n1", current_level=2, target_level=5, reason="r",
        status="approved", override=JunctionOverride.objects.create(name="x", location=at, level=4),
        avoid=AvoidJunction.objects.create(name="x", location=at, reason="r", approved=True),
    )  # fmt: skip
    return road, junction


@db
def test_the_update_statements_run_on_the_head_schema() -> None:
    road, junction = beta_rows()
    # The script's own statements, then the replace loop's DELETEs, in one transaction as the
    # update runs them (the loop's suggestions let go of their rows before these run). Django's
    # keys are checked at commit, so a key left pointing fails as the block ends.
    with transaction.atomic(), connection.cursor() as cursor:
        for statement in statements():
            cursor.execute(statement)
        for table in replaced():
            cursor.execute(f"DELETE FROM public.{table};")
    assert not Override.objects.exists() and not StressEdit.objects.exists()
    assert not JunctionOverride.objects.exists() and not AvoidJunction.objects.exists()
    # the beta's own suggestions stay, letting go only of what their approval made
    road.refresh_from_db()
    junction.refresh_from_db()
    assert road.status == "approved" and road.edit_id is None
    assert junction.override_id is None and junction.avoid_id is None
