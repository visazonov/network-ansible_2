#!/usr/bin/env python3
"""Dump Linux QEMU nodes and interface->network map for the Belikov lab."""
import json
import os
import pathlib
import subprocess
import sys
import urllib.parse

BASE = os.environ.get("EVE_URL", "https://10.0.150.62")
USER = os.environ.get("EVE_USER")
PASS = os.environ.get("EVE_PASS")
TARGET = os.environ.get("EVE_LAB", "Hybrid_network_clone_for_Belikov.unl")
CURL_WIN = "/mnt/c/Windows/System32/curl.exe"

if not USER or not PASS:
    sys.exit("Set EVE_USER and EVE_PASS")


def is_wsl():
    try:
        return "microsoft" in pathlib.Path("/proc/version").read_text().lower()
    except OSError:
        return False


def windows_temp():
    users = pathlib.Path("/mnt/c/Users")
    skip = {"Public", "Default", "Default User", "All Users"}
    if users.is_dir():
        for child in users.iterdir():
            if child.name in skip:
                continue
            temp = child / "AppData" / "Local" / "Temp"
            if temp.is_dir():
                return temp
    return pathlib.Path("/mnt/c/Windows/Temp")


def to_win_path(posix_path):
    return subprocess.check_output(["wslpath", "-w", str(posix_path)], text=True).strip()


COOKIE_JAR = windows_temp() / "eve_ng.cookie"


def api(method, path, body=None):
    url = BASE + path
    cmd = [
        CURL_WIN,
        "-sS",
        "-k",
        "-m",
        "30",
        "-X",
        method,
        "-c",
        to_win_path(COOKIE_JAR),
        "-b",
        to_win_path(COOKIE_JAR),
    ]
    if body is not None:
        tmp = windows_temp() / "eve_ng.body.json"
        tmp.write_text(json.dumps(body), encoding="utf-8")
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{to_win_path(tmp)}"]
    cmd.append(url)
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"Non-JSON from {path}:\n{out[:2000]}")


auth = api("POST", "/api/auth/login", {"username": USER, "password": PASS, "html5": "-1"})
print("AUTH", auth.get("status"), auth.get("message"))
if auth.get("status") != "success":
    sys.exit(1)

enc = urllib.parse.quote("/" + TARGET if not TARGET.startswith("/") else TARGET, safe="/")
nodes = (api("GET", "/api/labs" + enc + "/nodes").get("data") or {})
nets = (api("GET", "/api/labs" + enc + "/networks").get("data") or {})

print("\n=== NETWORKS (id -> name type) ===")
for nid, n in sorted(nets.items(), key=lambda x: int(x[0])):
    print(f"  net {nid:>3}  type={n.get('type'):8}  name={n.get('name')}")

print("\n=== LINUX / UBUNTU NODES ===")
for nid, n in nodes.items():
    image = (n.get("image") or "") + " " + (n.get("name") or "")
    if "linux" not in image.lower() and "ubuntu" not in image.lower():
        continue
    print(
        f"\nnode {nid}  name={n.get('name')}  image={n.get('image')}  "
        f"status={n.get('status')}  url={n.get('url')}"
    )
    ifaces = api("GET", f"/api/labs{enc}/nodes/{nid}/interfaces")
    data = ifaces.get("data") or ifaces
    print(json.dumps(data, indent=2)[:8000])
