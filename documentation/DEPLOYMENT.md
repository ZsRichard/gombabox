# GombaBox - Complete Deployment Guide

## Table of Contents
1. [System Requirements](#system-requirements)
2. [Hardware Setup](#hardware-setup)
3. [Raspberry Pi Preparation](#raspberry-pi-preparation)
4. [Software Installation](#software-installation)
5. [Configuration](#configuration)
6. [Running the System](#running-the-system)
7. [Monitoring & Maintenance](#monitoring--maintenance)
8. [Troubleshooting](#troubleshooting)

---

## System Requirements

### Hardware
- **Controller**: Raspberry Pi 4/5 (4GB+ RAM recommended)
- **OS**: Raspberry Pi OS (Debian-based)
- **Storage**: 16GB+ microSD card
- **Power**: 5V/3A USB-C power supply

### Sensors
- BME280 (Temperature, Humidity, Pressure) - I2C @ 0x76
- BH1750 (Light Level) - I2C @ 0x23
- MH-Z19C (CO2 Level) - Serial @ /dev/serial0 (115200 baud)

### Actuators
- 8-channel 5V Relay Module
- Pin assignments (GPIO):
  - GPIO 27: Fan (Relay 1)
  - GPIO 17: Humidifier (Relay 2)
  - GPIO 22: LED Light (Relay 3)

### Network
- Internet connectivity for software updates
- Static IP recommended for production

---

## Hardware Setup

### I2C Sensor Wiring
```
Raspberry Pi I2C Bus (GPIO 2 & 3)
├── BME280
│   ├── VCC → 3.3V
│   ├── GND → GND
│   ├── SDA → GPIO 2 (I2C SDA)
│   └── SCL → GPIO 3 (I2C SCL)
├── BH1750
│   ├── VCC → 3.3V
│   ├── GND → GND
│   ├── SDA → GPIO 2
│   └── SCL → GPIO 3
```

### MH-Z19C Serial Configuration
```
Raspberry Pi UART (GPIO 14 & 15)
├── VCC → 5V
├── GND → GND
├── RX → GPIO 15 (UART TX)
└── TX → GPIO 14 (UART RX)

Enable via: raspi-config → Interfacing Options → Serial
Disable Serial Console, Enable Serial Port Hardware
```

### Relay Module Wiring
```
GPIO 27 → Relay 1 (Fan) → 5V Relay Input
GPIO 17 → Relay 2 (Humidifier) → 5V Relay Input
GPIO 22 → Relay 3 (LED Light) → 5V Relay Input
ALL    → GND (Common Ground)

Relay NC contacts connect to 220V AC devices
```

---

## Raspberry Pi Preparation

### Step 1: Update System
```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3-pip python3-dev python3-venv git
```

### Step 2: Enable I2C and Serial
```bash
sudo raspi-config
# Interfacing Options → I2C → Enable
# Interfacing Options → Serial → Enable Serial Hardware (Disable Serial Console)
# Reboot
```

### Step 3: Verify I2C Devices
```bash
sudo apt install -y i2c-tools
i2cdetect -y 1
# Should show:
# 0x23 (BH1750 Light Sensor)
# 0x76 (BME280 Temperature/Humidity)
```

### Step 4: Setup Git Repository
```bash
cd /home/pi
git clone https://github.com/yourusername/gombabox.git
cd gombabox
```

---

## Software Installation

### Step 1: Create Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Initialize Database
```bash
python3 -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### Step 4: Verify Installation
```bash
./venv/bin/python3 test_integration.py
# All tests should pass
```

---

## Configuration

### app_config.py (Already set for production)
```python
DATABASE_URI = 'sqlite:///gombabox.db'
USE_MOCK_HARDWARE = False              # Set to True for testing
API_HOST = '0.0.0.0'                   # Listen on all interfaces
API_PORT = 5000                        # Web interface port
BACKGROUND_CYCLE_INTERVAL = 60         # Sensor check every 60 seconds
DEFAULT_MEASUREMENTS_LIMIT = 100       # API default limit
DEFAULT_CAPTURES_LIMIT = 20            # API default limit
DEFAULT_LOGS_LIMIT = 50                # API default limit
LOGGING_LEVEL = logging.INFO           # Log level
```

### Environment Variables (Optional)
```bash
export GOMBABOX_DB_PATH=/var/lib/gombabox/gombabox.db
export GOMBABOX_MOCK_HARDWARE=false
export GOMBABOX_DEBUG=false
```

### System Settings (Database Configuration)
Access via API after system starts:
```bash
curl http://localhost:5000/api/settings
```

Available settings:
- `target_temp`: 24.0°C (float)
- `temp_hysteresis`: 1.0°C (float)
- `target_humidity`: 90.0% (float)
- `humidity_hysteresis`: 5.0% (float)
- `co2_pulse_threshold_ppm`: 800 ppm (int)
- `co2_pulse_duration_s`: 5 s (int)
- `co2_pulse_cooldown_s`: 90 s (int)
- `light_on_hour`: 8 (0-23 int)
- `light_off_hour`: 20 (0-23 int)

---

## Running the System

### Development Mode
```bash
cd /home/pi/gombabox
source venv/bin/activate
python3 app.py
# Access dashboard at http://raspberrypi.local:5000
```

### Production Mode (Systemd Service)

Create systemd service file:
```bash
sudo nano /etc/systemd/system/gombabox.service
```

```ini
[Unit]
Description=GombaBox Mushroom Growing System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/gombabox
ExecStart=/home/pi/gombabox/venv/bin/python3 /home/pi/gombabox/app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable gombabox
sudo systemctl start gombabox
sudo systemctl status gombabox
```

## Monitoring & Maintenance

### View Logs
```bash
# Systemd logs
sudo journalctl -u gombabox -f

# Application logs
curl http://localhost:5000/api/system/logs

# Database query
sqlite3 gombabox.db "SELECT * FROM system_log ORDER BY timestamp DESC LIMIT 20;"
```

### Backup Database
```bash
# Daily backup
0 2 * * * cp /home/pi/gombabox/gombabox.db /backup/gombabox_$(date +\%Y\%m\%d).db
```

### Monitor System Health
```bash
# Check if running
systemctl is-active gombabox

# Resource usage
ps aux | grep python3 | grep app.py

# Disk space
df -h /home/pi/gombabox

# Database size
ls -lh /home/pi/gombabox/gombabox.db
```

---

## Troubleshooting

### I2C Sensors Not Detected
```bash
# Check I2C bus
i2cdetect -y 1

# Debug address detection
# BME280 should be at 0x76, BH1750 at 0x23
# If missing, check wiring and power
```

### Serial Port Access Error
```bash
# Add user to dialout group
sudo usermod -a -G dialout pi
# Log out and back in
```

### Relay Not Working
```bash
# Test GPIO manually
python3 << 'EOF'
from gpiozero import OutputDevice
relay = OutputDevice(27)  # GPIO 27
relay.on()   # Should hear click
relay.off()  # Should hear click
EOF
```

### Web Interface Not Loading
```bash
# Check Flask is running
curl http://localhost:5000/api/health

# Check templates exist
ls -la templates/

# Check permissions
ls -la static/
ls -la templates/
```

### Database Locked Error
```bash
# Kill any hung processes
ps aux | grep python3
kill -9 <PID>

# Reset database
rm gombabox.db
python3 -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### System Freezing/High CPU
```bash
# Check for infinite loops
top -p $(pgrep -f app.py)

# Restart service
sudo systemctl restart gombabox

# Check logs for errors
sudo journalctl -u gombabox -n 50 --priority err
```

---

## API Endpoints Reference

### Health & Status
- `GET /api/health` - System status
- `GET /api/system/logs` - System logs

### Sensor Data
- `GET /api/measurements` - Historical measurements
- `GET /api/measurements/latest` - Latest reading

### Camera
- `GET /api/camera/captures` - Historical captures
- `GET /api/camera/captures/<id>` - Specific capture

### Configuration
- `GET /api/settings` - All settings
- `GET /api/settings/<key>` - Specific setting
- `POST /api/settings/<key>` - Update setting

### Control
- `GET /api/relay/<id>` - Relay state
- `POST /api/relay/<id>` - Toggle relay
- `POST /api/start` - Start system
- `POST /api/stop` - Stop system

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Sensors report 0 | I2C not enabled | Run `raspi-config` → Enable I2C |
| "Motor" spins without permission | GPIO permissions | Add user to gpio group: `sudo usermod -a -G gpio pi` |
| Database locked error | Multiple processes | Kill hanging Python processes |
| Web interface slow | High database queries | Clean old measurements: keep recent only |
| WiFi disconnects | OS power saving | Disable WiFi power saving in dhcpcd.conf |

---

## Next Steps

1. ✅ **Validate Hardware Integration** - All sensors communicate
2. ✅ **Test Control Cycles** - Relays respond correctly
3. ✅ **Monitor Environmental Control** - Humidity/temp/CO2 regulated
4. ⊕ **Train on System Operation** - Understand thresholds
5. ⊕ **Optimize Growing Parameters** - Fine-tune for your climate
6. ⊕ **Create Backup Strategy** - Daily database backups
7. ⊕ **Plan Maintenance** - Clean sensors monthly

---

**For Support**: Check system logs and review API responses. All errors are logged with timestamps.
