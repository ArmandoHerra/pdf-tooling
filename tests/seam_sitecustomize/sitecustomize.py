"""Install the `PDF-43` seam observer in a DRIVEN CHILD at interpreter startup.

This directory goes on the child's ``PYTHONPATH`` and nothing else does. The
observer **must not** run in the pytest process: ``sys.addaudithook`` cannot be
removed once installed, so a hook added there would persist for every subsequent
test in that worker, under ``-n auto``, for the rest of the session -- and it
would observe pytest's own imports and coverage writes besides.

``tests/seams.py`` is loaded **by absolute path** from ``PDF_SEAM_MODULE`` rather
than by putting ``tests/`` on ``sys.path``. Two reasons, and the second is the
load-bearing one:

* it keeps the child's import namespace byte-identical to a normal run, so the
  drive measures the product rather than the harness;
* ``tests/`` contains modules with ordinary names (``registry.py``, ``corpus.py``)
  that could shadow an import in the child. A drive whose harness can change
  which module the product imports is not measuring the product.

**A FAILED INSTALL IS RECORDED, NEVER SWALLOWED.** An observer that fails to
install produces an empty ledger, and an empty ledger reads exactly like *"this
verb performed no reads"* -- a silent invisibility, which is the precise defect
class `PDF-43` exists to make impossible. So the failure is written into the
ledger as an ``install-error`` record and the arms fail on it by name. This was
not a hypothetical: the first draft of this file swallowed a real
``AttributeError`` and reported a clean, entirely fictional zero.
"""

import importlib.util
import json
import os
import sys
import traceback

_MODULE_ENV = "PDF_SEAM_MODULE"
_LEDGER_ENV = "PDF_SEAM_LEDGER"
_PRIVATE_NAME = "_pdf_seam_observer"

INSTALL_ERROR_CHANNEL = "install-error"


def _report(detail: str) -> None:
    ledger = os.environ.get(_LEDGER_ENV, "")
    if not ledger:
        return
    line = json.dumps({"channel": INSTALL_ERROR_CHANNEL, "detail": detail}, sort_keys=True)
    try:
        handle = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(handle, (line + "\n").encode("utf-8"))
        finally:
            os.close(handle)
    except OSError:
        pass


def _install() -> None:
    source = os.environ.get(_MODULE_ENV, "")
    if not source:
        return
    if not os.path.isfile(source):
        _report(f"{_MODULE_ENV} does not name a file: {source!r}")
        return
    spec = importlib.util.spec_from_file_location(_PRIVATE_NAME, source)
    if spec is None or spec.loader is None:
        _report(f"no import spec for {source!r}")
        return
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE execution: `@dataclass` resolves its own class's
    # `__module__` through `sys.modules`, so a module that executes while absent
    # from `sys.modules` dies on the first dataclass with an `AttributeError`.
    sys.modules[_PRIVATE_NAME] = module
    try:
        spec.loader.exec_module(module)
        module.install_observer()
    except BaseException:
        sys.modules.pop(_PRIVATE_NAME, None)
        raise


try:
    _install()
except BaseException:
    # Recorded, not swallowed. The interpreter's startup is still allowed to
    # finish -- a harness that breaks every child replaces the product's
    # behaviour with its own, which is the one thing a drive may not do -- but
    # the ledger now carries the reason and the arms fail on it by name.
    _report(traceback.format_exc())
