#!/usr/bin/env python3
"""A stand-in language server for tests/test_lsp.py (LSP over stdio, Content-Length framing): it answers the requests
the bridge of servers/lsp-*/src/server.py makes with fixed, recognisable answers about the file it was told of, asks
the client for its configuration once, publishes diagnostics twice (an empty first one, as pyright does) and records
every method it receives in FAKE_LSP_LOG (one per line), so a test can prove what the bridge never sends."""
import json
import os
import sys

LOG = os.environ.get("FAKE_LSP_LOG")


def read():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            sys.exit(0)
        line = line.strip()
        if not line:
            break
        name, _, value = line.decode().partition(":")
        if name.lower() == "content-length":
            length = int(value)
    return json.loads(sys.stdin.buffer.read(length))


def send(message):
    body = json.dumps(message).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    sys.stdout.buffer.flush()


def main():
    opened = {}
    root = None
    while True:
        message = read()
        method = message.get("method")
        if LOG and method:
            with open(LOG, "a", encoding="utf-8") as log:
                log.write(method + "\n")
        params = message.get("params") or {}
        if "id" in message and method is None:
            continue  # the client's answer to our workspace/configuration
        if method == "initialize":
            root = params["rootUri"]
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {"definitionProvider": True}}})
            send({"jsonrpc": "2.0", "id": 900, "method": "workspace/configuration",
                  "params": {"items": [{"section": "python"}]}})
        elif method == "textDocument/didOpen" or method == "textDocument/didChange":
            document = params["textDocument"]
            text = document.get("text") or params["contentChanges"][0]["text"]
            opened[document["uri"]] = text
            version = document.get("version", 1)
            send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                  "params": {"uri": document["uri"], "version": version, "diagnostics": []}})
            found = [{"range": {"start": {"line": i, "character": line.index("BUG")},
                                "end": {"line": i, "character": line.index("BUG") + 3}},
                      "severity": 1, "source": "fake", "code": "bug", "message": f"a bug in line {i + 1}"}
                     for i, line in enumerate(text.split("\n")) if "BUG" in line]
            send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                  "params": {"uri": document["uri"], "version": version, "diagnostics": found}})
        elif method in ("textDocument/definition", "textDocument/references"):
            position = params["position"]
            uri = params["textDocument"]["uri"]
            many = 150 if method.endswith("references") else 1
            result = [{"uri": uri, "range": {"start": {"line": 0, "character": position["character"]},
                                             "end": {"line": 0, "character": position["character"] + 1}}}] * many
            result.append({"uri": "file:///usr/lib/python3/os.py",
                           "range": {"start": {"line": 9, "character": 4}, "end": {"line": 9, "character": 5}}})
            send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif method == "textDocument/hover":
            send({"jsonrpc": "2.0", "id": message["id"], "result": {"contents": {
                "kind": "markdown", "value": "fake hover at character %d" % params["position"]["character"]}}})
        elif method == "textDocument/documentSymbol":
            send({"jsonrpc": "2.0", "id": message["id"], "result": [
                {"name": "Thing", "kind": 5, "range": {"start": {"line": 0, "character": 0},
                                                       "end": {"line": 3, "character": 0}},
                 "selectionRange": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 11}},
                 "children": [{"name": "run", "kind": 6,
                               "range": {"start": {"line": 1, "character": 4}, "end": {"line": 2, "character": 0}},
                               "selectionRange": {"start": {"line": 1, "character": 8},
                                                  "end": {"line": 1, "character": 11}}}]}]})
        elif method == "workspace/symbol":
            send({"jsonrpc": "2.0", "id": message["id"], "result": [
                {"name": params["query"], "kind": 12, "containerName": "mod",
                 "location": {"uri": root + "/a.py", "range": {"start": {"line": 4, "character": 0},
                                                               "end": {"line": 4, "character": 1}}}},
                {"name": params["query"], "kind": 12,
                 "location": {"uri": "file:///usr/lib/python3/os.py", "range": {
                     "start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 1}}}}]})
        elif method == "shutdown":
            send({"jsonrpc": "2.0", "id": message["id"], "result": None})
        elif "id" in message:
            send({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "not here"}})


if __name__ == "__main__":
    main()
