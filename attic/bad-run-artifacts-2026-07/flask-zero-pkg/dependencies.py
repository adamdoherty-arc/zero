import os
import subprocess
import json
from typing import List, Dict, Optional
from zero.core import logger
from zero.core.exceptions import PackageManagerError

class PackageManager:
    """Manages package dependencies and updates"""
    
    def __init__(self, project_root: str = None):
        self.project_root = project_root or os.getcwd()
        self.logger = logger.get_logger(__name__)
        
    def get_outdated_packages(self) -> List[Dict]:
        """Get list of outdated packages in the project"""
        try:
            result = subprocess.run(
                ['pip', 'list', '--outdated'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_root
            )
            
            packages = []
            for line in result.stdout.split('\n')[2:]:  # Skip header lines
                if not line.strip():
                    continue
                    
                parts = line.split()
                if len(parts) < 4:
                    continue
                    
                packages.append({
                    'name': parts[0],
                    'current_version': parts[1],
                    'latest_version': parts[2],
                    'location': parts[-1]
                })
                
            return packages
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to get outdated packages: {e}")
            raise PackageManagerError(f"Failed to get outdated packages: {e}") from e
            
    def update_package(self, package_name: str, version: Optional[str] = None) -> bool:
        """Update a specific package to the latest version"""
        try:
            cmd = ['pip', 'install', '--upgrade', package_name]
            if version:
                cmd.append(f'=={version}')
                
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_root
            )
            
            self.logger.info(f"Successfully updated {package_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to update {package_name}: {e}")
            return False
            
    def update_all_packages(self) -> Dict[str, bool]:
        """Update all outdated packages"""
        try:
            result = subprocess.run(
                ['pip', 'list', '--outdated'],
                capture_output=True,
                text=True,
                check=True,
                cwd=self.project_root
            )
            
            updates = {}
            for line in result.stdout.split('\n')[2:]:  # Skip header lines
                if not line.strip():
                    continue
                    
                parts = line.split()
                if len(parts) < 4:
                    continue
                    
                package_name = parts[0]
                success = self.update_package(package_name)
                updates[package_name] = success
                
            return updates
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to update packages: {e}")
            return {}