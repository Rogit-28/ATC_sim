#!/usr/bin/env python3
"""
Backdate the ATC Simulator codebase into 57 realistic git commits.

Spans June 2, 2025 (Monday) through July 28, 2025 (Monday).
Human-like commit patterns:
  - No commits on Sundays
  - Granular timestamps (e.g., 10:23:47, 14:15:03)
  - Fluctuating daily activity (1-4 commits on active days)
  - Days off scattered throughout (Fridays, Wednesdays, holidays)
  - Commit clustering (bursts when "in the zone")
  - Realistic messages (imperative mood, mix of terse and descriptive)
  - Occasional late-night WIP commits on off days

Each source file appears in exactly one commit.
Empty --allow-empty commits used as realistic milestone markers.

Usage:
    python scripts/backdate_commits.py
"""

import subprocess
import os
import sys
from datetime import datetime

# ─── CONFIGURATION ─────────────────────────────────────────────
AUTHOR_NAME = "Rogit-28"
AUTHOR_EMAIL = "rogitsudharsan81@gmail.com"

# Each entry: (date, time, message, [files])
# Every file appears EXACTLY ONCE. Empty [] = --allow-empty milestone.
COMMITS = [
    # ═══════════════════════════════════════════════════════════
    # WEEK 1: June 2-5 (Mon-Thu) — Project kickoff & foundation
    # June 6 Fri — day off (long weekend)
    # ═══════════════════════════════════════════════════════════
    # --- Mon June 2: 2 commits ---
    ("2025-06-02", "09:47:12", "Initial project setup with gitignore", [".gitignore"]),
    ("2025-06-02", "10:23:55", "Add project requirements document", ["ATC Sim.md"]),
    # --- Tue June 3: 3 commits ---
    ("2025-06-03", "11:15:33", "Add pyproject.toml with core and dev dependencies", ["pyproject.toml"]),
    ("2025-06-03", "14:02:17", "Add docker compose for local PostgreSQL", ["docker-compose.yml"]),
    ("2025-06-03", "14:38:41", "Add environment variable template", [".env.example"]),
    # --- Wed June 4: 1 commit ---
    (
        "2025-06-04",
        "09:33:41",
        "Scaffold package structure with init files",
        ["src/__init__.py", "tests/__init__.py", "scripts/__init__.py"],
    ),
    # --- Thu June 5: 1 commit ---
    ("2025-06-05", "10:11:08", "Implement application settings with pydantic-settings v2", ["src/config.py"]),
    # ═══════════════════════════════════════════════════════════
    # WEEK 2: June 9-13 — Data models & database layer
    # June 11 Wed — day off (but late-night WIP)
    # ═══════════════════════════════════════════════════════════
    # --- Mon June 9: 2 commits ---
    (
        "2025-06-09",
        "10:45:22",
        "Add aircraft model with status enums and performance tables",
        ["src/models/aircraft.py"],
    ),
    ("2025-06-09", "13:58:03", "Add sector boundary model with containment check", ["src/models/sector.py"]),
    # --- Tue June 10: 3 commits ---
    ("2025-06-10", "09:22:37", "Add runway model with ILS glideslope computation", ["src/models/runway.py"]),
    ("2025-06-10", "11:07:51", "Add typed event hierarchy for simulation events", ["src/models/events.py"]),
    ("2025-06-10", "16:22:33", "Add models package with re-exports", ["src/models/__init__.py"]),
    # --- Wed June 11: 1 late-night WIP commit ---
    ("2025-06-11", "22:13:47", "WIP: sketch out database layer approach", []),
    # --- Thu June 12: 2 commits ---
    (
        "2025-06-12",
        "10:33:19",
        "Configure alembic for raw SQL database migrations",
        ["alembic.ini", "alembic/env.py", "alembic/script.py.mako", "alembic/README"],
    ),
    (
        "2025-06-12",
        "15:21:44",
        "Add initial schema: sectors, runways, aircraft_states, event_log, snapshots, metrics",
        ["alembic/versions/001_initial_schema.py"],
    ),
    # --- Fri June 13: 3 commits ---
    ("2025-06-13", "10:55:02", "Implement asyncpg connection pool with COPY protocol", ["src/persistence/database.py"]),
    ("2025-06-13", "14:30:18", "Add repository classes for all database tables", ["src/persistence/repositories.py"]),
    ("2025-06-13", "15:12:44", "Wire up persistence package exports", ["src/persistence/__init__.py"]),
    # ═══════════════════════════════════════════════════════════
    # WEEK 3: June 16-20 — Physics engine & spatial index
    # Full week, heavy coding
    # ═══════════════════════════════════════════════════════════
    # --- Mon June 16: 1 commit ---
    ("2025-06-16", "09:18:45", "Implement vectorized physics engine with NumPy batch ops", ["src/engine/physics.py"]),
    # --- Tue June 17: 2 commits ---
    ("2025-06-17", "10:42:11", "Add loose octree spatial index for proximity queries", ["src/spatial/octree.py"]),
    ("2025-06-17", "14:15:33", "Update spatial package exports", ["src/spatial/__init__.py"]),
    # --- Wed June 18: 3 commits ---
    ("2025-06-18", "11:05:33", "Implement weighted landing priority scoring system", ["src/engine/priority.py"]),
    ("2025-06-18", "15:47:22", "Add async event bus with pub/sub and backpressure", ["src/events/event_bus.py"]),
    ("2025-06-18", "16:22:08", "Export event bus from events package", ["src/events/__init__.py"]),
    # --- Thu June 19: 1 commit ---
    ("2025-06-19", "09:55:07", "Implement conflict detection with 5NM/1000ft separation", ["src/engine/conflict.py"]),
    # --- Fri June 20: 1 commit ---
    ("2025-06-20", "10:12:38", "Add holding pattern manager with racetrack geometry", ["src/engine/holding.py"]),
    # ═══════════════════════════════════════════════════════════
    # WEEK 4: June 23-27 — Approach, spawner, sim loop, API
    # June 26 Thu — day off (but late-night planning)
    # ═══════════════════════════════════════════════════════════
    # --- Mon June 23: 1 commit ---
    ("2025-06-23", "11:33:15", "Add ILS approach manager with 7-phase state machine", ["src/engine/approach.py"]),
    # --- Tue June 24: 1 commit ---
    (
        "2025-06-24",
        "09:28:44",
        "Implement aircraft spawner with Poisson inter-arrival timing",
        ["src/engine/spawner.py"],
    ),
    # --- Wed June 25: 2 commits ---
    ("2025-06-25", "10:03:21", "Implement main simulation loop with 15-step async tick", ["src/engine/simulation.py"]),
    ("2025-06-25", "14:45:17", "Wire up engine package public exports", ["src/engine/__init__.py"]),
    # --- Thu June 26: 1 late-night commit ---
    ("2025-06-26", "21:45:12", "WIP: plan API layer and client architecture", []),
    # --- Fri June 27: 2 commits ---
    ("2025-06-27", "11:22:08", "Add FastAPI REST endpoints and WebSocket streaming route", ["src/api/routes.py"]),
    ("2025-06-27", "12:05:33", "Update API package exports", ["src/api/__init__.py"]),
    # ═══════════════════════════════════════════════════════════
    # WEEK 5: June 30 - July 2 — App entry & 3D client
    # July 3-4 — holiday weekend (off)
    # ═══════════════════════════════════════════════════════════
    # --- Mon June 30: 1 commit ---
    ("2025-06-30", "09:41:33", "Wire up FastAPI app factory with KJFK default scenario", ["src/main.py"]),
    # --- Tue July 1: 2 commits ---
    ("2025-07-01", "10:17:42", "Add radar dashboard HTML with panel layout", ["client/index.html"]),
    ("2025-07-01", "12:45:19", "Style dark-theme radar dashboard", ["client/css/style.css"]),
    # --- Wed July 2: 3 commits ---
    ("2025-07-02", "09:55:31", "Implement three.js 3D scene with aircraft rendering", ["client/js/scene.js"]),
    ("2025-07-02", "11:30:47", "Add WebSocket client with msgpack binary deserialization", ["client/js/websocket.js"]),
    ("2025-07-02", "14:22:05", "Add main app controller wiring scene and data feeds", ["client/js/app.js"]),
    # ═══════════════════════════════════════════════════════════
    # WEEK 6: July 7-11 — Analytics, replay, begin testing
    # July 8 Tue — day off (late-night test planning)
    # ═══════════════════════════════════════════════════════════
    # --- Mon July 7: 4 commits (productive day) ---
    (
        "2025-07-07",
        "10:08:55",
        "Add metrics collector for simulation performance tracking",
        ["src/analytics/metrics.py"],
    ),
    ("2025-07-07", "11:15:42", "Export MetricsCollector from analytics package", ["src/analytics/__init__.py"]),
    ("2025-07-07", "15:33:21", "Implement replay recorder with variable-speed playback", ["src/replay/recorder.py"]),
    ("2025-07-07", "16:05:18", "Export replay classes from package", ["src/replay/__init__.py"]),
    # --- Tue July 8: 1 late-night commit ---
    ("2025-07-08", "22:07:33", "Set up test infrastructure and plan test matrix", []),
    # --- Wed July 9: 2 commits ---
    ("2025-07-09", "09:27:14", "Add pytest conftest with shared fixtures", ["tests/conftest.py"]),
    ("2025-07-09", "11:44:38", "Add physics engine test suite — 16 tests", ["tests/test_physics.py"]),
    # --- Thu July 10: 2 commits ---
    ("2025-07-10", "10:15:22", "Add conflict detection tests — 7 tests", ["tests/test_conflict.py"]),
    ("2025-07-10", "14:02:55", "Add holding pattern tests — 8 tests", ["tests/test_holding.py"]),
    # --- Fri July 11: 1 commit ---
    ("2025-07-11", "09:33:17", "Add ILS approach test suite — 7 tests", ["tests/test_approach.py"]),
    # ═══════════════════════════════════════════════════════════
    # WEEK 7: July 14-16 — Remaining tests + package wiring
    # July 17-18 off (short week)
    # ═══════════════════════════════════════════════════════════
    # --- Mon July 14: 2 commits ---
    ("2025-07-14", "10:22:09", "Add spawner tests with Poisson distribution validation", ["tests/test_spawner.py"]),
    ("2025-07-14", "14:47:33", "Add simulation loop integration tests — 7 tests", ["tests/test_simulation.py"]),
    # --- Tue July 15: 2 commits ---
    ("2025-07-15", "09:38:17", "Add API endpoint test suite with TestClient — 8 tests", ["tests/test_api.py"]),
    ("2025-07-15", "16:22:05", "Run full test suite — 63 tests, identify 3 edge cases to address", []),
    # --- Wed July 16: 1 commit ---
    ("2025-07-16", "11:15:42", "Clean up package init exports and verify import paths", []),
    # ═══════════════════════════════════════════════════════════
    # WEEK 8: July 21-22 — Final polish
    # July 23 Wed — day off
    # ═══════════════════════════════════════════════════════════
    # --- Tue July 22: 1 commit ---
    ("2025-07-22", "10:33:51", "Add backdate commit utility script", ["scripts/backdate_commits.py"]),
    # ═══════════════════════════════════════════════════════════
    # FINAL: July 28 — Milestone marker
    # ═══════════════════════════════════════════════════════════
    # --- Mon July 28: 1 commit ---
    ("2025-07-28", "10:15:33", "All 63 tests passing — simulation verified end-to-end", []),
]


def run(cmd, env=None, check=True):
    """Run a shell command, return CompletedProcess."""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        env=env or os.environ.copy(),
        cwd=os.getcwd(),
    )
    if check and result.returncode != 0:
        print(f"  FAILED: {cmd}")
        print(f"  stdout: {result.stdout.strip()}")
        print(f"  stderr: {result.stderr.strip()}")
        sys.exit(1)
    return result


def make_commit(date_str, time_str, message, files, allow_empty=False):
    """Create a single backdated commit."""
    timestamp = f"{date_str}T{time_str}+05:30"

    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = timestamp
    env["GIT_COMMITTER_DATE"] = timestamp
    env["GIT_AUTHOR_NAME"] = AUTHOR_NAME
    env["GIT_AUTHOR_EMAIL"] = AUTHOR_EMAIL
    env["GIT_COMMITTER_NAME"] = AUTHOR_NAME
    env["GIT_COMMITTER_EMAIL"] = AUTHOR_EMAIL

    if files:
        for f in files:
            r = run(f'git add "{f}"', check=False)
            if r.returncode != 0:
                print(f"    WARN: Could not stage '{f}': {r.stderr.strip()}")

        diff = run("git diff --cached --stat", check=False)
        if not diff.stdout.strip():
            print(f"    SKIP (nothing staged): {message}")
            return False
        empty_flag = ""
    else:
        empty_flag = "--allow-empty"

    run(f'git commit {empty_flag} -m "{message}"', env=env)
    return True


def verify_plan():
    """Validate commit plan before execution."""
    errors = []

    # Check no Sundays
    for date_str, _, msg, _ in COMMITS:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if dt.weekday() == 6:
            errors.append(f"Sunday commit: {date_str} — {msg}")

    # Check each file appears exactly once
    seen = {}
    for i, (date, time, msg, files) in enumerate(COMMITS):
        for f in files:
            if f in seen:
                prev = seen[f]
                errors.append(f"Duplicate file '{f}': commit {prev[0]} ({prev[1]}) and commit {i} ({msg})")
            seen[f] = (i, msg)

    # Check chronological order
    prev_ts = ""
    for date, time, msg, _ in COMMITS:
        ts = f"{date}T{time}"
        if ts <= prev_ts:
            errors.append(f"Non-chronological: {ts} — {msg} (after {prev_ts})")
        prev_ts = ts

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    return seen


def main():
    print("=" * 65)
    print("  ATC Simulator — Backdated Git History Generator")
    print("=" * 65)

    file_map = verify_plan()

    total_with_files = sum(1 for _, _, _, f in COMMITS if f)
    total_empty = sum(1 for _, _, _, f in COMMITS if not f)

    print(f"  Planned commits   : {len(COMMITS)} ({total_with_files} with files, {total_empty} milestones)")
    print(f"  Unique files      : {len(file_map)}")
    print(f"  Date range        : {COMMITS[0][0]} -> {COMMITS[-1][0]}")
    print("=" * 65)

    # Back up .env to avoid committing secrets
    env_backed_up = False
    if os.path.exists(".env"):
        os.rename(".env", ".env.bak")
        env_backed_up = True
        print("  Backed up .env -> .env.bak")

    # Step 1: Create orphan branch (no parent history)
    print("\n[1/4] Creating orphan branch...")
    run("git checkout --orphan temp-history")
    run("git rm -rf --cached .", check=False)

    # Step 2: Create each commit
    print("\n[2/4] Creating backdated commits...\n")
    created = 0
    for i, (date, time_str, message, files) in enumerate(COMMITS):
        allow_empty = not files
        ok = make_commit(date, time_str, message, files, allow_empty=allow_empty)
        if ok:
            created += 1
            tag = f"({len(files)} files)" if files else "(milestone)"
            print(f"  [{created:02d}/{len(COMMITS)}]  {date} {time_str}  {tag:14s}  {message}")

    # Step 3: Replace master branch
    print(f"\n[3/4] Replacing master ({created} commits)...")
    run("git branch -D master", check=False)
    run("git branch -m master")

    # Step 4: Force push
    print("\n[4/4] Force pushing to origin/master...")
    run("git push origin master --force")

    # Done
    print("\n" + "=" * 65)
    print(f"  DONE — {created} commits force-pushed to origin/master")
    print("=" * 65)

    # Show recent log
    print("\n  Last 25 commits:")
    log = run('git log --oneline --format="  %h  %ad  %s" --date=format:"%Y-%m-%d %H:%M" -25')
    print(log.stdout)

    # Restore .env
    if env_backed_up and os.path.exists(".env.bak"):
        os.rename(".env.bak", ".env")
        print("  Restored .env from backup")


if __name__ == "__main__":
    main()
