"""Bounded receipt-window heuristics that emit suspected security observations."""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import math
import time
from typing import Callable

from .security_events import LogDigester, NormalizedEvent, ParseError, number


def positive(value, name):
    try:
        result = number(value)
    except ParseError:
        raise ValueError(f'{name} must be finite and positive') from None
    if result <= 0:
        raise ValueError(f'{name} must be finite and positive')
    return result


def capacity(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


@dataclass(frozen=True)
class AnomalyScore:
    metric_name: str
    unit: str
    value: float
    mean: float
    std_dev: float
    z_score: float
    is_anomaly: bool
    prior_samples: int
    baseline_evidence: tuple[str, ...]


@dataclass
class _Baseline:
    count: int
    mean: float
    variance: float
    last_seen: float
    evidence: deque


class EWMAAnomalyDetector:
    """Scores against prior same-unit data; outliers do not train the baseline."""
    def __init__(self, alpha=.15, z_threshold=3, min_samples=5, *, max_series=1024,
                 state_ttl_sec=300):
        self.alpha = positive(alpha, 'alpha')
        if self.alpha >= 1:
            raise ValueError('alpha must be below one')
        self.z_threshold = positive(z_threshold, 'z_threshold')
        self.min_samples = capacity(min_samples, 'min_samples')
        self.max_series = capacity(max_series, 'max_series')
        self.ttl = positive(state_ttl_sec, 'state_ttl_sec')
        self._state = OrderedDict()
        self.evictions = 0

    def prune(self, now):
        for key in list(self._state):
            if now - self._state[key].last_seen >= self.ttl:
                del self._state[key]

    def process(self, key, measurement, evidence_id, now):
        self.prune(now)
        val = measurement.value
        st = self._state.get(key)
        if st is None:
            if len(self._state) >= self.max_series:
                self._state.popitem(last=False)
                self.evictions += 1
            self._state[key] = _Baseline(1, val, 0, now, deque([evidence_id], maxlen=5))
            return None
        # One original measurement unit of noise prevents zero-variance blindness.
        std = max(math.sqrt(max(st.variance, 0)), 1.0)
        z = (val - st.mean) / std
        hit = st.count >= self.min_samples and abs(z) >= self.z_threshold
        score = AnomalyScore(measurement.name, measurement.unit, val, st.mean, std,
                             z, hit, st.count, tuple(st.evidence))
        st.last_seen = now
        self._state.move_to_end(key)
        if not hit:
            delta = val - st.mean
            st.mean += self.alpha * delta
            st.variance = (1-self.alpha) * (st.variance + self.alpha * delta * delta)
            st.count = min(st.count+1, (1 << 63)-1)
            st.evidence.append(evidence_id)
        return score


@dataclass(frozen=True)
class UnifiedThreatAlert:
    alert_type: str
    severity: str
    source_ip: str
    summary: str
    evidence_count: int
    targets: frozenset[str]
    evidence_ids: tuple[str, ...]
    evidence_truncated: bool = False
    metric_name: str | None = None
    metric_unit: str | None = None
    resource: str = '/'
    anomaly: AnomalyScore | None = None


@dataclass(frozen=True)
class DetectionResult:
    event: NormalizedEvent | None
    observations: tuple[UnifiedThreatAlert, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class _Failure:
    at: float
    user: str | None
    evidence_id: str


@dataclass
class _Source:
    last_seen: float
    failures: deque = field(default_factory=deque)
    truncated_until: float = 0


class UnifiedSecurityEngine:
    def __init__(self, window_seconds=60, *, clock: Callable[[], float] = time.monotonic,
                 max_sources=1024, max_series=1024, max_failures_per_source=100,
                 state_ttl_sec=300, alpha=.15, z_threshold=3, min_samples=5):
        self.window_seconds = positive(window_seconds, 'window_seconds')
        self.max_sources = capacity(max_sources, 'max_sources')
        self.max_failures = capacity(max_failures_per_source, 'max_failures_per_source', 4)
        self.ttl = positive(state_ttl_sec, 'state_ttl_sec')
        self.digester = LogDigester()
        self.anomaly_detector = EWMAAnomalyDetector(alpha,z_threshold,min_samples,
                                                   max_series=max_series,state_ttl_sec=state_ttl_sec)
        self._clock = clock
        self._last_clock = None
        self._sources = OrderedDict()
        self._evictions = 0

    def _prune(self, now):
        self.anomaly_detector.prune(now)
        for ip in list(self._sources):
            state = self._sources[ip]
            if now-state.last_seen >= self.ttl:
                del self._sources[ip]
                continue
            while state.failures and now-state.failures[0].at >= self.window_seconds:
                state.failures.popleft()

    def state_sizes(self):
        return {'sources':len(self._sources), 'series':len(self.anomaly_detector._state),
                'failures':sum(len(s.failures) for s in self._sources.values()),
                'evictions':self._evictions+self.anomaly_detector.evictions}

    def ingest_raw_log(self, raw_line: str, current_time: float | None = None) -> DetectionResult:
        now = number(self._clock())
        if self._last_clock is not None and now < self._last_clock:
            raise ValueError('receipt clock moved backwards')
        self._last_clock = now
        self._prune(now)
        try:
            event = self.digester.parse(raw_line, time.time() if current_time is None else current_time)
        except ParseError as exc:
            return DetectionResult(None,error=str(exc))
        if event is None or event.source_ip is None:
            return DetectionResult(event)
        ip = event.source_ip
        state = self._sources.get(ip)
        if state is None:
            if len(self._sources) >= self.max_sources:
                self._sources.popitem(last=False)
                self._evictions += 1
            state = self._sources[ip] = _Source(now)
        state.last_seen = now
        self._sources.move_to_end(ip)
        outliers = []
        for measurement in event.metrics:
            key = (ip,event.target_resource,measurement.name,measurement.unit)
            score = self.anomaly_detector.process(key,measurement,event.evidence_id,now)
            if score is not None and score.is_anomaly:
                outliers.append(score)
        if event.action in ('LOGIN_FAILED', 'AUTH_FAILED'):
            if len(state.failures) >= self.max_failures:
                state.failures.popleft()
                state.truncated_until = now+self.window_seconds
            state.failures.append(_Failure(now,event.user_id,event.evidence_id))
        alerts = []
        if event.action in ('LOGIN_FAILED', 'AUTH_FAILED') and len(state.failures) >= 4:
            users = frozenset(f.user for f in state.failures if f.user is not None)
            kind = 'SUSPECTED_PASSWORD_SPRAY' if len(users) >= 3 else 'SUSPECTED_AUTH_FAILURE_BURST'
            alerts.append(UnifiedThreatAlert(kind,'HIGH' if len(users)>=3 else 'MEDIUM',ip,
                f'Suspected authentication pattern: {len(state.failures)} retained failures '
                f'from {ip} across {len(users)} known users in the receipt window',
                len(state.failures),users,tuple(f.evidence_id for f in state.failures),
                now < state.truncated_until,resource=event.target_resource,
                anomaly=outliers[0] if outliers else None))
        for score in outliers:
            alerts.append(UnifiedThreatAlert('SUSPECTED_METRIC_OUTLIER','MEDIUM',ip,
                f'Suspected metric outlier: {score.metric_name}={score.value:g} {score.unit}; '
                f'prior mean={score.mean:g}, score={score.z_score:+.2f}',
                1,frozenset({event.target_resource}),(event.evidence_id,),
                metric_name=score.metric_name,metric_unit=score.unit,resource=event.target_resource,
                anomaly=score))
        return DetectionResult(event,tuple(alerts))
