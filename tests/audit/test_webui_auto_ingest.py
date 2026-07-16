from pathlib import Path

WEBUI = Path(__file__).resolve().parents[2] / "seam_runtime" / "webui" / "dashboard.html"


def _ingest_panel() -> str:
    dashboard = WEBUI.read_text(encoding="utf-8")
    return dashboard.split("// ── Ingest Panel", 1)[1].split("// ── Memory Panel", 1)[0]


def test_folder_picker_keeps_every_real_file_in_the_queue() -> None:
    panel = _ingest_panel()

    assert 'webkitdirectory=""' in panel
    assert "const selectedFiles = Array.from(e.target.files || [])" in panel
    assert "files.slice(0, 20)" not in panel
    assert "_file: f" in panel
    assert "f.webkitRelativePath || f.name" in panel
    assert "filesRef.current = nextFiles" in panel


def test_auto_ingest_drains_real_files_through_the_persist_api() -> None:
    panel = _ingest_panel()

    assert "enqueueFiles(fresh, 'persist', true)" in panel
    assert "const result = await window.SeamAPI.compile(text, persist, sourceRef)" in panel
    assert "const persist = task.mode === 'persist'" in panel
    assert "next.add(identity)" in panel
    assert "Auto-ingest enabled — selected folders will persist in queue order" in panel
    assert "eligibleStatuses = mode === 'persist' ? ['queued', 'error', 'preview']" in panel


def test_auto_ingest_has_no_simulated_success_path() -> None:
    panel = _ingest_panel()

    assert "Simulate agent" not in panel
    assert "Math.random" not in panel
    assert "setInterval" not in panel
    assert "seam-dash-ingest-files" not in panel
    assert "File handles cannot be serialized safely" in panel


def test_auto_folder_ingest_excludes_obvious_secret_and_generated_paths() -> None:
    panel = _ingest_panel()

    assert "AUTO_INGEST_EXCLUDED_DIRS" in panel
    assert "basename === '.env'" in panel
    assert "credential-shaped file" in panel
    assert "sensitive/generated skipped" in panel
    assert "dropped.filter((f) => !autoIngestExclusion" in panel
    assert "pickedFiles.filter((f) => !autoIngestExclusion" in panel


def test_ingest_bounds_file_reads_and_does_not_dedupe_loose_basenames() -> None:
    panel = _ingest_panel()

    assert "DASHBOARD_INGEST_MAX_FILE_BYTES = 4500000" in panel
    assert "fileEntry.sizeBytes > DASHBOARD_INGEST_MAX_FILE_BYTES" in panel
    assert "File exceeds the 4.5 MB dashboard ingest limit" in panel
    assert "_fingerprint: ''" in panel
    assert "const fingerprint = (f) => f._fingerprint || null" in panel
