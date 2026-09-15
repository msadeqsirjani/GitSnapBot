from __future__ import annotations

from dataclasses import dataclass

NON_REPORT_KINDS = frozenset(
    {"welcome", "status", "help", "system", "preview", "brief", "last"}
)


@dataclass(frozen=True, slots=True)
class DeliveryPlan:
    preview: bool
    pin: bool
    clear_queue: bool
    save_archive: bool
    update_slot: bool


def plan_delivery(*, preview: bool, digest_pin: bool) -> DeliveryPlan:
    """Preview leaves the queue and pin list alone. Scheduled send commits."""
    if preview:
        return DeliveryPlan(
            preview=True,
            pin=False,
            clear_queue=False,
            save_archive=False,
            update_slot=False,
        )
    return DeliveryPlan(
        preview=False,
        pin=digest_pin,
        clear_queue=True,
        save_archive=True,
        update_slot=True,
    )
