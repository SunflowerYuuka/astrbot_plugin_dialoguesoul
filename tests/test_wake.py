import types
import unittest

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul import config as cfg
from dialoguesoul.wake import _RESERVATION_TTL, WakeLimits, WakeManager


def event(group="1", private=False, admin=False):
    return types.SimpleNamespace(
        get_platform_name=lambda: "p",
        get_self_id=lambda: "bot",
        is_private_chat=lambda: private,
        get_group_id=lambda: None if private else group,
        get_sender_id=lambda: "u",
        is_admin=lambda: admin,
    )


EVENT = event()


def config(**wake):
    return {
        "wake": {
            "enabled": True,
            "duration_seconds": 300,
            "max_replies": 2,
            "idle_timeout_seconds": 120,
            **wake,
        }
    }


class WakeTest(unittest.TestCase):
    def test_limits_and_group_override(self):
        manager = WakeManager()
        data = config(groups=[{"group_id": "1", "max_replies": "4"}])
        limits = manager.resolve_limits(EVENT, data)
        self.assertEqual(
            (limits.duration_seconds, limits.max_replies, limits.idle_timeout_seconds),
            (300, 4, 120),
        )

    def test_group_override_inherits_missing_fields(self):
        manager = WakeManager()
        data = config(
            groups=[
                {
                    "group_id": "1",
                    "duration_seconds": "",
                    "max_replies": 4,
                    "idle_timeout_seconds": None,
                }
            ]
        )
        limits = manager.resolve_limits(EVENT, data)
        self.assertEqual(
            (limits.duration_seconds, limits.max_replies, limits.idle_timeout_seconds),
            (300, 4, 120),
        )

    def test_invalid_override_falls_back_to_global(self):
        manager = WakeManager()
        data = config(
            duration_seconds=200,
            max_replies=3,
            idle_timeout_seconds=90,
            groups=[
                {
                    "group_id": "1",
                    "duration_seconds": "bad",
                    "max_replies": "nope",
                    "idle_timeout_seconds": "x",
                }
            ],
        )
        limits = manager.resolve_limits(EVENT, data)
        self.assertEqual(
            (limits.duration_seconds, limits.max_replies, limits.idle_timeout_seconds),
            (200, 3, 90),
        )

    def test_private_and_admin_defaults_from_config(self):
        manager = WakeManager()
        data = {"wake": cfg.DEFAULTS["wake"]}
        private = manager.resolve_limits(event(private=True), data)
        admin = manager.resolve_limits(event(admin=True), data)
        self.assertEqual(
            (private.duration_seconds, private.max_replies, private.idle_timeout_seconds),
            (300, 5, 120),
        )
        self.assertEqual(
            (admin.duration_seconds, admin.max_replies, admin.idle_timeout_seconds),
            (0, 0, 0),
        )

    def test_zero_means_unlimited(self):
        manager = WakeManager()
        data = config(duration_seconds=0, max_replies=0, idle_timeout_seconds=0)
        limits = manager.resolve_limits(EVENT, data)
        key = manager.key_for(EVENT)
        sid = "s1"
        manager.reserve(key, limits, sid, now=1)
        self.assertTrue(manager.record_delivery(key, limits, sid, starts_session=True, now=2))
        self.assertTrue(manager.is_active(key, now=10_000))
        self.assertTrue(manager.record_delivery(key, limits, sid, now=10_000))
        session = manager.get(key, now=1_000_000)
        self.assertIsNotNone(session)
        self.assertEqual(session.consumed_replies, 2)

    def test_expired_reservation_cannot_start_session(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(300, 2, 120)
        sid = "s1"
        manager.reserve(key, limits, sid, now=1)
        self.assertFalse(
            manager.record_delivery(
                key, limits, sid, starts_session=True, now=1 + _RESERVATION_TTL
            )
        )
        self.assertFalse(manager.is_active(key, now=1 + _RESERVATION_TTL))

        manager.reserve(key, limits, sid, now=1 + _RESERVATION_TTL)
        self.assertTrue(
            manager.record_delivery(
                key, limits, sid, starts_session=True, now=1 + _RESERVATION_TTL
            )
        )

    def test_clear_expired_prunes_stale_reservations(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(300, 2, 120)
        manager.reserve(key, limits, "s1", now=1)
        manager.clear_expired(now=1 + _RESERVATION_TTL)
        self.assertEqual(manager._reserved, {})

    def test_reserve_and_delivery_count(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(300, 3, 120)
        sid = "s1"
        manager.reserve(key, limits, sid, now=1)

        self.assertTrue(manager.record_delivery(key, limits, sid, starts_session=True, now=2))
        session = manager.get(key, now=2)
        self.assertEqual(session.session_id, sid)
        self.assertEqual(session.started_at, 2)
        self.assertEqual(session.last_activity_at, 2)
        self.assertEqual(session.consumed_replies, 1)

        self.assertTrue(manager.record_delivery(key, limits, sid, now=3))
        session = manager.get(key, now=3)
        self.assertEqual(session.last_activity_at, 3)
        self.assertEqual(session.consumed_replies, 2)

    def test_second_delivery_hits_cap(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(300, 2, 120)
        sid = "s1"
        manager.reserve(key, limits, sid, now=1)

        self.assertTrue(manager.record_delivery(key, limits, sid, starts_session=True, now=2))
        self.assertTrue(manager.is_active(key, now=2))
        self.assertTrue(manager.record_delivery(key, limits, sid, now=3))
        self.assertFalse(manager.is_active(key, now=3))

    def test_delivery_without_reservation_does_not_start(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(300, 2, 120)
        self.assertFalse(
            manager.record_delivery(key, limits, "missing", starts_session=True, now=1)
        )
        self.assertFalse(manager.is_active(key, now=1))

    def test_stale_reservation_does_not_reopen_closed_session(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(10, 5, 0)
        sid = "s1"
        manager.reserve(key, limits, sid, now=1)
        self.assertTrue(manager.record_delivery(key, limits, sid, starts_session=True, now=1))

        manager.reserve(key, limits, sid, now=2)
        self.assertFalse(
            manager.record_delivery(key, limits, sid, starts_session=True, now=100)
        )
        self.assertFalse(manager.is_active(key, now=100))

        manager.reserve(key, limits, "s2", now=100)
        self.assertTrue(
            manager.record_delivery(key, limits, "s2", starts_session=True, now=100)
        )

    def test_session_cleanup_keeps_newer_reservation(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(100, 5, 0)
        manager.reserve(key, limits, "old", now=1)
        self.assertTrue(
            manager.record_delivery(key, limits, "old", starts_session=True, now=2)
        )
        manager.reserve(key, limits, "new", now=50)

        manager.clear_expired(now=103)
        self.assertFalse(manager.is_active(key, now=103))
        self.assertTrue(
            manager.record_delivery(key, limits, "new", starts_session=True, now=103)
        )

    def test_mismatched_session_id_does_not_refresh(self):
        manager = WakeManager()
        key = manager.key_for(EVENT)
        limits = WakeLimits(300, 2, 120)
        sid = "s1"
        manager.reserve(key, limits, sid, now=1)
        self.assertTrue(manager.record_delivery(key, limits, sid, starts_session=True, now=2))

        self.assertFalse(manager.record_delivery(key, limits, "other", now=3))
        session = manager.get(key, now=3)
        self.assertEqual(session.session_id, sid)
        self.assertEqual(session.consumed_replies, 1)
        self.assertEqual(session.last_activity_at, 2)


if __name__ == "__main__":
    unittest.main()
