#!/bin/bash
# Run by the user on the Mac. Password stays in the SSH terminal prompt.
# Opens a private local multiplexed connection; no remote files/jobs are changed.
# New masters retain idle connections for 12 hours and log disconnect diagnostics.
# Existing masters are reused unchanged, never killed or silently restarted.
set -euo pipefail
umask 077
test "$(uname -s)" = Darwin

BASE="/Users/gigi/发表/超算"
CONTROL="$BASE/.hakusan-control"
SOCKET="$CONTROL/master.sock"
test -d "$BASE"
test ! -L "$BASE"
test -O "$BASE"

if [ -L "$CONTROL" ]; then
  echo "STOP: control directory is a symlink" >&2
  exit 2
fi
if [ ! -e "$CONTROL" ]; then
  mkdir -m 700 "$CONTROL"
fi
test -d "$CONTROL"
test -O "$CONTROL"
test "$(stat -f %Lp "$CONTROL")" = 700

LOGS="$CONTROL/logs"
test ! -L "$LOGS"
if [ ! -e "$LOGS" ]; then
  mkdir -m 700 "$LOGS"
fi
test -d "$LOGS"
test -O "$LOGS"
test "$(stat -f %Lp "$LOGS")" = 700

# Unique, owner-only directory: preserve previous logs, never follow old log links.
STAMP=$(date -u '+%Y%m%dT%H%M%SZ')
RUN_LOGS=$(mktemp -d "$LOGS/connect-$STAMP.XXXXXX")
EVENT_LOG="$RUN_LOGS/events.log"
MASTER_LOG="$RUN_LOGS/master-ssh.log"
CHECK_LOG="$RUN_LOGS/check-ssh.log"

record_event ()
{
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >> "$EVENT_LOG"
}

finish ()
{
  RC=$?
  trap - EXIT
  record_event "SCRIPT_EXIT rc=$RC" || true
  if [ "$RC" -ne 0 ]; then
    printf 'CONNECTION_CHECK_FAILED_RC=%s\n' "$RC" >&2
    echo "See the private logs below; no automatic reconnection was attempted." >&2
  fi
  printf 'CONNECTION_LOG_DIRECTORY=%s\n' "$RUN_LOGS"
  exit "$RC"
}
trap finish EXIT

record_event "SCRIPT_START requested_idle_seconds=43200"
echo "Private SSH logs may include hostnames, account names and key fingerprints."
echo "Passwords are entered only at the SSH prompt; no terminal session is recorded."

NEW_MASTER=0
if [ -e "$SOCKET" ] || [ -L "$SOCKET" ]; then
  test ! -L "$SOCKET"
  test -S "$SOCKET"
  test -O "$SOCKET"
  record_event "CHECK_EXISTING_MASTER"
  if ! /usr/bin/ssh -E "$CHECK_LOG" -o LogLevel=DEBUG1 \
    -S "$SOCKET" -O check s2510040@hakusan1; then
    record_event "EXISTING_MASTER_UNAVAILABLE socket_preserved=true"
    echo "STOP: existing control socket is not live; do not overwrite it" >&2
    exit 2
  fi
  record_event "REUSED_MASTER settings_unchanged=true"
  echo "Existing master reused unchanged; its original timeout/log settings still apply."
else
  record_event "START_NEW_MASTER idle_seconds=43200 alive_interval=30 alive_count=3"
  echo "Enter the SSH password here if prompted; do not send it in chat."
  /usr/bin/ssh -E "$MASTER_LOG" -o LogLevel=DEBUG1 -M -S "$SOCKET" \
    -o ControlPersist=43200 \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -o ConnectTimeout=12 -fNT s2510040@hakusan1 2>> "$MASTER_LOG"
  NEW_MASTER=1
  record_event "NEW_MASTER_STARTED"
  printf 'MASTER_TRANSPORT_LOG=%s\n' "$MASTER_LOG"
fi

record_event "VERIFY_MASTER_AND_REMOTE_IDENTITY"
/usr/bin/ssh -E "$CHECK_LOG" -o LogLevel=DEBUG1 \
  -S "$SOCKET" -O check s2510040@hakusan1
/usr/bin/ssh -E "$CHECK_LOG" -o LogLevel=DEBUG1 -S "$SOCKET" -o BatchMode=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ConnectTimeout=12 s2510040@hakusan1 \
  'set -eu; test "$(id -un)" = s2510040; hostname; echo HAKUSAN_AUTHENTICATED=PASS'
record_event "REMOTE_IDENTITY_PASS"
echo "HAKUSAN_SHARED_CONNECTION=PASS"
echo "Connection only: no uploads, freezes, or jobs submitted."
if [ "$NEW_MASTER" -eq 1 ]; then
  echo "This new master exits after 12 idle hours with no client sessions."
  echo "Network loss, sleep or a server disconnect can still end it earlier."
else
  echo "The 12-hour timeout and background logging apply to the next NEW master."
  echo "This run logs connection checks only; it cannot retrofit the existing master."
fi
echo "No connection was closed. To close the shared master manually:"
printf 'ssh -S "%s" -O exit s2510040@hakusan1\n' "$SOCKET"
