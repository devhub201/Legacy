import subprocess
import os
import sys

_bot_process = None


def is_running():
    global _bot_process
    return _bot_process is not None and _bot_process.poll() is None


def start_bot(token: str):
    global _bot_process
    if is_running():
        return False, "Bot is already running"
    if not token:
        return False, "No bot token saved"
    env = os.environ.copy()
    env["DISCORD_BOT_TOKEN"] = token
    _bot_process = subprocess.Popen([sys.executable, "legacy_bot.py"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, "Bot starting"


def stop_bot():
    global _bot_process
    if not is_running():
        return False, "Bot isn't running"
    _bot_process.terminate()
    try:
        _bot_process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _bot_process.kill()
    _bot_process = None
    return True, "Bot stopped"


def restart_bot(token: str):
    stop_bot()
    return start_bot(token)
