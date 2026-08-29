"""L4. Ports — ``typing.Protocol`` definitions only.

Each port names one engine capability; each has exactly one concrete adapter in
``pdf_toolkit.adapters``. Nothing here imports an engine library: a port is a
shape, not an implementation. The resolution registry that maps a port to its
adapter (or to ``None`` with a reason) lands with the engine spec.

This package is intentionally empty at this point in the build order.
"""
