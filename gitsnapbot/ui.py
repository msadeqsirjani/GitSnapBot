from __future__ import annotations

from typing import Any

from gitsnapbot.messages import Alert

BTN_STATUS = "📊 Status"
BTN_DIGEST = "📬 Report"
BTN_LAST = "🗂 Last report"
BTN_PAUSE = "⏸ Pause"
BTN_RESUME = "▶️ Resume"
BTN_HELP = "❓ Help"

BUTTON_TO_COMMAND = {
    BTN_STATUS: "/status",
    BTN_DIGEST: "/digest",
    BTN_LAST: "/last",
    BTN_PAUSE: "/pause",
    BTN_RESUME: "/resume",
    BTN_HELP: "/help",
}

BOT_COMMANDS = [
    {"command": "start", "description": "Connect this chat and show status"},
    {"command": "status", "description": "Queue, next report, and API quota"},
    {"command": "digest", "description": "Preview the current queue (does not send the week)"},
    {"command": "last", "description": "Show the last scheduled report"},
    {"command": "when", "description": "Show or change the report schedule"},
    {"command": "pause", "description": "Pause GitHub collection"},
    {"command": "resume", "description": "Resume GitHub collection"},
    {"command": "help", "description": "Commands and reporting limits"},
]

HELP_RICH = """
<h2>GitSnapBot</h2>
<p>GitHub activity is collected throughout the week and delivered as one scheduled report. Report is a preview and does not clear the queue or replace the pin.</p>
<hr/>
<ul>
  <li><b>Menu</b> next to the input field lists available commands</li>
  <li>The keyboard below the chat provides Status, Report, Last report, and Pause</li>
</ul>
<table bordered striped compact>
  <tr><th>/start</th><td>Connect this chat</td></tr>
  <tr><th>/status</th><td>Queue size and next report time</td></tr>
  <tr><th>/digest</th><td>Preview the current queue</td></tr>
  <tr><th>/last</th><td>Show the last scheduled report</td></tr>
  <tr><th>/when</th><td>Show the schedule</td></tr>
  <tr><th>/when monday 9:00</th><td>Set the weekly slot</td></tr>
  <tr><th>/when timezone Asia/Tehran</th><td>Set the timezone</td></tr>
  <tr><th>/when brief on</th><td>Enable the daily brief</td></tr>
  <tr><th>/pause</th><td>Pause collection</td></tr>
  <tr><th>/resume</th><td>Resume collection</td></tr>
</table>
<footer>GitHub does not expose profile page views. Repository traffic is reported instead.</footer>
<footer>GitSnapBot</footer>
"""

HELP_FALLBACK = (
    "<b>GitSnapBot</b>\n"
    "GitHub activity is collected throughout the week and delivered as one scheduled report.\n"
    "Report is a preview and does not clear the queue.\n\n"
    "Use the keyboard below the chat, or open <b>Menu</b> next to the input field.\n\n"
    "/start — connect this chat\n"
    "/status — queue size and next report time\n"
    "/digest — preview the current queue\n"
    "/last — last scheduled report\n"
    "/when — show or change the schedule\n"
    "/pause — pause collection\n"
    "/resume — resume collection\n\n"
    "<i>GitSnapBot</i>"
)


def main_keyboard(paused: bool) -> dict[str, Any]:
    toggle = BTN_RESUME if paused else BTN_PAUSE
    return {
        "keyboard": [
            [{"text": BTN_STATUS}, {"text": BTN_DIGEST}, {"text": BTN_LAST}],
            [{"text": toggle}, {"text": BTN_HELP}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Use a command or the keyboard",
    }


def activity_inline(alert: Alert) -> dict[str, Any] | None:
    row: list[dict[str, str]] = []
    if alert.actor:
        row.append({"text": "View profile", "url": f"https://github.com/{alert.actor}"})
    if alert.url:
        row.append({"text": "Open on GitHub", "url": alert.url})
    if not row:
        return None
    return {"inline_keyboard": [row]}


def status_inline(paused: bool) -> dict[str, Any]:
    toggle = (
        {"text": "Resume collection", "callback_data": "resume"}
        if paused
        else {"text": "Pause collection", "callback_data": "pause"}
    )
    return {
        "inline_keyboard": [
            [
                {"text": "Refresh", "callback_data": "status"},
                toggle,
            ]
        ]
    }
