"""Temporal workflows for ZERO.

Each workflow lives in its own module and registers a deterministic
``@workflow.defn`` class. Activities live under ``app.workflows.activities``
and carry the actual I/O.

This ``__init__`` is intentionally empty — importing the package must not
require ``temporalio`` to be installed (the feature flag in
``app.workflows.client.use_temporal_enabled`` reads env vars without ever
touching the SDK). Pull workflow / activity classes from their submodules:

    from app.workflows.carousel_workflow import GenerateCarouselWorkflow
    from app.workflows.activities import ALL_ACTIVITIES
"""
