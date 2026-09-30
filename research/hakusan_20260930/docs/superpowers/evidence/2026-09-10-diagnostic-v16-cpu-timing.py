"""Time the pinned, unchanged v16 CPU preparation probe; no GPU or submission."""

import hashlib
from pathlib import Path
import sys

PROBE = Path(__file__).with_name('2026-09-10-diagnostic-v16-remote-cpu-probe.py')
EXPECTED = '9814308fa0d48abf7f0ffc534a1f9d8409afc5aa876d6b49193f6dac6385bb8e'


def main():
    source = PROBE.read_bytes()
    if hashlib.sha256(source).hexdigest() != EXPECTED:
        raise SystemExit('STOP: pinned probe differs')
    old = '    return module.main()'
    new = '''    replace_once(module, 'def event(stage, **fields):', "import time\\n_last_event = time.perf_counter()\\ndef event(stage, **fields):\\n    global _last_event\\n    now = time.perf_counter()\\n    fields['elapsed_since_previous_event_seconds'] = round(now - _last_event, 6)\\n    _last_event = now")
    replace_once(module, '                require(graphs == diag._callable_graphs(values, materialize_module_attributes=False),', '                event("repeat_model_fingerprint_complete")\\n                require(graphs == diag._callable_graphs(values, materialize_module_attributes=False),')
    return module.main()'''
    text = source.decode()
    if text.count(old) != 1:
        raise SystemExit('STOP: probe entrypoint differs')
    namespace = {'__file__': str(PROBE), '__name__': 'v16_cpu_timing_wrapper'}
    if '--profile' in sys.argv:
        old_profile = '                require(fingerprint == diag._model_execution_fingerprint(model), "unchanged model fingerprint differs")'
        new_profile = '''                import cProfile, pstats, io
                profiler = cProfile.Profile()
                repeated = profiler.runcall(diag._model_execution_fingerprint, model)
                require(fingerprint == repeated, "unchanged model fingerprint differs")
                output = io.StringIO()
                pstats.Stats(profiler, stream=output).sort_stats('cumulative').print_stats(25)
                print("CPU_CPROFILE_BEGIN\\n" + output.getvalue() + "CPU_CPROFILE_END", flush=True)'''
        new = new.replace('    return module.main()',
            '    replace_once(module, ' + repr(old_profile) + ', ' + repr(new_profile) + ')\n    return module.main()')
    exec(compile(text.replace(old, new), str(PROBE), 'exec'), namespace)
    sys.argv = [str(PROBE), '--run']
    return namespace['main']()


if __name__ == '__main__':
    raise SystemExit(main())
