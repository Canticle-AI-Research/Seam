"""SEAM terminal UI.

`app` holds the presentation shell, `commands` derives the `/` palette from the
backend parser, `settings_screen` renders `seam_runtime.config`, and
`theme.tcss` carries the Charm-flavoured styling.
"""

from __future__ import annotations

__all__ = ["run", "SeamTUI"]


def __getattr__(name: str):
    """Import lazily so `seam_runtime.tui` stays importable without textual."""
    if name in __all__:
        from . import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
