# GombaBox - Quick Start Guide

## 5-Minute Setup (Development/Testing)

### Prerequisites
- Raspberry Pi with Python 3.9+
- I2C, Serial, and GPIO enabled
- Git installed

### Quick Setup
```bash
# Clone repository
git clone https://github.com/yourusername/gombabox.git
cd gombabox

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Initialize database
python3 -c "from app import app, db; app.app_context().push(); db.create_all()"

# Run application
python3 app.py
```

Access dashboard: `http://raspberrypi.local:5000`

---

## Testing with Mock Hardware

For development without real sensors:

```python
# Automatically detects if real hardware is available
# Falls back to MockSensorDriver if I2C/Serial unavailable
# See app_config.py to override: USE_MOCK_HARDWARE = True
```

Run integration tests:
```bash
python3 test_integration.py
# Should see: ✓ ALL INTEGRATION TESTS PASSED
```

---

## Configuration Quick Reference

### Change Default Targets
```bash
curl -X POST http://localhost:5000/api/settings/target_humidity \
  -H "Content-Type: application/json" \
  -d '{"value": 85.0}'

curl -X POST http://localhost:5000/api/settings/target_temp \
  -H "Content-Type: application/json" \
  -d '{"value": 22.0}'
```

### Check System Status
```bash
curl http://localhost:5000/api/health
curl http://localhost:5000/api/measurements/latest
curl http://localhost:5000/api/system/logs
```

### Control Relays Manually
```bash
# Turn On (set state=1 or true)
curl -X POST http://localhost:5000/api/relay/1 \
  -H "Content-Type: application/json" \
  -d '{"state": true}'

# Turn Off
curl -X POST http://localhost:5000/api/relay/1 \
  -H "Content-Type: application/json" \
  -d '{"state": false}'
```

---

## Dashboard Features

### Real-Time Monitoring
- Live temperature, humidity, CO2, light readings
- Historical graphs (temperature, humidity, CO2, light, mycelium coverage)
- Latest image capture with mycelium analysis

### Controls
- Manual relay on/off switching
- System start/stop buttons
- Direct configuration of all settings

### Logging
- Real-time system events
- Error tracking
- Audit trail of all changes

---

## File Structure Reference

```
gombabox/
├── app.py                    # Flask application entry point
├── models.py                 # Database models (SQLAlchemy)
├── config.py                 # Configuration management
├── app_config.py             # Constants (DRY)
│
├── core/
│   ├── constants.py          # Color thresholds, paths
│   ├── controller.py         # Main control logic (CLEAN CODE)
│   └── vision.py             # Image analysis (Mycelium detection)
│
├── drivers/
│   ├── sensors.py            # Sensor abstraction + Mock fallback
│   ├── relays.py             # Relay control
│   └── camera.py             # Camera capture
│
├── templates/
│   └── dashboard.html        # Bootstrap UI
│
├── static/
│   ├── js/
│   │   └── dashboard.js      # Frontend logic (Chart.js)
│   └── captures/             # Saved images
│
├── test_integration.py       # Integration test suite
├── test_hardware.py          # Hardware diagnostics
│
├── ARCHITECTURE.md           # System design (SOLID principles)
├── DEPLOYMENT.md             # Production deployment guide
└── requirements.txt          # Python dependencies
```

---

## Typical Operating Cycle

1. **Every 60 seconds** (background task):
   - Read all sensors (temp, humidity, pressure, CO2, light)
   - Save measurements to database
   - Apply control logic:
     - Adjust humidifier based on humidity
     - Control light based on time schedule
     - Manage ventilation based on CO2 level
   - Log any events

2. **Every 60 minutes** (visual inspection):
   - Capture image from camera
   - Analyze mycelium coverage percentage
   - Store results in database

3. **Web Interface** (real-time):
   - Display latest readings
   - Show 20-point history graphs
   - Allow manual relay control
   - Display system logs

---

## Clean Code Principles Applied

✅ **SOLID**
- SRP: Each driver has one responsibility
- OCP: New sensor types extend cleanly
- LSP: Mock drivers substitute real ones
- ISP: Specific interfaces, not bloated ones
- DIP: All dependencies injected

✅ **Clean Code**
- Meaningful names (not abbreviations)
- Small, focused functions
- No magic numbers (app_config.py)
- Comprehensive error handling
- English documentation
- DRY compliance (BackgroundTaskManager)

✅ **Testing**
- Integration test suite
- Mock drivers for offline development
- API endpoint validation
- Hardware diagnostics

---

## Troubleshooting

**System won't start?**
```bash
# Check for Python errors
python3 app.py

# Check database
sqlite3 gombabox.db ".tables"

# Run tests
python3 test_integration.py
```

**Sensors not reading?**
```bash
# Check I2C
i2cdetect -y 1

# Check device permissions
ls -la /dev/ttyUSB* /dev/ttyAMA*
sudo usermod -a -G dialout $USER
```

**Web interface slow?**
```bash
# Check database size
du -h gombabox.db

# Check for errors
sqlite3 gombabox.db "VACUUM;"
```

---

## Next Steps

1. Verify all sensors work correctly
2. Configure target humidity/temperature for your mushroom species
3. Test relay actuation manually
4. Let system run for 24 hours to establish baseline
5. Fine-tune control thresholds based on observations
6. Set up daily database backups

**Happy growing! 🍄**
