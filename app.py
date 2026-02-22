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
from flask import Flask, jsonify, render_template, request, send_file
from flask_sqlalchemy import SQLAlchemy

# Database
from models import db, Measurement, CameraCapture, SystemLog
from config import Config
from app_config import (
    DATABASE_URI, USE_MOCK_HARDWARE, API_HOST, API_PORT, API_DEBUG,
    BACKGROUND_CYCLE_INTERVAL, DEFAULT_MEASUREMENTS_LIMIT,
    DEFAULT_CAPTURES_LIMIT, DEFAULT_LOGS_LIMIT, LOGGING_LEVEL
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
    
    # Start Flask server
    logger.info(f"Starting Flask server on {API_HOST}:{API_PORT}")
    app.run(host=API_HOST, port=API_PORT, debug=API_DEBUG)