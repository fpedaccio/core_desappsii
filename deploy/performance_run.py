
"""Run an isolated, authenticated three-endpoint local load test."""

import datetime
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from testing_up import Bootstrap, read_env

PROJECT = "muni-core-testing-performance"
IMAGE = "grafana/k6@sha256:2dd4756ec6e14e62778916e1eb850108e4b499304c02df56760fa0bdb0fba0b8"
BACKEND = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],
    cwd=Path(__file__).resolve().parent.parent,
    text=True,
).strip()
FRONTEND = "6353a6dfd3613d17ade5564b96b7e09dfec70573"
BASE = "http://127.0.0.1:18087/api/v1"


def main():
    deploy = Path(__file__).resolve().parent
    root = deploy.parent
    Bootstrap(deploy, project=PROJECT, port=18087).verify_local_engine()
    state = deploy / ".testing"
    startup = json.loads((state / "bootstrap-result.json").read_text())
    if (
        startup["project"] != PROJECT
        or startup["backend_ref"] != BACKEND
        or startup["frontend_ref"] != FRONTEND
        or not startup["ready"]
        or not startup["worker_consumers"]
    ):
        raise RuntimeError("Unexpected performance environment")

    app_diff = subprocess.check_output(
        ["git", "diff", BACKEND, "--", "backend", "deploy/compose.yaml"],
        cwd=root, text=True,
    )
    if app_diff:
        raise RuntimeError("Runtime application source differs from the tested base")

    # Refuse a run that does not use the accepted process configuration.
    api_runtime = json.loads(subprocess.check_output(
        ["docker", "inspect", PROJECT + "-api-1"], text=True,
    ))[0]
    expected_command = [
        "uvicorn", "app.main:app", "--host", "0.0.0.0",
        "--port", "8000", "--workers", "3",
    ]
    if api_runtime["Config"]["Cmd"] != expected_command:
        raise RuntimeError("Performance requires exactly three API workers")

    containers = {}
    for service in ("api", "worker", "postgres", "rabbitmq", "frontend"):
        item = json.loads(subprocess.check_output(
            ["docker", "inspect", f"{PROJECT}-{service}-1"], text=True,
        ))[0]
        if (
            item["Config"]["Labels"].get("com.docker.compose.project") != PROJECT
            or not item["State"]["Running"]
        ):
            raise RuntimeError("Unexpected container: " + service)
        containers[service] = {"id": item["Id"], "image": item["Image"]}

    suffix = uuid.uuid4().hex[:12]
    module = "qa-perf-" + suffix
    event_type = "qaPerf" + suffix
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + suffix
    evidence = state / "evidence" / ("performance-" + stamp)
    evidence.mkdir(parents=True)
    private = state / "performance-private"
    private.mkdir(mode=0o700, exist_ok=True)
    lock = private / "run.lock"
    with lock.open("x") as output:
        output.write(str(os.getpid()))

    config_path = private / ("config-" + suffix + ".json")
    name = PROJECT + "-k6-" + suffix
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    admin = None
    created = False
    subscription_id = None
    publication_id = None
    sensitive = []
    cleanup = {}
    report = {
        "project": PROJECT,
        "backend_ref": BACKEND,
        "frontend_ref": FRONTEND,
        "module": module,
        "event_type": event_type,
        "containers": containers,
        "k6_image": IMAGE,
        "configured_api_workers": 3,
        "configured_vus": 50,
        "configured_duration_seconds": 300,
        "shared_module_identity": True,
        "iteration": "publish, history, dashboard, then one-second pacing",
        "passed": False,
    }

    def request(method, path, payload=None, token=None, statuses=(200,)):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        raw = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            BASE + path, data=raw, headers=headers, method=method,
        )
        try:
            response = opener.open(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            status = response.status
            body = response.read()
        if status not in statuses:
            raise RuntimeError(f"{method} {path}: unexpected HTTP {status}")
        return json.loads(body) if body else None

    def run_k6(mode):
        destination = evidence / mode
        destination.mkdir()
        command = [
            "docker", "run", "--rm", "--pull=never",
            "--user", "0:0",
            "--name", name,
            "--label", "core.qa.project=" + PROJECT,
            "--network", PROJECT + "_default",
            "-e", "PERF_MODE=" + mode,
            "--mount", f"type=bind,source={config_path},target=/private/config.json,readonly",
            "--mount",
            (
                f"type=bind,source={deploy / 'performance/scenario.js'},"
                "target=/scenario.js,readonly"
            ),
            "--mount", f"type=bind,source={destination},target=/evidence",
            IMAGE, "run", "/scenario.js",
        ]
        started = time.monotonic()
        try:
            result = subprocess.run(
                command, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=420,
            )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elapsed = time.monotonic() - started
        text = result.stdout + "\n" + result.stderr
        for secret in sensitive:
            text = text.replace(secret, "[REDACTED]")
        (destination / "execution.log").write_text(text, encoding="utf-8")
        summary_path = destination / "summary.json"
        if not summary_path.exists():
            raise RuntimeError("No k6 summary generated: " + mode)
        summary = json.loads(summary_path.read_text())
        rows = []
        for endpoint in ("publish", "history", "dashboard"):
            metrics = summary["metrics"]
            errors = metrics[f"operation_errors{{endpoint:{endpoint}}}"]["values"]["rate"]
            count = metrics[f"operation_calls{{endpoint:{endpoint}}}"]["values"]["count"]
            # Latency submetrics are generated by thresholds in the full run.
            p95 = None
            if mode == "full":
                p95 = metrics[
                    f"operation_latency{{endpoint:{endpoint}}}"
                ]["values"]["p(95)"]
            rows.append({
                "endpoint": endpoint,
                "requests": count,
                "error_rate": errors,
                "p95_ms": p95,
                "passed": (
                    count >= (50 if mode == "full" else 1)
                    and errors < (0.01 if mode == "full" else 0.0000001)
                    and (mode != "full" or p95 < 500)
                ),
            })
        outcome = {
            "exit_code": result.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "endpoints": rows,
            "passed": (
                result.returncode == 0
                and all(row["passed"] for row in rows)
                and (mode != "full" or elapsed >= 300)
            ),
        }
        (destination / "result.json").write_text(
            json.dumps(outcome, indent=2), encoding="utf-8",
        )
        print(mode + ":", json.dumps(outcome), flush=True)
        return outcome

    try:
        hardware = subprocess.check_output(
            ["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}}"],
            text=True,
        ).split()
        report["docker_resources"] = {
            "cpus": int(hardware[0]), "memory_bytes": int(hardware[1]),
        }
        running = subprocess.check_output(
            ["docker", "ps", "-q"], text=True,
        ).splitlines()
        report["running_container_count_before"] = len(running)

        values = read_env(state / ".env")
        password = values["SEED_INITIAL_PASSWORD"]
        sensitive.append(password)
        login = request("POST", "/auth/login", {
            "email": "core@muni.uade.edu.ar", "password": password,
        })
        admin = login["accessToken"]
        sensitive.append(admin)

        account = request("POST", "/modules", {
            "name": module, "displayName": "Synthetic performance fixture",
            "team": "Local performance",
        }, admin, (201,))
        created = True
        secret = account["secret"]
        sensitive.append(secret)
        token_result = request("POST", "/auth/module-token", {
            "module": module, "secret": secret,
        })
        if token_result["isAdmin"] is not False or token_result["expiresIn"] < 600:
            raise RuntimeError("Unexpected fixture token permissions or lifetime")
        token = token_result["accessToken"]
        sensitive.append(token)
        request("POST", "/event-types", {
            "name": event_type, "ownerModule": module,
            "jsonSchema": {
                "type": "object",
                "required": ["marker"],
                "properties": {"marker": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
        }, token, (201,))
        publication = request("POST", "/publications", {
            "eventType": event_type,
        }, token, (201,))
        publication_id = publication["id"]
        subscription = request("POST", "/subscriptions", {
            "eventType": event_type, "maxAttempts": 4,
        }, token, (201,))
        subscription_id = subscription["id"]
        if subscription["queueName"] != "q." + module:
            raise RuntimeError("Unexpected fixture queue")

        with config_path.open("x", encoding="utf-8") as output:
            os.chmod(config_path, 0o600)
            json.dump({
                "base": "http://frontend/api/v1",
                "module": module, "event_type": event_type,
                "token": token, "run": suffix,
            }, output)

        print("Fixture isolated and ready. Evidence:", evidence, flush=True)
        smoke = run_k6("smoke")
        report["smoke"] = smoke
        if not smoke["passed"]:
            raise RuntimeError("Smoke test failed; full load was not started")

        print("Starting 50 virtual users for five minutes...", flush=True)
        full = run_k6("full")
        report["full"] = full
        report["event_count_after"] = request(
            "GET", "/events?eventType=" + event_type + "&size=1", token=token,
        )["total"]
        report["passed"] = full["passed"]
    except Exception as error:
        message = str(error)
        for secret in sensitive:
            message = message.replace(secret, "[REDACTED]")
        report["execution_error"] = message
        report["passed"] = False
    finally:
        if created:
            try:
                if subscription_id:
                    request(
                        "POST",
                        "/subscriptions/" + subscription_id + "/toggle?active=false",
                        token=admin,
                    )
                    cleanup["subscription_deactivated"] = True
                if publication_id:
                    request(
                        "DELETE", "/publications/" + publication_id,
                        token=admin, statuses=(204,),
                    )
                    cleanup["publication_removed"] = True
                request("PATCH", "/modules/" + module, {"active": False}, admin)
                cleanup["module_deactivated"] = True
            except Exception:
                cleanup["error"] = True
                report["passed"] = False
        config_path.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
        report["cleanup"] = cleanup
        report["temporary_config_removed"] = not config_path.exists()
        report["limitations"] = [
            "Local Docker host; other running containers can affect results",
            "Fifty virtual users share one non-admin module token",
            "Closed workload with one-second pacing after each three-request iteration",
            "HTTP timing includes local frontend proxy, API and database work",
            "Does not prove external business consumption or production capacity",
            "Events and queued synthetic messages are preserved",
            "Smoke activity precedes the measured five-minute run",
        ]
        (evidence / "results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8",
        )
        print("Cleanup:", json.dumps(cleanup), flush=True)
        print("Result:", "PASS" if report["passed"] else "REVIEW", flush=True)
        print("Evidence:", evidence, flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
