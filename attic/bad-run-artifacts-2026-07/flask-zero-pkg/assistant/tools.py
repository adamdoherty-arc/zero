import os
import subprocess
import json
from typing import List, Dict, Optional
from zero.assistant.base import Tool, ToolResponse

class OutdatedPackagesTool(Tool):
    """Tool to check for outdated Python packages in the current environment."""
    
    def __init__(self):
        super().__init__(
            name="outdated_packages",
            description="Check for outdated Python packages in the current environment",
            parameters={},
            returns={"packages": List[Dict[str, str]]}
        )

    def _run(self) -> ToolResponse:
        try:
            # Use pip list to get installed packages
            result = subprocess.run(
                ["pip", "list", "--outdated"],
                capture_output=True,
                text=True,
                check=True
            )
            
            packages = []
            for line in result.stdout.splitlines()[2:]:  # Skip header lines
                if not line.strip():
                    continue
                
                parts = line.split()
                if len(parts) >= 5:
                    package_name = parts[0]
                    current_version = parts[1]
                    latest_version = parts[3]
                    packages.append({
                        "name": package_name,
                        "current_version": current_version,
                        "latest_version": latest_version
                    })
            
            return ToolResponse(
                success=True,
                data={"packages": packages},
                message="Successfully retrieved outdated packages"
            )
            
        except subprocess.CalledProcessError as e:
            return ToolResponse(
                success=False,
                data={},
                message=f"Failed to get outdated packages: {str(e)}"
            )