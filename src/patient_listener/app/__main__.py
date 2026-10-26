"""``python -m patient_listener.app`` / ``patient-listener-server`` entry point."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "patient_listener.app.server:create_app",
        factory=True,
        host=os.environ.get("PL_HOST", "127.0.0.1"),
        port=int(os.environ.get("PL_PORT", "8000")),
        reload=os.environ.get("PL_RELOAD", "").strip().lower() in {"1", "true", "yes", "on"},
        proxy_headers=False,  # App transport checks own explicitly trusted proxy headers.
    )


if __name__ == "__main__":
    main()
