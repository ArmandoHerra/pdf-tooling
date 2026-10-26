"""PDF-145 probe: run ONLY as an explicit path by
`test_name_template.py::test_the_channel_crosses_the_worker_boundary_uncaught`.

It publishes PDF-88 D4's channel UNCAUGHT inside an xdist worker, so the
controller must import `conftest` to rebuild it. That crossing is the property
under test; this file never runs in the parent suite.
"""

import warnings

import conftest


def test_publish_the_encoding_refusal_channel_uncaught() -> None:
    warnings.warn(conftest._EncodingRefusalRecorded("PDF-145 crossing probe"))  # noqa: B028
