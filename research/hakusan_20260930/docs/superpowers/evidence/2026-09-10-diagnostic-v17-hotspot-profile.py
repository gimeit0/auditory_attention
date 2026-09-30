"""Reuse the pinned CPU-only preparation probe with one profiled repeat seal.

No model forward, GPU numerical inference, production edit or Slurm submission.
The inherited nonblocking shared evaluation lock refuses overlap with the job.
The new raw log is exclusive-created; existing final CPU evidence is untouched.
"""

import hashlib
from pathlib import Path

BASE = Path(__file__).with_name("2026-09-10-diagnostic-v17-remote-cpu-probe.py")
BASE_SHA = "90e83ad49d1962559a67594811f5b251ae7c5b1541812bacb3f379b18dc58c25"

OLD_REPEAT = (
    '                require(fingerprint == diag._model_execution_fingerprint(model), '
    '"unchanged model fingerprint differs")'
)
NEW_REPEAT = '''                import cProfile
                import pstats
                profile = cProfile.Profile()
                started_profile = time.perf_counter()
                profile.enable()
                try:
                    repeated_fingerprint = diag._model_execution_fingerprint(model)
                finally:
                    profile.disable()
                require(fingerprint == repeated_fingerprint, "unchanged model fingerprint differs")
                event("profiled_repeat_fingerprint", elapsed_seconds=time.perf_counter() - started_profile, source_unchanged=True, scientific_forward=False)
                pstats.Stats(profile, stream=sys.stdout).strip_dirs().sort_stats("cumtime").print_stats(35)
'''.rstrip()


def main():
    data = BASE.read_bytes()
    if hashlib.sha256(data).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: pinned CPU preparation probe changed")
    source = data.decode("utf-8")
    old_log = "2026-09-10-diagnostic-v17-final-cpu.log"
    if source.count(old_log) != 1 or source.count("        return module.main()") != 1:
        raise SystemExit("STOP: inherited probe layout differs")
    source = source.replace(old_log, "2026-09-10-diagnostic-v17-hotspot-profile.log")
    source = source.replace(
        "        return module.main()",
        "        replace_once(module, _PROFILE_OLD_REPEAT, _PROFILE_NEW_REPEAT)\n"
        "        return module.main()",
    )
    namespace = {
        "__name__": "v17_pinned_hotspot_probe",
        "__file__": str(BASE),
        "_PROFILE_OLD_REPEAT": OLD_REPEAT,
        "_PROFILE_NEW_REPEAT": NEW_REPEAT,
    }
    exec(compile(source, str(BASE), "exec"), namespace)
    return namespace["main"]()


if __name__ == "__main__":
    raise SystemExit(main())
