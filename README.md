# Performance Benchmark and Regression Platform

A reproducible command-line runner for performance suites. It runs each command without a shell, records warmups and repeated samples, saves bounded stdout/stderr logs, captures host and suite metadata, and compares medians with a prior JSON report using a configurable threshold.

The included example is a deterministic pure-Python workload. The runner is designed to orchestrate CPU and GPU programs; it does not itself provide GPU isolation, telemetry, scheduling, or hardware-specific counters.

## Install and run

Python 3.10+ is required. The runner has no runtime package dependencies.

```bash
python -m venv .venv
# Activate the environment.
python -m pip install -e .
bench-regress run examples/suite.json --output-dir results/baseline
```

The runner writes `report.json`, `summary.csv`, `summary.md`, and one log per warmup/sample. These local outputs are ignored by Git by default.

To compare a later run with the prior baseline:

```bash
bench-regress run examples/suite.json \
  --output-dir results/compare \
  --baseline results/baseline/report.json \
  --threshold 0.10
```

Commands are JSON arrays and are executed directly, without shell expansion. The supported placeholders are `{python}`, `{repo}`, and `{seed}`. This avoids accidental shell interpretation and makes replay commands explicit. Each case can set `warmups`, `repetitions`, `timeout_seconds`, and `expected_exit_code`.

## Result interpretation

- The median is the central elapsed wall time for successful measured processes.
- Median absolute deviation (MAD) gives a robust measure of variation across samples.
- A baseline status of `regression` means the median increased beyond the chosen relative threshold; `improvement` means it decreased beyond that threshold.
- Process startup is included, so use a long-running benchmark command for kernels or inference. Keep baseline and candidate on the same host, software, power mode, input, and benchmark procedure.
- A passing exit code checks process completion only. Workload correctness belongs in the workload's own checks.

This first version captures the host's OS, architecture, processor string, and Python version. GPU model, driver, CUDA version, profiler output, and workload-specific throughput should be emitted by the benchmark itself and retained with the report; the runner does not guess them.

## Test

```bash
python -m unittest discover -s tests -v
```

## Scope

The runner is a local single-machine process orchestrator. It is not a durable job service and does not manage containers, multi-GPU scheduling, retries across machines, or Prometheus telemetry. Those features require infrastructure and supported hardware beyond this benchmark harness.

## License

MIT. See [LICENSE](LICENSE).
