#!/usr/bin/env python3
"""Capture the users-guide screenshots against a fresh, synthetic demo home — repeatably.

Screenshots rot the moment the UI changes; this script is the anti-rot path (prm#91): it seeds a
TEMPORARY demo home (demo fixtures + the merge-overlay seed pairs — never your real data), serves the
workspace on a spare port, drives every important surface with a headless browser, and writes the
guide's images to ``docs/img/users-guide/``. After any UI change, re-run it and every image is current:

    .venv/bin/pip install playwright && .venv/bin/playwright install chromium   # one-time, dev-only
    .venv/bin/python scripts/capture_screenshots.py

Playwright is deliberately NOT a project dependency (runtime deps stay tiny — CLAUDE.md); it is a
dev-machine tool like a linter. The script never touches your PRM home: it builds its own under a
temp directory and serves on port 8788 (``--port`` to change; your normal 8770 server can keep running).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT = REPO / "docs" / "img" / "users-guide"
PYTHON = sys.executable
VIEWPORT = {"width": 1440, "height": 900}
JPEG_QUALITY = 82                                  # matches the explainers' size/quality trade-off


def sh(env, *args):
    subprocess.run([PYTHON, *args], env=env, check=True, cwd=REPO,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def seed_home(home: Path) -> dict:
    """Demo fixtures + the mergetest overlay pairs, then the ids/keys the shots deep-link to."""
    env = {**os.environ, "PRM_HOME": str(home)}
    sh(env, "-m", "cli", "init", "--demo")
    sh(env, str(REPO / "scripts" / "seed_merge_overlay_demo.py"))

    os.environ["PRM_HOME"] = str(home)             # resolve_home reads it at call time
    from cli.config import resolve_home
    from daemon.server import route
    h = resolve_home(None)

    def get(path, query=None):
        return json.loads(route("GET", path, query or {}, h)[2])

    def first_id(q, name):
        return next(r["id"] for r in get("/api/search", {"q": [q], "limit": ["20"]})["results"]
                    if r["name"] == name)

    ada = first_id("lovelace", "Ada Lovelace")
    melvin = first_id("melvin", "Melvin Mergetest")
    book2 = next(g["group_id"] for g in get("/api/groups")["groups"] if g["name"] == "Book club (pair 2)")
    key = next(c["key"] for c in get("/api/candidates")["clusters"]
               if c["tier"] == "confident" and melvin in (c["member_ids"] or []))
    return {"ada": ada, "melvin": melvin, "book2": book2, "dupkey": key}


def start_server(home: Path, port: int) -> tuple[subprocess.Popen, str]:
    env = {**os.environ, "PRM_HOME": str(home)}
    proc = subprocess.Popen([PYTHON, "-m", "cli", "serve", "--port", str(port)], env=env, cwd=REPO,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    url_file = home / "workspace.url"
    for _ in range(80):                            # the daemon writes the session-keyed link on boot
        if url_file.exists() and url_file.read_text(encoding="utf-8").strip():
            return proc, url_file.read_text(encoding="utf-8").strip()
        if proc.poll() is not None:
            raise SystemExit("the workspace server exited early — is the port in use?")
        time.sleep(0.25)
    raise SystemExit("timed out waiting for the workspace URL")


def capture(session_url: str, ids: dict) -> list[str]:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    base = session_url.split("?")[0].rstrip("/")
    taken, failed = [], []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(session_url)                     # mints the session cookie, lands on Contacts
        page.wait_for_selector(".row", timeout=15000)

        def shot(name: str, wait: str, *, hash_path: str | None = None, click: str | None = None,
                 settle_ms: int = 350):
            try:
                if hash_path is not None:
                    page.goto(f"{base}/#/{hash_path}")
                if click is not None:
                    page.click(click)
                page.wait_for_selector(wait, timeout=15000)
                page.wait_for_timeout(settle_ms)   # let entrance animations / async annotate finish
                page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=JPEG_QUALITY)
                taken.append(name)
            except Exception as exc:               # noqa: BLE001 — a missed shot is reported, not fatal
                failed.append(f"{name}: {exc}")

        shot("contacts", ".kv", hash_path=f"contacts/{ids['ada']}")
        shot("contact-duplicate", ".dupbanner", hash_path=f"contacts/{ids['melvin']}", settle_ms=600)
        shot("contact-edit", ".editkv", click="#edit-contact")
        shot("tags-manage", ".tagmodal", click="[data-managetags]")
        page.keyboard.press("Escape"); page.click("#tm-close") if page.is_visible("#tm-close") else None
        shot("groups", ".grouprow", hash_path="groups")
        shot("group-detail", "#grp-dups .dupbanner", hash_path=f"groups/{ids['book2']}", settle_ms=600)
        shot("duplicates-bulk", "#b-safe .groupcard", hash_path="duplicates")
        shot("duplicates-spotcheck", "#b-stage .mergecard", click="#b-go", settle_ms=600)
        shot("duplicates-review", "#merge .mergecard", hash_path=f"duplicates/{ids['dupkey']}")
        shot("schema", "#schema-body .fielddef", hash_path="schema")
        shot("schema-field", ".fieldmodal", click="#schema-new")
        page.click("#fm-close") if page.is_visible("#fm-close") else None
        shot("data", "#dropzone", hash_path="data")
        shot("access", ".axcard", hash_path="access")
        shot("access-gate", ".gatecard", click="#ax-grant")

        browser.close()

    print(f"captured {len(taken)}: {', '.join(taken)}")
    if failed:                                     # fail loudly — a silent gap would rot the guide
        print("FAILED:\n  " + "\n  ".join(failed), file=sys.stderr)
        return failed
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8788, help="spare port for the throwaway server")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="prm-shots-") as tmp:
        home = Path(tmp) / "home"
        print(f"seeding a throwaway demo home in {home} …")
        ids = seed_home(home)
        proc, url = start_server(home, args.port)
        try:
            failed = capture(url, ids)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
