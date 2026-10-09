# -*- coding: utf-8 -*-
"""Bootstrap: force TITAN_PRO_V75_PWA to use app private LLL and start Flask."""
from __future__ import annotations

import importlib.util
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

_engine_mod = None
_started = False
_lock = threading.Lock()
_last_error = ""


def _patch_source(text: str, home: Path) -> str:
    """Disable Android shared-storage hard-fail so TITAN_HOME / filesDir works."""
    # 1) Never raise when /storage/emulated/0 exists but is not writable
    text = text.replace(
        "if android_storage_present:\n        raise RuntimeError(",
        "if False and android_storage_present:\n        raise RuntimeError(",
    )
    # 2) Prefer TITAN_HOME first when set
    needle = "candidates = (\n        TITAN_SHARED_STORAGE,\n        Path(\"/sdcard\"),\n        Path(\"/storage/self/primary\"),\n    )"
    if needle in text:
        text = text.replace(
            needle,
            "# Patched for Android app private storage\n"
            "    _env_home = str(os.environ.get(\"TITAN_HOME\") or \"\").strip()\n"
            "    if _env_home:\n"
            "        try:\n"
            "            _p = Path(_env_home)\n"
            "            if _p.name != TITAN_FOLDER_NAME:\n"
            "                _p = _p / TITAN_FOLDER_NAME\n"
            "            _p.mkdir(parents=True, exist_ok=True)\n"
            "            (_p / \".titan_jjj_probe\").write_text(\"ok\", encoding=\"utf-8\")\n"
            "            (_p / \".titan_jjj_probe\").unlink(missing_ok=True)\n"
            "            return _p\n"
            "        except OSError:\n"
            "            pass\n"
            "    candidates = (\n"
            "        TITAN_SHARED_STORAGE,\n"
            "        Path(\"/sdcard\"),\n"
            "        Path(\"/storage/self/primary\"),\n"
            "    )",
        )
    return text


def start_titan(files_dir: str) -> str:
    """Start the real TITAN Flask engine. Returns status string."""
    global _engine_mod, _started, _last_error
    with _lock:
        if _started:
            return "already_started"
        try:
            home = Path(files_dir) / "LLL"
            for sub in (
                home,
                home / "data",
                home / "cache",
                home / "memory",
                home / "secrets",
                home / "cache" / "tmp",
                home / "cache" / "pycache",
                home / "cache" / "history",
                home / "data" / "replay",
                home / "data" / "flask_instance",
            ):
                sub.mkdir(parents=True, exist_ok=True)

            os.environ["TITAN_HOME"] = str(home)
            os.environ["TITAN_OPEN_BROWSER"] = "0"
            os.environ["TMPDIR"] = str(home / "cache" / "tmp")
            os.environ["TEMP"] = str(home / "cache" / "tmp")
            os.environ["TMP"] = str(home / "cache" / "tmp")
            os.environ["PYTHONUNBUFFERED"] = "1"

            here = Path(__file__).resolve().parent
            src = here / "TITAN_PRO_V75_PWA.py"
            if not src.is_file():
                raise FileNotFoundError("TITAN_PRO_V75_PWA.py missing in python/")

            raw = src.read_text(encoding="utf-8", errors="replace")
            patched = _patch_source(raw, home)
            out = here / "_titan_engine_patched.py"
            out.write_text(patched, encoding="utf-8")

            spec = importlib.util.spec_from_file_location("titan_engine", str(out))
            if spec is None or spec.loader is None:
                raise RuntimeError("cannot load titan_engine spec")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["titan_engine"] = mod
            spec.loader.exec_module(mod)
            _engine_mod = mod

            def _run():
                try:
                    # Prefer explicit host/port if run_titan accepts kwargs
                    fn = getattr(mod, "run_titan", None)
                    if fn is None:
                        raise RuntimeError("run_titan not found")
                    try:
                        fn(open_browser=False)
                    except TypeError:
                        fn()
                except Exception as exc:
                    global _last_error
                    _last_error = str(exc)
                    print("TITAN run_titan error:", exc)

            threading.Thread(target=_run, name="titan-flask", daemon=True).start()
            _started = True
            return "started"
        except Exception as exc:
            _last_error = str(exc)
            print("TITAN bootstrap error:", exc)
            raise


def wait_ready(url: str = "http://127.0.0.1:5000/health", timeout: float = 180.0) -> bool:
    deadline = time.time() + float(timeout)
    urls = [
        url,
        "http://127.0.0.1:5000/",
        "http://127.0.0.1:5000/health",
        "http://localhost:5000/health",
        "http://localhost:5000/",
    ]
    while time.time() < deadline:
        for u in urls:
            try:
                with urllib.request.urlopen(u, timeout=2.5) as resp:
                    if 200 <= getattr(resp, "status", 200) < 500:
                        return True
            except Exception:
                pass
        if _last_error:
            # keep waiting a bit; engine may recover
            pass
        time.sleep(1.0)
    return False


def last_error() -> str:
    return _last_error or ""
