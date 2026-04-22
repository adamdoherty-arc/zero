#!/usr/bin/env bash
# Smoke-test every Reachy endpoint Zero ships after the harvest.
# Run after `docker compose up -d zero-api`. Exit code is the number of
# endpoints that came back non-OK, so CI can gate on it.
#
#   bash scripts/reachy_smoke_test.sh
#
# Pass ZERO_BASE_URL to point at a different host (e.g. a staging box).

set -u
BASE="${ZERO_BASE_URL:-http://localhost:18792}"
TOKEN="${ZERO_GATEWAY_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  TOKEN=$(grep "^ZERO_GATEWAY_TOKEN=" "$(dirname "$0")/../.env" 2>/dev/null | head -1 | cut -d= -f2-)
fi

if [ -z "$TOKEN" ]; then
  echo "ERR: no ZERO_GATEWAY_TOKEN (checked env and .env)"
  exit 99
fi

HDR=(-H "Authorization: Bearer $TOKEN")
FAIL=0
PASS=0

hit() {
  local method="$1" path="$2" expect="${3:-2}"  # 2 = any 2xx, 2|5 = any 2xx|5xx
  local resp
  resp=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${HDR[@]}" "$BASE$path")
  local first="${resp:0:1}"
  if echo "$expect" | grep -q "$first"; then
    printf "  \033[32mOK\033[0m   %-45s HTTP %s\n" "$method $path" "$resp"
    PASS=$((PASS+1))
  else
    printf "  \033[31mFAIL\033[0m %-45s HTTP %s\n" "$method $path" "$resp"
    FAIL=$((FAIL+1))
  fi
}

hit_json() {
  local method="$1" path="$2" body="$3" expect="${4:-2}"
  local resp
  resp=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${HDR[@]}" -H "Content-Type: application/json" -d "$body" "$BASE$path")
  local first="${resp:0:1}"
  if echo "$expect" | grep -q "$first"; then
    printf "  \033[32mOK\033[0m   %-45s HTTP %s\n" "$method $path" "$resp"
    PASS=$((PASS+1))
  else
    printf "  \033[31mFAIL\033[0m %-45s HTTP %s\n" "$method $path" "$resp"
    FAIL=$((FAIL+1))
  fi
}

echo "=== Wave 1 — Motion library ==="
hit GET  /api/reachy/motion/library
hit GET  "/api/reachy/motion/resolve?query=happy"
hit GET  "/api/reachy/motion/resolve?query=thank%20you"

echo "=== Wave 2 — Personas + gesture parser ==="
hit GET  /api/reachy/personas
hit_json POST /api/reachy/personas/select '{"persona_id":"cosmic_kitchen"}'
hit_json POST /api/reachy/gesture/parse '{"text":"Hi [emotion:happy]!"}'

echo "=== Waves 3/11/12 — Vision + wake word ==="
hit GET  /api/reachy/vision/backends
hit GET  /api/reachy/wake-word/status
hit GET  /api/reachy/camera/stream

echo "=== Wave 4 — Meeting mode ==="
hit GET  /api/reachy/presence/meeting
hit_json POST /api/reachy/presence/meeting/start '{"meeting_id":"smoke-test"}'
hit POST /api/reachy/presence/meeting/stop

echo "=== Wave 5 — Presence / pomodoro ==="
hit GET  /api/reachy/presence/pomodoro
hit_json POST /api/reachy/presence/pomodoro/start '{"focus_minutes":25,"break_minutes":5}'
hit POST /api/reachy/presence/pomodoro/stop

echo "=== Wave 6 — Home Assistant ==="
hit GET  /api/home-assistant/status
hit GET  /api/home-assistant/gesture-map

echo "=== Wave 10 — Move recorder ==="
hit GET  /api/reachy/moves/record/status
hit GET  /api/reachy/moves/user

echo "=== Wave 13 — Radio mode ==="
hit GET  /api/reachy/radio/status
hit_json POST /api/reachy/radio/start '{"bpm":120,"beats_per_dance":4}' 2
hit POST /api/reachy/radio/stop

echo "=== Wave 15 — Persona state ==="
hit GET  /api/reachy/personas/stats
hit POST /api/reachy/personas/stats/reset

echo "=== Wave 17 — Context hint ==="
hit GET  /api/reachy/context/hint

echo
echo "Passed: $PASS    Failed: $FAIL"
exit $FAIL
