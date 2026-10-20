"""Invoke the restricted Core SSM deployment document."""
import json
import os
import re
import subprocess
import time

def aws(*arguments):
    return subprocess.run(
        ["aws", *arguments, "--region", "us-east-1",
         "--output", "json", "--no-cli-pager"],
        capture_output=True, text=True, timeout=90,
    )

def main():
    component = os.environ["CORE_COMPONENT"]
    expected = {
        "backend": "fpedaccio/core_desappsii",
        "frontend": "EmilioJOM/DAPP2-frontend",
    }
    if os.environ.get("GITHUB_REPOSITORY") != expected.get(component):
        raise SystemExit("Repository/component mismatch.")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Deployment requires main.")

    revision = os.environ["GITHUB_SHA"]
    mode = os.environ.get("CORE_CD_MODE", "--check")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SystemExit("Invalid revision.")
    if mode not in ("--check", "--apply"):
        raise SystemExit("Invalid deployment mode.")

    instance = "i-03828d9eb01af6764"
    parameters = {
        "Component": [component],
        "Revision": [revision],
        "Mode": [mode],
    }
    result = aws(
        "ssm", "send-command",
        "--document-name", "Core-DeployApplication",
        "--document-version", "1",
        "--instance-ids", instance,
        "--parameters", json.dumps(parameters),
        "--timeout-seconds", "300",
        "--comment", f"Core {component} {revision}",
    )
    if result.returncode:
        raise SystemExit(result.stderr)

    command_id = json.loads(result.stdout)["Command"]["CommandId"]
    print(f"SSM command: {command_id}; mode: {mode}", flush=True)
    started = time.monotonic()
    previous_status = None

    while time.monotonic() - started < 3300:
        result = aws(
            "ssm", "get-command-invocation",
            "--command-id", command_id,
            "--instance-id", instance,
            "--plugin-name", "deployCore",
        )
        if result.returncode:
            if ("InvocationDoesNotExist" in result.stderr
                    and time.monotonic() - started < 120):
                time.sleep(5)
                continue
            raise SystemExit(result.stderr)

        invocation = json.loads(result.stdout)
        status = invocation["Status"]
        if status != previous_status:
            print(f"SSM status: {status}", flush=True)
            previous_status = status

        if status in ("Pending", "InProgress", "Delayed", "Cancelling"):
            time.sleep(10)
            continue

        print(invocation.get("StandardOutputContent", ""))
        print(invocation.get("StandardErrorContent", ""))
        if status != "Success" or invocation.get("ResponseCode") != 0:
            raise SystemExit("SSM deployment/check failed.")
        print("PASS: SSM completed successfully.")
        return

    raise SystemExit(
        f"Monitoring timed out. Command {command_id} may still be running. "
        "Inspect SSM before retrying."
    )

if __name__ == "__main__":
    main()
