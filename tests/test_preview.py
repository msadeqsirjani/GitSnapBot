from gitsnapbot.features.preview import NON_REPORT_KINDS, plan_delivery


def test_preview_does_not_commit_or_pin() -> None:
    plan = plan_delivery(preview=True, digest_pin=True)
    assert plan.preview is True
    assert plan.pin is False
    assert plan.clear_queue is False
    assert plan.save_archive is False
    assert plan.update_slot is False


def test_scheduled_send_commits_and_respects_pin_flag() -> None:
    pinned = plan_delivery(preview=False, digest_pin=True)
    assert pinned.preview is False
    assert pinned.pin is True
    assert pinned.clear_queue is True
    assert pinned.save_archive is True
    assert pinned.update_slot is True
    unpinned = plan_delivery(preview=False, digest_pin=False)
    assert unpinned.pin is False
    assert unpinned.clear_queue is True


def test_non_report_kinds_exclude_preview_and_last() -> None:
    assert "preview" in NON_REPORT_KINDS
    assert "last" in NON_REPORT_KINDS
    assert "digest" not in NON_REPORT_KINDS
