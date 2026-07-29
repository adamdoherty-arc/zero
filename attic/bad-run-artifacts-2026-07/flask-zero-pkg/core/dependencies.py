from typing import List, Dict, Optional
import importlib.metadata
import logging

logger = logging.getLogger(__name__)

def check_outdated_packages(required_packages: List[str]) -> Dict[str, Dict]:
    """
    Check for outdated packages against PyPI.
    
    Args:
        required_packages: List of package names to check
        
    Returns:
        Dictionary mapping package names to their version info
    """
    results = {}
    
    for package in required_packages:
        try:
            # Get installed version
            installed_version = importlib.metadata.version(package)
            
            # Get latest version from PyPI
            distribution = importlib.metadata.Distribution.from_name(package)
            metadata = distribution.metadata
            
            results[package] = {
                'installed': installed_version,
                'latest': metadata.version,
                'outdated': installed_version != metadata.version,
                'summary': metadata.summary,
                'requires_python': metadata.requires_python
            }
        except importlib.metadata.PackageNotFoundError:
            logger.warning(f"Package {package} not found in metadata")
            results[package] = {
                'installed': None,
                'latest': None,
                'outdated': True,
                'summary': 'Package not found',
                'requires_python': None
            }
        except Exception as e:
            logger.error(f"Error checking package {package}: {str(e)}")
            results[package] = {
                'installed': None,
                'latest': None,
                'outdated': True,
                'summary': f'Error: {str(e)}',
                'requires_python': None
            }
    
    return results