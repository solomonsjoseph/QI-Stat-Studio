"""Local-dev process control. Admin only, and disabled when environment=production."""

from __future__ import annotations

import os
import signal
import threading
import time

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_admin
from api.config import settings
from api.models_db import User

router = APIRouter(tags=["dev"])


def _stop_process() -> None:
    time.sleep(0.4)
    # Prefer the reloader parent when uvicorn --reload is in use.
    parent = os.getppid()
    try:
        if parent and parent != 1:
            os.kill(parent, signal.SIGTERM)
            return
    except OSError:
        pass
    os.kill(os.getpid(), signal.SIGTERM)


@router.post("/dev/quit")
def quit_local_servers(user: User = Depends(require_admin)):
    """Sign the resident out of the process by stopping the local backend.

    Only available outside production. The frontend clears its own session and
    shows a stopped page; Vite may still be running until the terminal is closed.
    """
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="Not found")
    threading.Thread(target=_stop_process, daemon=True).start()
    return {"ok": True, "stopped": True, "by": user.email}
