"""Read-only HTTP smoke check after bootstrap; passwords/tokens are not printed."""

import argparse
import getpass
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--email", default="core@muni.uade.edu.ar")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    def request(path, payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(payload).encode() if payload is not None else None
        with urlopen(Request(base + path, data=data, headers=headers), timeout=15) as response:
            return json.load(response)

    try:
        state = request("/health/ready")
        if state.get("status") != "up":
            raise RuntimeError("API readiness is not up. Check database and broker locally.")
        password = getpass.getpass("Password (not shown): ")
        login = request("/api/v1/auth/login", {"email": args.email, "password": password})
        token = login["accessToken"]
        request("/api/v1/auth/me", token=token)
        request("/api/v1/dashboard", token=token)
        print("PASS: readiness, login, current account and dashboard HTTP.")
        print("Still required: browser UI, worker event flow, retries, restart and restore tests.")
    except (HTTPError, URLError, RuntimeError, KeyError, ValueError) as exc:
        # Do not echo response bodies, credentials or internal connection strings.
        raise SystemExit(f"FAIL: {type(exc).__name__}. Check private logs and configuration.") from None


if __name__ == "__main__":
    main()
