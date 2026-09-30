"""Bounded two-process supervisor and write-once submission journal.

No scheduler/SSH command is embedded here. Launch commands and an independent
verifier come from the pinned caller, never a downloaded result document.
"""
import hashlib
import contextlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def write_once(path, value):
    raw = canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    parent = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def file_record(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "regular single-link evidence required")
        digest, count = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, 1024**2)
            if not chunk:
                break
            count += len(chunk)
            digest.update(chunk)
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)
        require(identity(info) == identity(os.fstat(fd)) == identity(Path(path).lstat()) and count == info.st_size,
                "evidence changed while hashing")
        return {"size": count, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def stop_group(process):
    # Descendants may still hold stdout even after the leader exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


@contextlib.contextmanager
def verification_deadline(seconds):
    require(seconds > 0 and signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "verification deadline unavailable")
    previous = signal.getsignal(signal.SIGALRM)

    def expired(*_):
        raise TimeoutError("artifact verification deadline reached")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def run_process(command, env, log_path, *, seconds, max_log_bytes=8 * 1024**2):
    require(type(command) is list and command and all(type(a) is str for a in command), "explicit argv required")
    require(0 < seconds <= 7200 and type(max_log_bytes) is int and 0 < max_log_bytes <= 64 * 1024**2,
            "invalid child budget")
    started = time.monotonic()
    process, error, written = None, None, 0
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output, selectors.DefaultSelector() as poller:
        try:
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
            os.set_blocking(process.stdout.fileno(), False)
            poller.register(process.stdout, selectors.EVENT_READ)
            deadline, heartbeat = started + seconds, started
            while poller.get_map():
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError("child deadline reached")
                if now - heartbeat >= 30:
                    output.flush()
                    os.fsync(output.fileno())
                    print("PAIR_HEARTBEAT=" + json.dumps({"pid": process.pid, "seconds": round(now - started),
                                                          "log_bytes": written}), flush=True)
                    heartbeat = now
                for key, _ in poller.select(min(0.2, deadline - now)):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        poller.unregister(key.fileobj)
                        continue
                    allowed = min(len(chunk), max_log_bytes - written)
                    output.write(chunk[:allowed])
                    written += allowed
                    if allowed != len(chunk):
                        raise RuntimeError("child log budget exceeded; prefix preserved")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except BaseException as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            if process is not None:
                stop_group(process)
                process.stdout.close()
            output.flush()
            os.fsync(output.fileno())
    return {"pid": process.pid if process else None, "returncode": process.returncode if process else None,
            "error": error, "elapsed_seconds": round(time.monotonic() - started, 3),
            "log": {"name": Path(log_path).name, **file_record(log_path)}}


def run_pair(root, commands, environments, *, child_seconds, total_seconds, verify_child, verify_pair,
             max_log_bytes=8 * 1024**2):
    """Two sequential NEW processes; fail fast; durable failures; no retry.

The two callbacks independently verify each child and then the pair. A zero
process return code without verified artifacts is NOT accepted. Existing roots
are rejected, including partial failed attempts. Nothing is deleted here.
"""
    require(0 < child_seconds <= 7200 and child_seconds < total_seconds <= 14400, "pair deadline policy differs")
    root = Path(root)
    root.mkdir(mode=0o700, exist_ok=False)
    started, children, verified = time.monotonic(), [], []
    terminal = {"status": "PAIR_FAILED", "children": children, "error": None,
                "automatic_retry": False, "jobs_submitted": 0, "ready_for_gpu": False}
    write_once(root / "STARTED.json", {"pid": os.getpid(), "child_seconds": child_seconds,
                                        "total_seconds": total_seconds, "roles": ["reference", "observed"]})
    try:
        for role in ("reference", "observed"):
            remaining = total_seconds - (time.monotonic() - started)
            require(remaining > 0, "total deadline reached")
            child = run_process(commands[role], environments[role], root / (role + ".log"),
                                seconds=min(child_seconds, remaining), max_log_bytes=max_log_bytes)
            child["role"] = role
            children.append(child)
            write_once(root / (role + "-process.json"), child)
            require(child["error"] is None and child["returncode"] == 0, "child failed: " + role)
            require(len({c["pid"] for c in children}) == len(children), "cold process PID reused")
            with verification_deadline(total_seconds - (time.monotonic() - started)):
                verified.append(verify_child(role, child))
        require(time.monotonic() - started < total_seconds, "total deadline reached before pair verification")
        with verification_deadline(total_seconds - (time.monotonic() - started)):
            summary = verify_pair(*verified)
        require(type(summary) is dict and summary.get("verified") is True, "pair artifact verifier did not accept")
        require(time.monotonic() - started < total_seconds, "total deadline reached during verification")
        terminal.update(status="PAIR_VERIFIED", summary=summary)
    except BaseException as exc:
        terminal["error"] = {"type": type(exc).__name__, "message": str(exc)}
    terminal["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_once(root / "TERMINAL.json", terminal)
    return terminal


def submit_once(root, authorization, invoke_submit):
    """Journal-before-call guard. Never guesses whether an uncertain submit ran.

This reusable helper is not a submit command. The future controller must bind
the approved package/resources and provide the one audited scheduler call.
"""
    require(type(authorization) is dict and authorization.get("approved") is True,
            "new explicit resource authorization required")
    root = Path(root)
    write_once(root / "SUBMIT_INTENT.json", authorization)
    try:
        response = invoke_submit()
        require(type(response) is dict and type(response.get("job_id")) is str
                and response["job_id"].isascii() and response["job_id"].isdecimal()
                and not response["job_id"].startswith("0"), "ambiguous scheduler response")
        write_once(root / "SUBMIT_RESPONSE.json", response)
        return response
    except BaseException as exc:
        write_once(root / "SUBMIT_UNCERTAIN.json", {"type": type(exc).__name__, "message": str(exc),
                                                    "retry_allowed": False})
        raise
