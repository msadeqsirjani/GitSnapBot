from pathlib import Path

from gitsnapbot.features.archive import load_report, save_report
from gitsnapbot.messages import Alert
from gitsnapbot.store import Store


def test_save_and_load_last_report(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    assert load_report(store) is None
    save_report(
        store,
        Alert(
            kind="digest",
            text="<h1>Report</h1>",
            fallback="Report",
            image_url="https://github.com/octocat.png",
        ),
    )
    loaded = load_report(store)
    assert loaded is not None
    assert loaded.kind == "last"
    assert loaded.text == "<h1>Report</h1>"
    assert loaded.fallback == "Report"
    assert loaded.image_url == "https://github.com/octocat.png"
    store.close()
