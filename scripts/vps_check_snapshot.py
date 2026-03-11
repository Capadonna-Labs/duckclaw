#!/usr/bin/env python3
"""Run on VPS: cd /home/capadonna/projects/Capadonna-Driller && python3 /tmp/vps_check_snapshot.py"""
import os
import sys
sys.path.insert(0, "/home/capadonna/projects/Capadonna-Driller")
os.chdir("/home/capadonna/projects/Capadonna-Driller")
os.environ.setdefault("IB_ENV", "live")

from services.account_snapshot_service import get_account_snapshot as get_snap

s = get_snap(host="127.0.0.1", port=4001, client_id=999, timeout=10)
if s:
    print("keys:", list(s.keys()))
    for k in s:
        if k.startswith("account_") and k not in ("account_summary", "account_values"):
            print("account_data", k, s[k])
    print("positions count", len(s.get("positions", [])))
else:
    print("snapshot None")
