"""Remove expired post-deletion consent evidence even when nightly AI jobs are off."""
import asyncio
import logging
from ..store.privacy import PrivacyStore


async def purge_retained_consent(app):
    while True:
        try:
            PrivacyStore(app.state.pl.store).purge_expired_consent()
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Consent retention purge failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(3600)
