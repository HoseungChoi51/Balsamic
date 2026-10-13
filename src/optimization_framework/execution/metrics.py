"""Bounded, file-versioned projections of append-only worker metric journals."""
from base64 import b64decode, b64encode
from collections import OrderedDict
import json
import re
from threading import Lock

DESIGNS = re.compile(rb"\[[01,]{127,}\]")
PACKED = "packed_bits"
PACKED_DESIGNS = re.compile(rb'\{"packed_bits":"[A-Za-z0-9+/=]*","cells":\d+\}')
PACK_FROM = 128   # cells; a shorter design is cheap to keep as a list
_DIGITS, _CELLS = bytes.maketrans(b"\x00\x01", b"01"), bytes.maketrans(b"01", b"\x00\x01")


def pack_candidate(candidate):
    """A long binary design as packed bits for a journal row; any other candidate unchanged.

    The request and observation journals hold every evaluated design. As a JSON list a
    32,768-cell design takes 66 kB in each; packed it takes 5.5 kB.
    """
    if type(candidate) is not list or len(candidate) < PACK_FROM or set(map(type, candidate)) != {int} or not set(candidate) <= {0, 1}:
        return candidate
    bits = int(bytes(candidate).translate(_DIGITS), 2).to_bytes((len(candidate) + 7) // 8, "big")
    return {PACKED: b64encode(bits).decode(), "cells": len(candidate)}


def unpack_candidate(candidate):
    """The design a journal row holds, whichever way it was written."""
    if type(candidate) is not dict or PACKED not in candidate:
        return candidate
    digits = format(int.from_bytes(b64decode(candidate[PACKED]), "big"), "b").zfill(candidate["cells"])
    return list(digits.encode().translate(_CELLS))


def unpacked(row):
    """A journal record with its design as the list every reader expects."""
    if type(row) is dict and type(row.get("candidate")) is dict and PACKED in row["candidate"]:
        row["candidate"] = unpack_candidate(row["candidate"])
    return row


def scalar_record(line):
    """Parse one journal record for its scalar fields, about ten times faster for a large design.

    A record can carry binary designs (the evaluated one, as a list or packed; the best one and,
    in older journals, an archive of others); they are cut to empty lists before parsing, so
    only scalar fields of the result may be used.
    """
    return json.loads(PACKED_DESIGNS.sub(b"[]", DESIGNS.sub(b"[]", line)))


def scalar_rows(path):
    """Each record of a journal as (where its line starts, the line, its scalar fields).

    Looking through a journal of large designs this way keeps nothing large in memory; read
    the whole record of a line that turns out to matter with full_row().
    """
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return
    with stream:
        offset = 0
        for line in stream:
            try:
                row = scalar_record(line)
            except ValueError:
                # A torn final write is never reported as a completed record.
                if line.endswith(b"\n"):
                    raise ValueError(f"Corrupt journal record: {path.name}") from None
                return
            yield offset, line, row
            offset += len(line)


def full_row(path, offset):
    with path.open("rb") as stream:
        stream.seek(offset)
        return unpacked(json.loads(stream.readline()))


def recent_metrics(path, limit, *, block_bytes=65536):
    """Read only enough trailing journal blocks for the last valid records.

    Preserve append order, including repeated counters after recovery. The
    journal itself remains the source of truth; this view does not merge
    checkpoints, discard earlier attempts, or cache a running writer's tail.
    """
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        return []
    rows, remainder = [], b""
    with stream:
        position = stream.seek(0, 2)
        while position:
            count = min(position, block_bytes)
            position -= count
            stream.seek(position)
            lines = (stream.read(count) + remainder).split(b"\n")
            remainder = lines.pop(0)
            for line in reversed(lines):
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue  # Match the ordinary reader's torn/malformed-line handling.
                if len(rows) == limit:
                    return list(reversed(rows))
        try:
            rows.append(json.loads(remainder))
        except ValueError:
            pass
    return list(reversed(rows))


# Every chart that shows a trial reads its journal again every few seconds, so only a journal
# this small is parsed and returned whole.
LARGE_JOURNAL_BYTES = 2 * 2 ** 20


class LargeJournalScalars:
    """Scalar columns of journals too large to return whole, parsed once and then only where they grow.

    A row gives the best design where it changed (131 kB for 32,768 cells), and older journals
    repeat it and an archive of others on every row, over a megabyte per step. Rows keep only
    their scalar fields. A curve read without named fields is thinned to an even sample that
    always includes the latest record.
    """

    def __init__(self, max_rows=2000, max_files=64):
        self.max_rows, self.max_files = max_rows, max_files
        self._entries = OrderedDict()
        self._lock = Lock()

    def read(self, path, fields=None):
        with self._lock:
            entry = self._entries.pop(path, None) or {"identity": None, "offset": 0, "rows": [], "lock": Lock()}
            self._entries[path] = entry
            while len(self._entries) > self.max_files:
                self._entries.popitem(last=False)
        with entry["lock"]:
            try:
                stat = path.stat()
            except FileNotFoundError:
                return []
            identity = (stat.st_dev, stat.st_ino)
            if entry["identity"] != identity or stat.st_size < entry["offset"]:
                entry.update(identity=identity, offset=0, rows=[])   # replaced or truncated: read again
            with path.open("rb") as stream:
                stream.seek(entry["offset"])
                for line in stream:
                    if not line.endswith(b"\n"):
                        break  # an active writer's unfinished record
                    entry["offset"] += len(line)
                    try:
                        raw = scalar_record(line)
                    except ValueError:
                        continue
                    entry["rows"].append({key: value for key, value in raw.items()
                                          if value is None or type(value) in (bool, int, float, str)})
            rows = entry["rows"]
            if fields is not None:
                return [{field: row[field] for field in fields if field in row} for row in rows]
            if len(rows) <= self.max_rows:
                return [dict(row) for row in rows]
            spacing = (len(rows) - 1) / (self.max_rows - 1)
            return [dict(rows[round(index * spacing)]) for index in range(self.max_rows)]


class MetricProjectionCache:
    """Keep just requested scalar columns, never candidates or optimizer archives.

    Stat every read, including completed trials: resumed/replaced/truncated logs
    invalidate old projections. A changing file is returned but is not cached.
    The ordinary full-metric reader remains independent of this cache.
    """

    def __init__(self, max_points=100_000, max_files=128):
        self.max_points, self.max_files = max_points, max_files
        self._entries = OrderedDict()
        self._points = 0
        self._lock = Lock()

    @staticmethod
    def _version(path):
        try:
            stat = path.stat()
            return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
        except FileNotFoundError:
            return None

    def read(self, path, fields):
        fields = tuple(dict.fromkeys(fields))
        key, version = (path, fields), self._version(path)
        with self._lock:
            cached = self._entries.pop(key, None)
            if cached is not None:
                if version is not None and cached[0] == version:
                    self._entries[key] = cached
                    return [dict(row) for row in cached[1]]
                self._points -= len(cached[1])
        if version is None:
            return []
        rows = []
        cacheable = True
        with path.open() as stream:
            for line in stream:
                try:
                    raw = json.loads(line)
                except ValueError:
                    continue  # Active writers may leave an incomplete final line.
                row = tuple((field, raw[field]) for field in fields if field in raw)
                # The bound counts scalar points. Larger structures are returned
                # normally but cannot inflate or mutate a shared cached entry.
                cacheable &= all(value is None or type(value) in (bool, int, float) for _, value in row)
                rows.append(row)
        if cacheable and len(rows) <= self.max_points and self._version(path) == version:
            with self._lock:
                previous = self._entries.pop(key, None)
                if previous is not None:
                    self._points -= len(previous[1])
                self._entries[key] = (version, rows)
                self._points += len(rows)
                while self._points > self.max_points or len(self._entries) > self.max_files:
                    _, (_, evicted) = self._entries.popitem(last=False)
                    self._points -= len(evicted)
        return [dict(row) for row in rows]
