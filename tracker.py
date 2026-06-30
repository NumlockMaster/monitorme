#!/usr/bin/env python3
"""
MonitorMe - Claude Code hook handler.
Handles SessionStart, UserPromptSubmit, SessionEnd events.
Append-only event log for concurrency safety.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = BASE_DIR / "config.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"
PROJECTS_FILE = DATA_DIR / "projects.json"
ERRORS_FILE = DATA_DIR / "tracker_errors.log"


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"idle_threshold_minutes": 30}


def load_projects():
    try:
        with open(PROJECTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def append_event(event_data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event_data, ensure_ascii=False) + "\n")


def compute_category_summary(projects, idle_minutes, days=1):
    """Return a one-line group breakdown string for the last `days` days, or None if no data."""
    cutoff = datetime.now().replace(microsecond=0) - timedelta(days=days)
    try:
        events = []
        with open(EVENTS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if e.get("event") in ("session_start", "activity", "session_end"):
                    e["_dt"] = datetime.fromisoformat(e["ts"].replace("Z", ""))
                    if e["_dt"] >= cutoff:
                        events.append(e)
    except FileNotFoundError:
        return None

    if not events:
        return None

    by_session = defaultdict(list)
    for e in events:
        by_session[e["session_id"]].append(e)

    by_group = defaultdict(float)
    for evs in by_session.values():
        evs.sort(key=lambda e: e["_dt"])
        seg_start = seg_cwd = last_dt = None
        for e in evs:
            dt, cwd = e["_dt"], e.get("cwd", "")
            if e["event"] == "session_end":
                if seg_start and last_dt:
                    _add_hours(by_group, seg_cwd, seg_start, last_dt, projects)
                seg_start = seg_cwd = last_dt = None
                continue
            if seg_start is None:
                seg_start, seg_cwd, last_dt = dt, cwd, dt
                continue
            if (dt - last_dt).total_seconds() / 60 > idle_minutes:
                _add_hours(by_group, seg_cwd, seg_start, last_dt, projects)
                seg_start, seg_cwd = dt, cwd
            last_dt = dt
        if seg_start and last_dt:
            _add_hours(by_group, seg_cwd, seg_start, last_dt, projects)

    total = sum(by_group.values())
    if total < 0.001:
        return None

    # Load group order and emojis from config
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        group_meta = {g["name"]: g.get("emoji", "") for g in cfg.get("groups", [])}
        group_order = [g["name"] for g in cfg.get("groups", [])]
    except Exception:
        group_meta = {}
        group_order = []

    def sort_key(item):
        name, _ = item
        return group_order.index(name) if name in group_order else 999

    parts = [
        f"{grp} {round(h / total * 100)}%"
        for grp, h in sorted(by_group.items(), key=sort_key)
    ]
    total_h = int(total)
    total_m = int((total % 1) * 60)
    label = "today" if days == 1 else f"{days}d"
    return f"[MonitorMe] {label}: {' | '.join(parts)} — {total_h}h {total_m:02d}m"


def lookup_project(cwd, projects):
    if cwd in projects:
        return projects[cwd]
    cwd_lower = cwd.lower()
    best_key, best_len = None, 0
    for key in projects:
        key_lower = key.lower()
        if cwd_lower.startswith(key_lower + "\\") and len(key) > best_len:
            best_len = len(key)
            best_key = key
    return projects.get(best_key)


def _add_hours(by_group, cwd, start, end, projects):
    hours = (end - start).total_seconds() / 3600
    if hours < 1 / 3600:
        return
    info = lookup_project(cwd, projects)
    group = info["group"] if info and "group" in info else "Personal"
    by_group[group] += hours


def main():
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except Exception:
        return

    event_name = hook_input.get("hook_event_name", "")
    session_id = hook_input.get("session_id", "unknown")
    cwd = hook_input.get("cwd", os.getcwd())
    ts = datetime.now().isoformat()

    projects = load_projects()

    if event_name == "SessionStart":
        append_event({"ts": ts, "session_id": session_id, "cwd": cwd, "event": "session_start"})

        if not lookup_project(cwd, projects):
            config = load_config()
            cat_names = [c["name"] for c in config.get("categories", [])]
            categories = ", ".join(cat_names) if cat_names else "Learning, Training, Client Projects, MRR, Tools"
            print(
                f"[MONITORME] Unclassified project folder: {cwd}\n"
                f"Please ask the user: which project is this folder, and what category does it belong to?\n"
                f"Valid categories: {categories}\n"
                f"Once the user answers, run:\n"
                f'python "C:\\Projects\\monitorme\\classify.py" "{cwd}" "<ProjectName>" "<Category>"'
            )

    elif event_name == "UserPromptSubmit":
        append_event({"ts": ts, "session_id": session_id, "cwd": cwd, "event": "activity"})
        config = load_config()
        idle = config.get("idle_threshold_minutes", 30)
        days = config.get("status_bar_days", 1)
        summary = compute_category_summary(projects, idle, days=days)
        if summary:
            print(summary)
            status_file = DATA_DIR / "status.txt"
            status_file.write_text(summary, encoding="utf-8")

    elif event_name == "SessionEnd":
        append_event({"ts": ts, "session_id": session_id, "cwd": cwd, "event": "session_end"})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(ERRORS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat()} ERROR in {__file__}: {e}\n")
        except Exception:
            pass
    sys.exit(0)
