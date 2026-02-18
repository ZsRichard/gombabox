from flask_sqlalchemy import SQLAlchemy
import datetime

# Inicializálás (Dependency Injection előkészítése)
db = SQLAlchemy()

def init_db(app):
    """
    Az adatbázis inicializálása az alkalmazáshoz.
    Ez lehetővé teszi a 'db' objektum befecskendezését (Dependency Injection),
    növelve a tesztelhetőséget és csökkentve a csatoltságot.
    """
    db.init_app(app)
    with app.app_context():
        db.create_all()

# --- 1. MÉRÉSEK (Szenzor adat) ---
# SRP: Csak a környezeti változók tárolása.
class Measurement(db.Model):
    __tablename__ = 'measurements'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now, index=True) # Indexelés a gyors lekérdezésért
    
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)
    co2 = db.Column(db.Integer, nullable=False)
    light = db.Column(db.Float, nullable=False)

    def to_dict(self):
        """Segédfüggvény a JSON konverzióhoz (API)"""
        return {
            'time': self.timestamp.strftime('%Y-%m-%d %H:%M'),
            'temp': self.temperature,
            'hum': self.humidity,
            'press': self.pressure,
            'co2': self.co2,
            'light': self.light
        }

# --- 2. KAMERA (Képek metaadatai) ---
# SRP: A fájlrendszerben lévő képek nyilvántartása.
class CameraCapture(db.Model):
    __tablename__ = 'camera_captures'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now, index=True)
    filename = db.Column(db.String(120), nullable=False)
    
    # Opcionális: Később, ha akarod elemezni a képet (pl. "80% átszőtt"), ide írhatod.
    # YAGNI: Most még nem kell bonyolult elemző modul, csak egy hely az adatnak.
    analysis_result = db.Column(db.String(200), nullable=True)

    def to_dict(self):
        return {
            'timestamp': self.timestamp.isoformat(),
            'url': f"/static/captures/{self.filename}",
            'analysis': self.analysis_result
        }

# --- 3. BEÁLLÍTÁSOK (Konfiguráció) ---
# OCP: Új beállítások hozzáadása nem igényli a kódbázis (táblaszerkezet) módosítását.
# KISS: Egyszerű Kulcs-Érték pár (Key-Value pair).
class Settings(db.Model):
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)  # pl. "target_humidity"
    value = db.Column(db.String(50), nullable=False)             # pl. "90"
    description = db.Column(db.String(100), nullable=True)       # pl. "Cél páratartalom (%)"

    @staticmethod
    def get_value(key, default=None):
        """Segédfüggvény a könnyű lekérdezéshez (KISS)"""
        setting = Settings.query.filter_by(key=key).first()
        return setting.value if setting else default

# --- 4. RENDSZER NAPLÓ (Log) ---
# SRP: A működési események elválasztása a mért adatoktól.
class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now, index=True)
    level = db.Column(db.String(10), default="INFO")  # INFO, WARNING, ERROR
    message = db.Column(db.String(200), nullable=False)
    
    def to_dict(self):
        return {
            'time': self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'level': self.level,
            'message': self.message
        }