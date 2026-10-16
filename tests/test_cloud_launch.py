"""scripts/cloud/launch.sh: the one-command cloud rebuild, against a fake `aws`.

Nothing here reaches AWS. The fake `aws` answers the EC2, SSM and S3 calls the launcher
makes from small state files (the box's states in turn, the command's statuses in turn,
how many looks before the result appears) and records every call; send-inputs.sh and
import-result.sh are stand-ins that record their arguments (they have their own tests in
tests/test_cloud_scripts.py). What is asserted is the order of the steps, the regions each
call goes to, what ends a wait, and that a box the launcher started is stopped however it
ends, and never one it did not start.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAUNCH = REPO / "scripts" / "cloud" / "launch.sh"
INSTANCE = "i-0123456789abcdef0"
COMMIT = "c" * 40
URL = "s3://bucket/rebuild-checkpoints/transfer/cloud-20261012"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

FAKE_AWS = r"""#!/usr/bin/env bash
printf 'aws %s\n' "$*" >>"$FAKE_DIR/calls.log"
args=()
while [ $# -gt 0 ]; do
  case "$1" in --profile | --region) shift 2 ;; *) args+=("$1"); shift ;; esac
done
set -- "${args[@]}"
# Like the real one, a --query the API's answer has no such path for is an error here.
query="" prev=""
for a in "$@"; do [ "$prev" = --query ] && query=$a; prev=$a; done
case "$query" in
  "" | "Reservations[0].Instances[0].State.Name" | "InstanceInformationList[0].PingStatus" | \
    "Command.CommandId" | "Status" | "[StandardOutputContent,StandardErrorContent]") ;;
  *) echo "fake aws: unknown --query $query" >&2; exit 252 ;;
esac
# The first line of a file, the last line kept for every later read. FAIL: signed out.
next() {
  [ -s "$1" ] || return 1
  line=$(head -n1 "$1")
  [ "$(wc -l <"$1")" -gt 1 ] && sed -i 1d "$1"
  [ "$line" != FAIL ] || exit 255
  echo "$line"
}
[ -e "$FAKE_DIR/signed_out" ] && exit 255
case "$1 $2" in
  "ec2 describe-instances") next "$FAKE_DIR/states" ;;
  "ec2 start-instances") [ ! -e "$FAKE_DIR/start_fails" ] || exit 254; echo started ;;
  "ec2 stop-instances") [ ! -e "$FAKE_DIR/stop_fails" ] || exit 255; echo stopping ;;
  "ssm describe-instance-information") next "$FAKE_DIR/ping" || echo Online ;;
  "ssm send-command")
    while [ $# -gt 0 ]; do
      [ "$1" = --parameters ] && printf '%s' "$2" >"$FAKE_DIR/params"; shift
    done
    echo 11111111-2222-3333-4444-555555555555 ;;
  "ssm get-command-invocation")
    case "$*" in
      *"--query Status"*)
        next "$FAKE_DIR/invocation" || echo InProgress ;;
      *) printf 'box-rebuild: rebuild job 7 ended failed\tsome stderr\n' ;;
    esac ;;
  "s3 ls")
    [ ! -e "$FAKE_DIR/s3_denied" ] || exit 255
    case "$3" in
      */failed/)
        [ -e "$FAKE_DIR/failed_log" ] || exit 1
        echo "2026-10-16 10:00:00       2048 box-rebuild-20261016T100000Z.log.gz"
        echo "2026-10-16 10:00:00       4096 rebuild-20261016T100000Z.log.gz"
        exit 0 ;;
    esac
    n=$(cat "$FAKE_DIR/result_after" 2>/dev/null || echo 99)
    echo $((n - 1)) >"$FAKE_DIR/result_after"
    [ "$n" -le 0 ] ;;
  "s3 cp")
    case "$3" in
      */failed/rebuild-*) gzip -c "$FAKE_DIR/failed_log" ;;
      *) cat "$FAKE_DIR/manifest" 2>/dev/null ;;
    esac ;;
  *) exit 1 ;;
esac
"""

FAKE_SCRIPT = r"""#!/usr/bin/env bash
region=${AWS_DEFAULT_REGION:-}
[ "${AWS_REGION:-}" = "$region" ] || region="AWS_REGION=${AWS_REGION:-} differs"
printf '%s region=%s %s\n' "$(basename "$0")" "$region" "$*" >>"$FAKE_DIR/calls.log"
[ ! -e "$FAKE_DIR/$(basename "$0").fails" ]
"""


@pytest.fixture
def fake(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("aws", FAKE_AWS),
        ("send-inputs.sh", FAKE_SCRIPT),
        ("import-result.sh", FAKE_SCRIPT),
    ):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
    state = tmp_path / "fake"
    state.mkdir()
    (state / "manifest").write_text(f"run=cloud-20261012\ncommit={COMMIT}\n")
    # The check before sending, the check before starting, then starting
    (state / "states").write_text("stopped\nstopped\npending\nrunning\n")
    (state / "result_after").write_text("3")  # the check before the run, then two polls
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "FAKE_DIR": str(state),
        "CLOUD_AWS": str(bin_dir / "aws"),
        "CLOUD_SEND": str(bin_dir / "send-inputs.sh"),
        "CLOUD_IMPORT": str(bin_dir / "import-result.sh"),
        "CLOUD_INSTANCE_ID": INSTANCE,
        "CLOUD_LAUNCH_POLL_S": "0",
        "CLOUD_LAUNCH_START_POLL_S": "0",
        "CLOUD_LAUNCH_START_WAIT_S": "5",
        # Baked into the box's script: where the run marker goes on the "box".
        "CLOUD_LAUNCH_MARKER": str(tmp_path / "box-state" / "current"),
    }
    for key in (
        "CLOUD_BUCKET",
        "CLOUD_PREFIX",
        "CLOUD_PROFILE",
        "CLOUD_BOX_REGION",
        "CLOUD_BUCKET_REGION",
        "CLOUD_LAUNCH_TIMEOUT_S",
    ):
        env.pop(key, None)

    class Fake:
        root = tmp_path
        dir = state
        bin = bin_dir
        environ = env

        def run(self, *args: str, **more: str):
            return subprocess.run(
                ["bash", str(LAUNCH), *args],
                env={**env, **more},
                cwd=tmp_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

        def calls(self) -> list[str]:
            log = state / "calls.log"
            return log.read_text().splitlines() if log.exists() else []

        def called(self, text: str) -> list[str]:
            return [line for line in self.calls() if text in line]

        def box_scripts(self) -> tuple[str, str]:
            params = json.loads((state / "params").read_text())
            (command,) = params["commands"]
            b64 = re.fullmatch(
                r"echo ([A-Za-z0-9+/=]+) \| base64 -d >/tmp/rm-root.sh && bash /tmp/rm-root.sh",
                command,
            ).group(1)
            root = base64.b64decode(b64).decode()
            inner = re.search(r"^ubuntu_b64=([A-Za-z0-9+/=]+) ", root, re.M).group(1)
            return root, base64.b64decode(inner).decode()

    return Fake()


def position(calls: list[str], text: str) -> int:
    return next(i for i, line in enumerate(calls) if text in line)


def test_a_run_sends_starts_rebuilds_waits_stops_and_installs_without_swapping(fake) -> None:
    done = fake.run(URL)

    assert done.returncode == 0, done.stdout + done.stderr
    calls = fake.calls()
    order = [
        "ec2 describe-instances",
        "s3 ls " + URL + "/out/SHA256SUMS",
        "send-inputs.sh region=us-west-2 " + URL,
        "s3 cp " + URL + "/in/MANIFEST.txt -",
        "ec2 start-instances --instance-ids " + INSTANCE,
        "ssm describe-instance-information",
        "ssm send-command",
        "ec2 stop-instances --instance-ids " + INSTANCE,
        "import-result.sh region=us-west-2 " + URL,
    ]
    positions = [position(calls, step) for step in order]
    assert positions == sorted(positions), "\n".join(calls)
    assert not fake.called("--swap"), "staging only unless --swap"
    for line in calls:
        if line.startswith(("aws ec2", "aws ssm")) or " ec2 " in line or " ssm " in line:
            assert "--region us-east-1" in line, line
        if " s3 " in line:
            assert "--region us-west-2" in line, line
    assert len(fake.called("stop-instances")) == 1
    assert "terminate" not in "\n".join(calls)
    params = json.loads((fake.dir / "params").read_text())
    assert params["executionTimeout"] == [str(31 * 3600)]
    assert "scripts/cloud/import-result.sh --swap " + URL in done.stdout


def test_the_box_script_sets_up_once_checks_out_the_commit_and_runs_box_rebuild(fake) -> None:
    assert fake.run(URL, "--beta", "--refire").returncode == 0
    root, ubuntu = fake.box_scripts()

    assert "snap install aws-cli --classic" in root
    assert "sudo -iu ubuntu bash" in root
    assert f"commit={COMMIT}" in ubuntu and f"run_url={URL}" in ubuntu
    assert 'git clone --quiet "$repo_url" RouteMaker' in ubuntu
    assert "box_args=(--refire --beta-bundle )" in ubuntu
    assert "bucket_region=us-west-2" in ubuntu
    for script in (root, ubuntu):
        assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0


def test_the_box_script_runs_with_its_one_time_setup(fake) -> None:
    """Run the two scripts as the box would, with stand-ins for snap, sudo and git."""
    assert fake.run(URL).returncode == 0
    root, _ = fake.box_scripts()
    box_bin = fake.root / "box-bin"
    box_bin.mkdir()
    log = fake.dir / "box.log"
    stubs = {
        # The install puts an `aws` beside it, whose `s3 ls` finds a result when $RESULT is set.
        "snap": (
            'echo "snap $*" >>"$LOG"\n'
            'printf \'#!/usr/bin/env bash\\necho "aws $*" >>"$LOG"\\n[ -n "$RESULT" ]\\n\' '
            '>"$(dirname "$0")/aws"; chmod +x "$(dirname "$0")/aws"'
        ),
        "shutdown": 'echo "shutdown $*" >>"$LOG"',
        # sudo -iu ubuntu CMD...: the command, as "ubuntu", in its home
        "sudo": 'echo "sudo $*" >>"$LOG"; shift 2; cd "$HOME"; exec "$@"',
        "git": (
            'echo "git $*" >>"$LOG"\n'
            'if [ "$1" = clone ]; then mkdir -p "$4/.git" "$4/scripts/cloud"; '
            'printf \'#!/bin/sh\\necho "box-rebuild $*" >>"$LOG"\\necho rebuilt\\n\' '
            '>"$4/scripts/cloud/box-rebuild.sh"; chmod +x "$4/scripts/cloud/box-rebuild.sh"; fi'
        ),
    }
    for name, body in stubs.items():
        (box_bin / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (box_bin / name).chmod(0o755)
    # Only the stand-ins and the basic tools: no aws, so the one-time install runs.
    tools = fake.root / "tools"
    tools.mkdir()
    (fake.root / "ubuntu").mkdir()
    for tool in ("bash", "base64", "mktemp", "chmod", "tail", "cat", "mkdir", "dirname", "cut"):
        found = shutil.which(tool)
        if found:
            (tools / tool).symlink_to(found)
    box_env = {"PATH": f"{box_bin}:{tools}", "HOME": str(fake.root / "ubuntu"), "LOG": str(log)}

    def on_the_box(**more: str):
        return subprocess.run(
            ["bash"],
            input=root,
            env={**box_env, **more},
            capture_output=True,
            text=True,
            timeout=30,
        )

    done = on_the_box(RESULT="")
    assert done.returncode == 0, done.stdout + done.stderr
    steps = log.read_text().splitlines()
    assert steps[0] == f"shutdown -P +{31 * 60} RouteMaker launch: the command's time is up"
    assert steps[1] == "snap install aws-cli --classic"
    assert steps[2].startswith("sudo -iu ubuntu bash /tmp/routemaker-launch.")
    assert steps[3] == f"aws s3 ls {URL}/out/SHA256SUMS"
    assert any(s.startswith("git clone --quiet https://github.com/") for s in steps)
    assert f"git checkout --quiet --detach {COMMIT}" in steps
    assert steps[-1] == f"box-rebuild {URL}"
    assert "box-rebuild.sh exited 0" in done.stdout and "rebuilt" in done.stdout
    marker = fake.root / "box-state" / "current"
    launched, named = marker.read_text().split()
    assert named == URL and launched.isdigit()

    # SSM running the command again after a restart: the result is there, so nothing runs.
    log.write_text("")
    again = on_the_box(RESULT="1")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "already has its result" in again.stdout
    steps = log.read_text().splitlines()
    assert "snap install aws-cli --classic" not in steps, "installed the first time"
    assert not [s for s in steps if s.startswith(("git ", "box-rebuild"))]

    # A newer launch (another run) owns the box: this older command, run again, does
    # nothing, and leaves the newer launch's marker as it is.
    other = "s3://bucket/rebuild-checkpoints/transfer/cloud-20261019"
    marker.write_text(f"{int(launched) + 3600} {other}\n")
    log.write_text("")
    older = on_the_box(RESULT="")
    assert older.returncode == 0, older.stdout + older.stderr
    assert "a newer launch" in older.stdout
    assert log.read_text() == "", "not even the power-off is scheduled"
    assert marker.read_text() == f"{int(launched) + 3600} {other}\n"

    # The ubuntu half checks the marker too: one naming another run means nothing to do.
    _, ubuntu = fake.box_scripts()
    marker.write_text(f"{launched} {other}\n")
    log.write_text("")
    for name in ("aws",):
        (box_bin / name).write_text('#!/usr/bin/env bash\necho "aws $*" >>"$LOG"\nexit 1\n')
    half = subprocess.run(
        ["bash"], input=ubuntu, env={**box_env}, capture_output=True, text=True, timeout=30
    )
    assert half.returncode == 0, half.stdout + half.stderr
    assert f"the box is on {other}, not {URL}" in half.stdout
    assert log.read_text() == "", "no clone, no box-rebuild.sh, no power-off at its end"


def test_swap_installs_then_swaps(fake) -> None:
    assert fake.run(URL, "--swap", "--profile", "home").returncode == 0
    imports = fake.called("import-result.sh")
    assert imports == [
        f"import-result.sh region=us-west-2 --profile home {URL}",
        f"import-result.sh region=us-west-2 --profile home --swap {URL}",
    ]
    assert all("--profile home" in line for line in fake.called("aws "))


def test_the_run_url_is_made_from_bucket_prefix_and_run(fake) -> None:
    done = fake.run(
        "--bucket",
        "my-bucket",
        "--prefix",
        "/x/y/",
        "--run",
        "cloud-test",
        CLOUD_BOX_REGION="eu-west-1",
        CLOUD_BUCKET_REGION="eu-central-1",
    )
    assert done.returncode == 0, done.stderr
    assert fake.called("send-inputs.sh region=eu-central-1 s3://my-bucket/x/y/cloud-test")
    assert all("--region eu-west-1" in line for line in fake.called(" ec2 "))


def test_a_failed_command_says_so_shows_the_box_and_stops_it(fake) -> None:
    (fake.dir / "invocation").write_text("InProgress\nFailed\n")
    (fake.dir / "result_after").write_text("99")

    done = fake.run(URL)

    assert done.returncode == 1
    assert "ended Failed" in done.stderr
    assert "box | box-rebuild: rebuild job 7 ended failed" in done.stderr
    assert "--no-send" in done.stderr
    assert len(fake.called("stop-instances")) == 1
    assert not fake.called("import-result.sh")
    assert "no log reached" in done.stderr


def test_a_failed_rebuild_names_its_uploaded_log_and_shows_its_end(fake) -> None:
    """The log is in RUN_URL/failed/, read from home without starting the box again."""
    (fake.dir / "states").write_text("stopped\nstopped\nrunning\nrunning\nstopped\n")
    (fake.dir / "result_after").write_text("99")
    (fake.dir / "failed_log").write_text("step one\nTraceback: valhalla_build_tiles died\n")

    done = fake.run(URL)

    assert done.returncode == 1
    assert f"{URL}/failed/rebuild-20261016T100000Z.log.gz" in done.stderr
    assert "log | Traceback: valhalla_build_tiles died" in done.stderr
    assert len(fake.called("stop-instances")) == 1


def test_a_box_that_stops_with_no_result_ends_the_wait_and_is_stopped_once_more(fake) -> None:
    """A spot reclaim stops the box too; a stop of ours keeps the request from restarting it."""
    (fake.dir / "states").write_text("stopped\nstopped\nrunning\nrunning\nstopped\n")
    (fake.dir / "result_after").write_text("99")

    done = fake.run(URL)

    assert done.returncode == 1
    assert "stopped with no result" in done.stderr
    assert f"scripts/cloud/launch.sh --no-send {URL}" in done.stderr
    assert f"scripts/cloud/launch.sh --no-send --refire {URL}" in done.stderr
    assert len(fake.called("stop-instances")) == 1
    assert not fake.called("import-result.sh")


def test_a_sign_in_that_runs_out_while_waiting_is_reported_and_waited_through(fake) -> None:
    (fake.dir / "invocation").write_text("FAIL\nFAIL\nFAIL\nInProgress\n")
    (fake.dir / "result_after").write_text("6")

    done = fake.run(URL)

    assert done.returncode == 0, done.stderr
    assert done.stdout.count("AWS calls are failing") == 1
    assert "aws login --remote" in done.stdout
    assert fake.called("import-result.sh")


def test_a_run_that_already_has_a_result_is_refused_before_anything(fake) -> None:
    (fake.dir / "result_after").write_text("0")

    done = fake.run(URL)

    assert done.returncode == 2 and "already has a result" in done.stderr
    assert not fake.called("send-inputs.sh") and not fake.called("start-instances")


def test_a_running_box_is_refused_and_left_alone(fake) -> None:
    (fake.dir / "states").write_text("running\n")

    done = fake.run(URL)

    assert done.returncode == 2 and "--use-running" in done.stderr
    assert not fake.called("send-inputs.sh"), "refused before the sudo prompt and the upload"
    assert not fake.called("send-command") and not fake.called("stop-instances")


def test_use_running_uses_the_box_and_leaves_it_running(fake) -> None:
    (fake.dir / "states").write_text("running\n")

    done = fake.run(URL, "--use-running")

    assert done.returncode == 0, done.stderr
    assert fake.called("send-command")
    assert not fake.called("start-instances") and not fake.called("stop-instances")


def test_a_failed_send_starts_nothing(fake) -> None:
    (fake.dir / "send-inputs.sh.fails").touch()

    done = fake.run(URL)

    assert done.returncode == 1 and "send-inputs.sh failed" in done.stderr
    assert not fake.called("start-instances")


def test_no_send_carries_on_the_inputs_already_sent(fake) -> None:
    done = fake.run(URL, "--no-send", "--allow-dirty")

    assert done.returncode == 0, done.stderr
    assert not fake.called("send-inputs.sh")
    assert fake.called("send-command")


def test_no_manifest_is_refused_before_the_box_starts(fake) -> None:
    (fake.dir / "manifest").unlink()

    done = fake.run(URL, "--no-send")

    assert done.returncode == 2 and "MANIFEST.txt" in done.stderr
    assert not fake.called("start-instances")


def test_a_start_aws_refuses_is_reported(fake) -> None:
    (fake.dir / "start_fails").touch()

    done = fake.run(URL)

    assert done.returncode == 1 and "did not start" in done.stderr
    assert not fake.called("send-command")


def test_waiting_too_long_gives_up_and_stops_the_box(fake) -> None:
    (fake.dir / "result_after").write_text("99")

    done = fake.run(URL, CLOUD_LAUNCH_TIMEOUT_S="0")

    assert done.returncode == 1 and "no result after" in done.stderr
    assert len(fake.called("stop-instances")) == 1


def test_a_failed_import_is_reported_after_the_box_is_stopped(fake) -> None:
    (fake.dir / "import-result.sh.fails").touch()

    done = fake.run(URL, "--swap")

    assert done.returncode == 1 and "import-result.sh failed" in done.stderr
    calls = fake.calls()
    assert position(calls, "stop-instances") < position(calls, "import-result.sh")
    assert len(fake.called("import-result.sh")) == 1, "no swap after a failed install"


def test_the_resume_hint_names_the_run_even_with_the_default_name(fake) -> None:
    (fake.dir / "invocation").write_text("Failed\n")
    (fake.dir / "result_after").write_text("99")

    done = fake.run("--bucket", "my-bucket", "--profile", "home", "--beta")

    assert done.returncode == 1
    url = re.search(r"run (cloud-\d{8}) at (s3://\S+);", done.stdout).group(2)
    assert url.startswith("s3://my-bucket/rebuild-checkpoints/transfer/cloud-")
    assert f"scripts/cloud/launch.sh --no-send --profile home --beta {url}" in done.stderr
    assert f"--refire {url}" in done.stderr


def test_the_resume_hint_keeps_the_options_given(fake) -> None:
    (fake.dir / "invocation").write_text("Failed\n")
    (fake.dir / "result_after").write_text("99")
    live = fake.root / "my live"

    done = fake.run(
        "--instance-id", "i-0fedcba9876543210", "--box-region", "eu-west-1",
        "--bucket-region", "eu-central-1", "--bucket", "my-bucket", "--prefix", "p",
        "--run", "cloud-test", "--live-dir", str(live), "--repo-url",
        "https://example.org/fork.git", "--timeout-hours", "12", "--swap", "--refire",
    )  # fmt: skip

    assert done.returncode == 1
    hint = (
        "scripts/cloud/launch.sh --no-send --instance-id i-0fedcba9876543210"
        " --box-region eu-west-1 --bucket-region eu-central-1"
        f" --live-dir '{live}' --repo-url https://example.org/fork.git"
        " --timeout-hours 12 --swap s3://my-bucket/p/cloud-test"
    )
    assert hint in done.stderr, done.stderr
    assert hint.replace(" s3://", " --refire s3://") in done.stderr


def test_a_reclaimed_box_it_did_not_start_is_not_stopped(fake) -> None:
    (fake.dir / "states").write_text("running\nrunning\nrunning\nstopped\n")
    (fake.dir / "result_after").write_text("99")

    done = fake.run(URL, "--use-running")

    assert done.returncode == 1 and "stopped with no result" in done.stderr
    assert not fake.called("stop-instances")


def test_success_with_no_result_is_a_failure_with_the_resume_hint(fake) -> None:
    (fake.dir / "invocation").write_text("InProgress\nSuccess\n")
    (fake.dir / "result_after").write_text("99")

    done = fake.run(URL)

    assert done.returncode == 1 and "has no SHA256SUMS" in done.stderr
    assert f"--no-send {URL}" in done.stderr
    assert len(fake.called("stop-instances")) == 1
    assert not fake.called("import-result.sh")


def test_a_box_still_stopping_at_launch_is_waited_for_then_started(fake) -> None:
    (fake.dir / "states").write_text("stopping\nstopping\nstopping\nstopped\npending\nrunning\n")

    done = fake.run(URL)

    assert done.returncode == 0, done.stderr
    assert "waiting for it to stop" in done.stdout
    calls = fake.calls()
    assert position(calls, "send-inputs.sh") < position(calls, "start-instances")
    assert len(fake.called("start-instances")) == 1


def test_a_box_that_cannot_be_described_fails_before_anything_is_sent(fake) -> None:
    (fake.dir / "states").write_text("FAIL\n")

    done = fake.run(URL)

    assert done.returncode == 2 and "cannot describe" in done.stderr
    assert "aws login --remote" in done.stderr
    assert not fake.called("send-inputs.sh") and not fake.called("start-instances")


def test_a_bucket_that_cannot_be_read_fails_before_anything_is_sent(fake) -> None:
    (fake.dir / "s3_denied").touch()

    done = fake.run(URL)

    assert done.returncode == 2 and "cannot read" in done.stderr
    assert not fake.called("send-inputs.sh") and not fake.called("start-instances")


def test_the_child_scripts_get_both_region_variables(fake) -> None:
    done = fake.run(URL, AWS_REGION="eu-west-3")

    assert done.returncode == 0, done.stderr
    assert fake.called("send-inputs.sh region=us-west-2 ")
    assert fake.called("import-result.sh region=us-west-2 ")


def test_a_stop_when_signed_out_still_tries_and_says_so(fake) -> None:
    (fake.dir / "states").write_text("stopped\nstopped\nrunning\nFAIL\n")
    (fake.dir / "result_after").write_text("99")
    (fake.dir / "stop_fails").touch()

    done = fake.run(URL, CLOUD_LAUNCH_TIMEOUT_S="0")

    assert done.returncode == 1 and "no result after" in done.stderr
    assert len(fake.called("stop-instances")) == 1, "tried even with the state unknown"
    assert "could not stop" in done.stdout and "console" in done.stdout


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["INT", "TERM"])
def test_an_interrupted_wait_stops_the_box(fake, sig) -> None:
    (fake.dir / "result_after").write_text("9999")
    proc = subprocess.Popen(
        ["bash", str(LAUNCH), URL],
        env={**fake.environ, "CLOUD_LAUNCH_POLL_S": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if fake.called("get-command-invocation"):
                break
            time.sleep(0.1)
        proc.send_signal(sig)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode != 0
    assert len(fake.called("stop-instances")) == 1


def test_attach_only_waits_for_the_run_on_the_box_then_stops_it_and_installs(fake) -> None:
    (fake.dir / "states").write_text("running\n")

    done = fake.run("--attach", URL)

    assert done.returncode == 0, done.stdout + done.stderr
    assert not fake.called("send-inputs.sh") and not fake.called("start-instances")
    assert not fake.called("send-command") and not fake.called("get-command-invocation")
    calls = fake.calls()
    assert position(calls, "stop-instances") < position(calls, "import-result.sh")
    assert len(fake.called("stop-instances")) == 1


def test_attach_to_a_box_that_is_not_running_is_refused(fake) -> None:
    (fake.dir / "states").write_text("stopped\n")

    done = fake.run("--attach", URL)

    assert done.returncode == 2 and "nothing to attach to" in done.stderr
    assert "--no-send" in done.stderr and URL in done.stderr
    assert not fake.called("start-instances") and not fake.called("stop-instances")


def test_an_interrupted_attach_leaves_the_rebuild_running(fake) -> None:
    (fake.dir / "states").write_text("running\n")
    (fake.dir / "result_after").write_text("9999")
    proc = subprocess.Popen(
        ["bash", str(LAUNCH), "--attach", URL],
        env={**fake.environ, "CLOUD_LAUNCH_POLL_S": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            if len(fake.called("describe-instances")) >= 2:
                break
            time.sleep(0.1)
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode != 0
    assert not fake.called("stop-instances"), "the box is still rebuilding"


def test_dry_run_prints_the_calls_and_runs_none(fake) -> None:
    done = fake.run(URL, "--dry-run", "--swap", "--beta")

    assert done.returncode == 0, done.stderr
    assert fake.calls() == [], "nothing is run"
    out = done.stdout
    for call in (
        f"aws --region us-east-1 ec2 start-instances --instance-ids {INSTANCE}",
        "ssm send-command",
        "AWS-RunShellScript",
        f"s3 ls {URL}/out/SHA256SUMS",
        f"aws --region us-east-1 ec2 stop-instances --instance-ids {INSTANCE}",
        f"import-result.sh --swap {URL}",
        "snap install aws-cli --classic",
        "box_args=(--beta-bundle )",
    ):
        assert call in out, call


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--instance-id", "box1", URL], "--instance-id must look like"),
        (["--box-region", "useast", URL], "region name"),
        ([], "--bucket"),
        (["s3://bucket/x/Cloud_Run"], "lowercase"),
        (["--timeout-hours", "48", URL], "--timeout-hours"),
    ],
)
def test_bad_options_are_refused(fake, args, message) -> None:
    done = fake.run(*args)

    assert done.returncode == 2 and message in done.stderr
    assert fake.calls() == []


def test_without_an_instance_it_is_refused(fake) -> None:
    done = fake.run(URL, CLOUD_INSTANCE_ID="")

    assert done.returncode == 2 and "--instance-id" in done.stderr


def test_the_launcher_names_no_account_instance_or_bucket() -> None:
    text = LAUNCH.read_text().replace("i-0123456789abcdef0", "i-<example>")  # AWS's own example
    assert not re.search(r"\b\d{12}\b", text), "no account id"
    assert not re.search(r"\bi-[0-9a-f]{17}\b", text), "no real instance id"


def test_the_launcher_parses_and_shellcheck_is_clean_when_available() -> None:
    assert subprocess.run(["bash", "-n", str(LAUNCH)]).returncode == 0
    if shutil.which("shellcheck"):
        done = subprocess.run(
            ["shellcheck", "--severity=warning", str(LAUNCH)], capture_output=True, text=True
        )
        assert done.returncode == 0, done.stdout
