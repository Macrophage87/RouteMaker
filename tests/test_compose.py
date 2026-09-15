"""Compose stack rules.

Asserted here as well as in CI so that a change to the stack fails in the same
suite as everything else, rather than only on push.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
SERVICES: dict = COMPOSE["services"]


def limits(name: str) -> dict:
    return SERVICES[name].get("deploy", {}).get("resources", {}).get("limits", {})


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_service_has_a_memory_limit(name: str) -> None:
    """A service with no memory limit can take PostGIS down with it."""
    assert "memory" in limits(name), f"{name} has no memory limit"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_service_has_a_cpu_limit(name: str) -> None:
    """A six-hour rebuild with no CPU limit saturates every core and destroys the
    preview latency target and the canary health check along with it."""
    assert "cpus" in limits(name), f"{name} has no CPU limit"


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_only_the_edge_proxy_publishes_ports(name: str) -> None:
    """Photon, Valhalla, the renderer and the bot are reachable only from inside.
    The bot is the source of authorization truth and must never be addressable
    from outside the host."""
    if name == "caddy":
        return
    assert not SERVICES[name].get("ports"), f"{name} publishes a port"


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


def test_limits_script_passes_on_the_committed_stack() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_compose_limits.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
