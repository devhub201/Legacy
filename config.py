import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_CLIENT_ID = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_REDIRECT_URI = os.environ["DISCORD_REDIRECT_URI"]
SESSION_SECRET = os.environ["SESSION_SECRET"]
OWNER_DISCORD_ID = os.environ.get("OWNER_DISCORD_ID", "")
PANEL_DB_PATH = os.environ.get("PANEL_DB_PATH", "legacypanel.db")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "127.0.0.1")
PANEL_PORT = int(os.environ.get("PANEL_PORT", "8000"))
TTYD_PORT_START = int(os.environ.get("TTYD_PORT_START", "30000"))
TTYD_PORT_END = int(os.environ.get("TTYD_PORT_END", "30100"))
SSH_KEY_PATH = os.environ.get("SSH_KEY_PATH", "/root/.ssh/legacypanel_key")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

OS_IMAGES = {
    "ubuntu24": ("Ubuntu 24.04", "ubuntu:24.04"),
    "ubuntu22": ("Ubuntu 22.04", "ubuntu:22.04"),
    "ubuntu20": ("Ubuntu 20.04", "ubuntu:20.04"),
    "debian12": ("Debian 12", "debian:12"),
    "debian11": ("Debian 11", "debian:11"),
    "centos9":  ("CentOS Stream 9", "quay.io/centos/centos:stream9"),
    "alma9":    ("AlmaLinux 9", "almalinux:9"),
    "rocky9":   ("Rocky Linux 9", "rockylinux:9"),
    "alpine":   ("Alpine Linux", "alpine:latest"),
    "fedora":   ("Fedora", "fedora:latest"),
}

BACKGROUND_THEMES = {
    "plain":     "Plain Black",
    "grid":      "Animated Grid",
    "particles": "Floating Particles",
    "matrix":    "Matrix Rain",
}
