import os
import sys
from pathlib import Path

def get_project_root() -> Path:
    """Get the root directory of the project"""
    return Path(__file__).parent.parent.parent

def get_config_dir() -> Path:
    """Get the configuration directory"""
    return get_project_root() / "config"

def get_data_dir() -> Path:
    """Get the data directory"""
    return get_project_root() / "data"

def get_logs_dir() -> Path:
    """Get the logs directory"""
    return get_project_root() / "logs"

def get_temp_dir() -> Path:
    """Get the temporary directory"""
    return get_project_root() / "temp"

def ensure_dir_exists(path: Path) -> None:
    """Ensure a directory exists, creating it if necessary"""
    path.mkdir(parents=True, exist_ok=True)

def get_python_version() -> str:
    """Get the current Python version as a string"""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

def is_windows() -> bool:
    """Check if the current platform is Windows"""
    return os.name == "nt"

def is_linux() -> bool:
    """Check if the current platform is Linux"""
    return sys.platform.startswith("linux")

def is_macos() -> bool:
    """Check if the current platform is macOS"""
    return sys.platform.startswith("darwin")