"""Bounded read-only watch, then one terminal collection/offline check; no reconnect."""
import argparse
import datetime
import json
import os
import time
from publish_fine_alpha import RELEASE_ROOT
from status_fine_alpha_753729 import query
from collect_fine_alpha_753729 import collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch-authorized-job', action='store_true', required=True)
    parser.parse_args()
    root = RELEASE_ROOT/'watch-753729'; root.mkdir(mode=0o700, exist_ok=False)
    begin = time.monotonic()
    result = dict(status='WATCH_STARTED', job_id='753729', pid=os.getpid(), poll_interval_seconds=300,
                  maximum_watch_hours=48, started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  automatic_retry=False, automatic_reconnect=False, jobs_submitted=0, queries=0)
    (root/'START.json').write_text(json.dumps(result, indent=2)+'\n')
    print('WATCH_DIRECTORY='+str(root), flush=True)
    try:
        while time.monotonic()-begin < 48*3600:
            observation = query(); result['queries'] += 1
            result['last_observation'] = observation
            (root/f'OBSERVATION_{result["queries"]:04d}.json').write_text(json.dumps(observation, indent=2)+'\n')
            if observation['terminal']:
                result['collection'] = collect()  # One attempt only; failures propagate and stop.
                result['status'] = result['collection']['status']
                break
            result['status'] = 'WATCHING_NONTERMINAL_JOB'
            deadline = time.monotonic()+300
            while time.monotonic() < deadline:
                time.sleep(max(0, min(30, deadline-time.monotonic())))
        else:
            result['status'] = 'LOCAL_WATCH_DEADLINE_REACHED_REMOTE_JOB_UNCHANGED'
    except BaseException as exc:
        result.update(status='WATCH_STOPPED_INSPECT_NO_RECONNECT_NO_RETRY', error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        result['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (root/'RESULT.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result), flush=True)


if __name__ == '__main__': main()
