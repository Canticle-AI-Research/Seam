"""Canonical Python version identity shared by guarded release workflows."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version


def validate_release_version(requested: str, *, project_version: str | None = None) -> Version:
    """Require an exact public PEP 440 version with a three-part release.

    Alpha, beta, release candidate, development and post releases use Python's
    canonical spelling. Epochs and local version labels are outside SEAM's
    published release identity. Never normalize an input into another release.
    """
    message = (
        "requested version must be canonical public PEP 440 with three release "
        "components and no epoch or local version label"
    )
    try:
        version = Version(requested)
    except InvalidVersion:
        raise ValueError(message) from None
    if (
        requested != str(version)
        or len(version.release) != 3
        or version.epoch != 0
        or version.local is not None
    ):
        raise ValueError(message)
    if project_version is not None and project_version != requested:
        raise ValueError("pyproject.toml version does not match requested version")
    return version


def matches_release_version(actual: str, expected: str) -> bool:
    """Bind artifact filenames and metadata to the exact canonical release."""
    try:
        validate_release_version(actual, project_version=expected)
    except ValueError:
        return False
    return True
