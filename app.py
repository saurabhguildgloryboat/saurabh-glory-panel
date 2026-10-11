#!/usr/bin/env python3
"""
Eren Glory — Flask + bot + guild lookup + persistent jobs.
"""
import os, re, sys, json, time, uuid, hmac, base64, random, hashlib, secrets
import threading, traceback, collections
import socket, struct, math, ssl
import asyncio
from datetime import datetime, timedelta
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, jsonify, Response, session, redirect, url_for
import requests, aiohttp, urllib3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from protobuf_decoder.protobuf_decoder import Parser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════
BOT_NAME = "EREN"
API_URLS = [
    "https://genforglory10.vercel.app",
    "https://genforglory11.vercel.app",
    "https://genforglory12.vercel.app",
    "https://genforglory13.vercel.app",
]
_API_TIMEOUT = 120
API_RETRY_ATTEMPTS = 3
ACCOUNTS_PER_SQUAD = 4

ADMIN_USER = "Eren7587"
ADMIN_PASS = "Eren@7587#"

USER_MAX_SQUADS       = 2
USER_MAX_RUN_SECONDS  = 8 * 3600
CREDIT_COST_PER_SQUAD = 1
MAX_SQUADS_HARD       = 8

# ═══════════════════════════════════════════════════════════════════
# PATHS
# ═══════════════════════════════════════════════════════════════════
_IS_VERCEL  = bool(os.environ.get("VERCEL"))
_BASE_DIR   = "/tmp" if _IS_VERCEL else os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.dirname(os.path.abspath(__file__))

USER_FILE      = os.path.join(_BASE_DIR, "users.json")
DEBUG_FILE     = os.path.join(_BASE_DIR, "debug.txt")
UDP_LOG_FILE   = os.path.join(_BASE_DIR, "udp_logs.txt")
JWT_CACHE_FILE = os.path.join(_BASE_DIR, "jwt_cache.json")
JOBS_FILE      = os.path.join(_BASE_DIR, "jobs.json")
LOGIN_HTML     = os.path.join(_STATIC_DIR, "login.html")
DASHBOARD_HTML = os.path.join(_STATIC_DIR, "dashboard.html")

# ═══════════════════════════════════════════════════════════════════
# DEBUG
# ═══════════════════════════════════════════════════════════════════
_dbg_lock = threading.Lock()

def _dbg_open():
    try:
        with open(DEBUG_FILE, "w", encoding="utf-8") as f:
            f.write(f"# ere glory debug — {datetime.now().isoformat()}\n")
    except Exception: pass

def _dbg(tag, msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] [{level:<5}] [{tag}] {msg}"
    with _dbg_lock:
        try:
            with open(DEBUG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception: pass

# ═══════════════════════════════════════════════════════════════════
# GUILD LOOKUP
# ═══════════════════════════════════════════════════════════════════
JWT_API_URL  = "https://fastob55-jwt.lovable.app/api/public/token"
INFO_API_URL = "https://star-guild-info.lovable.app/api/public/info/direct"
JWT_TTL_SECONDS = 4 * 3600 + 1800

def _env(k, d=""):
    return (os.environ.get(k) or d).strip()

GUILD_ACCOUNTS = {
    "IND": {"uid": _env("GUILD_IND_UID"), "password": _env("GUILD_IND_PASSWORD")},
    "BR":  {"uid": _env("GUILD_BR_UID"),  "password": _env("GUILD_BR_PASSWORD")},
    "BD":  {"uid": _env("GUILD_BD_UID"),  "password": _env("GUILD_BD_PASSWORD")},
}
REGION_TO_ACCOUNT = {"IND": "IND", "BR": "BR", "SAC": "BR", "NA": "BR", "US": "BR"}
ALL_ACCOUNTS = ["IND", "BR", "BD"]
_guild_cache_lock = threading.Lock()

def _guild_load_cache():
    try:
        with open(JWT_CACHE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f); return d if isinstance(d, dict) else {}
    except Exception: return {}

def _guild_save_cache(data):
    try:
        with _guild_cache_lock:
            with open(JWT_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            try: os.chmod(JWT_CACHE_FILE, 0o600)
            except Exception: pass
    except Exception: pass

def _guild_account_for_region(region):
    if not region: return "IND"
    return REGION_TO_ACCOUNT.get(str(region).strip().upper(), "BD")

def _guild_cache_valid(entry):
    if not entry or not entry.get("token"): return False
    return (time.time() - (entry.get("fetched_at") or 0)) < JWT_TTL_SECONDS

def _guild_generate_token(account_key):
    acc = GUILD_ACCOUNTS.get(account_key) or {}
    if not acc.get("uid") or not acc.get("password"): return None
    try:
        r = requests.get(JWT_API_URL, params={"uid": acc["uid"], "password": acc["password"]}, timeout=20)
        if r.status_code != 200: return None
        data = r.json()
        for path in (("token",), ("jwt",), ("jwt_token",), ("access_token",),
                     ("data", "token"), ("data", "jwt")):
            cur = data; ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur: cur = cur[k]
                else: ok = False; break
            if ok and isinstance(cur, str) and cur: return cur
        return None
    except Exception: return None

def guild_get_token(account_key, force_refresh=False):
    cache = _guild_load_cache()
    entry = cache.get(account_key)
    if not force_refresh and _guild_cache_valid(entry): return entry["token"]
    token = _guild_generate_token(account_key)
    if token:
        cache[account_key] = {"token": token, "fetched_at": time.time()}
        _guild_save_cache(cache)
    return token

def guild_invalidate_token(account_key):
    cache = _guild_load_cache()
    if account_key in cache:
        cache.pop(account_key, None); _guild_save_cache(cache)

def guild_get_cache_info():
    cache = _guild_load_cache(); now = time.time(); out = {}
    for key in ALL_ACCOUNTS:
        entry = cache.get(key) or {}
        token = entry.get("token") or ""; fetched_at = entry.get("fetched_at")
        age = int(now - fetched_at) if fetched_at else None
        out[key] = {
            "has_token": bool(token), "fetched_at": fetched_at,
            "age_seconds": age,
            "expires_in_seconds": int(JWT_TTL_SECONDS - (age or 0)) if age is not None else None,
            "is_stale": (age is not None and age >= JWT_TTL_SECONDS),
        }
    return out

def guild_refresh_all_tokens():
    results = {}
    for key in ALL_ACCOUNTS:
        guild_invalidate_token(key)
        results[key] = bool(guild_get_token(key, force_refresh=True))
    return results

def _gnorm(k): return re.sub(r"[\s_\-]+", "", str(k).lower())
def _gvalid(v): return v not in (None, "", 0, "0", "00", "000")

def _gdeep_find(obj, key_patterns, max_depth=8):
    if max_depth <= 0 or obj is None: return None
    if isinstance(obj, dict):
        wanted = {_gnorm(p) for p in key_patterns}
        for k, v in obj.items():
            if _gnorm(k) in wanted and _gvalid(v): return v
        for k, v in obj.items():
            kn = _gnorm(k)
            for p in key_patterns:
                if _gnorm(p) in kn and _gvalid(v): return v
        for v in obj.values():
            r = _gdeep_find(v, key_patterns, max_depth - 1)
            if r is not None: return r
    elif isinstance(obj, list):
        for item in obj:
            r = _gdeep_find(item, key_patterns, max_depth - 1)
            if r is not None: return r
    return None

def _gbuild_candidates(data, max_depth=4):
    out = []
    def walk(o, d):
        if d > max_depth: return
        if isinstance(o, dict):
            out.append(o)
            for v in o.values(): walk(v, d + 1)
        elif isinstance(o, list):
            for it in o: walk(it, d + 1)
    walk(data, 0); return out

def _gto_int(v, default=0):
    try:
        if isinstance(v, str): v = v.strip()
        return int(float(v)) if v not in (None, "") else default
    except Exception: return default

def _gparse_guild(data):
    if not isinstance(data, dict): return None
    cands = _gbuild_candidates(data)
    def pick(*keys):
        for c in cands:
            for k in keys:
                if k in c and _gvalid(c[k]): return c[k]
        return None
    name = pick("clan_name","clanname","name","guild_name","guildname","clanName","guildName")
    if not name: name = _gdeep_find(data, ["clanname","clan_name","guildname","guild_name"])
    if not name: return None
    level = pick("guild_level","guildlevel","level","clan_level","clanLevel","guildLevel") or 1
    cur = pick("current_members","member_num","members","memberCount","membercount","cur_members") or 0
    total = pick("total_members","capacity","max_members","maxMembers","maxmembers","member_capacity","totalMembers") or 50
    glory = pick("glory_points","glory","total_glory","gloryPoints","glorypoints","gloryPoint") or 0
    leader = _gdeep_find(data, [
        "guildleaderid","guild_leader_id","leaderid","leader_id",
        "captainid","captain_id","leaderuid","leader_uid",
        "clanleaderid","clan_leader_id","guildleaderuid",
    ]) or ""
    welcome = pick("welcome_message","slogan","message","welcomeMessage") or ""
    region = pick("region","server","region_name","regionName") or ""
    return {
        "clan_name": str(name), "guild_id": "",
        "guild_level": _gto_int(level, 1),
        "current_members": _gto_int(cur, 0),
        "total_members": _gto_int(total, 50),
        "guild_leader_id": str(leader),
        "glory_points": _gto_int(glory, 0),
        "welcome_message": str(welcome), "region": str(region),
    }

def _gis_token_error(data):
    if not isinstance(data, dict): return False
    s = json.dumps(data).lower()
    return any(m in s for m in ("invalid_jwt","token_expired","jwt_expired",
                                "unauthorized","invalid_token","auth_failed"))

def _gis_not_found(data):
    if not isinstance(data, dict): return False
    s = json.dumps(data).lower()
    return "nf_clan" in s or "not_found" in s or "not found" in s

def fetch_guild_info(guild_id, region=None):
    guild_id = str(guild_id).strip()
    region = (region or "").strip().upper() or None
    if region:
        primary = _guild_account_for_region(region)
        order = [primary] + [a for a in ALL_ACCOUNTS if a != primary]
    else:
        order = list(ALL_ACCOUNTS)
    last_error = "Guild not found"; errors = []
    for acc in order:
        try:
            token = guild_get_token(acc)
            if not token:
                errors.append(f"{acc}: no token"); continue
            use_region = region if region else acc
            params = {"clan_id": guild_id, "region": use_region, "jwt_token": token}
            r = requests.get(INFO_API_URL, params=params, timeout=25)
            try: data = r.json()
            except Exception:
                errors.append(f"{acc}: bad JSON"); continue
            if _gis_token_error(data):
                guild_invalidate_token(acc)
                token = guild_get_token(acc, force_refresh=True)
                if token:
                    params["jwt_token"] = token
                    r = requests.get(INFO_API_URL, params=params, timeout=25)
                    try: data = r.json()
                    except Exception: data = {"error": "bad JSON"}
            parsed = _gparse_guild(data)
            if parsed and parsed.get("clan_name"):
                parsed["guild_id"] = guild_id
                return {"ok": True, "guild": parsed, "account_used": acc, "region_used": use_region}
            if _gis_not_found(data):
                errors.append(f"{acc}: not found in {use_region}")
                last_error = f"Guild not found in region {use_region}"; continue
            err = data.get("error") or data.get("message") or "parse_failed"
            errors.append(f"{acc}: {err}"); last_error = err
        except Exception as e:
            errors.append(f"{acc}: {type(e).__name__}"); last_error = str(e)
    return {"ok": False, "error": last_error, "attempts": errors}

# ═══════════════════════════════════════════════════════════════════
# USER STORE
# ═══════════════════════════════════════════════════════════════════
_user_lock = threading.Lock()

def _load_users():
    if not os.path.exists(USER_FILE): return []
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception: return []

def _save_users(users):
    with _user_lock:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)

def _hash_password(password, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return dk.hex(), salt.hex()

def _verify_password(password, stored, salt_hex):
    calc, _ = _hash_password(password, salt_hex)
    return hmac.compare_digest(calc, stored)

def _find_user(username):
    u = (username or "").lower().strip()
    for user in _load_users():
        if user.get("username","").lower() == u: return user
    return None

def _find_user_by_email(email):
    e = (email or "").lower().strip()
    for user in _load_users():
        if user.get("email","").lower() == e: return user
    return None

def _update_user(username, fn):
    with _user_lock:
        users = _load_users()
        for u in users:
            if u.get("username","").lower() == username.lower():
                fn(u)
                with open(USER_FILE, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=2, ensure_ascii=False)
                return True
    return False

def _public_user(u):
    return {
        "username": u.get("username"), "email": u.get("email"),
        "credits": u.get("credits", 0), "total_glory": u.get("total_glory", 0),
        "total_runs": len(u.get("history", [])),
        "created_at": u.get("created_at"),
        "history": u.get("history", [])[-20:],
    }

# ═══════════════════════════════════════════════════════════════════
# JOBS  (persistent deploy jobs)
# ═══════════════════════════════════════════════════════════════════
_jobs_lock = threading.Lock()
_JOBS = {}                              # job_id -> job dict


def _job_public(j):
    return {
        "id": j["id"],
        "owner": j.get("owner"),
        "region": j.get("region"),
        "squads": j.get("squads"),
        "clan_id": j.get("clan_id"),
        "status": j.get("status", "idle"),
        "phase": j.get("phase", ""),
        "created_at": j.get("created_at"),
        "started_at": j.get("started_at"),
        "stopped_at": j.get("stopped_at"),
        "glory": j.get("glory", 0),
        "rewards": j.get("rewards", {}),
        "squad_status": j.get("squad_status", {}),
        "error": j.get("error"),
        "paused": bool(j.get("_paused")),
        "event_count": j.get("event_count", 0),
    }


def _save_jobs():
    with _jobs_lock:
        data = []
        for j in _JOBS.values():
            data.append({
                "id": j["id"], "owner": j.get("owner"),
                "region": j.get("region"), "squads": j.get("squads"),
                "clan_id": j.get("clan_id"), "is_admin": j.get("is_admin", False),
                "status": j.get("status", "idle"),
                "phase": j.get("phase", ""),
                "created_at": j.get("created_at"),
                "started_at": j.get("started_at"),
                "stopped_at": j.get("stopped_at"),
                "glory": j.get("glory", 0),
                "rewards": j.get("rewards", {}),
                "squad_status": j.get("squad_status", {}),
                "error": j.get("error"),
                "paused": bool(j.get("_paused")),
            })
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        try: os.chmod(JOBS_FILE, 0o600)
        except Exception: pass
    except Exception as e:
        _dbg("JOBS", f"save failed: {type(e).__name__}: {e}", "ERR")


def _load_jobs_from_disk():
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _create_job(owner, region, squads, clan_id, is_admin):
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    job = {
        "id": jid, "owner": owner, "region": region, "squads": squads,
        "clan_id": clan_id, "is_admin": is_admin,
        "status": "starting", "phase": "starting",
        "created_at": now, "started_at": now, "stopped_at": None,
        "glory": 0, "rewards": {}, "squad_status": {},
        "events": collections.deque(maxlen=2000), "event_count": 0,
        "error": None,
        "_loop": None, "_task": None, "_thread": None, "_paused": False,
    }
    with _jobs_lock:
        _JOBS[jid] = job
    _save_jobs()
    return job


def _job_get(job_id): return _JOBS.get(job_id)


def _job_start_thread(job):
    t = threading.Thread(target=_job_thread, args=(job,), daemon=True,
                         name=f"job-{job['id']}")
    job["_thread"] = t
    t.start()
    threading.Thread(target=_job_watchdog, args=(job,), daemon=True).start()


def _job_watchdog(job):
    while job.get("status") in ("running", "paused", "starting", "restarting"):
        time.sleep(15)
        if job.get("is_admin"): continue
        if time.time() - (job.get("started_at") or 0) > USER_MAX_RUN_SECONDS:
            warn(f"job {job['id']} hit 8h limit — stopping")
            _job_stop(job["id"])
            return


def _job_thread(job):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    job["_loop"] = loop
    try:
        task = loop.create_task(_glory_async(job))
        job["_task"] = task
        loop.run_until_complete(task)
        job["phase"] = "done"; job["status"] = "done"
    except asyncio.CancelledError:
        job["phase"] = "stopped"
        if job.get("status") != "restarting":
            job["status"] = "stopped"
    except Exception as e:
        job["phase"] = "error"; job["status"] = "error"
        job["error"] = str(e)
        err(f"job {job['id']} fatal: {e}")
    finally:
        try: loop.close()
        except Exception: pass
        job["stopped_at"] = time.time()
        job["_loop"] = None; job["_task"] = None

        if job.get("status") != "restarting":
            try:
                owner = job.get("owner")
                glory = int(job.get("rewards", {}).get("glory", 0) or 0)
                if owner and not job.get("is_admin") and glory > 0:
                    _update_user(owner, lambda u: (
                        u.__setitem__("total_glory", u.get("total_glory", 0) + glory),
                        u.setdefault("history", []).append({
                            "id": job["id"],
                            "region": job["region"],
                            "squads": job["squads"],
                            "glory": glory,
                            "started_at": datetime.fromtimestamp(job["started_at"]).isoformat(),
                            "stopped_at": datetime.fromtimestamp(job["stopped_at"]).isoformat(),
                            "duration": int(job["stopped_at"] - job["started_at"]),
                        }),
                        u["history"].__setitem__(slice(-20), u["history"][-20:]),
                    ))
            except Exception as e:
                _dbg("CREDIT", f"failed: {type(e).__name__}: {e}", "WARN")
        _save_jobs()


def _job_stop(job_id):
    job = _JOBS.get(job_id)
    if not job: return False
    if job.get("status") in ("stopped", "done", "error"): return True
    job["status"] = "stopped"; job["_paused"] = False
    loop = job.get("_loop"); task = job.get("_task")
    if loop and task:
        try: loop.call_soon_threadsafe(task.cancel)
        except Exception: pass
    _save_jobs()
    return True


def _job_pause(job_id):
    job = _JOBS.get(job_id)
    if not job: return False
    if job.get("status") not in ("running", "starting"): return False
    job["_paused"] = True; job["status"] = "paused"
    _save_jobs()
    return True


def _job_resume(job_id):
    job = _JOBS.get(job_id)
    if not job: return False
    if job.get("status") != "paused": return False
    job["_paused"] = False; job["status"] = "running"
    _save_jobs()
    return True


def _job_restart(job_id):
    job = _JOBS.get(job_id)
    if not job: return False

    job["status"] = "restarting"; job["_paused"] = False
    loop = job.get("_loop"); task = job.get("_task")
    if loop and task:
        try: loop.call_soon_threadsafe(task.cancel)
        except Exception: pass

    old_thread = job.get("_thread")
    deadline = time.time() + 12
    while old_thread and old_thread.is_alive() and time.time() < deadline:
        time.sleep(0.2)

    with _jobs_lock:
        job["status"] = "starting"; job["phase"] = "starting"
        job["started_at"] = time.time(); job["stopped_at"] = None
        job["glory"] = 0; job["rewards"] = {}; job["squad_status"] = {}
        job["events"] = collections.deque(maxlen=2000); job["event_count"] = 0
        job["error"] = None; job["_paused"] = False
    _save_jobs()
    _job_start_thread(job)
    return True


def _job_delete(job_id):
    job = _JOBS.get(job_id)
    if not job: return False
    if job.get("status") in ("running", "paused", "starting", "restarting"):
        _job_stop(job_id)
        old = job.get("_thread"); deadline = time.time() + 5
        while old and old.is_alive() and time.time() < deadline:
            time.sleep(0.2)
    with _jobs_lock:
        _JOBS.pop(job_id, None)
    _save_jobs()
    return True


def _restore_jobs_on_boot():
    jobs = _load_jobs_from_disk()
    if not jobs:
        _dbg("JOBS", "no jobs to restore"); return
    for data in jobs:
        jid = data.get("id")
        if not jid: continue
        now = time.time()
        job = {
            "id": jid,
            "owner": data.get("owner"),
            "region": data.get("region", "IND"),
            "squads": data.get("squads", 1),
            "clan_id": data.get("clan_id"),
            "is_admin": data.get("is_admin", False),
            "status": "starting", "phase": "restoring",
            "created_at": data.get("created_at", now),
            "started_at": now, "stopped_at": None,
            "glory": 0, "rewards": {}, "squad_status": {},
            "events": collections.deque(maxlen=2000), "event_count": 0,
            "error": None,
            "_loop": None, "_task": None, "_thread": None, "_paused": False,
        }
        with _jobs_lock:
            _JOBS[jid] = job
        prev = data.get("status")
        if prev in ("running", "paused", "starting", "restarting"):
            _dbg("JOBS", f"auto-restart job {jid} (was {prev})")
            _job_start_thread(job)
        else:
            job["status"] = prev or "stopped"
            job["phase"] = "stopped"
            job["stopped_at"] = data.get("stopped_at")
            job["glory"] = data.get("glory", 0)
            job["rewards"] = data.get("rewards", {})
    _save_jobs()

# ═══════════════════════════════════════════════════════════════════
# THREAD-LOCAL current-run so multi-threaded logs route correctly
# ═══════════════════════════════════════════════════════════════════
_tls = threading.local()
def _set_current_run(run): _tls.run = run
def _current_run(): return getattr(_tls, "run", None)

R="\033[0m"; B="\033[1m"; D="\033[2m"; GR="\033[90m"
RD="\033[91m"; GN="\033[92m"; YL="\033[93m"; CY="\033[96m"; WH="\033[97m"; MG="\033[95m"
_print_lock = threading.Lock()

def _ts(): return datetime.now().strftime("%H:%M:%S")

def _push_event(run, level, msg, squad=None):
    if run is None: return
    evt = {"t": datetime.now().strftime("%H:%M:%S"), "level": level, "msg": msg, "squad": squad}
    with _jobs_lock:
        try:
            run["events"].append(evt); run["event_count"] += 1
        except Exception: pass

def line(msg, color=WH, prefix="·", level="info", squad=None):
    with _print_lock:
        print(f"{GR}{_ts()}{R} {color}{prefix}{R} {msg}", flush=True)
    _dbg("CONSOLE", f"{prefix} {msg}")
    _push_event(_current_run(), level, msg, squad)

def ok(msg):     line(msg, GN, "✔", "ok")
def warn(msg):   line(msg, YL, "!", "warn")
def err(msg):    line(msg, RD, "✘", "err")
def info(msg):   line(msg, GR, "·")
def action(msg): line(msg, CY, "»")

def squad_line(n, msg, color=CY, prefix="»", level="info"):
    with _print_lock:
        print(f"{GR}{_ts()}{R} {MG}{B}[Squad {n}]{R} {color}{prefix}{R} {msg}", flush=True)
    _dbg(f"SQ{n}", f"{prefix} {msg}")
    _push_event(_current_run(), level, msg, n)

def squad_ok(n, msg):   squad_line(n, msg, GN, "✔", "ok")
def squad_warn(n, msg): squad_line(n, msg, YL, "!", "warn")
def squad_err(n, msg):  squad_line(n, msg, RD, "✘", "err")

# ═══════════════════════════════════════════════════════════════════
# REGION TABLES
# ═══════════════════════════════════════════════════════════════════
REGION_LIST = ["IND","ID","TH","ME","EUROPE","VN","BD","PK","TW","RU","NA","SAC","BR","SG","US"]
REGION_LIST_ALLOWED = set(REGION_LIST)
REGION_LANG = {"ME":"ar","IND":"hi","ID":"id","VN":"vi","TH":"th","BD":"bn","PK":"ur",
               "TW":"zh","EUROPE":"fr","RU":"ru","NA":"na","SAC":"es","BR":"pt","SG":"ms","US":"us"}
REGION_GROUP = {
    "IND":"IND",
    "BR":"AMERICA","US":"AMERICA","NA":"AMERICA","SAC":"AMERICA",
    "ID":"OTHERS","TH":"OTHERS","ME":"OTHERS","EUROPE":"OTHERS",
    "VN":"OTHERS","BD":"OTHERS","PK":"OTHERS","TW":"OTHERS","RU":"OTHERS","SG":"OTHERS",
}
REGION_URLS = {
    "IND":    {"server":"https://loginbp.ggpolarbear.com/","client":"https://client.ind.freefiremobile.com/"},
    "AMERICA":{"server":"https://loginbp.ggpolarbear.com/","client":"https://client.us.freefiremobile.com/"},
    "OTHERS": {"server":"https://loginbp.ggpolarbear.com/","client":"https://clientbp.ggpolarbear.com/"},
}
REGION = "IND"; LANG_CODE = "hi"
SERVER_URL = REGION_URLS["IND"]["server"]
CLIENT_URL = REGION_URLS["IND"]["client"]

# ═══════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════
APP_ID=100067; CLIENT_TYPE=2; SOURCE=2
SECRET = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
PASSWORD_RAW = "Eren"
PASSWORD = hashlib.sha256(PASSWORD_RAW.encode()).hexdigest().upper()

GARENA_BASE  = "https://100067.connect.garena.com/api/v2/oauth"
REGISTER_URL = f"{GARENA_BASE}/guest:register"
GRANT_URL    = f"{GARENA_BASE}/guest/token:grant"
DATADOME_URL  = "https://datadome.garena.com/js/"
VER_URL_BASE  = "https://version.ggwhitehawk.com/live/ver.php"
PLAYSTORE_URL = "https://play.google.com/store/apps/details?id=com.dts.freefireth&hl=en&gl=US"

MIN_REGISTER_INTERVAL=1.0; REGISTER_BACKOFF_START=20.0; REGISTER_BACKOFF_MAX=180.0
REGISTER_MAX_RETRIES=12; DATADOME_MAX_RETRIES=4; VER_MAX_ATTEMPTS=3

USER_AGENT_MSDK  = "GarenaMSDK/4.0.44(V2538 ;Android 16;en;US;app 1.132.1 2019121227;)"
USER_AGENT_UNITY = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
USER_AGENT_WEB   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

KEY = bytes([89,103,38,116,99,37,68,69,117,104,54,37,90,99,94,56])
IV  = bytes([54,111,121,90,68,114,50,50,69,51,121,99,104,106,77,37])
AUTH_AES_KEY = bytes([0x19,0x47,0xB9,0x74,0xD9,0x73,0xF3,0x7F,
                      0x42,0x06,0x01,0x38,0x42,0x00,0x10,0x30])
AUTH_AES_IV  = bytes([0x28,0x7F,0xCA,0x7A,0xF9,0x67,0xF3,0x7A,
                      0x65,0x02,0x01,0x10,0x40,0x40,0x00,0x30])
AUTH_CMD = 0x65
_KEYSTREAM = bytes([
    0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,
    0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,
])
SESSION_HASH = "1ac4b80ecf0478a44203bf8fac6120f5"
Play_Version = "1.132.1"; Ob_VeR = "OB55"; CFG = {}
_gate_lock=threading.Lock(); _dd_lock=threading.Lock()
_last_register_time=0.0; _dd_session_cookie=None; _dd_expires_at=0.0
_LOGIN_LOCK=None
def _get_login_lock():
    global _LOGIN_LOCK
    if _LOGIN_LOCK is None: _LOGIN_LOCK = asyncio.Lock()
    return _LOGIN_LOCK

# ═══════════════════════════════════════════════════════════════════
# CRYPTO / PROTO
# ═══════════════════════════════════════════════════════════════════
def enc_aes(data): return AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(data, 16))
def dec_aes(data):
    try: return unpad(AES.new(KEY, AES.MODE_CBC, IV).decrypt(data), 16)
    except ValueError: return AES.new(KEY, AES.MODE_CBC, IV).decrypt(data)

def sign_body(body): return hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
def encode_open_id(oid):
    return bytes(ord(oid[i]) ^ _KEYSTREAM[i % len(_KEYSTREAM)] for i in range(len(oid)))
def decode_jwt_payload(token):
    try:
        parts = token.split(".")
        if len(parts) != 3: return {}
        p2 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(p2))
    except Exception: return {}
def enc_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F; v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v: return bytes(out)
def read_varint(data, off):
    v, s = 0, 0
    while True:
        b = data[off]; off += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80): return v, off
        s += 7
def ptag(f, wt): return enc_varint((f << 3) | wt)
def f_vint(f, n):  return ptag(f, 0) + enc_varint(n)
def f_bytes(f, b): return ptag(f, 2) + enc_varint(len(b)) + b
def f_str(f, s):
    b = s.encode("utf-8"); return ptag(f, 2) + enc_varint(len(b)) + b

def parse_proto(data):
    fields = {}; i = 0
    while i < len(data):
        try: key, i = read_varint(data, i)
        except Exception: break
        fn, wt = key >> 3, key & 7
        try:
            if wt == 0:
                v, i = read_varint(data, i)
                fields.setdefault(fn, []).append(("varint", v))
            elif wt == 1:
                v = int.from_bytes(data[i:i+8], "little"); i += 8
                fields.setdefault(fn, []).append(("u64", v))
            elif wt == 2:
                ln, i = read_varint(data, i)
                raw = data[i:i+ln]; i += ln
                s_ok = False
                try:
                    s = raw.decode("utf-8")
                    if s.isprintable():
                        fields.setdefault(fn, []).append(("string", s)); s_ok = True
                except UnicodeDecodeError: pass
                if not s_ok:
                    fields.setdefault(fn, []).append(("bytes", raw.hex()))
            elif wt == 5:
                v = int.from_bytes(data[i:i+4], "little"); i += 4
                fields.setdefault(fn, []).append(("u32", v))
            else: break
        except Exception: break
    return fields

def first_value(fields, field_num, want_kind=None):
    for kind, v in fields.get(field_num, []):
        if want_kind is None or kind == want_kind: return v
    return None

# ═══════════════════════════════════════════════════════════════════
# VERSION FETCH
# ═══════════════════════════════════════════════════════════════════
def get_play_store_version():
    headers = {"User-Agent": USER_AGENT_WEB, "Accept-Language": "en-US,en;q=0.9"}
    r = requests.get(PLAYSTORE_URL, headers=headers, timeout=15)
    versions = re.findall(r"\b(1\.\d{1,3}\.\d{1,3})\b", r.text)
    if not versions: raise RuntimeError("no version on Play Store page")
    real = [v for v in versions if v != "1.000.000"]
    return (real or versions)[-1]

def fetch_ver_config(initial_version):
    version = initial_version; last = None
    for attempt in range(1, VER_MAX_ATTEMPTS + 1):
        url = (
            f"{VER_URL_BASE}?version={version}"
            f"&lang={LANG_CODE}&device=android&channel=3rd_party&appstore=thirdparty"
            f"&region={REGION}&whitelist_version=1.7.0&whitelist_sp_version=1.0.0"
            f"&device_name=vivo%20V2538"
            f"&device_CPU=ARM64%20FP%20ASIMD%20AES"
            f"&device_GPU=Adreno%20%28TM%29%20722"
            f"&device_mem=7282"
        )
        try:
            r = requests.get(url, timeout=15); cfg = r.json()
        except Exception as e:
            last = e; time.sleep(1.0 * attempt); continue
        if cfg.get("code") == 0:
            cfg["region"] = REGION; cfg["lang"] = LANG_CODE
            cfg["country_code"] = REGION
            cfg["server_url"] = SERVER_URL; cfg["client_url"] = CLIENT_URL
            return cfg
        if cfg.get("remote_version"): version = cfg["remote_version"]
        last = cfg; time.sleep(1.0 * attempt)
    raise RuntimeError(f"ver.php failed: {last}")

# ═══════════════════════════════════════════════════════════════════
# ACCOUNT FETCHER
# ═══════════════════════════════════════════════════════════════════
def _distribute(total, n):
    base = total // n; rem = total % n
    return [base + (1 if i < rem else 0) for i in range(n)]

async def _call_gen_api(session, base_url, count, region):
    url = f"{base_url.rstrip('/')}/api/gen"
    payload = {"region": region, "count": count, "threads": 1, "name_prefix": BOT_NAME}
    try:
        async with session.post(url, json=payload,
                                timeout=aiohttp.ClientTimeout(total=_API_TIMEOUT)) as r:
            body = await r.text()
            if r.status != 200: return {"_ok": False, "error": f"HTTP {r.status}"}
            data = json.loads(body); data["_ok"] = bool(data.get("accounts")); return data
    except Exception as e: return {"_ok": False, "error": type(e).__name__}

async def _fetch_batch(total, region):
    dist = _distribute(total, len(API_URLS))
    async with aiohttp.ClientSession() as session:
        tasks = [_call_gen_api(session, API_URLS[i], cnt, region)
                 for i, cnt in enumerate(dist) if cnt > 0]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    accounts = []
    for res in results:
        if isinstance(res, Exception): continue
        if res.get("_ok"): accounts.extend(res.get("accounts") or [])
    return accounts

async def fetch_accounts_with_retry(total, region, max_retries=API_RETRY_ATTEMPTS):
    accounts = []
    for attempt in range(1, max_retries + 1):
        need = total - len(accounts)
        if need <= 0: break
        if attempt == 1: action(f"creating {total} account(s)…")
        else: action(f"retry {attempt}/{max_retries} · still need {need} account(s)…")
        batch = await _fetch_batch(need, region); got = len(batch)
        accounts.extend(batch)
        if got > 0: ok(f"received {got} account(s) · total {len(accounts)}/{total}")
        else: warn("no accounts from this attempt")
        if len(accounts) >= total: break
        await asyncio.sleep(3)
    return accounts[:total]

# ═══════════════════════════════════════════════════════════════════
# LOGIN PIPELINE
# ═══════════════════════════════════════════════════════════════════
def build_major_login(open_id, access_token, cfg, platform, region=None):
    remote_version = cfg["remote_version"]; country = cfg["country_code"]
    cdn_url = cfg["cdn_url"]; abhot_cdn = cfg["abhotupdate_cdn_url"]
    client_ip = cfg["client_ip"]; vercfg_sign = cfg["vercfg_sign"]
    cdn_hash = hashlib.md5(f"{open_id}{time.time_ns()}".encode()).hexdigest()
    cdn_blob = f"{cdn_url}|{abhot_cdn}|{cdn_hash}"
    sig_base64 = ("KqsHTwFsNrz71lqUGAjS+qIySSj2KOGy6RrHPlpy6KkAVaY7JOEtuPh7yc+7ruAa8IoJQdj5KVD"
                  "vnuda+C89owjNtP1VCdBI3Q591QXRXy8qF6s/")
    b  = b""
    b += f_str(3, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    b += f_str(4, "free fire"); b += f_vint(5, 1)
    b += f_str(7, remote_version)
    b += f_str(8, "Android OS 16 / API-36 (BP2A.250605.031.A3_V000L1/compiler260320183556)")
    b += f_str(9, "Handheld"); b += f_str(11, "CarrierDataNetwork")
    b += f_vint(12, 1637); b += f_vint(13, 750); b += f_str(14, "440")
    b += f_str(15, "ARM64 FP ASIMD AES | 5606 | 8"); b += f_vint(16, 7282)
    b += f_str(17, "Adreno (TM) 722")
    b += f_str(18, "OpenGL ES 3.2 V@0800.69.2 (GIT@4659378004, I7f7aee143c, 1773055375) (Date:03/09/26)")
    b += f_str(19, "Google|c15d0cbb-0f10-4ad4-a960-739ca3891a93")
    b += f_str(20, client_ip); b += f_str(21, LANG_CODE)
    b += f_str(22, open_id); b += f_str(23, str(platform))
    b += f_str(24, "Handheld"); b += f_str(25, "vivo V2538")
    if region is not None: b += f_str(26, region)
    b += f_str(29, access_token); b += f_vint(30, 1)
    b += f_str(42, "4G"); b += f_str(57, SESSION_HASH)
    b += f_vint(60, 223554); b += f_vint(61, 100654); b += f_vint(62, 4465)
    b += f_vint(64, 100782); b += f_vint(65, 223554); b += f_vint(66, 100782)
    b += f_vint(67, 223554); b += f_vint(70, 4); b += f_vint(73, 1)
    b += f_str(74, "/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/lib/arm64")
    b += f_vint(76, 1)
    b += f_str(77, "066a589fa3f5658377634fe7b1d88556|/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/base.apk")
    b += f_vint(78, 6); b += f_vint(79, 2); b += f_str(81, "64"); b += f_str(83, "2019121227")
    b += f_vint(85, 3); b += f_str(86, "OpenGLES2"); b += f_vint(87, 8191)
    b += f_vint(88, platform); b += f_vint(92, 40843)
    b += f_str(93, "3rd_party"); b += f_str(94, sig_base64)
    b += f_vint(95, 111207)
    b += f_str(96, '{"cur_rate":[60,90,120],"support_etc2":false}')
    b += f_vint(97, 1); b += f_vint(98, 1)
    b += f_str(99, str(platform)); b += f_str(100, str(platform))
    b += f_str(102, "42531243535e0e0531"); b += f_vint(104, 84750); b += f_vint(105, 1)
    b += f_str(106, cdn_blob); b += f_str(107, vercfg_sign)
    return b

def major_login(tag, open_id, access_token, cfg, platform, region=None):
    url = cfg["server_url"].rstrip("/") + "/MajorLogin"
    plain = build_major_login(open_id, access_token, cfg, platform, region=region)
    headers = {"User-Agent": USER_AGENT_UNITY, "Accept": "*/*",
               "Accept-Encoding": "deflate, gzip", "Authorization": "Bearer",
               "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
               "ReleaseVersion": cfg["latest_release_version"],
               "Content-Type": "application/x-www-form-urlencoded",
               "X-Unity-Version": "2018.4.12f1"}
    r = requests.post(url, data=enc_aes(plain), headers=headers, timeout=20)
    if r.status_code != 200: raise RuntimeError(f"MajorLogin HTTP {r.status_code}")
    attempts = [("plain", parse_proto(r.content))]
    if len(r.content) > 64: attempts.append(("plain[64:]", parse_proto(r.content[64:])))
    try: attempts.append(("dec", parse_proto(dec_aes(r.content))))
    except Exception: pass
    if len(r.content) > 64:
        try: attempts.append(("dec[64:]", parse_proto(dec_aes(r.content[64:]))))
        except Exception: pass
    fields = {}
    for _, f in attempts:
        if 8 in f or 22 in f: fields = f; break
    account_id = first_value(fields, 1, "varint")
    jwt = first_value(fields, 8, "string")
    game_url = first_value(fields, 10, "string")
    region_from_jwt = None
    payload = decode_jwt_payload(jwt) if jwt else {}
    if payload: region_from_jwt = payload.get("noti_region") or payload.get("lock_region")
    if (not jwt) or account_id is None or (isinstance(account_id, int) and account_id < 10_000_000):
        raise RuntimeError("MajorLogin implausible result")
    return {"account_id": account_id, "jwt": jwt, "game_url": game_url,
            "region": region_from_jwt or region, "fields": fields}

def choose_region(tag, jwt, cfg, region):
    url = cfg["server_url"].rstrip("/") + "/ChooseRegion"
    body = f_str(1, region)
    headers = {"User-Agent": USER_AGENT_UNITY, "Accept": "*/*",
               "Accept-Encoding": "deflate, gzip", "Authorization": f"Bearer {jwt}",
               "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
               "ReleaseVersion": cfg["latest_release_version"],
               "Content-Type": "application/x-www-form-urlencoded",
               "X-Unity-Version": "2018.4.12f1"}
    r = requests.post(url, data=enc_aes(body), headers=headers, timeout=20)
    if r.status_code != 200: raise RuntimeError(f"ChooseRegion HTTP {r.status_code}")
    fields = parse_proto(r.content)
    confirmed = first_value(fields, 1, "string")
    if not confirmed:
        for alt in (2, 3, 4):
            confirmed = first_value(fields, alt, "string")
            if confirmed: break
    if not confirmed: raise RuntimeError("ChooseRegion returned no region")
    return confirmed

def build_get_login_data(open_id, access_token, cfg, platform, jwt):
    remote_version = cfg["remote_version"]; country = cfg["country_code"]
    cdn_url = cfg["cdn_url"]; abhot_cdn = cfg["abhotupdate_cdn_url"]
    client_ip = cfg["client_ip"]; vercfg_sign = cfg["vercfg_sign"]
    cdn_hash = hashlib.md5(f"{open_id}{time.time_ns()}".encode()).hexdigest()
    cdn_blob = f"{cdn_url}|{abhot_cdn}|{cdn_hash}"
    sig_base64 = ("KqsHTwFsNrz71lqUGAjS+qIySSj2KOGy6RrHPlpy6KkAVaY7JOEtuPh7yc+7ruAa8IoJQdj5KVD"
                  "vnuda+C89owjNtP1VCdBI3Q591QXRXy8qF6s/")
    b  = b""
    b += f_str(3, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    b += f_str(4, "free fire"); b += f_vint(5, 1)
    b += f_str(7, remote_version)
    b += f_str(8, "Android OS 16 / API-36 (BP2A.250605.031.A3_V000L1/compiler260320183556)")
    b += f_str(9, "Handheld"); b += f_str(11, "CarrierDataNetwork")
    b += f_vint(12, 1637); b += f_vint(13, 750); b += f_str(14, "440")
    b += f_str(15, "ARM64 FP ASIMD AES | 5606 | 8"); b += f_vint(16, 7282)
    b += f_str(17, "Adreno (TM) 722")
    b += f_str(18, "OpenGL ES 3.2 V@0800.69.2 (GIT@4659378004, I7f7aee143c, 1773055375) (Date:03/09/26)")
    b += f_str(19, "Google|c15d0cbb-0f10-4ad4-a960-739ca3891a93")
    b += f_str(20, client_ip); b += f_str(21, LANG_CODE)
    b += f_str(22, open_id); b += f_str(23, str(platform))
    b += f_str(24, "Handheld"); b += f_str(25, "vivo V2538"); b += f_str(26, country)
    b += f_str(29, access_token); b += f_vint(30, 1)
    b += f_str(42, "4G"); b += f_str(57, SESSION_HASH)
    b += f_vint(60, 223554); b += f_vint(61, 100654); b += f_vint(62, 4465)
    b += f_vint(64, 100782); b += f_vint(65, 223554); b += f_vint(66, 100782)
    b += f_vint(67, 223554); b += f_vint(70, 4); b += f_vint(73, 1)
    b += f_str(74, "/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/lib/arm64")
    b += f_vint(76, 1)
    b += f_str(77, "066a589fa3f5658377634fe7b1d88556|/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/base.apk")
    b += f_vint(78, 6); b += f_vint(79, 2); b += f_str(81, "64"); b += f_str(83, "2019121227")
    b += f_vint(85, 3); b += f_str(86, "OpenGLES2"); b += f_vint(87, 8191)
    b += f_vint(88, platform); b += f_vint(92, 40843)
    b += f_str(93, "3rd_party"); b += f_str(94, sig_base64)
    b += f_vint(95, 111207)
    b += f_str(96, '{"cur_rate":[60,90,120],"support_etc2":false}')
    b += f_vint(97, 1); b += f_vint(98, 1)
    b += f_str(99, str(platform)); b += f_str(100, str(platform))
    b += f_str(102, "42531243535e0e0531"); b += f_vint(104, 84750); b += f_vint(105, 1)
    b += f_str(106, cdn_blob); b += f_str(107, vercfg_sign); b += f_str(108, jwt)
    return b

def _decode_session_blob(hex_str):
    try:
        raw = bytes.fromhex(hex_str); sub = parse_proto(raw)
        b64 = first_value(sub, 10, "string")
        if not b64: return {}
        padded = b64 + "=" * (-len(b64) % 4)
        return json.loads(base64.b64decode(padded))
    except Exception: return {}

def get_login_data(tag, open_id, access_token, cfg, platform, jwt):
    plain = build_get_login_data(open_id, access_token, cfg, platform, jwt)
    login_url = cfg["client_url"].rstrip("/") + "/GetLoginData"
    headers = {"User-Agent": USER_AGENT_UNITY, "Accept": "*/*",
               "Accept-Encoding": "deflate, gzip", "Authorization": f"Bearer {jwt}",
               "X-GA": "v1 1", "X-GA-SV": str(int(time.time())),
               "ReleaseVersion": cfg["latest_release_version"],
               "Content-Type": "application/x-www-form-urlencoded",
               "X-Unity-Version": "2018.4.12f1"}
    r = requests.post(login_url, data=enc_aes(plain), headers=headers, timeout=20)
    if r.status_code != 200: raise RuntimeError(f"GetLoginData HTTP {r.status_code}")
    fields = parse_proto(r.content)
    account_id  = first_value(fields, 1, "varint")
    region      = first_value(fields, 3, "string")
    nickname    = first_value(fields, 4, "string")
    game_server = first_value(fields, 14, "string")
    event_url   = first_value(fields, 16, "string")
    chat_server = first_value(fields, 32, "string")
    session = {}
    nested = first_value(fields, 63, "bytes")
    if nested: session = _decode_session_blob(nested)
    return {"account_id": account_id, "region": region, "nickname": nickname,
            "game_server": game_server, "chat_server": chat_server,
            "event_url": event_url, "session": session}

# ═══════════════════════════════════════════════════════════════════
# CLAN JOIN
# ═══════════════════════════════════════════════════════════════════
async def request_join_clan(base_url, jwt, clan_id, region):
    url = f"{base_url.rstrip('/')}/RequestJoinClan"
    body = f_vint(1, int(clan_id))
    payload = enc_aes(body)
    headers = {"User-Agent": USER_AGENT_UNITY, "Accept": "*/*",
               "Accept-Encoding": "deflate, gzip",
               "X-Ga-Sv": str(int(time.time())),
               "Authorization": f"Bearer {jwt}", "X-Ga": "v1 1",
               "ReleaseVersion": Ob_VeR,
               "Content-Type": "application/x-www-form-urlencoded",
               "X-Unity-Version": "2018.4.12f1",
               "Connection": "Keep-Alive", "X-Region": region}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    async with aiohttp.ClientSession() as s:
        async with s.post(url, data=payload, headers=headers, ssl=ctx, timeout=20) as r:
            return r.status, await r.read()

async def join_all_to_clan(accounts, clan_id):
    if not clan_id: return
    action(f"joining clan {clan_id}…")
    async def one(a):
        try:
            jwt = a.get("jwt"); base = a.get("game_url")
            if not jwt or not base: return
            status, _ = await request_join_clan(base, jwt, clan_id, REGION)
            if status == 200: ok(f"uid={a.get('uid')} joined clan")
        except Exception: pass
    await asyncio.gather(*[one(a) for a in accounts])

# ═══════════════════════════════════════════════════════════════════
# GLORY BOT ENGINE
# ═══════════════════════════════════════════════════════════════════
SETTLE_AFTER_ALL_JOIN = 1.5
SQUAD_PLAYERS = 4

async def t_enc_packet_hex(h, k, v):
    return AES.new(k, AES.MODE_CBC, v).encrypt(pad(bytes.fromhex(h), 16)).hex()
async def t_enc_vr(n):
    if n < 0: return b""
    out = []
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)
async def t_create_varint(f, val): return await t_enc_vr((f << 3) | 0) + await t_enc_vr(val)
async def t_create_length(f, val):
    ev = val.encode() if isinstance(val, str) else val
    return await t_enc_vr((f << 3) | 2) + await t_enc_vr(len(ev)) + ev
async def t_create_proto(fields):
    pkt = bytearray()
    for f, val in fields.items():
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict): pkt.extend(await t_create_length(f, await t_create_proto(item)))
                elif isinstance(item, int): pkt.extend(await t_create_varint(f, item))
                elif isinstance(item, (str, bytes)): pkt.extend(await t_create_length(f, item))
        elif isinstance(val, dict): pkt.extend(await t_create_length(f, await t_create_proto(val)))
        elif isinstance(val, int): pkt.extend(await t_create_varint(f, val))
        elif isinstance(val, (str, bytes)): pkt.extend(await t_create_length(f, val))
    return pkt
async def t_dec_hex(h):
    s = hex(h)[2:]
    return "0" + s if len(s) == 1 else s
async def t_fix_packet(parsed):
    out = {}
    for r in parsed:
        wt = r.wire_type
        if wt == "varint": val = r.data
        elif wt == "string": val = r.data
        elif wt == "bytes":
            v = r.data; val = v.hex() if isinstance(v, (bytes, bytearray)) else v
        elif wt == "length_delimited":
            try: val = await t_fix_packet(r.data.results)
            except Exception: val = str(r.data)
        else: val = r.data
        out[str(r.field)] = val
    return out
async def t_decode_packet(text):
    try: return await t_fix_packet(Parser().parse(text))
    except Exception: return None
async def t_generate_pk(pk_hex, n_prefix, k, v):
    enc = await t_enc_packet_hex(pk_hex, k, v)
    ln = await t_dec_hex(int(len(enc) // 2))
    pad = {2: "000000", 3: "00000", 4: "0000", 5: "000"}.get(len(ln), "")
    return bytes.fromhex(n_prefix + pad + ln + enc)

def _udp_log(msg):
    try:
        with open(UDP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception: pass

def _auth_region_byte(region):
    reg = str(region or "IND").upper()
    if reg == "IND": return 0x14
    if reg == "BD": return 0x19
    return 0x15

def build_auth_datagram(token, account_id):
    payload = token.encode("utf-8") if isinstance(token, str) else token
    p = 16 - (len(payload) % 16)
    data = AES.new(AUTH_AES_KEY, AES.MODE_CBC, AUTH_AES_IV).encrypt(payload + bytes([p]) * p)
    out = bytearray()
    out.append(AUTH_CMD & 0xFF); out.append(_auth_region_byte(REGION) & 0xFF)
    out += struct.pack(">Q", int(account_id) & 0xFFFFFFFFFFFFFFFF)
    out += struct.pack(">I", int(time.time()) & 0xFFFFFFFF)
    out += struct.pack(">i", len(data)); out += data
    return bytes(out)

PROTOCOL = {0:"NONE",1:"INIT",2:"HEARTBEAT",3:"MATCHMAKING",4:"STATS",5:"GROUP",6:"FRIEND",
            7:"MAIL",8:"INVENTORY",9:"BACKPACK",10:"ACTIVITY",11:"ACCOUNT",12:"CLAN",
            13:"PROFILE",14:"ROOM",15:"PRESENCE",16:"ELITEPASS",17:"RECONNECTION",
            18:"CHANNEL",19:"STORE",21:"PET",22:"MANUAL",23:"CHAMPIONSHIP",
            24:"ANTIADDICTION",25:"FRESH",26:"LINKAGE",27:"ATTENDANCE",28:"LIMITEDEVENT",
            29:"FFANTI",30:"CHAT",31:"CUP",32:"VIPCARD",34:"CREDITSCORE",
            35:"GAMESERVERMANAGER",36:"MINIGAME",37:"WORKSHOP",38:"CUSTOMEVENT",
            39:"ACHIEVEMENT",40:"GIN",41:"WEAPONPOWER",42:"CSRANKINGMATCH",
            43:"BRRANKINGMATCH",44:"OCCUPATION",45:"MODESTATS",46:"HIPPOINVENTORY",
            47:"PRIME",48:"TEAMTOPUP",49:"RELAYMART",50:"REMATCH",51:"GOOGLE_PLAY",
            52:"LBS",53:"SHAREDGACHA",54:"ESPORTS",55:"SOCIALHALL"}
GROUP_CMD = {0:"NONE",1:"CREATE",2:"INVITE",3:"INVITE_NTF",4:"ACCEPT",5:"REFUSE",
             6:"JOIN_NTF",7:"LEAVE",8:"LEAVE_NTF",9:"START",10:"START_NTF",11:"STOP",
             12:"STOP_NTF",13:"DISMISS_NTF",14:"GROUPINFO",15:"READY",16:"READY_NTF",
             17:"CHANGE",18:"CHANGE_NTF",19:"JOINROOM",20:"SPECTATEROOM",
             21:"SHOWEMOTE",22:"SHOWEMOTE_NTF",33:"JOIN",34:"JOINREQUEST_NTF",
             35:"KICKOUT",44:"ACCEPTJOIN_NTF",45:"START_ROOM_MATCHMAKING",
             46:"STOP_ROOM_MATCHMAKING",47:"START_ROOM_MATCHMAKING_NTF",
             48:"STOP_ROOM_MATCHMAKING_NTF",49:"CREATE_ROOM",55:"MIGRATE_GROUP",
             56:"MIGRATE_GROUP_NTF",57:"TRANSFER_LEADER",58:"TRANSFER_LEADER_NTF",
             102:"GROUP_NOTIFY_102"}
MATCHMAKING_CMD = {0:"NONE",1:"START",2:"CANCEL",3:"GROUPSTART",4:"GROUPCANCEL",
                   5:"MATCHMAKINGSUSS_NTF",6:"DROPMATCH",7:"GAMEOPENINGINFO",
                   8:"CHECKINGAMEPLAYER",9:"CLEARINGAMEPLAYER",10:"ANTIADDICTION_NTF",
                   11:"START_NTF",14:"STOP_NTF",15:"RANKING_BANNED",
                   16:"TEAMMATE_RANKING_BANNED",17:"CDT_HACKER_NTF",
                   18:"GETMATCHMAKINGINFO",19:"PUNISHINGAMEPLAYER",23:"SPECTATE"}
RECONNECTION_CMD = {0:"NONE",1:"RECONNECT",2:"TIMEOUT",3:"MATCHMAKINGSUSS_NTF",
                    4:"CANCEL",5:"GROUPINFO",6:"LEAVEMATCH_NTF"}
STATS_CMD = {0:"NONE",1:"MATCHSTATS_NTF",2:"UPDATEMMR_NTF"}
CMD_TABLES = {3:MATCHMAKING_CMD,4:STATS_CMD,5:GROUP_CMD,17:RECONNECTION_CMD}
UDP_CMD = {1:"UDP_HELLO",2:"UDP_ACK",3:"UDP_PING",4:"UDP_BYEBYE",5:"UDP_LONGTIMENOSEE",
           6:"MUDP_CONNECT_ACK",100:"RUDP_JOIN_MATCH",101:"RUDP_PLAYER_JOIN",
           102:"RUDP_PLAYER_QUIT",103:"RUDP_MATCH_END",107:"RUDP_DEAD",
           110:"RUDP_BATTLE_START",116:"RUDP_SYNC_SCENE_INFO",117:"RUDP_SAFE_ZONE",
           130:"RUDP_JOIN_MATCH_FINISHED",551:"RUDP_QUICK_CHAT",
           1901:"RUDP_GRI_SYNC",2000:"RUDP_SERVER_TIME",
           2001:"RUDP_MY_STATE",2012:"RUDP_OTHER_STATES",
           447:"RUDP_JOIN_MATCH_PREPARE",448:"RUDP_JOIN_MATCH_POST"}
LEAVE_REASONS = {0:"NORMAL",1:"OFFLINE",2:"DROPMATCH",3:"ALLJOINROOM",
                 4:"SOLOJOINROOM",5:"KICKOUT",6:"MERGEGROUP",7:"TIMEOUT"}

def describe(ptype, cmd):
    p = PROTOCOL.get(ptype, f"UNKNOWN_{ptype}")
    if isinstance(cmd, int): return f"{p}/{CMD_TABLES.get(ptype, {}).get(cmd, f'CMD_{cmd}')}"
    return p

def _br_rbyte(region):
    r = str(region or "BD").upper()
    return 0x19 if r == "BD" else (0x14 if r == "IND" else 0x15)

class _F64:
    __slots__ = ("v",)
    def __init__(self, v): self.v = v & 0xFFFFFFFFFFFFFFFF
def _vi(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: out.append(b | 0x80)
        else: out.append(b); break
    return bytes(out)
def _one(field, v):
    if isinstance(v, dict):
        body = _pb(v); return _vi((field << 3) | 2) + _vi(len(body)) + body
    if isinstance(v, _F64): return _vi((field << 3) | 1) + v.v.to_bytes(8, "little")
    if isinstance(v, int): return _vi(field << 3) + _vi(v)
    if isinstance(v, (str, bytes)):
        b = v.encode() if isinstance(v, str) else v
        return _vi((field << 3) | 2) + _vi(len(b)) + b
    raise TypeError(type(v))
def _pb(fields):
    out = bytearray()
    for f, v in fields.items():
        if isinstance(v, list):
            for it in v: out += _one(f, it)
        else: out += _one(f, v)
    return bytes(out)
def _br_frame(ptype, region, proto, key, iv):
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(proto, 16))
    return bytes([ptype, _br_rbyte(region)]) + len(enc).to_bytes(4, "big") + enc
def _br_idc(reg, pings=(75, 123)):
    return [{1:"IDC1",2:pings[0],3:reg},{1:"IDC2",2:pings[1],3:reg}]

_C_S1 = "0200044B122D3B02010000000000000000000000000000E3172CED00"
_C_14_1 = b"\x32" + bytes([len(_C_S1)]) + _C_S1.encode() + b"\x30\x30" * 3
_C_14_3 = bytes.fromhex(
    "7e585c521207074f5d030c5c545104570455070f0a555a085201095701025b560601545606010f07100802487d5c4043481e07"
    "1f081a1709034c0757787500566b45627e7a6548407565577a700e7708627a047e7e041005447b5d655070547e437c607f7656"
    "5675704e5877525b5a5b515662410a105f5c5a4c1e637f1c7147430b4f6c557778605b67416b50635850500056575e005a7606"
    "057005067e0c15060045455e56447a665a6672694b5046524b057b79427c715560577b575f0a120e4b470e631b536262186b0f"
    "73406359475343795c481d7918564b47790c13054d1d714b5d75451740515f7e586d414e40595a03000e654e0741507a091b08"
    "4c6668777b1c4c676517505d6e7a4c4e7d7c791f5269057f42440207041005004d7e5c5977037d4a631f560255026b7a647e6b"
    "0007015503746353500e1a0048701a0153626506774f18065e0558610457421856007313771b60010b140745554d7f50477d68"
    "770662600646696876026242541c4a49037f74750a1204074f487402135059457f517b415266604a434506064e79004c5a7b4f"
    "700d14044a58454a5a7c5e5f5b764354425e1267735041537d6041180a6d694305")
_C_14_7 = bytes.fromhex("1d02474b420204030506171d677c716374687d5f557051565753")
_C_14_11 = b"\x03" + (
    "bbSQ69i8H3F5AdV2KyoVlWj2cgPtsEL3Pi8QcWkc/NJiGxtxXsmeZDDwFPKPbvd56sULGeaD3qha9S6hKIkIb3oXVAAFErlI76uU2p2AqNdJyaucxz1ba5ecHPCBohQR6E5Y1UzpsgpxutURpI8pbqY0tCpeL1bOT+F5UaysgFmTeoIalHxxEYPQx7OVJHElCV5el0vpIs98JSA3nB8FWin6ckz5Fd0sG4n2g0B7OUOvcreqilCT737xI24wPxLdidSr1AJ2MK0/m3ugV1iqzPXhttKyvfmMNVY8DoXBBUcYt3vpK7mgbnietrOqJIbJC3O4ygX6IWl/hkp+ngsjfeOZSornpzFnxM/kkqZgZjVOweXe61FRU6JsGSeTeY63kqA/mbCPfdwodSYJE2hXfVJofxRG1644gFPYRkCPUjJazd2l9WAh9kd86kYbjphbxwz55ciWvZ3sDJR11W96ezyxJPhJPD8FQoQVmno6BP4e7QI1xe+h35bkS1epZq6K6xUP5YtHFvqbhARMNQKUYYzXQWRFMNL1JgAeMJNO0+eCPL57+RXzRKtlgM/rVsIWhNw8Oo9SdP+7wsGrMK+HIOJaF1apAXNRQ9mCqxI="
).encode()

def br_create_squad_pkt(region, cv, key, iv):
    reg = str(region or "IND").upper()
    f = {1:1, 2:{
        2: b"\x01", 3:15, 4:SQUAD_PLAYERS - 1, 5:"en",
        8: _br_idc(reg), 9: 1, 10: bytes.fromhex("01090a0b12191a202729"),
        11: 1, 13: 1,
        14: {1:_C_14_1, 2:40, 3:_C_14_3, 4:"w\\Z]", 6:12, 7:_C_14_7,
             8: cv or "1.132.9", 9:6, 10:2, 11:_C_14_11},
        19: 329, 21: bytes.fromhex("374f521955"),
        24: [{1:3,2:360},{1:4,2:391},{1:5,2:156},{1:29,2:204},
             {1:22,2:118},{1:14,2:139},{1:21}],
        30: ("https://dl-ind-production.freefiremobile.com/"
             "2832022628717E276054_7104117490_107_1767713981_0")}}
    return _br_frame(0x05, reg, _pb(f), key, iv)

def br_join_team_pkt(code, region, cv, key, iv):
    reg = str(region or "IND").upper()
    field9 = {1:_C_14_1, 2:40, 3:_C_14_3, 4:"w\\Z]", 6:12, 7:_C_14_7,
              8: cv or "1.132.9", 9:6, 10:2, 11:_C_14_11}
    f = {1:4, 2:{
        4: bytes.fromhex("01090a0b121619201d2729"),
        5: str(code), 6:6, 8:1, 9: field9,
        11: _br_idc(reg, (99, 136)), 13:"en", 16: bytes.fromhex("374f521955"),
        20: [{1:3,2:360},{1:4,2:391},{1:5,2:156},{1:29,2:204},
             {1:22,2:118},{1:14,2:139},{1:21}],
        27: {1:2, 2:4}}}
    return _br_frame(0x05, reg, _pb(f), key, iv)

def br_start_squad_pkt(uid, region, key, iv):
    reg = str(region or "IND").upper()
    return _br_frame(0x05, reg, _pb({1:9, 2:{1:int(uid), 7:_br_idc(reg)}}), key, iv)

async def send_op31(group_id, region, key, iv):
    fields = {1:31, 2:{1:int(group_id)}}
    pkt = f"05{_auth_region_byte(region):02x}"
    proto_hex = (await t_create_proto(fields)).hex()
    return await t_generate_pk(proto_hex, pkt, key, iv)

async def build_auth_packet(account_id, token, server_time, key, iv, region=REGION, typ="OnLine"):
    uid_hex = f"{int(account_id):016x}"; ts_hex = f"{int(server_time):08x}"
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(token.encode(), 16)).hex()
    enc_len = f"{len(enc) // 2:08x}"
    reg = str(region).upper()
    if reg == "BD": pre_on, pre_chat = "7119", "9219"
    elif reg == "IND": pre_on, pre_chat = "7114", "9214"
    else: pre_on, pre_chat = "7115", "9215"
    if typ == "OnLine":
        return bytes.fromhex(pre_on + uid_hex + ts_hex + "00000000" + enc_len + enc)
    return bytes.fromhex(pre_chat + uid_hex + ts_hex + enc_len + enc)

async def send_keep_alive(region=REGION):
    reg = str(region).upper()
    return bytes.fromhex("0214" if reg == "IND" else ("0219" if reg == "BD" else "0215"))

CRC7_TABLE = bytes([
    0,9,18,27,36,45,54,63,72,65,90,83,108,101,126,119,25,16,11,2,61,52,47,38,
    81,88,67,74,117,124,103,110,50,59,32,41,22,31,4,13,122,115,104,97,94,87,
    76,69,43,34,57,48,15,6,29,20,99,106,113,120,71,78,85,92,100,109,118,127,
    64,73,82,91,44,37,62,55,8,1,26,19,125,116,111,102,89,80,75,66,53,60,39,
    46,17,24,3,10,86,95,68,77,114,123,96,105,30,23,12,5,58,51,40,33,79,70,
    93,84,107,98,121,112,7,14,21,28,35,42,49,56,65,72,83,90,101,108,119,126,
    9,0,27,18,45,36,63,54,88,81,74,67,124,117,110,103,16,25,2,11,52,61,38,
    47,115,122,97,104,87,94,69,76,59,50,41,32,31,22,13,4,106,99,120,113,78,
    71,92,85,34,43,48,57,6,15,20,29,37,44,55,62,1,8,19,26,109,100,127,118,73,
    64,91,82,60,53,46,39,24,17,10,3,116,125,102,111,80,89,66,75,23,30,5,12,
    51,58,33,40,95,86,77,68,123,114,105,96,14,7,28,21,42,35,56,49,70,79,84,
    93,98,107,112,121])

_DELTA = 0x9E3779B9; _ROUNDS = 16
_FIELD_SIZES = {0:1,1:2,2:2,3:1,4:2}
_FIELD_NAMES = {0:"sendOption",1:"cmd",2:"orderId",3:"flags",4:"length"}

def optimize_udp_socket(sock):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)
    except Exception: pass

async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf: c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + ((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF
                    ^ ((v1 + s) & 0xFFFFFFFF)
                    ^ (((v1 >> 5) + k1) & 0xFFFFFFFF))) & 0xFFFFFFFF
        v1 = (v1 + ((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF
                    ^ ((v0 + s) & 0xFFFFFFFF)
                    ^ (((v0 >> 5) + k3) & 0xFFFFFFFF))) & 0xFFFFFFFF
    return v0, v1

async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - ((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF
                    ^ ((v0 + s) & 0xFFFFFFFF)
                    ^ (((v0 >> 5) + k3) & 0xFFFFFFFF))) & 0xFFFFFFFF
        v0 = (v0 - ((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF
                    ^ ((v1 + s) & 0xFFFFFFFF)
                    ^ (((v1 >> 5) + k1) & 0xFFFFFFFF))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

async def tea_cbc_encrypt(padded, kb):
    k0,k1,k2,k3 = (struct.unpack_from("<I", kb, o)[0] for o in (0,4,8,12))
    out = bytearray(len(padded)); pc = bytearray(8); pi = bytearray(8)
    for i in range(0, len(padded), 8):
        x = bytearray(8)
        for j in range(8): x[j] = padded[i+j] ^ pc[j]
        e0, e1 = await tea_enc(struct.unpack_from("<I", x, 0)[0],
                               struct.unpack_from("<I", x, 4)[0], k0,k1,k2,k3)
        en = bytearray(8)
        struct.pack_into("<I", en, 0, e0); struct.pack_into("<I", en, 4, e1)
        for j in range(8): out[i+j] = en[j] ^ pi[j]
        pc[:] = out[i:i+8]; pi[:] = x
        if i % 64 == 0: await asyncio.sleep(0)
    return bytes(out)

async def tea_cbc_decrypt(body, kb):
    k0,k1,k2,k3 = (struct.unpack_from("<I", kb, o)[0] for o in (0,4,8,12))
    out = bytearray(len(body)); pi = bytearray(8); pc = bytearray(8)
    x = bytearray(8); d = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8): x[j] = body[i+j] ^ pi[j]
        d0, d1 = await tea_dec(struct.unpack_from("<I", x, 0)[0],
                               struct.unpack_from("<I", x, 4)[0], k0,k1,k2,k3)
        struct.pack_into("<I", d, 0, d0); struct.pack_into("<I", d, 4, d1)
        for j in range(8): out[i+j] = d[j] ^ pc[j]
        pc[:] = body[i:i+8]; pi[:] = d
        if i % 64 == 0: await asyncio.sleep(0)
    return bytes(out)

async def build_padded(content):
    pl = (8 - (len(content) + 10) % 8) % 8
    return bytes([pl, 0, 0]) + b"\x00" * pl + content + b"\x00" * 7

async def oicq_unpad(padded):
    if not padded or len(padded) < 8: return None
    if not all(padded[-1-i] == 0 for i in range(7)): return None
    pl = padded[0] & 0x07
    s = 3 + pl; e = len(padded) - 7
    return padded[s:e] if s < e else b""

async def encode_header(layout, so, cmd, oid, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        value = {0:so,1:cmd,2:oid,3:flags,4:length}[code]
        if _FIELD_SIZES[code] == 1: out.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF); out.append((v >> 8) & 0xFF)
    return bytes(out)

async def layouts_from_mask(mask):
    s = str(mask).strip()
    try: ru = [int(c) for c in s]
    except ValueError: ru = [0,1,2,3,4]
    if sorted(ru) != [0,1,2,3,4]: ru = [0,1,2,3,4]
    return ru, [c for c in ru if c != 2]

async def build_packet(msg_key, layout, so, cmd, oid, flags, content, key, encrypted=True):
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        value = {0:so,1:cmd,2:oid,3:flags,4:len(body)}[code]
        if _FIELD_SIZES[code] == 1: hdr.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF); hdr.append((v >> 8) & 0xFF)
    pkt = bytearray(hdr + body)
    pkt[1] = await crc7_buff(0, bytes(pkt[2:])) & 0x7F
    return bytes(pkt)

async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")[:25]
    content = len(data).to_bytes(4, "little") + data + b"\x00" * 9
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    layout = [int(c) for c in str(layout).strip()]
    eb = await tea_cbc_encrypt(await build_padded(content), key)
    hdr = await encode_header(layout, 1, 1, 0, 1, len(eb), k, v80)
    pkt = bytearray([0x63, 0x00]) + hdr + eb
    pkt[1] = await crc7_buff(0, bytes(pkt[2:])) & 0x7F
    return bytes(pkt).hex()

HDR_RELIABLE = 10
UDP_HEAD_AND_ENCRY_SIZE = 40
MTU_LIMIT = 1300
_SALT_LEN, _ZERO_LEN = 2, 7

def _tea_encrypt_len(n):
    t = 1 + _SALT_LEN + n + _ZERO_LEN; r = t % 8
    return t + (8 - r if r else 0)
def _dg_size(tl, reliable=True):
    zv = bytearray(); _put_zigvarint(zv, tl)
    body = len(zv) + tl
    return (HDR_RELIABLE if reliable else 8) + _tea_encrypt_len(body)
def split_token_bytes(tb):
    n = len(tb); raw = int(n * 0.85); p1 = raw - (raw % 40)
    while UDP_HEAD_AND_ENCRY_SIZE + _dg_size(p1) > MTU_LIMIT and p1 > 40: p1 -= 40
    return tb[:p1], tb[p1:]

def _put_varint(out, v):
    v = int(v)
    while v >= 0x80:
        out.append((v & 0x7F) | 0x80); v >>= 7
    out.append(v & 0x7F)
def _put_zigvarint(out, v):
    z = (int(v) << 1) ^ (int(v) >> 63)
    _put_varint(out, z & 0xFFFFFFFFFFFFFFFF)
def _put_float_bits(out, f):
    bits = struct.unpack("<I", struct.pack("<f", float(f)))[0]
    _put_varint(out, bits)
def _put_string(out, s):
    raw = s.encode("utf-8") if isinstance(s, str) else s
    _put_zigvarint(out, len(raw)); out += raw
def _rd_varint(b, p):
    v = i = 0
    while True:
        c = b[p + i]; v |= (c & 0x7F) << (7 * i); i += 1
        if not c & 0x80: return v, p + i
def _zag(v): return (v >> 1) ^ -(v & 1)

def build_join_info_head(account_id, game_mode=15, match_mode=1, map_id=1,
                         country="IN", client_version="1.132.9",
                         client_version_code="2019121229",
                         client_url=("csoversea.stronghold.freefiremobile.com;"
                                     "0.0.0.0;34.126.76.45;34.87.177.14;"
                                     "34.87.170.230;35.185.183.57"),
                         room_id=0, match_id=0,
                         drift_bottle_owner_id=0, drift_bottle_owner_name="",
                         enable_antihack_tick=1, friend_count=0,
                         client_ip="", client_fingerprint="",
                         session_tag=0, is_emulator=1):
    room = int(match_id or room_id)
    b = bytearray()
    _put_varint(b, int(account_id)); _put_varint(b, room)
    b.append(1); b.append(int(game_mode) & 0xFF); _put_varint(b, room)
    b.append(int(map_id) & 0xFF); b.append(0)
    _put_varint(b, 0); _put_varint(b, 0); b.append(0); b.append(int(is_emulator) & 0xFF)
    b.append(0); b.append(1); b.append(2); b.append(3)
    b.append(int(enable_antihack_tick) & 0xFF); b.append(1)
    _put_string(b, country); _put_varint(b, 0)
    b.append(1); b.append(2); b.append(0); b.append(1); b.append(0); b.append(0); b.append(4)
    _put_string(b, client_version); _put_string(b, client_version_code); _put_string(b, client_url)
    b.append(0); b.append(0)
    _put_varint(b, int(friend_count)); b.append(0)
    _put_varint(b, int(drift_bottle_owner_id)); _put_string(b, drift_bottle_owner_name or "")
    b.append(1); _put_string(b, ""); _put_string(b, ""); b.append(0)
    _put_varint(b, 0); _put_varint(b, 0); b.append(0); b.append(0); b.append(0)
    _put_varint(b, 0); _put_string(b, ""); _put_varint(b, 0)
    b.append(0); b.append(1); b.append(0); b.append(0)
    _put_varint(b, 0); _put_varint(b, 0); b.append(0); b.append(1)
    _put_string(b, ""); _put_varint(b, 0); b.append(0); b.append(0); b.append(0)
    b.append(int(match_mode) & 0xFF); b.append(0)
    _put_varint(b, int(session_tag)); b.append(2); b.append(0)
    _put_string(b, client_ip or ""); _put_string(b, client_fingerprint or "")
    return bytes(b)

def build_join_post_body(account_id, token_part2, **kw):
    body = bytearray(); body += build_join_info_head(account_id, **kw)
    _put_string(body, token_part2); return bytes(body)

async def build_join_match_startup(jt, uk, mc, aid, bv, server_ip="", region="BD",
                                   cv="1.132.9", cvc="2019121229",
                                   at="", mid=0, cc="IN", map_id=1, gm=15, mm=1):
    jt = jt.strip(); ukb = bytes.fromhex(uk)
    mc = [int(c) for c in str(mc).strip()]
    et = jt.encode("utf-8") if isinstance(jt, str) else jt
    p1, p2 = split_token_bytes(et)
    pb = bytearray(); _put_string(pb, p1)
    prep = (await build_packet(0x5E, mc, 2, 447, 0, 1, bytes(pb), ukb)).hex()
    post_body = build_join_post_body(
        aid, p2, game_mode=gm, match_mode=mm, map_id=map_id,
        country=cc, client_version=cv, client_version_code=cvc,
        match_id=int(mid or bv),
        client_ip=server_ip.split(":")[0] if server_ip else "")
    post = await build_packet(0x5A, mc, 2, 448, 1, 1, post_body, ukb)
    return [prep], post.hex()

async def decode_packet(packet, key, mask=None):
    import itertools
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8: return None
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == await crc7_buff(0, data[2:])
    if mask:
        ru, nr = await layouts_from_mask(mask)
        layouts = [("RUDP", ru), ("nonRUDP", nr)]
    else:
        layouts = [("RUDP", list(p)) for p in itertools.permutations([0,1,2,3,4])]
        layouts += [("nonRUDP", list(p)) for p in itertools.permutations([0,1,3,4])]
    cands = []
    for kind, layout in layouts:
        off = 2; f = {}; ok = True
        for code in layout:
            size = _FIELD_SIZES[code]
            if off + size > len(data): ok = False; break
            f[_FIELD_NAMES[code]] = (data[off] ^ k) if size == 1 else \
                ((data[off] | (data[off+1] << 8)) ^ v80) & 0xFFFF
            off += size
        if not ok: continue
        if f["flags"] > 7 or f["sendOption"] > 7: continue
        if f["length"] != len(data) - off: continue
        body = data[off:off+f["length"]]
        content = None
        if f["flags"] & 1:
            if len(body) < 8 or len(body) % 8 != 0: continue
            content = await oicq_unpad(await tea_cbc_decrypt(body, key))
            if content is None: continue
        else: content = body
        score = (1 if crc_ok else 0) + (1 if content is not None else 0)
        cands.append({"kind":kind,"layout":layout,"headerLen":off,"msgKey":data[0],
                      "cmd":f["cmd"],"flags":f["flags"],"sendOrder":f["sendOption"],
                      "orderId":f.get("orderId"),"length":f["length"],
                      "content":content,"crcOk":crc_ok,"score":score})
    if not cands: return None
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands[0]

SEND_HZ = 10.0
MOVE_INTERVAL = 1.0 / SEND_HZ
WALK_SPEED = 5150.0
STEP_PER_TICK = WALK_SPEED / SEND_HZ
ZONE_RADIUS_SCALE = 1000.0

CMD_PLAYER_JOIN = 101; CMD_MATCH_END = 103; CMD_DEAD = 107
CMD_SAFE_ZONE = 117; CMD_SERVER_TIME = 2000; CMD_MY_STATE = 2001
CMD_OTHER_STATES = 2012; CMD_QUICK_CHAT = 551; CMD_GRI_SYNC = 1901

PHASE_PREPARE = 1; PHASE_FIGHT = 3; PHASE_ROUND_END = 5
POSE_STANDING = 0; POSE_DASHING = 2
QUICK_CHAT_FOLLOW = 1; QUICK_CHAT_HELP = 2

def build_player_state_upload(pid, pos, rot, tdir, vel, aim, st,
                              ps=0, pp=0, plat=0, lg=0, ping=0,
                              jump=0, slide=0, custom=0):
    o = bytearray()
    _put_varint(o, int(pid))
    _put_zigvarint(o, pos[0]); _put_zigvarint(o, pos[1]); _put_zigvarint(o, pos[2])
    _put_zigvarint(o, rot[0]); _put_zigvarint(o, rot[1]); _put_zigvarint(o, rot[2])
    _put_zigvarint(o, tdir[0]); _put_zigvarint(o, tdir[1])
    _put_zigvarint(o, vel[0]); _put_zigvarint(o, vel[1]); _put_zigvarint(o, vel[2])
    o.append(ps & 0xFF); o.append(pp & 0xFF)
    _put_float_bits(o, aim[0]); _put_float_bits(o, aim[1]); _put_float_bits(o, aim[2])
    _put_varint(o, plat); o.append(1 if lg else 0)
    _put_varint(o, ping); o.append(jump & 0xFF)
    _put_varint(o, slide); o.append(custom & 0xFF)
    _put_varint(o, st & 0xFFFFFFFF)
    return bytes(o)

def parse_player_join(body):
    if body is None or len(body) < 4: return None
    try:
        p = 0
        uid, p = _rd_varint(body, p); _s, p = _rd_varint(body, p)
        pid, p = _rd_varint(body, p); rl, p = _rd_varint(body, p)
        n = _zag(rl)
        name = body[p:p+n].decode("utf-8", "replace")
    except (IndexError, ValueError): return None
    return uid, pid, name

def decode_my_state(body):
    if body is None or len(body) < 6: return None
    try:
        p = 0
        _mt, p = _rd_varint(body, p); _c, p = _rd_varint(body, p); p += 1
        x, p = _rd_varint(body, p); y, p = _rd_varint(body, p); z, p = _rd_varint(body, p)
    except (IndexError, ValueError): return None
    return (_zag(x), _zag(y), _zag(z))

def decode_players_v2(body):
    players = {}
    if body is None or len(body) < 4: return players
    p = 2
    while p < len(body) - 1:
        try:
            sid = body[p]; p += 1
            x, p = _rd_varint(body, p); y, p = _rd_varint(body, p); z, p = _rd_varint(body, p)
            vx, p = _rd_varint(body, p); vy, p = _rd_varint(body, p); vz, p = _rd_varint(body, p)
            yr = body[p]; p += 1
            ay = body[p]; p += 1
            axz = body[p]; p += 1
            ps = body[p]; p += 1
            pp = body[p]; p += 1
            _pl, p = _rd_varint(body, p)
            _c = body[p]; p += 1
        except (IndexError, ValueError): break
        pos = (_zag(x), _zag(y), _zag(z))
        if not (1 <= sid <= 64): break
        if any(abs(v) > 4000000 for v in pos): break
        players[sid] = {"pos": pos, "vel": (_zag(vx), _zag(vy), _zag(vz)),
                        "yrot": yr, "aim_y": ay, "aim_xz": axz,
                        "physx_state": ps, "physx_pose": pp}
    return players

def decode_server_time(body):
    if not body: return None
    try:
        tick, p = _rd_varint(body, 0)
        phase = body[p] if p < len(body) else 0
    except (IndexError, ValueError): return None
    return tick, phase

def _read_vec2pos(b, p):
    x, p = _rd_varint(b, p); z, p = _rd_varint(b, p)
    return (_zag(x), _zag(z)), p

def decode_safezone(body):
    if not body: return None
    try:
        p = 0
        stage = body[p]; p += 1
        oc, p = _read_vec2pos(body, p); orad, p = _rd_varint(body, p)
        ic, p = _read_vec2pos(body, p); irad, p = _rd_varint(body, p)
        _t, p = (body[p] if p < len(body) else 0), p + 1
        st, p = _rd_varint(body, p); et, p = _rd_varint(body, p)
    except (IndexError, ValueError): return None
    return {"stage": stage, "outer_center": oc, "outer_radius": orad,
            "inner_center": ic, "inner_radius": irad, "start": st, "end": et}

def parse_gri_block(body):
    if body is None or len(body) < 2: return {}
    try: bl = struct.unpack_from("<H", body, 0)[0]
    except struct.error: return {}
    p = 2; end = min(2 + bl, len(body)); fields = {}
    while p < end:
        fid = body[p]; p += 1
        if p >= end: break
        try: v, p = _rd_varint(body, p)
        except (IndexError, ValueError): break
        fields[fid] = v
    return fields

def get_match_phase(body):
    fields = parse_gri_block(body)
    if 3 not in fields: return None
    v = fields[3]
    if v < 0x10000: return None
    return (v >> 16) & 0xFFFF, fields.get(2), (v >> 32) & 0xFFFFFFFF, v & 0xFFFF

def decode_quick_chat(body):
    if body is None or len(body) < 3: return None
    try:
        p = 0
        cid, p = _rd_varint(body, p)
        _i, p = _rd_varint(body, p)
        s, p = _rd_varint(body, p)
    except (IndexError, ValueError): return None
    return cid, s & 0xFF, s

GLORY_FIELD = None
_REWARD_SKIP = {"1", "2", "3"}

def extract_reward_ints(decoded):
    out = {}
    def walk(d, pre):
        if isinstance(d, dict):
            for k, v in d.items(): walk(v, f"{pre}.{k}" if pre else str(k))
        elif isinstance(d, list):
            for i, x in enumerate(d): walk(x, f"{pre}[{i}]")
        elif isinstance(d, int) and d > 0:
            out[pre] = d
    walk(decoded, ""); return out

def report_rewards(run, squad_n, source, decoded, accum):
    if not isinstance(decoded, dict): return accum
    flat = extract_reward_ints(decoded)
    top = {}
    for k, v in flat.items():
        head = k.split(".")[0].split("[")[0]
        if head in _REWARD_SKIP or v <= 0: continue
        top[k] = v
    if not top: return accum
    if GLORY_FIELD is not None:
        v = flat.get(str(GLORY_FIELD))
        if isinstance(v, int) and v > 0:
            accum["glory"] = accum.get("glory", 0) + v
            with _jobs_lock:
                run["rewards"]["glory"] = run["rewards"].get("glory", 0) + v
                run["glory"] = run.get("glory", 0) + v
            squad_ok(squad_n, f"+{v} glory  (squad total: {accum['glory']})")
    cands = {k: v for k, v in top.items() if v < 10_000_000}
    if not cands: return accum
    items = sorted(cands.items(), key=lambda kv: -kv[1])[:3]
    for k, v in items:
        accum[k] = accum.get(k, 0) + v
        squad_line(squad_n, f"+{v} reward[{k}]  (running: {accum[k]})",
                   color=GN, prefix="★", level="reward")
    return accum

class MovementState:
    def __init__(self, aid):
        self.account_id = int(aid)
        self.my_id = None; self.my_short = None; self.my_pos = None; self.server_pos = None
        self.target_short = None; self.target_pos = None; self.target_seen = None
        self.target_vel = (0.0, 0.0); self.target_pose = 0; self.target_state = 0
        self.target_yrot = 0; self.target_aim_y = 0; self.target_aim_xz = 0
        self.zone_center = None; self.zone_radius = 0.0
        self.phase = None; self.round_no = None
        self.server_tick = None; self.tick_local = None; self.tick_rate = 30.0
        self.alive = True; self.downed = {}; self.roster = {}
        self.joined_at = None; self.blocked = 0
        self.yaw = 0.0; self.orbit_angle = 0.0
    def teammates(self):
        if self.my_id is None: return set()
        team = (self.my_id >> 24) & 0xFF
        return {s for s, (fid, _) in self.roster.items()
                if (fid >> 24) & 0xFF == team and s != self.my_short}
    def set_identity(self, fid):
        self.my_id = int(fid); self.my_short = self.my_id & 0xFF
        if self.joined_at is None: self.joined_at = time.time()
    def add_player(self, fid, name):
        self.roster[int(fid) & 0xFF] = (int(fid), name)
    def seed_my_pos(self, pos):
        self.server_pos = pos
        if self.my_pos is None: self.my_pos = pos; self.blocked = 0; return
        dx = pos[0] - self.my_pos[0]; dz = pos[2] - self.my_pos[2]
        gap = math.sqrt(dx*dx + dz*dz)
        if gap > 120000.0: self.my_pos = pos; self.blocked = 0
        elif gap > 1500.0:
            self.blocked += 1
            if self.blocked >= 5: self.my_pos = pos; self.blocked = 0
        else: self.blocked = 0
    def update_target(self, info, now):
        prev_pos, prev_seen = self.target_pos, self.target_seen
        self.target_pos = info["pos"]; self.target_seen = now
        if prev_pos is not None and prev_seen is not None:
            dt = now - prev_seen
            if 0.01 < dt < 2.0:
                vx = (info["pos"][0] - prev_pos[0]) / dt
                vz = (info["pos"][2] - prev_pos[2]) / dt
                if abs(vx) < 30000 and abs(vz) < 30000: self.target_vel = (vx, vz)
        self.target_yrot = info.get("yrot", self.target_yrot)
        self.target_pose = info.get("physx_pose", self.target_pose)
    def sync_clock(self, tick, now):
        if self.server_tick is not None and self.tick_local is not None:
            dt = now - self.tick_local; dtick = tick - self.server_tick
            if dt > 0.5 and 0 < dtick < 10000:
                self.tick_rate = self.tick_rate * 0.7 + (dtick / dt) * 0.3
        self.server_tick = tick; self.tick_local = now
    def server_time(self, now):
        if self.server_tick is None:
            if self.joined_at is None: return 0
            return int((now - self.joined_at) * 1000.0) & 0xFFFFFFFF
        elapsed = now - self.tick_local
        ticks = self.server_tick + elapsed * self.tick_rate
        return int(ticks * 1000.0 / self.tick_rate) & 0xFFFFFFFF

class MovementPlanner:
    def __init__(self):
        self.step = float(STEP_PER_TICK)
        self.max_step = float(STEP_PER_TICK * 1.25)
        self.orbit_fraction = 0.55; self.orbit_speed = 6.0
        self.coast_limit = 3.0; self._last_yaw = 0.0
    def next_yaw(self): return self._last_yaw
    def aim_point(self, st, now):
        r = self._rescue_point(st)
        if r is not None: return r
        t = self._target_point(st, now); z = self._zone_point(st)
        if t is None: return z
        if z is not None and self._outside_zone(st, t): return z
        return t
    def _target_point(self, st, now):
        if st.target_pos is None: return None
        if st.target_seen is not None:
            gap = now - st.target_seen
            if 0.05 < gap < self.coast_limit:
                vx, vz = st.target_vel
                return (st.target_pos[0] + vx*gap, st.target_pos[1], st.target_pos[2] + vz*gap)
        return st.target_pos
    def _rescue_point(self, st):
        if not st.downed or st.my_pos is None: return None
        best, best_d = None, None
        for pos in st.downed.values():
            if pos is None: continue
            dx = pos[0] - st.my_pos[0]; dz = pos[2] - st.my_pos[2]
            d = math.sqrt(dx*dx + dz*dz)
            if best_d is None or d < best_d: best, best_d = pos, d
        return best
    def _zone_point(self, st):
        if st.zone_center is None or st.zone_radius <= 0: return None
        cx, cz = st.zone_center[0], st.zone_center[-1]
        y = st.my_pos[1] if st.my_pos else 0
        ring = st.zone_radius * self.orbit_fraction
        if st.my_pos is not None:
            dx = st.my_pos[0] - cx; dz = st.my_pos[2] - cz
            here = math.sqrt(dx*dx + dz*dz)
            if here <= ring * 1.15:
                if here > 1: st.orbit_angle = math.degrees(math.atan2(dz, dx))
                stride = float(self.step)
                max_deg = math.degrees(stride / max(ring, 1)) * 0.85
                st.orbit_angle = (st.orbit_angle + min(self.orbit_speed, max_deg)) % 360.0
                rad = math.radians(st.orbit_angle)
                return (cx + ring * math.cos(rad), y, cz + ring * math.sin(rad))
        return (cx, y, cz)
    def _outside_zone(self, st, point):
        if st.zone_center is None or st.zone_radius <= 0: return False
        cx, cz = st.zone_center[0], st.zone_center[-1]
        dx = point[0] - cx; dz = point[2] - cz
        return math.sqrt(dx*dx + dz*dz) > st.zone_radius * 0.75
    def plan(self, st, now):
        if st.my_pos is None or st.my_id is None: return None
        my = st.my_pos
        phases = (PHASE_FIGHT, PHASE_PREPARE, 2, 9)
        if st.phase is not None and st.phase not in phases: return my, 0.0, False
        aim = self.aim_point(st, now)
        if aim is None: return my, 0.0, False
        dx = aim[0] - my[0]; dz = aim[2] - my[2]
        dist = math.sqrt(dx*dx + dz*dz)
        ty = aim[1] if len(aim) > 2 else my[1]
        new_y = int(my[1] + (ty - my[1]) * 0.35)
        if dist <= 150.0 or dist < 1e-6: return (my[0], new_y, my[2]), dist, False
        step = float(self.step)
        if dist > 8000.0: step = self.max_step
        move = step if dist > step else dist
        nx = my[0] + dx / dist * move; nz = my[2] + dz / dist * move
        return (int(nx), new_y, int(nz)), dist, True

def _build_position_body(pid, old, new, yaw, st, moving):
    if moving and old is not None:
        dx = new[0] - old[0]; dz = new[2] - old[2]
        dist = math.sqrt(dx*dx + dz*dz)
        if dist >= 1:
            ux, uz = dx/dist, dz/dist
            vel = (int(ux*500), 0, int(uz*500))
            rot = (int(ux*100), 0, int(uz*100)); tdir = (int(ux*100), int(uz*100))
            aim = (ux, 0.0, uz); pose = POSE_DASHING
        else:
            vel = (0, 0, 0); rot = (0, 0, 0); tdir = (0, 0)
            aim = (0.0, 0.0, 0.0); pose = POSE_STANDING
    else:
        vel = (0, 0, 0)
        rad = math.radians(yaw); fx, fz = math.sin(rad), math.cos(rad)
        rot = (int(fx*100), 0, int(fz*100)); tdir = (int(fx*100), int(fz*100))
        aim = (fx, 0.0, fz); pose = POSE_STANDING
    return build_player_state_upload(pid, new, rot, tdir, vel, aim, st, ps=0, pp=pose, ping=90)

def dispatch_incoming(run, cmd, body, st, squad_n):
    if body is None: return
    if cmd == CMD_PLAYER_JOIN:
        info = parse_player_join(body)
        if info is None: return
        uid, fid, name = info
        st.add_player(fid, name)
        if uid == st.account_id:
            st.set_identity(fid)
            squad_ok(squad_n, f"we entered match (id 0x{fid:08X})")
            _set_squad_status(run, squad_n, "in_match", "fight phase")
    elif cmd == CMD_MY_STATE:
        pos = decode_my_state(body)
        if pos is not None: st.seed_my_pos(pos)
    elif cmd == CMD_OTHER_STATES:
        players = decode_players_v2(body); mates = st.teammates()
        for s, info in players.items():
            if s not in mates: continue
            if info.get("physx_pose") == 8: st.downed[s] = info["pos"]
            elif s in st.downed: st.downed.pop(s, None)
        if st.target_short is not None:
            info = players.get(st.target_short)
            if info is not None: st.update_target(info, time.time())
    elif cmd == CMD_SERVER_TIME:
        parsed = decode_server_time(body)
        if parsed is not None: st.sync_clock(parsed[0], time.time())
    elif cmd == CMD_GRI_SYNC:
        parsed = get_match_phase(body)
        if parsed is not None:
            phase, rn, _s, _e = parsed
            if phase != st.phase:
                st.phase = phase
                if phase == 3:
                    squad_ok(squad_n, "match started — fight phase")
                    _set_squad_status(run, squad_n, "in_match", "fight phase")
                elif phase == 5: squad_warn(squad_n, "round ended")
    elif cmd == CMD_SAFE_ZONE:
        zone = decode_safezone(body)
        if zone is None: return
        center = zone.get("inner_center") or zone.get("outer_center")
        radius = zone.get("inner_radius") or zone.get("outer_radius") or 0
        if center and radius > 0:
            st.zone_center = (center[0], 0, center[1]); st.zone_radius = radius * ZONE_RADIUS_SCALE
    elif cmd == CMD_QUICK_CHAT:
        parsed = decode_quick_chat(body)
        if parsed is None: return
        cid, short, _ = parsed
        if cid in (QUICK_CHAT_FOLLOW, QUICK_CHAT_HELP): st.target_short = short
    elif cmd == CMD_DEAD:
        try: pid, _ = _rd_varint(body, 0)
        except (IndexError, ValueError): return
        if st.my_id is not None and pid == st.my_id:
            if st.alive:
                st.alive = False
                squad_warn(squad_n, "one of ours was downed")

def _is_paused(run):
    return bool(run and run.get("_paused"))

def _set_phase(run, phase):
    if run is None: return
    with _jobs_lock:
        run["phase"] = phase
        if "status" in run and run["status"] not in ("stopped","done","error","restarting"):
            if phase == "error": run["status"] = "error"
            elif phase == "done": run["status"] = "done"
            elif run["status"] != "paused": run["status"] = "running"

def _set_squad_status(run, n, state, info=""):
    if run is None: return
    with _jobs_lock:
        run.setdefault("squad_status", {})[str(n)] = {"state": state, "info": info}

async def movement_loop(sock, ra, ukb, mc, state, stop_evt, run, squad_n, tag):
    planner = MovementPlanner()
    nr = (await layouts_from_mask(mc))[1]
    loop = asyncio.get_event_loop()
    next_tick = time.time(); sent = 0
    logged_started = False; last_mv = 0.0
    while not stop_evt.is_set():
        if _is_paused(run):
            await asyncio.sleep(0.5); continue
        now = time.time()
        if now < next_tick:
            try: await asyncio.wait_for(stop_evt.wait(), timeout=next_tick-now); break
            except asyncio.TimeoutError: pass
            continue
        next_tick += MOVE_INTERVAL
        if next_tick < now: next_tick = now + MOVE_INTERVAL
        if not state.alive or state.my_id is None: continue
        planned = planner.plan(state, now)
        if planned is None: continue
        new, dist, moving = planned
        old = state.my_pos; state.my_pos = new
        st = state.server_time(now)
        body = _build_position_body(state.my_id, old, new, planner.next_yaw(), st, moving)
        pkt = await build_packet(0x6B, nr, 0, CMD_MY_STATE, None, 1, body, ukb, True)
        try:
            await loop.sock_sendto(sock, pkt, ra)
            sent += 1
            if not logged_started:
                logged_started = True
                squad_ok(squad_n, f"{tag} entered map — moving now")
                _set_squad_status(run, squad_n, "moving", "position updates active")
            if moving and sent - last_mv >= 500:
                last_mv = sent
                squad_line(squad_n, f"{tag} moving ({sent} updates)", CY, "→")
        except Exception as e:
            _udp_log(f"{tag} move err: {e}")

async def play_game(sipp, prep_pkts, post_pkt, uk, mc, aid, tag, squad_n, run,
                    account_jwt="", sleep_ms=0):
    match_start = time.time()
    ping_task = afk_task = hello_task = sock = None
    ping_stop = asyncio.Event(); afk_stop = asyncio.Event()
    state = MovementState(aid); accum = {}
    try:
        ip, port = sipp.split(":"); port = int(port)
        rip = socket.gethostbyname(ip)
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        optimize_udp_socket(sock); sock.setblocking(False)
        ukb = bytes.fromhex(uk)
        remote = (rip, port)
        gap = sleep_ms / 1000.0 if sleep_ms else 0.02
        if account_jwt:
            await loop.sock_sendto(sock, build_auth_datagram(account_jwt, aid), remote)
        hello_hex = await build_hello_packet(f"{aid}_2585", ukb, mc)
        hello_bytes = bytes.fromhex(hello_hex)
        await loop.sock_sendto(sock, hello_bytes, remote)
        squad_line(squad_n, f"{tag} connecting to match server", GR, "·")
        ack_state = "waiting_for_hello_reply"
        startup_sent = False; local_closed = False
        send_lock = asyncio.Lock()
        nr = (await layouts_from_mask(mc))[1]

        async def ka_loop():
            pklist = [0x66,0x6D,0x69,0x6C,0x6B,0x6E,0x6F,0x70]; i = 0
            while not ping_stop.is_set():
                if ack_state != "waiting_for_hello_reply": break
                try: await asyncio.wait_for(ping_stop.wait(), timeout=0.1)
                except asyncio.TimeoutError: pass
            while not ping_stop.is_set():
                if _is_paused(run):
                    try: await asyncio.wait_for(ping_stop.wait(), timeout=1.0)
                    except asyncio.TimeoutError: pass
                    continue
                pk = pklist[i % len(pklist)]
                cnt = int(time.time()*1000) & 0xFFFFFFFF
                pkt = await build_packet(pk, nr, 0, 3, None, 0,
                                         cnt.to_bytes(4,"little") + b"\x00\x00\x00",
                                         ukb, encrypted=False)
                try: await loop.sock_sendto(sock, pkt, remote)
                except Exception: pass
                i += 1
                try: await asyncio.wait_for(ping_stop.wait(), timeout=3.0)
                except asyncio.TimeoutError: pass

        async def hello_retry_loop():
            for _ in range(8):
                if ping_stop.is_set() or ack_state != "waiting_for_hello_reply": return
                try: await asyncio.wait_for(ping_stop.wait(), timeout=0.8)
                except asyncio.TimeoutError: pass
                if ping_stop.is_set() or ack_state != "waiting_for_hello_reply": return
                try: await loop.sock_sendto(sock, hello_bytes, remote)
                except Exception: pass

        ping_task = asyncio.create_task(ka_loop())
        hello_task = asyncio.create_task(hello_retry_loop())
        afk_task = asyncio.create_task(movement_loop(sock, remote, ukb, mc, state,
                                                      afk_stop, run, squad_n, tag))
        last_activity = time.time()

        async def send_join():
            nonlocal ack_state, startup_sent
            if startup_sent: return
            async with send_lock:
                if startup_sent: return
                for p in prep_pkts:
                    await loop.sock_sendto(sock, bytes.fromhex(p), remote)
                    await asyncio.sleep(gap)
                await asyncio.sleep(gap)
                await loop.sock_sendto(sock, bytes.fromhex(post_pkt), remote)
                startup_sent = True; ack_state = "startup_sent"

        while not local_closed:
            if _is_paused(run):
                await asyncio.sleep(0.5); continue
            if time.time() - match_start > 700: break
            try:
                resp, sa = await asyncio.wait_for(loop.sock_recvfrom(sock, 65535), timeout=1.5)
                if resp:
                    last_activity = time.time()
                    frame = await decode_packet(resp, ukb, mc)
                    if frame:
                        cmd = frame.get('cmd'); oid = frame.get('orderId')
                        mk = frame.get('msgKey', 0); content = frame.get('content')
                        if mk < 100 and oid is not None:
                            da = await build_packet(0x68, nr, 0, 2, None, 1,
                                                    ((oid + 1) & 0xFFFF).to_bytes(2, "little"),
                                                    ukb)
                            await loop.sock_sendto(sock, da, sa)
                        if cmd == 1 and ack_state == "waiting_for_hello_reply":
                            ack_state = "ready_to_send_startup"
                        elif cmd == 3:
                            c = content or b""
                            cnt = c[:4] if len(c) >= 4 else c
                            rp = await build_packet(0x6D, nr, 0, 3, None, 0,
                                                    cnt + b"\x00\x00\x00", ukb, False)
                            await loop.sock_sendto(sock, rp, sa)
                        elif cmd == 130:
                            squad_ok(squad_n, f"{tag} joined match server — in game")
                        elif cmd == 103:
                            squad_line(squad_n, f"{tag} match ended", MG, "★", "ok")
                            if content:
                                try:
                                    de = await t_decode_packet(content.hex())
                                    if de: report_rewards(run, squad_n, "MATCH_END", de, accum)
                                except Exception: pass
                            local_closed = True
                        dispatch_incoming(run, cmd, content, state, squad_n)
            except asyncio.TimeoutError: pass
            except Exception as e:
                _udp_log(f"{tag} udp err: {e}"); await asyncio.sleep(0.5)
            if ack_state == "ready_to_send_startup" and not startup_sent:
                await send_join()
            elif ack_state == "startup_sent" and (time.time() - last_activity) > 30:
                break
    except Exception as e:
        squad_err(squad_n, f"{tag} fatal: {e}")
    finally:
        ping_stop.set(); afk_stop.set()
        for t in (ping_task, hello_task, afk_task):
            if t: t.cancel()
        if sock:
            try: sock.close()
            except Exception: pass
        if accum:
            summary = ", ".join(f"{k}=+{v}" for k, v in accum.items())
            squad_line(squad_n, f"{tag} rewards: {summary}", GN, "★", "reward")

# ═══════════════════════════════════════════════════════════════════
# ACCOUNT LOGIN
# ═══════════════════════════════════════════════════════════════════
_UA_V = ['4.0.18P6','4.0.19P7','4.0.20P1','4.1.0P3','4.1.5P2','4.2.1P8',
         '4.2.3P1','5.0.1B2','5.0.2P4','5.1.0P1','5.2.0B1','5.2.5P3',
         '5.3.0B1','5.3.2P2','5.4.0P1','5.4.3B2','5.5.0P1','5.5.2P3']
_UA_M = ['SM-A125F','SM-A225F','SM-A325M','SM-A515F','SM-A725F','SM-M215F',
         'SM-M325FV','Redmi 9A','Redmi 9C','POCO M3','POCO M4 Pro','RMX2185',
         'RMX3085','moto g(9) play','CPH2239','V2027','OnePlus Nord','ASUS_Z01QD']
_UA_A = ['9','10','11','12','13','14']
_UA_L = ['en-US','es-MX','pt-BR','id-ID','ru-RU','hi-IN']
_UA_C = ['USA','MEX','BRA','IDN','RUS','IND']
def _rand_ua():
    return (f"GarenaMSDK/{random.choice(_UA_V)}"
            f"({random.choice(_UA_M)};Android {random.choice(_UA_A)};"
            f"{random.choice(_UA_L)};{random.choice(_UA_C)};)")

async def get_guest_token(uid, password, max_retries=6):
    headers = {"Host": "100067.connect.garena.com", "User-Agent": _rand_ua(),
               "Content-Type": "application/x-www-form-urlencoded",
               "Accept-Encoding": "gzip, deflate, br", "Connection": "close"}
    data = {"uid": uid, "password": password, "response_type": "token",
            "client_type": "2", "client_secret": SECRET, "client_id": APP_ID}
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post("https://100067.connect.garena.com/oauth/guest/token/grant",
                                  headers=headers, data=data) as r:
                    body = await r.text()
                    if r.status != 200:
                        last_err = f"HTTP {r.status}"; await asyncio.sleep(min(2.0 * attempt, 10.0)); continue
                    j = json.loads(body)
                    oid = j.get("open_id"); tok = j.get("access_token"); plat = j.get("platform", 4)
                    if oid and tok: return oid, tok, int(plat or 4)
                    last_err = "missing fields"
        except Exception as e: last_err = str(e)
        await asyncio.sleep(min(2.0 * attempt, 10.0))
    raise RuntimeError(f"guest token failed: {last_err}")

def _to_bytes(v):
    if isinstance(v, bytes): return v
    if isinstance(v, str):
        try: return bytes.fromhex(v)
        except ValueError: return v.encode()
    return bytes(v)

async def login_new_account(rec, cfg, tag, max_retries=6):
    uid = rec["uid"]; pw = rec.get("pass") or rec.get("password")
    oid = rec.get("open_id"); at = rec.get("access_token"); plat = rec.get("platform")
    if not oid or not at:
        oid, at, plat = await get_guest_token(uid, pw)
        rec["open_id"] = oid; rec["access_token"] = at; rec["platform"] = plat
    plat = int(plat or 4)
    login = None; last_err = None
    lock = _get_login_lock()
    async with lock:
        for attempt in range(1, max_retries + 1):
            try:
                login = await asyncio.to_thread(major_login, tag, oid, at, cfg, plat, REGION); break
            except Exception as e:
                last_err = e; await asyncio.sleep(min(2.0 * attempt, 15.0))
        if login is None: raise RuntimeError(f"{tag} login failed: {last_err}")
    payload = decode_jwt_payload(login["jwt"]) if login.get("jwt") else {}
    lock_reg = (payload.get("lock_region") or "").upper()
    cfg_use = cfg
    if lock_reg != REGION:
        conf = await asyncio.to_thread(choose_region, tag, login["jwt"], cfg, REGION)
        cfg_use = {**cfg, "country_code": conf, "region": conf}
        login = await asyncio.to_thread(major_login, tag, oid, at, cfg_use, plat, conf)
    ld = await asyncio.to_thread(get_login_data, tag, oid, at, cfg_use, plat, login["jwt"])
    f = login["fields"]
    ts = first_value(f, 21, "varint")
    kr = first_value(f, 22, "bytes") or first_value(f, 22, "string")
    ir = first_value(f, 23, "bytes") or first_value(f, 23, "string")
    if ts is None or kr is None or ir is None: raise RuntimeError(f"{tag} missing key/iv/ts")
    return {"tag": tag, "uid": uid, "ingame_id": login["account_id"],
            "open_id": oid, "access_token": at, "jwt": login["jwt"],
            "key": _to_bytes(kr), "iv": _to_bytes(ir), "ts": ts,
            "game_server": ld["game_server"], "chat_server": ld["chat_server"],
            "server_url": login.get("game_url"), "name": rec.get("name", "?"),
            "cfg": cfg_use}

def collect_all_ints(obj, out):
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], int): out.add(obj["data"])
        for v in obj.values(): collect_all_ints(v, out)
    elif isinstance(obj, list):
        for x in obj: collect_all_ints(x, out)
    elif isinstance(obj, int): out.add(obj)

def _match_info_from_frame(ptype, cmd, decoded):
    if not isinstance(decoded, dict): return None
    if not ((ptype == 0x03 and cmd == 5) or (ptype == 0x11 and cmd == 3)): return None
    r5 = decoded.get("5") or {}
    if not isinstance(r5, dict): return None
    for k in ("2","3","4","42"):
        v = r5.get(k)
        if isinstance(v, dict): r5[k] = v.get("data")
    if (isinstance(r5.get("2"), str) and ":" in r5["2"]
            and isinstance(r5.get("3"), str)
            and isinstance(r5.get("4"), str)
            and r5.get("42")):
        r5["42"] = str(r5["42"]); return r5
    return None

# ═══════════════════════════════════════════════════════════════════
# MASTER / SLAVE
# ═══════════════════════════════════════════════════════════════════
async def master_loop(acct, slave_ids, holder, match_infos, squad_n, run):
    tag = acct["tag"]
    ip, port = acct["game_server"].split(":")
    key, iv = acct["key"], acct["iv"]
    jwt = acct["jwt"]; aid = int(acct["ingame_id"]); ts = acct["ts"]
    slave_set = {int(x) for x in slave_ids}
    rv = acct["cfg"].get("remote_version", Play_Version)
    auth_online = await build_auth_packet(aid, jwt, ts, key, iv, REGION, "OnLine")
    ka_bytes = await send_keep_alive(REGION)
    reader, writer = await asyncio.open_connection(ip, int(port))
    writer.write(auth_online); await writer.drain()
    writer.write(ka_bytes); await writer.drain()
    ka_stop = asyncio.Event()
    async def ka_loop():
        while not ka_stop.is_set():
            try:
                await asyncio.sleep(15)
                if _is_paused(run): continue
                writer.write(ka_bytes); await writer.drain()
            except Exception: return
    ka_task = asyncio.create_task(ka_loop())
    await asyncio.sleep(1.0)
    c = br_create_squad_pkt(REGION, rv, key, iv)
    writer.write(c); await writer.drain()
    squad_line(squad_n, "master creating squad…", CY, "»")
    created = False; op31_sent = False; buf = bytearray(); rewards_accum = {}

    async def start_watcher():
        try: await asyncio.wait_for(holder["team_code_ready"].wait(), 25)
        except asyncio.TimeoutError:
            squad_err(squad_n, "no team code")
            _set_squad_status(run, squad_n, "failed", "no team code"); return
        squad_ok(squad_n, "team code received")
        t0 = time.time()
        while time.time() - t0 < 25:
            if holder["slave_joined"] >= slave_set: break
            await asyncio.sleep(0.4)
        squad_line(squad_n, f"{len(holder['slave_joined'])}/{len(slave_set)} slaves joined", CY, "·")
        await asyncio.sleep(SETTLE_AFTER_ALL_JOIN)
        s = br_start_squad_pkt(aid, REGION, key, iv)
        try:
            writer.write(s); await writer.drain()
            squad_line(squad_n, "starting matchmaking…")
            _set_squad_status(run, squad_n, "matchmaking", "queued")
        except Exception as e: squad_err(squad_n, f"start err: {e}")
    start_task = asyncio.create_task(start_watcher())
    try:
        while True:
            if _is_paused(run):
                await asyncio.sleep(0.5); continue
            try:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=30)
            except asyncio.TimeoutError: continue
            except Exception: break
            if not chunk: break
            buf.extend(chunk)
            while len(buf) >= 5:
                ptype = buf[0]; plen = int.from_bytes(buf[1:5], "big")
                if plen > 100_000: buf.clear(); break
                if len(buf) < 5 + plen: break
                payload = bytes(buf[5:5+plen]); del buf[:5+plen]
                decoded = None
                try: decoded = await t_decode_packet(payload.hex())
                except Exception: pass
                cmd = decoded.get("4") if isinstance(decoded, dict) else None
                if ptype == 0x05 and isinstance(decoded, dict):
                    data = decoded.get("5", {})
                    if cmd == 1 and not created and plen >= 100:
                        gid = None
                        if isinstance(data, dict):
                            g = data.get("1")
                            if isinstance(g, dict): g = g.get("data")
                            if isinstance(g, int): gid = g
                        created = True; holder["group_id"] = gid; holder["master_id"] = aid
                    elif cmd == 32 and not holder["team_code"]:
                        tc_val = None
                        if isinstance(data, dict):
                            t = data.get("1")
                            if isinstance(t, dict): t = t.get("data")
                            if isinstance(t, (str, int)): tc_val = str(t)
                        if tc_val is None:
                            t = decoded.get("1")
                            if isinstance(t, dict): t = t.get("data")
                            if isinstance(t, (str, int)): tc_val = str(t)
                        if tc_val:
                            holder["team_code"] = tc_val; holder["team_code_ready"].set()
                    if created and not op31_sent and holder["group_id"]:
                        op31_sent = True
                        try:
                            p31 = await send_op31(holder["group_id"], REGION, key, iv)
                            writer.write(p31); await writer.drain()
                        except Exception: pass
                    if cmd == 6:
                        found = set(); collect_all_ints(decoded, found)
                        newj = found & slave_set
                        for sid in newj: holder["slave_joined"].add(sid)
                    elif cmd == 10:
                        squad_ok(squad_n, "match accepted — flying in")
                        _set_squad_status(run, squad_n, "in_match", "accepted")
                    elif ptype == 0x04 and cmd in (1, 2):
                        src = "MATCHSTATS_NTF" if cmd == 1 else "UPDATEMMR_NTF"
                        report_rewards(run, squad_n, src, decoded, rewards_accum)
                elif ptype == 0x11 and cmd == 5 and not holder["team_code"]:
                    data = decoded.get("5", {}) if isinstance(decoded, dict) else {}
                    tc_val = None
                    if isinstance(data, dict):
                        t = data.get("11")
                        if isinstance(t, dict): t = t.get("data")
                        if isinstance(t, (str, int)) and str(t).isdigit() and len(str(t)) >= 5:
                            tc_val = str(t)
                    if tc_val:
                        holder["team_code"] = tc_val; holder["team_code_ready"].set()
                minfo = _match_info_from_frame(ptype, cmd, decoded)
                if minfo is not None and tag not in match_infos:
                    match_infos[tag] = minfo
                    squad_ok(squad_n, "MATCH FOUND · deploying soon")
    finally:
        start_task.cancel()
        try: await start_task
        except asyncio.CancelledError: pass
        ka_stop.set(); ka_task.cancel(); writer.close()
        try: await writer.wait_closed()
        except Exception: pass

async def slave_loop(acct, holder, match_infos, stop_evt, squad_n, run):
    tag = acct["tag"]
    ip, port = acct["game_server"].split(":")
    key, iv = acct["key"], acct["iv"]
    jwt = acct["jwt"]; aid = int(acct["ingame_id"]); ts = acct["ts"]
    auth_online = await build_auth_packet(aid, jwt, ts, key, iv, REGION, "OnLine")
    ka_bytes = await send_keep_alive(REGION)
    rv = acct["cfg"].get("remote_version", Play_Version)
    while not stop_evt.is_set():
        try:
            if _is_paused(run):
                await asyncio.sleep(0.5); continue
            reader, writer = await asyncio.open_connection(ip, int(port))
            writer.write(auth_online); await writer.drain()
            writer.write(ka_bytes); await writer.drain()
            ka_stop = asyncio.Event()
            async def ka_loop():
                while not ka_stop.is_set():
                    try:
                        await asyncio.sleep(15)
                        if _is_paused(run): continue
                        writer.write(ka_bytes); await writer.drain()
                    except Exception: return
            ka_task = asyncio.create_task(ka_loop())
            try: await asyncio.wait_for(holder["team_code_ready"].wait(), 30)
            except asyncio.TimeoutError:
                ka_stop.set(); ka_task.cancel(); writer.close(); continue
            tc = holder["team_code"]
            j = br_join_team_pkt(tc, REGION, rv, key, iv)
            writer.write(j); await writer.drain()
            joined = False; js = time.time(); buf = bytearray()
            while not stop_evt.is_set():
                if _is_paused(run):
                    await asyncio.sleep(0.5); continue
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=1.0)
                except asyncio.TimeoutError:
                    if not joined and time.time() - js > 6:
                        joined = True; holder["slave_joined"].add(aid)
                    continue
                except Exception: break
                if not chunk: break
                buf.extend(chunk)
                while len(buf) >= 5:
                    ptype = buf[0]; plen = int.from_bytes(buf[1:5], "big")
                    if plen > 100_000 or len(buf) < 5 + plen: break
                    payload = bytes(buf[5:5+plen]); del buf[:5+plen]
                    decoded = None
                    try: decoded = await t_decode_packet(payload.hex())
                    except Exception: pass
                    cmd = decoded.get("4") if isinstance(decoded, dict) else None
                    if ptype == 0x05 and plen >= 200 and not joined:
                        joined = True; holder["slave_joined"].add(aid)
                    if ptype == 0x05 and isinstance(decoded, dict) and cmd == 10:
                        squad_ok(squad_n, f"{tag} match accepted")
                    minfo = _match_info_from_frame(ptype, cmd, decoded)
                    if minfo is not None and tag not in match_infos:
                        match_infos[tag] = minfo
            ka_stop.set(); ka_task.cancel(); writer.close()
            try: await writer.wait_closed()
            except Exception: pass
            if stop_evt.is_set(): break
        except Exception: await asyncio.sleep(2.0)

# ═══════════════════════════════════════════════════════════════════
# SQUAD / ALL SQUADS
# ═══════════════════════════════════════════════════════════════════
async def run_gameplay(accounts, cfg, run, squad_idx):
    pref = f"Q{squad_idx}"
    def _t(b): return f"[{pref}-{b}]"
    squad_line(squad_idx, "logging in accounts…")
    _set_squad_status(run, squad_idx, "logging_in")
    logged = []
    for i, rec in enumerate(accounts):
        tag = _t("M") if i == 0 else _t(f"S{i}")
        if _is_paused(run):
            while _is_paused(run):
                await asyncio.sleep(0.5)
        try:
            acct = await login_new_account(rec, cfg, tag)
            logged.append(acct)
        except Exception:
            squad_err(squad_idx, f"{tag} login failed")
            _set_squad_status(run, squad_idx, "failed", "login error")
            return
        await asyncio.sleep(1.5)
    if len(logged) < 4:
        squad_err(squad_idx, f"only {len(logged)}/4 logged in")
        _set_squad_status(run, squad_idx, "failed", "incomplete"); return
    master = logged[0]; slaves = logged[1:]
    ids = [int(s["ingame_id"]) for s in slaves]
    squad_ok(squad_idx, f"master id={master['ingame_id']} · {len(slaves)} slaves ready")
    _set_squad_status(run, squad_idx, "squad_ready")
    holder = {"group_id": None, "team_code": None,
              "team_code_ready": asyncio.Event(),
              "slave_joined": set(), "master_id": None}
    match_infos = {}
    slave_stop = asyncio.Event()
    slave_tasks = [asyncio.create_task(slave_loop(s, holder, match_infos, slave_stop,
                                                   squad_idx, run)) for s in slaves]
    await asyncio.sleep(2.0)
    master_task = asyncio.create_task(master_loop(master, ids, holder, match_infos,
                                                   squad_idx, run))
    expected = [a["tag"] for a in logged]
    deadline = time.time() + 180
    while time.time() < deadline:
        if all(t in match_infos for t in expected): break
        await asyncio.sleep(0.5)
    missing = [t for t in expected if t not in match_infos]
    if missing:
        squad_err(squad_idx, "no match info — aborting")
        _set_squad_status(run, squad_idx, "failed", "no match")
        slave_stop.set()
        for t in slave_tasks + [master_task]: t.cancel()
        return
    squad_ok(squad_idx, "all accounts got match info — deploying")
    _set_squad_status(run, squad_idx, "in_match")
    udp_tasks = []
    for a in logged:
        r5 = match_infos[a["tag"]]
        def _u(v): return v.get("data") if isinstance(v, dict) else v
        mid  = _u(r5.get("1")) or 0
        map_ = _u(r5.get("6")) or 1
        gm   = _u(r5.get("7")) or 15
        mm   = _u(r5.get("8")) or 1
        sm   = _u(r5.get("5")) or 0
        prep, post = await build_join_match_startup(
            r5["4"], r5["3"], r5["42"], int(a["ingame_id"]), mid,
            server_ip=r5["2"], region=REGION,
            cv=a["cfg"].get("remote_version", Play_Version),
            cvc="2019121229", at=a["access_token"],
            mid=mid, cc="IN", map_id=map_, gm=gm, mm=mm)
        udp_tasks.append(asyncio.create_task(play_game(
            r5["2"], prep, post, r5["3"], r5["42"],
            int(a["ingame_id"]), tag=a["tag"], squad_n=squad_idx, run=run,
            account_jwt=r5["4"], sleep_ms=sm)))
    tcp_tasks = slave_tasks + [master_task]
    try:
        await asyncio.gather(*udp_tasks, *tcp_tasks)
    except asyncio.CancelledError:
        slave_stop.set()
        for t in tcp_tasks: t.cancel()
        raise
    finally:
        slave_stop.set()
        for t in tcp_tasks: t.cancel()
        try: await asyncio.gather(*tcp_tasks, return_exceptions=True)
        except Exception: pass
        squad_ok(squad_idx, "match finished 🏁")
        _set_squad_status(run, squad_idx, "finished")

async def run_all_squads(accounts, cfg, run, num_squads, stagger=8.0):
    chunks = [accounts[i:i+4] for i in range(0, len(accounts), 4)]
    valid = [c for c in chunks if len(c) == 4][:num_squads]
    if not valid:
        err("no complete squads"); return
    ok(f"deploying {len(valid)} squad(s)")
    tasks = []
    for i, chunk in enumerate(valid, 1):
        if i > 1:
            action(f"waiting {stagger:.0f}s before squad {i}…")
            await asyncio.sleep(stagger)
        squad_line(i, f"SQUAD {i}/{len(valid)} starting", GN, "▶")
        tasks.append(asyncio.create_task(run_gameplay(chunk, cfg, run, i)))
    try: await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks: t.cancel()
        raise

# ═══════════════════════════════════════════════════════════════════
# GLORY RUN ENTRY
# ═══════════════════════════════════════════════════════════════════
def _setup_region(region):
    global REGION, LANG_CODE, SERVER_URL, CLIENT_URL
    REGION = region
    LANG_CODE = REGION_LANG.get(region, "en")
    grp = REGION_GROUP.get(region, "OTHERS")
    SERVER_URL = REGION_URLS[grp]["server"]
    CLIENT_URL = REGION_URLS[grp]["client"]

async def _glory_async(run):
    global CFG, Play_Version, Ob_VeR
    _set_current_run(run)
    region = run["region"]
    squads = run["squads"]
    _setup_region(region)
    try:
        with open(UDP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"# job {run['id']} — {datetime.now().isoformat()}\n")
    except Exception: pass

    info("fetching version info…")
    _set_phase(run, "version")
    try:
        pv = get_play_store_version()
        CFG = fetch_ver_config(pv)
        Play_Version = CFG.get("remote_version", pv)
        Ob_VeR = CFG["latest_release_version"]
        ok(f"game version {Ob_VeR}")
    except Exception:
        err("version fetch failed")
        _set_phase(run, "error")
        run["error"] = "version fetch failed"
        _save_jobs()
        return

    _set_phase(run, "creating_accounts")
    needed = squads * 4
    accounts = await fetch_accounts_with_retry(needed, region=region)
    if len(accounts) < 4:
        err("not enough accounts created — aborting")
        _set_phase(run, "error")
        run["error"] = "not enough accounts"
        _save_jobs(); return
    real = len(accounts) // 4
    if real < squads:
        warn(f"running {real} squad(s) instead of {squads}")
        squads = real
        run["squads"] = squads
    accounts = accounts[:squads * 4]
    if run.get("clan_id"):
        await join_all_to_clan(accounts, run["clan_id"])
    _set_phase(run, "deploying")
    ok(f"deploying {squads} squad(s)")
    await run_all_squads(accounts, CFG, run, squads, stagger=8.0)
    _set_phase(run, "done")
    _save_jobs()

# ═══════════════════════════════════════════════════════════════════
# FLASK APP
# ═══════════════════════════════════════════════════════════════════
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_IS_VERCEL,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
_dbg_open()
_restore_jobs_on_boot()

@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

def _read_html(path, fallback="<h1>Missing page</h1>"):
    try:
        with open(path, "r", encoding="utf-8") as f: return f.read()
    except Exception as e:
        _dbg("HTML", f"read {path}: {e}", "ERR"); return fallback

def _login_required(fn):
    @wraps(fn)
    def wrap(*a, **k):
        if not session.get("user"): return redirect(url_for("page_login"))
        return fn(*a, **k)
    return wrap

def _admin_required(fn):
    @wraps(fn)
    def wrap(*a, **k):
        if not session.get("admin"): return jsonify({"error":"admin only"}), 401
        return fn(*a, **k)
    return wrap

def _requester():
    """Return (is_admin, owner_username) or (None,None)."""
    if session.get("admin"): return True, ADMIN_USER
    u = session.get("user")
    if u: return False, u["username"]
    return None, None

def _job_owner_ok(job, is_admin, owner):
    if job is None: return False
    if is_admin: return True
    return job.get("owner") == owner

# ── PAGES ──
@app.route("/", methods=["GET"])
def page_login():
    if session.get("user"): return redirect(url_for("page_dashboard"))
    return Response(_read_html(LOGIN_HTML), mimetype="text/html")

@app.route("/dashboard", methods=["GET"])
@_login_required
def page_dashboard():
    return Response(_read_html(DASHBOARD_HTML), mimetype="text/html")

# ── AUTH ──
@app.route("/api/signup", methods=["POST", "OPTIONS"])
def api_signup():
    if request.method == "OPTIONS": return ("", 204)
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip().lower()
    username = (d.get("username") or "").strip().lower()
    password = d.get("password") or ""
    if not email.endswith("@gmail.com"): return jsonify({"status":"error","error":"Only @gmail.com accepted"}), 400
    if len(password) < 6: return jsonify({"status":"error","error":"Password too short"}), 400
    if not re.fullmatch(r"[a-z0-9._]{3,24}", username): return jsonify({"status":"error","error":"Invalid username"}), 400
    if _find_user(username): return jsonify({"status":"error","error":"Username taken"}), 409
    if _find_user_by_email(email): return jsonify({"status":"error","error":"Email already registered"}), 409
    pwd_hash, salt = _hash_password(password)
    users = _load_users()
    users.append({"email": email, "username": username,
                  "password_hash": pwd_hash, "salt": salt,
                  "credits": 0, "total_glory": 0, "history": [],
                  "created_at": datetime.now().isoformat()})
    _save_users(users)
    session.permanent = True
    session["user"] = {"username": username, "email": email}
    return jsonify({"status":"ok","username":username})

@app.route("/api/login", methods=["POST", "OPTIONS"])
def api_login():
    if request.method == "OPTIONS": return ("", 204)
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip().lower()
    password = d.get("password") or ""
    u = _find_user(username)
    if not u or not _verify_password(password, u.get("password_hash",""), u.get("salt","")):
        return jsonify({"status":"error","error":"Invalid credentials"}), 401
    session.permanent = True
    session["user"] = {"username": u["username"], "email": u.get("email","")}
    return jsonify({"status":"ok","username":u["username"]})

@app.route("/api/logout", methods=["POST", "OPTIONS"])
def api_logout():
    if request.method == "OPTIONS": return ("", 204)
    session.clear()
    return jsonify({"status":"ok"})

@app.route("/api/me", methods=["GET"])
def api_me():
    if session.get("admin"):
        return jsonify({"status":"ok","user":{
            "username": ADMIN_USER, "admin": True,
            "credits": -1, "total_glory": 0, "total_runs": 0}})
    u = session.get("user")
    if not u: return jsonify({"status":"error"}), 401
    full = _find_user(u["username"])
    if not full: return jsonify({"status":"error"}), 401
    pub = _public_user(full); pub["admin"] = False
    return jsonify({"status":"ok","user":pub})

# ── DEPLOY (creates a job) ──
@app.route("/api/glory/start", methods=["POST", "OPTIONS"])
def api_glory_start():
    if request.method == "OPTIONS": return ("", 204)
    is_admin, owner = _requester()
    if owner is None: return jsonify({"status":"error","error":"auth required"}), 401
    d = request.get_json(silent=True) or {}
    region = (d.get("region") or "IND").upper()
    clan_id = (d.get("clan_id") or "").strip() or None
    try: squads = int(d.get("squads", 1))
    except: return jsonify({"status":"error","error":"squads must be int"}), 400
    if region not in REGION_LIST: return jsonify({"status":"error","error":"unknown region"}), 400
    max_sq = MAX_SQUADS_HARD if is_admin else USER_MAX_SQUADS
    if not 1 <= squads <= max_sq:
        return jsonify({"status":"error","error": f"squads must be 1–{max_sq}"}), 400

    if not is_admin:
        full = _find_user(owner)
        if not full: return jsonify({"status":"error","error":"user missing"}), 400
        cost = squads * CREDIT_COST_PER_SQUAD
        if full.get("credits", 0) < cost:
            return jsonify({"status":"error","error": f"need {cost} credit(s), have {full.get('credits',0)}"}), 402
        _update_user(owner, lambda u2: u2.__setitem__("credits",
                                                     max(0, u2.get("credits",0)-cost)))

    job = _create_job(owner, region, squads, clan_id, is_admin)
    _job_start_thread(job)
    return jsonify({"status":"ok","job_id":job["id"],"region":region,"squads":squads})

# ── JOBS API ──
@app.route("/api/jobs", methods=["GET"])
def api_jobs_list():
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    with _jobs_lock:
        jobs = [_job_public(j) for j in _JOBS.values()
                if is_admin or j.get("owner") == owner]
    jobs.sort(key=lambda j: j.get("created_at") or 0, reverse=True)
    total_glory = sum(int(j.get("glory") or 0) for j in jobs)
    active = sum(1 for j in jobs
                 if j.get("status") in ("running","starting","paused","restarting"))
    return jsonify({"ok": True, "jobs": jobs,
                    "total_glory": total_glory, "active": active})

@app.route("/api/jobs/<job_id>/events", methods=["GET"])
def api_job_events(job_id):
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    job = _job_get(job_id)
    if not _job_owner_ok(job, is_admin, owner):
        return jsonify({"ok": False, "error": "not found"}), 404
    since = request.args.get("since", 0, type=int)
    with _jobs_lock:
        ev = list(job["events"])
        out = {"ok": True, "id": job_id,
               "status": job.get("status"), "phase": job.get("phase"),
               "glory": job.get("glory", 0),
               "rewards": job.get("rewards", {}),
               "squad_status": job.get("squad_status", {}),
               "paused": bool(job.get("_paused")),
               "error": job.get("error"),
               "events": ev[since:], "event_count": len(ev)}
    return jsonify(out)

@app.route("/api/jobs/<job_id>/pause", methods=["POST", "OPTIONS"])
def api_job_pause(job_id):
    if request.method == "OPTIONS": return ("", 204)
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    job = _job_get(job_id)
    if not _job_owner_ok(job, is_admin, owner): return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": _job_pause(job_id)})

@app.route("/api/jobs/<job_id>/resume", methods=["POST", "OPTIONS"])
def api_job_resume(job_id):
    if request.method == "OPTIONS": return ("", 204)
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    job = _job_get(job_id)
    if not _job_owner_ok(job, is_admin, owner): return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": _job_resume(job_id)})

@app.route("/api/jobs/<job_id>/stop", methods=["POST", "OPTIONS"])
def api_job_stop_route(job_id):
    if request.method == "OPTIONS": return ("", 204)
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    job = _job_get(job_id)
    if not _job_owner_ok(job, is_admin, owner): return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": _job_stop(job_id)})

@app.route("/api/jobs/<job_id>/restart", methods=["POST", "OPTIONS"])
def api_job_restart_route(job_id):
    if request.method == "OPTIONS": return ("", 204)
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    job = _job_get(job_id)
    if not _job_owner_ok(job, is_admin, owner): return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": _job_restart(job_id)})

@app.route("/api/jobs/<job_id>", methods=["DELETE", "OPTIONS"])
def api_job_delete_route(job_id):
    if request.method == "OPTIONS": return ("", 204)
    is_admin, owner = _requester()
    if owner is None: return jsonify({"ok": False, "error": "auth required"}), 401
    job = _job_get(job_id)
    if not _job_owner_ok(job, is_admin, owner): return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": _job_delete(job_id)})

# ── GUILD LOOKUP (used by deploy form + admin) ──
@app.route("/api/guild/check", methods=["POST", "OPTIONS"])
def api_guild_check():
    if request.method == "OPTIONS": return ("", 204)
    if not session.get("user") and not session.get("admin"):
        return jsonify({"ok": False, "error": "auth required"}), 401
    d = request.get_json(silent=True) or {}
    guild_id = str(d.get("guild_id") or "").strip()
    region = (d.get("region") or "").strip().upper() or None
    if not guild_id.isdigit() or not (8 <= len(guild_id) <= 12):
        return jsonify({"ok": False, "error": "Guild ID must be 8-12 digits"}), 400
    if region and region not in REGION_LIST_ALLOWED:
        return jsonify({"ok": False, "error": "Invalid region"}), 400
    try: result = fetch_guild_info(guild_id, region)
    except Exception as e:
        _dbg("GUILD", f"check failed: {type(e).__name__}: {e}", "ERR")
        return jsonify({"ok": False, "error": "Lookup failed. Try again."}), 500
    result.pop("attempts", None); result.pop("account_used", None); result.pop("region_used", None)
    return jsonify(result)

# ── ADMIN ──
ADMIN_LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Admin · Eren Glory</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:grid;place-items:center;
       background:radial-gradient(circle at 30% 20%,#1a0f36,#050208 70%);
       color:#f0eaff;font-family:system-ui,-apple-system,sans-serif;padding:24px}
  .card{width:min(380px,100%);padding:28px;border-radius:16px;
        border:1px solid rgba(220,210,255,.14);
        background:linear-gradient(160deg,rgba(28,16,52,.9),rgba(14,8,28,.9));
        backdrop-filter:blur(20px);box-shadow:0 24px 60px -22px rgba(0,0,0,.8)}
  h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
  p{color:#a99ac7;font-size:12.5px;margin:0 0 22px}
  label{display:block;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
        color:#6d5f8a;margin-bottom:6px;font-weight:600}
  input{width:100%;height:44px;padding:0 12px;border-radius:10px;
        border:1px solid rgba(220,210,255,.14);background:rgba(220,210,255,.03);
        color:#f0eaff;font-size:13.5px;outline:none;font-family:monospace;
        margin-bottom:14px}
  input:focus{border-color:rgba(139,92,246,.4);box-shadow:0 0 0 4px rgba(139,92,246,.1)}
  button{width:100%;height:46px;border:0;border-radius:10px;
         background:linear-gradient(135deg,#c084fc,#8b5cf6 45%,#fb923c);
         color:#fff;font-weight:700;font-size:13.5px;cursor:pointer;
         box-shadow:0 14px 32px -14px rgba(139,92,246,.8)}
  button:hover{transform:translateY(-1px)}
  .err{color:#ff7a90;font-size:12px;margin-top:10px;display:none}
</style></head><body>
<form class="card" onsubmit="return doLogin(event)">
  <h1>Admin Access</h1>
  <p>Restricted area.</p>
  <label>Username</label>
  <input id="u" autocomplete="off" autofocus>
  <label>Password</label>
  <input id="p" type="password" autocomplete="off">
  <button type="submit">Enter</button>
  <div class="err" id="err">Invalid credentials</div>
</form>
<script>
async function doLogin(e){
  e.preventDefault();
  const r = await fetch('/api/admin/login',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({username:document.getElementById('u').value,
                          password:document.getElementById('p').value})});
  if(r.ok){ location.href = '/dashboard'; }
  else { document.getElementById('err').style.display='block'; }
  return false;
}
</script></body></html>"""

@app.route("/glory/admin/eren/secret", methods=["GET"])
def page_admin_login():
    if session.get("admin"): return redirect(url_for("page_dashboard"))
    return Response(ADMIN_LOGIN_HTML, mimetype="text/html")

@app.route("/api/admin/login", methods=["POST", "OPTIONS"])
def api_admin_login():
    if request.method == "OPTIONS": return ("", 204)
    d = request.get_json(silent=True) or {}
    if d.get("username") == ADMIN_USER and d.get("password") == ADMIN_PASS:
        session["admin"] = True
        session["user"] = {"username": ADMIN_USER, "email": ""}
        return jsonify({"status":"ok"})
    return jsonify({"status":"error","error":"invalid"}), 401

@app.route("/api/admin/logout", methods=["POST", "OPTIONS"])
def api_admin_logout():
    if request.method == "OPTIONS": return ("", 204)
    session.clear()
    return jsonify({"status":"ok"})

@app.route("/api/admin/users", methods=["GET"])
@_admin_required
def api_admin_users():
    users = _load_users()
    return jsonify({"users": [_public_user(u) for u in users]})

@app.route("/api/admin/credits", methods=["POST", "OPTIONS"])
@_admin_required
def api_admin_credits():
    if request.method == "OPTIONS": return ("", 204)
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip().lower()
    try: delta = int(d.get("delta", 0))
    except: return jsonify({"error":"delta must be int"}), 400
    u = _find_user(username)
    if not u: return jsonify({"error":"user not found"}), 404
    _update_user(username, lambda u2: u2.__setitem__("credits",
                                                     max(0, u2.get("credits",0) + delta)))
    u = _find_user(username)
    return jsonify({"status":"ok","username":username,"credits": u.get("credits",0)})

@app.route("/api/admin/guild-accounts", methods=["GET"])
@_admin_required
def api_admin_guild_accounts():
    cache_info = guild_get_cache_info()
    accounts = {}
    for k, v in GUILD_ACCOUNTS.items():
        uid = str(v.get("uid") or "")
        accounts[k] = {"uid": ("•••" + uid[-3:]) if uid else "not set",
                       "cache": cache_info.get(k, {})}
    return jsonify({"ok": True, "accounts": accounts})

# ═══════════════════════════════════════════════════════════════════
# LOCAL ENTRY
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print()
    print(f"  {RD}{B}╔════════════════════════════════════════════════════╗{R}")
    print(f"  {RD}{B}║{R}  {WH}{B}EREN  GLORY{R}  {GR}·{R}  {RD}{B}WEB + API + BOT + JOBS{R}          {RD}{B}║{R}")
    print(f"  {RD}{B}╚════════════════════════════════════════════════════╝{R}")
    print()
    print(f"  {GR}·{R} http://localhost:{port}/")
    print(f"  {GR}·{R} admin: http://localhost:{port}/glory/admin/eren/secret")
    print()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)