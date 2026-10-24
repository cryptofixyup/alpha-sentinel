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
python -m unittest discover -s tests -p "test_monitoring*.py" -v
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

- ConsoleSink prints text. Without `--webhook`, WebhookMockSink also prints JSON and sends nothing. With `--webhook`, the second sink makes a real generic JSON POST.
- Exceptions from one sink are logged without blocking later sinks. A successful sink starts its own monotonic cooldown; a failed sink can retry when the next matching event arrives. There is no background retry.
- `ingest()` returns delivery/failure/suppression counts. Collectors return event/error/delivery counts. CLI exit status is 1 on collection, parsing, or delivery errors; invalid arguments exit 2.
- Numeric inputs must be finite; booleans and numeric strings are rejected by the event/rule API. The text parser converts numbers explicitly. Latency, memory, and cooldown must be nonnegative; disk capacity must be valid.
- A failed disk path does not prevent collecting later paths. Only selected paths are checked. Disk capacity is a percentage of total bytes, rather than a measure of unprivileged available space.

## Operational boundaries

One-shot mode checks disk once, reads selected input to EOF, and exits. Live mode keeps the same pipeline and per-sink cooldowns in memory:

```bash
# Live disk checks; Ctrl+C stops monitoring
python -m tools.monitoring.integrated_alerts --watch --interval 10

# Follow appended metric lines; existing history is skipped at first open
python -m tools.monitoring.integrated_alerts --watch --metrics-file metrics.log --interval 10

# Bounded run for validation or scheduled work
python -m tools.monitoring.integrated_alerts --watch --cycles 2 --interval 1

# Real delivery, after MONITOR_WEBHOOK_URL is configured in your host environment
python -m tools.monitoring.integrated_alerts --watch --metrics-file metrics.log --webhook
```

Keep the endpoint URL in `MONITOR_WEBHOOK_URL` on the target host, not in Git, shell command arguments, screenshots, or chat. Nothing is transmitted unless `--webhook` is supplied. Missing/invalid configuration fails before collection. The receiver must accept the generic JSON payload below; Slack, Discord, and Telegram native payload adapters are not included.

```json
{"alert":"API High Latency","severity":"CRITICAL","category":"METRIC_STREAM","metric":"latency_ms","value":650.0,"timestamp":100.0,"details":"latency_ms (650.0) breached threshold > 500.0"}
```

Raw log metadata is excluded. Endpoint URLs, response bodies, and transport exception details are not logged. HTTPS uses default certificate/hostname verification. Redirects are rejected. `--webhook-timeout` defaults to 5 seconds and permits `(0, 60]` seconds. This is a socket-operation timeout, not a strict total deadline: DNS resolution or slowly trickled response headers can exceed it. Delivery is serial, so a slow receiver delays subsequent collection. There is one attempt per matching event; failed sends can retry only when a new matching event arrives. There is no durable retry queue, backoff, or guaranteed delivery. A receiver may accept a request before a timeout is observed; a later attempt can duplicate it.

`--allow-http-localhost` permits HTTP only for explicitly configured loopback test receivers. Production endpoints must use HTTPS. No external production receiver is contacted by the regression suite.

The watch loop waits `--interval` seconds after each completed poll; it does not promise fixed-rate sampling. `--cycles N` stops after N polls. Ctrl+C exits 130; a bounded run exits 1 if any collection, parsing, or delivery error occurred during the run, even if a later poll recovered. An unlimited watch process keeps running through those errors and reports them in each cycle's output. Watch mode refuses blocking stdin and synthetic demo input.

The file follower reopens a regular file each poll and reads at most 64 KiB. Complete UTF-8 lines up to 16 KiB are parsed; partial lines are retained across polls, malformed/oversized lines are counted, and oversized input is discarded until its next newline. A new file identity or observed truncation resets the cursor and reads the replacement from the beginning. A missing file is retried on later polls; if it first appears after an observed absence, it is read from the beginning. Transient access failures on an existing file preserve the initial history-skip behavior. Copy-truncate followed by regrowth beyond the previous offset between polls cannot be detected reliably. Polling can also miss data written and rotated away between polls. There is no durable cursor, log shipping guarantee, or catch-up after downtime. On restart, existing history is skipped again.

This change supplies runnable live monitoring and real transport. It does not install or activate a background service. Choose a target host, configure an HTTPS receiver, and supervise the process there to make alerts operational.

Configure rules/sinks with `add_rule` and `add_sink` before ingestion; do not mutate their public lists during processing. Keep this monitoring process separate from the deterministic authorization path. A disk/latency alert is an observation, never an approval or signing instruction.

CI runs these tests on Ubuntu and Windows with Python 3.11, including real loopback HTTP deliveries and bounded live polling. Actual Alpha Sentinel metric producers and a production receiver still require host-specific configuration.
