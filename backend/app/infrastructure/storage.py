"""
JSON file storage utilities for sprint data.
Follows Zero's existing pattern of JSON-based persistence.
"""

import json
import aiofiles
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger()


class JsonStorage:
    """Async JSON file storage with atomic writes."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def read(self, filename: str) -> Dict[str, Any]:
        """Read JSON file and return contents."""
        filepath = self.base_path / filename
        try:
            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                content = await f.read()
                return json.loads(content)
        except FileNotFoundError:
            logger.warning("File not found", filepath=str(filepath))
            return {}
        except json.JSONDecodeError as e:
            logger.error("JSON decode error", filepath=str(filepath), error=str(e))
            return {}

    async def write(self, filename: str, data: Dict[str, Any]) -> bool:
        """Write data to JSON file atomically."""
        filepath = self.base_path / filename
        temp_filepath = filepath.with_suffix('.tmp')

        try:
            # Write to temp file first
            async with aiofiles.open(temp_filepath, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, default=str))

            # Atomic rename
            temp_filepath.replace(filepath)
            logger.debug("File written", filepath=str(filepath))
            return True
        except Exception as e:
            logger.error("Write error", filepath=str(filepath), error=str(e))
            if temp_filepath.exists():
                temp_filepath.unlink()
            return False

    async def update(self, filename: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Read, update, and write JSON file."""
        data = await self.read(filename)
        data.update(updates)
        await self.write(filename, data)
        return data


def json_serial(obj: Any) -> str:
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")
