"""CPU-only metadata type inventory; no values, forward or production changes."""

import hashlib
from pathlib import Path

BASE = Path(__file__).with_name("2026-09-10-diagnostic-v17-remote-cpu-probe.py")
BASE_SHA = "90e83ad49d1962559a67594811f5b251ae7c5b1541812bacb3f379b18dc58c25"
ANCHOR = '                event("actual_snapshot_import_seal", status="PASS", bindings=len(authority.sealed_bindings))'
INSPECTION = '''
                import types
                def metadata_types(value, depth=0):
                    kind = type(value)
                    label = kind.__module__ + "." + kind.__qualname__
                    if depth >= 5:
                        return {"type": label, "truncated": True}
                    if kind in (tuple, list):
                        return {"type": label, "length": len(value), "items": [metadata_types(item, depth+1) for item in value[:100]]}
                    if kind is dict:
                        return {"type": label, "length": len(value), "entries": [[metadata_types(key, depth+1), metadata_types(item, depth+1)] for key, item in list(dict.items(value))[:100]]}
                    return {"type": label}
                fallbacks = []
                for module_name, bound in authority.sealed_bindings.items():
                    entry = next(item for item in authority.issued_modules[module_name] if item[0] is bound)
                    for name, function in entry[3].items():
                        if type(function) is not types.FunctionType:
                            continue
                        defaults, kwdefaults = function.__defaults__, function.__kwdefaults__
                        if kwdefaults is None and diag._has_only_immutable_default_literals(defaults):
                            continue
                        fallbacks.append({"module": module_name, "name": name, "defaults": metadata_types(defaults), "kwdefaults": metadata_types(kwdefaults)})
                event("actual_anchor_fallback_types", count=len(fallbacks), entries=fallbacks, contents_disclosed=False)
'''.rstrip()


def main():
    data = BASE.read_bytes()
    if hashlib.sha256(data).hexdigest() != BASE_SHA:
        raise SystemExit("STOP: pinned CPU probe changed")
    source = data.decode("utf-8")
    old_log = "2026-09-10-diagnostic-v17-final-cpu.log"
    if source.count(old_log) != 1 or source.count("        return module.main()") != 1:
        raise SystemExit("STOP: inherited probe layout differs")
    source = source.replace(old_log, "2026-09-10-diagnostic-v17-anchor-types.log")
    source = source.replace(
        "        return module.main()",
        "        replace_once(module, _TYPE_ANCHOR, _TYPE_ANCHOR + _TYPE_INSPECTION)\n"
        "        return module.main()",
    )
    namespace = {
        "__name__": "v17_pinned_anchor_types_probe",
        "__file__": str(BASE),
        "_TYPE_ANCHOR": ANCHOR,
        "_TYPE_INSPECTION": INSPECTION,
    }
    exec(compile(source, str(BASE), "exec"), namespace)
    return namespace["main"]()


if __name__ == "__main__":
    raise SystemExit(main())
