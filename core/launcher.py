"""Double-click launcher: start the Mise hub in the background (no terminal window) and open the Hub page.

If Mise is already running, it just opens the Hub page. Used by the desktop shortcut
(scripts/install_shortcut.ps1 on Windows, Mise.command on macOS).
  python -m core.launcher
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import config

HUB = f"http://localhost:{config.LOCAL_PORT}/hub"


def running() -> bool:
    try:
        return urllib.request.urlopen(f"http://localhost:{config.LOCAL_PORT}/api/meta", timeout=1.5).status == 200
    except OSError:
        return False


def main():
    if running():
        webbrowser.open(HUB)
        return
    root = config.ROOT
    env = {**os.environ, "PYTHONUTF8": "1", "APP": "mise", "PHONE": "1", "OPEN_BROWSER": "0",
           "GEMMA_WATCH_MODEL": str(config.MODELS_DIR / "gemma-4-E2B-it.litertlm"), "GEMMA_WATCH_BACKEND": "cpu"}
    env.pop("PORT", None)
    (config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    log = open(config.DATA_DIR / "hub.log", "a", encoding="utf-8")
    log.write(f"\n--- started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log.flush()
    if sys.platform == "win32":
        py = Path(sys.executable).with_name("pythonw.exe")
        py = py if py.exists() else Path(sys.executable)
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        subprocess.Popen([str(py), "-m", "core.server", "mise"], cwd=root, env=env, stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    else:
        subprocess.Popen([sys.executable, "-m", "core.server", "mise"], cwd=root, env=env, stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    for _ in range(120):  # the web server is up within seconds; models keep loading behind the Hub page
        if running():
            break
        time.sleep(0.5)
    webbrowser.open(HUB)


if __name__ == "__main__":
    main()
