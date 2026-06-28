from pathlib import Path


WEBUI_DIR = Path(__file__).resolve().parents[2] / "seam_runtime" / "webui"


def test_webui_chat_sends_persist_chat_flag() -> None:
    api_js = (WEBUI_DIR / "seam-api.js").read_text(encoding="utf-8")
    dashboard = (WEBUI_DIR / "dashboard.html").read_text(encoding="utf-8")

    assert "persist_chat" in api_js
    assert "persistChat" in dashboard
    assert "setPersistChat" in dashboard
    assert "persistChat: persistChat" in dashboard
