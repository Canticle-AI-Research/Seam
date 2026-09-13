"""Export an explicit, revision-pinned report catalog into a Jekyll source tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit, urlunsplit

from tools.reports.publication_safety import PublicationSafetyError, validate_file, validate_text
from tools.security.secret_scan import SECRET_PATTERNS

REPOSITORY = 'https://github.com/Canticle-AI-Research/Seam'
FIELDS = {'id', 'title', 'date', 'kind', 'summary', 'context', 'source', 'revision', 'sha256', 'edition', 'edition_sha256'}
SITE_INPUTS = ('_config.yml', 'index.html', 'about.md', '404.html', 'feed.xml',
               '_layouts/default.html', '_layouts/report.html', 'assets/library.js', 'assets/reports.css')
UNSAFE = re.compile(
    r'\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b'
    r'|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
    r'|https?://(?:chatgpt\.com|chat\.openai\.com|claude\.ai)/(?:c|chat|share|codex/tasks)/'
    r'|(?:/home/|/media/|/mnt/|file://)|(?:postgres(?:ql)?://)'
    r'|</?\s*(?:script|iframe|object|embed|base|meta|link|style)\b'
    r'|\bon\w+\s*=|javascript\s*:|\bdata\s*:|\{%\s*endraw\b', re.I,
)
LINK = re.compile(r'(!?\[[^\]\n]*\]\()([^\s)]+)(\))')


def check_public(text: str, label: str) -> None:
    validate_text(text)
    if UNSAFE.search(text):
        raise ValueError(f'public-safety check failed for {label}; inspect source privately')


def source_bytes(repo: Path, item: dict) -> bytes:
    source = item['source']
    path = PurePosixPath(source)
    if path.is_absolute() or '..' in path.parts or '\\' in source or path.suffix != '.md':
        raise ValueError('invalid report source path')
    if not source.startswith(('docs/audits/', 'tests/docs/')):
        raise ValueError('report source must use the canonical audit or testing home')
    result = subprocess.run(['git', '-C', str(repo), 'show', f"{item['revision']}:{source}"],
                            capture_output=True, check=False)
    if result.returncode:
        raise ValueError('pinned report source is unavailable; fetch its history')
    if len(result.stdout) > 512_000:
        raise ValueError('report exceeds the 512 KB public-text bound')
    if hashlib.sha256(result.stdout).hexdigest() != item['sha256']:
        raise ValueError('pinned report content does not match its SHA-256')
    if any(pattern.search(result.stdout.decode('utf-8')) for _, pattern in SECRET_PATTERNS):
        raise ValueError('linked source contains confidential material; inspect privately')
    return result.stdout


def source_links(text: str, item: dict) -> str:
    def replace(match: re.Match) -> str:
        target = match[2]
        parts = urlsplit(target)
        if parts.scheme:
            if parts.scheme not in {'https', 'http', 'mailto'}:
                raise ValueError('unsupported report link scheme')
            return match[0]
        if parts.netloc:
            raise ValueError('protocol-relative report links are unsupported')
        if not parts.path:
            return match[0]
        path = posixpath.normpath(posixpath.join(posixpath.dirname(item['source']), parts.path))
        if path.startswith('../') or path.startswith('/'):
            raise ValueError('report link escapes repository context')
        url = f"{REPOSITORY}/blob/{item['revision']}/{quote(path, safe='/')}"
        url += urlunsplit(('', '', '', parts.query, parts.fragment))
        return f'{match[1]}{url}{match[3]}'
    return LINK.sub(replace, text)


def prepare(repo: Path, output: Path) -> int:
    if output.exists():
        raise ValueError('output already exists; select a new empty destination')
    site = repo / 'report-site'
    catalog = json.loads((site / 'catalog.json').read_text())
    if not isinstance(catalog, dict) or set(catalog) != {'schema', 'reports'} or catalog['schema'] != 1:
        raise ValueError('unsupported publication catalog')
    if not isinstance(catalog['reports'], list):
        raise ValueError('publication reports must be an array')
    prepared = []
    seen = set()
    for record in catalog['reports']:
        if not isinstance(record, dict) or set(record) != FIELDS:
            raise ValueError('report metadata fields do not match the catalog contract')
        if any(not isinstance(v, str) or not v or len(v) > 1600 for v in record.values()):
            raise ValueError('report metadata must contain bounded, nonempty text')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*', record['id']):
            raise ValueError('invalid report id')
        if record['id'] in seen:
            raise ValueError('duplicate report id')
        seen.add(record['id'])
        try:
            date.fromisoformat(record['date'])
        except ValueError:
            raise ValueError('invalid report date') from None
        if record['kind'] not in {'research', 'benchmark', 'test'}:
            raise ValueError('invalid report kind')
        if not re.fullmatch('[0-9a-f]{40}', record['revision']):
            raise ValueError('report revision must be a complete commit SHA')
        if any(not re.fullmatch('[0-9a-f]{64}', record[key]) for key in ('sha256', 'edition_sha256')):
            raise ValueError('report SHA-256 is invalid')
        check_public(json.dumps(record), 'metadata')
        source_bytes(repo, record)  # Verify provenance without copying the original into the site.
        if record['edition'] != f"report-site/editions/{record['id']}.md":
            raise ValueError('invalid public edition path')
        edition = repo / record['edition']
        if (site / 'editions').is_symlink():
            raise ValueError('public edition directory is a symlink')
        validate_file(edition)
        raw = edition.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record['edition_sha256']:
            raise ValueError('public edition does not match its SHA-256')
        text = raw.decode('utf-8')
        check_public(text, 'report text')
        body = source_links(text, record)
        if body.startswith('# '):
            body = body.partition('\n')[2].lstrip('\n')
        item = dict(record, source_url=f"{REPOSITORY}/blob/{record['revision']}/{record['source']}")
        prepared.append((item, raw, body))

    # Validate all inputs before creating the publication tree.
    for directory in ('assets', '_layouts'):
        root = site / directory
        if root.is_symlink():
            raise ValueError('site input symlinks are unsupported')
        for path in root.rglob('*'):
            if path.is_symlink() or (path.is_file() and path.relative_to(site).as_posix() not in SITE_INPUTS):
                raise ValueError('unexpected site input; inspect privately')
    for name in SITE_INPUTS:
        if (site / name).exists() or (site / name).is_symlink():
            validate_file(site / name)
    mark = repo / 'branding/kit/marks/canticle-company-lockup.svg'
    if mark.is_symlink() or not mark.is_file():
        raise ValueError('canonical Canticle mark is unavailable')
    validate_file(mark)
    output.mkdir(parents=True)
    for name in SITE_INPUTS:
        path = site / name
        if path.is_file():
            (output / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output / name)
    (output / 'assets').mkdir(exist_ok=True)
    shutil.copy2(mark, output / 'assets/canticle.svg')
    (output / '_reports').mkdir()
    (output / 'sources').mkdir()
    for item, raw, body in prepared:
        metadata = dict(item, report_id=item['id'], layout='report')
        front = '\n'.join(f'{key}: {json.dumps(value, ensure_ascii=False)}' for key, value in metadata.items())
        page = '---\n' + front + '\n---\n\n{% raw %}\n' + body + '\n{% endraw %}\n'
        (output / '_reports' / f"{item['id']}.md").write_text(page, encoding='utf-8')
        (output / 'sources' / f"{item['id']}.md").write_bytes(raw)
    manifest = {'schema': 1, 'repository': REPOSITORY, 'reports': [item for item, _, _ in prepared]}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    return len(prepared)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        count = prepare(args.repo.resolve(), args.output.resolve())
    except (ValueError, OSError, UnicodeError) as exc:
        # Never echo report contents or Git diagnostics containing a rejected value.
        message = str(exc) if type(exc) in (ValueError, PublicationSafetyError) else 'unable to read publication inputs'
        print(f'report export: {message}', file=sys.stderr)
        return 2
    print(f'Prepared {count} pinned public reports.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
