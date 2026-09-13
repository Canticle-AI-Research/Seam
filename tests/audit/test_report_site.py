"""Public report export must preserve provenance and reject unsafe publication."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE = 'tools.reports.prepare_site'


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def publication(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    git(repo, 'config', 'user.name', 'Report fixture')
    source = repo / 'docs/audits/2026-09-12-result.md'
    source.parent.mkdir(parents=True)
    source.write_text('# Recorded result\n\nA scoped finding.\n\n[Method](../METHOD.md#scope)\n')
    git(repo, 'add', 'docs')
    git(repo, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Recorded source')
    ref = git(repo, 'rev-parse', 'HEAD')
    site = repo / 'report-site'
    site.mkdir()
    (site / '_config.yml').write_text('title: Reports\n')
    (site / 'index.html').write_text('---\nlayout: default\n---\n')
    brand = repo / 'branding/kit/marks'
    brand.mkdir(parents=True)
    (brand / 'canticle-company-lockup.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    item = {'id': '2026-09-12-result', 'title': 'Recorded result', 'date': '2026-09-12',
            'kind': 'test', 'summary': 'A scoped test report.',
            'context': 'Historical evidence for its named revision.',
            'source': source.relative_to(repo).as_posix(), 'revision': ref,
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    edition = site / 'editions' / (item['id'] + '.md')
    edition.parent.mkdir()
    edition.write_text(source.read_text() + '\nPublic edition.\n')
    item['edition'] = edition.relative_to(repo).as_posix()
    item['edition_sha256'] = hashlib.sha256(edition.read_bytes()).hexdigest()
    return repo, tmp_path / 'output', item, source


def export(repo, output, items):
    (repo / 'report-site/catalog.json').write_text(json.dumps({'schema': 1, 'reports': items}))
    return subprocess.run([sys.executable, '-m', MODULE, '--repo', str(repo), '--output', str(output)],
                          text=True, capture_output=True)


def test_exports_pinned_report_not_changed_working_copy(publication):
    repo, output, item, source = publication
    source.write_text('Unreviewed later content')
    (repo / 'private.db').write_text('excluded')
    result = export(repo, output, [item])
    assert result.returncode == 0, result.stderr
    report = (output / '_reports' / (item['id'] + '.md')).read_text()
    assert 'A scoped finding.' in report
    assert 'Unreviewed' not in report
    assert f"/blob/{item['revision']}/docs/METHOD.md#scope" in report
    assert item['sha256'] in report
    download = (output / 'sources' / (item['id'] + '.md')).read_bytes()
    assert b'Public edition.' in download
    assert hashlib.sha256(download).hexdigest() == item['edition_sha256']
    assert not (output / 'private.db').exists()
    assert not (output / 'catalog.json').exists()
    manifest = json.loads((output / 'manifest.json').read_text())
    assert manifest['reports'][0]['sha256'] == item['sha256']


def test_empty_catalog_does_not_export_existing_reports(publication):
    repo, output, _, _ = publication
    result = export(repo, output, [])
    assert result.returncode == 0, result.stderr
    assert json.loads((output / 'manifest.json').read_text())['reports'] == []
    assert list((output / '_reports').iterdir()) == []
    assert list((output / 'sources').iterdir()) == []
    assert (output / 'index.html').is_file()


@pytest.mark.parametrize('field,value', [('sha256', '0' * 64), ('source', '../../private.md'),
                                        ('revision', 'HEAD'), ('id', '../escape'),
                                        ('kind', 'unreviewed')])
def test_rejects_unpinned_or_invalid_publication(publication, field, value):
    repo, output, item, _ = publication
    item[field] = value
    result = export(repo, output, [item])
    assert result.returncode == 2
    assert result.stderr.startswith('report export:')
    assert not (output / '_reports').exists()


@pytest.mark.parametrize('payload', ['<script>alert(1)</script>', '{% endraw %}',
                                    'https://' + 'chatgpt.com' + '/c/' + 'private-fixture',
                                    '/home/operator/private-records',
                                    '[click](javascript:alert%281%29)'])
def test_rejects_unsafe_source_before_writing(publication, payload):
    repo, output, item, source = publication
    source.write_text('# Unsafe fixture\n\n' + payload + '\n')
    edition = repo / item['edition']
    edition.write_bytes(source.read_bytes())
    item['edition_sha256'] = hashlib.sha256(edition.read_bytes()).hexdigest()
    git(repo, 'add', 'docs')
    git(repo, '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Unsafe fixture')
    item['revision'] = git(repo, 'rev-parse', 'HEAD')
    item['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    result = export(repo, output, [item])
    assert result.returncode == 2
    assert result.stderr.startswith('report export:')
    assert payload not in result.stderr
    assert not (output / '_reports').exists()


def test_rejects_duplicate_ids(publication):
    repo, output, item, _ = publication
    assert export(repo, output, [item, item]).returncode == 2


def test_invalid_date_is_not_echoed(publication):
    repo, output, item, _ = publication
    item['date'] = 'private-fixture-do-not-echo'
    result = export(repo, output, [item])
    assert result.returncode == 2
    assert result.stderr.startswith('report export:')
    assert item['date'] not in result.stderr
    assert not output.exists()


def test_will_not_overwrite_existing_destination(publication):
    repo, output, item, _ = publication
    output.mkdir()
    (output / 'keep.txt').write_text('preserve')
    assert export(repo, output, [item]).returncode == 2
    assert (output / 'keep.txt').read_text() == 'preserve'


def test_rejects_changed_public_edition(publication):
    repo, output, item, _ = publication
    (repo / item['edition']).write_text('Unreviewed replacement')
    assert export(repo, output, [item]).returncode == 2
    assert not output.exists()


@pytest.mark.parametrize('relative', ['index.html', 'assets/library.js', 'assets/.env'])
def test_rejects_template_or_asset_contamination(publication, relative):
    repo, output, item, _ = publication
    target = repo / 'report-site' / relative
    target.parent.mkdir(exist_ok=True)
    target.write_text('password=fixture-private-value')
    result = export(repo, output, [item])
    assert result.returncode == 2
    assert 'fixture-private-value' not in result.stderr
    assert not output.exists()
