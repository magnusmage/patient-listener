"""Pure translation between the controller's :class:`Action` values and the frontend's JSON
event protocol, and between inbound client messages and :class:`SessionEngine` event tuples.

No I/O, no timers, no session state beyond the small :class:`EmitContext` passed in - so the
whole mapping is unit-testable without a socket. The orchestrator (:mod:`.session`) owns timing,
the word cursor and the clock; this module only shapes messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..voice import hints as hintmod
from ..voice.actions import (
    Action,
    Confirm,
    EndTurn,
    LogAttempt,
    MoveOn,
    OfferRest,
    Play,
    Praise,
    SafetyStop,
    ShowHint,
    Speak,
    Stop,
)
from . import presenter

__all__ = ["EmitContext", "action_to_events", "client_message_to_event"]


@dataclass
class EmitContext:
    """The little bit of session context the pure mapping needs to shape an event."""

    feedback: str = "word_found"
    last_heard: str = ""
    hint_level: int = 0
    found: list[str] = field(default_factory=list)
    region: str = "UK"


def action_to_events(action: Action, ctx: EmitContext) -> list[dict]:
    """Map one controller action to zero or more frontend events (``{"type": ...}`` dicts)."""
    if isinstance(action, Play):
        if action.key == "mm":
            return [{"type": "backchannel", "key": "mm", "caption": "mm"}]
        if action.key == "offer_hint":
            return [{"type": "offerHint"}]
        return []  # hint:<id>:<lvl> audio clip - carried by ShowHint in text mode

    if isinstance(action, ShowHint):
        step = hintmod.render(action.word, action.level)
        return [
            {
                "type": "hint",
                "word_id": action.word.id,
                "level": int(action.level),
                "text": step.text,
                "letter": action.word.first_sound or action.word.text[:1],
                "word": action.word.text,
            }
        ]

    if isinstance(action, Confirm):
        if ctx.feedback == "what_i_heard":
            return [{"type": "whatIHeard", "text": ctx.last_heard}]
        return [{"type": "confirm", "word": action.word.text}]

    if isinstance(action, Praise):
        return [{"type": "found", "word": action.word.text, "hintLevel": ctx.hint_level}]

    if isinstance(action, LogAttempt):
        a = action.attempt
        return [
            {
                "type": "attempt",
                "word_id": a.word_id,
                "hint_level": int(a.hint_level),
                "outcome": a.outcome.value,
                "score": a.match_score,
            }
        ]

    if isinstance(action, MoveOn):
        return [{"type": "moveOn"}]

    if isinstance(action, Speak):
        return [{"type": "reply", "text": action.text}]

    if isinstance(action, SafetyStop):
        return [{"type": "safety", **presenter.safety_card(action.card, ctx.region)}]

    if isinstance(action, OfferRest):
        return [{"type": "restOffer"}]

    if isinstance(action, Stop):
        return [{"type": "ended", "reason": "done", "found": list(ctx.found)}]

    if isinstance(action, EndTurn):
        return []  # the turn's reply is emitted separately via Speak

    return []


# Inbound client messages that translate straight to a SessionEngine event kind (the orchestrator
# supplies ``now`` and any text). Stateful ones (start/pause/speech/resume/rest/demo_say) are
# handled by the orchestrator because they touch the word cursor, the clock or the ticker.
_DIRECT = {
    "help": "help",
    "yes": "yes",
    "no": "no",
    "done": "done",
    "stop": "stop",
}


def client_message_to_event(msg: dict) -> tuple[str, dict]:
    """Classify an inbound message. Returns ``(engine_kind | control_name, data)``.

    ``engine_kind`` is one of the direct :class:`SessionEngine` event kinds; otherwise the first
    element is the control name (``"start"``, ``"pause"``, ...) for the orchestrator to handle.
    """
    kind = msg.get("type", "")
    if kind in _DIRECT:
        return _DIRECT[kind], {}
    if kind == "confirm_tap":
        ok = msg.get("ok")
        if not isinstance(ok, bool):
            raise ValueError("confirm_tap requires a boolean ok")
        return ("confirm_tap", {"ok": ok})
    if kind == "typed":
        return ("typed", {"text": str(msg.get("text", ""))})
    if kind == "demo_say":
        return ("demo_say", {"variant": str(msg.get("variant", "exact"))})
    return (kind, {k: v for k, v in msg.items() if k != "type"})
