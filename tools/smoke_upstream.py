#!/usr/bin/env python3
# Program: ds3-together - smoke_upstream.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Starts the built ds3os server on localhost in a temporary folder and checks that its admin login rejects anonymous users, accepts the right password, listens only on loopback and shuts down cleanly.

"""Check a localhost ds3os build, admin authentication, and graceful shutdown."""
# ---------------- Imports ----------------
# Standard library modules: option parsing, JSON, file paths, random secrets, process control, timing and HTTP.
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

# ROOT is the repository folder (two levels up from this file).
ROOT = Path(__file__).resolve().parents[1]


def http(path, data=None):
    """Send a request to the local admin web server and return (status code, JSON body or None).

    With `data` it POSTs that dictionary as JSON; without it, it does a plain GET."""
    # Build the request to the local admin port (50005); no network leaves this computer.
    request = urllib.request.Request(
        "http://127.0.0.1:50005" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    # HTTP errors (like 401) are returned as a status code instead of crashing.
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


def main():
    """Run the whole smoke test and print a JSON summary when every check passes."""
    # Use this file's docstring as the help text.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/ds3os")
    # Read the options the user typed.
    args = parser.parse_args()
    # CMakeCache.txt records the settings the build was configured with.
    cache = (args.build / "CMakeCache.txt").read_text()
    # Only test builds that were configured to listen on localhost.
    if "WYLD_LOOPBACK_ONLY:BOOL=ON\n" not in cache:
        parser.error("Use a build configured with WYLD_LOOPBACK_ONLY=ON")
    # "ss" lists open network sockets; it is needed to inspect the listeners.
    if not shutil.which("ss"):
        parser.error("The ss command from iproute2 is required")
    # Find where the source tree is, from the cache, to locate the built Server program.
    source_line = next(line for line in cache.splitlines() if line.startswith("CMAKE_HOME_DIRECTORY:INTERNAL="))
    source = Path(source_line.split("=", 1)[1]) / "bin/x64_release"
    # List the sockets that are already listening.
    existing = subprocess.check_output(["ss", "-H", "-lntu"], text=True)
    # If any development port is already in use, stop rather than disturb another service.
    for line in existing.splitlines():
        if int(line.split()[4].rsplit(":", 1)[1]) in {50000, 50005, 50010, 50050}:
            parser.error("Development ports are in use; existing services preserved")
    # Make any files created next owner-only (private).
    os.umask(0o077)
    # Work in a throwaway folder that is deleted at the end.
    with tempfile.TemporaryDirectory(prefix="wyld-ds3os-") as temporary:
        runtime = Path(temporary)
        # Copy the server program and its library plus the web UI into the temp folder.
        for name in ("Server", "libsteam_api.so"):
            shutil.copy2(source / name, runtime / name)
        shutil.copytree(source / "WebUI", runtime / "WebUI")
        # The server reads its settings from Saved/default/config.json.
        saved = runtime / "Saved/default"
        saved.mkdir(parents=True)
        # Test configuration: localhost only, not advertised, with a random one-time admin password.
        config = {"GameType": "DarkSouls3", "ServerName": "Wyld local smoke test",
                  "ServerHostname": "127.0.0.1", "ServerPrivateHostname": "127.0.0.1",
                  "Advertise": False, "SupportSharding": False,
                  "WebUIServerUsername": "localdev", "WebUIServerPassword": secrets.token_urlsafe(32)}
        # Write the configuration file.
        (saved / "config.json").write_text(json.dumps(config))
        # Start the server in the background and save its output to server.log.
        with (runtime / "server.log").open("wb") as log:
            process = subprocess.Popen([str(runtime / "Server")], cwd=runtime, stdout=log,
                                       stderr=subprocess.STDOUT,
                                       env={**os.environ, "LD_LIBRARY_PATH": str(runtime)})
        # try/except/finally: show the server log on failure and always stop the server at the end.
        try:
            # Allow up to 25 seconds for the server to start answering.
            deadline = time.monotonic() + 25
            while True:
                # If the server already exited, it crashed on startup.
                if process.poll() is not None:
                    raise RuntimeError("Server exited before becoming ready")
                try:
                    # Ask the admin login endpoint without credentials; any answer means it is up.
                    code, _ = http("/auth")
                    break
                except (OSError, urllib.error.URLError):
                    # Not ready yet: give up after the deadline, otherwise wait a moment and retry.
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Server did not become ready within 25 seconds")
                    time.sleep(0.2)
            # Check 1: anonymous access must be refused (401 Unauthorized).
            assert code == 401, "Anonymous admin request was not rejected"
            # Check 2: list the listening sockets that belong to the server process.
            sockets = [line for line in subprocess.check_output(["ss", "-H", "-lntup"], text=True).splitlines()
                       if f"pid={process.pid}," in line]
            # There should be at least four listeners, and all must be on 127.0.0.1 (localhost only).
            assert len(sockets) >= 4, "Missing development listeners"
            assert all(line.split()[4].startswith("127.0.0.1:") for line in sockets), "Non-local listener found"
            # Collect the port numbers and confirm all four expected development ports are present.
            ports = {int(line.split()[4].rsplit(":", 1)[1]) for line in sockets}
            assert {50000, 50005, 50010, 50050} <= ports
            # Check 3: log in with the right username and password; expect success with a token.
            code, result = http("/auth", {"username": config["WebUIServerUsername"],
                                         "password": config["WebUIServerPassword"]})
            assert code == 200 and result.get("token") and result.get("gameType") == "DarkSouls3"
            # Check 4: ask the server to stop (like pressing Ctrl+C) and expect a clean exit code of 0.
            process.send_signal(signal.SIGINT)
            process.wait(timeout=10)
            assert process.returncode == 0, "Server did not exit cleanly"
            # All checks passed: print a summary.
            print(json.dumps({"passed": True, "listeners_loopback_only": True,
                              "anonymous_admin_status": 401, "authenticated_admin_status": 200,
                              "clean_shutdown": True, "game_clients_tested": 0}, indent=2))
        # On any failure, print the last part of the server log to help debugging, then re-raise.
        except BaseException:
            print((runtime / "server.log").read_text(errors="replace")[-8000:])
            raise
        # Cleanup: if the server is still running, ask it to stop, and kill it if it does not.
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


# Run main() only when this file is started directly.
if __name__ == "__main__":
    main()
