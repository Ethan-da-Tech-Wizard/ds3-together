"""Run a local event simulation; this does not connect to a running game."""
import argparse
import json
from .session import GAME_BUILD, PROTOCOL, SessionStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=":memory:")
    args = parser.parse_args()
    store = SessionStore(args.database)
    try:
        state = store.create("host", "cemetery-of-ash")
        party = state["id"]
        events = [
            ("guest", "join", {"type": "join", "build": GAME_BUILD, "protocol": PROTOCOL}),
            ("guest", "death", {"type": "death"}),
            ("host", "boss", {"type": "boss_defeated", "boss": "iudex-gundyr"}),
            ("host", "rest", {"type": "rest", "checkpoint": "firelink-shrine"}),
            ("host", "disconnect", {"type": "disconnect"}),
            ("host", "reconnect", {"type": "reconnect", "build": GAME_BUILD, "protocol": PROTOCOL}),
        ]
        for actor, request, event in events:
            state = store.apply(party, actor, request, event)
        print(json.dumps({"simulation_only": True, "game_adapter_connected": False, "state": state}, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
