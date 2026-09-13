"""The final public artifact must reject confidential material without echoing it."""
from pathlib import Path

import pytest

from tools.reports.publication_safety import PublicationSafetyError, scan_site, validate_text


@pytest.mark.parametrize('payload', [
    'github_' + 'pat_' + 'a' * 30,
    'sk-' + 'ant-' + 'a' * 30,
    'Authorization: Bearer fixture-private-value',
    'password=' + 'fixture-private-value',
    'SEAM_' + 'DB_PATH',
    'CUSTOM_' + 'SETTING=fixture-value',
    'process.' + 'env.SOME_VALUE',
    'https://' + 'claude.ai' + '/chat/' + 'private-fixture',
    'https%3A%2F%2F' + 'chatgpt.com%2Fc%2Fprivate-fixture',
    'https://example.invalid/report?access_token=fixture-private-value',
    'https://operator:fixture-private-value@example.invalid',
    '/home/operator/private-records',
])
def test_confidential_content_is_rejected_without_echo(payload):
    with pytest.raises(PublicationSafetyError) as rejected:
        validate_text(payload)
    assert payload not in str(rejected.value)


@pytest.mark.parametrize('relative,content', [
    ('assets/accidental.js', b'const harmless = true;'),
    ('.env', b'fixture-content'),
    ('debug.log', b'fixture-content'),
    ('assets/library.js', b'\x00uninspectable'),
    ('assets/reports.css', b'/* password=fixture-value */'),
    ('manifest.json', b'{"note":"SEAM_DB_PATH"}'),
    ('feed.xml', b'<summary>Authorization: Bearer fixture-value</summary>'),
    ('sources/2026-09-12-result.md', b'SEAM_DB_PATH'),
    ('reports/2026-09-12-result/index.html', b'SEAM_DB_PATH'),
])
def test_scans_every_output_surface_and_rejects_unexpected_files(tmp_path, relative, content):
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    with pytest.raises(PublicationSafetyError):
        scan_site(tmp_path)


def test_accepts_plain_public_text_assets_and_metadata(tmp_path):
    for relative, text in {'index.html': '<h1>Public findings</h1>',
                           'manifest.json': '{"schema":1}',
                           'assets/library.js': 'const reports = [];',
                           'assets/reports.css': 'body { color: #c0caf5; }'}.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert scan_site(tmp_path) == 4


def test_rejects_symlink_to_material_outside_artifact(tmp_path):
    (tmp_path / 'index.html').symlink_to(Path(__file__))
    with pytest.raises(PublicationSafetyError):
        scan_site(tmp_path)
