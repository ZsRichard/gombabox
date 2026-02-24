# app.py - GombaBox Mushroom Growing Automation System
# Main Flask application with REST API and hardware integration

import os
import sys


def _ensure_venv():
    """Re-exec into the local venv Python if available and not already active."""
    if os.environ.get("GOMBABOX_SKIP_VENV") == "1":
        return
    if sys.prefix != sys.base_prefix:
        return

    venv_python = os.path.join(os.path.dirname(__file__), "venv", "bin", "python3")
    if os.path.isfile(venv_python):
        os.environ["GOMBABOX_SKIP_VENV"] = "1"
        os.execv(venv_python, [venv_python] + sys.argv)


_ensure_venv()

import time
import logging
import threading
import subprocess
import datetime
import sqlite3
from flask import Flask, jsonify, render_template, request, send_file
from flask_sqlalchemy import SQLAlchemy

# Database
from models import db, Measurement, CameraCapture, SystemLog, Setting
from config import Config
from app_config import (
    DATABASE_URI, USE_MOCK_HARDWARE, API_HOST, API_PORT, API_DEBUG,
    BACKGROUND_CYCLE_INTERVAL, DEFAULT_MEASUREMENTS_LIMIT,
    DEFAULT_CAPTURES_LIMIT, DEFAULT_LOGS_LIMIT, LOGGING_LEVEL,
    BACKUP_PRIMARY_PATH, BACKUP_FALLBACK_PATH, BACKUP_INTERVAL_HOURS
)

# Drivers
from drivers.relays import MockRelayDriver, RealRelayDriver
from drivers.sensors import MockSensorDriver, RealSensorDriver
from drivers.camera import MockCameraDriver, RealCameraDriver

# Core
from core.controller import MushroomController
from core.constants import get_latest_capture_path, SSD_CAPTURE_DIRECTORY

# Configure Flask
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Configure logging
logging.basicConfig(level=LOGGING_LEVEL)
logger = logging.getLogger(__name__)

DB_TABLES = {
    'measurements': {
        'model': Measurement,
        'id_field': 'id',
        'columns': ['id', 'timestamp', 'temperature', 'humidity', 'pressure', 'co2', 'light'],
        'editable': ['temperature', 'humidity', 'pressure', 'co2', 'light'],
        'order_by': Measurement.timestamp.desc()
    },
    'camera_captures': {
        'model': CameraCapture,
        'id_field': 'id',
        'columns': ['id', 'timestamp', 'filename', 'analysis_result'],
        'editable': ['filename', 'analysis_result'],
        'order_by': CameraCapture.timestamp.desc()
    },
    'system_logs': {
        'model': SystemLog,
        'id_field': 'id',
        'columns': ['id', 'timestamp', 'level', 'message'],
        'editable': ['level', 'message'],
        'order_by': SystemLog.timestamp.desc()
    },
    'settings': {
        'model': Setting,
        'id_field': 'key',
        'columns': ['key', 'value', 'description'],
        'editable': ['value', 'description'],
        'order_by': Setting.key.asc()
    }
}


class BackgroundTaskManager:
    """Manages background tasks following Single Responsibility Principle."""
    
    def __init__(self, app_instance, db_session, relay_driver_instance):
        self.app = app_instance
        self.db = db_session
        self.relay_driver = relay_driver_instance
        self.thread = None
        self.running = False
        
    def start(self):
        """Start background task thread."""
        if self.thread is None or not self.thread.is_alive():
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            logger.info("Background task thread started.")
            
    def stop(self):
        """Stop background task thread."""
        self.running = False
        logger.info("Background task thread stopped.")
        
    def is_running(self):
        """Check if background tasks are running."""
        return self.running and (self.thread is not None and self.thread.is_alive())
    
    def _run(self):
        """Main background task loop - runs sensor cycles."""
        logger.info("Background task loop starting...")
        
        with self.app.app_context():
            # Select drivers based on configuration
            if USE_MOCK_HARDWARE:
                logger.info("SIMULATION MODE ACTIVE - Using mock hardware")
                sensors = MockSensorDriver()
                camera = MockCameraDriver()
            else:
                logger.info("HARDWARE MODE - Using real hardware")
                sensors = RealSensorDriver()
                camera = RealCameraDriver()

            # Create controller (reuse shared relay driver)
            controller = MushroomController(sensors, self.relay_driver, camera, self.db)

            # Main loop
            while self.running:
                try:
                    controller.run_cycle()
                except Exception as e:
                    logger.error(f"Error in background cycle: {e}")
                    logger.exception(e)
                
                time.sleep(BACKGROUND_CYCLE_INTERVAL)


class DatabaseBackupManager:
    """Manages periodic backups of the SQLite database file."""

    def __init__(self, app_instance, db_uri):
        self.app = app_instance
        self.db_uri = db_uri
        self.thread = None
        self.running = False

    def start(self):
        """Start database backup thread."""
        if self.thread is None or not self.thread.is_alive():
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            logger.info("Database backup thread started.")

    def stop(self):
        """Stop database backup thread."""
        self.running = False
        logger.info("Database backup thread stopped.")

    def _resolve_db_path(self):
        """Resolve the SQLite database file path from the configured URI."""
        if not self.db_uri.startswith('sqlite:///'):
            logger.error("Database backup skipped: unsupported DB URI %s", self.db_uri)
            return None

        db_path = self.db_uri.replace('sqlite:///', '', 1)
        if os.path.isabs(db_path):
            return db_path

        instance_candidate = os.path.join(self.app.instance_path, db_path)
        if os.path.exists(instance_candidate):
            return instance_candidate

        return os.path.join(self.app.root_path, db_path)

    def _resolve_backup_dir(self):
        """Pick primary backup path if available, otherwise use fallback."""
        if os.path.isdir(BACKUP_PRIMARY_PATH):
            return BACKUP_PRIMARY_PATH

        fallback_path = BACKUP_FALLBACK_PATH
        if not os.path.isabs(fallback_path):
            fallback_path = os.path.join(self.app.root_path, fallback_path)

        return fallback_path

    def _backup_once(self):
        db_path = self._resolve_db_path()
        if not db_path or not os.path.exists(db_path):
            logger.error("Database backup skipped: database file not found at %s", db_path)
            return

        backup_dir = self._resolve_backup_dir()
        try:
            os.makedirs(backup_dir, exist_ok=True)
        except Exception as e:
            logger.error("Database backup skipped: cannot create backup directory %s: %s", backup_dir, e)
            return

        date_stamp = datetime.datetime.now().strftime('%Y%m%d')
        backup_path = os.path.join(backup_dir, f"gombabox_{date_stamp}.db")

        try:
            with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as dest:
                source.backup(dest)
            logger.info("Database backup saved to %s", backup_path)
        except Exception as e:
            logger.error("Database backup failed: %s", e)

    def _run(self):
        """Run the daily backup loop."""
        interval = datetime.timedelta(hours=BACKUP_INTERVAL_HOURS)
        next_run = datetime.datetime.now()

        while self.running:
            now = datetime.datetime.now()
            if now >= next_run:
                self._backup_once()
                next_run = now + interval

            sleep_seconds = max(1, min(60, int((next_run - now).total_seconds())))
            time.sleep(sleep_seconds)


# Shared relay driver for manual control via API
def _create_relay_driver():
    """Create relay driver instance (real or mock based on config)."""
    if USE_MOCK_HARDWARE:
        return MockRelayDriver()
    try:
        return RealRelayDriver()
    except Exception as e:
        logger.error(f"Failed to initialize RealRelayDriver: {e}")
        logger.info("Falling back to mock relay driver")
        return MockRelayDriver()

relay_driver = _create_relay_driver()

# Global instances
task_manager = BackgroundTaskManager(app, db.session, relay_driver)
backup_manager = DatabaseBackupManager(app, DATABASE_URI)


def _restart_service_async():
    """Restart the gombabox systemd service in a background thread."""
    def _restart_service():
        time.sleep(0.5)
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', 'gombabox'],
                capture_output=True,
                text=True,
                timeout=20
            )

            if result.returncode != 0:
                logger.error(f"Service restart failed: {result.stderr}")
        except Exception as restart_error:
            logger.error(f"Service restart error: {restart_error}")

    threading.Thread(target=_restart_service, daemon=True).start()


# REST API Routes
# REST API Routes

@app.route('/')
def index():
    """Serve main web UI dashboard."""
    try:
        return render_template('dashboard.html')
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return jsonify({'error': 'Failed to load dashboard'}), 500


@app.route('/api/measurements', methods=['GET'])
def get_measurements():
    """Get sensor measurements with pagination."""
    try:
        limit = request.args.get('limit', DEFAULT_MEASUREMENTS_LIMIT, type=int)
        limit = min(limit, 1000)  # Prevent excessive queries
        
        measurements = Measurement.query.order_by(
            Measurement.timestamp.desc()
        ).limit(limit).all()
        
        return jsonify([m.to_dict() for m in reversed(measurements)])
    except Exception as e:
        logger.error(f"Error fetching measurements: {e}")
        return jsonify({'error': 'Failed to fetch measurements'}), 500


@app.route('/api/measurements/latest', methods=['GET'])
def get_latest_measurement():
    """Get the most recent measurement."""
    try:
        measurement = Measurement.query.order_by(
            Measurement.timestamp.desc()
        ).first()
        return jsonify(measurement.to_dict() if measurement else {})
    except Exception as e:
        logger.error(f"Error fetching latest measurement: {e}")
        return jsonify({'error': 'Failed to fetch measurement'}), 500


@app.route('/api/measurements/history', methods=['GET'])
def get_measurements_history():
    """Get measurement history for a given time range.
    
    Query parameters:
    - hours: Number of hours back to retrieve (default: 1, max: 720 = 30 days)
    """
    try:
        hours = request.args.get('hours', '1', type=str)
        try:
            hours = int(hours)
            hours = min(max(hours, 1), 720)  # Clamp between 1 and 720 hours
        except ValueError:
            hours = 1
        
        # Calculate time cutoff
        time_cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
        
        # Fetch measurements from the time range
        measurements = Measurement.query.filter(
            Measurement.timestamp >= time_cutoff
        ).order_by(Measurement.timestamp.asc()).all()
        
        return jsonify({
            'measurements': [m.to_dict() for m in measurements],
            'hours': hours,
            'count': len(measurements)
        })
    except Exception as e:
        logger.error(f"Error fetching measurement history: {e}")
        return jsonify({'error': 'Failed to fetch measurement history'}), 500


@app.route('/api/camera/history', methods=['GET'])
def get_camera_history():
    """Get camera capture history for a given time range.
    
    Query parameters:
    - hours: Number of hours back to retrieve (default: 1, max: 720 = 30 days)
    """
    try:
        hours = request.args.get('hours', '1', type=str)
        try:
            hours = int(hours)
            hours = min(max(hours, 1), 720)  # Clamp between 1 and 720 hours
        except ValueError:
            hours = 1
        
        # Calculate time cutoff
        time_cutoff = datetime.datetime.now() - datetime.timedelta(hours=hours)
        
        # Fetch camera captures from the time range
        captures = CameraCapture.query.filter(
            CameraCapture.timestamp >= time_cutoff
        ).order_by(CameraCapture.timestamp.asc()).all()
        
        # Extract timestamps and coverage percentages
        capture_data = []
        for capture in captures:
            capture_data.append({
                'time': capture.timestamp.strftime('%Y-%m-%d %H:%M'),
                'analysis': capture.analysis_result or "0"
            })
        
        return jsonify({
            'captures': capture_data,
            'hours': hours,
            'count': len(capture_data)
        })
    except Exception as e:
        logger.error(f"Error fetching camera history: {e}")
        return jsonify({'error': 'Failed to fetch camera history'}), 500


@app.route('/api/camera/captures', methods=['GET'])
def get_camera_captures():
    """Get camera capture history with pagination."""
    try:
        limit = request.args.get('limit', DEFAULT_CAPTURES_LIMIT, type=int)
        limit = min(limit, 500)  # Prevent excessive queries
        
        captures = CameraCapture.query.order_by(
            CameraCapture.timestamp.desc()
        ).limit(limit).all()
        
        return jsonify([c.to_dict() for c in reversed(captures)])
    except Exception as e:
        logger.error(f"Error fetching camera captures: {e}")
        return jsonify({'error': 'Failed to fetch captures'}), 500


@app.route('/api/camera/latest', methods=['GET'])
def get_latest_capture():
    """Get the latest camera capture from either SSD or SD card."""
    try:
        filename, full_path, serve_path = get_latest_capture_path()
        
        if not filename:
            return jsonify({'error': 'No captures available'}), 404
        
        # Construct the URL for the frontend
        url = f"{serve_path}/{filename}"
        
        # Try to get analysis from database for this filename
        capture = CameraCapture.query.filter_by(filename=filename).first()
        analysis = capture.analysis_result if capture else "0"
        
        return jsonify({
            'filename': filename,
            'url': url,
            'analysis': analysis,
            'timestamp': capture.timestamp.isoformat() if capture else None
        })
    except Exception as e:
        logger.error(f"Error fetching latest capture: {e}")
        return jsonify({'error': 'Failed to fetch latest capture'}), 500


@app.route('/captures/<filename>')
def serve_ssd_capture(filename):
    """Serve captures from SSD directory."""
    try:
        filepath = os.path.join(SSD_CAPTURE_DIRECTORY, filename)
        
        # Security check: ensure the file is within the allowed directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(SSD_CAPTURE_DIRECTORY)):
            return jsonify({'error': 'Access denied'}), 403
        
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(filepath, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Error serving capture: {e}")
        return jsonify({'error': 'Failed to serve file'}), 500


@app.route('/api/system/logs', methods=['GET'])
def get_system_logs():
    """Get system event logs with pagination."""
    try:
        limit = request.args.get('limit', DEFAULT_LOGS_LIMIT, type=int)
        limit = min(limit, 500)  # Prevent excessive queries
        
        logs = SystemLog.query.order_by(
            SystemLog.timestamp.desc()
        ).limit(limit).all()
        
        return jsonify([l.to_dict() for l in reversed(logs)])
    except Exception as e:
        logger.error(f"Error fetching system logs: {e}")
        return jsonify({'error': 'Failed to fetch logs'}), 500


@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all configuration settings."""
    try:
        from models import Setting
        settings = Setting.query.all()
        return jsonify({s.key: s.value for s in settings})
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        return jsonify({'error': 'Failed to fetch settings'}), 500


@app.route('/api/settings/<key>', methods=['GET', 'POST'])
def settings_endpoint(key):
    """Get or update a specific configuration setting."""
    try:
        if request.method == 'GET':
            value = Config.get(key)
            return jsonify({'key': key, 'value': value})
        
        elif request.method == 'POST':
            if not request.json or 'value' not in request.json:
                return jsonify({'error': 'Invalid request'}), 400
            
            new_value = request.json.get('value')
            Config.set(key, new_value)
            logger.info(f"Setting '{key}' updated to '{new_value}'")
            return jsonify({'status': 'ok', 'key': key, 'value': new_value})
    except Exception as e:
        logger.error(f"Error handling settings for {key}: {e}")
        logger.exception(e)
        return jsonify({'error': 'Failed to handle setting'}), 500


@app.route('/api/db/tables', methods=['GET'])
def list_db_tables():
    """List available database tables for the UI."""
    try:
        tables = {}
        for name, info in DB_TABLES.items():
            tables[name] = {
                'columns': info['columns'],
                'editable': info['editable'],
                'id_field': info['id_field']
            }
        return jsonify({'tables': tables})
    except Exception as e:
        logger.error(f"Error listing database tables: {e}")
        return jsonify({'error': 'Failed to list database tables'}), 500


@app.route('/api/db/<table_name>', methods=['GET'])
def get_db_table_rows(table_name):
    """Get rows for a database table with pagination."""
    info = DB_TABLES.get(table_name)
    if not info:
        return jsonify({'error': 'Unknown table'}), 404

    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        query = info['model'].query.order_by(info['order_by'])
        total = query.count()
        rows = query.offset(offset).limit(limit).all()

        def serialize_value(value):
            if isinstance(value, datetime.datetime):
                return value.isoformat(sep=' ', timespec='seconds')
            return value

        rows_payload = []
        for row in rows:
            row_data = {}
            for column in info['columns']:
                row_data[column] = serialize_value(getattr(row, column))
            rows_payload.append(row_data)

        return jsonify({
            'table': table_name,
            'columns': info['columns'],
            'editable': info['editable'],
            'id_field': info['id_field'],
            'rows': rows_payload,
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        logger.error(f"Error fetching database rows for {table_name}: {e}")
        return jsonify({'error': 'Failed to fetch database rows'}), 500


@app.route('/api/db/<table_name>/<row_id>', methods=['PATCH'])
def update_db_row(table_name, row_id):
    """Update a row in the selected database table."""
    info = DB_TABLES.get(table_name)
    if not info:
        return jsonify({'error': 'Unknown table'}), 404

    if not request.json:
        return jsonify({'error': 'Missing update payload'}), 400

    try:
        model = info['model']
        id_field = info['id_field']

        if id_field == 'id':
            try:
                row_id = int(row_id)
            except ValueError:
                return jsonify({'error': 'Invalid row id'}), 400

        row = model.query.get(row_id)
        if not row:
            return jsonify({'error': 'Row not found'}), 404

        updates = {k: v for k, v in request.json.items() if k in info['editable']}
        if not updates:
            return jsonify({'error': 'No editable fields provided'}), 400

        for field, value in updates.items():
            setattr(row, field, value)

        db.session.commit()
        return jsonify({'status': 'updated'})
    except Exception as e:
        logger.error(f"Error updating database row {table_name}/{row_id}: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update row'}), 500


@app.route('/api/db/<table_name>/<row_id>', methods=['DELETE'])
def delete_db_row(table_name, row_id):
    """Delete a row from the selected database table."""
    info = DB_TABLES.get(table_name)
    if not info:
        return jsonify({'error': 'Unknown table'}), 404

    try:
        model = info['model']
        id_field = info['id_field']

        if id_field == 'id':
            try:
                row_id = int(row_id)
            except ValueError:
                return jsonify({'error': 'Invalid row id'}), 400

        row = model.query.get(row_id)
        if not row:
            return jsonify({'error': 'Row not found'}), 404

        db.session.delete(row)
        db.session.commit()
        return jsonify({'status': 'deleted'})
    except Exception as e:
        logger.error(f"Error deleting database row {table_name}/{row_id}: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to delete row'}), 500


@app.route('/api/phase', methods=['GET', 'POST'])
def growth_phase():
    """Get or set the current growth phase."""
    try:
        if request.method == 'GET':
            phase = str(Config.get('growth_phase') or 'fruiting').strip().lower()
            return jsonify({'phase': phase, 'allowed': ['colonization', 'fruiting']})

        if not request.json or 'phase' not in request.json:
            return jsonify({'error': 'Missing phase parameter'}), 400

        phase = str(request.json.get('phase')).strip().lower()
        if phase not in ['colonization', 'fruiting']:
            return jsonify({'error': 'Invalid phase value'}), 400

        Config.set('growth_phase', phase)
        logger.info(f"Growth phase updated to '{phase}'")
        _restart_service_async()
        return jsonify({'status': 'restarting', 'phase': phase})

    except Exception as e:
        logger.error(f"Error handling growth phase: {e}")
        logger.exception(e)
        return jsonify({'error': 'Failed to handle growth phase'}), 500


@app.route('/api/relay/<int:relay_id>', methods=['GET', 'POST'])
def relay_control(relay_id):
    """Control individual relay - GET returns state, POST toggles it."""
    if relay_id not in [1, 2, 3]:
        return jsonify({'error': 'Invalid relay ID'}), 400
    
    try:
        if request.method == 'GET':
            state = relay_driver.get_state(relay_id)
            return jsonify({'relay_id': relay_id, 'state': state})
        
        # POST - set relay state
        if not request.json or 'state' not in request.json:
            return jsonify({'error': 'Missing state parameter'}), 400
        
        state = bool(request.json.get('state'))
        relay_driver.set_state(relay_id, state)
        logger.info(f"Manual relay control: Relay {relay_id} set to {'ON' if state else 'OFF'}")
        return jsonify({'relay_id': relay_id, 'state': state})
    
    except Exception as e:
        logger.error(f"Relay control error (relay {relay_id}): {e}")
        return jsonify({'error': 'Failed to control relay'}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'mode': 'mock' if USE_MOCK_HARDWARE else 'hardware',
        'background_running': task_manager.is_running()
    })


@app.route('/api/start', methods=['POST'])
def start_system():
    """Start background tasks."""
    try:
        task_manager.start()
        return jsonify({'status': 'started'})
    except Exception as e:
        logger.error(f"Error starting system: {e}")
        return jsonify({'error': 'Failed to start system'}), 500


@app.route('/api/stop', methods=['POST'])
def stop_system():
    """Stop background tasks."""
    try:
        task_manager.stop()
        return jsonify({'status': 'stopped'})
    except Exception as e:
        logger.error(f"Error stopping system: {e}")
        return jsonify({'error': 'Failed to stop system'}), 500


@app.route('/api/restart', methods=['POST'])
def restart_system():
    """Restart the gombabox systemd service."""
    try:
        _restart_service_async()
        return jsonify({'status': 'restarting'})
    except Exception as e:
        logger.error(f"Service restart error: {e}")
        logger.exception(e)
        return jsonify({'error': 'Failed to restart service'}), 500


@app.route('/api/camera/capture', methods=['POST'])
def capture_now():
    """Trigger manual camera capture."""
    try:
        from drivers.camera import RealCameraDriver, MockCameraDriver
        from core.vision import ImageAnalyzer
        
        # Use same camera driver as background task
        if USE_MOCK_HARDWARE:
            camera = MockCameraDriver()
        else:
            camera = RealCameraDriver()
        
        # Capture image
        lead_seconds = Config.get('camera_light_lead_seconds')
        try:
            lead_seconds = float(lead_seconds)
        except (TypeError, ValueError):
            lead_seconds = 0

        light_was_on = relay_driver.get_state(3)
        if not light_was_on:
            relay_driver.set_state(3, True)

        if lead_seconds > 0:
            time.sleep(lead_seconds)

        try:
            image_path = camera.capture_image()
        finally:
            if not light_was_on:
                relay_driver.set_state(3, False)
        
        if not image_path:
            return jsonify({'error': 'Failed to capture image'}), 500
        
        # Analyze coverage
        coverage_percent = ImageAnalyzer.calculate_mycelium_coverage(image_path)
        
        # Save to database
        import os
        filename = os.path.basename(image_path)
        capture = CameraCapture(
            filename=filename,
            analysis_result=f"{coverage_percent}%"
        )
        db.session.add(capture)
        db.session.commit()
        
        logger.info(f"Manual capture: {filename}, Coverage: {coverage_percent}%")
        
        return jsonify({
            'status': 'ok',
            'filename': filename,
            'coverage': coverage_percent,
            'path': f"/static/captures/{filename}"
        })
        
    except Exception as e:
        logger.error(f"Manual capture error: {e}")
        logger.exception(e)
        return jsonify({'error': 'Failed to capture image'}), 500


# Flask Application Startup
# Flask Application Startup

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        logger.info("Database initialized.")
    
    # Start background task manager
    task_manager.start()

    # Start database backup manager
    backup_manager.start()
    
    # Start Flask server
    logger.info(f"Starting Flask server on {API_HOST}:{API_PORT}")
    app.run(host=API_HOST, port=API_PORT, debug=API_DEBUG)