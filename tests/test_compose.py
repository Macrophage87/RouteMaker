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


def test_the_key_encryption_key_reaches_only_api_and_worker() -> None:
    holders = sorted(
        name
        for name, service in SERVICES.items()
        if "KEY_ENCRYPTION_KEY" in (service.get("environment") or {})
    )
    assert holders == ["api", "worker"]


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
