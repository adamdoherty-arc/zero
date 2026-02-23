"""
Run script for ZERO API.
"""

import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=18792,
        reload=os.getenv("ZERO_DEV_MODE", "").lower() == "true",
        log_level="info"
    )
