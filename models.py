from flask_sqlalchemy import SQLAlchemy
import datetime

# Database initialization using SQLAlchemy
# Enables dependency injection for improved testability and loose coupling
db = SQLAlchemy()

def init_db(app):
    """
    Initialize database with Flask application.
    Enables SQLAlchemy dependency injection pattern for better testability
    and reduced coupling between components.
    """
    db.init_app(app)
    with app.app_context():
        db.create_all()

class Measurement(db.Model):
    """Environmental sensor measurements (SRP: Data persistence only)."""
    __tablename__ = 'measurements'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now, index=True)  # Indexed for fast queries
    
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)
    co2 = db.Column(db.Integer, nullable=False)
    light = db.Column(db.Float, nullable=False)

    def to_dict(self):
        """Serialize measurement to JSON format for API responses."""
        return {
            'time': self.timestamp.strftime('%Y-%m-%d %H:%M'),
            'temp': self.temperature,
            'hum': self.humidity,
            'press': self.pressure,
            'co2': self.co2,
            'light': self.light
        }

class CameraCapture(db.Model):
    """Camera capture metadata (SRP: Track images in file system)."""
    __tablename__ = 'camera_captures'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now, index=True)
    filename = db.Column(db.String(120), nullable=False)
    
    analysis_result = db.Column(db.String(200), nullable=True)  # Future: Store mycelium coverage percentage

    def to_dict(self):
        return {
            'timestamp': self.timestamp.isoformat(),
            'url': f"/static/captures/{self.filename}",
            'analysis': self.analysis_result
        }

class Setting(db.Model):
    """Application configuration (OCP: Extensible without schema changes)."""
    __tablename__ = 'settings'
    
    key = db.Column(db.String(50), unique=True, nullable=False, primary_key=True)  # e.g., 'target_humidity'
    value = db.Column(db.String(50), nullable=False)  # e.g., '90'
    description = db.Column(db.String(100), nullable=True)  # e.g., 'Target humidity (%)'

    @staticmethod
    def get_value(key, default=None):
        """Retrieve setting value from database (KISS principle)."""
        setting = Setting.query.filter_by(key=key).first()
        return setting.value if setting else default

class SystemLog(db.Model):
    """System events and operational logs (SRP: Separated from measurements)."""
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