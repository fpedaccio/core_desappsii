"""Report separate line/branch metrics and enforce business-service thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

COUNT_KEYS = ("covered_lines", "num_statements", "covered_branches", "num_branches")
GROUPS = {
    "services": "app/services/", "models": "app/models/",
    "repositories": "app/repositories/", "api": "app/api/", "core": "app/core/",
}


def canonical(name: str) -> str:
    name = name.replace("\\", "/")
    return "app/" + name.rsplit("/app/", 1)[1] if "/app/" in name else name.removeprefix("./")


def summarize(items: list[dict]) -> dict:
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for item in items:
        for key in COUNT_KEYS:
            value = item.get(key)
            if type(value) is not int or value < 0:
                raise ValueError(f"Invalid or missing coverage count: {key}")
            counts[key] += value
        if item["covered_lines"] > item["num_statements"] or item["covered_branches"] > item["num_branches"]:
            raise ValueError("Covered count exceeds measured count")
    counts["lines_percent"] = 100 * counts["covered_lines"] / counts["num_statements"] if counts["num_statements"] else None
    counts["branches_percent"] = 100 * counts["covered_branches"] / counts["num_branches"] if counts["num_branches"] else None
    return counts


def evaluate(report: dict, source_root: Path) -> dict:
    if report.get("meta", {}).get("branch_coverage") is not True:
        raise ValueError("Branch coverage was not enabled; rerun with --cov-branch")
    files = {canonical(name): data["summary"] for name, data in report["files"].items()}
    for group in ("services", "models"):
        directory = source_root / group
        expected = {f"app/{group}/{p.relative_to(directory).as_posix()}" for p in directory.rglob("*.py")}
        if not expected:
            raise ValueError(f"Business source directory is empty or absent: {directory}")
        missing = expected - files.keys()
        if missing:
            raise ValueError("Source files missing from coverage: " + ", ".join(sorted(missing)))
    groups = {name: summarize([data for path, data in files.items() if path.startswith(prefix)])
              for name, prefix in GROUPS.items()}
    services = groups["services"]
    if services["lines_percent"] is None or services["branches_percent"] is None:
        raise ValueError("Business services have no measurable lines or branches")
    passed = services["lines_percent"] >= 80 and services["branches_percent"] >= 70
    return {"global": summarize(list(files.values())), "groups": groups,
            "gate": {"scope": "app/services/ (all source files)",
                     "minimum_lines": 80, "minimum_branches": 70, "passed": passed}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=Path("coverage-summary.json"))
    args = parser.parse_args()
    try:
        result = evaluate(json.loads(args.report.read_text()), Path(__file__).resolve().parents[1] / "backend/app")
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(f"Coverage is not verifiable: {exc}")
        return 2
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for name, item in {"global": result["global"], **result["groups"]}.items():
        lines = f"{item['lines_percent']:.2f}%" if item['lines_percent'] is not None else "N/A"
        branches = f"{item['branches_percent']:.2f}%" if item['branches_percent'] is not None else "N/A (no measured branches)"
        print(f"{name}: lines={lines}; branches={branches}")
    print("Business services gate:", "PASS" if result["gate"]["passed"] else "FAIL")
    return 0 if result["gate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
