"""Generic JSON webhook delivery with explicit transport limits."""
from __future__ import annotations

import ipaddress
from http.client import HTTPException
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .integrated_alerts import Alert


class WebhookDeliveryError(RuntimeError):
    """A sanitized failure: never includes endpoint, response body, or credentials."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WebhookSink:
    """One POST per emit; no redirects and no immediate retries.

    timeout_sec is a socket-operation timeout, not a hard wall-clock deadline.
    HTTPS uses Python's default certificate and hostname verification.
    """
    def __init__(self, url: str, *, timeout_sec: float = 5,
                 allow_http_localhost: bool = False):
        try:
            if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, (int, float)):
                raise ValueError
            timeout = float(timeout_sec)
            if not math.isfinite(timeout) or not 0 < timeout <= 60:
                raise ValueError
        except (ValueError, OverflowError):
            raise ValueError('webhook timeout must be finite and in (0, 60] seconds') from None
        try:
            if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url):
                raise ValueError
            parsed = urllib.parse.urlsplit(url)
            host = parsed.hostname
            if not host or parsed.username is not None or parsed.password is not None or parsed.fragment:
                raise ValueError
            # Accessing port validates its syntax and range.
            _ = parsed.port
            loopback = host.lower() == 'localhost'
            try:
                loopback = loopback or ipaddress.ip_address(host).is_loopback
            except ValueError:
                pass
            if parsed.scheme != 'https' and not (
                    parsed.scheme == 'http' and allow_http_localhost and loopback):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError('webhook requires a valid HTTPS URL without userinfo or fragment; '
                             'HTTP is allowed only for explicitly enabled loopback testing') from None
        self._url = url
        self._timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())

    def emit(self, alert: Alert) -> None:
        payload = json.dumps({
            'alert': alert.rule_name, 'severity': alert.severity,
            'category': alert.event.category, 'metric': alert.event.metric_name,
            'value': alert.event.value, 'timestamp': alert.event.timestamp,
            'details': alert.details,
        }, allow_nan=False).encode('utf-8')
        request = urllib.request.Request(self._url, data=payload, method='POST',
                                         headers={'Content-Type': 'application/json'})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status = response.status
                if not 200 <= status < 300:
                    raise WebhookDeliveryError(f'webhook returned HTTP {status}')
                # Do not read an unbounded response body or log its contents.
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise WebhookDeliveryError(f'webhook returned HTTP {status}') from None
        except (OSError, ValueError, urllib.error.URLError, HTTPException):
            raise WebhookDeliveryError('webhook transport failed') from None
