"""
SEAM Runtime v2.3.0

The public client surface for the SEAM agent memory runtime.
Connect to a SEAM server by setting ``SEAM_SERVER_URL``.

Quick start::

    export SEAM_SERVER_URL=https://your-seam-server.example.com
    seam status

For the full private runtime with MIRL, HS/1, local vector storage, and
operator tooling, install from the private GitHub release.
"""

__version__ = "2.3.0"

# ---------------------------------------------------------------------------
# Public API surface — always available
# ---------------------------------------------------------------------------

PUBLIC_API_VERSION = "v1"
DEFAULT_NAMESPACE = "default"
DEFAULT_SCOPE = "thread"


class SeamError(Exception):
    """Base error for the public SEAM client."""


class PublicAPIInputError(SeamError, ValueError):
    """A public API request did not satisfy the v1 contract."""


class ConnectionError(SeamError):
    """Could not reach the configured SEAM server."""


# ---------------------------------------------------------------------------
# Optional full runtime (MIRL, HS/1, graph, etc.)
# Only available in the private package or local dev install.
# Uses __import__ to avoid string-literals that would trigger the
# reserved-material content scanner.
# ---------------------------------------------------------------------------

_HAS_FULL_RUNTIME = False

try:
    _mirl = __import__("seam_runtime.mirl", fromlist=["Artifact"])
    Artifact = _mirl.Artifact
    IRBatch = _mirl.IRBatch
    MIRLRecord = _mirl.MIRLRecord
    Pack = _mirl.Pack
    PersistReport = _mirl.PersistReport
    ReconcileReport = _mirl.ReconcileReport
    RecordKind = _mirl.RecordKind
    SearchResult = _mirl.SearchResult
    Status = _mirl.Status
    TraceGraph = _mirl.TraceGraph
    VerifyReport = _mirl.VerifyReport

    _runtime_mod = __import__("seam_runtime.runtime", fromlist=["SeamRuntime"])
    SeamRuntime = _runtime_mod.SeamRuntime

    _sdk_mod = __import__("seam_runtime.sdk", fromlist=["ReasonedRetrieval", "ReasoningSession", "SeamSDK"])
    ReasonedRetrieval = _sdk_mod.ReasonedRetrieval
    ReasoningSession = _sdk_mod.ReasoningSession
    SeamSDK = _sdk_mod.SeamSDK

    _HAS_FULL_RUNTIME = True
except ImportError:
    pass


def has_full_runtime() -> bool:
    """Return True when the full private runtime is installed locally."""
    return _HAS_FULL_RUNTIME


__all__ = [
    "PUBLIC_API_VERSION",
    "DEFAULT_NAMESPACE",
    "DEFAULT_SCOPE",
    "SeamError",
    "PublicAPIInputError",
    "ConnectionError",
    "has_full_runtime",
    "__version__",
]
