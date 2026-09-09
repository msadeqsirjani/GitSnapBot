from __future__ import annotations

from typing import Any

from gitsnapbot.messages import Alert

BTN_STATUS = "📊 Status"
BTN_DIGEST = "📬 Report"
BTN_PAUSE = "⏸ Pause"
BTN_RESUME = "▶️ Resume"
BTN_HELP = "❓ Help"

BUTTON_TO_COMMAND = {
    BTN_STATUS: "/status",
    BTN_DIGEST: "/digest",
    BTN_PAUSE: "/pause",
    BTN_RESUME: "/resume",
    BTN_HELP: "/help",
}

BOT_COMMANDS = [
    {"command": "start", "description": "Open dashboard"},
    {"command": "status", "description": "Live snapshot"},
    {"command": "digest", "description": "Send the weekly report now"},
    {"command": "pause", "description": "Pause collection"},
    {"command": "resume", "description": "Resume collection"},
    {"command": "help", "description": "How this bot works"},
]

HELP_RICH = """
<h2>GitSnapBot</h2>
<p>GitHub activity is collected all week. One weekly report is sent at the time set in <code>.env</code>.</p>
<hr/>
<ul>
  <li><b>Menu</b> next to the input field — native command list</li>
  <li><b>Buttons</b> under the chat — Status, Report, Pause</li>
</ul>
<table bordered striped compact>
  <tr><th>/start</th><td>Connect this chat</td></tr>
  <tr><th>/status</th><td>Queue size and next report time</td></tr>
  <tr><th>/digest</th><td>Send the weekly report now</td></tr>
  <tr><th>/pause</th><td>Stop collecting</td></tr>
  <tr><th>/resume</th><td>Start collecting again</td></tr>
</table>
<footer>GitHub does not expose profile page views. Repo traffic is reported instead.</footer>
<footer>✦ GitSnapBot</footer>
"""

HELP_FALLBACK = (
    "<b>GitSnapBot</b>\n"
    "GitHub activity is collected all week and sent as one report.\n\n"
    "Use the buttons under the chat, or tap <b>Menu</b> next to the input field.\n\n"
    "/start — connect this chat\n"
    "/status — queue and next report time\n"
    "/digest — send the weekly report now\n"
    "/pause — stop collecting\n"
    "/resume — start collecting again\n\n"
    "<i>✦ GitSnapBot</i>"
)


def main_keyboard(paused: bool) -> dict[str, Any]:
    toggle = BTN_RESUME if paused else BTN_PAUSE
    return {
        "keyboard": [
            [{"text": BTN_STATUS}, {"text": BTN_DIGEST}],
            [{"text": toggle}, {"text": BTN_HELP}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Alerts arrive automatically…",
    }


def activity_inline(alert: Alert) -> dict[str, Any] | None:
    row: list[dict[str, str]] = []
    if alert.actor:
        row.append({"text": "👤 Profile", "url": f"https://github.com/{alert.actor}"})
    if alert.url:
        row.append({"text": "🔗 Open", "url": alert.url})
    if not row:
        return None
    return {"inline_keyboard": [row]}


def status_inline(paused: bool) -> dict[str, Any]:
    toggle = (
        {"text": "▶️ Resume", "callback_data": "resume"}
        if paused
        else {"text": "⏸ Pause", "callback_data": "pause"}
    )
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Refresh", "callback_data": "status"},
                toggle,
            ]
        ]
    }



