from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

# Ensure packaging doesn't miss the app package
# (PyInstaller sometimes needs an explicit hint)


def pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def port_available(host: str, port: int) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, int(port)))
        s.close()
        return True
    except OSError:
        return False


def _bundle_root() -> Path:
    """Return the root directory containing packaged resources.

    In source/dev runs: this file's directory.
    In PyInstaller onefile: sys._MEIPASS.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def run_alembic(repo_root: Path) -> None:
    """Best-effort DB setup for the bundled app.

    Our migration history isn't a clean baseline (early 'init' migration
    tries to ALTER tables that don't exist). For a self-contained demo app,
    the pragmatic approach is:
      1) try alembic upgrade head
      2) if it fails, create tables from SQLModel metadata
      3) stamp head so the app doesn't keep retrying broken migrations

    This keeps the installed demo functional without requiring manual DB work.
    """
    from alembic.config import Config
    from alembic import command

    def _cfg() -> Config:
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo_root / "alembic"))
        return cfg

    try:
        command.upgrade(_cfg(), "head")
        return
    except Exception as e:
        print(f"[backend] alembic failed: {type(e).__name__}: {e}", file=sys.stderr)

    try:
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from sqlmodel import SQLModel
        from app.db import engine
        import app.models  # noqa: F401

        SQLModel.metadata.create_all(engine)
        # Mark DB as up-to-date to avoid repeated failures on startup.
        command.stamp(_cfg(), "head")
    except Exception as e2:
        print(f"[backend] metadata fallback failed: {type(e2).__name__}: {e2}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    # Default to an ephemeral free port to avoid conflicts with dev servers or stale sidecars.
    # If PORT is provided, we'll try it; otherwise we pick a free port.
    ap.add_argument("--port", type=int, default=int(os.getenv("PORT", "0") or 0))
    ap.add_argument("--data-dir", default=os.getenv("SOURCERESS_DATA_DIR", ""))
    args = ap.parse_args()

    repo_root = _bundle_root()

    # Make relative paths (templates/static) resolve in bundled mode.
    try:
        os.chdir(repo_root)
    except Exception:
        pass

    # Desktop beta: no login. Force dev-ish defaults unless explicitly overridden.
    os.environ.setdefault("ENV", "dev")
    os.environ.setdefault("ALLOWLIST_EMAILS", "")

    # Data dir for sqlite
    data_dir = Path(args.data_dir).resolve() if args.data_dir else (repo_root / "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    # Use an absolute sqlite path to avoid cwd surprises.
    db_path = data_dir / "app.db"
    os.environ.setdefault("DB_URL", f"sqlite:///{db_path.as_posix()}")
    os.environ.setdefault("DATABASE_URL", os.environ["DB_URL"])

    port = int(args.port or 0)
    if port <= 0:
        port = pick_free_port()

    if not port_available(args.host, port):
        fallback = pick_free_port()
        print(f"[backend] port {port} unavailable; falling back to {fallback}")
        port = fallback

    run_alembic(repo_root)

    # Start uvicorn
    import uvicorn  # noqa

    # Ensure our bundled root is on sys.path so `import app.*` works.
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Start uvicorn. If we lose a port race (common if multiple sidecars spawn), retry once.
    for attempt in range(2):
        try:
            print(f"[backend] running on http://{args.host}:{port}")
            uvicorn.run(
                "app.main:app",
                app_dir=str(repo_root),
                host=args.host,
                port=port,
                log_level="info",
            )
            return 0
        except OSError as e:
            if getattr(e, 'errno', None) == 10048 and attempt == 0:
                # Address already in use
                new_port = pick_free_port()
                print(f"[backend] port race on {port}; retrying on {new_port}", file=sys.stderr)
                port = new_port
                continue
            raise


if __name__ == "__main__":
    raise SystemExit(main())
