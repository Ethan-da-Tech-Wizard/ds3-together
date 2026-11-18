# Program: ds3-together - __main__.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Runs a small offline simulation of a party session (join, death, boss, rest, disconnect, reconnect) and prints the resulting state as JSON.

"""Run a local event simulation; this does not connect to a running game."""
# ---------------- Imports ----------------
# argparse reads command-line options, json prints the result nicely.
import argparse
import json
# Bring in the session storage class and the constants it checks against.
from .session import GAME_BUILD, PROTOCOL, SessionStore


def main():
    """Build a session store, play a scripted list of events through it, and print the final state."""
    # ---------------- Command-line options ----------------
    # Describe the program using this file's docstring as the help text.
    parser = argparse.ArgumentParser(description=__doc__)
    # --database picks where to save data; ":memory:" keeps it in RAM only (nothing saved).
    parser.add_argument("--database", default=":memory:")
    # Read the options the user typed.
    args = parser.parse_args()
    # Open (or create) the session database.
    store = SessionStore(args.database)
    # try/finally makes sure the database is closed even if something fails.
    try:
        # Create a new party owned by the player "host", starting at a checkpoint.
        state = store.create("host", "cemetery-of-ash")
        # Remember the party's unique id so later events refer to it.
        party = state["id"]
        # The script of events to replay. Each tuple is (who, request id, command).
        # Order matters: guest joins, guest dies, host beats a boss, host rests, host drops, host returns.
        events = [
            ("guest", "join", {"type": "join", "build": GAME_BUILD, "protocol": PROTOCOL}),
            ("guest", "death", {"type": "death"}),
            ("host", "boss", {"type": "boss_defeated", "boss": "iudex-gundyr"}),
            ("host", "rest", {"type": "rest", "checkpoint": "firelink-shrine"}),
            ("host", "disconnect", {"type": "disconnect"}),
            ("host", "reconnect", {"type": "reconnect", "build": GAME_BUILD, "protocol": PROTOCOL}),
        ]
        # Apply every event in order; each call returns the new party state.
        for actor, request, event in events:
            state = store.apply(party, actor, request, event)
        # Print the final state. The flags make it clear this is only a simulation.
        print(json.dumps({"simulation_only": True, "game_adapter_connected": False, "state": state}, indent=2))
    # Always release the database connection.
    finally:
        store.close()


# Only run main() when this file is started directly (python -m wyld_together).
if __name__ == "__main__":
    main()
