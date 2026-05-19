#!/usr/bin/env python3
"""
bifrost_vk_rebind.py — repair / migrate Bifrost virtual-key bindings.

Why this exists:
    Bifrost's PUT /api/governance/virtual-keys/{id} silently strips the
    `keys` binding from each provider_config unless `key_ids` is included
    in the body. After ANY VK edit that doesn't pass `key_ids`, every
    chat call fails with `no keys found for provider X` and the model
    quietly disappears from /v1/models. This script:
      1. Re-binds every VK's provider_configs to the full set of
         currently-registered provider keys.
      2. Optionally adds a model to a provider's `allowed_models` list.

Usage:
    python scripts/bifrost_vk_rebind.py                    # rebind all VKs
    python scripts/bifrost_vk_rebind.py --vk zero-prod     # one VK
    python scripts/bifrost_vk_rebind.py --add-model moonshot/moonshot-v1-32k-vision-preview

Env:
    BIFROST_URL  default http://localhost:4445
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


BIFROST_URL = os.environ.get("BIFROST_URL", "http://localhost:4445").rstrip("/")


def _http(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BIFROST_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vk", help="restrict to a single VK name")
    ap.add_argument("--add-model", help="add 'provider/model' to allowed_models")
    ap.add_argument("--dry-run", action="store_true", help="show changes without applying")
    args = ap.parse_args()

    add_prov, add_model = None, None
    if args.add_model:
        if "/" not in args.add_model:
            sys.exit("--add-model must be 'provider/model'")
        add_prov, add_model = args.add_model.split("/", 1)

    # Collect provider -> [key_id] from /api/providers/{p}/keys
    provider_keys: dict[str, list[str]] = {}
    for prov in ("vllm-local", "vllm-vlm", "embed-local", "moonshot"):
        try:
            d = _http("GET", f"/api/providers/{prov}/keys")
            provider_keys[prov] = [k["id"] for k in d.get("keys", [])]
        except SystemExit:
            provider_keys[prov] = []

    vks = _http("GET", "/api/governance/virtual-keys").get("virtual_keys", [])
    for vk in vks:
        if args.vk and vk.get("name") != args.vk:
            continue
        print(f"==> {vk['name']} ({vk['id']})")

        new_pcs = []
        for pc in vk.get("provider_configs", []):
            prov = pc.get("provider")
            allowed = list(pc.get("allowed_models") or [])
            if add_prov == prov and add_model and add_model not in allowed:
                allowed.append(add_model)
            new_pcs.append({
                "id": pc.get("id"),
                "provider": prov,
                "weight": pc.get("weight"),
                "allowed_models": allowed,
                "key_ids": provider_keys.get(prov, []),
            })

        body = {
            "name": vk["name"],
            "description": vk.get("description") or "rebound by bifrost_vk_rebind.py",
            "is_active": True,
            "provider_configs": new_pcs,
        }

        if args.dry_run:
            for pc in new_pcs:
                print(f"    DRY {pc['provider']:<14} key_ids={len(pc['key_ids'])} allowed={pc['allowed_models']}")
            continue

        result = _http("PUT", f"/api/governance/virtual-keys/{vk['id']}", body)
        for pc in result.get("virtual_key", {}).get("provider_configs", []):
            print(f"    {pc['provider']:<14} keys={len(pc.get('keys') or [])} allowed={pc.get('allowed_models')}")


if __name__ == "__main__":
    main()
