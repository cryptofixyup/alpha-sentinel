"""Bounded, incremental reading of complete UTF-8 metric lines."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import stat
from dataclasses import dataclass, field

LOG = logging.getLogger(__name__)


@dataclass
class FollowBatch:
    lines: list[str] = field(default_factory=list)
    errors: int = 0


class MetricFileFollower:
    """Skip existing history on first open, then read each appended line once.

    Rotation (file identity change) and observed truncation reset the cursor.
    Copy-truncate followed by regrowth beyond the old offset between polls
    cannot be detected reliably. Cursor state is process-local.
    """
    def __init__(self, path: str | Path, *, max_read_bytes: int = 65536,
                 max_line_bytes: int = 16384):
        for value in (max_read_bytes, max_line_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError('follower byte limits must be positive integers')
        self.path = Path(path)
        self._read_limit = max_read_bytes
        self._line_limit = max_line_bytes
        self._first = True
        self._identity = None
        self._offset = 0
        self._pending = b''
        self._discard = False

    def poll(self) -> FollowBatch:
        batch = FollowBatch()
        first = self._first
        try:
            # NONBLOCK avoids hanging when a configured path is a FIFO on POSIX.
            fd = os.open(self.path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0)
                         | getattr(os, 'O_BINARY', 0))
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise OSError('metric input must be a regular file')
                identity = (info.st_dev, info.st_ino)
                if first:
                    self._identity, self._offset = identity, info.st_size
                    if info.st_size:
                        source.seek(info.st_size - 1)
                        self._discard = source.read(1) != b'\n'
                    self._first = False
                    return batch
                if identity != self._identity or info.st_size < self._offset:
                    self._identity, self._offset = identity, 0
                    self._pending, self._discard = b'', False
                source.seek(self._offset)
                chunk = source.read(self._read_limit)
                self._offset = source.tell()
        except OSError as exc:
            # An absent file can be newly created; an inaccessible existing file
            # must still skip its history when the first open finally succeeds.
            if isinstance(exc, FileNotFoundError):
                self._first = False
            batch.errors += 1
            LOG.warning('Metric file is unavailable or is not a readable regular file')
            return batch

        pieces = (self._pending + chunk).split(b'\n')
        self._pending = pieces.pop()
        for line in pieces:
            if self._discard:
                self._discard = False
                continue
            if len(line) > self._line_limit:
                batch.errors += 1
                continue
            try:
                batch.lines.append(line.decode('utf-8').rstrip('\r'))
            except UnicodeError:
                batch.errors += 1
        if self._discard:
            self._pending = b''
        elif len(self._pending) > self._line_limit:
            batch.errors += 1
            self._pending, self._discard = b'', True
        return batch
