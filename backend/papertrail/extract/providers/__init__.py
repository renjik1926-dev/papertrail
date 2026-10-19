"""Pick a provider from settings (decision D9)."""

from __future__ import annotations

from papertrail.config import Settings
from papertrail.extract.providers.base import Provider
from papertrail.extract.providers.claude import ClaudeProvider
from papertrail.extract.providers.fake import FakeProvider
from papertrail.extract.providers.replay import ReplayProvider


def make_provider(settings: Settings) -> Provider:
    if settings.provider == "replay":
        return ReplayProvider(settings.resolved_recordings_dir(), model=settings.model)
    if settings.provider == "fake":
        return FakeProvider()
    key = settings.require_api_key()
    return ClaudeProvider(
        api_key=key.get_secret_value(),
        model=settings.model,
        workspace_id=settings.anthropic_workspace_id,
        timeout_s=settings.api_timeout_s,
    )
