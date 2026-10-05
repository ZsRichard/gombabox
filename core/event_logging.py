"""Persist application events asynchronously, independently of sensor transactions."""
import atexit
import datetime
import logging
import queue
import sqlite3
import sys
import threading
import time
from collections import OrderedDict

SOURCES = {
    'core.controller': 'controller', 'drivers.sensors': 'sensors',
    'drivers.camera': 'camera', 'drivers.relays': 'relays',
    'core.constants': 'storage', 'core.vision': 'image-analysis',
    'core.web_push': 'notifications'
}


class EventLogHandler(logging.Handler):
    def __init__(self, database_path):
        super().__init__(logging.INFO)
        self.path = database_path
        self.events = queue.Queue(maxsize=2000)
        self.stopping = threading.Event()
        self.recent = OrderedDict()
        self.thread = threading.Thread(target=self._write, name='event-log-writer', daemon=True)
        self.thread.start()

    def emit(self, record):
        if record.name not in SOURCES and record.name not in ('__main__', 'app'):
            return  # HTTP access logs and third-party debug output stay in the journal.
        try:
            source = SOURCES.get(record.name, 'server')
            if record.module == 'web_push':
                source = 'notifications'
            message = record.getMessage()[:4000]
            # Suppress identical repeating faults for one minute, not successful control pulses.
            if record.levelno >= logging.WARNING:
                key = (source, record.levelname, message)
                now = time.monotonic()
                if now - self.recent.get(key, -1000) < 60:
                    return
                self.recent[key] = now
                self.recent.move_to_end(key)
                while len(self.recent) > 256:
                    self.recent.popitem(last=False)
            self.events.put_nowait((datetime.datetime.fromtimestamp(record.created).isoformat(' '),
                                   record.levelname, message, source))
        except Exception:
            self.handleError(record)  # Journal fallback; never log recursively to this handler.

    def _write(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            while not self.stopping.is_set() or not self.events.empty():
                try:
                    event = self.events.get(timeout=0.2)
                except queue.Empty:
                    continue
                batch = [event]
                while len(batch) < 100:
                    try:
                        batch.append(self.events.get_nowait())
                    except queue.Empty:
                        break
                try:
                    connection.executemany(
                        'INSERT INTO system_logs (timestamp, level, message, source) VALUES (?, ?, ?, ?)', batch)
                    connection.commit()
                except sqlite3.Error as error:
                    connection.rollback()
                    print(f'Event log persistence failed: {error}; events: {batch!r}', file=sys.stderr)
                finally:
                    for _ in batch:
                        self.events.task_done()
        finally:
            connection.close()

    def close(self):
        self.stopping.set()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=6)
        super().close()


def install_event_logging(database_path):
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, EventLogHandler):
            return handler
    handler = EventLogHandler(database_path)
    root.addHandler(handler)
    atexit.register(handler.close)
    return handler
