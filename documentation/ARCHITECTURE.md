# GombaBox Architecture & Development Roadmap

## Project Overview
**Automated Oyster Mushroom Growing System** with AI-powered mycelium coverage monitoring via Raspberry Pi.

### Hardware Stack
- **Controller**: Raspberry Pi 4/5
- **Sensors**: 
  - BME280 (Temperature, Humidity, Pressure)
  - BH1750 (Light Level)
  - MH-Z19C (CO2 Level via Serial)
  - Pi Camera V3 (top-down mycelium monitoring)
- **Actuators**: 
  - 8-channel 5V relay board
  - Ventilation fan (GPIO 27)
  - Humidifier (GPIO 17)
  - LED strip (GPIO 22)

### Software Stack
```
Frontend: HTML + Bootstrap + JavaScript (Chart.js)
    ↓
Backend: Flask REST API
    ↓
Business Logic: MushroomController (60-second cycle)
    ↓
Drivers: Sensor/Relay/Camera (Dependency Injection)
    ↓
Database: SQLite + SQLAlchemy ORM
    ↓
Task Scheduler: APScheduler (background processes)
```

## Architecture Principles

### SOLID Principles Applied
1. **SRP** (Single Responsibility): Each class has one reason to change
   - MushroomController: Decision logic only
   - SensorDriver: Hardware abstraction
   - RelayDriver: Actuator controls
   - ImageAnalyzer: Image processing only

2. **OCP** (Open/Closed): Open for extension, closed for modification
   - Mock drivers substitute Real drivers without code changes
   - New sensor types add to Driver interface

3. **LSP** (Liskov Substitution): Derived classes substitute base classes
   - RealSensorDriver/MockSensorDriver interchangeable
   - RealCameraDriver/MockCameraDriver interchangeable

4. **ISP** (Interface Segregation): Clients depend on specific abstractions
   - SensorDriver interface (read measurements)
   - RelayDriver interface (on/off control)
   - CameraDriver interface (capture image)

5. **DIP** (Dependency Inversion): Depend on abstractions, not concretions
   - All drivers injected via constructor
   - No global dependencies

### Clean Code Principles Implemented
- ✅ Meaningful names (Config.get() not Config.g())
- ✅ Functions do one thing (run_sensor_cycle, _control_humidity)
- ✅ No magic numbers (app_config.py constants)
- ✅ Error handling on all API routes
- ✅ English documentation throughout
- ✅ DRY compliance (extracted BackgroundTaskManager)

## Current Project Status

### ✅ Completed
- Database schema (4 models: Measurement, CameraCapture, Setting, SystemLog)
- Sensor integration (I2C + serial with fallback)
- Camera support (rpicam with mock fallback)
- Relay control (GPIO with gpiozero)
- Flask app with BackgroundTaskManager
- API routes with error handling
- Configuration constants extracted
- All code converted to English

### 🔄 In Progress
- API endpoint testing
- Frontend dashboard

### ❌ Not Started
- Real-time monitoring UI
- Database migrations
- Deployment scripts

## Development Phases

### Phase 1: Stabilize Backend
- [ ] Unit test all drivers
- [ ] Integration test sensor lifecycle
- [ ] Validate database persistence
- [ ] Test background task cycling

### Phase 2: Build Frontend
- [ ] Create dashboard HTML
- [ ] Implement real-time graphs (Chart.js)
- [ ] Add settings management UI
- [ ] Display system logs

### Phase 3: Production Ready
- [ ] Add authentication
- [ ] Performance optimization
- [ ] Deployment automation
- [ ] Documentation complete

## Testing Strategy

### Unit Tests
- Test each driver independently
- Mock external dependencies
- Validate calculations (mycelium coverage)

### Integration Tests
- Backend + Database
- Sensor cycle → Database persistence
- API endpoints → Response validation

### System Tests
- Hardware validation (actual sensors)
- Full cycle: measure → decide → actuate
- Frontend interaction end-to-end

## Directory Structure
```
gombabox/
├── app.py                 # Flask application
├── models.py              # SQLAlchemy ORM models
├── config.py              # Configuration management
├── app_config.py          # Constants (DRY)
├── core/
│   ├── __init__.py
│   ├── constants.py       # Color thresholds, paths
│   ├── controller.py      # Main control logic
│   └── vision.py          # Image analysis (mycelium)
├── drivers/
│   ├── __init__.py
│   ├── sensors.py         # I2C & serial sensor reading
│   ├── relays.py          # GPIO relay control
│   └── camera.py          # Pi camera capture
├── static/
│   ├── css/               # Bootstrap styles
│   ├── js/                # Chart.js, interactions
│   └── captures/          # Saved images
├── templates/
│   ├── dashboard.html     # Main UI
│   ├── settings.html      # Configuration page
│   └── logs.html          # System log viewer
├── venv/                  # Python virtual environment
├── test_hardware.py       # Hardware diagnostics
├── requirements.txt       # Dependencies
└── ARCHITECTURE.md        # This file
```

## Key Algorithms

### Mycelium Coverage Detection
1. Load captured image (Pillow)
2. Convert to RGB color space
3. Detect white pixels: grayscale > 180, saturation < 0.2
4. Calculate: (white_pixels / total_pixels) × 100%
5. Store result as CameraCapture.analysis_result

### Environmental Control Cycles
**60-second main cycle:**
- Every minute: Sensor reading → Database → Control decisions → Relay actuation
- Every 60 minutes: Visual inspection (capture image → analyze → store)

**Control Decisions (Hysteresis-based):**
- Humidity: Hysteresis ±5% around target
- Temperature: Hysteresis ±1°C (future enhancement)
- Light: Timer-based (on/off hours)
- CO2: Hysteresis ±200 ppm (ventilation)

## Clean Code Checklist

- [x] All names meaningful and searchable
- [x] Functions small and focused
- [x] Comments explain "why" not "what"
- [x] No magic numbers (constants file)
- [x] Error handling comprehensive
- [x] DRY principle enforced
- [x] SOLID principles applied
- [x] Code localized to English
- [ ] Unit tests comprehensive
- [ ] Integration tests complete
- [ ] API documentation complete

## Next Immediate Actions

1. **Run integration tests** - Verify sensor→DB→relay flow
2. **Build frontend dashboard** - Bootstrap + Chart.js
3. **Add unit test suite** - pytest for all drivers
4. **Create deployment guide** - Setup for production Pi
