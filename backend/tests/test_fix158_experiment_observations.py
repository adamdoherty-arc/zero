"""Fix-158 (L4): the A/B experiment arm appender.

Carried as an open lead for three consecutive supervise runs. The content A/B
subsystem had a creator (POST /api/brain/experiments) and a concluder (the
scheduler's check_experiments sweep, which completes an experiment once BOTH arms
reach sample_size_target) but NOTHING that could ever append to an arm:
`control_results`/`variant_results` were initialised to [] and only ever read.
Every experiment an operator created therefore sat "active" forever and the
experiment dashboards counted it as live work that could not conclude.

These tests pin the middle step. They exercise validation and payload shape
without a live Postgres; the JSONB concat itself is asserted against the real
database in the deployed smoke check (see the sprint record).
"""

import pytest

from app.models.brain import ContentExperimentObservation
from app.services.content_learning_engine import ContentLearningEngine


@pytest.mark.asyncio
async def test_rejects_unknown_arm():
    """Only 'control'/'variant' exist; a typo must not silently no-op."""
    engine = ContentLearningEngine()
    for bad in ("treatment", "", "CONTROLL", "both"):
        with pytest.raises(ValueError, match="arm must be"):
            await engine.record_experiment_observation("exp1", bad, 50.0)


@pytest.mark.asyncio
async def test_arm_is_case_and_whitespace_insensitive(monkeypatch):
    """'Control' / ' variant ' are the same arms — reject only real typos."""
    engine = ContentLearningEngine()

    # Fails later (no DB) but must get PAST arm validation.
    for ok in ("Control", " variant ", "VARIANT"):
        with pytest.raises(Exception) as exc:
            await engine.record_experiment_observation("exp1", ok, 50.0)
        assert "arm must be" not in str(exc.value)


@pytest.mark.asyncio
async def test_rejects_non_numeric_score():
    engine = ContentLearningEngine()
    with pytest.raises(ValueError, match="score must be numeric"):
        await engine.record_experiment_observation("exp1", "control", "not-a-number")


def test_observation_schema_rejects_bad_arm():
    """The API boundary rejects a bad arm as a 422 before reaching the service."""
    with pytest.raises(Exception):
        ContentExperimentObservation(arm="treatment", score=1.0)

    ok = ContentExperimentObservation(arm="control", score=12.5)
    assert ok.arm == "control"
    assert ok.metrics is None


def test_observation_schema_carries_optional_metrics():
    obs = ContentExperimentObservation(
        arm="variant", score=77.0, metrics={"views": 1000, "likes": 42}
    )
    assert obs.metrics["views"] == 1000


def test_arm_append_binds_jsonb_not_a_json_string():
    """Regression: the arm append must bind a LIST, never json.dumps() output.

    First implementation used cast(json.dumps([obs]), JSONB). A Python str bound to
    a JSONB parameter is encoded as a JSON scalar *string*, so `arm || '[{...}]'`
    appended one text element instead of an object. jsonb_array_length still
    incremented (so counts looked right), but every ContentExperiment validation
    then failed on `control_results.0: Input should be a valid dictionary`, and
    get_experiments' defensive except returned [] — blanking the whole experiments
    API. Green unit tests missed it because they never touched Postgres; only the
    live end-to-end check caught it.
    """
    import inspect
    from app.services import content_learning_engine as mod

    raw = inspect.getsource(mod.ContentLearningEngine.record_experiment_observation)
    # Strip comments/docstring lines — the explanatory comment names json.dumps on
    # purpose, so assert against executable code only.
    src = "\n".join(
        ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "json.dumps" not in src, (
        "record_experiment_observation is binding a json.dumps() string to a JSONB "
        "column again; bind a real list so the driver encodes a JSON array"
    )
    assert "literal([observation], JSONB)" in src


def test_get_experiments_isolates_bad_rows():
    """One malformed row must not blank the entire list (it did, live)."""
    import inspect
    from app.services import content_learning_engine as mod

    src = inspect.getsource(mod.ContentLearningEngine.get_experiments)
    assert "content_experiment_row_skipped" in src, (
        "get_experiments lost its per-row isolation; a single bad JSONB arm will "
        "again return [] for the whole experiments API"
    )


def test_endpoint_is_registered():
    """The appender must be reachable — an unreachable method is what we had."""
    from app.routers.brain import router

    paths = {r.path for r in router.routes}
    assert "/api/brain/experiments/{experiment_id}/observations" in paths, sorted(paths)

    route = next(
        r for r in router.routes
        if r.path == "/api/brain/experiments/{experiment_id}/observations"
    )
    assert "POST" in route.methods
