#!/usr/bin/env python3
"""Authorize the youtube MCP server once and print its refresh token. A human runs this, on the host, never an
agent; it needs Python 3.9+ and nothing else (standard library only):

    python3 -I authorize.py --client-secrets ~/Downloads/client_secret_....json | sandbox-ai secrets set YOUTUBE_REFRESH_TOKEN

The client is a "Desktop app" OAuth client of your Google Cloud project with the YouTube Data API v3 enabled
(its JSON from the console: --client-secrets FILE; or YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in the
environment; else it asks, the secret not shown). It prints a Google sign-in address (and opens it in your
browser with --open), waits on 127.0.0.1 for Google's redirect (the loopback flow for desktop apps, with PKCE
and a random state), exchanges the code at https://oauth2.googleapis.com/token and writes the refresh token,
and nothing else, to standard output. Messages go to stderr. It refuses to print the token to a terminal
unless --show is given. It writes no file.

--scopes picks what the token may do (least privilege; Google may let you untick some on its consent page):
    upload     https://www.googleapis.com/auth/youtube.upload     upload_video, set_thumbnail
    readonly   https://www.googleapis.com/auth/youtube.readonly   list_my_videos
    force-ssl  https://www.googleapis.com/auth/youtube.force-ssl  upload_captions, update_metadata (and all the
               others): it also lets the token edit and delete videos, comments and captions - the server
               offers no such tool, but the token could
Default: upload,readonly.

The refresh token stays valid until you revoke it (https://myaccount.google.com/permissions) - but only 7
days while the project's OAuth consent screen is in "Testing": publish the app ("In production") first.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.server
import json
import os
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = {
    "upload": ("https://www.googleapis.com/auth/youtube.upload", "upload_video, set_thumbnail"),
    "readonly": ("https://www.googleapis.com/auth/youtube.readonly", "list_my_videos"),
    "force-ssl": ("https://www.googleapis.com/auth/youtube.force-ssl",
                  "upload_captions, update_metadata (and every other tool)"),
}
WAIT = 300  # seconds for the browser's redirect
CLIENT_ID = re.compile(r"[A-Za-z0-9._-]{1,200}\.apps\.googleusercontent\.com")
CLIENT_SECRET = re.compile(r"[A-Za-z0-9_-]{8,128}")


class Refused(SystemExit):
    def __init__(self, text: str) -> None:
        super().__init__(f"authorize.py: {text}")


def client_from(path: str | None) -> tuple[str, str]:
    """(client id, client secret): from the console's JSON file, the environment, or asked on the terminal."""
    client_id = client_secret = ""
    if path:
        try:
            with open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, ValueError) as exc:
            raise Refused(f"{path}: not a readable client JSON ({type(exc).__name__})") from None
        section = document.get("installed") if isinstance(document, dict) else None
        if not isinstance(section, dict):
            raise Refused(f"{path}: not the JSON of a Desktop app client (no \"installed\" section; a Web client "
                          "does not take the loopback redirect)")
        client_id, client_secret = str(section.get("client_id", "")), str(section.get("client_secret", ""))
    client_id = client_id or os.environ.get("YOUTUBE_CLIENT_ID", "").strip() or ask("OAuth client id: ")
    client_secret = client_secret or os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip() or \
        getpass.getpass("OAuth client secret (not shown): ", stream=sys.stderr).strip()
    if not CLIENT_ID.fullmatch(client_id):
        raise Refused("the client id ends with .apps.googleusercontent.com")
    if not CLIENT_SECRET.fullmatch(client_secret):
        raise Refused("that is not an OAuth client secret")
    return client_id, client_secret


def ask(prompt: str) -> str:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        raise Refused("no input")
    return line.strip()


def scope_list(text: str) -> list[str]:
    names = [name.strip() for name in text.split(",") if name.strip()]
    unknown = [name for name in names if name not in SCOPES]
    if not names or unknown:
        raise Refused(f"--scopes: a comma-separated choice of {', '.join(SCOPES)}")
    return [SCOPES[name][0] for name in dict.fromkeys(names)]


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)  # 86 characters (PKCE: 43-128)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, scopes: list[str], state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(scopes),
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


class Redirect(http.server.BaseHTTPRequestHandler):
    """Takes the one redirect with the right state; answers everything else with 404."""

    timeout = 20  # one request at a time: a connection that sends nothing must not hold up the browser's redirect
    expected_state = ""
    result: dict = {}
    done: threading.Event

    def do_GET(self):  # noqa: N802 - http.server's name
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        state = (query.get("state") or [""])[0]
        if urllib.parse.urlsplit(self.path).path != "/" or type(self).done.is_set() \
                or not secrets.compare_digest(state.encode(), self.expected_state.encode()):
            self.send_error(404)  # another path, a wrong state, or after the answer: the first one counts
            return
        if "error" in query:
            type(self).result = {"error": re.sub(r"[^A-Za-z0-9_.-]", "?", query["error"][0][:100])}
        elif query.get("code"):
            type(self).result = {"code": query["code"][0]}
        else:
            self.send_error(400)
            return
        text = ("Done: the youtube MCP server is authorized. You can close this tab."
                if "code" in type(self).result else "Authorization was refused. You can close this tab.")
        body = f"<!doctype html><meta charset=utf-8><title>sandbox-ai-mcp youtube</title><p>{text}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        type(self).done.set()

    def log_message(self, *args):  # the request line carries the code: never printed
        pass


class LoopbackHTTPServer(http.server.HTTPServer):
    """The redirect's listener on 127.0.0.1, never shared: no SO_REUSEPORT (newer Pythons set it for HTTPServer),
    so no second listener can bind the port and take the redirect with its code."""

    allow_reuse_port = False


def open_browser(url: str) -> None:
    """webbrowser.open(URL) with standard output pointed at standard error meanwhile: the browser it starts
    inherits standard output (Chrome writes "Opening in existing browser session." there and keeps it open), which
    is the pipe into the secret store - the token alone goes there."""
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        webbrowser.open(url)
    finally:
        os.dup2(saved, 1)
        os.close(saved)


def wait_for_code(port: int, state: str, open_url, url_for) -> tuple[str, str]:
    """(code, redirect URI) after the browser came back to 127.0.0.1:PORT (0: any free port)."""
    handler = type("Handler", (Redirect,), {"expected_state": state, "result": {}, "done": threading.Event()})
    server = LoopbackHTTPServer(("127.0.0.1", port), handler)
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        open_url(url_for(redirect_uri))
        if not handler.done.wait(WAIT):
            raise Refused(f"no answer from the browser within {WAIT} s")
    finally:
        server.shutdown()
        server.server_close()
    if "error" in handler.result:
        raise Refused(f"Google refused the authorization ({handler.result['error']})")
    return handler.result["code"], redirect_uri


def exchange(client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str, opener=None) -> dict:
    form = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret, "code": code,
                                   "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                                   "code_verifier": verifier}).encode()
    request = urllib.request.Request(TOKEN_URL, data=form, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "Accept": "application/json"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            data = json.loads(response.read(1 << 20))
    except urllib.error.HTTPError as exc:
        try:
            code_name = json.loads(exc.read(1 << 16)).get("error", "")
        except (ValueError, AttributeError):
            code_name = ""
        raise Refused(f"Google's token endpoint answered HTTP {exc.code} {str(code_name)[:60]}".rstrip()) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise Refused(f"Google's token endpoint not reachable ({type(exc).__name__})") from None
    if not isinstance(data, dict) or not isinstance(data.get("refresh_token"), str):
        raise Refused("Google sent no refresh token (it sends one with prompt=consent; revoke the old grant at "
                      "https://myaccount.google.com/permissions and try again)")
    return data


def main(argv: list[str] | None = None, *, open_url=None, opener=None) -> int:
    parser = argparse.ArgumentParser(description="Authorize the youtube MCP server once; the refresh token goes "
                                                 "to standard output.", epilog=__doc__.split("\n\n", 1)[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-secrets", metavar="FILE", help="the Desktop client's JSON from the console")
    parser.add_argument("--scopes", default="upload,readonly", help="upload, readonly, force-ssl (default: "
                                                                    "upload,readonly)")
    parser.add_argument("--port", type=int, default=0, help="loopback port for the redirect (default: any free)")
    parser.add_argument("--open", action="store_true", help="open the sign-in address in your browser")
    parser.add_argument("--show", action="store_true", help="print the token even when stdout is a terminal")
    opts = parser.parse_args(argv)
    if sys.stdout.isatty() and not opts.show:
        print("authorize.py: standard output is a terminal and would show the refresh token (access to your "
              "channel).\nPipe it into the secret store instead:\n"
              "    python3 -I authorize.py --client-secrets FILE | sandbox-ai secrets set YOUTUBE_REFRESH_TOKEN\n"
              "or pass --show to print it here anyway.", file=sys.stderr)
        return 2
    if not 0 <= opts.port <= 65535:
        raise Refused("--port: 0-65535")
    scopes = scope_list(opts.scopes)
    client_id, client_secret = client_from(opts.client_secrets)
    verifier, challenge = pkce()
    state = secrets.token_urlsafe(24)

    def show(url: str) -> None:
        print(f"authorize.py: sign in with the Google account of the channel at\n\n    {url}\n", file=sys.stderr)
        if opts.open:
            open_browser(url)

    code, redirect_uri = wait_for_code(opts.port, state, open_url or show,
                                       lambda uri: auth_url(client_id, uri, scopes, state, challenge))
    data = exchange(client_id, client_secret, code, redirect_uri, verifier, opener)
    granted = str(data.get("scope", "")).split()
    for name, (url, tools) in SCOPES.items():
        if url in scopes:
            print(f"authorize.py: {name}: {'granted' if url in granted or not granted else 'NOT granted'} "
                  f"({tools})", file=sys.stderr)
    print("authorize.py: the refresh token follows on standard output. Give the server the client too:\n"
          "    sandbox-ai secrets set YOUTUBE_CLIENT_ID; sandbox-ai secrets set YOUTUBE_CLIENT_SECRET",
          file=sys.stderr)
    sys.stdout.write(data["refresh_token"] + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
