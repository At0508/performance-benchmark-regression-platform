"""Run JSON benchmark suites, preserve logs, and compare medians to a baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_LIMIT = 64 * 1024
ALLOWED_TOKENS = {"{python}", "{repo}", "{seed}"}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON file {path}: {exc}") from exc


def _validate_suite(suite: Any) -> None:
    if not isinstance(suite, dict) or suite.get("schema_version") != 1:
        raise ValueError("suite must be an object with schema_version=1")
    cases = suite.get("benchmarks")
    if not isinstance(cases, list) or not cases:
        raise ValueError("suite must define a non-empty benchmarks array")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each benchmark entry must be an object")
        case_id, command = case.get("id"), case.get("command")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError("benchmark ids must be non-empty and unique")
        seen.add(case_id)
        if (not isinstance(command, list) or not command or
                not all(isinstance(arg, str) and arg for arg in command)):
            raise ValueError(f"{case_id}: command must be a non-empty string array")
        placeholders = {"{" + name + "}" for arg in command
                        for name in re.findall(r"\{([^{}]+)\}", arg)}
        if placeholders - ALLOWED_TOKENS:
            raise ValueError(f"{case_id}: command contains an unsupported placeholder")
        for field in ("warmups", "repetitions"):
            value = case.get(field, 0 if field == "warmups" else 1)
            if not isinstance(value, int) or value < (0 if field == "warmups" else 1):
                raise ValueError(f"{case_id}: {field} has an invalid value")
        timeout = case.get("timeout_seconds", 120)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"{case_id}: timeout_seconds must be positive")
        expected = case.get("expected_exit_code", 0)
        if not isinstance(expected, int):
            raise ValueError(f"{case_id}: expected_exit_code must be an integer")


def _expand_command(command: list[str], repo: Path, seed: int) -> list[str]:
    replacements = {"{python}": sys.executable, "{repo}": str(repo), "{seed}": str(seed)}
    expanded = []
    for argument in command:
        for token, value in replacements.items():
            argument = argument.replace(token, value)
        expanded.append(argument)
    return expanded


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _invoke(command: list[str], cwd: Path, timeout: float, log_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr, code = _text(exc.stdout), _text(exc.stderr), None
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    log_path.parent.mkdir(parents=True, exist_ok=True)
    truncated = len(stdout) > LOG_LIMIT or len(stderr) > LOG_LIMIT
    log_path.write_text(
        "STDOUT\n" + stdout[:LOG_LIMIT] + "\nSTDERR\n" + stderr[:LOG_LIMIT],
        encoding="utf-8",
    )
    return {"elapsed_ms": elapsed_ms, "return_code": code,
            "timed_out": timed_out, "log_file": str(log_path),
            "log_truncated": truncated}


def _compare(median_ms: float | None, baseline: dict | None,
             threshold: float) -> tuple[str, float | None]:
    if baseline is None or median_ms is None:
        return "new" if baseline is None else "not_measured", None
    baseline_ms = baseline.get("median_ms")
    if not isinstance(baseline_ms, (int, float)) or baseline_ms <= 0:
        return "baseline_invalid", None
    change = (median_ms - baseline_ms) / baseline_ms
    if change > threshold:
        return "regression", change
    if change < -threshold:
        return "improvement", change
    return "within_threshold", change


def run_suite(suite_path: Path, output_dir: Path, baseline_path: Path | None = None,
              threshold: float = 0.10) -> dict[str, Any]:
    raw_config = suite_path.read_bytes()
    suite = json.loads(raw_config.decode("utf-8"))
    _validate_suite(suite)
    if threshold < 0 or threshold >= 1:
        raise ValueError("threshold must be in [0, 1)")
    baseline_cases: dict[str, dict] = {}
    if baseline_path is not None:
        baseline = _load_json(baseline_path)
        baseline_cases = {case["id"]: case for case in baseline.get("cases", [])
                          if isinstance(case, dict) and isinstance(case.get("id"), str)}

    suite_root = suite_path.resolve().parent
    repo_root = suite_root.parent if suite_root.name == "examples" else suite_root
    output_dir.mkdir(parents=True, exist_ok=True)
    seed = int(suite.get("seed", 2026))
    rows = []
    for case in suite["benchmarks"]:
        case_id = case["id"]
        command = _expand_command(case["command"], repo_root, seed)
        expected_code = case.get("expected_exit_code", 0)
        timeout = case.get("timeout_seconds", 120)
        warmups = case.get("warmups", 0)
        repetitions = case.get("repetitions", 1)
        samples = []
        failures = []
        runs = []
        run_index = 0

        for label, count in (("warmup", warmups), ("sample", repetitions)):
            for index in range(count):
                run_index += 1
                log_path = output_dir / "logs" / f"{case_id}-{label}-{index + 1:02d}.log"
                result = _invoke(command, repo_root, timeout, log_path)
                succeeded = (not result["timed_out"] and
                             result["return_code"] == expected_code)
                result["run_kind"] = label
                result["run_index"] = run_index
                result["passed"] = succeeded
                runs.append(result)
                if not succeeded:
                    failures.append({"run_kind": label, "run_index": run_index,
                                     "return_code": result["return_code"],
                                     "timed_out": result["timed_out"],
                                     "log_file": result["log_file"]})
                if label == "sample" and succeeded:
                    samples.append(result["elapsed_ms"])
                if not succeeded:
                    break
            if failures:
                break

        median_ms = statistics.median(samples) if samples else None
        mad_ms = (statistics.median(abs(value - median_ms) for value in samples)
                  if median_ms is not None else None)
        comparison, delta = _compare(median_ms, baseline_cases.get(case_id), threshold)
        status = "failed" if failures else comparison
        rows.append({
            "id": case_id, "description": case.get("description", ""),
            "command": command, "expected_exit_code": expected_code,
            "warmups": warmups, "requested_repetitions": repetitions,
            "samples_ms": samples, "median_ms": median_ms, "mad_ms": mad_ms,
            "baseline_status": comparison, "relative_change": delta,
            "status": status, "failures": failures, "runs": runs,
        })

    report = {
        "schema_version": 1,
        "suite": suite.get("name", suite_path.stem),
        "suite_sha256": hashlib.sha256(raw_config).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "os": platform.platform(),
                        "architecture": platform.machine(), "processor": platform.processor()},
        "comparison_threshold": threshold,
        "cases": rows,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    _write_csv(rows, output_dir / "summary.csv")
    _write_markdown(report, output_dir / "summary.md")
    return report


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "id", "status", "median_ms", "mad_ms", "baseline_status",
            "relative_change", "samples_ms",
        ])
        writer.writeheader()
        for row in rows:
            output = {key: row.get(key) for key in writer.fieldnames}
            output["samples_ms"] = json.dumps(row["samples_ms"])
            writer.writerow(output)


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [f"# Benchmark report: {report['suite']}", "",
             f"Created (UTC): {report['created_at_utc']}",
             f"Host: {report['environment']['os']} / {report['environment']['architecture']}",
             f"Comparison threshold: {report['comparison_threshold']:.1%}", "",
             "| Benchmark | Status | Median (ms) | MAD (ms) | Change vs baseline |",
             "|---|---:|---:|---:|---:|"]
    for row in report["cases"]:
        median = "—" if row["median_ms"] is None else f"{row['median_ms']:.3f}"
        mad = "—" if row["mad_ms"] is None else f"{row['mad_ms']:.3f}"
        delta = "—" if row["relative_change"] is None else f"{row['relative_change']:+.1%}"
        lines.append(f"| {row['id']} | {row['status']} | {median} | {mad} | {delta} |")
    lines.extend(["", "Median absolute deviation (MAD) summarizes run-to-run spread. "
                  "Benchmark wall time includes process startup; compare on the same host and software stack.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run = subparsers.add_parser("run", help="run a JSON suite")
    run.add_argument("suite", type=Path)
    run.add_argument("--output-dir", type=Path, default=Path("results/latest"))
    run.add_argument("--baseline", type=Path)
    run.add_argument("--threshold", type=float, default=0.10)
    args = parser.parse_args()
    try:
        report = run_suite(args.suite, args.output_dir, args.baseline, args.threshold)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Wrote {args.output_dir / 'report.json'}")
    for case in report["cases"]:
        median = "n/a" if case["median_ms"] is None else f"{case['median_ms']:.3f} ms"
        print(f"{case['id']}: {case['status']} ({median})")
    if any(case["status"] in {"failed", "regression"} for case in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
