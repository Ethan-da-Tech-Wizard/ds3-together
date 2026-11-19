#!/usr/bin/env python3
# ==============================================================================
# Program: smoke_upstream.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: Integration smoke testing utility for the compiled ds3os server,
#          validating loopback network binding, socket listener security,
#          HTTP admin authentication, and clean process termination under Linux.
# ==============================================================================

"""Check a localhost ds3os build, admin authentication, and graceful shutdown."""
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

# Repository root; used to find the build output and its CMake cache.
ROOT = Path(__file__).resolve().parents[1]


# The ds3os web admin UI listens on 127.0.0.1:50005 in development builds.
# A POST with a JSON body is made when `data` is given, else a GET. HTTP errors
# are returned as (status, None) so callers can assert on 401 without catching.
def http(path, data=None):
    """Execute JSON HTTP request against localhost development server."""
    request = urllib.request.Request(
        "http://127.0.0.1:50005" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None


def main():
    # Step 1: Parse arguments and inspect CMake cache for security flags
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/ds3os")
    args = parser.parse_args()
    # The CMake cache records the options the build was configured with; we refuse
    # to run a server not built loopback-only, since the test opens real ports.
    cache = (args.build / "CMakeCache.txt").read_text()
    if "WYLD_LOOPBACK_ONLY:BOOL=ON\n" not in cache:
        parser.error("Use a build configured with WYLD_LOOPBACK_ONLY=ON")
    if not shutil.which("ss"):
        parser.error("The ss command from iproute2 is required")

    # Step 2: Locate compiled binary paths and check port availability (50000, 50005, 50010, 50050)
    # Find where the source tree lives so the compiled binaries can be located.
    source_line = next(line for line in cache.splitlines() if line.startswith("CMAKE_HOME_DIRECTORY:INTERNAL="))
    source = Path(source_line.split("=", 1)[1]) / "bin/x64_release"
    # Abort if any development port is already taken, so we never interfere with
    # (or mistake) a service the user already has running.
    existing = subprocess.check_output(["ss", "-H", "-lntu"], text=True)
    for line in existing.splitlines():
        if int(line.split()[4].rsplit(":", 1)[1]) in {50000, 50005, 50010, 50050}:
            parser.error("Development ports are in use; existing services preserved")

    # Step 3: Configure isolated temporary execution environment with restrictive umask
    # Restrictive umask: files copied into the temp runtime are owner-only.
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="wyld-ds3os-") as temporary:
        runtime = Path(temporary)
        for name in ("Server", "libsteam_api.so"):
            shutil.copy2(source / name, runtime / name)
        shutil.copytree(source / "WebUI", runtime / "WebUI")
        # ds3os reads its config from Saved/default/config.json relative to its cwd.
        saved = runtime / "Saved/default"
        saved.mkdir(parents=True)

        # Step 4: Write transient server configuration enforcing loopback bindings and credentials
        # Throwaway config: loopback hostnames, no advertising, and a random admin
        # password generated per run (never stored or reused).
        config = {"GameType": "DarkSouls3", "ServerName": "Wyld local smoke test",
                  "ServerHostname": "127.0.0.1", "ServerPrivateHostname": "127.0.0.1",
                  "Advertise": False, "SupportSharding": False,
                  "WebUIServerUsername": "localdev", "WebUIServerPassword": secrets.token_urlsafe(32)}
        (saved / "config.json").write_text(json.dumps(config))

        # Step 5: Spawn native server process bound to LD_LIBRARY_PATH
        # Server output goes to a log that is only printed if the test fails.
        with (runtime / "server.log").open("wb") as log:
            process = subprocess.Popen([str(runtime / "Server")], cwd=runtime, stdout=log,
                                       stderr=subprocess.STDOUT,
                                       env={**os.environ, "LD_LIBRARY_PATH": str(runtime)})
        try:
            # Step 6: Poll health check endpoint until service is receptive
            # Poll until the HTTP port answers; give up after 25 s or if the server dies.
            deadline = time.monotonic() + 25
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Server exited before becoming ready")
                try:
                    code, _ = http("/auth")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Server did not become ready within 25 seconds")
                    time.sleep(0.2)

            # Step 7: Verify authentication challenge and socket loopback confinement
            # An unauthenticated admin request must be refused.
            assert code == 401, "Anonymous admin request was not rejected"
            # Confirm via `ss` that every listener owned by this process is bound to
            # 127.0.0.1, i.e. nothing is reachable from the network.
            sockets = [line for line in subprocess.check_output(["ss", "-H", "-lntup"], text=True).splitlines()
                       if f"pid={process.pid}," in line]
            assert len(sockets) >= 4, "Missing development listeners"
            assert all(line.split()[4].startswith("127.0.0.1:") for line in sockets), "Non-local listener found"
            ports = {int(line.split()[4].rsplit(":", 1)[1]) for line in sockets}
            assert {50000, 50005, 50010, 50050} <= ports

            # Step 8: Validate admin authentication handshake
            # Valid credentials must yield a token and report the DarkSouls3 game type.
            code, result = http("/auth", {"username": config["WebUIServerUsername"],
                                         "password": config["WebUIServerPassword"]})
            assert code == 200 and result.get("token") and result.get("gameType") == "DarkSouls3"

            # Step 9: Verify graceful daemon shutdown via SIGINT signal
            # SIGINT is how the server is stopped interactively; it must exit with code 0.
            process.send_signal(signal.SIGINT)
            process.wait(timeout=10)
            assert process.returncode == 0, "Server did not exit cleanly"
            print(json.dumps({"passed": True, "listeners_loopback_only": True,
                              "anonymous_admin_status": 401, "authenticated_admin_status": 200,
                              "clean_shutdown": True, "game_clients_tested": 0}, indent=2))
        except BaseException:
            print((runtime / "server.log").read_text(errors="replace")[-8000:])
            raise
        # Always stop the server, escalating terminate -> kill, so no process leaks.
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
