#!/usr/bin/env python3
"""Classify a project folder for MonitorMe time tracking."""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PROJECTS_FILE = DATA_DIR / "projects.json"

VALID_CATEGORIES = {"Learning", "Training", "Client Projects", "MRR", "Tools", "Personal"}


def main():
    if len(sys.argv) != 4:
        print("Usage: classify.py <folder_path> <project_name> <category>")
        print(f"Categories: {', '.join(sorted(VALID_CATEGORIES))}")
        sys.exit(1)

    folder = sys.argv[1].rstrip("\\").rstrip("/")
    name = sys.argv[2]
    category = sys.argv[3]

    if category not in VALID_CATEGORIES:
        print(f"Invalid category: '{category}'")
        print(f"Valid categories: {', '.join(sorted(VALID_CATEGORIES))}")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    projects = {}
    if PROJECTS_FILE.exists():
        with open(PROJECTS_FILE, encoding="utf-8") as f:
            projects = json.load(f)

    projects[folder] = {"name": name, "category": category}

    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)

    print(f"Classified '{folder}'")
    print(f"  Project:  {name}")
    print(f"  Category: {category}")


if __name__ == "__main__":
    main()
