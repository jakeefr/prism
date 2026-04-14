"""HTML dashboard generator for PRISM.

Generates a single self-contained HTML file at ~/.claude/prism/dashboard.html.
No external dependencies — all CSS, JS, and data are inlined.

Called by: cli.py dashboard_cmd, and at end of analyze_cmd.
"""

from __future__ import annotations

import json
import os
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from prism import __version__
from prism.analyzer import ProjectHealthReport, score_to_grade


def get_dashboard_path() -> Path:
    """Return the path to the dashboard HTML file, creating parent dirs."""
    path = Path.home() / ".claude" / "prism"
    path.mkdir(parents=True, exist_ok=True)
    return path / "dashboard.html"


def _safe_json(data: object) -> str:
    """Serialize data to JSON safe for inline embedding in HTML."""
    raw = json.dumps(data, ensure_ascii=False)
    # Escape characters that could break out of a <script> or confuse HTML parsers
    raw = raw.replace("&", r"\u0026")
    raw = raw.replace("<", r"\u003c")
    raw = raw.replace(">", r"\u003e")
    return raw


def _build_project_data(report: ProjectHealthReport) -> dict:
    """Convert a ProjectHealthReport to the dashboard JSON shape."""
    from prism.advisor import generate_advice

    # Advisor recommendations (no CLAUDE.md path needed for basic recs)
    try:
        advisor_report = generate_advice(report)
        advisor_recs = [
            {
                "action": r.action,
                "impact": r.impact,
                "content": r.content,
                "rationale": r.rationale,
            }
            for r in advisor_report.recommendations
        ]
    except Exception:
        advisor_recs = []

    # last_active from most-recent session file mtime
    last_active = None
    if report.project.session_files:
        try:
            mtime = report.project.session_files[0].stat().st_mtime
            last_active = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass

    def issues_for(metrics) -> list[str]:
        return [i.description[:120] for i in getattr(metrics, "issues", [])[:5]]

    return {
        "name": report.project.encoded_name,
        "display_name": report.project.display_name,
        "overall_grade": report.overall_grade,
        "overall_score": round(report.overall_score, 1),
        "dimensions": {
            "token_efficiency": {
                "grade": report.token_efficiency.grade,
                "score": round(report.token_efficiency.score, 1),
                "issues": issues_for(report.token_efficiency),
            },
            "tool_health": {
                "grade": report.tool_health.grade,
                "score": round(report.tool_health.score, 1),
                "issues": issues_for(report.tool_health),
            },
            "context_hygiene": {
                "grade": report.context_hygiene.grade,
                "score": round(report.context_hygiene.score, 1),
                "issues": issues_for(report.context_hygiene),
            },
            "md_adherence": {
                "grade": report.claude_md_adherence.grade,
                "score": round(report.claude_md_adherence.score, 1),
                "issues": issues_for(report.claude_md_adherence),
            },
            "continuity": {
                "grade": report.session_continuity.grade,
                "score": round(report.session_continuity.score, 1),
                "issues": issues_for(report.session_continuity),
            },
        },
        "top_issues": [i.description[:120] for i in report.top_issues[:5]],
        "advisor_recommendations": advisor_recs,
        "session_count": report.session_count,
        "last_active": last_active,
    }


def _grade_letter(grade: str) -> str:
    """Return just the letter part of a grade (e.g. 'A+' -> 'A')."""
    return grade[0] if grade and grade not in ("N/A", "?") else "?"


def generate_dashboard(reports: list[ProjectHealthReport], output_path: Path) -> Path:
    """Generate self-contained HTML dashboard. Returns path to file."""
    now = datetime.now(tz=timezone.utc)
    generated_at = now.isoformat()

    projects_data = []
    for report in reports:
        try:
            projects_data.append(_build_project_data(report))
        except Exception:
            pass

    # Fleet-level aggregates
    total_sessions = sum(p["session_count"] for p in projects_data)
    grade_dist: dict[str, int] = {}
    for p in projects_data:
        letter = _grade_letter(p["overall_grade"])
        grade_dist[letter] = grade_dist.get(letter, 0) + 1

    avg_score = (
        sum(p["overall_score"] for p in projects_data) / len(projects_data)
        if projects_data else 0
    )
    fleet_grade = score_to_grade(avg_score) if projects_data else "N/A"

    data = {
        "generated_at": generated_at,
        "prism_version": __version__,
        "fleet_grade": fleet_grade,
        "total_sessions": total_sessions,
        "grade_distribution": grade_dist,
        "projects": projects_data,
    }

    json_blob = _safe_json(data)
    html = _render_html(json_blob)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def serve_dashboard(html_path: Path, port: int = 19821) -> None:
    """Serve dashboard on localhost using http.server."""
    import http.server
    import threading

    orig_dir = os.getcwd()
    os.chdir(html_path.parent)

    handler = http.server.SimpleHTTPRequestHandler

    # Silence default request log
    class QuietHandler(handler):
        def log_message(self, format: str, *args: object) -> None:
            pass

    url = f"http://localhost:{port}/{html_path.name}"

    try:
        with http.server.TCPServer(("", port), QuietHandler) as httpd:
            webbrowser.open(url)
            httpd.serve_forever()
    finally:
        os.chdir(orig_dir)


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

def _render_html(json_blob: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PRISM Dashboard</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;
  --muted:#8b949e;--green:#3fb950;--blue:#58a6ff;--yellow:#d29922;
  --red:#f85149;--orange:#d18616;--purple:#bc8cff;
  --font-mono:ui-monospace,"Cascadia Code","Fira Code",Consolas,"Liberation Mono",monospace;
  --font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
}}
body{{background:var(--bg);color:var(--text);font-family:var(--font-sans);font-size:14px;line-height:1.5}}
a{{color:var(--blue);text-decoration:none}}
/* Header */
.header{{background:#010409;border-bottom:1px solid var(--border);padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
.header-brand{{font-family:var(--font-mono);font-size:20px;font-weight:700;letter-spacing:0.08em;color:var(--blue)}}
.header-sub{{font-size:12px;color:var(--muted);margin-top:2px}}
.header-fleet{{text-align:right}}
.fleet-grade{{font-family:var(--font-mono);font-size:28px;font-weight:700}}
.fleet-label{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em}}
/* Main layout */
.main{{max-width:1200px;margin:0 auto;padding:24px}}
.section-title{{font-family:var(--font-mono);font-size:12px;text-transform:uppercase;letter-spacing:0.1em;color:var(--muted);margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border)}}
/* Project grid */
.project-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-bottom:40px}}
.project-card{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;cursor:pointer;transition:border-color 0.15s}}
.project-card:hover{{border-color:var(--blue)}}
.project-card.active{{border-color:var(--blue);box-shadow:0 0 0 1px var(--blue)}}
.card-header{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:12px}}
.card-name{{font-family:var(--font-mono);font-size:13px;color:var(--text);word-break:break-all;flex:1;padding-right:12px}}
.card-grade{{font-family:var(--font-mono);font-size:28px;font-weight:700;line-height:1;flex-shrink:0}}
.card-meta{{font-size:11px;color:var(--muted);margin-bottom:12px}}
/* Dimension mini-grid */
.dim-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:4px}}
.dim-cell{{background:#010409;border-radius:4px;padding:4px 2px;text-align:center}}
.dim-label{{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:2px}}
.dim-grade{{font-family:var(--font-mono);font-size:13px;font-weight:600}}
/* Detail panel */
.detail-panel{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:24px;margin-bottom:40px;display:none}}
.detail-panel.active{{display:block}}
.detail-title{{font-family:var(--font-mono);font-size:16px;font-weight:700;margin-bottom:20px;color:var(--blue)}}
.detail-dims{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:24px}}
.detail-dim-card{{background:#010409;border:1px solid var(--border);border-radius:6px;padding:12px}}
.detail-dim-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.detail-dim-name{{font-size:12px;color:var(--muted)}}
.detail-dim-grade{{font-family:var(--font-mono);font-size:18px;font-weight:700}}
.detail-dim-issues{{font-size:11px;color:var(--muted);margin-top:4px}}
.detail-dim-issues li{{margin-left:12px;margin-bottom:2px;list-style:disc}}
.issues-section{{margin-bottom:24px}}
.issues-section h3{{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px}}
.issue-item{{font-size:12px;color:var(--text);padding:6px 10px;border-left:3px solid var(--border);margin-bottom:4px;background:#010409;border-radius:0 4px 4px 0}}
.issue-item.high{{border-left-color:var(--red)}}
.issue-item.medium{{border-left-color:var(--yellow)}}
/* Recommendations */
.rec-item{{background:#010409;border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:8px}}
.rec-header{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.rec-action{{font-family:var(--font-mono);font-size:11px;font-weight:700;padding:2px 6px;border-radius:3px}}
.rec-action.ADD{{background:rgba(63,185,80,0.15);color:var(--green)}}
.rec-action.TRIM{{background:rgba(248,81,73,0.15);color:var(--red)}}
.rec-action.WARN{{background:rgba(210,153,34,0.15);color:var(--yellow)}}
.rec-action.RESTRUCTURE{{background:rgba(88,166,255,0.15);color:var(--blue)}}
.rec-impact{{font-size:11px;color:var(--muted)}}
.rec-content{{font-size:12px;color:var(--text);white-space:pre-wrap;font-family:var(--font-mono)}}
.rec-rationale{{font-size:11px;color:var(--muted);margin-top:6px}}
/* Fleet summary */
.fleet-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:16px;margin-bottom:24px}}
.fleet-stat{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center}}
.fleet-stat-value{{font-family:var(--font-mono);font-size:28px;font-weight:700;color:var(--blue)}}
.fleet-stat-label{{font-size:12px;color:var(--muted);margin-top:4px}}
/* Grade distribution bar chart */
.grade-chart{{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;margin-bottom:24px}}
.grade-bars{{display:flex;align-items:flex-end;gap:8px;height:80px;margin-top:12px}}
.grade-bar-wrap{{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px}}
.grade-bar{{width:100%;border-radius:3px 3px 0 0;min-height:4px;transition:height 0.3s}}
.grade-bar-label{{font-family:var(--font-mono);font-size:11px;color:var(--muted)}}
.grade-bar-count{{font-family:var(--font-mono);font-size:11px;font-weight:600}}
/* Utilities */
.grade-A{{color:var(--green)}} .grade-B{{color:var(--blue)}} .grade-C{{color:var(--yellow)}}
.grade-D{{color:var(--red)}} .grade-F{{color:var(--red)}} .grade-N{{color:var(--muted)}}
.bg-A{{background:var(--green)}} .bg-B{{background:var(--blue)}} .bg-C{{background:var(--yellow)}}
.bg-D{{background:var(--red)}} .bg-F{{background:var(--red)}} .bg-N{{background:var(--muted)}}
.no-data{{color:var(--muted);font-style:italic;font-size:13px;padding:16px 0}}
.close-btn{{float:right;background:none;border:1px solid var(--border);border-radius:4px;color:var(--muted);font-size:12px;padding:4px 10px;cursor:pointer}}
.close-btn:hover{{color:var(--text);border-color:var(--text)}}
footer{{text-align:center;padding:24px;color:var(--muted);font-size:11px;font-family:var(--font-mono)}}
</style>
</head>
<body>
<script type="application/json" id="prism-data">{json_blob}</script>
<script>
(function(){{
const D = JSON.parse(document.getElementById('prism-data').textContent);

function gradeClass(g){{
  if(!g||g==='N/A'||g==='?') return 'grade-N';
  return 'grade-'+g[0];
}}
function bgClass(g){{
  if(!g||g==='N/A'||g==='?') return 'bg-N';
  return 'bg-'+g[0];
}}
function esc(s){{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}
function fmtDate(iso){{
  if(!iso) return 'never';
  try{{
    const d=new Date(iso);
    const now=Date.now();
    const diff=now-d.getTime();
    if(diff<60000) return 'just now';
    if(diff<3600000) return Math.floor(diff/60000)+'m ago';
    if(diff<86400000) return Math.floor(diff/3600000)+'h ago';
    return Math.floor(diff/86400000)+'d ago';
  }}catch(e){{return iso.slice(0,10);}}
}}

// ---- Header ----
const fleetClass = gradeClass(D.fleet_grade);
document.body.innerHTML = `
<header class="header">
  <div>
    <div class="header-brand">◈ PRISM</div>
    <div class="header-sub">Session intelligence for Claude Code &nbsp;·&nbsp; v${{esc(D.prism_version)}}</div>
  </div>
  <div class="header-fleet">
    <div class="fleet-label">Fleet Health</div>
    <div class="fleet-grade ${{fleetClass}}">${{esc(D.fleet_grade)}}</div>
    <div class="fleet-label">Last updated: ${{fmtDate(D.generated_at)}}</div>
  </div>
</header>
<main class="main" id="main"></main>
<footer>Generated by PRISM v${{esc(D.prism_version)}} · ${{esc(new Date(D.generated_at).toLocaleString())}}</footer>
`;

const main = document.getElementById('main');

// ---- Project Health Grid ----
const DIM_LABELS = {{token_efficiency:'Token',tool_health:'Tools',context_hygiene:'Context',md_adherence:'MD',continuity:'Continu.'}};
const DIM_KEYS = ['token_efficiency','tool_health','context_hygiene','md_adherence','continuity'];

let activeProject = null;
const detailEl = document.createElement('div');
detailEl.id = 'detail-panel';
detailEl.className = 'detail-panel';

function renderGrid(){{
  const section = document.createElement('div');
  section.innerHTML = '<div class="section-title">Project Health</div>';

  if(!D.projects||!D.projects.length){{
    section.innerHTML += '<p class="no-data">No projects found.</p>';
    main.appendChild(section);
    return;
  }}

  const grid = document.createElement('div');
  grid.className = 'project-grid';

  D.projects.forEach((proj,idx)=>{{
    const card = document.createElement('div');
    card.className = 'project-card';
    card.dataset.idx = idx;

    const dimCells = DIM_KEYS.map(k=>{{
      const dim = proj.dimensions[k]||{{}};
      const g = dim.grade||'?';
      return `<div class="dim-cell"><div class="dim-label">${{DIM_LABELS[k]||k}}</div><div class="dim-grade ${{gradeClass(g)}}">${{esc(g)}}</div></div>`;
    }}).join('');

    card.innerHTML = `
      <div class="card-header">
        <div class="card-name">${{esc(proj.display_name||proj.name)}}</div>
        <div class="card-grade ${{gradeClass(proj.overall_grade)}}">${{esc(proj.overall_grade)}}</div>
      </div>
      <div class="card-meta">${{proj.session_count}} session${{proj.session_count!==1?'s':''}} · last active ${{fmtDate(proj.last_active)}}</div>
      <div class="dim-grid">${{dimCells}}</div>
    `;
    card.addEventListener('click',()=>toggleDetail(idx,card));
    grid.appendChild(card);
  }});

  section.appendChild(grid);
  section.appendChild(detailEl);
  main.appendChild(section);
}}

function toggleDetail(idx, card){{
  const allCards = document.querySelectorAll('.project-card');
  if(activeProject===idx){{
    detailEl.classList.remove('active');
    detailEl.style.display='none';
    card.classList.remove('active');
    activeProject=null;
  }}else{{
    allCards.forEach(c=>c.classList.remove('active'));
    card.classList.add('active');
    renderDetail(D.projects[idx]);
    detailEl.classList.add('active');
    detailEl.style.display='block';
    detailEl.scrollIntoView({{behavior:'smooth',block:'nearest'}});
    activeProject=idx;
  }}
}}

function renderDetail(proj){{
  const dimCards = DIM_KEYS.map(k=>{{
    const dim = proj.dimensions[k]||{{}};
    const g = dim.grade||'N/A';
    const issues = (dim.issues||[]).map(i=>`<li>${{esc(i)}}</li>`).join('');
    const issueHtml = issues ? `<ul class="detail-dim-issues">${{issues}}</ul>` : '';
    const names = {{token_efficiency:'Token Efficiency',tool_health:'Tool Health',context_hygiene:'Context Hygiene',md_adherence:'MD Adherence',continuity:'Continuity'}};
    return `<div class="detail-dim-card">
      <div class="detail-dim-header">
        <span class="detail-dim-name">${{names[k]||k}}</span>
        <span class="detail-dim-grade ${{gradeClass(g)}}">${{esc(g)}}</span>
      </div>
      ${{issueHtml||'<div style="font-size:11px;color:#3fb950">No issues</div>'}}
    </div>`;
  }}).join('');

  const topIssues = (proj.top_issues||[]).map(i=>`<div class="issue-item">${{esc(i)}}</div>`).join('') || '<p class="no-data">No issues detected.</p>';

  const recs = (proj.advisor_recommendations||[]).map(r=>{{
    return `<div class="rec-item">
      <div class="rec-header">
        <span class="rec-action ${{esc(r.action)}}">${{esc(r.action)}}</span>
        <span class="rec-impact">${{esc(r.impact)}} impact</span>
      </div>
      <div class="rec-content">${{esc(r.content)}}</div>
      <div class="rec-rationale">${{esc(r.rationale)}}</div>
    </div>`;
  }}).join('') || '<p class="no-data">No recommendations.</p>';

  detailEl.innerHTML = `
    <button class="close-btn" onclick="document.getElementById('detail-panel').style.display='none';document.querySelectorAll('.project-card').forEach(c=>c.classList.remove('active'));">✕ Close</button>
    <div class="detail-title">${{esc(proj.display_name||proj.name)}}</div>
    <div class="detail-dims">${{dimCards}}</div>
    <div class="issues-section">
      <h3>Top Issues</h3>
      ${{topIssues}}
    </div>
    <div class="issues-section">
      <h3>Advisor Recommendations</h3>
      ${{recs}}
    </div>
  `;
}}

// ---- Fleet Summary ----
function renderFleet(){{
  const section = document.createElement('div');
  section.innerHTML = '<div class="section-title">Fleet Summary</div>';

  const statsHtml = `
    <div class="fleet-grid">
      <div class="fleet-stat">
        <div class="fleet-stat-value">${{D.projects?D.projects.length:0}}</div>
        <div class="fleet-stat-label">Projects</div>
      </div>
      <div class="fleet-stat">
        <div class="fleet-stat-value">${{D.total_sessions||0}}</div>
        <div class="fleet-stat-label">Sessions Analyzed</div>
      </div>
      <div class="fleet-stat">
        <div class="fleet-stat-value ${{gradeClass(D.fleet_grade)}}">${{esc(D.fleet_grade||'N/A')}}</div>
        <div class="fleet-stat-label">Fleet Grade</div>
      </div>
    </div>
  `;
  section.innerHTML += statsHtml;

  // Grade distribution bar chart
  const dist = D.grade_distribution||{{}};
  const GRADES = ['A','B','C','D','F'];
  const maxCount = Math.max(1,...GRADES.map(g=>dist[g]||0));
  const bars = GRADES.map(g=>{{
    const cnt = dist[g]||0;
    const pct = Math.round((cnt/maxCount)*100);
    const color = {{A:'var(--green)',B:'var(--blue)',C:'var(--yellow)',D:'var(--red)',F:'var(--red)'}}[g]||'var(--muted)';
    return `<div class="grade-bar-wrap">
      <div class="grade-bar-count">${{cnt||''}}</div>
      <div class="grade-bar" style="height:${{Math.max(4,pct*0.72)}}px;background:${{color}}"></div>
      <div class="grade-bar-label">${{g}}</div>
    </div>`;
  }}).join('');

  const chartHtml = `
    <div class="grade-chart">
      <div class="section-title" style="margin-bottom:4px">Grade Distribution</div>
      <div class="grade-bars">${{bars}}</div>
    </div>
  `;
  section.innerHTML += chartHtml;

  // Most common issues across all projects
  const issueCounts = {{}};
  (D.projects||[]).forEach(proj=>{{
    (proj.top_issues||[]).forEach(issue=>{{
      const key = issue.slice(0,60);
      issueCounts[key]=(issueCounts[key]||0)+1;
    }});
  }});
  const sorted = Object.entries(issueCounts).sort((a,b)=>b[1]-a[1]).slice(0,5);
  if(sorted.length){{
    const issueHtml = sorted.map(([desc,cnt])=>
      `<div class="issue-item">${{esc(desc)}}${{cnt>1?` <span style="color:var(--muted);font-size:10px">(×${{cnt}})</span>`:''}}</div>`
    ).join('');
    section.innerHTML += `<div class="issues-section" style="margin-top:16px"><h3>Most Common Issues</h3>${{issueHtml}}</div>`;
  }}

  main.appendChild(section);
}}

renderGrid();
renderFleet();
}})();
</script>
</body>
</html>"""
