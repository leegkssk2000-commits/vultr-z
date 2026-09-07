"""Match a live STEP7 callback to its installed source without executing that source.

This closes mutable-function-metadata substitution, not arbitrary hostile Python
execution. The validator process, imported dependencies and host administrator
remain trusted. Source hashes are still compared to the signed approval by the
existing authorization owner. No data access, network or approval is provided.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
import sys
import types


def producer_binding(producer, *, error_type=ValueError):
    """Return the source/name binding only for an unchanged canonical function.

    Compiling verifies the actual code object, including nested code/constants,
    but does not run module top-level statements. STEP7 byte producers deliberately
    have no defaults or closures: those are mutable executable inputs otherwise
    absent from the existing signed source binding.
    """
    def deny(reason):
        raise error_type(reason)

    if (not inspect.isfunction(producer) or '<' in producer.__qualname__
            or producer.__qualname__ != producer.__name__):
        deny('TOP_LEVEL_PINNED_PRODUCER_REQUIRED')
    module = sys.modules.get(producer.__module__)
    if (not isinstance(module, types.ModuleType)
            or vars(module).get(producer.__name__) is not producer):
        deny('PRODUCER_CANONICAL_FUNCTION_REQUIRED')
    if producer.__globals__ is not vars(module):
        deny('PRODUCER_GLOBAL_NAMESPACE_MISMATCH')
    if (producer.__defaults__ is not None or producer.__kwdefaults__ is not None
            or producer.__closure__ is not None):
        deny('PRODUCER_MUTABLE_ARGUMENT_STATE_FORBIDDEN')
    filename = inspect.getsourcefile(module)
    if not filename:
        deny('PRODUCER_SOURCE_REQUIRED')
    path = Path(filename)
    try:
        if Path(producer.__code__.co_filename).resolve() != path.resolve():
            deny('PRODUCER_CODE_LOCATION_MISMATCH')
        source = path.read_bytes()
        # Do not inherit this helper's future flags into the target compilation.
        compiled = compile(source, producer.__code__.co_filename, 'exec',
                           dont_inherit=True, optimize=sys.flags.optimize)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise error_type('PRODUCER_SOURCE_NOT_COMPILABLE') from exc
    candidates = [value for value in compiled.co_consts
                  if isinstance(value, types.CodeType)
                  and value.co_name == producer.__name__
                  and value.co_qualname == producer.__qualname__]
    if len(candidates) != 1 or candidates[0] != producer.__code__:
        deny('PRODUCER_EXECUTABLE_CODE_MISMATCH')
    return hashlib.sha256(source).hexdigest(), module.__name__ + ':' + producer.__qualname__
