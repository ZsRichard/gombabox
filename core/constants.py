# Color thresholds needed for mycelium recognition (HSV color space)
# These are the "white" color ranges
MYCELIUM_LOWER_H = 0
MYCELIUM_LOWER_S = 0
MYCELIUM_LOWER_V = 150

MYCELIUM_UPPER_H = 180
MYCELIUM_UPPER_S = 50
MYCELIUM_UPPER_V = 255

# Image save paths
import os
import logging

logger = logging.getLogger(__name__)

# Primary path: SSD
SSD_CAPTURE_DIRECTORY = "/media/richard/GOMBABOX/Gombabox_captures"

# Fallback path: SD card
SD_CAPTURE_DIRECTORY = "static/captures"

def get_capture_directory() -> str:
    """
    Returns the appropriate capture directory.
    Attempts to use the SSD first, falls back to SD card if unavailable.
    This check is performed at runtime to handle SSD mount/unmount scenarios.
    """
    # Try SSD first
    if os.path.exists(SSD_CAPTURE_DIRECTORY):
        try:
            # Verify we have write permissions
            if os.access(SSD_CAPTURE_DIRECTORY, os.W_OK):
                return SSD_CAPTURE_DIRECTORY
            else:
                logger.warning(f"SSD path exists but is not writable: {SSD_CAPTURE_DIRECTORY}. Falling back to SD card.")
        except Exception as e:
            logger.warning(f"Error accessing SSD: {e}. Falling back to SD card.")
    else:
        logger.warning(f"SSD not mounted at {SSD_CAPTURE_DIRECTORY}. Falling back to SD card.")
    
    # Fallback to SD card
    return SD_CAPTURE_DIRECTORY

def get_latest_capture_path() -> tuple:
    """
    Returns a tuple of (filename, full_path, serve_path) for the latest capture.
    Checks both SSD and SD card locations and returns the most recent file.
    Returns (None, None, None) if no captures exist.
    serve_path is the URL path to use in the frontend (/static/captures or direct serve path)
    """
    latest_file = None
    latest_time = None
    latest_dir = None
    latest_serve_path = None
    
    # Check both directories
    dirs_to_check = [
        (SSD_CAPTURE_DIRECTORY, f"/captures"),  # Direct serve from SSD
        (SD_CAPTURE_DIRECTORY, "/static/captures")  # Static serve from SD
    ]
    
    for directory, serve_path in dirs_to_check:
        if not os.path.exists(directory):
            continue
            
        try:
            files = [f for f in os.listdir(directory) 
                    if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            
            if not files:
                continue
                
            # Get the most recent file from this directory
            for filename in files:
                filepath = os.path.join(directory, filename)
                try:
                    file_time = os.path.getmtime(filepath)
                    if latest_time is None or file_time > latest_time:
                        latest_file = filename
                        latest_time = file_time
                        latest_dir = directory
                        latest_serve_path = serve_path
                except Exception as e:
                    logger.error(f"Error getting mtime for {filepath}: {e}")
                    
        except Exception as e:
            logger.error(f"Error scanning directory {directory}: {e}")
    
    if latest_file:
        return (latest_file, os.path.join(latest_dir, latest_file), latest_serve_path)
    
    return (None, None, None)

# Legacy constant for backward compatibility
CAPTURE_DIRECTORY = get_capture_directory()