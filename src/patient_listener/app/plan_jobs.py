"""Shared bounded plan work for authenticated requests and the trusted nightly worker."""
import asyncio
from fastapi import HTTPException


class PlanBusy(HTTPException):
    def __init__(self, detail):
        super().__init__(409, detail)


async def run_generation(app, access, pid, options, *, on_admitted=None):
    import importlib.util
    from ..llm.factory import build_llm
    from ..plan_generation import generate_plan, PlanConflict
    from .nemo_stream import render_hint
    from ..voice.processing import hint_profile
    from .voice_connection import worker_call
    state = app.state.pl
    if not access.store.can_manage_profile(pid, access.user_id):
        raise HTTPException(403, "Only the linked therapist, or carer without a therapist, can generate plans")
    if access.demo and (options.use_ai or options.render_audio):
        raise HTTPException(403, "Judge demo plan generation supports templates and text only")
    runtime = app.state.voice_runtime
    remote=state.settings.service_role=="api"
    if options.render_audio and runtime is None and not remote:
        raise HTTPException(503, "Voice models are not loaded; use render_audio=false for a text plan")
    if options.use_ai and (not access.store.is_ai_enabled() or not state.settings.nebius_api_key.strip()
                          or importlib.util.find_spec('openai') is None):
        raise HTTPException(409, "Enable AI and configure the API key and SDK before requesting model hints")
    # Same admission controls as live practice. A generation cannot compete with voice
    # or mutate the person's hints under an active session on this worker.
    person_key = ('demo-plan:' if access.demo else '') + pid
    if not await state.sessions.claim(person_key):
        raise PlanBusy("This person has an active session or plan generation")
    gpu_claimed = False
    try:
        if options.render_audio and not remote:
            if not await state.sessions.claim('__gpu_voice__'):
                raise PlanBusy("GPU is busy; stop the voice session before generating audio")
            gpu_claimed = True
        limits = {} if on_admitted is None else on_admitted()
        if limits is None:
            return {"already_claimed": True}
        if remote:
            from .remote_voice import RemoteRenderer
            remote_renderer=RemoteRenderer(state.settings,state.sessions,pid)
        async def render(text):
            if remote:return await remote_renderer.render(text)
            def locked_render():
                with runtime.gpu_lock:
                    return render_hint(runtime, text)
            return await worker_call(locked_render)
        return await generate_plan(access.store, pid, actor=access.user_id,
            llm=build_llm(state.settings, access.store), max_words=options.max_words,
            use_ai=options.use_ai, render=render if options.render_audio else None,
            tts_model=state.settings.tts_model, voice=state.settings.tts_voice, audio_profile=hint_profile(state.settings),
            check_admission=lambda:state.sessions.check_owned(person_key), **limits)
    except asyncio.CancelledError:
        if state.sessions.was_lost(person_key) or (gpu_claimed and state.sessions.was_lost('__gpu_voice__')):
            raise HTTPException(503,'Plan admission lost') from None
        raise
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(403, "Plan generation is no longer permitted") from exc
    except PlanConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        # Never include model payloads, keys or text in an error response.
        raise HTTPException(503, "Plan generation failed; the previous plan was kept") from exc
    finally:
        if gpu_claimed:
            await state.sessions.release('__gpu_voice__')
        await state.sessions.release(person_key)
