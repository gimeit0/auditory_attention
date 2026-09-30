"""Read-only watch of the released v3 job until a terminal state, then collection and offline verification.

Unlike the v1 watcher, one failed status query does not end the watch. It exits only for a terminal
job, or for an ALERT that needs a person: the SSH master is gone (reconnect needed), several
consecutive query failures, a failure marker, no progress for too long, or the job is close to
its wall-clock limit. Nothing here submits, releases, cancels, updates or reconnects.
"""
import argparse
import datetime
import json
import os
import time
from publish_fine_alpha_v3 import RELEASE_ROOT
from status_fine_alpha_v3 import elapsed_seconds, query, released_job
from collect_fine_alpha_v3 import collect

POLL_SECONDS = 300
MAX_QUERY_FAILURES = 4            # ~20 min of consecutive failed polls
STALL_SECONDS = 50*60             # RUNNING with no new record, marker or log growth
WALL_ALERT_SECONDS = 5*3600+40*60  # 20 min before the 6 h limit
COLLECT_ATTEMPTS = 3


def fingerprint(observation):
    return json.dumps([observation.get('observed_records'), observation.get('worker_records'),
                       observation.get('complete_marker'), observation.get('failure_marker'),
                       sorted((observation.get('block_failures') or {}).keys()), observation.get('log_sizes')],
                      sort_keys=True)


def attempt_dir(job):
    n = 1
    while (RELEASE_ROOT/f'watch-{job}-{n}').exists(): n += 1
    root = RELEASE_ROOT/f'watch-{job}-{n}'; root.mkdir(mode=0o700, exist_ok=False)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch-released-v3-job', action='store_true', required=True)
    parser.add_argument('--poll-seconds', type=int, default=POLL_SECONDS)
    args = parser.parse_args()
    job, receipt_sha = released_job()
    root = attempt_dir(job)
    begin = time.monotonic()
    result = dict(status='WATCH_STARTED', job_id=job, pid=os.getpid(), poll_interval_seconds=args.poll_seconds,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), automatic_reconnect=False,
                  jobs_submitted=0, scheduler_writes=0, queries=0, query_failures=[], alerts=[])
    (root/'START.json').write_text(json.dumps(result, indent=2)+'\n')
    print('WATCH_DIRECTORY='+str(root), flush=True)
    failures = 0; last_change = time.monotonic(); last_print = None

    def alert(kind, **detail):
        result['alerts'].append(dict(kind=kind, utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), **detail))
        result['status'] = 'ALERT_'+kind
        print('ALERT '+kind+' '+json.dumps(detail), flush=True)

    try:
        while time.monotonic()-begin < 48*3600:
            try:
                observation = query(job, receipt_sha); failures = 0
            except ConnectionError as exc:
                result['query_failures'].append(dict(error=str(exc), utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
                failures += 1
                if 'MASTER_ABSENT' in str(exc) or failures >= 2:
                    alert('SSH_MASTER_LOST_USER_RECONNECT_REQUIRED', error=str(exc), consecutive=failures); break
            except Exception as exc:
                result['query_failures'].append(dict(error=f'{type(exc).__name__}: {exc}',
                                                     utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
                failures += 1
                if failures >= MAX_QUERY_FAILURES:
                    alert('REPEATED_QUERY_FAILURE', error=str(exc), consecutive=failures); break
            else:
                result['queries'] += 1; result['last_observation'] = observation
                (root/f'OBSERVATION_{result["queries"]:04d}.json').write_text(json.dumps(observation, indent=2)+'\n')
                print('OBS {} state={} elapsed={} records={} progress={}'.format(
                    observation['observed_utc'], observation['scheduler_state'], observation['elapsed'],
                    observation['observed_records'], observation['progress']), flush=True)
                if observation['terminal']:
                    result['terminal_observation'] = observation
                    for attempt in range(1, COLLECT_ATTEMPTS+1):
                        try:
                            result['collection'] = collect(job, receipt_sha); result['status'] = result['collection']['status']
                            break
                        except ConnectionError as exc:
                            result.setdefault('collection_failures', []).append(str(exc))
                            if attempt == COLLECT_ATTEMPTS or 'MASTER_ABSENT' in str(exc):
                                alert('COLLECTION_TRANSPORT_FAILED', error=str(exc)); break
                            time.sleep(120)
                        except Exception as exc:
                            alert('COLLECTION_OR_OFFLINE_VERIFY_FAILED', error=f'{type(exc).__name__}: {exc}'); break
                    break
                if observation['failure_marker'] or observation['block_failures']:
                    alert('FAILURE_MARKER_WHILE_ACTIVE', failure=observation['failure'],
                          block_failures=observation['block_failures']); break
                current = fingerprint(observation)
                if current != last_print: last_print = current; last_change = time.monotonic()
                elif observation['scheduler_state'] == 'RUNNING' and time.monotonic()-last_change > STALL_SECONDS:
                    alert('NO_PROGRESS', minutes=round((time.monotonic()-last_change)/60), records=observation['observed_records']); break
                seconds = elapsed_seconds(observation['elapsed'])
                if seconds and seconds > WALL_ALERT_SECONDS and not observation['complete_marker']:
                    alert('NEAR_WALL_LIMIT', elapsed=observation['elapsed'], records=observation['observed_records']); break
                result['status'] = 'WATCHING_NONTERMINAL_JOB'
            (root/'LATEST.json').write_text(json.dumps(result, indent=2)+'\n')
            time.sleep(args.poll_seconds)
        else:
            alert('LOCAL_WATCH_DEADLINE_REMOTE_JOB_UNCHANGED')
    except BaseException as exc:
        result.update(status='WATCH_CRASHED_INSPECT', error_type=type(exc).__name__, error=str(exc)); raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (root/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print('WATCH_RESULT '+json.dumps({k: result.get(k) for k in ('status', 'job_id', 'queries', 'alerts')}), flush=True)


if __name__ == '__main__': main()
