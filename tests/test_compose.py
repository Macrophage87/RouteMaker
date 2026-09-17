"""Compose stack rules.

Asserted here as well as in CI so that a change to the stack fails in the same
suite as everything else, rather than only on push.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
SERVICES: dict = COMPOSE["services"]


def limits(name: str) -> dict:
    return SERVICES[name].get("deploy", {}).get("resources", {}).get("limits", {})


def test_every_service_declares_both_limits() -> None:
    """A service with no memory limit can take PostGIS down with it, and a
    six-hour rebuild with no CPU limit saturates every core and destroys the
    preview latency target and the canary health check along with it.

    One test reporting every offending service, rather than three parametrised
    over thirteen services each. Twenty-six near-identical cases said nothing
    that this does not, and a stack that lost limits on four services reported
    four failures where one naming all four is what an operator needs.
    """
    missing = {
        name: sorted({"memory", "cpus"} - set(limits(name)))
        for name in sorted(SERVICES)
        if not {"memory", "cpus"} <= set(limits(name))
    }
    assert not missing, f"services missing limits: {missing}"


def test_only_the_edge_proxy_publishes_ports() -> None:
    """Photon, Valhalla, the renderer and the bot are reachable only from inside.
    The bot is the source of authorization truth and must never be addressable
    from outside the host."""
    published = sorted(
        name for name, service in SERVICES.items() if name != "caddy" and service.get("ports")
    )
    assert not published, f"services publishing ports: {published}"


def test_the_bot_alone_holds_the_bot_token() -> None:
    """A shared env_file would hand it to every container, which is exactly what
    the per-service scoping exists to prevent."""
    holders = [
        name
        for name, service in SERVICES.items()
        if "DISCORD_BOT_TOKEN" in (service.get("environment") or {})
    ]
    assert holders == ["bot"]


def key_encryption_key_holders() -> list[str]:
    return sorted(
        name
        for name, service in SERVICES.items()
        if "KEY_ENCRYPTION_KEY" in (service.get("environment") or {})
    )


def test_the_key_encryption_key_reaches_the_api_and_the_worker() -> None:
    """Both of them, and the pin matters: the ban tombstone's HMAC key is
    derived from this one, so a service that lost it would refuse to start
    rather than key tombstones with something else."""
    assert {"api", "worker"} <= set(key_encryption_key_holders())


def test_the_key_encryption_key_reaches_only_the_services_that_run_django() -> None:
    """Which is a wider set than it was, on purpose.

    `settings.TOMBSTONE_KEY` is derived from this key and has no default at all,
    so every process that imports Django settings needs it or fails at import -
    including `migrate` and the rebuild worker, neither of which computes a
    tombstone. That is the intended direction: a container that cannot key a
    tombstone should stop, not carry on with a key from the repository.

    What the scoping rule is actually protecting is asserted here rather than
    implied by an equality against two names: the bot, the edge proxy, the
    database and the routing containers never see it. The bot is the one that
    matters - it is the source of authorization truth and holds the token that
    reads every guild's roster.
    """
    assert key_encryption_key_holders() == ["api", "migrate", "rebuild", "worker"]
    for name in ("bot", "caddy", "postgis", "photon", "valhalla-standard"):
        assert "KEY_ENCRYPTION_KEY" not in (SERVICES[name].get("environment") or {}), name


def test_the_bootstrap_instance_admin_id_reaches_the_api_alone() -> None:
    """The admin is the only surface that reads it, and it is inert once the
    instance-admin list is non-empty."""
    holders = sorted(
        name
        for name, service in SERVICES.items()
        if "BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID" in (service.get("environment") or {})
    )
    assert holders == ["api"]


def test_no_service_uses_a_shared_env_file() -> None:
    """env_file hands the same secrets to every service that declares it, which
    is the failure mode the scoping rule exists for."""
    assert [name for name, s in SERVICES.items() if s.get("env_file")] == []


def test_one_valhalla_process_per_tile_variant() -> None:
    variants = sorted(n for n in SERVICES if n.startswith("valhalla-"))
    assert variants == ["valhalla-ebike", "valhalla-no-trail", "valhalla-standard"]


def _load_check_compose_limits():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_compose_limits", REPO / "scripts" / "check_compose_limits.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_the_swap_time_peak_fits_in_the_host() -> None:
    """The one rule the script adds that this file does not: the sum of the
    limits, including the duplicate Valhalla containers resident during a swap,
    has to stay under host RAM.

    Run in-process rather than as a subprocess. The script used to be shelled out
    to here, which re-ran the two limit checks above a fourth time and reported
    whatever it found as a single opaque return code.

    The path is passed explicitly (NIT 7): main()'s old default,
    `"compose.yaml"`, resolved against pytest's own working directory rather
    than the repository root, so a run from any other directory silently
    parsed a different file - or none - from the one this test's other
    assertions were written against.
    """
    script = _load_check_compose_limits()
    assert script.main(str(REPO / "compose.yaml")) == 0


def test_valhalla_worker_count_is_checked_against_its_own_limit(tmp_path) -> None:
    """PLAN: "the CI compose check asserts the worker count against the limit
    rather than merely asserting that a limit exists." A worker count raised
    from 2 to 64 at the same 2 GB limit is exactly the mutation that survived
    the round-3 panel, and it must fail here, not just the weak `>= 2` floor
    tests/test_valhalla_config.py used to carry alone.
    """
    script = _load_check_compose_limits()

    mutated = yaml.safe_load((REPO / "compose.yaml").read_text())
    mutated["services"]["valhalla-standard"]["command"][2] = "64"
    mutated_path = tmp_path / "compose.yaml"
    mutated_path.write_text(yaml.safe_dump(mutated))

    assert script.main(str(mutated_path)) == 1, "64 workers at a 2 GB, 2-cpu limit must be refused"


def test_the_worker_starts_through_django() -> None:
    """`procrastinate --app=... worker` never set Django up: it died on the
    missing schema, and past that every task raised AppRegistryNotReady. The
    process has to be the management command, whose schema comes from the same
    migrate one-shot as every other table."""
    for name in ("worker", "rebuild"):
        command = SERVICES[name]["command"]
        assert command[:3] == ["./manage.py", "procrastinate", "worker"], name
        assert SERVICES[name]["depends_on"]["migrate"] == {
            "condition": "service_completed_successfully"
        }, f"{name} must not start before the schema exists"
    assert SERVICES["api"]["depends_on"]["migrate"] == {
        "condition": "service_completed_successfully"
    }


def test_the_rebuild_queue_is_consumed_only_by_the_container_with_the_binaries() -> None:
    """The queue split is load-bearing: the rebuild service is the one with the
    Valhalla and GDAL binaries, the data mounts and the 8G limit, so it is the
    only worker on the rebuild queue - and the api-image worker, which has
    none of those, never picks a rebuild up."""

    def queues(name: str) -> set[str]:
        for argument in SERVICES[name]["command"]:
            if argument.startswith("--queues="):
                return set(argument.removeprefix("--queues=").split(","))
        raise AssertionError(f"{name} listens on every queue")

    assert queues("rebuild") == {"rebuild"}
    assert "rebuild" not in queues("worker")
    assert "maintenance" in queues("worker")
    assert SERVICES["rebuild"]["image"] != SERVICES["worker"]["image"]
    assert SERVICES["rebuild"]["restart"] == "unless-stopped", "a resident worker, not a one-shot"


def test_the_maintenance_worker_has_more_than_one_slot() -> None:
    """Every periodic task except the rebuild queues on the maintenance worker,
    and Procrastinate drops a periodic tick whose predecessor is still running
    rather than delaying it. With the default of one slot a nightly dump held
    the queue, and the 5-minute degraded sweep and the 10-minute worker
    heartbeat silently missed their ticks - the bound docs/OPERATIONS.md
    describes could not be met by any change inside the tasks."""
    assert "--concurrency=4" in SERVICES["worker"]["command"]
    assert "--concurrency=1" in SERVICES["rebuild"]["command"], (
        "the rebuild stays single-slot: two rebuilds at once would share a data volume"
    )


def test_the_rebuild_sees_the_whole_data_volume_at_the_path_its_settings_assume() -> None:
    volumes = SERVICES["rebuild"]["volumes"]
    assert "${DATA_ROOT}:/data" in volumes
    assert SERVICES["rebuild"]["environment"]["DATA_ROOT"] == "/data"
    assert "./lua:/conf/lua:ro" in volumes and "./valhalla:/conf:ro" in volumes


def test_the_backup_lands_on_the_data_volume() -> None:
    assert "${DATA_ROOT}/backups:/data/backups" in SERVICES["worker"]["volumes"]
