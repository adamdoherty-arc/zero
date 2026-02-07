"""
Run script for ZERO API.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=18792,
        reload=True,
        log_level="info"
    )
