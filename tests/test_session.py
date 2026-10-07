import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from wyld_together.session import GAME_BUILD, MAX_PLAYERS, PROTOCOL, Rejected, SessionStore


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "party.sqlite"
        self.store = SessionStore(self.path)
        self.party = self.store.create("host", "start")["id"]
        self.store.apply(self.party, "guest", "join", self.connection("join"))

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    @staticmethod
    def connection(kind):
        return {"type": kind, "build": GAME_BUILD, "protocol": PROTOCOL}

    def event(self, actor, request, kind, **fields):
        return self.store.apply(self.party, actor, request, {"type": kind, **fields})

    def test_death_and_boss_defeat_keep_party(self):
        self.event("guest", "dead", "death")
        state = self.event("host", "boss", "boss_defeated", boss="boss-1")
        self.assertEqual(set(state["players"]), {"host", "guest"})
        self.assertTrue(state["players"]["guest"]["connected"])
        self.assertFalse(state["players"]["guest"]["alive"])
        self.assertEqual(state["bosses"], ["boss-1"])
        self.assertEqual(state["status"], "active")

    def test_rest_revives_whole_party_at_shared_checkpoint(self):
        self.event("guest", "dead", "death")
        self.event("host", "dead", "death")
        state = self.event("host", "rest", "rest", checkpoint="next")
        self.assertEqual(state["epoch"], 1)
        for player in state["players"].values():
            self.assertTrue(player["alive"])
            self.assertEqual(player["checkpoint"], "next")

    def test_network_loss_does_not_remove_member_or_revive_them(self):
        self.event("guest", "dead", "death")
        self.event("guest", "lost", "disconnect")
        state = self.store.apply(self.party, "guest", "back", self.connection("reconnect"))
        self.assertTrue(state["players"]["guest"]["connected"])
        self.assertFalse(state["players"]["guest"]["alive"])

    def test_host_loss_pauses_until_same_host_returns(self):
        state = self.event("host", "lost", "disconnect")
        self.assertEqual(state["status"], "paused")
        with self.assertRaises(Rejected):
            self.event("guest", "boss", "boss_defeated", boss="fake")
        state = self.store.apply(self.party, "host", "back", self.connection("reconnect"))
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["host"], "host")

    def test_guest_cannot_commit_world_progress(self):
        before = self.store.snapshot(self.party)
        for command in ({"type": "rest", "checkpoint": "cheat"}, {"type": "boss_defeated", "boss": "fake"}):
            with self.assertRaises(Rejected):
                self.store.apply(self.party, "guest", "bad", command)
        self.assertEqual(self.store.snapshot(self.party), before)

    def test_retried_event_does_not_apply_twice(self):
        first = self.event("host", "rest", "rest", checkpoint="next")
        again = self.event("host", "rest", "rest", checkpoint="next")
        self.assertEqual(first, again)
        self.assertEqual(again["epoch"], 1)

    def test_conflicting_request_id_is_rejected(self):
        self.event("host", "rest", "rest", checkpoint="next")
        with self.assertRaises(Rejected):
            self.event("host", "rest", "rest", checkpoint="different")
        self.assertEqual(self.store.snapshot(self.party)["checkpoint"], "next")

    def test_stale_revision_rolls_back(self):
        before = self.store.snapshot(self.party)
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "host", "stale", {"type": "rest", "checkpoint": "next"}, expected_revision=0)
        self.assertEqual(self.store.snapshot(self.party), before)

    def test_wrong_build_or_protocol_cannot_join(self):
        for changes in ({"build": "wrong"}, {"protocol": 999}):
            with self.assertRaises(Rejected):
                self.store.apply(self.party, "outsider", "bad", self.connection("join") | changes)
        self.assertNotIn("outsider", self.store.snapshot(self.party)["players"])

    def test_full_party_reserves_disconnected_players_slot(self):
        for number in range(MAX_PLAYERS - 2):
            self.store.apply(self.party, f"peer{number}", "join", self.connection("join"))
        self.event("guest", "lost", "disconnect")
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "extra", "join", self.connection("join"))
        self.store.apply(self.party, "guest", "back", self.connection("reconnect"))

    def test_unknown_member_cannot_reconnect_or_send_events(self):
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "stranger", "back", self.connection("reconnect"))
        with self.assertRaises(Rejected):
            self.event("stranger", "dead", "death")

    def test_intentional_leave_and_host_close(self):
        state = self.event("guest", "leave", "leave")
        self.assertNotIn("guest", state["players"])
        state = self.event("host", "leave", "leave")
        self.assertEqual(state["status"], "closed")
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "host", "back", self.connection("reconnect"))

    def test_restart_preserves_progress_and_requires_reconnect(self):
        self.event("host", "boss", "boss_defeated", boss="boss-1")
        self.event("host", "rest", "rest", checkpoint="next")
        self.store.close()
        self.store = SessionStore(self.path)
        self.store.recover_after_restart()
        state = self.store.snapshot(self.party)
        self.assertEqual(state["bosses"], ["boss-1"])
        self.assertEqual(state["checkpoint"], "next")
        self.assertEqual(state["status"], "paused")
        self.assertFalse(any(p["connected"] for p in state["players"].values()))
        self.store.recover_after_restart()
        self.assertEqual(self.store.snapshot(self.party), state)
        self.store.apply(self.party, "host", "back", self.connection("reconnect"))
        # Replaying a pre-crash checkpoint event must not reset the world again.
        self.assertEqual(self.event("host", "rest", "rest", checkpoint="next")["epoch"], 1)

    def test_malformed_event_leaves_no_partial_mutation(self):
        before = self.store.snapshot(self.party)
        with self.assertRaises(Rejected):
            self.event("host", "bad", "rest", checkpoint="")
        with self.assertRaises(Rejected):
            self.event("host", "bad", "death", unexpected=True)
        self.assertEqual(self.store.snapshot(self.party), before)

    def test_concurrent_connections_do_not_lose_updates(self):
        def defeat(number):
            store = SessionStore(self.path)
            try:
                return store.apply(self.party, "host", f"boss-{number}", {"type": "boss_defeated", "boss": f"boss-{number}"})
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(defeat, range(8)))
        state = self.store.snapshot(self.party)
        self.assertEqual(len(state["bosses"]), 8)
        self.assertEqual(state["revision"], 9)


if __name__ == "__main__":
    unittest.main()
