"""PyInstaller entrypoint for the Sourceress backend.

Goal: ship a single `sourceress-backend.exe` that starts uvicorn on 127.0.0.1:8000.

Usage (dev):
  py backend/run_server.py

Usage (packaged):
  sourceress-backend.exe
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    # Ensure imports work when executed from an arbitrary working directory.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)

    host = os.environ.get("SOURCERESS_HOST", "127.0.0.1")
    port = int(os.environ.get("SOURCERESS_PORT", "8000"))

    import uvicorn

    # Import FastAPI app
    from app.main import app

    # In PyInstaller --noconsole builds, sys.stdout/sys.stderr may not be real TTY streams.
    # Uvicorn's default logging config can crash when it tries to call .isatty() on None.
    # So we disable uvicorn's dictConfig and rely on basic logging.
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "warning"),
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
