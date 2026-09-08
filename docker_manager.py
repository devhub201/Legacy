import docker
import subprocess
import secrets
import string
from config import SSH_KEY_PATH

_clients = {}


def _ensure_ssh_ready(node):
    ip, user, port = node["ip"], node["ssh_user"], node["ssh_port"]
    subprocess.run(f"ssh-keyscan -p {port} {ip} >> /root/.ssh/known_hosts 2>/dev/null", shell=True)
    config_path = "/root/.ssh/config"
    try:
        with open(config_path, "r") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ""
    if f"Host {ip}\n" not in existing:
        with open(config_path, "a") as f:
            f.write(f"\nHost {ip}\n  User {user}\n  Port {port}\n  IdentityFile {SSH_KEY_PATH}\n  StrictHostKeyChecking no\n")


def get_client(node):
    node_id = node["id"]
    if node_id in _clients:
        return _clients[node_id]

    ip, user, port = node["ip"], node["ssh_user"], node["ssh_port"]
    password = node.get("ssh_password")

    subprocess.run(f"ssh-keyscan -p {port} {ip} >> /root/.ssh/known_hosts 2>/dev/null", shell=True)

    if password:
        # Password-based auth (paramiko transport, no key needed)
        client = docker.DockerClient(base_url=f"ssh://{user}:{password}@{ip}:{port}", use_ssh_client=False)
    else:
        # Key-based auth (existing method)
        _ensure_ssh_ready(node)
        client = docker.DockerClient(base_url=f"ssh://{ip}", use_ssh_client=True)

    _clients[node_id] = client
    return client


def test_node_connection(node):
    try:
        get_client(node).ping()
        return True, "Connected"
    except Exception as e:
        return False, str(e)


def get_container(node, name):
    client = get_client(node)
    try:
        return client.containers.get(name)
    except docker.errors.NotFound:
        return None


def list_all_containers(node):
    containers = get_client(node).containers.list(all=True)
    result = []
    for c in containers:
        try:
            image_tag = c.image.tags[0] if c.image.tags else c.image.short_id
        except Exception:
            image_tag = "unknown"
        result.append({"name": c.name, "status": c.status, "image": image_tag})
    return result


def start_container(node, name):
    c = get_container(node, name)
    if not c:
        raise ValueError("Container not found")
    c.start()


def stop_container(node, name):
    c = get_container(node, name)
    if not c:
        raise ValueError("Container not found")
    c.stop(timeout=15)


def restart_container(node, name):
    c = get_container(node, name)
    if not c:
        raise ValueError("Container not found")
    c.restart(timeout=15)


def remove_container(node, name):
    c = get_container(node, name)
    if c:
        c.stop(timeout=10)
        c.remove()


def get_status(node, name):
    c = get_container(node, name)
    if not c:
        return "not_found"
    c.reload()
    return c.status


def get_stats(node, name):
    c = get_container(node, name)
    if not c:
        raise ValueError("Container not found")
    stats = c.stats(stream=False)
    cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
    system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats["precpu_stats"].get("system_cpu_usage", 0)
    online_cpus = stats["cpu_stats"].get("online_cpus", 1)
    cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0 if system_delta > 0 and cpu_delta > 0 else 0.0
    mem_usage = stats["memory_stats"].get("usage", 0)
    mem_limit = stats["memory_stats"].get("limit", 1)
    return {"cpu_percent": round(cpu_percent, 1), "mem_used_mb": round(mem_usage / (1024*1024), 1), "mem_limit_mb": round(mem_limit / (1024*1024), 1)}


def reset_password(node, name, username="root"):
    c = get_container(node, name)
    if not c:
        raise ValueError("Container not found")
    new_password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(14))
    exit_code, output = c.exec_run(f"bash -c \"echo '{username}:{new_password}' | chpasswd\"")
    if exit_code != 0:
        raise RuntimeError(f"Password reset failed: {output.decode(errors='ignore')}")
    return new_password


def create_vps_container(node, name, image, ssh_port, mem_bytes, nano_cpus):
    client = get_client(node)
    container = client.containers.run(
        image, name=name, detach=True, tty=True, ports={"22/tcp": ssh_port},
        mem_limit=mem_bytes, nano_cpus=nano_cpus, labels={"legacycloud": "vps"}, command="sleep infinity",
    )
    container.exec_run("bash -c 'apt update && apt install -y openssh-server && service ssh start' || "
                        "sh -c 'apk add openssh && ssh-keygen -A && /usr/sbin/sshd'")
    return container.id


def reinstall_container(node, name):
    client = get_client(node)
    container = client.containers.get(name)
    port_bindings = container.attrs["HostConfig"]["PortBindings"]
    mem_limit = container.attrs["HostConfig"].get("Memory")
    nano_cpus = container.attrs["HostConfig"].get("NanoCpus")
    image = container.image.tags[0] if container.image.tags else container.image.id

    container.stop(timeout=10)
    container.remove()

    new_container = client.containers.run(
        image, name=name, detach=True, tty=True,
        ports=port_bindings, mem_limit=mem_limit, nano_cpus=nano_cpus,
        labels={"legacycloud": "vps"}, command="sleep infinity",
    )
    new_container.exec_run("bash -c 'apt update && apt install -y openssh-server && service ssh start' || "
                            "sh -c 'apk add openssh && ssh-keygen -A && /usr/sbin/sshd'")
    return new_container.id
