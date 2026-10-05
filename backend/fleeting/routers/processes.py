"""Processes and active applications monitoring and control router.

Compositor support is best-effort: Hyprland is the supported target (see
README) and is tried first; Sway and X11/wmctrl are fallbacks for anyone running
this on another Wayland or X session. If none answer, /api/processes/apps
degrades to listing GUI-named or terminal-owning processes instead of windows.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import signal
import subprocess
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

if TYPE_CHECKING:  # pragma: no cover - psutil is optional at runtime
    import psutil

log = logging.getLogger("fleeting.processes")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

router = APIRouter(prefix="/api/processes", tags=["processes"])


def _get_cpu_map() -> Dict[int, float]:
    """Fast snapshot of CPU percentages via ps on Linux/Unix systems."""
    cpu_map: Dict[int, float] = {}
    try:
        out = subprocess.run(
            ["ps", "-axo", "pid,%cpu"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
        for line in out.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    cpu_map[int(parts[0])] = float(parts[1])
                except ValueError:
                    pass
    except Exception:
        pass
    return cpu_map


def _get_active_windows() -> Dict[int, Dict[str, str]]:
    """Detect active desktop application windows on Linux (Hyprland, Wayland, X11)."""
    windows: Dict[int, Dict[str, str]] = {}

    # 1. Hyprland
    try:
        out = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
        if out.strip():
            clients = json.loads(out)
            if isinstance(clients, list):
                for c in clients:
                    pid = c.get("pid")
                    if pid and pid > 0:
                        windows[pid] = {
                            "title": str(c.get("title") or ""),
                            "class": str(c.get("class") or c.get("initialClass") or ""),
                        }
                if windows:
                    return windows
    except Exception:
        pass

    # 2. Sway / Wayland
    try:
        out = subprocess.run(
            ["swaymsg", "-t", "get_tree"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
        if out.strip():
            tree = json.loads(out)

            def find_windows(node):
                if not isinstance(node, dict):
                    return
                pid = node.get("pid")
                if pid and pid > 0 and node.get("name"):
                    app_id = node.get("app_id") or node.get("window_properties", {}).get("class") or ""
                    windows[pid] = {"title": str(node.get("name") or ""), "class": str(app_id)}
                for child in node.get("nodes", []):
                    find_windows(child)
                for child in node.get("floating_nodes", []):
                    find_windows(child)

            find_windows(tree)
            if windows:
                return windows
    except Exception:
        pass

    # 3. X11 via wmctrl
    try:
        out = subprocess.run(
            ["wmctrl", "-lp"],
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 5:
                try:
                    pid = int(parts[2])
                    if pid > 0:
                        windows[pid] = {
                            "title": parts[4].strip(),
                            "class": "",
                        }
                except ValueError:
                    continue
        if windows:
            return windows
    except Exception:
        pass

    return windows


def get_process_info_psutil(p: "psutil.Process", cpu_map: Optional[Dict[int, float]] = None) -> Optional[Dict[str, Any]]:
    try:
        rss = p.memory_info().rss / (1024 * 1024)
        mem = round(rss, 1)
        created = datetime.datetime.fromtimestamp(p.create_time()).isoformat()
        cpu = (cpu_map.get(p.pid) if cpu_map else None)
        if cpu is None:
            cpu = p.cpu_percent(interval=None) or 0.0

        try:
            cmd = p.cmdline()
        except Exception:
            cmd = []

        return {
            "pid": p.pid,
            "name": p.name(),
            "username": p.username(),
            "cpu_percent": round(cpu, 1),
            "memory_mb": mem,
            "status": p.status(),
            "command": cmd,
            "created": created,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def get_process_info_fallback(pid: int, cpu_map: Optional[Dict[int, float]] = None) -> Optional[Dict[str, Any]]:
    """Fallback reader using Linux /proc filesystem if psutil is unavailable."""
    proc_path = f"/proc/{pid}"
    if not os.path.exists(proc_path):
        return None

    try:
        name = ""
        status = "unknown"
        rss_kb = 0
        with open(f"{proc_path}/status", "r", errors="ignore") as f:
            for line in f:
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("State:"):
                    status = line.split(":", 1)[1].strip().split()[0]
                elif line.startswith("VmRSS:"):
                    parts = line.split(":", 1)[1].strip().split()
                    if parts:
                        rss_kb = int(parts[0])

        with open(f"{proc_path}/cmdline", "rb") as f:
            raw_cmd = f.read().split(b"\x00")
            cmd = [c.decode("utf-8", errors="replace") for c in raw_cmd if c]

        mem = round(rss_kb / 1024.0, 1)
        cpu = (cpu_map.get(pid, 0.0) if cpu_map else 0.0)

        # creation time
        stat = os.stat(proc_path)
        created = datetime.datetime.fromtimestamp(stat.st_ctime).isoformat()

        return {
            "pid": pid,
            "name": name or f"pid-{pid}",
            "username": "",
            "cpu_percent": round(cpu, 1),
            "memory_mb": mem,
            "status": status,
            "command": cmd,
            "created": created,
        }
    except Exception:
        return None


@router.get("/whoami")
def whoami() -> Dict[str, str]:
    """The user this server runs as.

    The client needs this to decide which processes it can even offer to end,
    rather than letting the OS refuse with a bare 403 after the click.
    """
    return {"user": _current_user()}


@router.get("/apps")
def list_apps() -> List[Dict[str, Any]]:
    """List active user-facing applications."""
    window_map = _get_active_windows()
    cpu_map = _get_cpu_map()
    apps: List[Dict[str, Any]] = []

    if window_map:
        for pid, meta in window_map.items():
            if pid <= 0:
                continue
            info = None
            if HAS_PSUTIL:
                try:
                    p = psutil.Process(pid)
                    info = get_process_info_psutil(p, cpu_map)
                except Exception:
                    pass
            if not info:
                info = get_process_info_fallback(pid, cpu_map)

            if info:
                # Use window title and preferred app class name
                info["window_title"] = meta.get("title") or ""
                if meta.get("class"):
                    info["name"] = meta["class"]
                apps.append(info)
    else:
        # Generic desktop fallback: list running apps that have terminal or GUI names
        common_gui_names = {
            "code", "chrome", "firefox", "zen", "zen-bin", "brave", "edge",
            "slack", "discord", "spotify", "telegram-desktop", "steam",
            "vlc", "obs", "gimp", "inkscape", "blender", "fleeting", "electron"
        }
        if HAS_PSUTIL:
            for p in psutil.process_iter(["pid", "name", "terminal"]):
                try:
                    pname = (p.info.get("name") or "").lower()
                    has_term = bool(p.info.get("terminal"))
                    if has_term or any(gui in pname for gui in common_gui_names):
                        info = get_process_info_psutil(p, cpu_map)
                        if info:
                            info["window_title"] = ""
                            apps.append(info)
                except Exception:
                    continue

    # Sort apps by CPU descending
    apps.sort(key=lambda x: x.get("cpu_percent") or 0.0, reverse=True)
    return apps


@router.get("/list")
def list_processes(
    sort_by: str = Query("cpu", description="Sort by: cpu, memory, name, pid"),
    limit: int = Query(100, ge=1, le=2000, description="Max limit"),
) -> List[Dict[str, Any]]:
    """List system processes."""
    cpu_map = _get_cpu_map()
    procs: List[Dict[str, Any]] = []

    if HAS_PSUTIL:
        for p in psutil.process_iter():
            info = get_process_info_psutil(p, cpu_map)
            if info:
                procs.append(info)
    else:
        # Proc filesystem fallback
        try:
            for entry in os.listdir("/proc"):
                if entry.isdigit():
                    pid = int(entry)
                    info = get_process_info_fallback(pid, cpu_map)
                    if info:
                        procs.append(info)
        except Exception as e:
            log.exception("Failed to read /proc: %s", e)

    if sort_by == "cpu":
        procs.sort(key=lambda x: x.get("cpu_percent") or 0.0, reverse=True)
    elif sort_by == "memory":
        procs.sort(key=lambda x: x.get("memory_mb") or 0.0, reverse=True)
    elif sort_by == "name":
        procs.sort(key=lambda x: (x.get("name") or "").lower())
    elif sort_by == "pid":
        procs.sort(key=lambda x: x.get("pid") or 0)

    return procs[:limit]


def _current_user() -> str:
    """Who this server runs as. Used to explain permission refusals."""
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return ""


def _owner_of(pid: int) -> str:
    """Username owning `pid`, best effort. Empty when unknown."""
    if HAS_PSUTIL:
        try:
            return psutil.Process(pid).username() or ""
        except Exception:
            return ""
    try:
        import pwd

        with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
            uid = next(
                (int(l.split()[1]) for l in fh if l.startswith("Uid:")), None
            )
        return pwd.getpwuid(uid).pw_name if uid is not None else ""
    except Exception:
        return ""


def _denied(pid: int) -> HTTPException:
    """A 403 that says why, instead of a bare 'Access denied'."""
    owner = _owner_of(pid) or "another user"
    me = _current_user() or "this user"
    return HTTPException(
        status_code=403,
        detail=(
            f"Process is owned by {owner}, and Fleeting runs as {me}. "
            "Use sudo from a terminal to end it."
        ),
    )


@router.post("/{pid}/kill")
def kill_process(pid: int, force: bool = Query(False)) -> Dict[str, Any]:
    """Terminate or kill a process by PID."""
    if pid <= 1:
        raise HTTPException(status_code=400, detail="Cannot terminate system root/init process")

    if HAS_PSUTIL:
        try:
            p = psutil.Process(pid)
            if force:
                p.kill()
            else:
                p.terminate()
            return {"ok": True, "pid": pid}
        except psutil.NoSuchProcess:
            raise HTTPException(status_code=404, detail="Process not found")
        except psutil.AccessDenied:
            raise _denied(pid)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    else:
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)
            return {"ok": True, "pid": pid}
        except ProcessLookupError:
            raise HTTPException(status_code=404, detail="Process not found")
        except PermissionError:
            raise _denied(pid)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{pid}/details")
def process_details(pid: int) -> Dict[str, Any]:
    """Get detailed runtime info for a process."""
    cpu_map = _get_cpu_map()

    if HAS_PSUTIL:
        try:
            p = psutil.Process(pid)
            info = get_process_info_psutil(p, cpu_map)
            if not info:
                raise HTTPException(status_code=404, detail="Process info unavailable")

            try:
                info["num_threads"] = p.num_threads()
            except Exception:
                info["num_threads"] = 0

            try:
                info["open_files_count"] = len(p.open_files())
            except Exception:
                info["open_files_count"] = 0

            try:
                # psutil renamed connections() to net_connections() in 6.0.
                conn_fn = getattr(p, "net_connections", None) or p.connections
                info["connections_count"] = len(conn_fn())
            except Exception:
                info["connections_count"] = 0

            try:
                parent = p.parent()
                info["parent_pid"] = parent.pid if parent else None
            except Exception:
                info["parent_pid"] = None

            try:
                info["children"] = [c.pid for c in p.children(recursive=False)]
            except Exception:
                info["children"] = []

            return info
        except psutil.NoSuchProcess:
            raise HTTPException(status_code=404, detail="Process not found")
        except psutil.AccessDenied:
            raise HTTPException(status_code=403, detail="Access denied")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
    else:
        info = get_process_info_fallback(pid, cpu_map)
        if not info:
            raise HTTPException(status_code=404, detail="Process not found")

        info["num_threads"] = 0
        info["open_files_count"] = 0
        info["connections_count"] = 0
        info["parent_pid"] = None
        info["children"] = []
        return info
