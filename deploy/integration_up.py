"""Run opt-in integration tests against private PostgreSQL and RabbitMQ containers."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from testing_up import Bootstrap, read_env

PROJECT = "muni-core-testing-integration"
PASSWORDS = ("IT_ADMIN_PASSWORD", "IT_DB_PASSWORD", "IT_RABBIT_PASSWORD")


class IntegrationRunner(Bootstrap):
    def __init__(self, deploy_dir: Path):
        super().__init__(deploy_dir, project=PROJECT)
        self.state = self.deploy / ".integration"

    def compose(self, *args: str, capture: bool = False) -> str:
        return self.run([
            "docker", "compose", "--project-name", PROJECT,
            "--env-file", str(self.state / ".env"),
            "-f", str(self.deploy / "compose.integration.yaml"), *args,
        ], capture=capture)

    def prepare(self) -> None:
        env = self.state / ".env"
        evidence = self.state / "evidence"
        evidence.mkdir(exist_ok=True)
        if not env.exists():
            previous = self.run(["docker", "volume", "ls", "--filter",
                                 f"label=com.docker.compose.project={PROJECT}",
                                 "--format", "{{.Name}}"], capture=True)
            if previous.strip():
                raise RuntimeError("Integration volumes exist without config; preserve and review them.")
            with env.open("x", encoding="utf-8") as handle:
                for name in PASSWORDS:
                    handle.write(f"{name}={secrets.token_urlsafe(32)}\n")
                handle.write(f'IT_EVIDENCE_PATH="{evidence.as_posix()}"\n')
            os.chmod(env, 0o600)
        values = read_env(env)
        if any(not values.get(name) for name in PASSWORDS) or values.get("IT_EVIDENCE_PATH") != evidence.as_posix():
            raise RuntimeError("Integration config incomplete or moved; nothing was overwritten.")
        # Linux containers write as uid 10001; this directory contains synthetic reports only.
        os.chmod(evidence, 0o777)

    def start(self) -> None:
        for name in (*PASSWORDS, "IT_EVIDENCE_PATH"):
            os.environ.pop(name, None)
        if not shutil.which("docker") or not shutil.which("git"):
            raise RuntimeError("Install Git and start local Docker with Compose first.")
        self.verify_local_engine()
        self.run(["docker", "info"], capture=True)
        self.state.mkdir(mode=0o700, exist_ok=True)
        lock = self.state / "integration.lock"
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        code = 1
        try:
            self.normalize_init_script()
            self.prepare()
            self.compose("config", "--quiet")
            (self.state / "evidence/integration.xml").unlink(missing_ok=True)
            try:
                self.compose("up", "--build", "--abort-on-container-exit", "--exit-code-from", "tests")
                code = 0
            except subprocess.CalledProcessError as exc:
                code = exc.returncode
            report = {"project": PROJECT, "test_exit_code": code,
                      "seconds": round(time.monotonic() - self.started, 2),
                      "backend_ref": self.run(["git", "rev-parse", "HEAD"], capture=True).strip(),
                      "backend_dirty": bool(self.run(["git", "status", "--porcelain"], capture=True).strip()),
                      "completed_at": datetime.now(UTC).isoformat()}
            (self.state / "evidence/run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            xml = self.state / "evidence/integration.xml"
            if code == 0 and not xml.exists():
                raise RuntimeError("No JUnit report was generated; success cannot be verified.")
            print(f"Integration test exit code: {code}. Reports: deploy/.integration/evidence/")
        finally:
            try:
                if (self.state / ".env").exists():
                    # Cleanup must still work if the test execution used its time budget.
                    subprocess.run([
                        "docker", "compose", "--project-name", PROJECT,
                        "--env-file", str(self.state / ".env"),
                        "-f", str(self.deploy / "compose.integration.yaml"), "down",
                    ], cwd=self.repo, check=True, timeout=45)
            finally:
                lock.unlink(missing_ok=True)
        if code:
            raise RuntimeError(f"Integration tests failed (exit {code}); inspect the test report.")


if __name__ == "__main__":
    try:
        IntegrationRunner(Path(__file__).resolve().parent).start()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Integration run failed: {exc}") from exc
