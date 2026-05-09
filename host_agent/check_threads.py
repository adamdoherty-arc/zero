"""Attach to running python process's wake loop — call /wake/status and verify the thread is actually alive."""

import requests
import time

# Hit wake status — shows running=true but we need to confirm the thread
r = requests.get("http://localhost:18796/wake/status").json()
print("wake/status:", r)

# Then let's see if log has heartbeat
with open("host_agent.log", "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()
heartbeats = [l for l in lines if "heartbeat" in l.lower()]
print(f"heartbeat lines: {len(heartbeats)}")
scans = [l for l in lines if "scan_heard" in l or "scan_silent" in l]
print(f"scan lines: {len(scans)}")
errs = [l for l in lines if "error" in l.lower() or "warning" in l.lower() or "crashed" in l.lower()]
print(f"error/warning/crashed lines: {len(errs)}")
for l in errs[-5:]:
    print(" ", l.rstrip())
