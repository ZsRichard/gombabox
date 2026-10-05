import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from core.event_logging import EventLogHandler


class EventLoggingTests(unittest.TestCase):
    def test_sources_dedup_journal_only_and_rollback_independence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'logs.db')
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE system_logs (timestamp TEXT, level TEXT, message TEXT, source TEXT)')
            connection.commit()
            handler = EventLogHandler(path)
            try:
                # This unrelated transaction must not erase a queued error when rolled back.
                connection.execute("INSERT INTO system_logs VALUES ('now', 'INFO', 'rolled back', 'test')")
                def emit(name, level, message):
                    handler.handle(logging.LogRecord(name, level, __file__, 1, message, (), None))
                emit('core.controller', logging.ERROR, 'sensor cycle failed')
                emit('core.controller', logging.ERROR, 'sensor cycle failed')
                emit('drivers.camera', logging.INFO, 'capture saved')
                emit('drivers.camera', logging.INFO, 'capture saved')
                emit('werkzeug', logging.INFO, 'GET /api/health')
                connection.rollback()
                handler.close()
                rows = connection.execute('SELECT level, message, source FROM system_logs').fetchall()
                self.assertEqual(rows, [('ERROR', 'sensor cycle failed', 'controller'),
                                        ('INFO', 'capture saved', 'camera'), ('INFO', 'capture saved', 'camera')])
            finally:
                handler.close(); connection.close()


if __name__ == '__main__':
    unittest.main()
