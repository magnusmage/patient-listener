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
        reload=bool(os.environ.get("PL_RELOAD")),
    )


if __name__ == "__main__":
    main()
