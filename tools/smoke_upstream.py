#!/usr/bin/env python3
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

ROOT = Path(__file__).resolve().parents[1]


def http(path, data=None):
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/ds3os")
    args = parser.parse_args()
    cache = (args.build / "CMakeCache.txt").read_text()
    if "WYLD_LOOPBACK_ONLY:BOOL=ON\n" not in cache:
        parser.error("Use a build configured with WYLD_LOOPBACK_ONLY=ON")
    if not shutil.which("ss"):
        parser.error("The ss command from iproute2 is required")
    source_line = next(line for line in cache.splitlines() if line.startswith("CMAKE_HOME_DIRECTORY:INTERNAL="))
    source = Path(source_line.split("=", 1)[1]) / "bin/x64_release"
    existing = subprocess.check_output(["ss", "-H", "-lntu"], text=True)
    for line in existing.splitlines():
        if int(line.split()[4].rsplit(":", 1)[1]) in {50000, 50005, 50010, 50050}:
            parser.error("Development ports are in use; existing services preserved")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="wyld-ds3os-") as temporary:
        runtime = Path(temporary)
        for name in ("Server", "libsteam_api.so"):
            shutil.copy2(source / name, runtime / name)
        shutil.copytree(source / "WebUI", runtime / "WebUI")
        saved = runtime / "Saved/default"
        saved.mkdir(parents=True)
        config = {"GameType": "DarkSouls3", "ServerName": "Wyld local smoke test",
                  "ServerHostname": "127.0.0.1", "ServerPrivateHostname": "127.0.0.1",
                  "Advertise": False, "SupportSharding": False,
                  "WebUIServerUsername": "localdev", "WebUIServerPassword": secrets.token_urlsafe(32)}
        (saved / "config.json").write_text(json.dumps(config))
        with (runtime / "server.log").open("wb") as log:
            process = subprocess.Popen([str(runtime / "Server")], cwd=runtime, stdout=log,
                                       stderr=subprocess.STDOUT,
                                       env={**os.environ, "LD_LIBRARY_PATH": str(runtime)})
        try:
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
            assert code == 401, "Anonymous admin request was not rejected"
            sockets = [line for line in subprocess.check_output(["ss", "-H", "-lntup"], text=True).splitlines()
                       if f"pid={process.pid}," in line]
            assert len(sockets) >= 4, "Missing development listeners"
            assert all(line.split()[4].startswith("127.0.0.1:") for line in sockets), "Non-local listener found"
            ports = {int(line.split()[4].rsplit(":", 1)[1]) for line in sockets}
            assert {50000, 50005, 50010, 50050} <= ports
            code, result = http("/auth", {"username": config["WebUIServerUsername"],
                                         "password": config["WebUIServerPassword"]})
            assert code == 200 and result.get("token") and result.get("gameType") == "DarkSouls3"
            process.send_signal(signal.SIGINT)
            process.wait(timeout=10)
            assert process.returncode == 0, "Server did not exit cleanly"
            print(json.dumps({"passed": True, "listeners_loopback_only": True,
                              "anonymous_admin_status": 401, "authenticated_admin_status": 200,
                              "clean_shutdown": True, "game_clients_tested": 0}, indent=2))
        except BaseException:
            print((runtime / "server.log").read_text(errors="replace")[-8000:])
            raise
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
