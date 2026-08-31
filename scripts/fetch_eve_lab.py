#!/usr/bin/env python3
"""Fetch EVE-NG lab summary. Usage:
EVE_USER=admin EVE_PASS=eve python3 scripts/fetch_eve_lab.py

On WSL2, Python has no route to the lab LAN. The script calls
Windows curl.exe so traffic uses the same stack as Chrome.
"""
import json
import os
import pathlib
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

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


def use_win_curl():
    return is_wsl() and pathlib.Path(CURL_WIN).is_file()


COOKIE_JAR = None
if use_win_curl():
    COOKIE_JAR = windows_temp() / "eve_ng.cookie"
    try:
        COOKIE_JAR.unlink()
    except FileNotFoundError:
        pass


def api_win_curl(method, path, body=None):
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
    tmp = None
    if body is not None:
        tmp = windows_temp() / "eve_ng.body.json"
        tmp.write_text(json.dumps(body), encoding="utf-8")
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{to_win_path(tmp)}"]
    cmd.append(url)
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"curl.exe failed ({exc.returncode}) {path}\n{exc.output[:2000]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"Non-JSON from {path}:\n{out[:2000]}")


def api_urllib(method, path, body=None, cookie=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw_cookie = resp.headers.get("Set-Cookie", "")
            payload = json.load(resp)
            return payload, raw_cookie
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        sys.exit(f"HTTP {exc.code} {path}\n{detail}")
    except urllib.error.URLError as exc:
        sys.exit(
            f"Timeout/unreachable {BASE}{path}: {exc.reason}\n"
            "WSL2 cannot reach this LAN IP. Use curl.exe (script does this) "
            "or run from Windows PowerShell."
        )


_urllib_cookie = None


def api(method, path, body=None):
    global _urllib_cookie
    if use_win_curl():
        return api_win_curl(method, path, body)
    payload, raw = api_urllib(method, path, body, _urllib_cookie)
    if raw:
        _urllib_cookie = raw.split(";", 1)[0]
    return payload


print("TRANSPORT", "curl.exe (Windows stack)" if use_win_curl() else "python urllib")

auth = api(
    "POST",
    "/api/auth/login",
    {"username": USER, "password": PASS, "html5": "-1"},
)
print("AUTH", auth.get("status"), auth.get("message", auth.get("code")))
if auth.get("status") != "success" and auth.get("code") not in (200, 201):
    print(json.dumps(auth, indent=2)[:2000])
    sys.exit(1)


def get(path):
    return api("GET", path)


found = []


def walk(folder):
    path = "/api/folders/" if folder in ("", "/") else "/api/folders" + folder
    payload = get(path).get("data") or {}
    for lab in payload.get("labs") or []:
        if isinstance(lab, dict):
            name = lab.get("file") or lab.get("filename") or lab.get("name") or ""
            lab_path = lab.get("path") or (folder.rstrip("/") + "/" + name)
        else:
            name = str(lab)
            lab_path = folder.rstrip("/") + "/" + name
        if not lab_path.startswith("/"):
            lab_path = "/" + lab_path.lstrip("/")
        if TARGET in str(name) or TARGET in lab_path:
            found.append(lab_path)
    for sub in payload.get("folders") or []:
        if isinstance(sub, dict):
            name = sub.get("name") or ""
        else:
            name = str(sub)
        if not name or name in (".", ".."):
            continue
        nxt = folder.rstrip("/") + "/" + name.lstrip("/")
        if not nxt.startswith("/"):
            nxt = "/" + nxt
        walk(nxt)


walk("/")
print("LABS_MATCHING", found or ["not_found"])
lab_path = (found or ["/" + TARGET])[0]
# Keep slashes: Apache 404s on /api/labs%2FLab.unl. Encode spaces only.
enc = urllib.parse.quote(lab_path, safe="/")
print("USING", lab_path)

lab = get("/api/labs" + enc)
print("\n=== LAB ===")
print(json.dumps(lab.get("data", lab), indent=2)[:4000])

nodes = get("/api/labs" + enc + "/nodes")
print("\n=== NODES ===")
ndata = nodes.get("data") or nodes
if isinstance(ndata, dict):
    for nid, node in ndata.items():
        print(
            f"{nid:>4}  {node.get('name', '?'):20}  type={node.get('type', '?'):8}  "
            f"image={node.get('image') or node.get('template') or '-':30}  "
            f"status={node.get('status')}  url={node.get('url', '')}"
        )
else:
    print(json.dumps(nodes, indent=2)[:4000])

nets = get("/api/labs" + enc + "/networks")
print("\n=== NETWORKS ===")
print(json.dumps(nets.get("data", nets), indent=2)[:4000])
