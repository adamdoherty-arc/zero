"""Fix-128 (supervise run 2c2077d7, 2026-06-26) coverage hardening — regression locks.

Five source-verified gaps fixed this supervise run across the act-with-approval
(crown-jewel) and learn capability loops; each test pins one fix so it cannot
silently regress. Provenance: run 2c2077d7, sprint Fix-128 #11200, commit 93a4c68.

  ACT-B1  act-with-approval  approval_service._decide      approve() refuses logically-expired pending row (mirror queue svc)
  ACT-B2  act-with-approval  approval_service.list_pending excludes expired-but-unswept rows
  LRN-X1  learn              experiment_service.run_experiment  null-guards both re-fetched rows (concurrent delete)
  LRN-X2  learn              knowledge_service.update_note      regenerates embedding on title/content edit (rule 60 ordering)
  LRN-X3  learn              content_learning_engine            per-record loop isolates non-Integrity exceptions

These are DB-free static-introspection locks (the live behavioural ACs were
verified in-container at fix time: ACT-B1 approve(expired)->refused +
approve(live)->approved, ACT-B2 expired excluded / live present, LRN-X2
embedding before!=after on a content edit — see sprint retro). The locks fail
loudly if any guard is reverted.
"""
import inspect

import pytest


# --- ACT-B1 (act-with-approval): approve() refuses an expired pending row -----
def test_decide_guards_expiry_on_approve_only():
    from app.services.approval_service import ApprovalService
    import app.services.approval_service as mod

    # or_ must be importable in the module namespace (the guard needs it)
    assert getattr(mod, "or_", None) is not None, "approval_service must import sqlalchemy.or_"

    src = inspect.getsource(ApprovalService._decide)
    assert 'status == "approved"' in src, "_decide must branch on the approved status"
    assert "expires_at" in src and "or_(" in src, "_decide must add an expiry predicate"
    # reject path must stay un-gated: the expiry append is inside the approved branch
    approved_idx = src.index('if status == "approved"')
    or_idx = src.index("or_(", approved_idx)
    assert or_idx > approved_idx, "expiry guard must live inside the approved branch only"


# --- ACT-B2 (act-with-approval): list_pending excludes expired rows -----------
def test_list_pending_excludes_expired():
    from app.services.approval_service import ApprovalService

    src = inspect.getsource(ApprovalService.list_pending)
    assert "expires_at" in src and "or_(" in src, (
        "list_pending must filter out logically-expired-but-unswept pending rows"
    )
    assert ".is_(None)" in src, "expiry filter must allow NULL expires_at (never-expiring rows)"


# --- LRN-X1 (learn): run_experiment null-guards both re-fetched rows ----------
def test_run_experiment_null_guards_refetch():
    from app.services.experiment_service import ExperimentService

    src = inspect.getsource(ExperimentService.run_experiment)
    # Two re-fetches (completion + failure handler); both must guard None before
    # touching row.status, or a concurrent delete AttributeErrors and the
    # experiment is stuck "running".
    assert src.count("if row is None") >= 2, (
        "both the completion and failure re-fetch must guard a vanished row"
    )


# --- LRN-X2 (learn): update_note regenerates the embedding (rule-60 ordering) -
def test_update_note_regenerates_embedding_before_write_session():
    from app.services.knowledge_service import KnowledgeService

    src = inspect.getsource(KnowledgeService.update_note)
    assert "_generate_embedding" in src, "update_note must regenerate the embedding on edit"
    assert "row.embedding" in src, "update_note must assign the regenerated vector"
    # rule 60: the network embed call must happen BEFORE the write session that
    # sets row.embedding (no DB session held across the embedder await).
    embed_idx = src.index("_generate_embedding")
    write_session_idx = src.rindex("get_session()")
    assert embed_idx < write_session_idx, (
        "embedding must be computed before the write session (rule 60: no session across network await)"
    )


# --- LRN-X3 (learn): content batch isolates non-Integrity per-record errors ---
def test_content_outcomes_isolate_non_integrity_errors():
    from app.services.content_learning_engine import ContentLearningEngine

    src = inspect.getsource(ContentLearningEngine.process_content_outcomes)
    assert "except IntegrityError" in src, "the integrity-race fast-path must remain"
    # A broad per-record catch must follow so a re-raised OperationalError /
    # TimeoutError from record_outcome can't abort the whole batch.
    integ_idx = src.index("except IntegrityError")
    broad_idx = src.index("except Exception", integ_idx)
    assert broad_idx > integ_idx, "a broad per-record guard must follow the IntegrityError catch"
    assert "continue" in src[broad_idx:], "the broad guard must continue the batch, not abort it"
