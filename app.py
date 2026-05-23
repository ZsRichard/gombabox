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
import shutil
import tempfile
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy

# Database
from models import db, Measurement, CameraCapture, SystemLog, Setting
from config import Config, DEFAULTS
from app_config import (
    DATABASE_URI, USE_MOCK_HARDWARE, API_HOST, API_PORT, API_DEBUG,
    DEFAULT_MEASUREMENTS_LIMIT,
    DEFAULT_CAPTURES_LIMIT, DEFAULT_LOGS_LIMIT, LOGGING_LEVEL,
    BACKUP_PRIMARY_PATH, BACKUP_FALLBACK_PATH, BACKUP_INTERVAL_HOURS
)

# Drivers
from drivers.relays import MockRelayDriver, RealRelayDriver
from drivers.sensors import MockSensorDriver, RealSensorDriver
from drivers.camera import MockCameraDriver, RealCameraDriver

# Core
from core.controller import MushroomController
from core.constants import get_latest_capture_path, SSD_CAPTURE_DIRECTORY, get_ssd_capture_directory

# Configure Flask
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Configure logging
logging.basicConfig(level=LOGGING_LEVEL)
logger = logging.getLogger(__name__)
ENGINE_TICK_SECONDS = 1

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

                time.sleep(ENGINE_TICK_SECONDS)


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
        primary_mount = os.path.dirname(BACKUP_PRIMARY_PATH.rstrip(os.sep))
        if os.path.ismount(primary_mount):
            try:
                os.makedirs(BACKUP_PRIMARY_PATH, exist_ok=True)
                if os.access(BACKUP_PRIMARY_PATH, os.W_OK):
                    return BACKUP_PRIMARY_PATH
                logger.warning("Primary backup path is mounted but not writable: %s", BACKUP_PRIMARY_PATH)
            except Exception as e:
                logger.warning("Cannot prepare primary backup path %s: %s", BACKUP_PRIMARY_PATH, e)

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


def _parse_client_datetime(value, field_name):
    """Parse datetime-local payload values from API clients."""
    if not value:
        raise ValueError(f"Missing '{field_name}' parameter")

    try:
        return datetime.datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"Invalid datetime for '{field_name}'") from exc


def _normalize_capture_directory(capture_dir):
    """Resolve and validate a user-supplied capture directory path."""
    if not capture_dir:
        return None

    resolved_dir = os.path.abspath(os.path.expanduser(str(capture_dir).strip()))
    if not os.path.isdir(resolved_dir):
        raise ValueError(f"Capture directory not found: {capture_dir}")

    return resolved_dir


def _capture_search_directories(preferred_dir=None):
    """Return ordered capture directories where images may exist."""
    directories = []

    if preferred_dir:
        directories.append(preferred_dir)

    ssd_capture_dir = get_ssd_capture_directory()
    if ssd_capture_dir:
        directories.append(ssd_capture_dir)

    sd_capture_dir = os.path.join(app.root_path, 'static', 'captures')
    directories.append(sd_capture_dir)

    return directories


def _resolve_capture_file_path(filename, preferred_dir=None):
    """Resolve capture filename to a real file path in SSD/SD capture stores."""
    for directory in _capture_search_directories(preferred_dir):
        candidate = os.path.join(directory, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def _collect_capture_paths(start_dt, end_dt, preferred_dir=None):
    """Collect capture file paths from DB metadata, with mtime fallback scan."""
    if preferred_dir:
        folder_candidates = []
        try:
            for filename in os.listdir(preferred_dir):
                if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue

                path = os.path.join(preferred_dir, filename)
                if not os.path.isfile(path):
                    continue

                mtime = os.path.getmtime(path)
                if start_dt.timestamp() <= mtime <= end_dt.timestamp():
                    folder_candidates.append((mtime, path))
        except Exception as scan_error:
            logger.warning("Capture directory scan failed for %s: %s", preferred_dir, scan_error)

        folder_candidates.sort(key=lambda item: item[0])
        if folder_candidates:
            return [path for _, path in folder_candidates]

    captures = CameraCapture.query.filter(
        CameraCapture.timestamp >= start_dt,
        CameraCapture.timestamp <= end_dt
    ).order_by(CameraCapture.timestamp.asc()).all()

    file_paths = []
    seen = set()

    for capture in captures:
        resolved_path = _resolve_capture_file_path(capture.filename, preferred_dir)
        if not resolved_path or resolved_path in seen:
            continue
        seen.add(resolved_path)
        file_paths.append(resolved_path)

    if file_paths:
        return file_paths

    # Fallback for captures not present in DB: scan directories by file modification time.
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()
    fallback_candidates = []

    for directory in _capture_search_directories(preferred_dir):
        if not os.path.isdir(directory):
            continue

        try:
            for filename in os.listdir(directory):
                if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue

                path = os.path.join(directory, filename)
                if not os.path.isfile(path):
                    continue

                mtime = os.path.getmtime(path)
                if start_ts <= mtime <= end_ts:
                    fallback_candidates.append((mtime, path))
        except Exception as scan_error:
            logger.warning("Capture directory scan failed for %s: %s", directory, scan_error)

    fallback_candidates.sort(key=lambda item: item[0])
    return [path for _, path in fallback_candidates]


def _probe_video_stats(video_path):
    """Return actual duration/frame metadata for a generated video when available."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe or not os.path.exists(video_path):
        return None


def _build_timelapse_scale_filter(max_width=1280):
    """Return an ffmpeg scale filter that preserves aspect ratio and avoids odd dimensions."""
    return f"scale='if(gt(iw,{max_width}),{max_width},iw)':-2"

    try:
        result = subprocess.run(
            [
                ffprobe,
                '-v', 'error',
                '-print_format', 'json',
                '-show_entries', 'format=duration:stream=nb_frames',
                video_path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0 or not result.stdout:
            return None

        import json
        payload = json.loads(result.stdout)
        duration = None
        frame_count = None

        format_info = payload.get('format') or {}
        if format_info.get('duration') is not None:
            try:
                duration = float(format_info['duration'])
            except (TypeError, ValueError):
                duration = None

        for stream in payload.get('streams', []) or []:
            nb_frames = stream.get('nb_frames')
            if nb_frames and nb_frames != 'N/A':
                try:
                    frame_count = int(nb_frames)
                    break
                except (TypeError, ValueError):
                    pass

        return {
            'duration_seconds': duration,
            'frame_count': frame_count
        }
    except Exception as e:
        logger.warning("Video probe failed for %s: %s", video_path, e)
        return None


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


@app.route('/manifest.webmanifest')
def pwa_manifest():
    """Serve web app manifest for PWA installability."""
    response = send_from_directory('static', 'manifest.webmanifest', mimetype='application/manifest+json')
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@app.route('/sw.js')
def pwa_service_worker():
    """Serve service worker from root scope for broad cache control."""
    response = send_from_directory('static/js', 'sw.js', mimetype='application/javascript')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


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
        active_ssd_capture_dir = get_ssd_capture_directory() or SSD_CAPTURE_DIRECTORY
        filepath = os.path.join(active_ssd_capture_dir, filename)
        
        # Security check: ensure the file is within the allowed directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(active_ssd_capture_dir)):
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
        # Remove deprecated key from DB to keep settings clean after migration.
        Setting.query.filter_by(key='co2_limit').delete()
        Setting.query.filter_by(key='service_cycle_interval_s').delete()
        Setting.query.filter_by(key='co2_auto_vent_interval_s').delete()
        Setting.query.filter_by(key='fan_cycle_on').delete()
        Setting.query.filter_by(key='fan_cycle_off').delete()
        db.session.commit()

        # Fill short descriptions for known setting rows.
        Config.ensure_descriptions()

        settings = {key: Config.get(key) for key in DEFAULTS.keys()}
        return jsonify(settings)
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        return jsonify({'error': 'Failed to fetch settings'}), 500


@app.route('/api/settings/descriptions', methods=['GET'])
def get_settings_descriptions():
    """Get short descriptions for known configuration settings."""
    try:
        Config.ensure_descriptions()
        descriptions = {key: (Config.get_description(key) or "") for key in DEFAULTS.keys()}
        return jsonify(descriptions)
    except Exception as e:
        logger.error(f"Error fetching setting descriptions: {e}")
        return jsonify({'error': 'Failed to fetch setting descriptions'}), 500


@app.route('/api/settings/<key>', methods=['GET', 'POST'])
def settings_endpoint(key):
    """Get or update a specific configuration setting."""
    try:
        if key not in DEFAULTS:
            return jsonify({'error': 'Unknown setting key'}), 404

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
        relay_driver.camera_capture_active = True
        if not light_was_on:
            relay_driver.set_state(3, True)

        if lead_seconds > 0:
            time.sleep(lead_seconds)

        try:
            image_path = camera.capture_image()
        finally:
            if not light_was_on:
                relay_driver.set_state(3, False)
            relay_driver.camera_capture_active = False
        
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


@app.route('/api/camera/timelapse', methods=['POST'])
def create_timelapse():
    """Create a timelapse video from captured images within a selected time range."""
    if not request.json:
        return jsonify({'error': 'Missing JSON payload'}), 400

    try:
        start_dt = _parse_client_datetime(request.json.get('start'), 'start')
        end_dt = _parse_client_datetime(request.json.get('end'), 'end')
        capture_dir = _normalize_capture_directory(request.json.get('capture_dir'))
    except ValueError as validation_error:
        return jsonify({'error': str(validation_error)}), 400

    if start_dt > end_dt:
        return jsonify({'error': 'Start time must be earlier than end time'}), 400

    fps = request.json.get('fps', 15)
    try:
        fps = int(fps)
    except (TypeError, ValueError):
        return jsonify({'error': 'FPS must be an integer'}), 400

    if fps < 1 or fps > 60:
        return jsonify({'error': 'FPS must be between 1 and 60'}), 400

    if not shutil.which('ffmpeg'):
        return jsonify({'error': 'ffmpeg is not installed on this system'}), 500

    try:
        db_capture_count = CameraCapture.query.filter(
            CameraCapture.timestamp >= start_dt,
            CameraCapture.timestamp <= end_dt
        ).count()

        image_paths = _collect_capture_paths(start_dt, end_dt, capture_dir)
        if len(image_paths) < 2:
            if db_capture_count >= 2:
                return jsonify({
                    'error': (
                        f"Found {db_capture_count} capture records in the selected range, "
                        f"but only {len(image_paths)} image files are currently accessible. "
                        "Your capture storage may be unmounted or the chosen folder does not match the source images."
                    ),
                    'db_capture_count': db_capture_count,
                    'accessible_file_count': len(image_paths),
                    'capture_dir': capture_dir
                }), 400

            return jsonify({
                'error': 'Not enough images in selected range (minimum 2)',
                'db_capture_count': db_capture_count,
                'accessible_file_count': len(image_paths),
                'capture_dir': capture_dir
            }), 400

        output_dir = os.path.join(app.root_path, 'static', 'exports', 'timelapses')
        os.makedirs(output_dir, exist_ok=True)

        timestamp_tag = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        output_name = f"timelapse_{timestamp_tag}.mp4"
        output_path = os.path.join(output_dir, output_name)

        with tempfile.TemporaryDirectory(prefix='gombabox_timelapse_') as temp_dir:
            for index, image_path in enumerate(image_paths, start=1):
                _, extension = os.path.splitext(image_path)
                link_name = os.path.join(temp_dir, f"frame_{index:06d}{extension.lower() or '.jpg'}")
                try:
                    os.symlink(image_path, link_name)
                except OSError:
                    shutil.copy2(image_path, link_name)

            ffmpeg_command = [
                'ffmpeg',
                '-y',
                '-framerate', str(fps),
                '-i', os.path.join(temp_dir, 'frame_%06d.jpg'),
                '-vf', _build_timelapse_scale_filter(1280),
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '28',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ]

            result = subprocess.run(
                ffmpeg_command,
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode != 0:
                logger.error("Timelapse ffmpeg failed: %s", result.stderr)
                return jsonify({'error': 'Timelapse generation failed. Check ffmpeg logs.'}), 500

        return jsonify({
            'status': 'ok',
            'video_url': f"/static/exports/timelapses/{output_name}",
            'frames': len(image_paths),
            'fps': fps,
            'duration_seconds': round(len(image_paths) / fps, 2),
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'capture_dir': capture_dir,
            'video_stats': _probe_video_stats(output_path)
        })
    except Exception as e:
        logger.error(f"Timelapse generation error: {e}")
        logger.exception(e)
        return jsonify({'error': 'Failed to create timelapse'}), 500


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