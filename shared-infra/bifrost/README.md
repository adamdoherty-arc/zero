# Bifrost gateway — shared infra contract

[Bifrost](https://github.com/maximhq/bifrost) runs as **shared infrastructure**
in your docker stack — it is **not owned by Zero**. Zero talks to it the way
any client does: HTTP at `BIFROST_GATEWAY_URL` with OpenAI-compatible bodies.

## What lives in this dir

This is a **reference contract**, not a deployed config:

- `config.yaml` — the virtual-model / preset / alias map Zero expects the
  Bifrost gateway to honor. Drop this onto the shared Bifrost host (or use
  it as a checklist when editing the gateway's real config there). The
  contents mirror Zero's in-process `LlmRouter` so behavior is identical
  whether a call goes through the gateway or direct.

The file is here so Zero developers can audit / propose changes to the
shared gateway via PR, even when the gateway itself lives in a different
repo / cluster.

## How Zero calls Bifrost

1. Set `BIFROST_GATEWAY_URL` in the backend env (defaults to
   `http://bifrost:8080` when present in the docker network).
2. The `BifrostClient` in
   [`backend/app/infrastructure/bifrost_client.py`](../../backend/app/infrastructure/bifrost_client.py)
   wraps the gateway. Any service that wants gateway-mediated routing
   imports `get_bifrost_client()` and calls `complete()` with a hint or
   a real model name.
3. When `BIFROST_GATEWAY_URL` is unset the client reports
   `available=False` and callers fall back to the in-process provider
   path. No silent failures.

```python
from app.infrastructure.bifrost_client import get_bifrost_client

bifrost = get_bifrost_client()
if bifrost.is_available():
    text = await bifrost.complete(
        model="hint:summarize",
        messages=[{"role": "user", "content": "Summarize this meeting..."}],
    )
else:
    # Falls back to the in-process LlmRouter path
    ...
```

## Why the YAML still ships here

- **Versioning** — the contract evolves with Zero. PRs that add a new
  `hint:*` should update both `llm_hints.py` and `config.yaml` in the
  same change.
- **Bootstrap** — when standing up a new Bifrost instance, this file is
  the starter config.
- **Validation** — the test
  [`tests/test_bifrost_contract.py`](../../backend/tests/test_bifrost_contract.py)
  diff-checks the YAML against the in-process taxonomy so they can't
  drift.

## Switching presets

The preset is process-env-driven on both sides:

```bash
export ZERO_HINT_PRESET=everything_local
```

The in-process router reads it at call time; Bifrost reads its own
preset block once at admin reload. Trigger a Bifrost reload via the
gateway's admin API after flipping the env on shared infra.
