from __future__ import annotations

from pathlib import Path


def _key_path() -> Path:
    """Path for the local agent key.

    Installer-safe: store in %APPDATA%\Sourceress\data when available.
    """
    try:
        import os

        appdata = (os.environ.get('APPDATA') or '').strip()
        if appdata:
            return Path(appdata) / 'Sourceress' / 'data' / 'agent_key.txt'
    except Exception:
        pass

    # Dev fallback.
    return Path('data') / 'agent_key.txt'


def get_agent_key() -> str:
    try:
        p = _key_path()
        if not p.exists():
            return ''
        return (p.read_text(encoding='utf-8', errors='ignore') or '').strip()
    except Exception:
        return ''


def set_agent_key(key: str) -> None:
    k = (key or '').strip()
    if not k:
        raise ValueError('missing key')
    p = _key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(k, encoding='utf-8')


def agent_key_configured() -> bool:
    return bool(get_agent_key())
