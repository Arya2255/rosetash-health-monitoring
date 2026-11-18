"""Operational alert contracts against real temporary SQLite databases.

Fixtures are synthetic input snapshots; production code and SQLite are real.
This suite imports no bridge, device, transport, or UI modules.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import operational_alerts as alerts

TEHRAN = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 11, 18, 12, tzinfo=TEHRAN).timestamp()
MAC = "aa:bb:cc:dd:ee:01"
MAC_2 = "aa:bb:cc:dd:ee:02"
ACTOR = "operator@example.test"


class OperationalAlertTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(
            prefix="operational-alerts-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "alerts.db"
        self.c = self.connect()
        self.addCleanup(lambda: self.c.close())

    def connect(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            alerts.ensure_schema(c)
            c.commit()
        except BaseException:
            c.close()
            raise
        return c

    def reopen(self):
        self.c.commit()
        self.c.close()
        self.c = self.connect()

    @staticmethod
    def person(**changes):
        return {
            "mac": MAC, "name": "Synthetic Employee", "registered": True,
            "scan_allowed": True, "status": "warn", "issues": ["hr_high"],
            "dept": "Unit A", "zone": "Hall A",
            "location": {"gw": "gw-a", "zone": "Hall A", "x": .2, "y": .3},
            **changes,
        }

    def snapshot(self, employees=(), gateways=(), at=NOW):
        alerts.sync(self.c, employees, gateways, at)
        return alerts.view(self.c, at)

    def test_schema_setup_does_not_commit_callers_transaction(self):
        self.c.execute("CREATE TABLE caller_work(value TEXT)")
        self.c.execute("INSERT INTO caller_work VALUES('uncommitted')")
        alerts.ensure_schema(self.c)
        self.c.close()
        self.c = self.connect()
        tables = {row["name"] for row in self.c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("caller_work", tables)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM caller_work").fetchone()[0], 0)
        self.assertIn("operational_alerts", tables)

    def test_ineligible_or_cleared_health_is_not_reported(self):
        for index, employee in enumerate((
            self.person(registered=False),
            self.person(scan_allowed=False),
            self.person(status="off"),
            self.person(issues=[]),
        )):
            with self.subTest(ineligible_case=index):
                self.assertEqual(self.snapshot([employee])["alerts_active"], [])
        eligible = self.snapshot([self.person()])
        self.assertEqual(len(eligible["alerts_active"]), 1)

    def test_health_episode_closes_on_recovery_and_reopens_with_new_id(self):
        person = self.person(
            issues=["hr_high", "hr_high"],
            health={"avg": 250, "bpm": [250], "medical_detail": "synthetic-private"},
            vitals={"spo2": 2},
        )
        first = self.snapshot([person])
        episode = first["alerts_active"][0]
        self.assertNotIn("health", episode)
        self.assertNotIn("vitals", episode)
        self.assertNotIn("bpm", episode)
        self.assertNotIn("spo2", episode)
        self.assertEqual(episode["source"], "live")
        self.assertEqual(episode["type"], "hr_high")
        self.assertEqual(episode["status"], "open")
        self.assertEqual(episode["emp"], "Synthetic Employee")
        self.assertEqual(episode["mac"], MAC)
        self.assertEqual(episode["location"], "Hall A")
        self.assertEqual(datetime.fromisoformat(episode["time"]).timestamp(), NOW)

        for at in (NOW + 1, NOW + 2):
            repeated = self.snapshot([person], at=at)
            self.assertEqual(repeated["alerts_active"], [episode])
            self.assertEqual(repeated["alerts_history"], [])
        self.reopen()
        self.assertEqual(self.snapshot([person], at=NOW + 3)["alerts_active"], [episode])

        recovered = self.snapshot([self.person(status="ok", issues=[])], at=NOW + 4)
        self.assertEqual(recovered["alerts_active"], [])
        self.assertEqual(recovered["alerts_history"][0]["id"], episode["id"])
        self.assertEqual(recovered["alerts_history"][0]["status"], "closed")

        later = self.snapshot([self.person()], at=NOW + 5)
        self.assertEqual(len(later["alerts_active"]), 1)
        self.assertNotEqual(later["alerts_active"][0]["id"], episode["id"])
        self.assertEqual(len(later["alerts_history"]), 1)

    def test_acknowledgement_persists_and_does_not_clear_live_condition(self):
        alert = self.snapshot([self.person()])["alerts_active"][0]
        self.assertEqual(alert["acknowledged_by"], None)
        self.assertEqual(alerts.acknowledge(self.c, alert["id"], ACTOR, NOW + 1), (True, ""))
        self.c.commit()
        self.assertEqual(self.c.execute(
            "SELECT acknowledged_at FROM operational_alerts WHERE id=?", (alert["id"],)
        ).fetchone()["acknowledged_at"], NOW + 1)
        self.reopen()

        acknowledged = self.snapshot([self.person()], at=NOW + 2)
        self.assertEqual(len(acknowledged["alerts_active"]), 1)
        self.assertEqual(acknowledged["alerts_active"][0]["status"], "acknowledged")
        self.assertEqual(acknowledged["alerts_active"][0]["acknowledged_by"], ACTOR)
        self.assertEqual(alerts.acknowledge(self.c, alert["id"], "another-actor", NOW + 3),
                         (True, ""))
        self.assertEqual(alerts.view(self.c, NOW + 3)["alerts_active"][0]["acknowledged_by"], ACTOR)
        self.assertEqual(alerts.acknowledge(self.c, "missing", ACTOR, NOW + 3),
                         (False, "alert_not_found"))
        self.assertEqual(alerts.acknowledge(self.c, alert["id"], " ", NOW + 3),
                         (False, "actor_required"))

        closed = self.snapshot([], at=NOW + 4)
        self.assertEqual(closed["alerts_active"], [])
        self.assertEqual(closed["alerts_history"][0]["status"], "closed")
        self.assertEqual(closed["alerts_history"][0]["acknowledged_by"], ACTOR)
        self.assertEqual(alerts.acknowledge(self.c, alert["id"], ACTOR, NOW + 5),
                         (False, "alert_closed"))

    def test_gateway_offline_episode_requires_prior_sighting_and_installed_kind(self):
        gateways = [
            {"gw": "gw-never", "label": "Never online", "zone": "Hall N",
             "registered": True, "kind": "installed", "online": False,
            "last_seen": None, "ever_seen": False},
            {"gw": "gw-discovery", "label": "Discovery", "zone": "Hall D",
             "registered": True, "kind": "proposed", "online": False,
             "last_seen": NOW - 10},
            {"gw": "gw-unknown", "label": "Unknown", "zone": "Hall U",
             "registered": False, "kind": "installed", "online": False,
             "last_seen": NOW - 10},
        ]
        self.assertEqual(self.snapshot(gateways=gateways)["alerts_active"], [])
        gateways[0]["last_seen"] = NOW - 10
        # A positive last_seen is evidence it was provisioned/online earlier;
        # the bridge's offline bit already incorporates its 180-second TTL.
        gateways[0]["online"] = True
        online = self.snapshot(gateways=gateways, at=NOW + 2)
        self.assertEqual(online["alerts_active"], [])
        gateways[0]["online"] = False
        offline = self.snapshot(gateways=gateways, at=NOW + 3)
        self.assertEqual(len(offline["alerts_active"]), 1)
        episode = offline["alerts_active"][0]
        self.assertEqual((episode["type"], episode["gw"], episode["location"]),
                         ("gateway_offline", "gw-never", "Hall N"))
        self.assertEqual(len(self.snapshot(gateways=gateways, at=NOW + 4)["alerts_active"]), 1)

        gateways[0]["online"] = True
        recovered = self.snapshot(gateways=gateways, at=NOW + 5)
        self.assertEqual(recovered["alerts_active"], [])
        self.assertEqual(recovered["alerts_history"][0]["status"], "closed")
        gateways[0]["online"] = False
        reopened = self.snapshot(gateways=gateways, at=NOW + 6)
        self.assertNotEqual(reopened["alerts_active"][0]["id"], episode["id"])

    def test_gateway_explicit_ttl_boundary_opens_only_after_expiry(self):
        gateway = {
            "gw": "gw-ttl", "label": "TTL gateway", "zone": "Hall T",
            "registered": True, "kind": "installed", "online": True,
            "last_seen": NOW - 179,
        }
        self.assertEqual(self.snapshot(gateways=[gateway])["alerts_active"], [])
        gateway.update(online=False, last_seen=NOW - 181)
        self.assertEqual(len(self.snapshot(gateways=[gateway], at=NOW + 2)["alerts_active"]), 1)
        iso_gateway = {
            "gw": "gw-iso", "label": "ISO gateway", "zone": "Hall ISO",
            "registered": True, "kind": "installed", "online": False,
            "last_seen": datetime.fromtimestamp(NOW - 200, TEHRAN).isoformat(),
        }
        self.assertEqual(len(self.snapshot(gateways=[gateway, iso_gateway], at=NOW + 2)["alerts_active"]), 2)

    def test_history_is_bounded_to_current_tehran_day_and_100_rows(self):
        previous_day = NOW - 24 * 60 * 60
        yesterday = self.snapshot([self.person()], at=previous_day)["alerts_active"][0]
        self.snapshot([], at=previous_day + 1)
        self.assertNotIn(yesterday["id"], {
            row["id"] for row in self.snapshot([], at=NOW)["alerts_history"]
        })

        spanning = self.person(mac=MAC_2, issues=["spo2_low"])
        opened_yesterday = self.snapshot([spanning], at=NOW - 13 * 60 * 60)["alerts_active"][0]
        self.snapshot([], at=NOW + 1)
        history = self.snapshot([], at=NOW + 2)["alerts_history"]
        self.assertEqual(history[0]["id"], opened_yesterday["id"])
        self.assertEqual(datetime.fromisoformat(history[0]["time"]).timestamp(), NOW + 1)

        for second in range(2, 106):
            self.snapshot([self.person()], at=NOW + second)
            self.snapshot([], at=NOW + second + .25)
        history = self.snapshot([], at=NOW + 200)["alerts_history"]
        self.assertEqual(len(history), 100)
        self.assertEqual(history, sorted(history, key=lambda item: item["time"], reverse=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
