"""Fix-131 (supervise run aa57faaf, 2026-06-30) coverage hardening — regression locks.

Per-domain coverage rotation (reason/respond/retrieve/reflect/index). Each shipped
fix is pinned by a DB-free static-introspection lock so it cannot silently regress.
Provenance: run aa57faaf, sprint Fix-131 #11381.

  RSN-7  reason  experiment_service.run_experiment  status check-then-set locks the
                                                     row FOR UPDATE (serialize concurrent
                                                     runs -> no double-execution)
  RSN-8  reason  experiment_service.design_experiment broadens the LLM-failure catch
                                                     beyond StructuredOutputError so a
                                                     network/gateway error degrades to the
                                                     manual-eval default instead of a 500
"""
import inspect


# --- RSN-7 (reason): run_experiment locks the row before the status guard -------
def test_run_experiment_locks_row_for_update_before_status_transition():
    from app.services.experiment_service import ExperimentService

    src = inspect.getsource(ExperimentService.run_experiment)
    # The status check-then-set (status not in (designed, failed) -> "running") is
    # a TOCTOU race: two concurrent run_experiment(exp_id) calls both read
    # "designed", both pass, both transition, executing the experiment twice. The
    # initial read must lock the row FOR UPDATE so the guard + transition are atomic.
    assert "with_for_update=True" in src, (
        "run_experiment must lock the experiment row FOR UPDATE before the "
        "status check-then-set (RSN-7) to serialize concurrent runs"
    )
    # The lock must be on the read that GUARDS the transition — i.e. it precedes
    # the `row.status = \"running\"` write, not on a later re-fetch.
    lock_idx = src.index("with_for_update=True")
    running_idx = src.index('row.status = "running"')
    assert lock_idx < running_idx, (
        "the FOR UPDATE lock must be acquired on the status-guard read, before "
        "the transition to running"
    )


# --- RSN-8 (reason): design_experiment degrades on ANY LLM failure, not 500 -----
def test_design_experiment_degrades_on_non_structured_llm_failure():
    from app.services.experiment_service import ExperimentService

    src = inspect.getsource(ExperimentService.design_experiment)
    # The StructuredOutputError fast-path (JSON parse failure) must remain...
    assert "except StructuredOutputError" in src, (
        "the StructuredOutputError parse-fallback must stay"
    )
    # ...but a broad catch must follow so a network/timeout/gateway failure
    # (raw provider exception, NOT StructuredOutputError) degrades to the same
    # manual-eval default and still persists the row, instead of escaping the
    # method as a raw 500 (the sibling run_experiment already does this).
    struct_idx = src.index("except StructuredOutputError")
    broad_idx = src.index("except Exception", struct_idx)
    assert broad_idx > struct_idx, (
        "a broad except must follow the StructuredOutputError catch (RSN-8) so a "
        "non-parse LLM failure can't escape design_experiment as a 500"
    )
    # The broad branch must still create the experiment row (the get_session
    # write block runs after the try/except, so the fallback design feeds it).
    assert 'session.add(row)' in src and 'get_session()' in src, (
        "design_experiment must still persist the row after a degraded design"
    )
