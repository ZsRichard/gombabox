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
SSD_MOUNT_POINT = os.path.dirname(SSD_CAPTURE_DIRECTORY.rstrip(os.sep))

# Fallback path: SD card
SD_CAPTURE_DIRECTORY = "static/captures"


def _is_mounted_path(path: str) -> bool:
    """Return True when path is a mount point (also handles symlinked mounts)."""
    real_path = os.path.realpath(path)
    return os.path.ismount(path) or os.path.ismount(real_path)


def _iter_gombabox_mount_points():
    """Yield possible mount points for the GOMBABOX SSD label."""
    seen = set()

    preferred = SSD_MOUNT_POINT
    if preferred not in seen:
        seen.add(preferred)
        yield preferred

    scan_roots = ["/media", "/run/media", "/mnt"]
    for root in scan_roots:
        if not os.path.isdir(root):
            continue

        # Support direct mounts (/mnt/GOMBABOX, /media/GOMBABOX)
        for entry in os.listdir(root):
            direct_path = os.path.join(root, entry)
            if os.path.isdir(direct_path) and entry.startswith("GOMBABOX"):
                if direct_path not in seen:
                    seen.add(direct_path)
                    yield direct_path

        # Support user-scoped mounts (/media/<user>/GOMBABOX*)
        for user_dir in os.listdir(root):
            user_path = os.path.join(root, user_dir)
            if not os.path.isdir(user_path):
                continue
            for volume in os.listdir(user_path):
                if not volume.startswith("GOMBABOX"):
                    continue
                mount_point = os.path.join(user_path, volume)
                if mount_point in seen:
                    continue
                seen.add(mount_point)
                yield mount_point


def get_ssd_capture_directory() -> str:
    """Return active SSD capture directory, or None if SSD is unavailable."""
    for mount_point in _iter_gombabox_mount_points():
        if not _is_mounted_path(mount_point):
            continue

        capture_dir = os.path.join(mount_point, "Gombabox_captures")
        try:
            os.makedirs(capture_dir, exist_ok=True)
            if os.access(capture_dir, os.W_OK):
                return capture_dir
            logger.warning("SSD is mounted but not writable: %s", capture_dir)
        except Exception as e:
            logger.warning("Error preparing SSD capture path %s: %s", capture_dir, e)

    return None

def get_capture_directory() -> str:
    """
    Returns the appropriate capture directory.
    Attempts to use the SSD first, falls back to SD card if unavailable.
    This check is performed at runtime to handle SSD mount/unmount scenarios.
    """
    ssd_capture_dir = get_ssd_capture_directory()
    if ssd_capture_dir:
        return ssd_capture_dir

    logger.warning("No mounted/writable GOMBABOX SSD detected. Falling back to SD card.")
    
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
    dirs_to_check = [(SD_CAPTURE_DIRECTORY, "/static/captures")]

    ssd_capture_dir = get_ssd_capture_directory()
    if ssd_capture_dir:
        dirs_to_check.insert(0, (ssd_capture_dir, "/captures"))
    
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

def resolve_capture_file_path(filename: str) -> str | None:
    """Resolve a stored capture filename to an absolute file path if it exists."""
    if not filename:
        return None

    candidate_directories = []

    ssd_capture_dir = get_ssd_capture_directory()
    if ssd_capture_dir:
        candidate_directories.append(ssd_capture_dir)

    candidate_directories.append(SD_CAPTURE_DIRECTORY)

    for directory in candidate_directories:
        file_path = os.path.join(directory, filename)
        if os.path.exists(file_path):
            return file_path

    return None

# Legacy constant for backward compatibility
CAPTURE_DIRECTORY = get_capture_directory()