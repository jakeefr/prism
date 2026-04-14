"""Generate a demo dashboard HTML from anonymized mock data.

Run: python scripts/gen_demo_dashboard.py
Output: assets/dashboard-demo.html  (then screenshotted to assets/dashboard-preview.png)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from prism.dashboard import _render_html, _safe_json

# ---------------------------------------------------------------------------
# Mock project data — 5 generic projects with varied health grades
# ---------------------------------------------------------------------------

MOCK_DATA = {
    "generated_at": "2026-04-13T19:00:00+00:00",
    "prism_version": "0.2.0",
    "fleet_grade": "C+",
    "total_sessions": 47,
    "grade_distribution": {"A": 1, "B": 2, "C": 1, "D": 1},
    "projects": [
        {
            "name": "frontend",
            "display_name": "~/projects/frontend",
            "overall_grade": "A-",
            "overall_score": 85.2,
            "dimensions": {
                "token_efficiency": {
                    "grade": "A",
                    "score": 91.0,
                    "issues": [],
                },
                "tool_health": {
                    "grade": "A",
                    "score": 95.0,
                    "issues": [],
                },
                "context_hygiene": {
                    "grade": "B+",
                    "score": 82.0,
                    "issues": ["Session has 1 compaction event"],
                },
                "md_adherence": {
                    "grade": "A-",
                    "score": 86.0,
                    "issues": [],
                },
                "continuity": {
                    "grade": "A+",
                    "score": 97.0,
                    "issues": [],
                },
            },
            "top_issues": ["Session has 1 compaction event"],
            "advisor_recommendations": [],
            "session_count": 8,
            "last_active": "2026-04-13T18:42:00+00:00",
        },
        {
            "name": "api-server",
            "display_name": "~/projects/api-server",
            "overall_grade": "B",
            "overall_score": 76.8,
            "dimensions": {
                "token_efficiency": {
                    "grade": "B+",
                    "score": 81.0,
                    "issues": [],
                },
                "tool_health": {
                    "grade": "B",
                    "score": 75.0,
                    "issues": [
                        "Retry loop detected: Bash called 3+ times with same input",
                    ],
                },
                "context_hygiene": {
                    "grade": "B-",
                    "score": 72.0,
                    "issues": ["Session has 2 compaction events"],
                },
                "md_adherence": {
                    "grade": "B+",
                    "score": 80.0,
                    "issues": [],
                },
                "continuity": {
                    "grade": "A",
                    "score": 92.0,
                    "issues": [],
                },
            },
            "top_issues": [
                "Retry loop detected: Bash called 3+ times with same input",
                "Session has 2 compaction events",
            ],
            "advisor_recommendations": [
                {
                    "action": "ADD",
                    "impact": "High",
                    "content": (
                        "Always use non-interactive flags when available: "
                        "--yes, -y, --non-interactive, --no-input."
                    ),
                    "rationale": "Fixes 2 retry loop(s) and 3 interactive command(s) across 2 session(s)",
                },
            ],
            "session_count": 11,
            "last_active": "2026-04-13T17:15:00+00:00",
        },
        {
            "name": "myapp",
            "display_name": "~/projects/myapp",
            "overall_grade": "C+",
            "overall_score": 67.4,
            "dimensions": {
                "token_efficiency": {
                    "grade": "D",
                    "score": 43.0,
                    "issues": [
                        "CLAUDE.md re-reads consume >31% of session tokens",
                    ],
                },
                "tool_health": {
                    "grade": "B+",
                    "score": 82.0,
                    "issues": [],
                },
                "context_hygiene": {
                    "grade": "C+",
                    "score": 67.0,
                    "issues": ["Session has 2 compaction events"],
                },
                "md_adherence": {
                    "grade": "C",
                    "score": 62.0,
                    "issues": [
                        "CLAUDE.md is 118 lines — adherence degrades past line 80",
                    ],
                },
                "continuity": {
                    "grade": "A-",
                    "score": 86.0,
                    "issues": [],
                },
            },
            "top_issues": [
                "CLAUDE.md re-reads consume >31% of session tokens",
                "CLAUDE.md is 118 lines — adherence degrades past line 80",
                "Session has 2 compaction events",
            ],
            "advisor_recommendations": [
                {
                    "action": "TRIM",
                    "impact": "High",
                    "content": "Trim CLAUDE.md from 118 lines to under 80",
                    "rationale": (
                        "Your CLAUDE.md is 118 lines — adherence drops significantly past line 80. "
                        "Consider moving rarely-used rules to per-directory CLAUDE.md files."
                    ),
                },
                {
                    "action": "RESTRUCTURE",
                    "impact": "Medium",
                    "content": (
                        "Move these rules to the top or bottom of your CLAUDE.md:\n"
                        "  Line 28: NEVER edit existing migration files\n"
                        "  Line 47: ALWAYS run tests before marking a task done"
                    ),
                    "rationale": (
                        "Found 2 critical rule(s) in the attention dead zone "
                        "(lines 24–89 of 118). LLMs follow a U-shaped attention curve "
                        "— middle content gets least focus."
                    ),
                },
            ],
            "session_count": 14,
            "last_active": "2026-04-13T16:00:00+00:00",
        },
        {
            "name": "data-pipeline",
            "display_name": "~/projects/data-pipeline",
            "overall_grade": "C-",
            "overall_score": 56.1,
            "dimensions": {
                "token_efficiency": {
                    "grade": "C",
                    "score": 62.0,
                    "issues": ["Session has 3 compaction events"],
                },
                "tool_health": {
                    "grade": "C-",
                    "score": 55.0,
                    "issues": [
                        "Retry loop detected: Bash called 3+ times with same input",
                        "Potentially interactive Bash command: apt install python3-dev",
                        "Consecutive tool failures: 4 errors in a row",
                    ],
                },
                "context_hygiene": {
                    "grade": "D+",
                    "score": 52.0,
                    "issues": [
                        "Session has 4 compaction events",
                        "Mid-task compaction: tool patterns repeat after boundary",
                    ],
                },
                "md_adherence": {
                    "grade": "C+",
                    "score": 65.0,
                    "issues": [],
                },
                "continuity": {
                    "grade": "B",
                    "score": 77.0,
                    "issues": [],
                },
            },
            "top_issues": [
                "Mid-task compaction: tool patterns repeat after boundary (context loss signal)",
                "Consecutive tool failures: 4 errors in a row",
                "Retry loop detected: Bash called 3+ times with same input",
                "Potentially interactive Bash command: apt install python3-dev",
                "Session has 4 compaction events",
            ],
            "advisor_recommendations": [
                {
                    "action": "ADD",
                    "impact": "High",
                    "content": (
                        "Always use non-interactive flags when available: "
                        "--yes, -y, --non-interactive, --no-input. "
                        "Never use commands with --watch, --interactive, or prompts that wait for input."
                    ),
                    "rationale": "Fixes 1 retry loop(s) and 2 interactive command(s) across 3 session(s)",
                },
                {
                    "action": "WARN",
                    "impact": "High",
                    "content": "Rule appears violated — review sessions and reinforce: Never edit existing migration files",
                    "rationale": "Rule violated in 2 session(s): 'Never edit existing migration files'",
                },
            ],
            "session_count": 9,
            "last_active": "2026-04-12T22:30:00+00:00",
        },
        {
            "name": "web-scraper",
            "display_name": "~/projects/web-scraper",
            "overall_grade": "D+",
            "overall_score": 51.3,
            "dimensions": {
                "token_efficiency": {
                    "grade": "F",
                    "score": 22.0,
                    "issues": [
                        "CLAUDE.md re-reads consume >48% of session tokens",
                        "Session has 5 compaction boundaries (>1 is a warning)",
                    ],
                },
                "tool_health": {
                    "grade": "D",
                    "score": 45.0,
                    "issues": [
                        "Retry loop detected: Bash called 3+ times with same input",
                        "Edit-revert cycle detected on src/scraper.py",
                        "Consecutive tool failures: 5 errors in a row",
                    ],
                },
                "context_hygiene": {
                    "grade": "D-",
                    "score": 41.0,
                    "issues": [
                        "Session has 5 compaction events",
                        "Mid-task compaction: tool patterns repeat after boundary",
                        "Session has 112 turns — possible context drift",
                    ],
                },
                "md_adherence": {
                    "grade": "D+",
                    "score": 52.0,
                    "issues": [
                        "CLAUDE.md is 156 lines — adherence degrades past line 80",
                    ],
                },
                "continuity": {
                    "grade": "B-",
                    "score": 71.0,
                    "issues": ["Session file truncated — write was interrupted"],
                },
            },
            "top_issues": [
                "CLAUDE.md re-reads consume >48% of session tokens",
                "Mid-task compaction: tool patterns repeat after boundary (context loss signal)",
                "Consecutive tool failures: 5 errors in a row",
                "Session has 112 turns — possible context drift",
                "CLAUDE.md is 156 lines — adherence degrades past line 80",
            ],
            "advisor_recommendations": [
                {
                    "action": "TRIM",
                    "impact": "High",
                    "content": "Trim CLAUDE.md from 156 lines to under 80",
                    "rationale": (
                        "Your CLAUDE.md is 156 lines — adherence drops significantly past line 80. "
                        "Consider moving rarely-used rules to per-directory CLAUDE.md files."
                    ),
                },
                {
                    "action": "ADD",
                    "impact": "High",
                    "content": (
                        "Always use non-interactive flags when available: "
                        "--yes, -y, --non-interactive, --no-input."
                    ),
                    "rationale": "Fixes 2 retry loop(s) and 4 interactive command(s) across 3 session(s)",
                },
                {
                    "action": "RESTRUCTURE",
                    "impact": "Medium",
                    "content": (
                        "Move these rules to the top or bottom of your CLAUDE.md:\n"
                        "  Line 38: NEVER push directly to main without review\n"
                        "  Line 61: ALWAYS run the full test suite before committing\n"
                        "  Line 74: DO NOT hardcode credentials or API keys"
                    ),
                    "rationale": (
                        "Found 3 critical rule(s) in the attention dead zone "
                        "(lines 32–117 of 156). LLMs follow a U-shaped attention curve."
                    ),
                },
            ],
            "session_count": 5,
            "last_active": "2026-04-11T14:20:00+00:00",
        },
    ],
}


def main() -> None:
    repo_root = Path(__file__).parent.parent
    assets_dir = repo_root / "assets"
    assets_dir.mkdir(exist_ok=True)

    html_path = assets_dir / "dashboard-demo.html"
    json_blob = _safe_json(MOCK_DATA)
    html = _render_html(json_blob)
    html_path.write_text(html, encoding="utf-8")
    print(f"Dashboard HTML written: {html_path}")

    # Try to take a screenshot with Chrome headless
    png_path = assets_dir / "dashboard-preview.png"
    _take_screenshot(html_path, png_path)


def _take_screenshot(html_path: Path, png_path: Path) -> None:
    """Try multiple approaches to screenshot the dashboard."""
    import subprocess
    import shutil

    html_url = html_path.as_uri()

    # Approach 1: Chrome headless
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for chrome in chrome_paths:
        if Path(chrome).exists():
            print(f"Found Chrome: {chrome}")
            try:
                result = subprocess.run(
                    [
                        chrome,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-sandbox",
                        f"--screenshot={png_path}",
                        "--window-size=1440,900",
                        "--hide-scrollbars",
                        "--virtual-time-budget=3000",
                        html_url,
                    ],
                    capture_output=True,
                    timeout=30,
                    cwd=str(png_path.parent),
                )
                if png_path.exists():
                    print(f"Screenshot saved: {png_path}")
                    return
                else:
                    print(f"Chrome exited {result.returncode}, screenshot not found at {png_path}")
                    # Chrome may have saved as screenshot.png in cwd
                    fallback = png_path.parent / "screenshot.png"
                    if fallback.exists():
                        fallback.rename(png_path)
                        print(f"Moved screenshot.png → {png_path}")
                        return
                    print(f"stdout: {result.stdout.decode(errors='replace')[:200]}")
                    print(f"stderr: {result.stderr.decode(errors='replace')[:400]}")
            except Exception as exc:
                print(f"Chrome attempt failed: {exc}")

    # Approach 2: Edge headless
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for edge in edge_paths:
        if Path(edge).exists():
            print(f"Found Edge: {edge}")
            try:
                result = subprocess.run(
                    [
                        edge,
                        "--headless=new",
                        "--disable-gpu",
                        "--no-sandbox",
                        f"--screenshot={png_path}",
                        "--window-size=1440,900",
                        "--hide-scrollbars",
                        "--virtual-time-budget=3000",
                        html_url,
                    ],
                    capture_output=True,
                    timeout=30,
                    cwd=str(png_path.parent),
                )
                if png_path.exists():
                    print(f"Screenshot saved: {png_path}")
                    return
                else:
                    print(f"Edge exited {result.returncode}")
                    fallback = png_path.parent / "screenshot.png"
                    if fallback.exists():
                        fallback.rename(png_path)
                        print(f"Moved screenshot.png → {png_path}")
                        return
                    print(f"stderr: {result.stderr.decode(errors='replace')[:400]}")
            except Exception as exc:
                print(f"Edge attempt failed: {exc}")

    # Approach 3: Playwright with system Chrome
    try:
        from playwright.sync_api import sync_playwright
        print("Trying playwright with system Chrome...")
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=chrome, headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(html_url)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(png_path), full_page=False)
            browser.close()
        if png_path.exists():
            print(f"Screenshot saved via playwright: {png_path}")
            return
    except Exception as exc:
        print(f"Playwright attempt failed: {exc}")

    print("WARNING: Could not take screenshot automatically.")
    print(f"Open this URL in a browser and screenshot manually: {html_url}")


if __name__ == "__main__":
    main()
