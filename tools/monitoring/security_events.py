"""Bounded normalization of supported security log formats; no attack attribution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as daytime
import hashlib
import ipaddress
import json
import math
import re
import shlex
from urllib.parse import urlsplit

MAX_METRIC = 1_000_000_000_000
METRIC_UNITS = {'latency_ms': 'ms', 'response_bytes': 'bytes'}


class ParseError(ValueError):
    """Safe rejection reason; never contains the raw input."""


def number(value, *, text=False, nonnegative=True):
    if isinstance(value, bool) or not isinstance(value, (int, float, str) if text else (int, float)):
        raise ParseError('invalid numeric field')
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ParseError('invalid numeric field') from None
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ParseError('invalid numeric field')
    return result


def label(value, limit, *, optional=False):
    if optional and value in (None, '', '-'):
        return None
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ParseError('invalid text field')
    return value


@dataclass(frozen=True)
class Measurement:
    name: str
    unit: str
    value: float

    def __post_init__(self):
        value = number(self.value)
        if METRIC_UNITS.get(self.name) != self.unit or value > MAX_METRIC:
            raise ParseError('invalid measurement semantics or range')
        if self.unit == 'bytes' and not value.is_integer():
            raise ParseError('byte measurement must be an integer')
        object.__setattr__(self, 'value', value)


@dataclass(frozen=True)
class NormalizedEvent:
    received_at: float
    source_timestamp: float | None
    source_time_text: str | None
    source_ip: str | None
    user_id: str | None
    action: str
    target_resource: str
    status_code: int | None
    metrics: tuple[Measurement, ...]
    evidence_id: str


class LogDigester:
    COMMON = re.compile(r'^(?P<ip>\S+)\s+\S+\s+(?P<user>\S+)\s+\[(?P<time>[^\]]+)\]\s+"[A-Z]+\s+(?P<path>\S+)\s+HTTP/[0-9.]+"\s+(?P<status>\d{3})\s+(?P<bytes>\d+|-)(?:\s.*)?$')
    SYSLOG = re.compile(r'^(?P<time>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+\S+\s+(?P<process>[\w./-]+)(?:\[\d+\])?:\s*(?P<msg>.*)$')
    SSH_FAILURE = re.compile(r'^Failed password for (?:invalid user )?(?P<user>\S+) from (?P<ip>\S+) port \d+(?: ssh2)?$')
    FIELDS = frozenset({'ip', 'user', 'action', 'path', 'resource', 'status', 'lat_ms', 'bytes', 'time'})

    def __init__(self, *, max_line_bytes=16384):
        if isinstance(max_line_bytes, bool) or not isinstance(max_line_bytes, int) or max_line_bytes <= 0:
            raise ValueError('max_line_bytes must be a positive integer')
        self.max_line_bytes = max_line_bytes

    def _kv(self, line):
        try:
            tokens = shlex.split(line)
        except ValueError:
            raise ParseError('invalid key-value quoting') from None
        data = {}
        for token in tokens:
            if '=' not in token:
                raise ParseError('invalid key-value token')
            key, value = token.split('=', 1)
            if key in data:
                raise ParseError('duplicate key-value field')
            data[key] = value
        if not self.FIELDS.intersection(data):
            raise ParseError('unsupported log format')
        return data

    def _time(self, value, *, text):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return number(value), None
        value = label(value, 64)
        if text:
            try:
                return number(value, text=True), value
            except ParseError:
                pass
        try:
            if re.fullmatch(r'\d{2}:\d{2}:\d{2}(?:\.\d+)?', value):
                daytime.fromisoformat(value)
                return None, value
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.timestamp(), value
            # Time-of-day metadata is retained without guessing date/timezone.
            daytime.fromisoformat(value)
            return None, value
        except (ValueError, OverflowError, OSError):
            raise ParseError('invalid or ambiguous source timestamp') from None

    def parse(self, raw_line: str, now: float) -> NormalizedEvent | None:
        received_at = number(now)
        if not isinstance(raw_line, str) or len(raw_line) > self.max_line_bytes:
            raise ParseError('invalid or oversized log line')
        try:
            raw = raw_line.encode('utf-8')
        except UnicodeError:
            raise ParseError('invalid UTF-8 log line') from None
        if len(raw) > self.max_line_bytes:
            raise ParseError('oversized log line')
        line = raw_line.strip()
        if not line:
            return None
        source_timestamp, source_time_text = None, None
        text = False
        if line.startswith('{'):
            try:
                data = json.loads(line)
            except (ValueError, RecursionError):
                raise ParseError('invalid JSON log') from None
            if not isinstance(data, dict):
                raise ParseError('JSON log must be an object')
        elif match := self.COMMON.fullmatch(line):
            data = match.groupdict()
            text = True
            try:
                source_timestamp = datetime.strptime(data.pop('time'), '%d/%b/%Y:%H:%M:%S %z').timestamp()
            except (ValueError, OverflowError, OSError):
                raise ParseError('invalid access-log timestamp') from None
            data['action'] = 'WEB_ACCESS'
            if data['bytes'] == '-':
                del data['bytes']
        elif match := self.SYSLOG.fullmatch(line):
            parts = match.groupdict()
            source_time_text = parts['time']
            try:
                datetime.strptime('2000 ' + source_time_text, '%Y %b %d %H:%M:%S')
            except ValueError:
                raise ParseError('invalid syslog timestamp') from None
            if parts['process'] == 'sshd' and (auth := self.SSH_FAILURE.fullmatch(parts['msg'])):
                data = auth.groupdict() | {'action': 'LOGIN_FAILED', 'path': '/ssh'}
            else:
                data = self._kv(parts['msg'])
            text = True
        else:
            data = self._kv(line)
            text = True

        if 'time' in data:
            source_timestamp, source_time_text = self._time(data['time'], text=text)
        ip = label(data.get('ip'), 64, optional=True)
        if ip is not None:
            try:
                address = ipaddress.ip_address(ip)
            except ValueError:
                raise ParseError('invalid source address') from None
            ip = None if address.is_unspecified else str(address)
        user = label(data.get('user'), 128, optional=True)
        action = label(data.get('action', 'API_REQUEST'), 64).upper()
        resource = label(data.get('resource', data.get('path', '/')), 512)
        try:
            resource = urlsplit(resource).path or '/'
        except ValueError:
            raise ParseError('invalid resource path') from None
        if not resource.startswith('/'):
            raise ParseError('resource must be a path')
        status = None
        if 'status' in data:
            val = data['status']
            if text and isinstance(val, str) and re.fullmatch(r'\d{3}', val):
                val = int(val)
            if isinstance(val, bool) or not isinstance(val, int) or not 100 <= val <= 599:
                raise ParseError('invalid HTTP status')
            status = val
        metrics = []
        for source, name, unit in [('lat_ms', 'latency_ms', 'ms'), ('bytes', 'response_bytes', 'bytes')]:
            if source in data:
                metrics.append(Measurement(name, unit, number(data[source], text=text)))
        return NormalizedEvent(received_at, source_timestamp, source_time_text, ip, user,
                               action, resource, status, tuple(metrics), hashlib.sha256(raw).hexdigest())
