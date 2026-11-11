"""osint-mcp (robyroro/osint-mcp 0.3.0, the hash-pinned wheel in /opt/venv) as an MCP server of sandbox-ai-mcp.

Upstream's tools run unchanged; one check is tightened before they start. osint_mcp.network.public_ip is the
address check behind every HTTP request, every redirect, every TLS connection and a chosen DNS resolver: it
refuses what ipaddress does not call global and IPv4-mapped IPv6, but takes an IPv6 address of the NAT64 prefix
64:ff9b::/96 that carries a private IPv4 address (64:ff9b::a00:1 is 10.0.0.1 behind a NAT64 gateway). Here the
IPv4 address such an address reaches (NAT64 64:ff9b::/96 and 64:ff9b:1::/48, IPv4-mapped, 6to4 2002::/16) must
be global too, as in web-fetch. Every caller looks public_ip up in that module when it runs (network.py
normalize_url and resolve_public, sources.py dns_records), so replacing it there covers all of them.
"""
import ipaddress

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

if __name__ == "__main__":
    server.main()
