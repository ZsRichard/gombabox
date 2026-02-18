import logging

# Próbáljuk importálni a hardveres könyvtárat.
# Ha nincs (pl. a laptopodon fejleszted), nem omlik össze, csak jelzi.
try:
    from gpiozero import OutputDevice
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

logger = logging.getLogger(__name__)

class RelayDriver:
    """
    Ez az 'Absztrakt' ősosztály vagy Interfész.
    Meghatározza, mit KELL tudnia egy relé vezérlőnek.
    """
    def set_state(self, relay_id, state):
        raise NotImplementedError

    def get_state(self, relay_id):
        raise NotImplementedError

class RealRelayDriver(RelayDriver):
    """
    A VALÓDI hardver vezérlője.
    Csak akkor használd, ha a Raspberry Pi-n futsz.
    """
    def __init__(self):
        if not GPIO_AVAILABLE:
            raise RuntimeError("GPIO könyvtár nem elérhető! Használd a Mock drivert.")
        
        # Hardveres bekötés (Configból is jöhetne, de KISS: itt fixáljuk)
        # PIN kiosztás a korábbi beszélgetésünk alapján:
        self.devices = {
            1: OutputDevice(27, active_high=False, initial_value=False), # Venti
            2: OutputDevice(17, active_high=False, initial_value=False), # Párásító
            3: OutputDevice(22, active_high=False, initial_value=False)  # LED
        }
        logger.info("✅ RealRelayDriver inicializálva (GPIO módban).")

    def set_state(self, relay_id, state):
        if relay_id in self.devices:
            device = self.devices[relay_id]
            if state:
                device.on()
            else:
                device.off()
            # Itt nem logolunk minden kapcsolást, azt a Business Layer végzi majd (SRP).
            
    def get_state(self, relay_id):
        if relay_id in self.devices:
            return bool(self.devices[relay_id].value)
        return False

class MockRelayDriver(RelayDriver):
    """
    A SZIMULÁLT vezérlő (Teszt Dublőr)[cite: 781].
    Távollétben és fejlesztéshez ezt használjuk.
    """
    def __init__(self):
        # Memóriában tároljuk az állapotot
        self.states = {1: False, 2: False, 3: False}
        logger.info("⚠️ MockRelayDriver inicializálva (Szimulációs mód).")

    def set_state(self, relay_id, state):
        if relay_id in self.states:
            self.states[relay_id] = state
            # Konzolra írjuk, hogy lásd a működést fejlesztés közben
            print(f"   [MOCK HARDWARE] Relé {relay_id} -> {'BE' if state else 'KI'}")

    def get_state(self, relay_id):
        return self.states.get(relay_id, False)