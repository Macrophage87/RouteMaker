#!/usr/bin/env bash
# Runs a whole cloud rebuild from home with one command: sends the inputs, starts the box,
# runs the rebuild on it through Session Manager, waits for the result, stops the box and
# installs the result here (staging only, unless --swap). Run at home, from the live
# stack's checkout. It drives the other three scripts and adds nothing to them:
# docs/OPERATIONS.md, "Rebuilding on the cloud box" and "The launcher".
#
#   scripts/cloud/launch.sh [options] [RUN_URL]
#
#   RUN_URL   s3://<bucket>/<prefix>/<run>; without it, the run's folder is made from
#             --bucket, --prefix and --run. Nothing in the repository names the bucket,
#             the account or the instance: they come from the options or the environment.
#
# Steps:
#   1. refuses a run that already has a result (RUN_URL/out/SHA256SUMS), then
#      send-inputs.sh (skipped with --no-send, to carry on a run whose inputs are sent)
#   2. reads the commit from RUN_URL/in/MANIFEST.txt
#   3. `aws ec2 start-instances` on the box, if it is stopped, and waits until it is
#      running and its SSM agent is online
#   4. `aws ssm send-command` (AWS-RunShellScript): on the box, as root, installs the AWS
#      CLI if it is missing (snap), then as ubuntu clones the repository to ~/RouteMaker if
#      it is missing, checks out the run's commit there and runs box-rebuild.sh from it,
#      its output appended to ~/cloud-rebuild.log on the box
#   5. waits for RUN_URL/out/SHA256SUMS (box-rebuild.sh uploads it last), watching the
#      command (get-command-invocation) and the box: a failed command, or a box that stops
#      with no result (a failed rebuild powers itself off; so does a spot reclaim), ends
#      the wait with the reason and the last lines of the box's output
#   6. stops the box, then import-result.sh: install and its dry run; with --swap, the
#      swap after it
# However it ends, a box this script started and that is still running is stopped (never
# terminated): its disk keeps the run's state, and the same command with --no-send carries
# on where it stopped (add --refire after a failed rebuild).
#
# Options:
#   --instance-id ID     the box [$CLOUD_INSTANCE_ID]
#   --box-region R       the box's region [$CLOUD_BOX_REGION, or us-east-1]
#   --bucket-region R    the bucket's region [$CLOUD_BUCKET_REGION, or us-west-2]
#   --bucket NAME        [$CLOUD_BUCKET]
#   --prefix P           the transfer folder in the bucket
#                        [$CLOUD_PREFIX, or rebuild-checkpoints/transfer]
#   --run NAME           the run's name [cloud-<today, UTC>]
#   --profile NAME       the AWS CLI profile [$CLOUD_PROFILE] (`aws login --remote` first)
#   --live-dir DIR       the live stack's checkout, for send-inputs.sh and import-result.sh
#   --repo-url URL       the box's clone of the repository
#                        [https://github.com/Macrophage87/RouteMaker.git]
#   --allow-dirty        passed to send-inputs.sh
#   --no-send            the inputs are in RUN_URL/in/ already; carry that run on
#   --refire             passed to box-rebuild.sh: fire a new job after a failed one
#   --beta               passed to box-rebuild.sh as --beta-bundle (the beta server's bundle;
#                        install it there with import-result.sh --beta)
#   --swap               after the install and its dry run, swap (import-result.sh --swap)
#   --use-running        use a box that is already running (and leave it running)
#   --timeout-hours N    give up waiting for the result after N hours [30]
#   --dry-run            print the commands and the box's script, run nothing
#   -h, --help
# Environment (for tests): CLOUD_AWS [aws], CLOUD_SEND, CLOUD_IMPORT [the scripts beside
# this one], CLOUD_LAUNCH_POLL_S [60], CLOUD_LAUNCH_START_POLL_S [10],
# CLOUD_LAUNCH_START_WAIT_S [900], CLOUD_LAUNCH_TIMEOUT_S [--timeout-hours in seconds].
set -Eeuo pipefail

die() { echo "launch: $*" >&2; exit 2; }
note() { echo "launch: $(date -u +%H:%M:%SZ) $*"; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
instance=${CLOUD_INSTANCE_ID:-}
box_region=${CLOUD_BOX_REGION:-us-east-1}
bucket_region=${CLOUD_BUCKET_REGION:-us-west-2}
bucket=${CLOUD_BUCKET:-}
prefix=${CLOUD_PREFIX:-rebuild-checkpoints/transfer}
profile=${CLOUD_PROFILE:-}
repo_url=https://github.com/Macrophage87/RouteMaker.git
run="" url="" live_dir="" allow_dirty=0 send=1 refire=0 beta=0 swap=0 use_running=0
timeout_hours=30 dry_run=0
while [ $# -gt 0 ]; do
	case "$1" in
		--instance-id) [ $# -ge 2 ] || die "$1 needs a value"; instance=$2; shift 2 ;;
		--box-region) [ $# -ge 2 ] || die "$1 needs a value"; box_region=$2; shift 2 ;;
		--bucket-region) [ $# -ge 2 ] || die "$1 needs a value"; bucket_region=$2; shift 2 ;;
		--bucket) [ $# -ge 2 ] || die "$1 needs a value"; bucket=$2; shift 2 ;;
		--prefix) [ $# -ge 2 ] || die "$1 needs a value"; prefix=$2; shift 2 ;;
		--run) [ $# -ge 2 ] || die "$1 needs a value"; run=$2; shift 2 ;;
		--profile) [ $# -ge 2 ] || die "$1 needs a value"; profile=$2; shift 2 ;;
		--live-dir) [ $# -ge 2 ] || die "$1 needs a value"; live_dir=$2; shift 2 ;;
		--repo-url) [ $# -ge 2 ] || die "$1 needs a value"; repo_url=$2; shift 2 ;;
		--timeout-hours) [ $# -ge 2 ] || die "$1 needs a value"; timeout_hours=$2; shift 2 ;;
		--allow-dirty) allow_dirty=1; shift ;;
		--no-send) send=0; shift ;;
		--refire) refire=1; shift ;;
		--beta) beta=1; shift ;;
		--swap) swap=1; shift ;;
		--use-running) use_running=1; shift ;;
		--dry-run) dry_run=1; shift ;;
		-h | --help) sed -n '2,/^set -E/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) [ -z "$url" ] || die "one RUN_URL only"; url=$1; shift ;;
	esac
done

if [ -z "$url" ]; then
	[ -n "$bucket" ] || die "give RUN_URL, or --bucket (or CLOUD_BUCKET) for the run's folder"
	prefix=${prefix#/}; prefix=${prefix%/}
	url="s3://$bucket/${prefix:+$prefix/}${run:-cloud-$(date -u +%Y%m%d)}"
fi
url=${url%/}
case "$url" in s3://?*/?*) ;; *) die "RUN_URL must be s3://<bucket>/.../<run>, not $url" ;; esac
run=${url##*/}
[[ "$run" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || die "the run name '$run' must be lowercase letters, digits and hyphens"
[[ "$url" =~ ^s3://[a-z0-9.-]+/[A-Za-z0-9._/-]+$ ]] || die "RUN_URL has a character it should not: $url"
[ -n "$instance" ] || die "no box: give --instance-id (or CLOUD_INSTANCE_ID)"
[[ "$instance" =~ ^i-[0-9a-f]{8,17}$ ]] || die "--instance-id must look like i-0123456789abcdef0, not $instance"
for r in "$box_region" "$bucket_region"; do
	[[ "$r" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]] || die "'$r' is not a region name like us-east-1"
done
[[ "$timeout_hours" =~ ^[1-9][0-9]?$ ]] && [ "$timeout_hours" -le 47 ] ||
	die "--timeout-hours must be a whole number from 1 to 47"
[[ "$repo_url" =~ ^https://[A-Za-z0-9._/-]+$ ]] || die "--repo-url must be an https URL"

AWS=${CLOUD_AWS:-aws}
SEND=${CLOUD_SEND:-$here/send-inputs.sh}
IMPORT=${CLOUD_IMPORT:-$here/import-result.sh}
POLL_S=${CLOUD_LAUNCH_POLL_S:-60}
START_POLL_S=${CLOUD_LAUNCH_START_POLL_S:-10}
START_WAIT_S=${CLOUD_LAUNCH_START_WAIT_S:-900}
TIMEOUT_S=${CLOUD_LAUNCH_TIMEOUT_S:-$((timeout_hours * 3600))}
# The command may run a little longer than the launcher waits; SSM allows 48 hours at most.
exec_timeout=$((timeout_hours * 3600 + 3600))

common=()
[ -z "$profile" ] || common+=(--profile "$profile")
passed=()
[ -z "$profile" ] || passed+=(--profile "$profile")
[ -z "$live_dir" ] || passed+=(--live-dir "$live_dir")

# Every AWS call goes through here: printed (and not run) with --dry-run. The box's own
# region for EC2 and SSM; S3 in the bucket's region.
show() {
	local a line=""
	for a in "$@"; do
		if [[ "$a" =~ ^[A-Za-z0-9_./:=@,+-]+$ ]]; then line+=" $a"; else line+=" '${a//\'/\'\\\'\'}'"; fi
	done
	echo " $line"
}
aws_box() {
	if [ "$dry_run" = 1 ]; then show aws "${common[@]}" --region "$box_region" "$@"; return 0; fi
	"$AWS" "${common[@]}" --region "$box_region" "$@"
}
aws_s3() {
	if [ "$dry_run" = 1 ]; then show aws "${common[@]}" --region "$bucket_region" s3 "$@"; return 0; fi
	"$AWS" "${common[@]}" --region "$bucket_region" s3 "$@"
}
# The other scripts call `aws` without a region; theirs is the bucket's.
script() {
	if [ "$dry_run" = 1 ]; then show AWS_DEFAULT_REGION="$bucket_region" "$@"; return 0; fi
	AWS_DEFAULT_REGION=$bucket_region "$@"
}
box_state() { aws_box ec2 describe-instances --instance-ids "$instance" \
	--query 'Reservations[0].Instances[0].State.Name' --output text; }

# --- the box's script --------------------------------------------------------------------
# Runs as root through AWS-RunShellScript. The values are fixed here and checked above;
# the script travels base64-encoded, so no quoting survives the trip through JSON.
box_args=()
[ "$refire" = 0 ] || box_args+=(--refire)
[ "$beta" = 0 ] || box_args+=(--beta-bundle)
ubuntu_script() {
	printf 'run_url=%q commit=%q repo_url=%q bucket_region=%q\n' "$url" "$1" "$repo_url" "$bucket_region"
	printf 'box_args=('
	[ "${#box_args[@]}" = 0 ] || printf '%q ' "${box_args[@]}"
	printf ')\n'
	cat <<'EOF'
set -euo pipefail
export PATH="$PATH:/snap/bin" AWS_DEFAULT_REGION="$bucket_region"
cd "$HOME"
if [ ! -d RouteMaker/.git ]; then
	echo "launch: cloning $repo_url into ~/RouteMaker (one-time setup)"
	git clone --quiet "$repo_url" RouteMaker
fi
cd RouteMaker
git fetch --quiet --tags origin
git checkout --quiet --detach "$commit"
echo "launch: running scripts/cloud/box-rebuild.sh ${box_args[*]} $run_url at commit $commit; its log is ~/cloud-rebuild.log"
rc=0
scripts/cloud/box-rebuild.sh "${box_args[@]}" "$run_url" >>"$HOME/cloud-rebuild.log" 2>&1 </dev/null || rc=$?
echo "launch: box-rebuild.sh exited $rc; the end of ~/cloud-rebuild.log:"
tail -n 40 "$HOME/cloud-rebuild.log"
exit "$rc"
EOF
}
root_script() {
	printf 'ubuntu_b64=%q\n' "$(ubuntu_script "$1" | base64 | tr -d '\n')"
	cat <<'EOF'
set -euo pipefail
export PATH="$PATH:/snap/bin"
if ! command -v aws >/dev/null 2>&1; then
	echo "launch: installing the AWS CLI (one-time setup)"
	snap install aws-cli --classic
fi
f=$(mktemp /tmp/routemaker-launch.XXXXXX)
echo "$ubuntu_b64" | base64 -d >"$f"
chmod 0644 "$f"
exec sudo -iu ubuntu bash "$f"
EOF
}

# --- the end, however it comes -----------------------------------------------------------
started=0 stopped=0
stop_box() {
	[ "$started" = 1 ] && [ "$stopped" = 0 ] || return 0
	stopped=1
	local s
	s=$(box_state 2>/dev/null) || s=unknown
	case "$s" in
		pending | running)
			note "stopping the box $instance (stop, never terminate; its disk keeps the run)"
			aws_box ec2 stop-instances --instance-ids "$instance" --output text >/dev/null ||
				note "WARNING: could not stop $instance; stop it in the console (EC2, Instances, Stop)" ;;
		stopping | stopped) note "the box $instance is $s" ;;
		*) note "WARNING: cannot tell whether $instance is running ($s); check the console and stop it" ;;
	esac
}
# shellcheck disable=SC2329 # invoked by the traps below
on_exit() {
	local rc=$?
	trap - EXIT
	stop_box
	exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
fail() { echo "launch: $*" >&2; exit 1; }

if [ "$dry_run" = 1 ]; then
	note "--dry-run: these are the commands, in order; nothing is run"
fi
note "run $run at $url; the box $instance in $box_region, the bucket in $bucket_region"

# --- 1. inputs ---------------------------------------------------------------------------
if [ "$dry_run" = 0 ] && aws_s3 ls "$url/out/SHA256SUMS" >/dev/null 2>&1; then
	die "$url already has a result. Install it with scripts/cloud/import-result.sh $url, or name a new run (--run)"
fi
[ "$dry_run" = 0 ] || aws_s3 ls "$url/out/SHA256SUMS"
if [ "$send" = 1 ]; then
	note "sending the inputs (send-inputs.sh)"
	sargs=("${passed[@]}")
	[ "$allow_dirty" = 0 ] || sargs+=(--allow-dirty)
	script "$SEND" "${sargs[@]}" "$url" || fail "send-inputs.sh failed; the box was not started"
else
	note "--no-send: using the inputs already in $url/in/"
fi

# --- 2. the commit -----------------------------------------------------------------------
if [ "$dry_run" = 1 ]; then
	aws_s3 cp "$url/in/MANIFEST.txt" -
	commit="<the commit in MANIFEST.txt>"
else
	manifest=$(aws_s3 cp "$url/in/MANIFEST.txt" - 2>/dev/null) ||
		die "$url/in/ has no MANIFEST.txt: send the inputs (drop --no-send)"
	commit=$(sed -n 's/^commit=//p' <<<"$manifest" | tail -n1)
	[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "$url/in/MANIFEST.txt names no commit"
	note "the box builds commit $commit"
fi

# --- 3. the box --------------------------------------------------------------------------
wait_for() { # what, seconds, test command...
	local what=$1 limit=$2 waited=0
	shift 2
	until "$@"; do
		[ "$waited" -lt "$limit" ] || fail "$what after $((limit / 60)) minutes; giving up"
		sleep "$START_POLL_S"
		waited=$((waited + START_POLL_S))
	done
}
is_stopped() { [ "$(box_state 2>/dev/null)" = stopped ]; }
is_running() { [ "$(box_state 2>/dev/null)" = running ]; }
ssm_online() {
	[ "$(aws_box ssm describe-instance-information \
		--filters "Key=InstanceIds,Values=$instance" \
		--query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null)" = Online ]
}
if [ "$dry_run" = 1 ]; then
	box_state
	aws_box ec2 start-instances --instance-ids "$instance"
	aws_box ssm describe-instance-information --filters "Key=InstanceIds,Values=$instance" \
		--query 'InstanceInformationList[0].PingStatus' --output text
else
	state=$(box_state) || die "cannot describe $instance in $box_region: signed in (aws login --remote)? the right --box-region?"
	if [ "$state" = stopping ]; then
		note "the box is stopping; waiting for it to stop before starting it"
		wait_for "the box did not stop" "$START_WAIT_S" is_stopped
		state=stopped
	fi
	case "$state" in
		stopped)
			note "starting the box $instance"
			trap '' INT
			aws_box ec2 start-instances --instance-ids "$instance" --output text >/dev/null ||
				fail "AWS did not start $instance (no spot room just now is the usual reason; try again later)"
			started=1
			trap 'exit 130' INT ;;
		pending | running)
			[ "$use_running" = 1 ] ||
				die "the box $instance is already $state: another run may be using it. Stop it, or pass --use-running (it is then left running)"
			note "--use-running: using the box as it is, and leaving it running" ;;
		*) die "the box $instance is $state; it cannot be started" ;;
	esac
	note "waiting for the box to run and for its SSM agent"
	wait_for "the box is not running" "$START_WAIT_S" is_running
	wait_for "the box's SSM agent is not online" "$START_WAIT_S" ssm_online
	note "the box is up"
fi

# --- 4. the rebuild ----------------------------------------------------------------------
b64=$(root_script "$commit" | base64 | tr -d '\n')
params="{\"commands\":[\"echo $b64 | base64 -d | bash\"],\"executionTimeout\":[\"$exec_timeout\"]}"
if [ "$dry_run" = 1 ]; then
	aws_box ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
		--comment "RouteMaker rebuild $run" --parameters "<the script below, base64>" \
		--query Command.CommandId --output text
	echo "  The box runs, as root:"
	root_script "$commit" | sed '/^ubuntu_b64=/d; s/^/    | /'
	echo "  and as ubuntu:"
	ubuntu_script "$commit" | sed 's/^/    | /'
	aws_box ssm get-command-invocation --command-id "<command-id>" --instance-id "$instance" \
		--query Status --output text
	aws_s3 ls "$url/out/SHA256SUMS"
	echo "  (every ${POLL_S}s, for at most $timeout_hours hours)"
	aws_box ec2 stop-instances --instance-ids "$instance"
	iargs=("${passed[@]}")
	script "$IMPORT" "${iargs[@]}" "$url"
	[ "$swap" = 0 ] || script "$IMPORT" "${iargs[@]}" --swap "$url"
	exit 0
fi
note "starting the rebuild on the box (box-rebuild.sh; hours)"
command_id=$(aws_box ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
	--comment "RouteMaker rebuild $run" --parameters "$params" \
	--query Command.CommandId --output text) || fail "ssm send-command failed"
[ -n "$command_id" ] && [ "$command_id" != None ] || fail "ssm send-command returned no command id"
note "command $command_id sent"

# --- 5. the wait -------------------------------------------------------------------------
box_output() {
	aws_box ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
		--query '[StandardOutputContent,StandardErrorContent]' --output text 2>/dev/null |
		tail -n 40 | sed 's/^/  box | /' || true
}
began=$(date +%s)
deadline=$((began + TIMEOUT_S))
last_report=$began
failing=0
while :; do
	if aws_s3 ls "$url/out/SHA256SUMS" >/dev/null 2>&1; then
		break
	fi
	status=$(aws_box ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
		--query Status --output text 2>/dev/null) || status=""
	state=$(box_state 2>/dev/null) || state=""
	if [ -z "$status" ] || [ -z "$state" ]; then
		# Usually a sign-in that ran out (a command just sent can also be unknown for a moment).
		# The box carries on regardless, and powers off at the end.
		failing=$((failing + 1))
		if [ "$failing" = 3 ] || [ $((failing % 10)) = 0 ]; then
			note "WARNING: AWS calls are failing (signed out? run \`aws login --remote${profile:+ --profile $profile}\` in another window); still waiting"
		fi
	else
		failing=0
	fi
	case "$status" in
		Failed | Cancelled | TimedOut | Cancelling)
			aws_s3 ls "$url/out/SHA256SUMS" >/dev/null 2>&1 && break
			echo "launch: the rebuild command ended $status on the box. Its output:" >&2
			box_output >&2
			fail "no result. Read ~/cloud-rebuild.log on the box (Session Manager); then this command again with --no-send (and --refire after a failed rebuild)" ;;
		Success)
			aws_s3 ls "$url/out/SHA256SUMS" >/dev/null 2>&1 && break
			box_output >&2
			fail "box-rebuild.sh finished but $url/out/ has no SHA256SUMS" ;;
	esac
	case "$state" in
		stopping | stopped | shutting-down | terminated)
			aws_s3 ls "$url/out/SHA256SUMS" >/dev/null 2>&1 && break
			box_output >&2
			fail "the box $state with no result: a failed rebuild (it powers itself off; its log is under ~/cloud-runs/$run/ on the box) or a spot reclaim. Then this command again with --no-send (add --refire after a failed rebuild)" ;;
	esac
	now=$(date +%s)
	[ "$now" -lt "$deadline" ] ||
		fail "no result after $((TIMEOUT_S / 3600)) hours (command ${status:-unknown}); stopping the box. Its state is kept: --no-send carries the run on"
	if [ $((now - last_report)) -ge 600 ]; then
		el=$((now - began))
		note "still rebuilding: $((el / 3600))h$(printf %02d $((el % 3600 / 60)))m, command ${status:-unknown}, box ${state:-unknown}"
		last_report=$now
	fi
	sleep "$POLL_S"
done
note "the result is at $url/out/"

# --- 6. home -----------------------------------------------------------------------------
stop_box
note "installing the result here (import-result.sh, then its dry run; nothing served changes)"
script "$IMPORT" "${passed[@]}" "$url" || fail "import-result.sh failed; fix what it says and run scripts/cloud/import-result.sh $url"
if [ "$swap" = 1 ]; then
	note "--swap: swapping the result in (import-result.sh --swap)"
	script "$IMPORT" "${passed[@]}" --swap "$url" || fail "the swap failed; see import-result.sh's message above"
	note "done: swapped. Now the post-swap closure probes (OPERATIONS.md, \"Bicycle closures in the tiles\", step 3)"
else
	note "done: installed as staging. Read the dry run above, then: scripts/cloud/import-result.sh${profile:+ --profile $profile} --swap $url"
fi
[ "$beta" = 0 ] || note "and on the beta server: scripts/cloud/import-result.sh --beta $url"
