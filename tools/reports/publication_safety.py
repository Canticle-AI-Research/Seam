"""Fail-closed checks for every text file in the public report artifact."""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path
from urllib.parse import unquote

from tools.security.secret_scan import SECRET_PATTERNS

MAX_BYTES = 2_000_000
CONFIDENTIAL = re.compile(
    r'\b(?:SEAM_[A-Z0-9_]+|PGVECTOR_TEST_DSN|PYTHONPATH|[A-Z][A-Z0-9_]*_(?:KEY|TOKEN|SECRET|PASSWORD|DSN))\b'
    r'|\b[A-Z][A-Z0-9_]{2,}\s*='
    r'|\$\{?[A-Z][A-Z0-9_]*\b'
    r'|\b(?:process\.env|os\.environ|getenv\s*\()'
    r'|(?:/home/|/media/|/mnt/|/tmp/|file://|[A-Za-z]:[\\/]Users[\\/])'
    r'|(?i:\b(?:password|api[_-]?key|access[_-]?token|client[_-]?secret|authorization|cookie)\b[\s"\x27]*[:=])'
    r'|(?i:[?&](?:access_token|token|key|sig|signature|password|session|thread|auth|code)=)'
    r'|https?://[^\s/<>"\x27]+:[^\s/<>"\x27]+@'
    r'|(?i:\b(?:postgres(?:ql)?|mysql|mongodb|redis)://)'
    r'|(?i:https?://(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)(?:[:/]|\b))'
    r'|\bxox[baprs]-[A-Za-z0-9-]{12,}'
    r'|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
    r'|(?i:\bdata\s*:|\bbase64\s*,|(?:^|[\s/"\x27])\.env(?:\b|\.))'
)
STATIC_OUTPUTS = frozenset({
    'index.html', '404.html', 'about/index.html', 'manifest.json', 'feed.xml',
    'assets/canticle.svg', 'assets/library.js', 'assets/reports.css', 'assets/css/style.css',
})
REPORT_OUTPUT = re.compile(r'(?:reports/\d{4}-\d{2}-\d{2}-[a-z0-9-]+/index\.html|sources/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md)')


class PublicationSafetyError(ValueError):
    """Messages are content-free: never include the rejected value or filename."""


def validate_text(text: str) -> None:
    if '\0' in text or len(text.encode('utf-8')) > MAX_BYTES:
        raise PublicationSafetyError('publication text is uninspectable or exceeds its size bound')
    # Inspect common HTML, URL and JSON encodings as well as the literal text.
    for _ in range(3):
        if any(pattern.search(text) for _, pattern in SECRET_PATTERNS) or CONFIDENTIAL.search(text):
            raise PublicationSafetyError('confidential material or runtime configuration detected; inspect privately')
        text = re.sub(r'\\u00([0-9a-fA-F]{2})', lambda m: chr(int(m[1], 16)), unquote(html.unescape(text)))


def validate_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise PublicationSafetyError('publication input is missing, uninspectable or a symlink')
    try:
        validate_text(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError):
        raise PublicationSafetyError('publication input is not readable UTF-8 text') from None


def scan_site(root: Path) -> int:
    if root.is_symlink() or not root.is_dir():
        raise PublicationSafetyError('publication artifact is missing or a symlink')
    count = 0
    for path in root.rglob('*'):
        if path.is_symlink():
            raise PublicationSafetyError('publication artifact contains a symlink')
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if name not in STATIC_OUTPUTS and not REPORT_OUTPUT.fullmatch(name):
            raise PublicationSafetyError('publication artifact contains an unapproved file')
        validate_file(path)
        count += 1
    if not count:
        raise PublicationSafetyError('publication artifact is empty')
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, type=Path)
    args = parser.parse_args()
    try:
        count = scan_site(args.site)
    except (PublicationSafetyError, OSError):
        print('Publication blocked: an unapproved file or confidential content was detected; inspect privately.', file=sys.stderr)
        return 2
    print(f'Public artifact safety checks passed for all {count} files; none excluded from scanning.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
