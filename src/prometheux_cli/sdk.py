"""Lazy bridge to the prometheux_chain SDK.

The CLI is a thin orchestration layer over prometheux_chain (the design's round 5
decision). This module imports it on demand, injects the CLI's resolved
credentials into the SDK's runtime config, and turns missing-SDK / missing-auth
into clear CLI errors instead of tracebacks.
"""

from __future__ import annotations

from . import credentials


class SdkError(Exception):
    """A user-facing problem reaching or configuring the SDK."""


def load_sdk():
    """Import prometheux_chain, raising :class:`SdkError` with guidance if absent."""
    try:
        import prometheux_chain as px  # noqa: WPS433 (intentional lazy import)
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise SdkError(
            "prometheux_chain is not installed. Install it with:\n"
            "  pip install prometheux_chain"
        ) from exc
    return px


def configure(px, *, require_token: bool = True):
    """Push the CLI's resolved URL/token into the SDK config for this process."""
    url = credentials.resolve_url()
    token = credentials.resolve_token()
    if require_token and not token:
        raise SdkError(
            "Not authenticated. Run `px login` (or set the PMTX_TOKEN environment "
            "variable) first."
        )
    px.config.set(credentials.ENV_URL, url)
    if token:
        px.config.set(credentials.ENV_TOKEN, token)
    return url, token


def connected_sdk(*, require_token: bool = True):
    """Convenience: load the SDK and configure it. Returns ``(px, url, token)``."""
    px = load_sdk()
    url, token = configure(px, require_token=require_token)
    return px, url, token
