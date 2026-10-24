# Operational monitoring

Standalone, informational system metrics analyzer and alert pipeline. Python 3.11+; standard library only. It has no imports from Alpha Sentinel's authorization, signing, simulation, or lifecycle components and does not change their decisions.

Run from the repository root:

```bash
# One disk check: root of the current drive/filesystem
python -m tools.monitoring.integrated_alerts

# Explicit paths; repeat to monitor multiple filesystems
python -m tools.monitoring.integrated_alerts --disk-path / --disk-path /home

# Actual latency/memory measurements, one key=value row per line
python -m tools.monitoring.integrated_alerts --metrics-file metrics.log

# Read stdin until EOF
python -m tools.monitoring.integrated_alerts --metrics-file -

# Synthetic demonstration data is opt-in
python -m tools.monitoring.integrated_alerts --demo

# Dependency-free regression suite
python -m unittest discover -s tests -p test_monitoring.py -v
```

On Windows, use an accessible path such as `--disk-path C:/`. Paths containing spaces should be quoted. Disk collection uses `shutil.disk_usage`; it does not enumerate drives or invoke system commands.

Example input:

```text
time=10:00:01 status=200 lat_ms=25.4 mem_mb=180
 time=10:00:02 status=200 lat_ms=650 mem_mb=350.5
```

`lat_ms` becomes `latency_ms`; `mem_mb` becomes `memory_mb`. Other fields remain metadata. Event timestamps represent ingestion time, not parsed source time. Rows without either recognized key are ignored. Malformed recognized values are logged and counted; valid metrics on the same row still proceed.

The CLI configures disk usage above 80%, latency above 500 ms, and memory above 300 MB. These are example thresholds, not validated Alpha Sentinel service-level objectives. Memory/latency must come from the producing service; this tool does not inspect process memory or instrument simulations automatically. Python callers can configure other `AlertRule` thresholds and supported operators: `>`, `>=`, `<`, `<=`, `==`.

## Delivery and failure behavior

- ConsoleSink prints text; WebhookMockSink prints JSON and never sends a webhook.
- Exceptions from one sink are logged without blocking later sinks. A successful sink starts its own monotonic cooldown; a failed sink can retry when the next matching event arrives. There is no background retry.
- `ingest()` returns delivery/failure/suppression counts. Collectors return event/error/delivery counts. CLI exit status is 1 on collection, parsing, or delivery errors; invalid arguments exit 2.
- Numeric inputs must be finite; booleans and numeric strings are rejected by the event/rule API. The text parser converts numbers explicitly. Latency, memory, and cooldown must be nonnegative; disk capacity must be valid.
- A failed disk path does not prevent collecting later paths. Only selected paths are checked. Disk capacity is a percentage of total bytes, rather than a measure of unprivileged available space.

## Operational boundaries

This is a single-threaded, synchronous tool. It checks disk once, reads the selected input to EOF, and exits. It does not tail files, poll periodically, deploy a service, persist cooldowns, aggregate duplicate events, or send recovery alerts. Use an external scheduler if periodic checks are needed; separate CLI runs reset cooldowns. Sink implementations must bound their own blocking I/O. Delivery is not exactly-once: a sink that performs a side effect and then raises may duplicate that side effect on a later attempt.

Configure rules/sinks with `add_rule` and `add_sink` before ingestion; do not mutate their public lists during processing. Keep this monitoring process separate from the deterministic authorization path. A disk/latency alert is an observation, never an approval or signing instruction.

CI runs these tests on Ubuntu and Windows with Python 3.11. Actual Alpha Sentinel log adapters and real notification delivery remain future work.
