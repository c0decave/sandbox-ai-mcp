"""osint-mcp (robyroro/osint-mcp 0.3.0, the hash-pinned wheel in /opt/venv) as an MCP server of sandbox-ai-mcp.

Upstream's tools run unchanged; one check is tightened before they start. osint_mcp.network.public_ip is the
address check behind every HTTP request, every redirect, every TLS connection and a chosen DNS resolver: it
refuses what ipaddress does not call global and IPv4-mapped IPv6, but takes an IPv6 address of the NAT64 prefix
64:ff9b::/96 that carries a private IPv4 address (64:ff9b::a00:1 is 10.0.0.1 behind a NAT64 gateway). Here the
IPv4 address such an address reaches (NAT64 64:ff9b::/96 and 64:ff9b:1::/48, IPv4-mapped, 6to4 2002::/16) must
be global too, as in web-fetch. Every caller looks public_ip up in that module when it runs (network.py
normalize_url and resolve_public, sources.py dns_records), so replacing it there covers all of them.

Behind sandbox-ai's Tor profile (SANDBOX_AI_TOR=1) every DNS lookup of upstream's (dns_records, txt_records,
reverse_dns: dns.asyncresolver.Resolver, looked up when each runs) goes over TCP to public resolvers (TOR_RESOLVERS,
or the nameserver a dns_lookup call names), with longer timeouts. There no UDP passes, and what is sent to port 53
reaches tor's DNSPort, which answers A, AAAA and PTR only: MX, TXT, NS, SOA and CAA got no answer, and with them
email_security and the DNS parts of recon_domain and compare_domains. A TCP connection goes through tor's TransPort
and an exit like every other: the resolver sees the exit's address, never yours. The names that HTTP and TLS
connect to are still looked up by the system (getaddrinfo), through tor's DNSPort.

Answers are bounded (bounded): subdomains of a large domain, wayback with up to 500 snapshots, recon_batch of ten
domains and certificate_history answered far more than the 25,000 characters clients such as Claude Code, Qwen Code
and Hermes show a model (beyond that a model sees only a preview). An answer above MAX_ANSWER characters has its
longest lists cut until it fits, and says which and how many entries ("shortened", "note"). The server advertises
tools only (tools_only): it publishes no resources or prompts.
"""
import copy
import ipaddress
import json
import os

import dns.asyncresolver

from osint_mcp import network, server

NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_upstream_public_ip = network.public_ip


def embedded_ipv4(address):
    """The IPv4 address an IPv6 address reaches through NAT64, IPv4 mapping or 6to4, else None."""
    if address.version != 6:
        return None
    if any(address in net for net in NAT64):
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return address.ipv4_mapped or address.sixtofour


def public_ip(value):
    """Upstream's check, and the IPv4 address an IPv6 one carries must be public as well."""
    checked = _upstream_public_ip(value)
    embedded = embedded_ipv4(ipaddress.ip_address(checked))
    if embedded is not None and (not embedded.is_global or embedded.is_multicast):
        raise ValueError("private, local and reserved addresses are not supported")
    return checked


network.public_ip = public_ip


# -- DNS behind sandbox-ai's Tor profile ------------------------------------------------------------------------------
# The same block is in openosint (each image has its own copy: keep them alike; openosint's resolver is dnspython's
# synchronous one, osint-mcp's the asynchronous one).

TOR_RESOLVERS = ("1.1.1.1", "9.9.9.9", "8.8.8.8")  # Cloudflare, Quad9, Google: public, answering DNS over TCP
TOR_DNS_TIMEOUT = 10.0   # seconds one resolver is given (a circuit, the exit's connection, the answer)
TOR_DNS_LIFETIME = 20.0  # seconds one lookup is given, every resolver tried included


def behind_tor() -> bool:
    return os.environ.get("SANDBOX_AI_TOR") == "1"


class TorResolver(dns.asyncresolver.Resolver):
    """Upstream's resolver behind Tor: TOR_RESOLVERS instead of /etc/resolv.conf's (not read), every query over TCP,
    and at least TOR_DNS_TIMEOUT per resolver and TOR_DNS_LIFETIME per lookup, whatever upstream sets (5 s)."""

    def __init__(self, filename="/etc/resolv.conf", configure=True):
        super().__init__(filename, configure=False)
        self.nameservers = list(TOR_RESOLVERS)

    @property
    def timeout(self):
        return self._tor_timeout

    @timeout.setter
    def timeout(self, value):
        self._tor_timeout = max(float(value), TOR_DNS_TIMEOUT)

    @property
    def lifetime(self):
        return self._tor_lifetime

    @lifetime.setter
    def lifetime(self, value):
        self._tor_lifetime = max(float(value), TOR_DNS_LIFETIME)

    async def resolve(self, qname, rdtype="A", rdclass="IN", tcp=False, *args, **kwargs):
        return await super().resolve(qname, rdtype, rdclass, True, *args, **kwargs)


if behind_tor():
    dns.asyncresolver.Resolver = TorResolver


# -- answers a model can read -----------------------------------------------------------------------------------------

#: Characters of one answer at most (as JSON, as the SDK sends it).
MAX_ANSWER = 24_000


def _size(value) -> int:
    return len(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _lists(value, path=""):
    """(path, list) of every list in VALUE, nested ones included."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _lists(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        yield path, value
        for index, item in enumerate(value):
            yield from _lists(item, f"{path}[{index}]")


def bounded(answer):
    """ANSWER (a tool's dict) as it is when its JSON has at most MAX_ANSWER characters; else a copy whose longest
    lists are halved until it fits, with "shortened" (path: entries left out) and a "note"."""
    if not isinstance(answer, dict) or _size(answer) <= MAX_ANSWER:
        return answer
    answer, cut = copy.deepcopy(answer), {}
    while _size(answer) > MAX_ANSWER - 600:  # room for "shortened" and the note
        found = [(_size(items), path, items) for path, items in _lists(answer) if len(items) > 1]
        if not found:
            break
        _, path, items = max(found, key=lambda entry: entry[0])
        keep = len(items) // 2
        cut[path] = cut.get(path, 0) + len(items) - keep
        del items[keep:]
    answer["shortened"] = cut
    answer["note"] = (f"answer shortened to fit {MAX_ANSWER:,} characters (what a model is shown of a tool result): "
                      "'shortened' says how many entries of each list were left out; ask for less (a lower limit, "
                      "fewer domains, a narrower URL) to see them")
    return answer


def bound_answers(mcp):
    """Every tool of MCP (an MCPServer) answers through bounded."""
    for tool in mcp._tool_manager.list_tools():
        original = tool.fn

        async def answer(__original=original, **arguments):
            return bounded(await __original(**arguments))
        tool.fn = answer


def tools_only(mcp):
    """MCP (an MCPServer) advertises tools only: the SDK registers the handlers of resources and prompts for every
    server, and the capabilities of the initialize answer follow the handlers, so a server that publishes neither
    advertised both. Agents then offer a model tools for MCP resources, which local models took for the way to the
    server's tools (sandbox-ai research round 1, "the MCP-resource trap")."""
    for method in ("resources/list", "resources/read", "resources/templates/list", "prompts/list", "prompts/get"):
        mcp._lowlevel_server._request_handlers.pop(method, None)


bound_answers(server.mcp)
tools_only(server.mcp)

if __name__ == "__main__":
    server.main()
