#!/usr/bin/env bash
# Uploads a signed bundle to Google Play's internal testing track (the Android app workflow, on a
# release tag). Needs only curl, openssl and jq, all on GitHub's runners: no third-party action
# handles the key.
#
#   PLAY_SERVICE_ACCOUNT_JSON  the service account's JSON key (repository secret)
#   PLAY_PACKAGE               the application id (ROUTEMAKER_APP_ID)
#   PLAY_NOTES                 release notes, en-US, 500 characters at most
#   $1                         the .aab file
#
# Promoting a build from internal testing to the closed test or production stays a click in Play
# Console (mobile/README.md, "Building").
set -euo pipefail
# --fail-with-body: a refusal prints Google's reason, not just the status code.

aab="$1"
: "${PLAY_SERVICE_ACCOUNT_JSON:?}" "${PLAY_PACKAGE:?}" "${PLAY_NOTES:?}"
# PLAY_API_ROOT only for the script's own test (mobile/test/play-upload.test.mjs).
root="${PLAY_API_ROOT:-https://androidpublisher.googleapis.com}"
api="$root/androidpublisher/v3/applications/$PLAY_PACKAGE"
upload="$root/upload/androidpublisher/v3/applications/$PLAY_PACKAGE"

# The private key lives only in the runner's temporary directory, for this script.
key="$(mktemp "${RUNNER_TEMP:-/tmp}/play-key.XXXXXX")"
trap 'rm -f "$key"' EXIT
jq -r .private_key <<<"$PLAY_SERVICE_ACCOUNT_JSON" >"$key"
email="$(jq -r .client_email <<<"$PLAY_SERVICE_ACCOUNT_JSON")"
token_uri="$(jq -r '.token_uri // "https://oauth2.googleapis.com/token"' <<<"$PLAY_SERVICE_ACCOUNT_JSON")"

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
now="$(date +%s)"
header="$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)"
claims="$(jq -cn --arg iss "$email" --arg aud "$token_uri" --argjson iat "$now" \
  '{iss: $iss, scope: "https://www.googleapis.com/auth/androidpublisher", aud: $aud, iat: $iat, exp: ($iat + 600)}' | b64url)"
signature="$(printf '%s.%s' "$header" "$claims" | openssl dgst -sha256 -sign "$key" -binary | b64url)"

token="$(curl -sS --fail-with-body "$token_uri" \
  --data-urlencode "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" \
  --data-urlencode "assertion=$header.$claims.$signature" | jq -r .access_token)"
[ -n "$token" ] && [ "$token" != null ] || { echo "::error::Google refused the service account's sign-in." >&2; exit 1; }
echo "::add-mask::$token"
auth=(-H "Authorization: Bearer $token")

edit="$(curl -sS --fail-with-body -X POST "${auth[@]}" "$api/edits" | jq -r .id)"
code="$(curl -sS --fail-with-body -X POST "${auth[@]}" -H "Content-Type: application/octet-stream" \
  --data-binary "@$aab" "$upload/edits/$edit/bundles?uploadType=media" | jq -r .versionCode)"
jq -n --arg code "$code" --arg notes "$PLAY_NOTES" \
  '{track: "internal", releases: [{versionCodes: [$code], status: "completed",
    releaseNotes: [{language: "en-US", text: $notes}]}]}' |
  curl -sS --fail-with-body -X PUT "${auth[@]}" -H "Content-Type: application/json" --data-binary @- \
    "$api/edits/$edit/tracks/internal" >/dev/null
curl -sS --fail-with-body -X POST "${auth[@]}" "$api/edits/$edit:commit" >/dev/null
echo "Uploaded version code $code to internal testing."
