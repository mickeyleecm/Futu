"""Start the option chain web UI (OpenD must be running)."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8080"))
    uvicorn.run("web.app:app", host=host, port=port, reload=False)
