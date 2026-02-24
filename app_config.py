# Application Configuration Constants
# Following Clean Code principles: DRY, meaningful names, no magic numbers

# Database Configuration  
DATABASE_URI = 'sqlite:///gombabox.db'

# Hardware Mode (True = simulation, False = real hardware)
USE_MOCK_HARDWARE = False

# Application Ports and Hosts
API_HOST = '0.0.0.0'
API_PORT = 5000
API_DEBUG = False

# Background Thread
BACKGROUND_CYCLE_INTERVAL = 60  # seconds

# API Pagination Defaults
DEFAULT_MEASUREMENTS_LIMIT = 100
DEFAULT_CAPTURES_LIMIT = 20
DEFAULT_LOGS_LIMIT = 50

# Logging Configuration
LOGGING_LEVEL = 'INFO'

# Database Backup Configuration
BACKUP_PRIMARY_PATH = '/media/richard/GOMBABOX/Database_backup'
BACKUP_FALLBACK_PATH = '/static/Database_backup'
BACKUP_INTERVAL_HOURS = 24
