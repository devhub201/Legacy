import subprocess
import socket
from config import TTYD_PORT_START, TTYD_PORT_END

_active_sessions = {}


def _find_free_port():
    for port in range(TTYD_PORT_START, TTYD_PORT_END):
        used_ports = {s["port"] for s in _active_sessions.values()}
        if port in used_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free ttyd ports available")


def start_terminal(node, container_name):
    key = f"{node['id']}:{container_name}"
    if key in _active_sessions:
        return _active_sessions[key]["port"]
    port = _find_free_port()
    docker_host = f"ssh://{node['ip']}"
    process = subprocess.Popen(
        ["ttyd", "-p", str(port), "-W", "docker", "-H", docker_host, "exec", "-it", container_name, "/bin/bash"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _active_sessions[key] = {"port": port, "process": process}
    return port


def stop_terminal(node, container_name):
    key = f"{node['id']}:{container_name}"
    session = _active_sessions.pop(key, None)
    if session:
        session["process"].terminate()
        return True
    return False
