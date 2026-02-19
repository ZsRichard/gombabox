import logging

# Try to import the hardware library.
# If not available (e.g., developing on a laptop), it won't crash, just a flag.
try:
    from gpiozero import OutputDevice
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

logger = logging.getLogger(__name__)

class RelayDriver:
    """
    Abstract base class or interface.
    Defines what a relay controller must be able to do.
    """
    def set_state(self, relay_id, state):
        raise NotImplementedError

    def get_state(self, relay_id):
        raise NotImplementedError

class RealRelayDriver(RelayDriver):
    """
    Real hardware controller.
    Use this only if running on a Raspberry Pi.
    """
    def __init__(self):
        if not GPIO_AVAILABLE:
            raise RuntimeError("GPIO library not available! Use Mock driver instead.")
        
        # Hardware connection (could come from Config, but KISS: fixed here)
        # PIN assignments from previous conversation:
        self.devices = {
            1: OutputDevice(27, active_high=False, initial_value=False), # Fan
            2: OutputDevice(17, active_high=False, initial_value=False), # Humidifier
            3: OutputDevice(22, active_high=False, initial_value=False)  # Light
        }
        logger.info("RealRelayDriver initialized (GPIO mode).")

    def set_state(self, relay_id, state):
        if relay_id in self.devices:
            device = self.devices[relay_id]
            if state:
                device.on()
            else:
                device.off()
            # We don't log every switch here; Business Layer handles that (SRP).
            
    def get_state(self, relay_id):
        if relay_id in self.devices:
            return bool(self.devices[relay_id].value)
        return False

class MockRelayDriver(RelayDriver):
    """
    Mock/simulated controller (Test Double pattern).
    Used for absence and development.
    """
    def __init__(self):
        # Store state in memory
        self.states = {1: False, 2: False, 3: False}
        logger.info("MockRelayDriver initialized (Simulation mode).")

    def set_state(self, relay_id, state):
        if relay_id in self.states:
            self.states[relay_id] = state
            # Print to console so you can see it working during development
            print(f"   [MOCK HARDWARE] Relay {relay_id} -> {'ON' if state else 'OFF'}")

    def get_state(self, relay_id):
        return self.states.get(relay_id, False)