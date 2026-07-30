"""API-only compatibility surface for the public ``seam-runtime`` name.

This package delegates to :mod:`seam_client` and never imports local-runtime
implementation modules. It requires a separately provisioned SEAM ``/v1``
server; it is not the private local runtime.
"""

import sys

from seam_client import (
    DEFAULT_BASE_URL,
    AgentMemory,
    APIError,
    AsyncAgentMemory,
    AsyncSeamClient,
    AuthenticationError,
    ConnectionError,
    ContextResult,
    Health,
    Memory,
    RateLimitError,
    RecallResult,
    RememberReceipt,
    SeamClient,
    SeamError,
)

__version__ = "2.3.1"
PUBLIC_API_VERSION = "v1"
DEFAULT_NAMESPACE = "default"
DEFAULT_SCOPE = "thread"

# The compatibility distribution has no supported submodules. Emptying the
# package search path makes an unowned file left behind by a legacy or manual
# installation unreachable through this public package.
__path__ = []


class _SubmoduleBlocker:
    """Fail closed if any importer tries to resolve a shim submodule."""

    @staticmethod
    def find_spec(fullname, path=None, target=None):
        del path, target
        if fullname.startswith(f"{__name__}."):
            raise ModuleNotFoundError(
                f"{fullname!r} is not available in the API-only seam-runtime package"
            )
        return None


sys.meta_path.insert(0, _SubmoduleBlocker())


def has_client() -> bool:
    """Return ``True`` because ``seam-client`` is a required dependency."""
    return True


def has_full_runtime() -> bool:
    """Return ``False``; this public compatibility package is always API-only."""
    return False


__all__ = [
    "APIError",
    "AgentMemory",
    "AsyncAgentMemory",
    "AsyncSeamClient",
    "AuthenticationError",
    "ConnectionError",
    "ContextResult",
    "DEFAULT_BASE_URL",
    "Health",
    "Memory",
    "PUBLIC_API_VERSION",
    "DEFAULT_NAMESPACE",
    "DEFAULT_SCOPE",
    "RateLimitError",
    "RecallResult",
    "RememberReceipt",
    "SeamClient",
    "SeamError",
    "has_client",
    "has_full_runtime",
    "__version__",
]
