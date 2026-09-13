"""A pull request or an empty catalog must never become a Pages publication."""
from pathlib import Path

import yaml


def test_pages_upload_and_deploy_require_main_reports_and_successful_safety_gate():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / '.github/workflows/reports-pages.yml').read_text())
    assert workflow['permissions'] == {'contents': 'read'}
    build = workflow['jobs']['build']
    deploy = workflow['jobs']['deploy']
    assert deploy['needs'] == 'build'
    assert deploy['permissions'] == {'pages': 'write', 'id-token': 'write'}
    assert deploy['environment']['name'] == 'github-pages'
    assert deploy['concurrency'] == {'group': 'pages', 'cancel-in-progress': False}
    boundary = "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'"
    assert deploy['if'] == boundary + " && needs.build.outputs.report_count != '0'"
    steps = build['steps']
    safety = next(i for i, step in enumerate(steps) if step.get('id') == 'privacy')
    upload = next(i for i, step in enumerate(steps)
                  if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
    assert upload > safety
    assert steps[upload]['if'] == boundary + " && steps.publication.outputs.report_count != '0'"
    assert steps[upload]['with']['path'] == 'test_seam/report-site/site'
    assert steps[safety]['run'].strip() == (
        'python -m tools.reports.publication_safety --site test_seam/report-site/site'
    )
    assert all(not step.get('continue-on-error') for step in steps)
    assert 'if' not in steps[safety]
    assert 'pull_request_target' not in workflow.get('on', workflow.get(True, {}))
