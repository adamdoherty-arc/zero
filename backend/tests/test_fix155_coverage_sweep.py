"""Fix-155 (supervise run 6a1563fd) — retrieve/respond coverage sweep.

Every test here fails against the pre-fix code. They are written to pin the
SYMPTOM that was measured live, not merely to execute the new branch:

  RET-4  the dense side of vault search had no similarity floor, so it always
         returned `per_side_k` rows and RRF scored purely on rank — making
         `score` identical (0.016393) for gibberish and for a real query.
  RET-5/IDX-7  17.7% of the live index was sub-40-char boilerplate; the two
         strings `**Status:** `success`` / `**Status:** `failure`` alone
         accounted for 15,674 chunks collapsed onto two embedding vectors.
  RET-2  memory_tree frontmatter dump -> parse was lossy for list fields.
  INFRA-1 the autopilot's Legion project-id map was wrong for all four labels.
  INFRA-2 /api/swarm/* is gone; a 404 there is "removed", not "flaky".
"""

from __future__ import annotations

import pytest

from app.services.vault_indexer_service import (
    _MIN_CHUNK_SIGNAL_CHARS,
    _chunk_section,
    _is_indexable,
    _signal_len,
)


# ---------------------------------------------------------------------------
# IDX-7 / RET-5 — boilerplate chunks must not reach the index
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "boilerplate",
    [
        "**Status:** `success`",          # 10,391 copies in the live index
        "**Status:** `failure`",          # 5,283 copies
        "```bash",
        "```markdown",
        "```",
        "- None",
        "- None.",
        "_(none)_",
        "_(no tasks yet)_",
        "_(set manually above)_",
    ],
)
def test_boilerplate_chunks_are_not_indexed(boilerplate):
    """The 10 most common sub-40-char chunks in the live vault were all noise."""
    assert _chunk_section("Some > Heading", boilerplate) == []


def test_signal_len_ignores_markdown_decoration():
    """The floor measures retrievable text, not formatting bytes.

    `**Status:** `success`` is 21 raw chars but only 14 chars of signal, which
    is why a naive length floor had to be set uncomfortably high to catch it.
    """
    assert _signal_len("**Status:** `success`") == len("Status:success")
    assert _signal_len("```bash") == len("bash")


def test_real_prose_survives_the_floor():
    """The floor must not eat legitimately short but meaningful content."""
    body = "Renew the ADA trading licence before the end of August 2026."
    chunks = _chunk_section("Admin", body)
    assert len(chunks) == 1
    assert chunks[0].content == body


def test_floor_boundary_is_signal_based():
    just_under = "a" * (_MIN_CHUNK_SIGNAL_CHARS - 1)
    just_over = "a" * _MIN_CHUNK_SIGNAL_CHARS
    assert not _is_indexable(just_under)
    assert _is_indexable(just_over)
    # Decoration alone can never lift a chunk over the floor.
    assert not _is_indexable("**" + just_under + "**")


def test_chunk_indices_stay_gap_free_after_filtering():
    """Dropping a boilerplate tail slice must not leave a hole in `idx`."""
    body = ("Substantive paragraph about vault indexing. " * 80).strip()
    chunks = _chunk_section("H", body)
    assert len(chunks) > 1
    assert [c.idx for c in chunks] == list(range(len(chunks)))


# ---------------------------------------------------------------------------
# RET-2 — memory_tree frontmatter list round-trip
# ---------------------------------------------------------------------------

def test_frontmatter_list_round_trips_as_a_list():
    from app.services.memory_tree.vault import _frontmatter_dump, _frontmatter_parse

    meta = {"partition": "personal", "tags": ["alpha", "beta"], "agent_writable": []}
    parsed, _body = _frontmatter_parse(_frontmatter_dump(meta) + "\n\nbody\n")

    assert parsed["tags"] == ["alpha", "beta"], "tags came back as a string"
    # The pre-fix bug: [] round-tripped to the string "[]", which is TRUTHY,
    # inverting the meaning of "nothing is agent-writable".
    assert parsed["agent_writable"] == []
    assert not parsed["agent_writable"]
    assert parsed["partition"] == "personal"


# ---------------------------------------------------------------------------
# INFRA-1 — Legion project-id map
# ---------------------------------------------------------------------------

def test_autopilot_project_ids_match_legion():
    """Verified against GET http://localhost:8005/api/projects on 2026-07-28.

    Pre-fix every label was wrong AND pointed at a real other project:
    zero->8 (AI Content Tools), ada->6 (FortressOS), fortressos->7 (Zero),
    legion->3 (GPU Manager).
    """
    from app.services.autonomous_orchestration_service import PROJECT_IDS

    assert PROJECT_IDS == {"zero": 7, "ada": 5, "fortressos": 6, "legion": 1}


def test_autopilot_zero_id_matches_settings():
    """The map and `settings.zero_legion_project_id` must not drift apart."""
    from app.infrastructure.config import get_settings
    from app.services.autonomous_orchestration_service import PROJECT_IDS

    assert PROJECT_IDS["zero"] == get_settings().zero_legion_project_id


# ---------------------------------------------------------------------------
# INFRA-2 — a removed endpoint is not a transient failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_swarm_404_raises_capability_removed():
    from app.services.legion_client import (
        LegionAPIError,
        LegionCapabilityRemovedError,
        LegionClient,
    )

    client = LegionClient.__new__(LegionClient)

    async def _post(endpoint, json=None):
        raise LegionAPIError(
            f"Legion API error 404: POST {endpoint} — endpoint or resource not found"
        )

    client._post = _post
    with pytest.raises(LegionCapabilityRemovedError):
        await client._swarm_post("/swarm/plan-next/7", {})


@pytest.mark.asyncio
async def test_swarm_non_404_stays_a_plain_api_error():
    """A 500 from Legion IS transient and must keep its retry semantics."""
    from app.services.legion_client import (
        LegionAPIError,
        LegionCapabilityRemovedError,
        LegionClient,
    )

    client = LegionClient.__new__(LegionClient)

    async def _post(endpoint, json=None):
        raise LegionAPIError("Legion API error 500: Internal Server Error")

    client._post = _post
    with pytest.raises(LegionAPIError) as excinfo:
        await client._swarm_post("/swarm/lifecycle", {})
    assert not isinstance(excinfo.value, LegionCapabilityRemovedError)


def test_capability_removed_warns_once_only():
    """The hourly tick must not re-warn about a permanently gone endpoint."""
    from app.services import autonomous_orchestration_service as svc

    svc._REMOVED_CAPABILITIES.clear()
    try:
        err = RuntimeError("gone")
        assert svc._note_capability_removed("swarm", err) is True
        assert svc._note_capability_removed("swarm", err) is False
        assert svc._note_capability_removed("swarm", err) is False
    finally:
        svc._REMOVED_CAPABILITIES.clear()


# ---------------------------------------------------------------------------
# RET-4 — the dense side must be able to abstain
# ---------------------------------------------------------------------------

def test_search_accepts_a_similarity_floor():
    import inspect

    from app.services.vault_retrieval_service import _MIN_DENSE_SIM, VaultRetrievalService

    sig = inspect.signature(VaultRetrievalService.search)
    assert "min_similarity" in sig.parameters
    assert sig.parameters["min_similarity"].default is None  # None => _MIN_DENSE_SIM
    assert 0.0 < _MIN_DENSE_SIM < 1.0


def test_dense_sql_bounds_cosine_distance():
    """The floor must be expressed as a distance bound so HNSW still applies.

    Filtering on the `1 - (embedding <=> :emb)` alias instead would force a
    sequential scan over all 101k chunks.
    """
    import inspect

    from app.services import vault_retrieval_service as mod

    src = inspect.getsource(mod.VaultRetrievalService.search)
    assert "(embedding <=> (:emb)::vector) <= :max_dist" in src
    assert "dense_params[\"max_dist\"] = 1.0 - min_similarity" in src
