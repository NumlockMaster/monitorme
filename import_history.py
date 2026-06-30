#!/usr/bin/env python3
"""
MonitorMe - Import historical sessions from Claude Code transcripts.

For each session JSONL file in ~/.claude/projects/, extracts:
- cwd (working directory = project folder)
- timestamps of user messages (used as activity heartbeats)

Writes synthetic events to data/events.jsonl.
Projects not yet in projects.json are listed as unclassified.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
EVENTS_FILE = DATA_DIR / "events.jsonl"
PROJECTS_FILE = DATA_DIR / "projects.json"
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

ACTIVITY_TYPES = {"user", "assistant"}


def load_projects():
    try:
        with open(PROJECTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_existing_session_ids():
    """Return set of session_ids already in events.jsonl to avoid duplicates."""
    ids = set()
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    sid = obj.get("session_id")
                    if sid:
                        ids.add(sid)
    except FileNotFoundError:
        pass
    return ids


def extract_session_events(jsonl_path):
    """
    Returns (session_id, cwd, list_of_timestamps) from a transcript file.
    Uses user/assistant message timestamps as activity heartbeats.
    """
    session_id = jsonl_path.stem
    cwd = None
    timestamps = []

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if cwd is None and "cwd" in obj:
                    cwd = obj["cwd"]

                if obj.get("type") in ACTIVITY_TYPES and "timestamp" in obj:
                    timestamps.append(obj["timestamp"])

    except Exception:
        pass

    return session_id, cwd, sorted(set(timestamps))


def main():
    dry_run = "--dry-run" in sys.argv

    existing_ids = load_existing_session_ids()
    projects = load_projects()

    sessions = []
    unclassified_cwds = set()

    print("Scanning Claude Code transcripts...")

    for proj_dir in sorted(CLAUDE_PROJECTS.iterdir()):
        if not proj_dir.is_dir():
            continue
        for jsonl_file in sorted(proj_dir.glob("*.jsonl")):
            session_id, cwd, timestamps = extract_session_events(jsonl_file)

            if not cwd or not timestamps:
                continue
            if session_id in existing_ids:
                continue

            sessions.append((session_id, cwd, timestamps))
            if cwd not in projects:
                unclassified_cwds.add(cwd)

    print(f"Found {len(sessions)} new sessions to import.")

    if unclassified_cwds:
        print(f"\n{len(unclassified_cwds)} unclassified project folders:")
        for cwd in sorted(unclassified_cwds):
            print(f"  {cwd}")
        print(
            "\nYou can classify them now or later with:\n"
            '  python "C:\\Projects\\monitorme\\classify.py" "<folder>" "<name>" "<category>"'
        )
        print()

    if dry_run:
        print("(dry run - no data written)")
        return

    confirm = input(f"Import {len(sessions)} sessions? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    events_written = 0

    with open(EVENTS_FILE, "a", encoding="utf-8") as f:
        for session_id, cwd, timestamps in sessions:
            # session_start
            f.write(json.dumps({
                "ts": timestamps[0],
                "session_id": session_id,
                "cwd": cwd,
                "event": "session_start",
                "source": "import"
            }, ensure_ascii=False) + "\n")
            events_written += 1

            # activity events for each message timestamp
            for ts in timestamps:
                f.write(json.dumps({
                    "ts": ts,
                    "session_id": session_id,
                    "cwd": cwd,
                    "event": "activity",
                    "source": "import"
                }, ensure_ascii=False) + "\n")
                events_written += 1

            # session_end
            f.write(json.dumps({
                "ts": timestamps[-1],
                "session_id": session_id,
                "cwd": cwd,
                "event": "session_end",
                "source": "import"
            }, ensure_ascii=False) + "\n")
            events_written += 1

    print(f"\nDone. Wrote {events_written} events for {len(sessions)} sessions.")
    print('Run: python "C:\\Projects\\monitorme\\report.py" to see your stats.')


if __name__ == "__main__":
    main()
