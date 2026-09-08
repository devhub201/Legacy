#!/bin/bash
# ================================================================
# LEGACY CLOUD PANEL — Installer
# ================================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

TOTAL_STEPS=9
CURRENT_STEP=0

banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    cat << "EOF"
888                                                88888888888
888                                                    888
888                                                    888
888       .d88b.   .d88b.   8888b.   .d8888b 888  888  888
888      d8P  Y8b d88P"88b     "88b d88P"    888  888  888
888      88888888 888  888 .d888888 888      888  888  888
888      Y8b.     Y88b 888 888  888 Y88b.    Y88b 888  888
88888888  "Y8888   "Y88888 "Y888888  "Y8888P  "Y88888  888
                        888
                   Y8b d88P
                    "Y88P"       C L O U D   P A N E L
EOF
    echo -e "${NC}${DIM}                 Multi-Node VPS Provider Platform${NC}\n"
}

step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo -e "\n${MAGENTA}${BOLD}[${CURRENT_STEP}/${TOTAL_STEPS}]${NC} ${CYAN}${BOLD}$1${NC}"
}

ok()   { echo -e "  ${GREEN}✔${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
info() { echo -e "  ${DIM}$1${NC}"; }

spinner_run() {
    local msg="$1"; shift
    ("$@") &>/tmp/legacy_install.log &
    local pid=$!
    local spin='⣾⣽⣻⢿⡿⣟⣯⣷'
    local i=0
    tput civis 2>/dev/null
    while kill -0 "$pid" 2>/dev/null; do
        i=$(( (i+1) % ${#spin} ))
        printf "\r  ${CYAN}%s${NC} %s" "${spin:$i:1}" "$msg"
        sleep 0.08
    done
    wait "$pid"; local status=$?
    tput cnorm 2>/dev/null
    if [ $status -eq 0 ]; then
        printf "\r  ${GREEN}✔${NC} %s\n" "$msg"
    else
        printf "\r  ${RED}✘${NC} %s (see /tmp/legacy_install.log)\n" "$msg"
        exit 1
    fi
}

progress_bar() {
    local pct=$1
    local width=40
    local filled=$(( pct * width / 100 ))
    local empty=$(( width - filled ))
    printf "\r  ${CYAN}["
    printf "%0.s█" $(seq 1 $filled) 2>/dev/null
    printf "%0.s░" $(seq 1 $empty) 2>/dev/null
    printf "]${NC} %d%%" "$pct"
}

banner
echo -e "${YELLOW}${BOLD}Welcome to the Legacy Cloud Panel installer.${NC}"
echo -e "${DIM}This will set up everything — Docker, ttyd, firewall, SSH keys, and the panel itself.${NC}\n"
read -p "$(echo -e ${BOLD}Press Enter to begin...${NC})"

INSTALL_DIR="/root/legacypanel"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ---------------- STEP 1: Questions ----------------
step "Configuration"
echo -e "${DIM}Detecting public IP...${NC}"
DETECTED_IP=$(curl -s ifconfig.me)
info "Detected: $DETECTED_IP"
read -p "  Public IP/host for this panel [$DETECTED_IP]: " PUBLIC_HOST
PUBLIC_HOST=${PUBLIC_HOST:-$DETECTED_IP}
read -p "  Discord Application Client ID: " DISCORD_CLIENT_ID
read -p "  Discord Application Client Secret: " DISCORD_CLIENT_SECRET
read -p "  Your Discord User ID (owner): " OWNER_DISCORD_ID
read -p "  Set Legacy Bot token now? [y/N]: " SET_BOT_NOW
BOT_TOKEN=""
if [[ "$SET_BOT_NOW" =~ ^[Yy]$ ]]; then
    read -p "  Discord Bot Token: " BOT_TOKEN
fi
SESSION_SECRET=$(openssl rand -hex 32)
read -p "  Panel port [8000]: " PANEL_PORT
PANEL_PORT=${PANEL_PORT:-8000}

echo ""
echo -e "  ${BOLD}Summary${NC}"
echo -e "  ${DIM}────────────────────────────────────${NC}"
echo -e "  Public Host   : ${CYAN}$PUBLIC_HOST${NC}"
echo -e "  Panel Port    : ${CYAN}$PANEL_PORT${NC}"
echo -e "  Redirect URI  : ${CYAN}http://$PUBLIC_HOST:$PANEL_PORT/callback${NC}"
echo -e "  ${DIM}────────────────────────────────────${NC}"
read -p "$(echo -e ${BOLD}Looks good? Press Enter to continue, Ctrl+C to abort...${NC})"

# ---------------- STEP 2: System packages ----------------
step "Installing system packages"
spinner_run "Updating package lists" apt update -y
spinner_run "Installing Docker, ttyd, Python, firewall tools" \
    apt install -y docker.io ttyd python3 python3-pip python3-venv curl openssh-client sqlite3 ufw
spinner_run "Enabling Docker service" systemctl enable --now docker

# ---------------- STEP 3: Firewall ----------------
step "Configuring firewall"
ufw allow 22/tcp comment 'SSH' >/dev/null 2>&1 || true
ufw allow "$PANEL_PORT"/tcp comment 'Admin Panel' >/dev/null 2>&1 || true
ufw allow 20000:21000/tcp comment 'Customer VPS ports' >/dev/null 2>&1 || true
ufw allow 30000:30100/tcp comment 'Terminal sessions' >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true
ok "Firewall active (SSH, panel, VPS ports, terminal ports open)"

# ---------------- STEP 4: SSH key for multi-node ----------------
step "Generating multi-node SSH key"
mkdir -p /root/.ssh
if [ ! -f /root/.ssh/legacypanel_key ]; then
    ssh-keygen -t ed25519 -f /root/.ssh/legacypanel_key -N "" -C "legacypanel" -q
fi
touch /root/.ssh/config
chmod 600 /root/.ssh/config
ok "SSH key ready"

echo ""
echo -e "  ${YELLOW}${BOLD}┌─────────────────────────────────────────────────────────┐${NC}"
echo -e "  ${YELLOW}${BOLD}│  COPY THIS KEY — you'll need it when adding other nodes  │${NC}"
echo -e "  ${YELLOW}${BOLD}└─────────────────────────────────────────────────────────┘${NC}"
echo -e "  ${GREEN}$(cat /root/.ssh/legacypanel_key.pub)${NC}"
echo ""
read -p "$(echo -e ${BOLD}Press Enter once you've noted this down...${NC})"

# ---------------- STEP 5: Python env ----------------
step "Setting up Python environment"
spinner_run "Creating virtual environment" python3 -m venv venv
source venv/bin/activate
spinner_run "Upgrading pip" pip install --upgrade pip -q
spinner_run "Installing Python dependencies" pip install -r requirements.txt -q
mkdir -p static/uploads

# ---------------- STEP 6: Write config ----------------
step "Writing configuration"
cat > .env << EOF
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
EOF
ok ".env written"

if [ -n "$BOT_TOKEN" ]; then
    python3 -c "
import os, sys
os.chdir('$INSTALL_DIR'); sys.path.insert(0, '.')
from database import init_db, save_bot_token
init_db(); save_bot_token('$BOT_TOKEN')
" && ok "Bot token saved"
fi

# ---------------- STEP 7: systemd service ----------------
step "Creating systemd service"
cat > /etc/systemd/system/legacypanel.service << EOF
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
EOF
systemctl daemon-reload
systemctl enable legacypanel >/dev/null 2>&1
ok "Service registered (auto-start on boot, auto-restart on crash)"

# ---------------- STEP 8: Start ----------------
step "Starting Legacy Cloud Panel"
systemctl restart legacypanel
for i in 1 2 3 4 5 6 7 8 9 10; do
    progress_bar $((i * 10))
    sleep 0.3
done
echo ""
if systemctl is-active --quiet legacypanel; then
    ok "Panel is running"
else
    warn "Panel may have failed to start — check: journalctl -u legacypanel -n 50"
fi

# ---------------- STEP 9: Done ----------------
step "Installation complete"
echo ""
echo -e "${GREEN}${BOLD}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║              LEGACY CLOUD PANEL IS LIVE                    ║${NC}"
echo -e "${GREEN}${BOLD}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}Panel URL:${NC}      ${CYAN}http://$PUBLIC_HOST:$PANEL_PORT${NC}"
echo -e "  ${BOLD}Redirect URI:${NC}   ${CYAN}http://$PUBLIC_HOST:$PANEL_PORT/callback${NC}"
echo ""
echo -e "  ${DIM}Manage the service:${NC}"
echo -e "    systemctl status legacypanel"
echo -e "    systemctl restart legacypanel"
echo -e "    journalctl -u legacypanel -f"
echo ""
echo -e "  ${DIM}Next: log in, go to 'Nodes', and add your other machines"
echo -e "  using the SSH key printed above.${NC}"
echo ""
