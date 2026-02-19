# app.py - GombaBox Raspberry Pi Szenzoradatok és Képelemzés

import os
import time
import logging
import threading
from flask import Flask, jsonify, render_template, request
from flask_sqlalchemy import SQLAlchemy

# Database
from models import db, Measurement, CameraCapture, SystemLog
from config import Config

# Driverek
from drivers.relays import MockRelayDriver, RealRelayDriver
from drivers.sensors import MockSensorDriver, RealSensorDriver
from drivers.camera import MockCameraDriver, RealCameraDriver

# Vezérlő
from core.controller import MushroomController

# --- KONFIGURÁCIÓ ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gombabox.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Database inicializálása
db.init_app(app)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- HARDVER MÓD ---
# Fejlesztéskor: True, Élesben: False
USE_MOCK_HARDWARE = False

# --- HÁTTÉRSZÁL VEZÉRLŐ ---
background_thread = None
background_running = False

def background_loop():
    """
    Háttérszál fő ciklusa.
    - Szenzor mérések: percenként
    - Vizuális ellenőrzés: óránként
    """
    global background_running
    background_running = True
    
    logger.info("🚀 Háttérszál indítása...")
    
    with app.app_context():
        # 1. Driverek kiválasztása (Dependency Injection)
        if USE_MOCK_HARDWARE:
            logger.info("⚠️ SZIMULÁCIÓS MÓD AKTÍV")
            sensors = MockSensorDriver()
            relays = MockRelayDriver()
            camera = MockCameraDriver()
        else:
            logger.info("⚡ ÉLES ÜZEMMÓD")
            sensors = RealSensorDriver()
            relays = RealRelayDriver()
            camera = RealCameraDriver()

        # 2. Controller létrehozása
        controller = MushroomController(sensors, relays, camera, db.session)

        # 3. Végtelen ciklus
        while background_running:
            try:
                # Fő metódus: szenzor mérés + vezérlés
                controller.run_cycle()
            except Exception as e:
                logger.error(f"🔥 KRITIKUS HIBA: {e}")
                logger.exception(e)
            
            # Várakozás 60 másodperc (1 perc)
            time.sleep(60)

def start_background_loop():
    """Elindítja a háttérszálat."""
    global background_thread
    if background_thread is None or not background_thread.is_alive():
        background_thread = threading.Thread(target=background_loop, daemon=True)
        background_thread.start()
        logger.info("✅ Háttérszál elindult.")

def stop_background_loop():
    """Megállítja a háttérszálat."""
    global background_running
    background_running = False
    logger.info("🛑 Háttérszál megállítva.")

# --- REST API ÚTVONALAK ---

@app.route('/')
def index():
    """Web UI (index.html)"""
    return render_template('index.html')

@app.route('/api/measurements', methods=['GET'])
def get_measurements():
    """Utolsó mérések (default: utolsó 100 darab)"""
    limit = request.args.get('limit', 100, type=int)
    measurements = Measurement.query.order_by(Measurement.timestamp.desc()).limit(limit).all()
    return jsonify([m.to_dict() for m in reversed(measurements)])

@app.route('/api/measurements/latest', methods=['GET'])
def get_latest_measurement():
    """Legutolsó mérés"""
    measurement = Measurement.query.order_by(Measurement.timestamp.desc()).first()
    return jsonify(measurement.to_dict() if measurement else {})

@app.route('/api/camera/captures', methods=['GET'])
def get_camera_captures():
    """Képek listája (utolsó 20)"""
    limit = request.args.get('limit', 20, type=int)
    captures = CameraCapture.query.order_by(CameraCapture.timestamp.desc()).limit(limit).all()
    return jsonify([c.to_dict() for c in reversed(captures)])

@app.route('/api/system/logs', methods=['GET'])
def get_system_logs():
    """Rendszer naplók (utolsó 50)"""
    limit = request.args.get('limit', 50, type=int)
    logs = SystemLog.query.order_by(SystemLog.timestamp.desc()).limit(limit).all()
    return jsonify([l.to_dict() for l in reversed(logs)])

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Összes beállítás"""
    from models import Setting
    settings = Setting.query.all()
    return jsonify({s.key: s.value for s in settings})

@app.route('/api/settings/<key>', methods=['GET', 'POST'])
def settings_endpoint(key):
    """Egyetlen beállítás lekérdezése vagy módosítása"""
    if request.method == 'GET':
        value = Config.get(key)
        return jsonify({'key': key, 'value': value})
    
    elif request.method == 'POST':
        data = request.json
        Config.set(key, data.get('value'))
        return jsonify({'status': 'ok', 'key': key, 'value': data.get('value')})

@app.route('/api/relay/<int:relay_id>', methods=['GET', 'POST'])
def relay_control(relay_id):
    """Relé vezérlés"""
    # TODO: Valós relay interface
    return jsonify({'relay_id': relay_id, 'status': 'ok'})

@app.route('/api/health', methods=['GET'])
def health_check():
    """Zdravotnosť check"""
    return jsonify({
        'status': 'ok',
        'mode': 'mock' if USE_MOCK_HARDWARE else 'hardware',
        'background_running': background_running
    })

@app.route('/api/start', methods=['POST'])
def start_system():
    """Rendszer indítása"""
    start_background_loop()
    return jsonify({'status': 'started'})

@app.route('/api/stop', methods=['POST'])
def stop_system():
    """Rendszer leállítása"""
    stop_background_loop()
    return jsonify({'status': 'stopped'})

# --- Flask ALKALMAZÁS FUTTATÁSA ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        logger.info("✅ Adatbázis inicializálva.")
    
    # Háttérszál indítása
    start_background_loop()
    
    # Flask szerver indítása (0.0.0.0 - IPv6 támogatás nélkül)
    app.run(host='0.0.0.0', port=5000, debug=False)