"""System metrics analyzer with optional live polling and webhook delivery (Python 3.11+)."""
from __future__ import annotations

import argparse
import json
import logging
import math
import operator
import os
import re
import shutil
import sys
import time
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .tail import MetricFileFollower
from .webhook import WebhookSink

LOG = logging.getLogger(__name__)
OPERATORS = {'>': operator.gt, '>=': operator.ge, '<': operator.lt,
             '<=': operator.le, '==': operator.eq}


def finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be a finite number') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number')
    return result


@dataclass(frozen=True)
class MetricEvent:
    timestamp: float
    category: str
    metric_name: str
    value: float
    raw_payload: dict[str, Any]

    def __post_init__(self):
        object.__setattr__(self, 'timestamp', finite_number(self.timestamp, 'timestamp'))
        object.__setattr__(self, 'value', finite_number(self.value, 'value'))


@dataclass(frozen=True)
class Alert:
    rule_name: str
    severity: str
    event: MetricEvent
    details: str
    evidence: dict[str, Any] | None = None


class AlertSink:
    def emit(self, alert: Alert) -> None:
        raise NotImplementedError


class ConsoleSink(AlertSink):
    def emit(self, alert: Alert) -> None:
        print(f'[{alert.severity}] {alert.rule_name}: {alert.details}')


class WebhookMockSink(AlertSink):
    """Print JSON only; does not send network requests."""
    def emit(self, alert: Alert) -> None:
        print(json.dumps({'alert': alert.rule_name, 'severity': alert.severity,
                          'metric': alert.event.metric_name, 'value': alert.event.value,
                          'details': alert.details,
                          **({'evidence': alert.evidence} if alert.evidence is not None else {})}, allow_nan=False))


@dataclass(frozen=True)
class AlertRule:
    name: str
    category: str
    metric_name: str
    threshold: float
    condition: str = '>'
    severity: str = 'HIGH'
    cooldown_sec: float = 5

    def __post_init__(self):
        if not isinstance(self.condition, str) or self.condition not in OPERATORS:
            raise ValueError('condition must be one of >, >=, <, <=, ==')
        object.__setattr__(self, 'threshold', finite_number(self.threshold, 'threshold'))
        cooldown = finite_number(self.cooldown_sec, 'cooldown_sec')
        if cooldown < 0:
            raise ValueError('cooldown_sec must be nonnegative')
        object.__setattr__(self, 'cooldown_sec', cooldown)

    def evaluate(self, event: MetricEvent) -> Alert | None:
        """Pure matching; the pipeline owns per-sink delivery cooldowns."""
        if event.category != self.category or event.metric_name != self.metric_name:
            return None
        if not OPERATORS[self.condition](event.value, self.threshold):
            return None
        return Alert(self.name, self.severity, event,
                     f'{event.metric_name} ({event.value}) breached threshold '
                     f'{self.condition} {self.threshold}')


@dataclass
class DeliveryReport:
    delivered: int = 0
    failed: int = 0
    suppressed: int = 0


class IntegratedAlertPipeline:
    """Single-threaded. Successful deliveries alone consume sink cooldowns."""
    def __init__(self, *, clock: Callable[[], float] = time.monotonic, observation_capacity: int = 1024):
        if isinstance(observation_capacity, bool) or not isinstance(observation_capacity, int) or observation_capacity <= 0:
            raise ValueError('observation_capacity must be a positive integer')
        self._observation_capacity = observation_capacity
        self._observation_delivered = OrderedDict()
        self.rules: list[AlertRule] = []
        self.sinks: list[AlertSink] = []
        self._clock = clock
        self._last_delivered: dict[tuple[int, int], float] = {}

    def add_rule(self, rule: AlertRule) -> IntegratedAlertPipeline:
        self.rules.append(rule)
        return self

    def add_sink(self, sink: AlertSink) -> IntegratedAlertPipeline:
        self.sinks.append(sink)
        return self

    def observation_state_size(self) -> int:
        """Operational diagnostic: retained security delivery cooldown entries."""
        return len(self._observation_delivered)

    def dispatch_observation(self, alert: Alert, key, cooldown_sec: float = 30) -> DeliveryReport:
        cooldown = finite_number(cooldown_sec, 'observation cooldown')
        if cooldown < 0:
            raise ValueError('observation cooldown must be nonnegative')
        now = self._clock()
        for entry in list(self._observation_delivered):
            if self._observation_delivered[entry] <= now:
                del self._observation_delivered[entry]
        report = DeliveryReport()
        for sink in self.sinks:
            entry = (key, id(sink))
            if self._observation_delivered.get(entry, -1) > self._clock():
                report.suppressed += 1
                continue
            try:
                sink.emit(alert)
            except Exception:
                report.failed += 1
                LOG.exception('Security observation delivery failed: sink=%s', type(sink).__name__)
            else:
                report.delivered += 1
                if cooldown > 0:
                    self._observation_delivered[entry] = self._clock() + cooldown
                    self._observation_delivered.move_to_end(entry)
                    while len(self._observation_delivered) > self._observation_capacity:
                        self._observation_delivered.popitem(last=False)
        return report

    def ingest(self, event: MetricEvent) -> DeliveryReport:
        report = DeliveryReport()
        for rule in self.rules:
            alert = rule.evaluate(event)
            if alert is None:
                continue
            for sink in self.sinks:
                key = (id(rule), id(sink))
                now = self._clock()
                last = self._last_delivered.get(key)
                if last is not None and now - last < rule.cooldown_sec:
                    report.suppressed += 1
                    continue
                try:
                    sink.emit(alert)
                except Exception:
                    report.failed += 1
                    LOG.exception('Alert delivery failed: rule=%s sink=%s',
                                  rule.name, type(sink).__name__)
                else:
                    self._last_delivered[key] = self._clock()
                    report.delivered += 1
        return report


@dataclass
class AnalysisReport:
    events: int = 0
    errors: int = 0
    delivered: int = 0
    delivery_failures: int = 0

    def ingest(self, pipeline: IntegratedAlertPipeline, event: MetricEvent) -> None:
        delivery = pipeline.ingest(event)
        self.events += 1
        self.delivered += delivery.delivered
        self.delivery_failures += delivery.failed


class SystemAnalyzerEngine:
    def __init__(self, pipeline: IntegratedAlertPipeline, *, security_engine=None):
        self.pipeline = pipeline
        self.security_engine = security_engine

    def analyze_disk_usage(self, paths: Iterable[str | Path] | None = None) -> AnalysisReport:
        """Collect each requested path; default to the current drive/filesystem root."""
        report = AnalysisReport()
        if paths is None:
            paths = [Path.cwd().anchor]
        for path in paths:
            try:
                label = str(Path(path).absolute())
                usage = shutil.disk_usage(path)
                total = finite_number(usage.total, 'disk total')
                used = finite_number(usage.used, 'disk used')
                if total <= 0 or not 0 <= used <= total:
                    raise ValueError('invalid disk capacity values')
                event = MetricEvent(time.time(), 'DISK', f'disk_used_percent_{label}',
                                    used / total * 100,
                                    {'path': label, 'total_bytes': usage.total,
                                     'used_bytes': usage.used, 'free_bytes': usage.free})
            except (OSError, ValueError) as exc:
                report.errors += 1
                LOG.warning('Disk collection failed for %r: %s', str(path), exc)
                continue
            report.ingest(self.pipeline, event)
        return report

    def _parse_security_stream(self, log_lines: Iterable[str]) -> AnalysisReport:
        report = AnalysisReport()
        try:
            for line in log_lines:
                result = self.security_engine.ingest_raw_log(line)
                if result.error is not None:
                    report.errors += 1
                    LOG.warning('Security log rejected: %s', result.error)
                    continue
                if result.event is None:
                    continue
                report.events += 1
                for observation in result.observations:
                    evidence = {
                        'classification': 'suspected', 'source_ip': observation.source_ip,
                        'evidence_count': observation.evidence_count,
                        'content_hashes': observation.evidence_ids,
                        'evidence_truncated': observation.evidence_truncated,
                        'known_target_count': len(observation.targets),
                        'resource': observation.resource,
                        'window_basis': 'monotonic_receipt_time',
                        'window_seconds': self.security_engine.window_seconds,
                    }
                    value = float(observation.evidence_count)
                    metric_name = 'auth_failure_count'
                    if observation.anomaly is not None:
                        evidence['anomaly'] = asdict(observation.anomaly)
                    if observation.metric_name is not None:
                        metric_name = observation.metric_name + '_outlier'
                        value = observation.anomaly.value
                        evidence['metric_unit'] = observation.metric_unit
                    alert = Alert(observation.alert_type, observation.severity,
                                  MetricEvent(result.event.received_at,'SECURITY',metric_name,value,{}),
                                  observation.summary,evidence=evidence)
                    key = (observation.alert_type, observation.source_ip,
                           observation.resource, observation.metric_name)
                    delivery = self.pipeline.dispatch_observation(alert,key,30)
                    report.delivered += delivery.delivered
                    report.delivery_failures += delivery.failed
        except (OSError, UnicodeError):
            report.errors += 1
            LOG.warning('Security log input failed')
        return report

    def parse_and_analyze_stream(self, log_lines: Iterable[str]) -> AnalysisReport:
        if self.security_engine is not None:
            return self._parse_security_stream(log_lines)
        report = AnalysisReport()
        try:
            for line_number, line in enumerate(log_lines, 1):
                matches = dict(re.findall(r'(\w+)=(\S*)', line))
                for source, name in [('lat_ms', 'latency_ms'), ('mem_mb', 'memory_mb')]:
                    if source not in matches:
                        continue
                    try:
                        value = finite_number(float(matches[source]), source)
                        if value < 0:
                            raise ValueError(f'{source} must be nonnegative')
                        event = MetricEvent(time.time(), 'METRIC_STREAM', name, value, dict(matches))
                    except (ValueError, OverflowError) as exc:
                        report.errors += 1
                        LOG.warning('Invalid metric on line %d (%s): %s', line_number, source, exc)
                        continue
                    report.ingest(self.pipeline, event)
        except (OSError, UnicodeError) as exc:
            report.errors += 1
            LOG.warning('Metric input failed: %s', exc)
        return report


def run_watch(engine: SystemAnalyzerEngine, paths: Iterable[str | Path], *,
              metrics_path: str | Path | None = None, interval_sec: float = 10,
              cycles: int | None = None, stop_event=None) -> AnalysisReport:
    """Serial polls with process-local cooldowns; wait interval after each poll."""
    interval = finite_number(interval_sec, 'interval')
    if interval <= 0:
        raise ValueError('interval must be positive')
    if cycles is not None and (isinstance(cycles, bool) or not isinstance(cycles, int) or cycles <= 0):
        raise ValueError('cycles must be a positive integer')
    stop = stop_event if stop_event is not None else threading.Event()
    paths = list(paths)
    follower = MetricFileFollower(metrics_path) if metrics_path is not None else None
    total = AnalysisReport()
    cycle = 0
    while not stop.is_set():
        disk = engine.analyze_disk_usage(paths)
        reports = [disk]
        if follower is not None:
            batch = follower.poll()
            stream = engine.parse_and_analyze_stream(batch.lines)
            stream.errors += batch.errors
            reports.append(stream)
        for report in reports:
            total.events += report.events
            total.errors += report.errors
            total.delivered += report.delivered
            total.delivery_failures += report.delivery_failures
        cycle += 1
        print(f'Cycle {cycle}: collected {sum(r.events for r in reports)} events; '
              f'{sum(r.errors for r in reports)} collection/parse errors; '
              f'{sum(r.delivery_failures for r in reports)} delivery failures', flush=True)
        if cycles is not None and cycle >= cycles:
            break
        stop.wait(interval)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk-path', action='append', help='Path to monitor; repeat for multiple paths')
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--metrics-file', help='Read metric lines from a UTF-8 file, or - for stdin')
    inputs.add_argument('--demo', action='store_true', help='Process synthetic sample metrics explicitly')
    parser.add_argument('--security', action='store_true', help='Normalize security logs and emit suspected-pattern observations')
    parser.add_argument('--watch', action='store_true', help='Poll disk and follow new metric-file rows')
    parser.add_argument('--interval', type=float, default=10, help='Seconds to wait after each watch poll')
    parser.add_argument('--cycles', type=int, help='Stop watch mode after this many polls')
    parser.add_argument('--webhook', action='store_true', help='Send generic JSON alerts to MONITOR_WEBHOOK_URL')
    parser.add_argument('--webhook-timeout', type=float, default=5, help='Webhook socket timeout, seconds (0, 60]')
    parser.add_argument('--allow-http-localhost', action='store_true', help='Allow HTTP loopback receiver for local testing')
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error('--interval must be finite and positive')
    if args.cycles is not None and (not args.watch or args.cycles <= 0):
        parser.error('--cycles requires --watch and a positive integer')
    if args.security and args.demo:
        parser.error('--security requires actual log input, not synthetic metric demo data')
    if args.watch and (args.demo or args.metrics_file == '-'):
        parser.error('--watch accepts a regular metric file, not stdin or demo data')
    webhook = None
    if args.webhook:
        url = os.environ.get('MONITOR_WEBHOOK_URL')
        if not url:
            parser.error('--webhook requires MONITOR_WEBHOOK_URL in the environment')
        try:
            webhook = WebhookSink(url, timeout_sec=args.webhook_timeout,
                                  allow_http_localhost=args.allow_http_localhost)
        except ValueError as exc:
            parser.error(str(exc))
    logging.basicConfig(level=logging.WARNING)
    paths = args.disk_path if args.disk_path is not None else [Path.cwd().anchor]
    pipeline = IntegratedAlertPipeline().add_sink(ConsoleSink())
    pipeline.add_sink(webhook if webhook is not None else WebhookMockSink())
    for path in paths:
        label = str(Path(path).absolute())
        pipeline.add_rule(AlertRule('High Disk Usage', 'DISK', f'disk_used_percent_{label}',
                                    80, severity='WARNING'))
    pipeline.add_rule(AlertRule('API High Latency', 'METRIC_STREAM', 'latency_ms',
                                500, severity='CRITICAL', cooldown_sec=3))
    pipeline.add_rule(AlertRule('High Memory', 'METRIC_STREAM', 'memory_mb',
                                300, cooldown_sec=3))
    security_engine = None
    if args.security:
        from .security_detector import UnifiedSecurityEngine
        security_engine = UnifiedSecurityEngine()
    engine = SystemAnalyzerEngine(pipeline,security_engine=security_engine)
    if args.watch:
        try:
            total = run_watch(engine, paths, metrics_path=args.metrics_file,
                              interval_sec=args.interval, cycles=args.cycles)
        except KeyboardInterrupt:
            print('Monitoring stopped', flush=True)
            return 130
        if security_engine is not None:
            print('Security state:', json.dumps(security_engine.state_sizes() | {'cooldown_entries': pipeline.observation_state_size()}))
        print(f'Collected {total.events} events; {total.errors} collection/parse errors; '
              f'{total.delivery_failures} delivery failures')
        return int(bool(total.errors or total.delivery_failures))
    disk = engine.analyze_disk_usage(paths)
    stream = AnalysisReport()
    try:
        if args.demo:
            stream = engine.parse_and_analyze_stream([
                'time=10:00:01 status=200 lat_ms=25.4 mem_mb=180',
                'time=10:00:02 status=200 lat_ms=650 mem_mb=350.5',
                'time=10:00:03 status=200 lat_ms=620 mem_mb=340',
                'time=10:00:04 status=200 lat_ms=15.1 mem_mb=210'])
        elif args.metrics_file == '-':
            stream = engine.parse_and_analyze_stream(sys.stdin)
        elif args.metrics_file:
            with open(args.metrics_file, encoding='utf-8') as source:
                stream = engine.parse_and_analyze_stream(source)
    except (OSError, UnicodeError) as exc:
        stream.errors += 1
        LOG.warning('Metric input failed: %s', exc)
    if security_engine is not None:
        print('Security state:', json.dumps(security_engine.state_sizes() | {'cooldown_entries': pipeline.observation_state_size()}))
    print(f'Collected {disk.events + stream.events} events; '
          f'{disk.errors + stream.errors} collection/parse errors; '
          f'{disk.delivery_failures + stream.delivery_failures} delivery failures')
    return int(bool(disk.errors or stream.errors or disk.delivery_failures or stream.delivery_failures))


if __name__ == '__main__':
    raise SystemExit(main())
