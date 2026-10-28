"""Start the isolated testing stack using Docker, Git and Python's standard library."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

FRONTEND_URL = "https://github.com/EmilioJOM/DAPP2-frontend.git"
FRONTEND_REF = "27df1e4636ba1b7df60f23ca14f6b967487c021c"
PROJECT = "muni-core-testing"
BACKEND_IMAGE = "muni-core-backend:testing"
FRONTEND_IMAGE = "muni-core-frontend:testing"
PORT = 18080
REQUIRED_KEYS = {"POSTGRES_PASSWORD", "APP_DB_PASSWORD", "RABBITMQ_PASSWORD", "SEED_INITIAL_PASSWORD"}


class Bootstrap:
    def __init__(self, deploy_dir: Path, *, project: str = PROJECT, port: int = PORT) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project) or not project.startswith("muni-core-testing"):
            raise ValueError("Use a project name starting with muni-core-testing and lowercase letters/digits.")
        if not 1024 <= port <= 65535:
            raise ValueError("Use a local testing port between 1024 and 65535.")
        self.project = project
        self.port = port
        self.deploy = deploy_dir.resolve()
        self.repo = self.deploy.parent
        self.state = self.deploy / ".testing"
        self.frontend = self.state / "frontend"
        self.started = time.monotonic()

    def remaining(self) -> float:
        value = 900 - (time.monotonic() - self.started)
        if value <= 0:
            raise RuntimeError("Testing startup exceeded 15 minutes; G1 is not verified.")
        return value

    def run(self, args: list[str], *, capture: bool = False) -> str:
        environment = os.environ.copy()
        # Shell variables have precedence over --env-file in Compose. Do not let
        # a production shell redirect this testing stack's credentials or paths.
        for name in REQUIRED_KEYS | {
            "CORE_HTTP_PORT", "CORE_BACKEND_IMAGE", "CORE_FRONTEND_IMAGE",
            "CORE_FRONTEND_PATH", "JWT_PRIVATE_KEY_PATH", "CORS_ORIGINS",
        }:
            environment.pop(name, None)
        result = subprocess.run(
            args, cwd=self.repo, check=True, text=True,
            stdout=subprocess.PIPE if capture else None, timeout=self.remaining(), env=environment,
        )
        return result.stdout or ""

    def verify_local_engine(self) -> None:
        explicit = os.environ.get("DOCKER_HOST")
        endpoint = json.loads(self.run([
            "docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}",
        ], capture=True))
        for host in (explicit, endpoint):
            if host and not host.startswith(("unix://", "npipe://")):
                raise RuntimeError("Use a local Docker engine for testing; remote endpoints are refused.")

    def compose(self, *args: str, capture: bool = False) -> str:
        # Explicit options prevent reuse of another project's volumes or env file.
        return self.run([
            "docker", "compose", "--project-name", self.project,
            "--env-file", str(self.state / ".env"),
            "-f", str(self.deploy / "compose.yaml"), *args,
        ], capture=capture)

    def checkout_frontend(self) -> None:
        if not self.frontend.exists():
            self.run(["git", "init", str(self.frontend)])
            self.run(["git", "-C", str(self.frontend), "remote", "add", "origin", FRONTEND_URL])
            self.run(["git", "-C", str(self.frontend), "fetch", "--depth=1", "origin", FRONTEND_REF])
            self.run(["git", "-C", str(self.frontend), "checkout", "--detach", "FETCH_HEAD"])
        actual = self.run(["git", "-C", str(self.frontend), "rev-parse", "HEAD"], capture=True).strip()
        dirty = self.run(["git", "-C", str(self.frontend), "status", "--porcelain"], capture=True)
        if actual != FRONTEND_REF or dirty.strip():
            raise RuntimeError("The private testing frontend differs from the pinned revision; preserve and review it.")

    def normalize_init_script(self) -> None:
        # Windows patch/checkout tools can produce CRLF even with .gitattributes.
        # Linux executes this mounted file directly and rejects a /bin/sh\r shebang.
        path = self.deploy / "postgres-init" / "10-core-app.sh"
        data = path.read_bytes()
        normalized = data.replace(b"\r\n", b"\n")
        if normalized != data:
            path.write_bytes(normalized)

    def prepare_configuration(self) -> None:
        self.fresh = False
        env = self.state / ".env"
        key = self.state / "secrets" / "jwt-private.pem"
        if env.exists() != key.exists():
            raise RuntimeError("Incomplete testing credentials. Preserve them and review; nothing was rotated.")
        if not env.exists():
            volumes = self.run([
                "docker", "volume", "ls", "--filter",
                f"label=com.docker.compose.project={self.project}", "--format", "{{.Name}}",
            ], capture=True)
            if volumes.strip():
                raise RuntimeError("Testing volumes already exist without their credentials. Preserve and review them.")
            self.fresh = True
            # cryptography runs in the application image, not in the host Python.
            identity = f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "0:0"
            self.run([
                "docker", "run", "--rm", "--user", identity, "--entrypoint", "python",
                "--mount", f"type=bind,source={self.state},target=/config",
                "--mount", f"type=bind,source={self.deploy / 'prepare_local.py'},target=/prepare.py,readonly",
                BACKEND_IMAGE, "/prepare.py", "--output-dir", "/config",
            ])
            # This is a newly generated private file. Existing config is never edited.
            lines = env.read_text(encoding="utf-8").splitlines()
            lines = [line for line in lines if not line.startswith("CORS_ORIGINS=")]
            lines.extend([
                f"CORS_ORIGINS=http://localhost:{self.port}",
                f"CORE_HTTP_PORT={self.port}",
                f"CORE_BACKEND_IMAGE={BACKEND_IMAGE}",
                f"CORE_FRONTEND_IMAGE={FRONTEND_IMAGE}",
                f'CORE_FRONTEND_PATH="{self.frontend.as_posix()}"',
                f'JWT_PRIVATE_KEY_PATH="{key.as_posix()}"',
            ])
            env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        values = read_env(env)
        if not REQUIRED_KEYS.issubset(values) or any(not values[k] for k in REQUIRED_KEYS):
            raise RuntimeError("Testing config is missing required credentials; no existing values were changed.")
        expected = {
            "CORE_HTTP_PORT": str(self.port), "CORE_BACKEND_IMAGE": BACKEND_IMAGE,
            "CORE_FRONTEND_IMAGE": FRONTEND_IMAGE,
            "CORE_FRONTEND_PATH": self.frontend.as_posix(),
            "JWT_PRIVATE_KEY_PATH": key.as_posix(),
            "CORS_ORIGINS": f"http://localhost:{self.port}",
        }
        if any(values.get(name) != value for name, value in expected.items()):
            raise RuntimeError("Existing testing config does not match this isolated stack; review it without overwriting.")

    def wait_ready(self) -> None:
        required = {"api", "worker", "frontend", "postgres", "rabbitmq"}
        while True:
            self.remaining()
            try:
                with urllib.request.urlopen(f"http://localhost:{self.port}/health/ready", timeout=3) as response:
                    ready = json.load(response).get("status") == "up"
                running = set(self.compose("ps", "--status", "running", "--services", capture=True).split())
                if ready and required.issubset(running):
                    queues = self.compose(
                        "exec", "-T", "rabbitmq", "rabbitmqctl", "-q", "list_queues",
                        "-p", "core", "name", "consumers", capture=True,
                    )
                    counts = {}
                    for line in queues.splitlines():
                        cells = line.split()
                        if len(cells) == 2 and cells[1].isdigit():
                            counts[cells[0]] = int(cells[1])
                    if counts.get("core.inbox", 0) > 0 and counts.get("q.dlq", 0) > 0:
                        return
            except (OSError, ValueError, subprocess.CalledProcessError):
                pass
            time.sleep(min(2, self.remaining()))

    def start(self) -> None:
        if not shutil.which("docker") or not shutil.which("git"):
            raise RuntimeError("Install Docker with Compose and Git, then rerun this command.")
        self.verify_local_engine()
        self.run(["docker", "info"], capture=True)
        self.run(["docker", "compose", "version"], capture=True)
        self.state.mkdir(mode=0o700, exist_ok=True)
        lock = self.state / "bootstrap.lock"
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        try:
            self.normalize_init_script()
            self.checkout_frontend()
            self.run(["docker", "build", "-t", BACKEND_IMAGE, str(self.repo / "backend")])
            self.prepare_configuration()
            self.compose("config", "--quiet")
            self.compose("up", "-d", "--build")
            self.wait_ready()
            seconds = round(time.monotonic() - self.started, 2)
            backend_ref = self.run(["git", "rev-parse", "HEAD"], capture=True).strip()
            backend_dirty = bool(self.run(["git", "status", "--porcelain"], capture=True).strip())
            result = {"seconds": seconds, "backend_ref": backend_ref, "frontend_ref": FRONTEND_REF,
                      "backend_dirty": backend_dirty,
                      "project": self.project, "http_port": self.port,
                      "ready": True, "worker_consumers": True,
                      "fresh_credentials_and_no_previous_volumes": self.fresh,
                      "completed_at": datetime.now(UTC).isoformat()}
            (self.state / "bootstrap-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(f"Testing stack ready: http://localhost:{self.port} ({seconds}s).")
            print("Initial login: core@muni.uade.edu.ar; password is SEED_INITIAL_PASSWORD in deploy/.testing/.env.")
            print("Keep that file private. No production configuration or data was modified.")
        finally:
            lock.unlink(missing_ok=True)


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value.strip('"')
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-name", default=PROJECT)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    try:
        Bootstrap(Path(__file__).resolve().parent, project=args.project_name, port=args.port).start()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Testing startup failed: {exc}") from exc
