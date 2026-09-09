#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

TOTAL_STEPS=9
CURRENT_STEP=0

print_banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "=================================================="
    echo "           LEGACY CLOUD PANEL"
    echo "=================================================="
    echo -e "${NC}${DIM}      Multi-Node VPS Provider Platform${NC}"
    echo ""
}

print_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "${MAGENTA}${BOLD}[${CURRENT_STEP}/${TOTAL_STEPS}] $1${NC}"
}

print_ok() {
    echo -e "  ${GREEN}OK${NC} - $1"
}

print_warn() {
    echo -e "  ${YELLOW}WARN${NC} - $1"
}

print_info() {
    echo -e "  ${DIM}$1${NC}"
}

run_step() {
    MSG="$1"
    shift
    "$@" > /tmp/legacy_install.log 2>&1
    STATUS=$?
    if [ $STATUS -eq 0 ]; then
        print_ok "$MSG"
    else
        echo -e "  ${RED}FAILED${NC} - $MSG"
        echo "See /tmp/legacy_install.log for details"
        exit 1
    fi
}

print_banner
echo "Welcome to the Legacy Cloud Panel installer."
echo "This sets up Docker, ttyd, firewall, SSH keys, and the panel."
echo ""
read -p "Press Enter to begin..." DUMMY

INSTALL_DIR="/root/legacypanel"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

print_step "Configuration"
echo "Detecting public IP..."
DETECTED_IP=$(curl -s ifconfig.me)
print_info "Detected: $DETECTED_IP"

read -p "Public IP/host for this panel [$DETECTED_IP]: " PUBLIC_HOST
if [ -z "$PUBLIC_HOST" ]; then
    PUBLIC_HOST=$DETECTED_IP
fi

read -p "Discord Application Client ID: " DISCORD_CLIENT_ID
read -p "Discord Application Client Secret: " DISCORD_CLIENT_SECRET
read -p "Your Discord User ID (owner): " OWNER_DISCORD_ID

read -p "Set Legacy Bot token now? [y/N]: " SET_BOT_NOW
BOT_TOKEN=""
if [ "$SET_BOT_NOW" = "y" ] || [ "$SET_BOT_NOW" = "Y" ]; then
    read -p "Discord Bot Token: " BOT_TOKEN
fi

echo ""
read -p "Set up email/password login too? [y/N]: " SET_EMAIL_LOGIN
ADMIN_EMAIL=""
ADMIN_PASSWORD=""
SMTP_USER_INPUT=""
SMTP_PASS_INPUT=""
if [ "$SET_EMAIL_LOGIN" = "y" ] || [ "$SET_EMAIL_LOGIN" = "Y" ]; then
    read -p "Admin login email: " ADMIN_EMAIL
    read -s -p "Admin login password: " ADMIN_PASSWORD
    echo ""
    read -p "SMTP email (Gmail address to send FROM): " SMTP_USER_INPUT
    echo "Note: Gmail requires an App Password, not your normal password."
    echo "Generate one at myaccount.google.com under Security, App Passwords."
    read -s -p "SMTP App Password: " SMTP_PASS_INPUT
    echo ""
fi

SESSION_SECRET=$(openssl rand -hex 32)

read -p "Panel port [8000]: " PANEL_PORT
if [ -z "$PANEL_PORT" ]; then
    PANEL_PORT=8000
fi

echo ""
echo "Summary"
echo "----------------------------------------"
echo "Public Host   : $PUBLIC_HOST"
echo "Panel Port    : $PANEL_PORT"
echo "Redirect URI  : http://$PUBLIC_HOST:$PANEL_PORT/callback"
echo "----------------------------------------"
read -p "Looks good? Press Enter to continue, Ctrl+C to abort..." DUMMY

print_step "Installing system packages"
run_step "Updating package lists" apt update -y
run_step "Installing Docker, ttyd, Python, firewall tools" apt install -y docker.io ttyd python3 python3-pip python3-venv curl openssh-client sqlite3 ufw
run_step "Enabling Docker service" systemctl enable --now docker

print_step "Configuring firewall"
ufw allow 22/tcp comment "SSH" > /dev/null 2>&1 || true
ufw allow "$PANEL_PORT"/tcp comment "Admin Panel" > /dev/null 2>&1 || true
ufw allow 20000:21000/tcp comment "Customer VPS ports" > /dev/null 2>&1 || true
ufw allow 30000:30100/tcp comment "Terminal sessions" > /dev/null 2>&1 || true
ufw --force enable > /dev/null 2>&1 || true
print_ok "Firewall active"

print_step "Generating multi-node SSH key"
mkdir -p /root/.ssh
if [ ! -f /root/.ssh/legacypanel_key ]; then
    ssh-keygen -t ed25519 -f /root/.ssh/legacypanel_key -N "" -C "legacypanel" -q
fi
touch /root/.ssh/config
chmod 600 /root/.ssh/config
print_ok "SSH key ready"

echo ""
echo "=================================================="
echo "COPY THIS KEY - needed when adding other nodes"
echo "=================================================="
cat /root/.ssh/legacypanel_key.pub
echo "=================================================="
echo ""
read -p "Press Enter once you have noted this down..." DUMMY

print_step "Setting up Python environment"
run_step "Creating virtual environment" python3 -m venv venv
source venv/bin/activate
run_step "Upgrading pip" pip install --upgrade pip -q
run_step "Installing Python dependencies" pip install -r requirements.txt -q
mkdir -p static/uploads

print_step "Writing configuration"
cat > .env << ENVEOF
DISCORD_CLIENT_ID=$DISCORD_CLIENT_ID
DISCORD_CLIENT_SECRET=$DISCORD_CLIENT_SECRET
DISCORD_REDIRECT_URI=http://$PUBLIC_HOST:$PANEL_PORT/callback
SESSION_SECRET=$SESSION_SECRET
OWNER_DISCORD_ID=$OWNER_DISCORD_ID
PANEL_DB_PATH=$INSTALL_DIR/legacypanel.db
PUBLIC_HOST=$PUBLIC_HOST
PANEL_PORT=$PANEL_PORT
TTYD_PORT_START=30000
TTYD_PORT_END=30100
SSH_KEY_PATH=/root/.ssh/legacypanel_key
SMTP_USER=$SMTP_USER_INPUT
SMTP_PASSWORD=$SMTP_PASS_INPUT
ENVEOF
print_ok ".env written"

if [ -n "$BOT_TOKEN" ]; then
    python3 - << PYEOF
import os, sys
os.chdir("$INSTALL_DIR")
sys.path.insert(0, ".")
from database import init_db, save_bot_token
init_db()
save_bot_token("$BOT_TOKEN")
PYEOF
    print_ok "Bot token saved"
fi

if [ -n "$ADMIN_EMAIL" ]; then
    python3 - << PYEOF2
import os, sys, bcrypt
os.chdir("$INSTALL_DIR")
sys.path.insert(0, ".")
from database import init_db, set_admin_credentials
init_db()
hashed = bcrypt.hashpw("$ADMIN_PASSWORD".encode(), bcrypt.gensalt()).decode()
set_admin_credentials("$ADMIN_EMAIL", hashed)
PYEOF2
    print_ok "Email login configured"
fi

print_step "Creating systemd service"
cat > /etc/systemd/system/legacypanel.service << SERVICEEOF
[Unit]
Description=Legacy Cloud Admin Panel
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python3 main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICEEOF
systemctl daemon-reload
systemctl enable legacypanel > /dev/null 2>&1
print_ok "Service registered"

print_step "Starting Legacy Cloud Panel"
systemctl restart legacypanel
sleep 3
if systemctl is-active --quiet legacypanel; then
    print_ok "Panel is running"
else
    print_warn "Panel may have failed to start - check: journalctl -u legacypanel -n 50"
fi

print_step "Installation complete"
echo ""
echo "=================================================="
echo "  LEGACY CLOUD PANEL IS LIVE"
echo "=================================================="
echo ""
echo "Panel URL:     http://$PUBLIC_HOST:$PANEL_PORT"
echo "Redirect URI:  http://$PUBLIC_HOST:$PANEL_PORT/callback"
echo ""
echo "Manage the service:"
echo "  systemctl status legacypanel"
echo "  systemctl restart legacypanel"
echo "  journalctl -u legacypanel -f"
echo ""
echo "Next: log in, go to Nodes, and add your other machines"
echo "using the SSH key printed above."
echo ""
