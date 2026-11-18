# Program: ds3-together - test_session.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Unit tests that check the party rules in session.py (death, rest, host loss, retries, restart recovery and concurrency).

# ---------------- Imports ----------------
# tempfile makes a temporary folder so tests never touch real data.
import tempfile
# unittest is Python's built-in testing framework.
import unittest
# A thread pool lets one test run several database writers at once.
from concurrent.futures import ThreadPoolExecutor
# Path builds file locations.
from pathlib import Path

# The code under test and its constants.
from wyld_together.session import GAME_BUILD, MAX_PLAYERS, PROTOCOL, Rejected, SessionStore


# All tests live in one class; unittest runs every method whose name starts with "test".
class SessionTests(unittest.TestCase):
    """Tests for the SessionStore party rules."""
    def setUp(self):
        """Before each test: make a fresh temporary database with a host and one guest in a party."""
        # A throwaway folder that is deleted after the test.
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "party.sqlite"
        # Open a store on a new database file.
        self.store = SessionStore(self.path)
        # Create a party owned by "host" and remember its id.
        self.party = self.store.create("host", "start")["id"]
        # Have "guest" join so most tests start with two players.
        self.store.apply(self.party, "guest", "join", self.connection("join"))

    def tearDown(self):
        """After each test: close the database and delete the temporary folder."""
        self.store.close()
        self.directory.cleanup()

    # A helper that builds a join/reconnect command carrying the right build and protocol.
    @staticmethod
    def connection(kind):
        """Return a join or reconnect command dictionary for the current build and protocol."""
        return {"type": kind, "build": GAME_BUILD, "protocol": PROTOCOL}

    def event(self, actor, request, kind, **fields):
        """Apply one event of type `kind` for `actor` in the test party and return the new state."""
        return self.store.apply(self.party, actor, request, {"type": kind, **fields})

    # A guest dying and the host beating a boss must not remove anyone from the party.
    def test_death_and_boss_defeat_keep_party(self):
        self.event("guest", "dead", "death")
        state = self.event("host", "boss", "boss_defeated", boss="boss-1")
        self.assertEqual(set(state["players"]), {"host", "guest"})
        self.assertTrue(state["players"]["guest"]["connected"])
        self.assertFalse(state["players"]["guest"]["alive"])
        self.assertEqual(state["bosses"], ["boss-1"])
        self.assertEqual(state["status"], "active")

    # Resting brings every dead member back at the new checkpoint and raises the epoch to 1.
    def test_rest_revives_whole_party_at_shared_checkpoint(self):
        self.event("guest", "dead", "death")
        self.event("host", "dead", "death")
        state = self.event("host", "rest", "rest", checkpoint="next")
        self.assertEqual(state["epoch"], 1)
        for player in state["players"].values():
            self.assertTrue(player["alive"])
            self.assertEqual(player["checkpoint"], "next")

    # Disconnecting and reconnecting must keep a dead player dead (it is not a free revive).
    def test_network_loss_does_not_remove_member_or_revive_them(self):
        self.event("guest", "dead", "death")
        self.event("guest", "lost", "disconnect")
        state = self.store.apply(self.party, "guest", "back", self.connection("reconnect"))
        self.assertTrue(state["players"]["guest"]["connected"])
        self.assertFalse(state["players"]["guest"]["alive"])

    # When the host disconnects the party pauses and guests cannot change progress until the host returns.
    def test_host_loss_pauses_until_same_host_returns(self):
        state = self.event("host", "lost", "disconnect")
        self.assertEqual(state["status"], "paused")
        with self.assertRaises(Rejected):
            self.event("guest", "boss", "boss_defeated", boss="fake")
        state = self.store.apply(self.party, "host", "back", self.connection("reconnect"))
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["host"], "host")

    # Guests may not rest or defeat bosses, and a rejected command must leave the state untouched.
    def test_guest_cannot_commit_world_progress(self):
        before = self.store.snapshot(self.party)
        for command in ({"type": "rest", "checkpoint": "cheat"}, {"type": "boss_defeated", "boss": "fake"}):
            with self.assertRaises(Rejected):
                self.store.apply(self.party, "guest", "bad", command)
        self.assertEqual(self.store.snapshot(self.party), before)

    # Sending the same request twice gives the same result and applies only once.
    def test_retried_event_does_not_apply_twice(self):
        first = self.event("host", "rest", "rest", checkpoint="next")
        again = self.event("host", "rest", "rest", checkpoint="next")
        self.assertEqual(first, again)
        self.assertEqual(again["epoch"], 1)

    # Reusing a request id with different data is rejected and changes nothing.
    def test_conflicting_request_id_is_rejected(self):
        self.event("host", "rest", "rest", checkpoint="next")
        with self.assertRaises(Rejected):
            self.event("host", "rest", "rest", checkpoint="different")
        self.assertEqual(self.store.snapshot(self.party)["checkpoint"], "next")

    # A command expecting an old revision number is rejected and the state is unchanged.
    def test_stale_revision_rolls_back(self):
        before = self.store.snapshot(self.party)
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "host", "stale", {"type": "rest", "checkpoint": "next"}, expected_revision=0)
        self.assertEqual(self.store.snapshot(self.party), before)

    # Joining with a different game build or protocol is refused.
    def test_wrong_build_or_protocol_cannot_join(self):
        for changes in ({"build": "wrong"}, {"protocol": 999}):
            with self.assertRaises(Rejected):
                self.store.apply(self.party, "outsider", "bad", self.connection("join") | changes)
        self.assertNotIn("outsider", self.store.snapshot(self.party)["players"])

    # A disconnected member still holds a slot, so a full party cannot admit a newcomer.
    def test_full_party_reserves_disconnected_players_slot(self):
        for number in range(MAX_PLAYERS - 2):
            self.store.apply(self.party, f"peer{number}", "join", self.connection("join"))
        self.event("guest", "lost", "disconnect")
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "extra", "join", self.connection("join"))
        self.store.apply(self.party, "guest", "back", self.connection("reconnect"))

    # People who never joined cannot reconnect or send events.
    def test_unknown_member_cannot_reconnect_or_send_events(self):
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "stranger", "back", self.connection("reconnect"))
        with self.assertRaises(Rejected):
            self.event("stranger", "dead", "death")

    # A guest leaving removes them; the host leaving closes the party for good.
    def test_intentional_leave_and_host_close(self):
        state = self.event("guest", "leave", "leave")
        self.assertNotIn("guest", state["players"])
        state = self.event("host", "leave", "leave")
        self.assertEqual(state["status"], "closed")
        with self.assertRaises(Rejected):
            self.store.apply(self.party, "host", "back", self.connection("reconnect"))

    # After a simulated crash, progress is kept but the party is paused and everyone must reconnect.
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

    # Bad commands (empty checkpoint, unexpected field) are rejected with no partial change.
    def test_malformed_event_leaves_no_partial_mutation(self):
        before = self.store.snapshot(self.party)
        with self.assertRaises(Rejected):
            self.event("host", "bad", "rest", checkpoint="")
        with self.assertRaises(Rejected):
            self.event("host", "bad", "death", unexpected=True)
        self.assertEqual(self.store.snapshot(self.party), before)

    # Eight writers on separate connections at once must all succeed with no lost update.
    def test_concurrent_connections_do_not_lose_updates(self):
        # Each worker opens its own store, records one boss defeat, then closes it.
        def defeat(number):
            """Record the defeat of boss number `number` using a separate database connection."""
            store = SessionStore(self.path)
            try:
                return store.apply(self.party, "host", f"boss-{number}", {"type": "boss_defeated", "boss": f"boss-{number}"})
            finally:
                store.close()
        # Run the eight defeats using four threads at a time.
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(defeat, range(8)))
        state = self.store.snapshot(self.party)
        self.assertEqual(len(state["bosses"]), 8)
        self.assertEqual(state["revision"], 9)


# Lets you run the tests with "python tests/test_session.py".
if __name__ == "__main__":
    unittest.main()
