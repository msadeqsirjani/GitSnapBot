from gitsnapbot.messages import format_follow
from gitsnapbot.ui import BUTTON_TO_COMMAND, BTN_STATUS, activity_inline, main_keyboard, status_inline


def test_reply_keyboard_swaps_pause_resume() -> None:
    running = main_keyboard(paused=False)
    paused = main_keyboard(paused=True)
    assert running["is_persistent"] is True
    labels_running = {btn["text"] for row in running["keyboard"] for btn in row}
    labels_paused = {btn["text"] for row in paused["keyboard"] for btn in row}
    assert "⏸ Pause" in labels_running
    assert "📬 Report" in labels_running
    assert "🗂 Last report" in labels_running
    assert "▶️ Resume" in labels_paused
    assert BUTTON_TO_COMMAND[BTN_STATUS] == "/status"


def test_activity_inline_has_profile_and_open() -> None:
    alert = format_follow("octocat", 3)
    markup = activity_inline(alert)
    assert markup is not None
    buttons = markup["inline_keyboard"][0]
    assert any(btn["text"] == "View profile" for btn in buttons)
    assert any(btn["text"] == "Open on GitHub" for btn in buttons)


def test_status_inline_callback() -> None:
    markup = status_inline(paused=False)
    data = {btn["callback_data"] for row in markup["inline_keyboard"] for btn in row}
    assert "status" in data
    assert "pause" in data
