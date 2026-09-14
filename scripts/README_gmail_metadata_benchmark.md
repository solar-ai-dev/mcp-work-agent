# Gmail metadata hydration benchmark

This diagnostic evaluates the existing Gmail 20-thread list projection with fixed Provider READ
semantics. It never calls Gmail WRITE or SEND. Raw output belongs under `evaluation/results/**`.

Run from the repository root with no other product backend or Gmail experiment active:

```powershell
$result = "evaluation/results/gmail-metadata-hydration-20260914-7afac9f5"
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py provider-sweep --result-dir $result
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py local-confirm --result-dir $result
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py concurrent-confirm --result-dir $result
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py finalize-report --result-dir $result
```

Defaults are the frozen experiment contract: seed `20260913`, 5 warm-ups per Provider config,
100 measured blocks, 16.2-second page-job pacing, 5,000 paired block-bootstrap resamples, and
J=2 episode pacing of 32.4 seconds. The Local API lane restarts a dedicated production-composition
loopback server for each 10-trial subblock and applies its candidate once at MCP process startup.

To regenerate summaries without Provider calls:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py summarize-provider --result-dir $result
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py summarize-backend --result-dir $result
.\.venv\Scripts\python.exe scripts\benchmark_gmail_metadata_hydration.py summarize-concurrent --result-dir $result
```

The production retrieval-node confirmation starts at the real `execute_read_node`, uses a fresh
run/cache handle for every trial, and materializes the tool binding from the current signed
production registry. Its fixture is an absolute three-month-old window, June 1 through July 1,
2026 in `America/Los_Angeles`; only the expected count and identity hash are persisted.

```powershell
$nodeResult = "$result/node-session-003-fixed-june"
.\.venv\Scripts\python.exe -m scripts.benchmark_gmail_execute_read_node --result-dir $nodeResult --warmups 5 --blocks 100 --pacing-seconds 16.2
.\.venv\Scripts\python.exe -m scripts.benchmark_gmail_execute_read_node --result-dir $nodeResult --aggregate-only
```

The node harness stops at the first dataset drift or rate-limited HTTP attempt. Earlier exploratory
sessions that used a moving latest-20 result are retained as invalid diagnostic evidence and are
never combined with the fixed-window summary.

The harness stops rather than replacing a failed sample when authentication changes, three
rate-limit jobs occur, the fixed result contract changes, or instrumentation becomes invalid.
The bounded Gmail query is held in process memory and is intentionally absent from artifacts.
