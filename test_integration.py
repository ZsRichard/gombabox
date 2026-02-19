#!/usr/bin/env python3
"""
Integration Test Suite for GombaBox
Tests: Database → Models → Drivers → Controller → API Routes
"""

import sys
import time
import logging
import json
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger("IntegrationTests")

print("\n" + "="*70)
print("GOMBABOX - COMPLETE INTEGRATION TEST SUITE")
print("="*70 + "\n")

# Test 1: Database Connectivity
print("[1/6] Testing Database Connectivity...")
try:
    from app import db, app
    with app.app_context():
        # Test database connection
        db.create_all()
        from models import Measurement, CameraCapture, Setting, SystemLog
        
        # Count records
        measurement_count = Measurement.query.count()
        logger.info(f"✓ Database connected. Measurements: {measurement_count}")
except Exception as e:
    logger.error(f"✗ Database error: {e}")
    sys.exit(1)

# Test 2: Configuration Management
print("\n[2/6] Testing Configuration System...")
try:
    with app.app_context():
        from config import Config
        
        # Test get with defaults
        target_temp = Config.get('target_temp')
        logger.info(f"✓ Config.get('target_temp') = {target_temp}")
        
        # Test set
        Config.set('target_temp', 25.0)
        verify_temp = Config.get('target_temp')
        assert abs(verify_temp - 25.0) < 0.1, "Config.set failed"
        logger.info(f"✓ Config.set/get working")
        
        # Reset to default
        Config.set('target_temp', 24.0)
except Exception as e:
    logger.error(f"✗ Configuration error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Sensor Driver (Mock)
print("\n[3/6] Testing Sensor System...")
try:
    from drivers.sensors import MockSensorDriver
    
    sensor = MockSensorDriver()
    readings = []
    for i in range(3):
        data = sensor.read_all()
        readings.append(data)
        logger.info(f"  Measurement {i+1}: {data}")
        time.sleep(0.5)
    
    # Verify data structure
    assert 'temp' in readings[0], "Missing 'temp' field"
    assert 'hum' in readings[0], "Missing 'hum' field"
    assert 'co2' in readings[0], "Missing 'co2' field"
    logger.info(f"✓ Sensor driver working, data structure valid")
except Exception as e:
    logger.error(f"✗ Sensor error: {e}")
    sys.exit(1)

# Test 4: Relay Driver (Mock)
print("\n[4/6] Testing Relay System...")
try:
    from drivers.relays import MockRelayDriver
    
    relays = MockRelayDriver()
    relay_names = {1: "Fan", 2: "Humidifier", 3: "Light"}
    
    for relay_id, name in relay_names.items():
        # Test turn on
        relays.set_state(relay_id, True)
        state = relays.get_state(relay_id)
        assert state == True, f"{name} failed to turn on"
        logger.info(f"  ✓ {name} ON")
        
        # Test turn off
        relays.set_state(relay_id, False)
        state = relays.get_state(relay_id)
        assert state == False, f"{name} failed to turn off"
        logger.info(f"  ✓ {name} OFF")
    
    logger.info(f"✓ Relay driver working")
except Exception as e:
    logger.error(f"✗ Relay error: {e}")
    sys.exit(1)

# Test 5: Camera & Image Analysis
print("\n[5/6] Testing Camera & Image Analysis...")
try:
    from drivers.camera import MockCameraDriver
    from core.vision import ImageAnalyzer
    
    camera = MockCameraDriver()
    image_path = camera.capture_image()
    logger.info(f"  Captured image: {image_path}")
    
    # Verify image was created
    assert Path(image_path).exists(), "Image file not created"
    
    # Analyze image
    coverage = ImageAnalyzer.calculate_mycelium_coverage(image_path)
    logger.info(f"  Mycelium coverage: {coverage}%")
    assert 0 <= coverage <= 100, "Coverage percentage out of range"
    
    logger.info(f"✓ Camera and image analysis working")
except Exception as e:
    logger.error(f"✗ Camera/Vision error: {e}")
    sys.exit(1)

# Test 6: Flask API Routes
print("\n[6/6] Testing Flask API Routes...")
try:
    with app.test_client() as client:
        # Test health endpoint
        resp = client.get('/api/health')
        assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
        data = json.loads(resp.data)
        assert 'status' in data, "Missing 'status' in health response"
        logger.info(f"  ✓ GET /api/health → {resp.status_code}")
        
        # Test measurements endpoint
        resp = client.get('/api/measurements?limit=10')
        assert resp.status_code == 200, f"Measurements failed: {resp.status_code}"
        logger.info(f"  ✓ GET /api/measurements → {resp.status_code}")
        
        # Test settings endpoint
        resp = client.get('/api/settings')
        assert resp.status_code == 200, f"Settings failed: {resp.status_code}"
        logger.info(f"  ✓ GET /api/settings → {resp.status_code}")
        
        # Test camera captures endpoint
        resp = client.get('/api/camera/captures?limit=5')
        assert resp.status_code == 200, f"Captures failed: {resp.status_code}"
        logger.info(f"  ✓ GET /api/camera/captures → {resp.status_code}")
        
        # Test logs endpoint
        resp = client.get('/api/system/logs?limit=10')
        assert resp.status_code == 200, f"Logs failed: {resp.status_code}"
        logger.info(f"  ✓ GET /api/system/logs → {resp.status_code}")
        
        # Test POST endpoints with error handling
        resp = client.post('/api/settings/target_temp', 
                          json={'value': 24.5},
                          content_type='application/json')
        assert resp.status_code == 200, f"Settings POST failed: {resp.status_code}"
        logger.info(f"  ✓ POST /api/settings/<key> → {resp.status_code}")
        
        logger.info(f"✓ All API routes working")
except Exception as e:
    logger.error(f"✗ API route error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*70)
print("✓ ALL INTEGRATION TESTS PASSED")
print("="*70)
print("\nBackend is ready for frontend development!")
print("\nNext steps:")
print("1. Create frontend dashboard with Bootstrap")
print("2. Implement real-time monitoring with Chart.js")
print("3. Add system administrator UI")
print("4. Deploy to Raspberry Pi\n")
