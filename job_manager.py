import uuid
import threading

_jobs = {}
_lock = threading.Lock()


def create_job():
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"steps": [], "done": False, "error": None, "result": None}
    return job_id


def add_step(job_id, name, status="in_progress"):
    with _lock:
        _jobs[job_id]["steps"].append({"name": name, "status": status})


def complete_last_step(job_id):
    with _lock:
        if _jobs[job_id]["steps"]:
            _jobs[job_id]["steps"][-1]["status"] = "done"


def fail_last_step(job_id, error):
    with _lock:
        if _jobs[job_id]["steps"]:
            _jobs[job_id]["steps"][-1]["status"] = "failed"
        _jobs[job_id]["error"] = error
        _jobs[job_id]["done"] = True


def finish_job(job_id, result=None):
    with _lock:
        _jobs[job_id]["done"] = True
        _jobs[job_id]["result"] = result


def get_job(job_id):
    with _lock:
        return _jobs.get(job_id)
