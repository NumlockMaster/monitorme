#!/usr/bin/env python3
"""Generate MonitorMe HTML dashboard with embedded data."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, date
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
EVENTS_FILE = DATA_DIR / "events.jsonl"
PROJECTS_FILE = DATA_DIR / "projects.json"
CONFIG_FILE = BASE_DIR / "config.json"
OUTPUT_FILE = BASE_DIR / "dashboard.html"

DEV_CATEGORIES = {"Training", "Client Projects", "MRR", "Tools"}
WEEKDAY_LABELS   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Data loading ──────────────────────────────────────────────────────────────

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
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    ts = e["ts"].replace("Z", "")
                    e["_dt"] = datetime.fromisoformat(ts)
                    events.append(e)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    return events


# ── Segment parsing ───────────────────────────────────────────────────────────

def parse_segments(events, idle_minutes):
    by_session = defaultdict(list)
    for e in events:
        if e.get("event") in ("session_start", "activity", "session_end"):
            by_session[e["session_id"]].append(e)

    segments = []
    for evs in by_session.values():
        evs.sort(key=lambda e: e["_dt"])
        seg_start = seg_cwd = last_dt = None

        for e in evs:
            dt, cwd = e["_dt"], e.get("cwd", "")
            if e["event"] == "session_end":
                if seg_start and last_dt:
                    segments.append((seg_cwd, seg_start, last_dt))
                seg_start = seg_cwd = last_dt = None
                continue
            if seg_start is None:
                seg_start, seg_cwd, last_dt = dt, cwd, dt
                continue
            if (dt - last_dt).total_seconds() / 60 > idle_minutes:
                segments.append((seg_cwd, seg_start, last_dt))
                seg_start, seg_cwd = dt, cwd
            last_dt = dt

        if seg_start and last_dt:
            segments.append((seg_cwd, seg_start, last_dt))

    return segments


# ── Stats computation ─────────────────────────────────────────────────────────

def compute_stats(segments, activity_events, projects, config, cutoff=None):
    if cutoff:
        segments       = [(c, s, e) for c, s, e in segments if e >= cutoff]
        activity_events = [e for e in activity_events if e["_dt"] >= cutoff]

    groups_cfg = config.get("groups", [])
    group_colors = {g["name"]: g["color"] for g in groups_cfg}
    group_emojis = {g["name"]: g.get("emoji", "") for g in groups_cfg}
    default_group = groups_cfg[0]["name"] if groups_cfg else "Unclassified"

    cat_cfgs       = config.get("categories", [])
    CATEGORY_COLORS  = {c["name"]: c.get("color", "#64748b") for c in cat_cfgs}
    CATEGORY_TARGETS = {c["name"]: c["target"] for c in cat_cfgs if "target" in c}

    by_project   = defaultdict(float)
    by_category  = defaultdict(float)
    by_group     = defaultdict(float)
    daily        = defaultdict(float)
    group_daily  = defaultdict(lambda: defaultdict(float))
    cat_daily    = defaultdict(lambda: defaultdict(float))

    def lookup(cwd):
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

    def cwd_info(cwd):
        p = lookup(cwd)
        if p:
            return p["name"], p["category"], p.get("group", default_group)
        return f"[?] {Path(cwd).name}", "Unclassified", default_group

    for cwd, start, end in segments:
        hours = (end - start).total_seconds() / 3600
        if hours < 1 / 3600:
            continue
        name, cat, grp = cwd_info(cwd)
        by_project[name]  += hours
        by_category[cat]  += hours
        by_group[grp]     += hours

        cur = start.date()
        while cur <= end.date():
            day_s = datetime.combine(cur, datetime.min.time())
            day_e = datetime.combine(cur + timedelta(days=1), datetime.min.time())
            overlap = (min(end, day_e) - max(start, day_s)).total_seconds() / 3600
            if overlap > 0:
                daily[str(cur)]          += overlap
                group_daily[grp][str(cur)] += overlap
                cat_daily[cat][str(cur)]   += overlap
            cur += timedelta(days=1)

    hour_matrix = [[0] * 24 for _ in range(7)]
    for e in activity_events:
        dt = e["_dt"]
        hour_matrix[dt.weekday()][dt.hour] += 1

    total     = sum(by_project.values())
    dev_total = sum(h for c, h in by_category.items() if c in DEV_CATEGORIES)

    name_to_cat   = {info["name"]: info["category"] for info in projects.values()}
    name_to_group = {info["name"]: info.get("group", "Building") for info in projects.values()}

    def largest_remainder(items):
        raw    = [x["pct"] for x in items]
        floors = [int(p) for p in raw]
        needed = 100 - sum(floors)
        order  = sorted(range(len(raw)), key=lambda i: -(raw[i] - floors[i]))
        for i in range(max(0, needed)):
            floors[order[i]] += 1
        for i, item in enumerate(items):
            item["pct"] = floors[i]

    cats = [
        {
            "name":   cat,
            "hours":  round(h, 2),
            "pct":    round(h / total * 100, 1) if total else 0,
            "target": CATEGORY_TARGETS.get(cat),
            "color":  CATEGORY_COLORS.get(cat, "#6b7280"),
        }
        for cat, h in sorted(by_category.items(), key=lambda x: -x[1])
    ]
    if cats and total:
        largest_remainder(cats)

    groups_order = [g["name"] for g in groups_cfg]
    grps = [
        {
            "name":   grp,
            "hours":  round(h, 2),
            "pct":    round(h / total * 100, 1) if total else 0,
            "color":  group_colors.get(grp, "#6b7280"),
            "emoji":  group_emojis.get(grp, ""),
        }
        for grp, h in sorted(
            by_group.items(),
            key=lambda x: groups_order.index(x[0]) if x[0] in groups_order else 999,
        )
    ]
    if grps and total:
        largest_remainder(grps)

    projs = [
        {
            "name":     name,
            "hours":    round(h, 2),
            "pct":      round(h / total * 100, 1) if total else 0,
            "category": name_to_cat.get(name, "Unclassified"),
            "group":    name_to_group.get(name, default_group),
            "color":    CATEGORY_COLORS.get(name_to_cat.get(name, "Unclassified"), "#6b7280"),
        }
        for name, h in sorted(by_project.items(), key=lambda x: -x[1])
    ]

    group_daily_list = [
        {"name": g["name"], "color": g["color"],
         "daily": {k: round(v, 2) for k, v in group_daily.get(g["name"], {}).items()}}
        for g in grps
    ]
    cat_daily_list = [
        {"name": c["name"], "color": c["color"],
         "daily": {k: round(v, 2) for k, v in cat_daily.get(c["name"], {}).items()}}
        for c in cats
    ]

    return {
        "total_hours":      round(total, 2),
        "dev_hours":        round(dev_total, 2),
        "categories":       cats,
        "groups":           grps,
        "projects":         projs,
        "daily":            {k: round(v, 2) for k, v in daily.items()},
        "hour_matrix":      hour_matrix,
        "group_daily_list": group_daily_list,
        "cat_daily_list":   cat_daily_list,
    }


# ── HTML template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MonitorMe Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"
        integrity="sha384-e6nUZLBkQ86NJ6TVVKAeSaK8jWa3NhkYWZFomE39AvDbQWeie9PlQqM3pmYW5d1g"
        crossorigin="anonymous"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:      #f1f5f9;
    --surface: #ffffff;
    --border:  #e2e8f0;
    --text:    #0f172a;
    --muted:   #64748b;
    --accent:  #2563eb;
    --radius:  14px;
    --shadow:  0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.05);
  }
  body { background: var(--bg); color: var(--text);
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
         font-size: 14px; min-height: 100vh; padding: 28px 32px; }
  h1   { font-size: 26px; font-weight: 800; letter-spacing: -.5px; color: #fff; }
  h2   { font-size: 11px; font-weight: 700; text-transform: uppercase;
         letter-spacing: .1em; color: var(--muted); margin-bottom: 18px; }

  header {
    background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
    border-radius: var(--radius);
    padding: 20px 26px;
    display: flex; align-items: center; gap: 16px; margin-bottom: 24px; flex-wrap: wrap;
    box-shadow: 0 4px 24px rgba(37,99,235,.35);
  }
  .subtitle { color: rgba(255,255,255,.75); font-size: 12px; margin-top: 3px; }

  .header-actions { display: flex; gap: 8px; margin-left: auto; align-items: center; }

  .filters { display: flex; gap: 6px; }
  .filters button {
    background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.3);
    color: rgba(255,255,255,.9); padding: 6px 16px; border-radius: 8px;
    cursor: pointer; font-size: 12px; font-weight: 500; transition: all .15s;
  }
  .filters button.active { background: #fff; border-color: #fff; color: var(--accent); font-weight: 700; }
  .filters button:hover:not(.active) { background: rgba(255,255,255,.28); color: #fff; }

  .btn-settings {
    background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.3);
    color: rgba(255,255,255,.9); padding: 6px 14px; border-radius: 8px;
    cursor: pointer; font-size: 12px; font-weight: 500; transition: all .15s;
    display: flex; align-items: center; gap: 6px;
  }
  .btn-settings:hover { background: rgba(255,255,255,.28); }

  .kpis { display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }
  .kpi  { background: var(--surface); border-radius: var(--radius);
           box-shadow: var(--shadow); padding: 18px 22px; flex: 1; min-width: 140px;
           border-top: 3px solid transparent; transition: transform .15s, box-shadow .15s; }
  .kpi:hover { transform: translateY(-2px); box-shadow: 0 6px 24px rgba(0,0,0,.1); }
  .kpi:nth-child(1) { border-top-color: #475569; }
  .kpi:nth-child(2) { border-top-color: #2563eb; }
  .kpi:nth-child(3) { border-top-color: #7c3aed; }
  .kpi:nth-child(4) { border-top-color: #0891b2; }
  .kpi:nth-child(5) { border-top-color: #db2777; }
  .kpi-value  { font-size: 26px; font-weight: 800; line-height: 1; color: var(--text); }
  .kpi-label  { color: var(--muted); font-size: 11px; margin-top: 5px; font-weight: 500; }
  .kpi-badge  { font-size: 11px; padding: 3px 9px; border-radius: 99px; margin-top: 8px;
                display: inline-block; font-weight: 600; }
  .badge-high { background: #fef2f2; color: #dc2626; }
  .badge-low  { background: #eff6ff; color: #2563eb; }
  .badge-ok   { background: #eff6ff; color: #0891b2; }

  .grid { display: grid; gap: 18px;
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
  .card { background: var(--surface); border-radius: var(--radius);
          box-shadow: var(--shadow); padding: 22px; }
  .card.wide  { grid-column: span 2; }
  .card.full  { grid-column: 1 / -1; }

  /* Group / category bars */
  .group-row { margin-bottom: 18px; }
  .group-label { display: flex; justify-content: space-between; margin-bottom: 7px;
                 font-size: 13px; font-weight: 600; }
  .group-track { background: #f1f5f9; border-radius: 99px; height: 10px;
                 position: relative; overflow: visible; }
  .group-fill  { height: 10px; border-radius: 99px; transition: width .5s; }
  .group-tgt   { position: absolute; top: -4px; width: 2px; height: 18px;
                 background: #475569; border-radius: 2px; }
  .group-meta  { font-size: 11px; color: var(--muted); margin-top: 6px; }



  /* Activity calendar */
  #cal-wrap { overflow-x: auto; padding-bottom: 8px; }
  .cal-grid { display: inline-grid; grid-auto-flow: column;
              grid-template-rows: repeat(7, 13px); gap: 3px; }
  .cal-cell { width: 13px; height: 13px; border-radius: 3px; cursor: default; }
  .cal-labels { display: flex; gap: 3px; margin-top: 6px; font-size: 10px; color: var(--muted); }
  .cal-day-labels { display: grid; grid-template-rows: repeat(7,13px); gap:3px;
                    margin-right: 6px; font-size: 10px; color: var(--muted); line-height: 13px; }

  /* Hour heatmap */
  .hm-wrap   { overflow-x: auto; }

  /* Tooltip */
  .tip { position: fixed; background: #1e293b; color: #f8fafc;
         padding: 7px 12px; border-radius: 8px; font-size: 12px; font-weight: 500;
         pointer-events: none; opacity: 0; transition: opacity .1s; z-index: 99;
         box-shadow: 0 4px 16px rgba(0,0,0,.25); }

  /* ── Settings panel ───────────────────────────────────────────────────────── */
  .overlay {
    position: fixed; inset: 0; background: rgba(15,23,42,.45); z-index: 100;
    display: none; align-items: flex-start; justify-content: flex-end;
  }
  .overlay.open { display: flex; }
  .panel {
    background: #fff; width: 560px; max-width: 100vw; height: 100vh;
    overflow-y: auto; padding: 28px 28px 40px;
    box-shadow: -4px 0 32px rgba(0,0,0,.15);
  }
  .panel h3 { font-size: 18px; font-weight: 800; margin-bottom: 6px; }
  .panel p  { font-size: 12px; color: var(--muted); margin-bottom: 24px; }

  .panel-section { margin-bottom: 32px; }
  .panel-section h4 { font-size: 11px; font-weight: 700; text-transform: uppercase;
                      letter-spacing: .1em; color: var(--muted); margin-bottom: 14px;
                      padding-bottom: 8px; border-bottom: 1px solid var(--border); }

  .proj-row {
    display: grid; grid-template-columns: 1fr 160px 160px; gap: 8px;
    align-items: center; padding: 8px 0; border-bottom: 1px solid #f8fafc; font-size: 12px;
  }
  .proj-row:last-child { border-bottom: none; }
  .proj-name { font-weight: 600; color: var(--text); }
  .proj-path { font-size: 10px; color: var(--muted); margin-top: 2px; word-break: break-all; }

  select.proj-select {
    border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px;
    font-size: 11px; color: var(--text); background: #f8fafc; width: 100%;
    cursor: pointer;
  }
  select.proj-select:focus { outline: 2px solid var(--accent); border-color: transparent; }

  .col-labels {
    display: grid; grid-template-columns: 1fr 160px 160px; gap: 8px;
    font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase;
    letter-spacing: .06em; margin-bottom: 6px;
  }

  .save-bar {
    position: sticky; bottom: 0; background: #fff; border-top: 1px solid var(--border);
    padding: 16px 0 0; margin-top: 24px; display: flex; gap: 10px; align-items: center;
  }
  .btn-primary {
    background: var(--accent); color: #fff; border: none; padding: 10px 22px;
    border-radius: 9px; font-size: 13px; font-weight: 700; cursor: pointer; transition: opacity .15s;
  }
  .btn-primary:hover { opacity: .85; }
  .btn-secondary {
    background: #f1f5f9; color: var(--text); border: none; padding: 10px 18px;
    border-radius: 9px; font-size: 13px; font-weight: 600; cursor: pointer;
  }
  .save-hint { font-size: 11px; color: var(--muted); margin-left: 4px; }
  .save-ok   { font-size: 12px; color: #0891b2; font-weight: 600; display: none; }
</style>
</head>
<body>

<div class="tip" id="tip"></div>

<!-- Settings overlay -->
<div class="overlay" id="overlay" onclick="if(event.target===this)closeSettings()">
  <div class="panel" id="panel">
    <h3>⚙️ Settings</h3>
    <p>Assign each project a category and group. Click Save to download the updated projects.json, then replace <code>C:\Projects\monitorme\data\projects.json</code> and regenerate the dashboard.</p>
    <div class="panel-section">
      <h4>Status Bar</h4>
      <div style="display:flex;align-items:center;gap:10px;font-size:12px">
        <label for="status-days" style="color:var(--text);font-weight:500">Timeframe (days)</label>
        <input id="status-days" type="number" min="1" max="90"
          style="width:70px;border:1px solid var(--border);border-radius:7px;padding:5px 8px;font-size:12px;color:var(--text)"
          oninput="editedConfig.status_bar_days = parseInt(this.value)||1">
        <span style="color:var(--muted)">1 = today only, 7 = last week</span>
      </div>
    </div>
    <div class="panel-section">
      <h4>Groups</h4>
      <div id="group-rename-list"></div>
    </div>
    <div class="panel-section">
      <h4>Categories</h4>
      <div id="cat-rename-list"></div>
    </div>
    <div class="panel-section">
      <h4>Projects</h4>
      <div class="col-labels">
        <span>Project</span><span>Category</span><span>Group</span>
      </div>
      <div id="proj-list"></div>
    </div>
    <div class="save-bar">
      <button id="btn-save-regen" class="btn-primary" onclick="saveAndRegenerate()">⚡ Save &amp; Regenerate</button>
      <button class="btn-secondary" onclick="saveSettings()">⬇ Download files</button>
      <button class="btn-secondary" onclick="closeSettings()">Cancel</button>
      <span class="save-ok" id="save-ok"></span>
    </div>
  </div>
</div>

<header>
  <div>
    <h1>MonitorMe</h1>
    <div class="subtitle" id="subtitle"></div>
  </div>
  <div class="header-actions">
    <div class="filters">
      <button onclick="setPeriod('7d')">7d</button>
      <button onclick="setPeriod('30d')">30d</button>
      <button onclick="setPeriod('90d')">90d</button>
      <button class="active" onclick="setPeriod('all')">All time</button>
    </div>
    <button class="btn-settings" onclick="openSettings()">⚙️ Settings</button>
  </div>
</header>

<div class="kpis" id="kpis"></div>

<div class="grid">
  <div class="card">
    <h2>Groups</h2>
    <div id="groups"></div>
  </div>

  <div class="card">
    <h2>Categories</h2>
    <div id="categories"></div>
  </div>

  <div class="card full">
    <h2>Projects</h2>
    <canvas id="projects" height="200"></canvas>
  </div>

  <div class="card full">
    <h2>Activity Calendar</h2>
    <div style="display:flex">
      <div class="cal-day-labels" id="cal-day-labels"></div>
      <div id="cal-wrap"><div class="cal-grid" id="calendar"></div></div>
    </div>
  </div>

  <div class="card full">
    <h2>Hour of Week Heatmap</h2>
    <div class="hm-wrap" id="hm-wrap"></div>
  </div>

  <div class="card full">
    <h2>Groups — Activity Calendar</h2>
    <div id="group-cal-wrap"></div>
  </div>

  <div class="card full">
    <h2>Categories — Activity Calendar</h2>
    <div id="cat-cal-wrap"></div>
  </div>
</div>

<script>
const DATA     = /*DASHBOARD_DATA*/;
const PROJECTS = /*PROJECTS_DATA*/;
const CONFIG   = /*CONFIG_DATA*/;
const tip      = document.getElementById('tip');

let projChart;
let currentPeriod = 'all';

function fmtH(h) {
  const m = Math.round(h * 60);
  return `${Math.floor(m/60)}h ${String(m%60).padStart(2,'0')}m`;
}
function lerp(a, b, t) { return a + (b - a) * t; }
function hexToRgb(hex) {
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return [r,g,b];
}
function blendColor(hex, t) {
  const [r,g,b] = hexToRgb(hex);
  return `rgb(${Math.round(lerp(241,r,t))},${Math.round(lerp(245,g,t))},${Math.round(lerp(249,b,t))})`;
}

function showTip(e, text) {
  tip.textContent = text;
  tip.style.opacity = '1';
  tip.style.left = (e.clientX + 12) + 'px';
  tip.style.top  = (e.clientY + 12) + 'px';
}
function hideTip() { tip.style.opacity = '0'; }

function renderKPIs(d) {
  const total  = d.total_hours;
  const groups = d.groups;
  const earning = groups.find(g => g.name === 'Earning now');
  const building = groups.find(g => g.name === 'Building');

  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="kpi-value">${fmtH(total)}</div><div class="kpi-label">Total tracked</div></div>
    ${earning ? `<div class="kpi"><div class="kpi-value" style="color:${earning.color}">${fmtH(earning.hours)}</div>
      <div class="kpi-label">${earning.emoji} Earning now (${earning.pct}%)</div></div>` : ''}
    ${building ? `<div class="kpi"><div class="kpi-value" style="color:${building.color}">${fmtH(building.hours)}</div>
      <div class="kpi-label">${building.emoji} Building (${building.pct}%)</div></div>` : ''}
    <div class="kpi"><div class="kpi-value">${d.categories.length}</div><div class="kpi-label">Categories active</div></div>
    <div class="kpi"><div class="kpi-value">${d.projects.length}</div><div class="kpi-label">Projects tracked</div></div>
  `;
}

function renderBarRow(item, totalHours) {
  const pct    = item.pct || 0;
  const target = item.target || null;
  const over   = target && pct > target * 1.2;
  const under  = target && pct < target * 0.8;
  const barColor = over ? '#dc2626' : under ? '#2563eb' : item.color;

  const pctLabel = target
    ? `<span style="color:${barColor};font-weight:700">${pct}%</span><span style="color:var(--muted)"> / ${target}%</span>`
    : `<span style="color:${item.color};font-weight:700">${pct}%</span>`;

  const tgtH = target ? totalHours * target / 100 : null;
  const hoursLabel = tgtH != null
    ? `${fmtH(item.hours)} <span style="color:var(--muted)">/ ${fmtH(tgtH)} planned</span>`
    : fmtH(item.hours);

  const tgtMarker = target != null
    ? `<div class="group-tgt" style="left:${Math.min(target, 99)}%"></div>`
    : '';

  return `
    <div class="group-row">
      <div class="group-label">
        <span style="color:${item.color}">${item.emoji ? item.emoji + ' ' : ''}${item.name}</span>
        <span style="font-size:13px">${pctLabel}</span>
      </div>
      <div class="group-track">
        <div class="group-fill" style="width:${Math.min(pct,100)}%;background:${barColor}"></div>
        ${tgtMarker}
      </div>
      <div class="group-meta">${hoursLabel}</div>
    </div>`;
}

function renderGroups(d) {
  document.getElementById('groups').innerHTML =
    d.groups.map(g => renderBarRow(g, d.total_hours)).join('');
}

function renderCategories(d) {
  document.getElementById('categories').innerHTML =
    d.categories.map(c => renderBarRow(c, d.total_hours)).join('');
}

function renderProjects(d) {
  const ctx = document.getElementById('projects').getContext('2d');
  if (projChart) projChart.destroy();
  const top = d.projects.slice(0, 20);
  projChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: top.map(p=>p.name),
      datasets: [{
        data:            top.map(p=>p.hours),
        backgroundColor: top.map(p=>p.color + 'cc'),
        borderColor:     top.map(p=>p.color),
        borderWidth:     1,
        borderRadius:    4,
      }]
    },
    options: {
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` ${fmtH(ctx.raw)}  (${d.projects[ctx.dataIndex].pct}%)  · ${d.projects[ctx.dataIndex].category} · ${d.projects[ctx.dataIndex].group}`
          }
        }
      },
      scales: {
        x: { ticks: { color:'#94a3b8', callback: v=>fmtH(v) }, grid: { color:'#f1f5f9' } },
        y: { ticks: { color:'#475569', font:{size:11} }, grid: { display:false } }
      }
    }
  });
}

function renderCalendar(d, period) {
  const grid = document.getElementById('calendar');
  const dayLabels = document.getElementById('cal-day-labels');
  grid.innerHTML = '';
  dayLabels.innerHTML = ['M','T','W','T','F','S','S'].map(l=>`<div>${l}</div>`).join('');

  const today  = new Date();
  const lookback = period === '7d' ? 7 : period === '30d' ? 30 : period === '90d' ? 90 : 365;
  const start  = new Date(today); start.setDate(today.getDate() - (lookback - 1));
  start.setDate(start.getDate() - ((start.getDay()+6)%7));

  const maxH = Math.max(...Object.values(d.daily), 0.01);

  let cur = new Date(start);
  while (cur <= today) {
    const key = cur.toISOString().slice(0,10);
    const h   = d.daily[key] || 0;
    const t   = Math.sqrt(h / maxH);
    const bg  = h === 0 ? '#e2e8f0' : blendColor('#2563eb', t);
    const cell = document.createElement('div');
    cell.className = 'cal-cell';
    cell.style.background = bg;
    cell.addEventListener('mousemove', e => showTip(e, `${key}: ${fmtH(h)}`));
    cell.addEventListener('mouseleave', hideTip);
    grid.appendChild(cell);
    cur.setDate(cur.getDate()+1);
  }
}

function renderHeatmap(d) {
  const wrap = document.getElementById('hm-wrap');
  const mat  = d.hour_matrix;
  const maxV = Math.max(...mat.flat(), 1);
  const days  = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  const hours = Array.from({length:24},(_,i)=>i);

  let html = '<table style="border-collapse:separate;border-spacing:2px;width:100%">';
  html += '<tr><th style="width:36px"></th>';
  hours.forEach(h => {
    html += `<th style="font-size:9px;color:#94a3b8;text-align:center;width:3.8%">${h%3===0?h+':00':''}</th>`;
  });
  html += '</tr>';
  days.forEach((day, di) => {
    html += `<tr><td style="font-size:10px;color:#94a3b8;font-weight:500;padding-right:6px;white-space:nowrap">${day}</td>`;
    hours.forEach(h => {
      const v = mat[di][h];
      const t = Math.sqrt(v / maxV);
      const bg = v === 0 ? '#e2e8f0' : blendColor('#7c3aed', t);
      html += `<td style="background:${bg};border-radius:3px;height:20px;cursor:default"
        onmousemove="showTip(event,'${day} ${h}:00 — ${v} sessions')"
        onmouseleave="hideTip()"></td>`;
    });
    html += '</tr>';
  });
  html += '</table>';
  wrap.innerHTML = html;
}

function renderBlendedCalendar(containerId, items, period) {
  const wrap = document.getElementById(containerId);
  if (!items || !items.length) { wrap.innerHTML = ''; return; }

  const today = new Date();
  const start = new Date(today);
  const lookback = period === '7d' ? 7 : period === '30d' ? 30 : period === '90d' ? 90 : 365;
  start.setDate(today.getDate() - (lookback - 1));

  // Sum hours per day across all items
  const dayTotals = {};
  for (const item of items) {
    for (const [day, h] of Object.entries(item.daily)) {
      dayTotals[day] = (dayTotals[day] || 0) + h;
    }
  }
  const maxH = Math.max(...Object.values(dayTotals), 0.01);

  let cells = '';
  let cur = new Date(start);
  while (cur <= today) {
    const key = cur.toISOString().slice(0, 10);
    const total = dayTotals[key] || 0;
    const t = Math.sqrt(total / maxH);

    // Dominant item = the one with most hours this day
    let domColor = '#6b7280';
    let domH = 0;
    for (const item of items) {
      const h = item.daily[key] || 0;
      if (h > domH) { domH = h; domColor = item.color; }
    }

    const bg = total === 0 ? '#e2e8f0' : blendColor(domColor, t);

    const breakdown = items
      .map(item => ({ name: item.name, h: item.daily[key] || 0 }))
      .filter(x => x.h > 0)
      .sort((a, b) => b.h - a.h)
      .map(x => `${x.name}: ${fmtH(x.h)}`)
      .join(' | ');
    const label = total > 0 ? `${key}: ${fmtH(total)} — ${breakdown}` : '';

    cells += `<div style="width:10px;height:10px;border-radius:2px;background:${bg};cursor:default"
      ${total > 0 ? `onmousemove="showTip(event,'${label}')" onmouseleave="hideTip()"` : ''}></div>`;
    cur.setDate(cur.getDate() + 1);
  }

  const legend = items.map(item =>
    `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;font-size:10px;color:${item.color}">
      <span style="width:8px;height:8px;border-radius:50%;background:${item.color};display:inline-block"></span>
      ${item.name}
    </span>`
  ).join('');

  wrap.innerHTML = `
    <div style="margin-bottom:8px">${legend}</div>
    <div style="overflow-x:auto">
      <div style="display:inline-grid;grid-auto-flow:column;grid-template-rows:repeat(7,10px);gap:2px">${cells}</div>
    </div>`;
}

function setPeriod(p) {
  currentPeriod = p;
  document.querySelectorAll('.filters button').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase().replace(' ','') === p || (p==='all' && b.textContent==='All time'));
  });
  const d = DATA.periods[p];
  const range = DATA.ranges[p];
  document.getElementById('subtitle').textContent =
    `Generated ${DATA.generated_at} · ${range}`;
  renderKPIs(d);
  renderGroups(d);
  renderCategories(d);
  renderProjects(d);
  renderCalendar(d, p);
  renderHeatmap(d);
  renderBlendedCalendar('group-cal-wrap', d.group_daily_list, p);
  renderBlendedCalendar('cat-cal-wrap', d.cat_daily_list, p);
}

// ── Settings panel ────────────────────────────────────────────────────────────

const ALL_CATEGORIES = [...new Set(Object.values(PROJECTS).map(p => p.category).filter(Boolean))].sort();
const ALL_GROUPS     = CONFIG.groups ? CONFIG.groups.map(g => g.name) : [];

let editedProjects   = JSON.parse(JSON.stringify(PROJECTS));
let editedGroups     = [];
let editedCategories = [];
let editedConfig     = {};

function openSettings() {
  editedProjects   = JSON.parse(JSON.stringify(PROJECTS));
  editedGroups     = JSON.parse(JSON.stringify(CONFIG.groups || []));
  editedCategories = JSON.parse(JSON.stringify(CONFIG.categories || []));
  editedConfig     = JSON.parse(JSON.stringify(CONFIG));
  document.getElementById('status-days').value = editedConfig.status_bar_days ?? 1;
  renderGroupRenameList();
  renderCatRenameList();
  renderProjList();
  document.getElementById('overlay').classList.add('open');
  document.getElementById('save-ok').style.display = 'none';
}

function renderGroupRenameList() {
  document.getElementById('group-rename-list').innerHTML = editedGroups.map((g, i) => `
    <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f8fafc">
      <span style="font-size:16px;width:24px;text-align:center">${g.emoji || ''}</span>
      <span style="width:10px;height:10px;border-radius:50%;background:${g.color};flex-shrink:0;display:inline-block"></span>
      <input type="text" value="${g.name}"
        style="flex:1;border:1px solid var(--border);border-radius:7px;padding:5px 8px;font-size:12px;color:var(--text)"
        oninput="renameGroup(${i}, this.value)">
    </div>`).join('');
}

function renderCatRenameList() {
  document.getElementById('cat-rename-list').innerHTML = editedCategories.map((c, i) => `
    <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f8fafc">
      <span style="width:12px;height:12px;border-radius:3px;background:${c.color};flex-shrink:0;display:inline-block"></span>
      <input type="text" value="${c.name}"
        style="flex:1;border:1px solid var(--border);border-radius:7px;padding:5px 8px;font-size:12px;color:var(--text)"
        oninput="renameCategory(${i}, this.value)">
    </div>`).join('');
}

function renameGroup(idx, newName) {
  const oldName = editedGroups[idx].name;
  editedGroups[idx].name = newName;
  Object.values(editedProjects).forEach(p => { if (p.group === oldName) p.group = newName; });
  renderProjList();
}

function renameCategory(idx, newName) {
  const oldName = editedCategories[idx].name;
  editedCategories[idx].name = newName;
  Object.values(editedProjects).forEach(p => { if (p.category === oldName) p.category = newName; });
  renderProjList();
}

function closeSettings() {
  document.getElementById('overlay').classList.remove('open');
}

function renderProjList() {
  const list = document.getElementById('proj-list');
  const cats = editedCategories.length ? editedCategories.map(c => c.name) : ALL_CATEGORIES;
  const grps = editedGroups.length     ? editedGroups.map(g => g.name)     : ALL_GROUPS;
  list.innerHTML = Object.entries(editedProjects).map(([path, info]) => {
    const catOpts = cats.map(c =>
      `<option value="${c}" ${c === info.category ? 'selected' : ''}>${c}</option>`
    ).join('');
    const grpOpts = grps.map(g =>
      `<option value="${g}" ${g === (info.group || '') ? 'selected' : ''}>${g}</option>`
    ).join('');
    const safePath = path.replace(/"/g, '&quot;');
    return `
      <div class="proj-row">
        <div>
          <div class="proj-name">${info.name}</div>
          <div class="proj-path">${path}</div>
        </div>
        <select class="proj-select" data-path="${safePath}" data-field="category"
                onchange="updateProject(this)">${catOpts}</select>
        <select class="proj-select" data-path="${safePath}" data-field="group"
                onchange="updateProject(this)">${grpOpts}</select>
      </div>`;
  }).join('');
}

function updateProject(sel) {
  const path  = sel.dataset.path;
  const field = sel.dataset.field;
  editedProjects[path][field] = sel.value;
}

function downloadJson(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], {type: 'application/json'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function buildPayload() {
  return {
    projects: editedProjects,
    config: Object.assign({}, editedConfig, {
      groups:     editedGroups,
      categories: editedCategories,
    }),
  };
}

function saveSettings() {
  const p = buildPayload();
  downloadJson(p.projects, 'projects.json');
  setTimeout(() => downloadJson(p.config, 'config.json'), 300);
  const ok = document.getElementById('save-ok');
  ok.textContent = '✓ Downloaded — replace files then run generate_dashboard.py';
  ok.style.display = 'inline';
}

async function saveAndRegenerate() {
  const btn = document.getElementById('btn-save-regen');
  const ok  = document.getElementById('save-ok');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  ok.style.display = 'none';
  try {
    const res  = await fetch('/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(buildPayload()),
    });
    const data = await res.json();
    if (data.ok) {
      ok.textContent = '✓ Saved! Reloading…';
      ok.style.display = 'inline';
      setTimeout(() => location.reload(), 800);
    } else {
      ok.textContent = '✗ Error: ' + data.output;
      ok.style.display = 'inline';
    }
  } catch (_) {
    saveSettings();
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Save & Regenerate';
  }
}

// Init
setPeriod('all');
</script>
</body>
</html>
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config   = load_config()
    idle     = config.get("idle_threshold_minutes", 30)
    projects = load_projects()
    events   = load_events()

    if not events:
        print("No data yet. Run tracker.py via hooks or import_history.py first.")
        return

    activity = [e for e in events if e.get("event") == "activity"]
    segments = parse_segments(events, idle)

    now    = datetime.now()
    ranges = {
        "7d":  "Last 7 days",
        "30d": "Last 30 days",
        "90d": "Last 90 days",
        "all": "All time",
    }
    cutoffs = {
        "7d":  now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
        "all": None,
    }

    periods = {}
    for key, cutoff in cutoffs.items():
        periods[key] = compute_stats(segments, activity, projects, config, cutoff)

    dashboard_data = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "ranges":        ranges,
        "periods":       periods,
    }

    html = HTML_TEMPLATE.replace(
        "/*DASHBOARD_DATA*/", json.dumps(dashboard_data, ensure_ascii=False)
    ).replace(
        "/*PROJECTS_DATA*/", json.dumps(projects, ensure_ascii=False)
    ).replace(
        "/*CONFIG_DATA*/", json.dumps(config, ensure_ascii=False)
    )

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Dashboard written to: {OUTPUT_FILE}")
    total = periods["all"]["total_hours"]
    print(f"Total tracked (all time): {int(total)}h {int((total%1)*60):02d}m")
    groups = periods["all"]["groups"]
    for g in groups:
        print(f"  {g['name']}: {g['pct']}% ({g['hours']}h)")


if __name__ == "__main__":
    main()
