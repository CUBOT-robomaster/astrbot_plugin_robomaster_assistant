from __future__ import annotations

import asyncio
import socket
from ipaddress import ip_address
from urllib.parse import urlparse


async def is_public_url(url: str, *, allowed_schemes: set[str] | None = None) -> bool:
    schemes = allowed_schemes or {"http", "https"}
    parsed = urlparse(url)
    if parsed.scheme.lower() not in schemes or not parsed.hostname:
        return False

    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "0.0.0.0"} or hostname.endswith(".localhost"):
        return False

    try:
        address = ip_address(hostname)
    except ValueError:
        try:
            addresses = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
        except OSError:
            return False
        resolved_hosts = {item[4][0] for item in addresses if item and item[4]}
        if not resolved_hosts:
            return False
        return all(is_public_address(item) for item in resolved_hosts)
    return is_public_address(str(address))


def is_public_address(host: str) -> bool:
    try:
        address = ip_address(host)
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
