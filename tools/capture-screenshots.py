#!/usr/bin/env python3
"""Capture the README screenshots from the UI preview — no backend needed.

Renders templates/index.html against the generic fixture from ui-preview.py,
switches to each tab, and screenshots it with headless Chromium into docs/img/.

    python3 tools/capture-screenshots.py

Requires chromium (or google-chrome) on PATH. Re-run after any UI change so the
README never drifts from what the app actually looks like.
"""
import http.server
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "docs" / "img"
PORT = 8899

# tab id -> (output name, window size, theme, extra JS run before capture)
SHOTS = [
    ("login",    "01-login.png",      (1100, 760), "dark",  None),
    ("tc",       "02-tc-emulation.png", (1440, 1000), "dark",  None),
    ("vlans",    "03-interfaces-vlans.png", (1440, 820), "dark",
     "document.querySelector('.toggle-btn') && document.querySelector('.toggle-btn').click()"),
    ("bridges",  "04-bridge-manager.png", (1440, 760), "dark",  None),
    ("users",    "05-user-management.png", (1440, 820), "dark",  None),
    ("tc",       "06-light-theme.png", (1440, 1000), "light", None),
]


def shrink(path):
    """Re-encode a screenshot with an adaptive palette.

    The captures are flat UI with a small colour count, so a 256-colour palette
    is visually identical at roughly a third of the size. Without this step a
    regeneration silently triples the weight of docs/img (546K vs 213K at the
    time of writing), which is a real cost in a repo people clone.

    Skipped with a warning if Pillow is absent — the screenshots are still
    correct, just larger.
    """
    try:
        from PIL import Image
    except ImportError:
        return False
    with Image.open(path) as im:
        im.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT) \
          .save(path, optimize=True)
    return True


def find_chromium():
    for exe in ("chromium", "chromium-browser", "google-chrome",
                "google-chrome-stable"):
        path = shutil.which(exe)
        if path:
            return path
    sys.exit("error: no chromium/chrome found on PATH")


def build_pages(workdir):
    """Write one HTML file per shot, each auto-selecting its tab and theme."""
    subprocess.run([sys.executable, str(ROOT / "tools" / "ui-preview.py")],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    preview = (ROOT / "_preview.html").read_text()

    for tab, name, _size, theme, extra in SHOTS:
        if tab == "login":
            import re
            html = (ROOT / "templates" / "login.html").read_text()
            html = html.replace("{{ csrf_token() }}", "preview")
            # Drop the conditional message blocks whole — leaving their markup
            # behind renders an empty error box in the screenshot.
            html = re.sub(r"\{% with messages.*?\{% endwith %\}", "", html, flags=re.S)
            html = re.sub(r"\{% if rate_limited %\}.*?\{% endif %\}", "", html, flags=re.S)
            html = re.sub(r"\{%.*?%\}|\{\{.*?\}\}", "", html, flags=re.S)
            html = html.replace("localStorage.getItem('tc-theme')||'dark'",
                                f"'{theme}'")
        else:
            html = preview.replace(
                "loadRole();",
                f"applyTheme('{theme}');switchTab('{tab}');loadRole();", 1)
            if extra:
                html = html.replace(
                    "setInterval(loadAll,20000);",
                    f"setInterval(loadAll,20000);\nsetTimeout(()=>{{{extra}}},600);", 1)
        (workdir / f"{name}.html").write_text(html)


def serve(directory):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(directory), **k)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    chromium = find_chromium()
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="tclab-shots-"))
    build_pages(workdir)
    httpd = serve(workdir)
    try:
        for _tab, name, (w, h), _theme, _extra in SHOTS:
            out = IMG_DIR / name
            subprocess.run([
                chromium, "--headless", "--disable-gpu", "--no-sandbox",
                "--hide-scrollbars", "--force-device-scale-factor=1",
                f"--window-size={w},{h}",
                "--virtual-time-budget=4000",
                f"--screenshot={out}",
                f"http://127.0.0.1:{PORT}/{name}.html",
            ], check=True, capture_output=True)
            raw = out.stat().st_size // 1024
            shrunk = shrink(out)
            kb = out.stat().st_size // 1024
            note = f"  ({raw} KB raw)" if shrunk else "  (Pillow absent - not shrunk)"
            print(f"  {name}  {w}x{h}  {kb} KB{note}")
    finally:
        httpd.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)
        (ROOT / "_preview.html").unlink(missing_ok=True)
    print(f"\nWrote {len(SHOTS)} screenshots to {IMG_DIR}")


if __name__ == "__main__":
    main()
