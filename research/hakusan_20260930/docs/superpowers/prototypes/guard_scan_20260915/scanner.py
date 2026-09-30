"""Candidate function body; assembled into a LOCAL TEST copy of pinned v18.

One live key snapshot, one pass. Validate each name before hashing/partitioning
it. Cache only exact immutable unprotected names, as in the original. Never
cache a binding value, a successful guard, or the registry key set.
Dependencies are the unchanged v18 globals, not replacements of those globals.
"""


def _live_protected_module_bindings(protected_tops):
    registry = sys.modules
    if type(registry) is not dict:
        raise DiagnosticError("module registry requires exact dict")
    top_names = tuple(protected_tops)
    if any(type(name) is not str for name in top_names):
        raise DiagnosticError("protected module root names require exact strings")
    tops = frozenset(top_names)
    names = tuple(registry)
    budget = _ACTIVE_SEAL_BUDGET.get()
    excluded = (
        budget.unprotected_module_names.get(tops, frozenset())
        if budget is not None else frozenset()
    )
    bindings = {}
    additional = set()
    for name in names:
        # Reject BEFORE any operation that might dispatch a custom name method.
        # The current registry is enumerated on every call, including warm cache.
        if type(name) is not str:
            raise DiagnosticError("module registry names require exact strings")
        if name in excluded:
            continue
        if name.partition(".")[0] in tops:
            bindings[name] = registry[name]
        else:
            additional.add(name)
    if budget is not None and additional:
        budget.unprotected_module_names[tops] = excluded | frozenset(additional)
    return bindings
