# MonitorMe

Automatic time tracker for [Claude Code](https://claude.ai/code) sessions. Tracks which project folders you work in, classifies them by category and group, and shows a live status bar + HTML dashboard.

![Status bar example](https://img.shields.io/badge/MonitorMe-7d%3A%20Production%2014%25%20%7C%20Development%2058%25%20%7C%20Personal%2019%25%20—%2020h%2032m-blue)

## How it works

Claude Code fires hooks on every session start, prompt submit, and session end. MonitorMe listens to those hooks, appends an event to `data/events.jsonl`, and prints a status bar summary to stdout (which Claude Code displays above the prompt).

```
[MonitorMe] 7d: Production 14% | Development 58% | Personal 19% — 20h 32m
```

## Setup

### 1. Install

Clone the repo anywhere you like:

```bash
git clone https://github.com/NumlockMaster/monitorme.git
cd monitorme
```

No dependencies beyond the Python standard library.

### 2. Create your data files

Copy the example files to get started:

```bash
cp data/projects.example.json data/projects.json
cp data/events.example.jsonl data/events.jsonl
```

Edit `data/projects.json` to map your project folders to names and categories:

```json
{
  "C:\\Projects\\my-saas": {
    "name": "My SaaS",
    "category": "MRR",
    "group": "Development"
  }
}
```

### 3. Wire up the hooks

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python C:\\path\\to\\monitorme\\tracker.py"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python C:\\path\\to\\monitorme\\tracker.py"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python C:\\path\\to\\monitorme\\tracker.py"
          }
        ]
      }
    ]
  }
}
```

### 4. Import history (optional)

If you have existing Claude Code sessions, import them:

```bash
python import_history.py
```

Use `--dry-run` to preview without writing.

## Usage

### Status bar

The status bar updates automatically on every prompt submit — no action needed.

### Dashboard

```bash
# Generate the HTML file
python generate_dashboard.py

# Serve it with live Save & Regenerate support
python serve.py
# Open http://localhost:7070
```

The dashboard has period filters (7d / 30d / 90d / all time), group and category breakdowns with target % markers, a project bar chart, activity calendar, and hour-of-week heatmap.

### Reports

```bash
python report.py              # all time
python report.py --days 7     # last 7 days
```

### Classify a new project folder

When MonitorMe sees an unclassified folder it will prompt you to classify it:

```bash
python classify.py "C:\Projects\my-project" "My Project" "MRR"
```

Categories are defined in `config.json`. Default categories: `Client Projects`, `MRR`, `Tools`, `Personal`, `Learning`, `Training`.

## Configuration

`config.json` controls groups, categories, colors, targets, and the status bar timeframe:

```json
{
  "idle_threshold_minutes": 30,
  "status_bar_days": 7,
  "groups": [
    { "name": "Production", "emoji": "💰", "color": "#2563eb" },
    { "name": "Development", "emoji": "🚀", "color": "#7c3aed" }
  ],
  "categories": [
    { "name": "MRR", "color": "#7C3AED", "target": 40 },
    { "name": "Client Projects", "color": "#2563EB", "target": 18 }
  ]
}
```

| Field | Description |
|---|---|
| `idle_threshold_minutes` | Gap between events that splits a session into two segments |
| `status_bar_days` | How many days the status bar covers (1 = today only) |
| `groups.target` | Target % shown as a marker on the dashboard bar |

## File structure

```
monitorme/
├── tracker.py              # Hook handler — logs events, prints status bar
├── classify.py             # CLI to map a folder to a project + category
├── generate_dashboard.py   # Builds dashboard.html from events + config
├── serve.py                # HTTP server for the dashboard (localhost:7070)
├── import_history.py       # One-time import from Claude Code transcripts
├── report.py               # Terminal report
├── config.json             # Groups, categories, colors, targets
└── data/
    ├── events.jsonl         # Append-only event log (gitignored)
    ├── projects.json        # Folder → project mapping (gitignored)
    ├── events.example.jsonl
    └── projects.example.json
```

`data/events.jsonl` and `data/projects.json` are gitignored — they contain your personal project paths and session history.
