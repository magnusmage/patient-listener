"""The application server (the "app API").

An adapter layer (ports-and-adapters invariant #3) that connects the ``web/`` frontend to the
pure decision core. It serves the static frontend, issues short-lived session tokens, runs the
real :class:`~patient_listener.voice.session.SessionEngine` over a WebSocket speaking the event
protocol ``web/app.js`` already consumes, and backs the therapist console with real store data.

Nothing here is imported by the decision core. Text mode does not load GPU models or Pipecat.
The live voice path lazily loads app.pipecat_pipeline and the NeMo/Magpie adapters.
"""

from __future__ import annotations

__all__ = ["create_app"]


def create_app():  # noqa: ANN201 - FastAPI app; imported lazily to keep the core import-light
    """Build the FastAPI application. Imported lazily so the ``api`` extra is only needed here."""
    from .server import create_app as _create_app

    return _create_app()
