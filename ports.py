"""ports.py — the dashboard's TCP port: the rules, in one place.

Used by app.py (Settings → Service port) and cli.py (`tc-lab set-port`).
setup.sh --port applies the same range in bash; a test keeps them in step.
"""
import socket

# The service runs as an unprivileged user, and only root (or CAP_NET_BIND_SERVICE,
# which it deliberately does not have) may listen below 1024.
PORT_MIN, PORT_MAX = 1024, 65535
DEFAULT_PORT = 5000


def parse_port(value):
    """Return `value` as a port number, or raise ValueError with a message that
    can be shown to the user as-is. Accepts an int or a string of ASCII digits."""
    if isinstance(value, bool):                      # True is an int in Python
        raise ValueError("The port must be a whole number")
    if isinstance(value, int):
        port = value
    elif isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        port = int(value.strip())
    else:
        raise ValueError("The port must be a whole number")
    if not PORT_MIN <= port <= PORT_MAX:
        raise ValueError(f"The port must be between {PORT_MIN} and {PORT_MAX}")
    return port


def port_available(host, port):
    """True if nothing is listening on (host, port) right now — tested by
    binding it, the same way the web server will (SO_REUSEADDR included)."""
    try:
        family, stype, proto, _, addr = socket.getaddrinfo(
            host or None, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)[0]
    except (socket.gaierror, IndexError):
        return False
    with socket.socket(family, stype, proto) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(addr)
        except OSError:
            return False
    return True
