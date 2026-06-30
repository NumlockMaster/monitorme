#!/usr/bin/env python3
"""MonitorMe - Time tracking report generator."""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
EVENTS_FILE = DATA_DIR / "events.jsonl"
PROJECTS_FILE = DATA_DIR / "projects.json"
CONFIG_FILE = BASE_DIR / "config.json"

# Target % of total work time
CATEGORY_TARGETS = {
    "Learning": 20.0,
    "Training": 8.0,          # 10% of 80% dev time
    "Client Projects": 16.0,  # 20% of 80% dev time
    "MRR": 56.0,              # 70% of 80% dev time
    "Tools": None,
    "Personal": None,
}
DEV_CATEGORIES = {"Training", "Client Projects", "MRR", "Tools"}


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


def load_events():
    events = []
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except FileNotFoundError:
        pass
    return events


def parse_ts(ts_str):
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def parse_segments(events, idle_threshold_minutes):
    """
    Returns list of (cwd, start_dt, end_dt) work segments.
    Gaps > idle_threshold between consecutive activities split a segment.
    """
    by_session = defaultdict(list)
    for e in events:
        if e.get("event") in ("session_start", "activity", "session_end"):
            try:
                e["_dt"] = parse_ts(e["ts"])
            except Exception:
                continue
            by_session[e["session_id"]].append(e)

    segments = []

    for session_events in by_session.values():
        session_events.sort(key=lambda e: e["_dt"])

        seg_start = None
        seg_cwd = None
        last_dt = None

        for e in session_events:
            dt = e["_dt"]
            cwd = e.get("cwd", "")

            if e["event"] == "session_end":
                if seg_start is not None and last_dt is not None:
                    segments.append((seg_cwd, seg_start, last_dt))
                seg_start = None
                last_dt = None
                continue

            if seg_start is None:
                seg_start = dt
                seg_cwd = cwd
                last_dt = dt
                continue

            gap = (dt - last_dt).total_seconds() / 60

            if gap > idle_threshold_minutes:
                segments.append((seg_cwd, seg_start, last_dt))
                seg_start = dt
                seg_cwd = cwd

            last_dt = dt

        # Unclosed session: count up to last activity
        if seg_start is not None and last_dt is not None:
            segments.append((seg_cwd, seg_start, last_dt))

    return segments


def format_hours(h):
    total_minutes = int(h * 60)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{hh}h {mm:02d}m"


def main():
    # Optional --days N filter
    days_filter = None
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        try:
            days_filter = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("Usage: report.py [--days N]")
            sys.exit(1)

    config = load_config()
    idle_threshold = config.get("idle_threshold_minutes", 30)
    projects = load_projects()
    events = load_events()

    if not events:
        print("No tracking data yet. Start working and events will be logged automatically.")
        return

    if days_filter:
        cutoff = datetime.now() - timedelta(days=days_filter)
        events = [e for e in events if parse_ts(e["ts"]) >= cutoff]

    segments = parse_segments(events, idle_threshold)

    by_project = defaultdict(float)
    by_category = defaultdict(float)
    unclassified = set()

    for cwd, start, end in segments:
        hours = (end - start).total_seconds() / 3600
        if hours < 1 / 3600:
            continue

        if cwd in projects:
            name = projects[cwd]["name"]
            cat = projects[cwd]["category"]
        else:
            name = f"[?] {Path(cwd).name}"
            cat = "Unclassified"
            unclassified.add(cwd)

        by_project[name] += hours
        by_category[cat] += hours

    total_hours = sum(by_project.values())
    dev_hours = sum(h for cat, h in by_category.items() if cat in DEV_CATEGORIES)

    period = f"last {days_filter} days" if days_filter else "all time"
    print("=" * 54)
    print(f"  MonitorMe Report  ({period})")
    print("=" * 54)
    print(f"  Total tracked: {format_hours(total_hours)}\n")

    print("CATEGORIES  (% of total | target)")
    print("-" * 54)
    for cat in sorted(by_category, key=lambda c: -by_category[c]):
        hours = by_category[cat]
        pct = (hours / total_hours * 100) if total_hours > 0 else 0
        target = CATEGORY_TARGETS.get(cat)
        target_str = f"target {target:.0f}%" if target else "no target"
        if target:
            delta = pct - target
            flag = " OK" if abs(delta) <= target * 0.2 else (" LOW" if delta < 0 else " HIGH")
        else:
            flag = ""
        print(f"  {cat:<20} {format_hours(hours):>8}  {pct:>5.1f}%  [{target_str}]{flag}")

    if dev_hours > 0:
        print(f"\nDEVELOPMENT BREAKDOWN  (% of dev: {format_hours(dev_hours)})")
        print("-" * 54)
        for cat in sorted(DEV_CATEGORIES & by_category.keys(), key=lambda c: -by_category[c]):
            hours = by_category[cat]
            pct = (hours / dev_hours * 100) if dev_hours > 0 else 0
            print(f"  {cat:<20} {format_hours(hours):>8}  {pct:>5.1f}%")

    print(f"\nPROJECTS")
    print("-" * 54)
    for name in sorted(by_project, key=lambda p: -by_project[p]):
        hours = by_project[name]
        pct = (hours / total_hours * 100) if total_hours > 0 else 0
        print(f"  {name:<28} {format_hours(hours):>8}  {pct:>5.1f}%")

    if unclassified:
        print(f"\nUNCLASSIFIED FOLDERS ({len(unclassified)}) - classify with:")
        for folder in sorted(unclassified):
            print(f'  python "C:\\Projects\\monitorme\\classify.py" "{folder}" "<name>" "<category>"')


if __name__ == "__main__":
    main()
