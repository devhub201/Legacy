import os
import requests
from fastapi import FastAPI, Request, HTTPException, Form, UploadFile, File, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import bcrypt

from config import (
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
    SESSION_SECRET, OWNER_DISCORD_ID, PUBLIC_HOST, PANEL_PORT, OS_IMAGES, BACKGROUND_THEMES
)
import database as db
import docker_manager as dm
import terminal_manager as tm
import bot_manager as bm
import job_manager as jm
import anti_mining

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
templates = Jinja2Templates(directory="templates")

os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    db.init_db()
    anti_mining.start_monitor()


def render(name, request, **kwargs):
    context = {"request": request, "branding": db.get_branding(), **kwargs}
    return templates.TemplateResponse(name, context)


def require_owner(request: Request):
    discord_id = request.session.get("discord_id")
    if not discord_id or discord_id != OWNER_DISCORD_ID:
        raise HTTPException(status_code=403, detail="Owner access only")
    return discord_id


def require_api_key(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    key = auth.replace("Bearer ", "").strip()
    if not db.validate_api_key(key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key


@app.get("/login")
async def login(request: Request):
    return render("login.html", request)


@app.get("/discord-login")
async def discord_login():
    url = (f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
           f"&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify")
    return RedirectResponse(url)


@app.post("/login-email")
async def login_email(request: Request, email: str = Form(...), password: str = Form(...)):
    creds = db.get_admin_credentials()
    if not creds["email"] or not creds["password_hash"]:
        raise HTTPException(status_code=400, detail="Email login not set up yet")
    if email != creds["email"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.checkpw(password.encode(), creds["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["discord_id"] = OWNER_DISCORD_ID
    request.session["username"] = email
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/callback")
async def callback(request: Request, code: str):
    token_res = requests.post("https://discord.com/api/oauth2/token", data={
        "client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code", "code": code, "redirect_uri": DISCORD_REDIRECT_URI,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    if token_res.status_code != 200:
        raise HTTPException(status_code=400, detail="Discord auth failed")
    access_token = token_res.json()["access_token"]
    user = requests.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"}).json()
    if user["id"] != OWNER_DISCORD_ID:
        return RedirectResponse("/login?denied=1")
    request.session["discord_id"] = user["id"]
    request.session["username"] = user["username"]
    return RedirectResponse("/dashboard")


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


@app.get("/")
async def root():
    return RedirectResponse("/dashboard")


@app.get("/dashboard")
async def dashboard(request: Request):
    require_owner(request)
    vps_list = db.list_vps()
    nodes = db.list_nodes()
    running = 0
    for v in vps_list:
        node = db.get_node(v["node_id"])
        if node:
            try:
                if dm.get_status(node, v["container_name"]) == "running":
                    running += 1
            except Exception:
                pass
    revenue = sum(int("".join(ch for ch in (v["price"] or "0") if ch.isdigit()) or 0)
                  for v in vps_list if v["status"] in ("active", "renewed"))
    return render("dashboard.html", request, username=request.session.get("username"),
                  total_vps=len(vps_list), running_vps=running, revenue=revenue,
                  total_nodes=len(nodes), active_page="dashboard")


@app.get("/nodes")
async def nodes_page(request: Request):
    require_owner(request)
    nodes = db.list_nodes()
    for n in nodes:
        ok, msg = dm.test_node_connection(n)
        n["online"] = ok; n["conn_msg"] = msg
    return render("nodes.html", request, username=request.session.get("username"), nodes=nodes,
                  active_page="nodes", panel_pubkey_hint="cat /root/.ssh/legacypanel_key.pub")


@app.post("/nodes/add")
async def nodes_add(request: Request, name: str = Form(...), ip: str = Form(...),
                     ssh_user: str = Form("root"), ssh_port: int = Form(22),
                     ram_total: str = Form(...), cpu_total: str = Form(...), disk_total: str = Form(...)):
    require_owner(request)
    db.add_node(name, ip, ssh_user, ssh_port, ram_total, cpu_total, disk_total)
    return RedirectResponse("/nodes", status_code=303)


@app.post("/nodes/{node_id}/delete")
async def nodes_delete(node_id: int, request: Request):
    require_owner(request)
    db.delete_node(node_id)
    return RedirectResponse("/nodes", status_code=303)


@app.get("/vps")
async def vps_management(request: Request):
    require_owner(request)
    vps_list = db.list_vps()
    nodes = db.list_nodes()
    for v in vps_list:
        node = db.get_node(v["node_id"])
        try:
            v["live_status"] = dm.get_status(node, v["container_name"]) if node else "no-node"
        except Exception:
            v["live_status"] = "unknown"
    return render("vps_management.html", request, username=request.session.get("username"),
                  vps_list=vps_list, nodes=nodes, os_images=OS_IMAGES, active_page="vps")


@app.get("/api/nodes/{node_id}/next-port")
async def api_next_port(node_id: int, request: Request):
    require_owner(request)
    return {"port": db.next_free_port(node_id)}


@app.post("/vps/create")
async def vps_create(request: Request, vps_name: str = Form(...), node_id: int = Form(...),
                      discord_id: str = Form(...), os_image_key: str = Form(...),
                      ram_limit: str = Form(...), cpu_limit: str = Form(...), disk_limit: str = Form(...),
                      ssh_port: int = Form(...), time_days: int = Form(...), plan: str = Form(...),
                      price: str = Form(...), mem_bytes: str = Form(...), nano_cpus: str = Form(...)):
    require_owner(request)
    job_id = jm.create_job()

    def run():
        try:
            jm.add_step(job_id, "Validating node")
            node = db.get_node(node_id)
            if not node:
                raise ValueError("Node not found")
            jm.complete_last_step(job_id)

            jm.add_step(job_id, f"Connecting to node '{node['name']}'")
            client = dm.get_client(node)
            client.ping()
            jm.complete_last_step(job_id)

            _, image = OS_IMAGES.get(os_image_key, ("Ubuntu 24.04", "ubuntu:24.04"))
            jm.add_step(job_id, f"Pulling image {image}")
            try:
                client.images.pull(image)
            except Exception:
                pass
            jm.complete_last_step(job_id)

            jm.add_step(job_id, "Creating Docker container")
            container = client.containers.run(
                image, name=vps_name, detach=True, tty=True,
                ports={"22/tcp": ssh_port}, mem_limit=mem_bytes, nano_cpus=int(nano_cpus),
                labels={"legacycloud": "vps"}, command="sleep infinity",
            )
            jm.complete_last_step(job_id)

            jm.add_step(job_id, "Installing SSH server")
            container.exec_run("bash -c 'apt update && apt install -y openssh-server && service ssh start' || "
                                "sh -c 'apk add openssh && ssh-keygen -A && /usr/sbin/sshd'")
            jm.complete_last_step(job_id)

            jm.add_step(job_id, "Setting root username & generating password")
            new_password = dm.reset_password(node, vps_name)
            jm.complete_last_step(job_id)

            jm.add_step(job_id, "Registering anti-mining protection tag")
            jm.complete_last_step(job_id)

            jm.add_step(job_id, "Saving VPS to database")
            vps_id, renewal_date = db.add_vps(node_id, discord_id, vps_name, os_image_key, ssh_port,
                                               new_password, ram_limit, cpu_limit, disk_limit, plan, price, time_days)
            jm.complete_last_step(job_id)

            jm.add_step(job_id, "Queuing credential delivery to customer")
            db.queue_delivery(vps_id)
            jm.complete_last_step(job_id)

            jm.finish_job(job_id, result={"vps_id": vps_id, "renewal_date": renewal_date})
        except Exception as e:
            jm.fail_last_step(job_id, str(e))

    import threading
    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    require_owner(request)
    job = jm.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/vps/{vps_id}/deliver")
async def vps_deliver(vps_id: int, request: Request):
    require_owner(request)
    db.queue_delivery(vps_id)
    return {"ok": True}


@app.post("/vps/{vps_id}/delete")
async def vps_delete(vps_id: int, request: Request):
    require_owner(request)
    vps = db.get_vps(vps_id)
    if vps:
        node = db.get_node(vps["node_id"])
        if node:
            dm.remove_container(node, vps["container_name"])
        db.delete_vps(vps_id)
    return RedirectResponse("/vps", status_code=303)


@app.post("/api/vps/{vps_id}/start")
async def api_start(vps_id: int, request: Request):
    require_owner(request)
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    dm.start_container(node, vps["container_name"]); return {"ok": True}


@app.post("/api/vps/{vps_id}/stop")
async def api_stop(vps_id: int, request: Request):
    require_owner(request)
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    dm.stop_container(node, vps["container_name"]); return {"ok": True}


@app.post("/api/vps/{vps_id}/restart")
async def api_restart(vps_id: int, request: Request):
    require_owner(request)
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    dm.restart_container(node, vps["container_name"]); return {"ok": True}


@app.post("/api/vps/{vps_id}/reset-password")
async def api_reset_password(vps_id: int, request: Request):
    require_owner(request)
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    new_password = dm.reset_password(node, vps["container_name"])
    db.update_vps(vps_id, ssh_password=new_password)
    return {"ok": True, "new_password": new_password}


@app.post("/api/vps/{vps_id}/terminal/start")
async def api_terminal_start(vps_id: int, request: Request):
    require_owner(request)
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    port = tm.start_terminal(node, vps["container_name"])
    return {"ok": True, "url": f"http://{PUBLIC_HOST}:{port}"}


@app.get("/bot-settings")
async def bot_settings(request: Request):
    require_owner(request)
    token = db.get_bot_token()
    masked = (token[:6] + "..." + token[-4:]) if token else None
    return render("bot_settings.html", request, username=request.session.get("username"),
                  masked_token=masked, is_running=bm.is_running(), heartbeat=db.get_bot_heartbeat(),
                  delivery_log=db.get_delivery_log(), active_page="bot")


@app.post("/bot-settings/save-token")
async def save_token(request: Request, token: str = Form(...)):
    require_owner(request)
    db.save_bot_token(token)
    return RedirectResponse("/bot-settings", status_code=303)


@app.post("/api/bot/start")
async def api_bot_start(request: Request):
    require_owner(request)
    ok, msg = bm.start_bot(db.get_bot_token()); return {"ok": ok, "message": msg}


@app.post("/api/bot/stop")
async def api_bot_stop(request: Request):
    require_owner(request)
    ok, msg = bm.stop_bot(); return {"ok": ok, "message": msg}


@app.post("/api/bot/restart")
async def api_bot_restart(request: Request):
    require_owner(request)
    ok, msg = bm.restart_bot(db.get_bot_token()); return {"ok": ok, "message": msg}


@app.get("/settings")
async def settings_page(request: Request):
    require_owner(request)
    return render("settings.html", request, username=request.session.get("username"),
                  api_keys=db.list_api_keys(), public_host=PUBLIC_HOST, panel_port=PANEL_PORT,
                  background_themes=BACKGROUND_THEMES, active_page="settings")


@app.post("/settings/api-keys/create")
async def create_key(request: Request, name: str = Form(...)):
    require_owner(request)
    db.create_api_key(name)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/api-keys/{key_id}/revoke")
async def revoke_key(key_id: int, request: Request):
    require_owner(request)
    db.revoke_api_key(key_id)
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/branding/logo")
async def upload_logo(request: Request, logo: UploadFile = File(...)):
    require_owner(request)
    ext = logo.filename.split(".")[-1]
    save_path = f"static/uploads/logo.{ext}"
    with open(save_path, "wb") as f:
        f.write(await logo.read())
    db.save_branding(logo_url=f"/{save_path}")
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/branding/theme")
async def set_theme(request: Request, background_theme: str = Form(...)):
    require_owner(request)
    db.save_branding(background_theme=background_theme)
    return RedirectResponse("/settings", status_code=303)


@app.get("/api/v1/nodes")
async def api_v1_list_nodes(key: str = Depends(require_api_key)):
    nodes = db.list_nodes()
    for n in nodes:
        ok, _ = dm.test_node_connection(n)
        n["online"] = ok
    return {"nodes": nodes}


@app.get("/api/v1/vps")
async def api_v1_list_vps(key: str = Depends(require_api_key)):
    return {"vps": db.list_vps()}


@app.get("/api/v1/vps/{vps_id}")
async def api_v1_get_vps(vps_id: int, key: str = Depends(require_api_key)):
    vps = db.get_vps(vps_id)
    if not vps:
        raise HTTPException(status_code=404, detail="VPS not found")
    return vps


@app.post("/api/v1/vps")
async def api_v1_create_vps(request: Request, key: str = Depends(require_api_key)):
    body = await request.json()
    node = db.get_node(body["node_id"])
    if not node:
        raise HTTPException(status_code=400, detail="Node not found")
    _, image = OS_IMAGES.get(body["os_image_key"], ("Ubuntu 24.04", "ubuntu:24.04"))
    dm.create_vps_container(node, body["vps_name"], image, body["ssh_port"], body["mem_bytes"], int(body["nano_cpus"]))
    new_password = dm.reset_password(node, body["vps_name"])
    vps_id, renewal_date = db.add_vps(
        body["node_id"], body["discord_id"], body["vps_name"], body["os_image_key"], body["ssh_port"],
        new_password, body["ram_limit"], body["cpu_limit"], body["disk_limit"], body["plan"], body["price"], body["time_days"]
    )
    db.queue_delivery(vps_id)
    return {"ok": True, "vps_id": vps_id, "renewal_date": renewal_date, "ssh_password": new_password}


@app.post("/api/v1/vps/{vps_id}/suspend")
async def api_v1_suspend(vps_id: int, key: str = Depends(require_api_key)):
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    dm.stop_container(node, vps["container_name"]); db.set_vps_status(vps_id, "suspended")
    return {"ok": True}


@app.post("/api/v1/vps/{vps_id}/unsuspend")
async def api_v1_unsuspend(vps_id: int, key: str = Depends(require_api_key)):
    vps = db.get_vps(vps_id); node = db.get_node(vps["node_id"])
    dm.start_container(node, vps["container_name"]); db.set_vps_status(vps_id, "active")
    return {"ok": True}


@app.delete("/api/v1/vps/{vps_id}")
async def api_v1_delete(vps_id: int, key: str = Depends(require_api_key)):
    vps = db.get_vps(vps_id)
    if vps:
        node = db.get_node(vps["node_id"])
        if node:
            dm.remove_container(node, vps["container_name"])
        db.delete_vps(vps_id)
    return {"ok": True}


@app.post("/api/v1/vps/{vps_id}/renew")
async def api_v1_renew(vps_id: int, request: Request, key: str = Depends(require_api_key)):
    body = await request.json()
    from datetime import datetime as dt, timedelta
    new_date = (dt.utcnow() + timedelta(days=int(body.get("time_days", 30)))).date().isoformat()
    db.update_vps(vps_id, renewal_date=new_date, status="active")
    return {"ok": True, "renewal_date": new_date}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PANEL_PORT)
