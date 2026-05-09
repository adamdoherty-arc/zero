import importlib.metadata
import requests
from packaging.version import parse as parse_version

def check_outdated_packages():
    outdated = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata['Name'].lower()
        current_version = dist.version
        
        # Get latest version from PyPI
        try:
            response = requests.get(f"https://pypi.org/pypi/{name}/json", timeout=5)
            response.raise_for_status()
            latest_version = response.json()['info']['version']
            
            if parse_version(current_version) < parse_version(latest_version):
                outdated.append({
                    'name': name,
                    'current_version': current_version,
                    'latest_version': latest_version
                })
        except (requests.HTTPError, requests.ConnectionError, KeyError):
            # Skip packages that can't be checked
            continue
            
    return outdated