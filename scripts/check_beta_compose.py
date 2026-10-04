#!/usr/bin/env python3
"""Assert the private-beta stack's resource and exposure rules.

The beta variant of scripts/check_compose_limits.py. That script is written
against the 32 GB production host (caddy publishes, the rebuild is resident, the
sum of limits must stay under 32 GB); the beta runs on a shared 15 GiB EC2 host
with about 8.6 GiB free and no swap, with nginx instead of Caddy and no rebuild,
so it needs its own rules. It checks the RENDERED config - what `docker compose
-f compose.yaml -f compose.beta.yaml config` prints - because that is what the
daemon will be given: an overlay's merge can change a value the file never
mentions, and the rendered form is also where compose has already expanded the
`${...}` defaults.

    scripts/check_beta_compose.py --render              # render with dummy env, then check
    scripts/check_beta_compose.py --render --offroad    # the same with the offroad profile on
    scripts/check_beta_compose.py rendered.yaml         # a file made by `docker compose config`

The rules, each of which exists because breaking it hurts a host that is not ours:

* exactly the beta's services - caddy and rebuild must not be in the rendered set;
* every service has a memory cap AND a CPU cap, and memswap_limit equals the
  memory cap, so a container can neither grow past its cap nor borrow swap;
* the only published port is the api's, on 127.0.0.1;
* the resident total (everything but the one-shot migrate) fits the budget;
* gunicorn is at most 3 workers, the weekly rebuild is paused, Photon's heap and
  PostgreSQL's shared_buffers fit inside their caps;
* the Valhalla worker count fits each router's cap, using the same function the
  production check uses with the beta's own per-worker figure (below).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_compose_limits as production  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# The services the beta runs. `valhalla-offroad` is the placeholder behind the
# `offroad` profile and is allowed, not required.
EXPECTED_SERVICES = {
    "postgis",
    "api",
    "worker",
    "migrate",
    "photon",
    "valhalla-standard",
    "valhalla-no-trail",
    "valhalla-ebike",
    "valhalla-weekend",
}
OPTIONAL_SERVICES = {"valhalla-offroad"}
FORBIDDEN_SERVICES = {"caddy", "rebuild", "renderer", "bot"}

# Exits before the api starts (api depends on it completing), so it is not
# resident beside the others; it is still capped.
ONE_SHOT = {"migrate"}

# The host: 15 GiB total, about 8.6 GiB available at the owner's measurement
# (OWNER-DECISIONS 361). The resident ceiling is the owner's "about 6 GB"
# widened to what the measured per-container needs add up to (compose.beta.yaml
# header), and still leaves the host 1.5 GiB of the 8.6 for its own growth.
HOST_AVAILABLE_GB = 8.6
MAX_RESIDENT_GB = 7.0

MAX_GUNICORN_WORKERS = 3

# The production check charges 700 MB per Valhalla worker, a documented policy
# figure that was never measured. For the beta, the measurement exists: the
# standard router used 666 MiB at its 2-worker idle with the 500 MiB tiles.tar
# mapped (docker stats, 2026-10-04), so the workers themselves are well under
# 100 MiB each and the rest is file pages the kernel reclaims instead of killing
# the container for. 300 MB per worker is three times that, and two workers at
# 300 MB fit a 768 MB cap with the archive's working set beside them.
BETA_VALHALLA_PER_WORKER_MEMORY_MB = 300

# Photon: JVM heap plus the native overhead (metaspace, threads, direct buffers)
# must fit the cap; 256 MB is the floor measured at ~100 threads.
PHOTON_NATIVE_OVERHEAD_MB = 256

# PostgreSQL: shared_buffers is a fixed carve-out of the cap; the backends'
# work_mem, maintenance_work_mem and the OS cache all share the rest.
POSTGRES_MAX_SHARED_BUFFERS_FRACTION = 0.30

_UNITS = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3}


def parse_bytes(value) -> int:
    """`1258291200` (as `docker compose config` prints it), `"768M"` or `1.2G`."""
    text = str(value).strip().upper()
    if text.endswith("IB"):  # 768MiB
        text = text[:-2]
    elif text.endswith("B") and len(text) > 1 and text[-2] in "KMG":  # 768MB
        text = text[:-1]
    if text and text[-1] in "KMG":
        return int(float(text[:-1]) * _UNITS[text[-1]])
    return int(float(text))


def mib(n: int) -> float:
    return n / 1024**2


def limits(service: dict) -> dict:
    return service.get("deploy", {}).get("resources", {}).get("limits", {})


def _env(service: dict) -> dict:
    env = service.get("environment") or {}
    if isinstance(env, list):  # "K=V" form
        return dict(item.split("=", 1) for item in env if "=" in item)
    return {k: ("" if v is None else str(v)) for k, v in env.items()}


def _published(service: dict) -> list[dict]:
    """Published ports as dicts, whether compose rendered them long or short form."""
    out = []
    for port in service.get("ports") or []:
        if isinstance(port, dict):
            out.append(port)
            continue
        parts = str(port).split(":")
        host_ip = parts[0] if len(parts) == 3 else ""
        out.append(
            {
                "host_ip": host_ip,
                "published": parts[-2] if len(parts) >= 2 else "",
                "target": parts[-1],
            }
        )
    return out


def _flags(command) -> list[str]:
    return [str(c) for c in command] if isinstance(command, list) else str(command or "").split()


def check_services(services: dict) -> list[str]:
    problems: list[str] = []
    names = set(services)
    for name in sorted(FORBIDDEN_SERVICES & names):
        problems.append(f"{name}: must not be part of the beta stack (park it behind a profile)")
    for name in sorted(EXPECTED_SERVICES - names):
        problems.append(f"{name}: missing from the beta stack")
    for name in sorted(names - EXPECTED_SERVICES - OPTIONAL_SERVICES - FORBIDDEN_SERVICES):
        problems.append(
            f"{name}: not a service the beta expects (add it to EXPECTED_SERVICES deliberately)"
        )
    return problems


def check_limits(services: dict) -> list[str]:
    problems: list[str] = []
    for name, service in services.items():
        lim = limits(service)
        if "memory" not in lim:
            problems.append(f"{name}: no memory limit")
            continue
        if "cpus" not in lim:
            problems.append(f"{name}: no CPU limit")
        swap = service.get("memswap_limit")
        if swap is None:
            problems.append(
                f"{name}: no memswap_limit (a container could borrow swap past its cap)"
            )
        elif parse_bytes(swap) != parse_bytes(lim["memory"]):
            problems.append(
                f"{name}: memswap_limit {mib(parse_bytes(swap)):.0f} MiB differs from its "
                f"{mib(parse_bytes(lim['memory'])):.0f} MiB memory limit"
            )
    return problems


def check_ports(services: dict) -> list[str]:
    problems: list[str] = []
    for name, service in services.items():
        ports = _published(service)
        if not ports:
            continue
        if name != "api":
            problems.append(f"{name}: publishes a port, and only the api may")
            continue
        for port in ports:
            if str(port.get("host_ip", "")) != "127.0.0.1":
                problems.append(
                    f"api: port {port.get('published')} is not bound to 127.0.0.1 "
                    f"(host_ip={port.get('host_ip')!r})"
                )
    if "api" in services and not _published(services["api"]):
        problems.append("api: publishes no port, so nginx has nothing to proxy to")
    return problems


def resident_bytes(services: dict) -> int:
    return sum(
        parse_bytes(limits(s)["memory"])
        for n, s in services.items()
        if n not in ONE_SHOT and "memory" in limits(s)
    )


def check_budget(services: dict) -> list[str]:
    problems: list[str] = []
    resident_gb = resident_bytes(services) / 1024**3
    if resident_gb > MAX_RESIDENT_GB:
        problems.append(
            f"resident total {resident_gb:.2f} GiB exceeds the beta's "
            f"{MAX_RESIDENT_GB:.1f} GiB ceiling (the host has about {HOST_AVAILABLE_GB} GiB "
            "available); lower another cap before adding a service"
        )
    with_migrate = (
        sum(parse_bytes(limits(s)["memory"]) for s in services.values() if "memory" in limits(s))
        / 1024**3
    )
    if with_migrate > HOST_AVAILABLE_GB - 1.0:
        problems.append(
            f"startup peak (resident plus migrate) {with_migrate:.2f} GiB leaves under 1 GiB of "
            "the host's "
            f"{HOST_AVAILABLE_GB} GiB available"
        )
    return problems


def check_runtime_settings(services: dict) -> list[str]:
    problems: list[str] = []
    api_env = _env(services.get("api", {}))
    try:
        workers = int(api_env.get("WEB_CONCURRENCY", ""))
    except ValueError:
        problems.append(f"api: WEB_CONCURRENCY is not a number: {api_env.get('WEB_CONCURRENCY')!r}")
    else:
        if workers > MAX_GUNICORN_WORKERS:
            problems.append(
                f"api: WEB_CONCURRENCY {workers} exceeds the beta's {MAX_GUNICORN_WORKERS}"
            )
    for name in ("api", "worker", "migrate"):
        if name in services and _env(services[name]).get("WEEKLY_REBUILD_PAUSED") != "1":
            problems.append(
                f"{name}: WEEKLY_REBUILD_PAUSED must be 1 "
                "(no rebuild worker exists to take the job)"
            )

    photon = services.get("photon")
    if photon is not None and "memory" in limits(photon):
        text = " ".join(_flags(photon.get("command")))
        match = re.search(r"-Xmx(\d+)([mMgG])", text)
        if not match:
            problems.append(
                "photon: the command sets no -Xmx, so the JVM sizes its heap from the host's RAM"
            )
        else:
            heap_mb = int(match.group(1)) * (1024 if match.group(2).lower() == "g" else 1)
            cap_mb = mib(parse_bytes(limits(photon)["memory"]))
            if heap_mb + PHOTON_NATIVE_OVERHEAD_MB > cap_mb:
                problems.append(
                    f"photon: -Xmx{heap_mb}m plus {PHOTON_NATIVE_OVERHEAD_MB} MB native overhead "
                    f"exceeds its {cap_mb:.0f} MB cap"
                )

    postgis = services.get("postgis")
    if postgis is not None and "memory" in limits(postgis):
        flags = _flags(postgis.get("command"))
        buffers = next((f.split("=", 1)[1] for f in flags if f.startswith("shared_buffers=")), None)
        if buffers is None:
            problems.append(
                "postgis: shared_buffers is not set (the 128 MB default is not sized to this cap)"
            )
        else:
            cap = parse_bytes(limits(postgis)["memory"])
            if parse_bytes(buffers) > cap * POSTGRES_MAX_SHARED_BUFFERS_FRACTION:
                problems.append(
                    f"postgis: shared_buffers={buffers} is over "
                    f"{POSTGRES_MAX_SHARED_BUFFERS_FRACTION:.0%} of its cap"
                )
    return problems


def check_valhalla(services: dict) -> list[str]:
    """The production check's own function, fed the beta's limits as `NNNM` strings
    and with the per-worker figure swapped for the measured one."""
    translated = {
        name: {
            "command": service.get("command"),
            "deploy": {
                "resources": {
                    "limits": {
                        "memory": f"{mib(parse_bytes(limits(service)['memory'])):.0f}M",
                        "cpus": str(limits(service).get("cpus", "1")),
                    }
                }
            },
        }
        for name, service in services.items()
        if name.startswith("valhalla-") and "memory" in limits(service)
    }
    original = production.VALHALLA_PER_WORKER_MEMORY_MB
    production.VALHALLA_PER_WORKER_MEMORY_MB = BETA_VALHALLA_PER_WORKER_MEMORY_MB
    try:
        return production.check_valhalla_worker_counts(translated)
    finally:
        production.VALHALLA_PER_WORKER_MEMORY_MB = original


def check_mounts(services: dict, data_root: str | None) -> list[str]:
    """Binds come from DATA_ROOT or the repository, and never the Docker socket."""
    problems: list[str] = []
    for name, service in services.items():
        for volume in service.get("volumes") or []:
            source = (
                volume.get("source", "") if isinstance(volume, dict) else str(volume).split(":")[0]
            )
            if "docker.sock" in source:
                problems.append(f"{name}: mounts the Docker socket")
            if (
                data_root
                and source.startswith("/")
                and not (source.startswith(data_root) or source.startswith(str(REPO)))
            ):
                problems.append(
                    f"{name}: bind source {source} is outside DATA_ROOT and the checkout"
                )
    return problems


def check(compose: dict, data_root: str | None = None) -> list[str]:
    services = compose.get("services", {})
    return [
        *check_services(services),
        *check_limits(services),
        *check_ports(services),
        *check_budget(services),
        *check_runtime_settings(services),
        *check_valhalla(services),
        *check_mounts(services, data_root),
    ]


def table(compose: dict) -> str:
    services = compose.get("services", {})
    rows = [f"{'service':<20}{'memory MiB':>12}{'cpus':>7}"]
    for name in sorted(services):
        lim = limits(services[name])
        if "memory" not in lim:
            continue
        note = "  (one-shot, not resident)" if name in ONE_SHOT else ""
        rows.append(
            f"{name:<20}{mib(parse_bytes(lim['memory'])):>12.0f}"
            f"{str(lim.get('cpus', '?')):>7}{note}"
        )
    total = resident_bytes(services)
    rows.append(
        f"{'resident total':<20}{mib(total):>12.0f}   = {total / 1024**3:.2f} GiB "
        f"of about {HOST_AVAILABLE_GB} GiB available"
    )
    return "\n".join(rows)


DUMMY_ENV = {
    "TAG": "check",
    "DATA_ROOT": "/data/routemaker",
    "DJANGO_SECRET_KEY": "dummy",
    "KEY_ENCRYPTION_KEY": "dummy",
    "PGPASSWORD": "dummy",
    "DJANGO_ALLOWED_HOSTS": "routemaker.cieply.com",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://routemaker.cieply.com",
    "DISCORD_CLIENT_ID": "dummy",
    "DISCORD_REDIRECT_URI": "https://routemaker.cieply.com/auth/callback",
    "DISCORD_CLIENT_SECRET": "dummy",
}


def render(offroad: bool = False) -> dict:
    """`docker compose config` over the base and the overlay, with dummy values and
    an empty env file, so neither a local .env nor the caller's environment leaks in."""
    with tempfile.NamedTemporaryFile("w", suffix=".env") as empty:
        command = [
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.beta.yaml",
            "--env-file",
            empty.name,
        ]
        if offroad:
            command += ["--profile", "offroad"]
        command += ["config"]
        env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG")
        }
        env.update(DUMMY_ENV)
        done = subprocess.run(
            command, cwd=REPO, env=env, capture_output=True, text=True, check=False
        )
    if done.returncode != 0:
        raise SystemExit(f"docker compose config failed:\n{done.stderr}")
    return yaml.safe_load(done.stdout)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if "--render" in argv:
        compose = render(offroad="--offroad" in argv)
    elif args:
        compose = yaml.safe_load(Path(args[0]).read_text())
    else:
        print(__doc__, file=sys.stderr)
        return 2
    data_root = DUMMY_ENV["DATA_ROOT"] if "--render" in argv else None
    problems = check(compose, data_root)
    print(table(compose))
    for problem in problems:
        print(f"beta compose: {problem}", file=sys.stderr)
    if not problems:
        print("beta compose: ok")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
