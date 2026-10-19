"""Supervisor for the voice worker on a server: `python -m ai_sdr.voice.run` (started by the web backend; one per
machine). Plan root cause 7: the worker used to be a bare subprocess of the web backend, so a crash, a stuck process
or old code after an update went unnoticed while /health said ok.

What it does:
- holds a lock for its whole life, so exactly one supervisor runs per machine;
- downloads the model files (retrying until they are there) before the first start;
- runs the worker in LiveKit's `start` mode, restarts it with backoff if it exits;
- picks the health port that is free (8081/8082), so a new worker can start while an old one finishes its calls;
- when the code version changes (a sync to the preview pod), starts a worker with the new code and lets the old one
  drain its calls (SIGTERM) instead of killing them;
- writes the worker's state to a status file the web backend serves at /health;
- keeps the worker's log in a rotating file (never the backend's stdout: a pipe nobody reads froze the agent, 16 Oct).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import logging.handlers
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

LOCK = Path(os.environ.get("AGENT_LOCK", "/tmp/ai_sdr_agent.lock"))
STATUS = Path(os.environ.get("AGENT_STATUS", "/tmp/ai_sdr_agent_status.json"))
LOG = Path(os.environ.get("AGENT_LOG", "/tmp/ai_sdr_agent.log"))
VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"
ENV_FILE = Path(os.environ.get("AGENT_ENV_FILE", ".env"))   # the app's settings (cwd = the backend directory)
SELF_FILE = Path(__file__).resolve()
PORTS = (8081, 8082)
HEALTHY_RESET_S = 600     # a worker that ran this long resets the restart backoff
VERSION_CHECK_S = 15

log = logging.getLogger("ai_sdr.supervisor")


def code_version() -> str:
    try:
        return VERSION_FILE.read_text().strip() or "unknown"
    except FileNotFoundError:
        return "unknown"


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except FileNotFoundError:
        return "none"


def settings_fingerprint() -> str:
    """Changes when .env changes, without exposing any value."""
    return _sha(ENV_FILE)


def _read_env_file() -> dict:
    try:
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}
    except Exception:
        log.exception("could not read %s", ENV_FILE)
        return {}


# Settings the platform itself provides (Emergent's Secrets panel on the deployed app), named by the web backend,
# which sees the environment before .env is read. They always win over the deployed app's frozen .env copy (17-19 Oct:
# prod used MONGO_URL=localhost and the old ElevenLabs/LiteLLM keys from that copy). Not inferred from "value differs
# from .env": a supervisor that restarted itself keeps its original environment, and that guess pinned stale keys.
PLATFORM_KEYS = {k for k in os.environ.get("SUPERVISOR_PLATFORM_KEYS", "").split(",") if k}


def worker_env(port: int, version: str) -> dict:
    """The worker's environment, built fresh for every worker: .env as it is NOW, on top of what the supervisor was
    started with. Two kinds of keys keep their value: those the backend set on purpose (SUPERVISOR_PINNED, e.g. the
    preview's agent name) and those the platform injected (PLATFORM_KEYS, e.g. the deployed app's MONGO_URL).
    17 Oct: a new voice setting in .env never reached the worker, because it inherited the supervisor's old copy."""
    env = dict(os.environ)
    pinned = {k for k in os.environ.get("SUPERVISOR_PINNED", "").split(",") if k} | PLATFORM_KEYS
    for k, v in _read_env_file().items():
        if k not in pinned:
            env[k] = v
    env.update(AGENT_HEALTH_PORT=str(port), APP_VERSION=version)
    return env


def _port_free(port: int) -> bool:
    """Same bind options as a server: a port in TIME_WAIT after a worker exited counts as free (drill, 17 Oct)."""
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status, r.read().decode(errors="replace")
    except Exception as e:
        return getattr(e, "code", 0) or 0, str(e)


class Worker:
    def __init__(self, port: int, version: str, out: logging.Logger):
        self.port, self.version = port, version
        self.settings = settings_fingerprint()
        self.started = time.time()
        self.registered = False
        self.worker_id: str | None = None
        env = worker_env(port, version)
        self.proc = subprocess.Popen([sys.executable, "-m", "ai_sdr.agent.worker", "start"], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                     start_new_session=True)
        threading.Thread(target=self._pump, args=(out,), daemon=True).start()

    def _pump(self, out: logging.Logger) -> None:
        """Copy the worker's output to the rotating log, and notice its registration with LiveKit."""
        for raw in self.proc.stdout:
            out.info(raw.rstrip("\n"))
            if not self.registered and "registered worker" in raw:
                self.registered = True
                try:
                    self.worker_id = json.loads(raw).get("id")
                except (json.JSONDecodeError, AttributeError):
                    pass

    def alive(self) -> bool:
        return self.proc.poll() is None

    def reap(self) -> None:
        """After the worker exited: kill anything left in its process group (job processes)."""
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def drain(self) -> None:
        """SIGTERM = stop taking calls, finish the ones in progress, then exit (LiveKit `start` mode)."""
        if self.alive():
            os.killpg(self.proc.pid, signal.SIGTERM)

    def health(self) -> dict:
        code, _ = _get(f"http://127.0.0.1:{self.port}/")
        wcode, body = _get(f"http://127.0.0.1:{self.port}/worker")
        info = {}
        if wcode == 200:
            try:
                info = json.loads(body)
            except json.JSONDecodeError:
                pass
        return {"http_ok": code == 200, "worker": info}


class Supervisor:
    def __init__(self):
        self.out = logging.getLogger("ai_sdr.worker_output")
        self.out.propagate = False
        handler = logging.handlers.RotatingFileHandler(LOG, maxBytes=20_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.out.addHandler(handler)
        self.out.setLevel(logging.INFO)
        self.current: Worker | None = None
        self.draining: list[Worker] = []
        self.restarts = 0
        self.last_exit: dict | None = None
        self.stopping = False
        self.self_hash = _sha(SELF_FILE)
        self.phase = "starting"

    def download_models(self) -> None:
        for attempt in range(1, 6):
            rc = subprocess.run([sys.executable, "-m", "ai_sdr.agent.worker", "download-files"],
                                capture_output=True, text=True)
            if rc.returncode == 0:
                log.info("model files ready")
                return
            log.warning("model download failed (attempt %s): %s", attempt, rc.stdout[-500:] + rc.stderr[-500:])
            time.sleep(min(30, 2 ** attempt))
        log.error("model download kept failing; starting the worker anyway (it will report the error)")

    def _free_port(self) -> int | None:
        busy = {w.port for w in self.draining if w.alive()}
        for p in PORTS:
            if p not in busy and _port_free(p):
                return p
        return None

    def start_worker(self) -> bool:
        port = self._free_port()
        if port is None:  # e.g. two older workers still finishing calls: try again on the next loop
            log.error("no free health port among %s; will retry", PORTS)
            self.current = None
            return False
        version = code_version()
        self.current = Worker(port, version, self.out)
        log.info("worker started: pid %s port %s version %s", self.current.proc.pid, self.current.port, version)
        return True

    def stop_leftovers(self) -> None:
        """Workers started by a previous supervisor that died (they run in their own session, so they survive it):
        drain them so two workers never take calls side by side."""
        try:
            old = json.loads(STATUS.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return
        pids = [(old.get("worker") or {}).get("pid")] + [d.get("pid") for d in old.get("draining", [])]
        for pid in filter(None, pids):
            try:
                cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace") if Path("/proc").exists() \
                    else subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
            except OSError:
                continue
            if "ai_sdr.agent.worker" in cmd:
                log.warning("draining leftover worker %s from a previous supervisor", pid)
                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass

    def write_status(self) -> None:
        w = self.current
        status = {
            "supervisor_pid": os.getpid(), "updated_at": time.time(), "code_version": code_version(),
            "phase": self.phase,
            "restarts": self.restarts, "last_exit": self.last_exit,
            "draining": [{"pid": d.proc.pid, "version": d.version} for d in self.draining if d.alive()],
            "worker": None if w is None else {
                "pid": w.proc.pid, "alive": w.alive(), "port": w.port, "version": w.version, "settings": w.settings,
                "registered": w.registered, "worker_id": w.worker_id, "up_s": round(time.time() - w.started),
                **(w.health() if w.alive() else {})},
        }
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(status))
        tmp.replace(STATUS)

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        self.stop_leftovers()
        self.phase = "downloading model files"
        self.write_status()  # a fresh status at once, so /health never shows the previous supervisor's
        self.download_models()
        self.phase = "running"
        self.start_worker()
        last_version_check = time.time()
        while not self.stopping:
            try:
                self._tick(last_version_check)
                if time.time() - last_version_check > VERSION_CHECK_S:
                    last_version_check = time.time()
            except Exception:  # the supervisor itself must never die
                log.exception("supervisor loop error")
            time.sleep(2)
        for wk in [self.current, *self.draining]:
            if wk is not None:
                wk.drain()
        deadline = time.time() + int(os.environ.get("AGENT_DRAIN_TIMEOUT_S", "900"))
        while time.time() < deadline and any(wk.alive() for wk in [self.current, *self.draining] if wk):
            time.sleep(1)

    def _tick(self, last_version_check: float) -> None:
        w = self.current
        if w is None:
            self.start_worker()
        elif not w.alive():
            w.reap()
            up = time.time() - w.started
            self.last_exit = {"code": w.proc.returncode, "up_s": round(up), "at": time.time()}
            self.restarts = 0 if up > HEALTHY_RESET_S else self.restarts + 1
            delay = min(60, 2 ** self.restarts) if self.restarts else 1
            log.error("worker exited with %s after %ss; restarting in %ss", w.proc.returncode, round(up), delay)
            self.current = None
            self.write_status()
            time.sleep(delay)
            self.start_worker()
        elif time.time() - last_version_check > VERSION_CHECK_S and _sha(SELF_FILE) != self.self_hash:
            # the supervisor's own code changed: restart it in place; the new one drains this worker and starts one
            log.info("supervisor code changed: restarting the supervisor")
            self.write_status()
            os.execv(sys.executable, [sys.executable, "-m", "ai_sdr.voice.run"])
        elif time.time() - last_version_check > VERSION_CHECK_S and (
                code_version() != w.version or settings_fingerprint() != w.settings):
            log.info("code %s -> %s, settings %s -> %s: new worker, old one finishes its calls",
                     w.version, code_version(), w.settings, settings_fingerprint())
            w.drain()
            self.draining.append(w)
            self.start_worker()
        for d in self.draining:
            if not d.alive():
                d.reap()
        self.draining = [d for d in self.draining if d.alive()]
        self.write_status()

    def _stop(self, *_):
        self.stopping = True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s supervisor %(levelname)s %(message)s",
                        handlers=[logging.handlers.RotatingFileHandler(LOG.with_suffix(".supervisor.log"),
                                                                       maxBytes=5_000_000, backupCount=2)])
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("voice worker supervisor already running on this machine", flush=True)
        return
    Supervisor().run()


if __name__ == "__main__":
    main()
