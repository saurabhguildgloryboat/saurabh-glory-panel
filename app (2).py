import os
import re
import sys
import json
import time
import uuid
import hmac
import base64
import random
import hashlib
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

REGION_LIST = [
    "IND", "ID", "TH", "ME", "EUROPE", "VN", "BD",
    "PK", "TW", "RU", "NA", "SAC", "BR", "SG", "US",
]

REGION_LANG = {
    "ME":     "ar",
    "IND":    "hi",
    "ID":     "id",
    "VN":     "vi",
    "TH":     "th",
    "BD":     "bn",
    "PK":     "ur",
    "TW":     "zh",
    "EUROPE": "fr",
    "RU":     "ru",
    "NA":     "na",
    "SAC":    "es",
    "BR":     "pt",
    "SG":     "ms",
    "US":     "us",
}

REGION_GROUP = {
    "IND":    "IND",
    "BR":     "AMERICA", "US": "AMERICA", "NA": "AMERICA", "SAC": "AMERICA",
    "ID":     "OTHERS",  "TH": "OTHERS",  "ME": "OTHERS",  "EUROPE": "OTHERS",
    "VN":     "OTHERS",  "BD": "OTHERS",  "PK": "OTHERS",  "TW": "OTHERS",
    "RU":     "OTHERS",  "SG": "OTHERS",
}

REGION_URLS = {
    "IND":     {"server": "https://loginbp.ggpolarbear.com/",
                "client": "https://client.ind.freefiremobile.com/"},
    "AMERICA": {"server": "https://loginbp.ggpolarbear.com/",
                "client": "https://client.us.freefiremobile.com/"},
    "OTHERS":  {"server": "https://loginbp.ggpolarbear.com/",
                "client": "https://clientbp.ggpolarbear.com/"},
}

REGION    = None
LANG_CODE = None
SERVER_URL = None
CLIENT_URL = None

APP_ID       = 100067
CLIENT_TYPE  = 2
SOURCE       = 2
SECRET       = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
PASSWORD_RAW = "Eren"
PASSWORD     = hashlib.sha256(PASSWORD_RAW.encode()).hexdigest().upper()

GARENA_BASE  = "https://100067.connect.garena.com/api/v2/oauth"
REGISTER_URL = f"{GARENA_BASE}/guest:register"
GRANT_URL    = f"{GARENA_BASE}/guest/token:grant"

DATADOME_URL  = "https://datadome.garena.com/js/"
VER_URL_BASE  = "https://version.ggwhitehawk.com/live/ver.php"
PLAYSTORE_URL = "https://play.google.com/store/apps/details?id=com.dts.freefireth&hl=en&gl=US"

ACCOUNT_FILE_TEMPLATE = "{region}_Account.json"

MAX_WORKERS            = 10
MIN_REGISTER_INTERVAL  = 1.0
REGISTER_BACKOFF_START = 20.0
REGISTER_BACKOFF_MAX   = 180.0
REGISTER_MAX_RETRIES   = 12
DATADOME_MAX_RETRIES   = 4
VER_MAX_ATTEMPTS       = 3

USER_AGENT_MSDK  = "GarenaMSDK/4.0.44(V2538 ;Android 16;en;US;app 1.132.1 2019121227;)"
USER_AGENT_UNITY = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"
USER_AGENT_WEB   = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

_KEYSTREAM = bytes([
    0x30, 0x30, 0x30, 0x32, 0x30, 0x31, 0x37, 0x30, 0x30, 0x30, 0x30, 0x30, 0x32, 0x30, 0x31, 0x37,
    0x30, 0x30, 0x30, 0x30, 0x30, 0x32, 0x30, 0x31, 0x37, 0x30, 0x30, 0x30, 0x30, 0x30, 0x32, 0x30,
])

SESSION_HASH = "1ac4b80ecf0478a44203bf8fac6120f5"

R  = "\033[0m"
B  = "\033[1m"
D  = "\033[2m"
GR = "\033[90m"
RD = "\033[91m"
GN = "\033[92m"
YL = "\033[93m"
BL = "\033[94m"
MG = "\033[95m"
CY = "\033[96m"
WH = "\033[97m"

_print_lock = threading.Lock()
_file_lock  = threading.Lock()
_gate_lock  = threading.Lock()
_dd_lock    = threading.Lock()

_last_register_time = 0.0
_start_time         = time.time()
_total_target       = 0
_success_count      = 0
_failure_count      = 0
_count_lock         = threading.Lock()

_dd_session_cookie = None
_dd_expires_at     = 0.0

CFG = {}
ACCOUNT_FILE = "Account.json"

SYMBOLS = [
    "꧁", "꧂", "『", "』", "【", "】", "乂", "么", "メ", "ツ", "彡", "々", "〆", "๛",
    "✿", "❀", "✧", "✦", "★", "☆", "✪", "✯", "✰", "✮", "⚡", "☠", "☣", "☢",
    "♛", "♚", "♔", "♕", "♤", "♠", "♡", "♥", "♦", "♣", "∞", "✓", "✘", "☯",
    "卍", "۝", "༒", "༺", "༻", "⸸", "⌁", "ꨄ", "࿐", "ꪜ", "ꫂ",
]


def _tag(i, n):
    return f"{i:>2}/{n}"


def step(tag, icon, msg, color=CY):
    with _print_lock:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{GR}{ts}{R} {color}{B}[{tag}]{R} {color}{icon}{R} {msg}", flush=True)


def ok(tag, msg):
    step(tag, "✔", msg, GN)


def warn(tag, msg):
    step(tag, "!", msg, YL)


def fail(tag, msg):
    step(tag, "✘", msg, RD)


def info(tag, msg):
    step(tag, "·", msg, GR)


def decorate_name(prefix, max_prefix_len=7):
    core = prefix[:max_prefix_len]
    left = ''.join(random.sample(SYMBOLS, 2))
    right = ''.join(random.sample(SYMBOLS, 2))
    return f"{left}{core}{right}"


def _wait_register_slot(tag):
    global _last_register_time
    while True:
        with _gate_lock:
            now = time.time()
            wait = MIN_REGISTER_INTERVAL - (now - _last_register_time)
            if wait <= 0:
                _last_register_time = now
                return
        time.sleep(min(wait, 0.5))


def enc_aes(data):
    return AES.new(KEY, AES.MODE_CBC, IV).encrypt(pad(data, 16))


def dec_aes(data):
    try:
        return unpad(AES.new(KEY, AES.MODE_CBC, IV).decrypt(data), 16)
    except ValueError:
        return AES.new(KEY, AES.MODE_CBC, IV).decrypt(data)


def sign_body(body):
    return hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


def encode_open_id(open_id):
    return bytes(ord(open_id[i]) ^ _KEYSTREAM[i % len(_KEYSTREAM)] for i in range(len(open_id)))


def decode_jwt_payload(token):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        p2 = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(p2))
    except Exception:
        return {}


def enc_varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def read_varint(data, off):
    v, s = 0, 0
    while True:
        b = data[off]
        off += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80):
            return v, off
        s += 7


def ptag(f, wt):
    return enc_varint((f << 3) | wt)


def f_vint(f, n):
    return ptag(f, 0) + enc_varint(n)


def f_bytes(f, b):
    return ptag(f, 2) + enc_varint(len(b)) + b


def f_str(f, s):
    b = s.encode("utf-8")
    return ptag(f, 2) + enc_varint(len(b)) + b


def parse_proto(data):
    fields = {}
    i = 0
    while i < len(data):
        try:
            key, i = read_varint(data, i)
        except Exception:
            break
        fn, wt = key >> 3, key & 7
        try:
            if wt == 0:
                v, i = read_varint(data, i)
                fields.setdefault(fn, []).append(("varint", v))
            elif wt == 1:
                v = int.from_bytes(data[i:i+8], "little")
                i += 8
                fields.setdefault(fn, []).append(("u64", v))
            elif wt == 2:
                ln, i = read_varint(data, i)
                raw = data[i:i+ln]
                i += ln
                s_ok = False
                try:
                    s = raw.decode("utf-8")
                    if s.isprintable():
                        fields.setdefault(fn, []).append(("string", s))
                        s_ok = True
                except UnicodeDecodeError:
                    pass
                if not s_ok:
                    fields.setdefault(fn, []).append(("bytes", raw.hex()))
            elif wt == 5:
                v = int.from_bytes(data[i:i+4], "little")
                i += 4
                fields.setdefault(fn, []).append(("u32", v))
            else:
                break
        except Exception:
            break
    return fields


def first_value(fields, field_num, want_kind=None):
    for kind, v in fields.get(field_num, []):
        if want_kind is None or kind == want_kind:
            return v
    return None


def load_accounts():
    if not os.path.exists(ACCOUNT_FILE):
        return []
    try:
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_accounts(accounts):
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def append_account(account):
    with _file_lock:
        accounts = load_accounts()
        accounts.append(account)
        save_accounts(accounts)


def get_play_store_version():
    headers = {"User-Agent": USER_AGENT_WEB, "Accept-Language": "en-US,en;q=0.9"}
    html = requests.get(PLAYSTORE_URL, headers=headers, timeout=15).text
    versions = re.findall(r"\b(1\.\d{1,3}\.\d{1,3})\b", html)
    if not versions:
        raise RuntimeError("no version on playstore page")
    real = [v for v in versions if v != "1.000.000"]
    return (real or versions)[-1]


def fetch_ver_config(initial_version):
    version = initial_version
    last = None
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
            cfg = requests.get(url, timeout=15).json()
        except Exception as e:
            last = e
            time.sleep(1.0 * attempt)
            continue

        if cfg.get("code") == 0:
            cfg["region"]       = REGION
            cfg["lang"]         = LANG_CODE
            cfg["country_code"] = REGION
            cfg["server_url"]   = SERVER_URL
            cfg["client_url"]   = CLIENT_URL
            return cfg

        if cfg.get("remote_version"):
            version = cfg["remote_version"]
        last = cfg
        time.sleep(1.0 * attempt)

    raise RuntimeError(f"ver.php failed: {last}")


def get_datadome(tag, force=False):
    global _dd_session_cookie, _dd_expires_at
    with _dd_lock:
        now = time.time()
        if not force and _dd_session_cookie and _dd_expires_at > now:
            return _dd_session_cookie

        headers = {
            "User-Agent":      USER_AGENT_WEB,
            "Content-Type":    "application/x-www-form-urlencoded",
            "Referer":         "https://sso.garena.com/universal/register?locale=en-SG",
            "Origin":          "https://sso.garena.com",
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        payload = {
            "jsType":        "le",
            "eventCounters": '{"mousemove":1,"click":1,"keydown":11}',
            "ddk":           "AE3F04AD3F0D3A462481A337485081",
            "Referer":       "https://sso.garena.com/universal/register?locale=en-SG",
            "request":       "/universal/register?locale=en-SG",
            "responsePage":  "origin",
            "ddv":           "5.7.0",
        }

        last = None
        for attempt in range(1, DATADOME_MAX_RETRIES + 1):
            try:
                r = requests.post(DATADOME_URL, data=payload, headers=headers, timeout=15)
                r.raise_for_status()
                result = r.json()
            except Exception as e:
                last = e
                time.sleep(1.5 * attempt)
                continue

            if result.get("status") == 200 and result.get("cookie"):
                for part in result["cookie"].split(";"):
                    if "datadome=" in part:
                        dd = part.replace("datadome=", "").strip()
                        if dd:
                            _dd_session_cookie = dd
                            _dd_expires_at     = now + 300.0
                            ok(tag, f"{D}datadome{R} {GN}acquired{R} {GR}({len(dd)} chars){R}")
                            return dd

            last = result
            time.sleep(1.5 * attempt)

        raise RuntimeError(f"DataDome failed: {last}")


def guest_register(tag, device_id, max_retries=REGISTER_MAX_RETRIES):
    payload = {
        "app_id":      APP_ID,
        "client_type": CLIENT_TYPE,
        "password":    PASSWORD,
        "source":      SOURCE,
    }
    body = json.dumps(payload, separators=(",", ":"))

    last_err = None
    for attempt in range(1, max_retries + 1):
        _wait_register_slot(tag)
        datadome = get_datadome(tag, force=(attempt > 1 and attempt % 3 == 0))

        headers = {
            "User-Agent":    USER_AGENT_MSDK,
            "Authorization": f"Signature {sign_body(body)}",
            "Cookie":        f"datadome={datadome}",
            "Accept":        "application/json",
            "Content-Type":  "application/json; charset=utf-8",
        }

        try:
            r = requests.post(REGISTER_URL, data=body, headers=headers, timeout=25)
            data = r.json()
        except Exception as e:
            last_err = e
            warn(tag, f"register net-err ({attempt}/{max_retries})")
            time.sleep(2.0 * attempt)
            continue

        code = data.get("code")

        if code == 0:
            uid = data["data"]["uid"]
            ok(tag, f"register {D}uid{R}={WH}{uid}{R}")
            return uid

        if code in (1006, 1005):
            wait = min(REGISTER_BACKOFF_START * (2 ** (attempt - 1)), REGISTER_BACKOFF_MAX)
            warn(tag, f"register {code} cooling {YL}{wait:.0f}s{R} ({attempt}/{max_retries})")
            last_err = data
            time.sleep(wait)
            continue

        raise RuntimeError(f"guest:register failed: {data}")

    raise RuntimeError(f"guest:register gave up: {last_err}")


def guest_token(tag, uid, device_id):
    payload = {
        "client_id":     APP_ID,
        "client_secret": SECRET,
        "client_type":   CLIENT_TYPE,
        "device_id":     device_id,
        "password":      PASSWORD,
        "response_type": "token",
        "uid":           uid,
    }
    body = json.dumps(payload, separators=(",", ":"))
    datadome = get_datadome(tag)
    headers = {
        "User-Agent":   USER_AGENT_MSDK,
        "Cookie":       f"datadome={datadome}",
        "Accept":       "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    r = requests.post(GRANT_URL, data=body, headers=headers, timeout=20)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"guest/token:grant failed: {data}")
    tokens = data["data"]
    ok(tag, f"token    {D}open_id{R}={WH}{tokens['open_id'][:16]}…{R}  "
           f"{D}platform{R}={tokens.get('platform')}")
    return tokens


def generate_nickname(tag, open_id, cfg):
    url = cfg["server_url"].rstrip("/") + "/GenerateNickname"
    body = f_bytes(2, encode_open_id(open_id))
    headers = {
        "User-Agent":      USER_AGENT_UNITY,
        "Accept":          "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Authorization":   "Bearer",
        "X-GA":            "v1 1",
        "X-GA-SV":         str(int(time.time())),
        "ReleaseVersion":  cfg["latest_release_version"],
        "Content-Type":    "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    r = requests.post(url, data=enc_aes(body), headers=headers, timeout=20)

    fields = parse_proto(r.content)
    nickname = None
    payload = None
    for kind, v in fields.get(1, []):
        if kind == "string":
            nickname = v
            break
        if kind == "bytes":
            payload = bytes.fromhex(v)

    if nickname is None and payload is not None:
        decoded = bytes(b ^ _KEYSTREAM[i % len(_KEYSTREAM)] for i, b in enumerate(payload))
        nickname = "".join(chr(b) for b in decoded if 0x20 <= b <= 0x7E)

    if not nickname:
        raise RuntimeError(f"Nickname not found: {r.content.hex()}")

    ok(tag, f"name     {MG}{nickname}{R}")
    return nickname


def major_register(tag, open_id, access_token, name, cfg):
    url = cfg["server_url"].rstrip("/") + "/MajorRegister"

    body  = f_str(1, name)
    body += f_str(2, access_token)
    body += f_str(3, open_id)
    body += f_vint(5, 102000007)
    body += f_vint(6, 4)
    body += f_vint(7, 1)
    body += f_vint(13, 1)
    body += f_bytes(14, encode_open_id(open_id))
    body += f_str(15, LANG_CODE)
    body += f_vint(16, 2)
    body += f_str(22, PASSWORD)

    headers = {
        "User-Agent":      USER_AGENT_UNITY,
        "Accept":          "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Authorization":   "Bearer",
        "X-GA":            "v1 1",
        "X-GA-SV":         str(int(time.time())),
        "ReleaseVersion":  cfg["latest_release_version"],
        "Content-Type":    "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    r = requests.post(url, data=enc_aes(body), headers=headers, timeout=20)

    fields = parse_proto(r.content)
    if first_value(fields, 1, "varint") != 1:
        raise RuntimeError(f"MajorRegister failed: {fields}")
    ok(tag, f"register {GN}game-account created{R}")


def build_major_login(open_id, access_token, cfg, platform, region=None):
    remote_version = cfg["remote_version"]
    country        = cfg["country_code"]
    cdn_url        = cfg["cdn_url"]
    abhot_cdn      = cfg["abhotupdate_cdn_url"]
    client_ip      = cfg["client_ip"]
    vercfg_sign    = cfg["vercfg_sign"]

    cdn_hash = hashlib.md5(f"{open_id}{time.time_ns()}".encode()).hexdigest()
    cdn_blob = f"{cdn_url}|{abhot_cdn}|{cdn_hash}"

    sig_base64 = (
        "KqsHTwFsNrz71lqUGAjS+qIySSj2KOGy6RrHPlpy6KkAVaY7JOEtuPh7yc+7ruAa8IoJQdj5KVD"
        "vnuda+C89owjNtP1VCdBI3Q591QXRXy8qF6s/"
    )

    b  = b""
    b += f_str(3, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    b += f_str(4, "free fire")
    b += f_vint(5, 1)
    b += f_str(7, remote_version)
    b += f_str(8, "Android OS 16 / API-36 (BP2A.250605.031.A3_V000L1/compiler260320183556)")
    b += f_str(9, "Handheld")
    b += f_str(11, "CarrierDataNetwork")
    b += f_vint(12, 1637)
    b += f_vint(13, 750)
    b += f_str(14, "440")
    b += f_str(15, "ARM64 FP ASIMD AES | 5606 | 8")
    b += f_vint(16, 7282)
    b += f_str(17, "Adreno (TM) 722")
    b += f_str(18, "OpenGL ES 3.2 V@0800.69.2 (GIT@4659378004, I7f7aee143c, 1773055375) (Date:03/09/26)")
    b += f_str(19, "Google|c15d0cbb-0f10-4ad4-a960-739ca3891a93")
    b += f_str(20, client_ip)
    b += f_str(21, LANG_CODE)
    b += f_str(22, open_id)
    b += f_str(23, str(platform))
    b += f_str(24, "Handheld")
    b += f_str(25, "vivo V2538")
    if region is not None:
        b += f_str(26, region)
    b += f_str(29, access_token)
    b += f_vint(30, 1)
    b += f_str(42, "4G")
    b += f_str(57, SESSION_HASH)
    b += f_vint(60, 223554)
    b += f_vint(61, 100654)
    b += f_vint(62, 4465)
    b += f_vint(64, 100782)
    b += f_vint(65, 223554)
    b += f_vint(66, 100782)
    b += f_vint(67, 223554)
    b += f_vint(70, 4)
    b += f_vint(73, 1)
    b += f_str(74, "/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/lib/arm64")
    b += f_vint(76, 1)
    b += f_str(77, "066a589fa3f5658377634fe7b1d88556|/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/base.apk")
    b += f_vint(78, 6)
    b += f_vint(79, 2)
    b += f_str(81, "64")
    b += f_str(83, "2019121227")
    b += f_vint(85, 3)
    b += f_str(86, "OpenGLES2")
    b += f_vint(87, 8191)
    b += f_vint(88, platform)
    b += f_vint(92, 40843)
    b += f_str(93, "3rd_party")
    b += f_str(94, sig_base64)
    b += f_vint(95, 111207)
    b += f_str(96, '{"cur_rate":[60,90,120],"support_etc2":false}')
    b += f_vint(97, 1)
    b += f_vint(98, 1)
    b += f_str(99, str(platform))
    b += f_str(100, str(platform))
    b += f_str(102, "42531243535e0e0531")
    b += f_vint(104, 84750)
    b += f_vint(105, 1)
    b += f_str(106, cdn_blob)
    b += f_str(107, vercfg_sign)
    return b


def major_login(tag, open_id, access_token, cfg, platform, region=None):
    url = cfg["server_url"].rstrip("/") + "/MajorLogin"
    plain = build_major_login(open_id, access_token, cfg, platform, region=region)

    headers = {
        "User-Agent":      USER_AGENT_UNITY,
        "Accept":          "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Authorization":   "Bearer",
        "X-GA":            "v1 1",
        "X-GA-SV":         str(int(time.time())),
        "ReleaseVersion":  cfg["latest_release_version"],
        "Content-Type":    "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    r = requests.post(url, data=enc_aes(plain), headers=headers, timeout=20)

    if r.status_code != 200:
        raise RuntimeError(f"MajorLogin HTTP {r.status_code}")

    attempts = [("plain", parse_proto(r.content))]
    if len(r.content) > 64:
        attempts.append(("plain[64:]", parse_proto(r.content[64:])))
    try:
        attempts.append(("dec", parse_proto(dec_aes(r.content))))
    except Exception:
        pass
    if len(r.content) > 64:
        try:
            attempts.append(("dec[64:]", parse_proto(dec_aes(r.content[64:]))))
        except Exception:
            pass

    fields = {}
    for _, f in attempts:
        if 8 in f or 22 in f:
            fields = f
            break

    account_id = first_value(fields, 1, "varint")
    jwt        = first_value(fields, 8, "string")
    game_url   = first_value(fields, 10, "string")

    region_from_jwt = None
    payload = decode_jwt_payload(jwt) if jwt else {}
    if payload:
        region_from_jwt = payload.get("noti_region") or payload.get("lock_region")

    if (not jwt) or account_id is None or (isinstance(account_id, int) and account_id < 10_000_000):
        raise RuntimeError("MajorLogin implausible result")

    ok(tag, f"login    {D}id{R}={WH}{account_id}{R}  {D}jwt_region{R}={CY}{region_from_jwt or '—'}{R}")

    return {
        "account_id": account_id,
        "jwt":        jwt,
        "game_url":   game_url,
        "region":     region_from_jwt or region,
        "fields":     fields,
    }


def choose_region(tag, jwt, cfg, region):
    url = cfg["server_url"].rstrip("/") + "/ChooseRegion"
    body = f_str(1, region)

    headers = {
        "User-Agent":      USER_AGENT_UNITY,
        "Accept":          "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Authorization":   f"Bearer {jwt}",
        "X-GA":            "v1 1",
        "X-GA-SV":         str(int(time.time())),
        "ReleaseVersion":  cfg["latest_release_version"],
        "Content-Type":    "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    r = requests.post(url, data=enc_aes(body), headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"ChooseRegion HTTP {r.status_code}")

    fields = parse_proto(r.content)
    confirmed = first_value(fields, 1, "string")
    if not confirmed:
        for alt in (2, 3, 4):
            confirmed = first_value(fields, alt, "string")
            if confirmed:
                break
    if not confirmed:
        raise RuntimeError("ChooseRegion returned no region")

    ok(tag, f"lock     {D}region{R}={MG}{confirmed}{R}")
    return confirmed


def build_get_login_data(open_id, access_token, cfg, platform, jwt):
    remote_version = cfg["remote_version"]
    country        = cfg["country_code"]
    cdn_url        = cfg["cdn_url"]
    abhot_cdn      = cfg["abhotupdate_cdn_url"]
    client_ip      = cfg["client_ip"]
    vercfg_sign    = cfg["vercfg_sign"]

    cdn_hash = hashlib.md5(f"{open_id}{time.time_ns()}".encode()).hexdigest()
    cdn_blob = f"{cdn_url}|{abhot_cdn}|{cdn_hash}"

    sig_base64 = (
        "KqsHTwFsNrz71lqUGAjS+qIySSj2KOGy6RrHPlpy6KkAVaY7JOEtuPh7yc+7ruAa8IoJQdj5KVD"
        "vnuda+C89owjNtP1VCdBI3Q591QXRXy8qF6s/"
    )

    b  = b""
    b += f_str(3, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    b += f_str(4, "free fire")
    b += f_vint(5, 1)
    b += f_str(7, remote_version)
    b += f_str(8, "Android OS 16 / API-36 (BP2A.250605.031.A3_V000L1/compiler260320183556)")
    b += f_str(9, "Handheld")
    b += f_str(11, "CarrierDataNetwork")
    b += f_vint(12, 1637)
    b += f_vint(13, 750)
    b += f_str(14, "440")
    b += f_str(15, "ARM64 FP ASIMD AES | 5606 | 8")
    b += f_vint(16, 7282)
    b += f_str(17, "Adreno (TM) 722")
    b += f_str(18, "OpenGL ES 3.2 V@0800.69.2 (GIT@4659378004, I7f7aee143c, 1773055375) (Date:03/09/26)")
    b += f_str(19, "Google|c15d0cbb-0f10-4ad4-a960-739ca3891a93")
    b += f_str(20, client_ip)
    b += f_str(21, LANG_CODE)
    b += f_str(22, open_id)
    b += f_str(23, str(platform))
    b += f_str(24, "Handheld")
    b += f_str(25, "vivo V2538")
    b += f_str(26, country)
    b += f_str(29, access_token)
    b += f_vint(30, 1)
    b += f_str(42, "4G")
    b += f_str(57, SESSION_HASH)
    b += f_vint(60, 223554)
    b += f_vint(61, 100654)
    b += f_vint(62, 4465)
    b += f_vint(64, 100782)
    b += f_vint(65, 223554)
    b += f_vint(66, 100782)
    b += f_vint(67, 223554)
    b += f_vint(70, 4)
    b += f_vint(73, 1)
    b += f_str(74, "/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/lib/arm64")
    b += f_vint(76, 1)
    b += f_str(77, "066a589fa3f5658377634fe7b1d88556|/data/app/~~Hl4pq6GoyauPV457pS4N8g==/com.dts.freefireth-mRT8MtqxsyyrZkxcQBSRAA==/base.apk")
    b += f_vint(78, 6)
    b += f_vint(79, 2)
    b += f_str(81, "64")
    b += f_str(83, "2019121227")
    b += f_vint(85, 3)
    b += f_str(86, "OpenGLES2")
    b += f_vint(87, 8191)
    b += f_vint(88, platform)
    b += f_vint(92, 40843)
    b += f_str(93, "3rd_party")
    b += f_str(94, sig_base64)
    b += f_vint(95, 111207)
    b += f_str(96, '{"cur_rate":[60,90,120],"support_etc2":false}')
    b += f_vint(97, 1)
    b += f_vint(98, 1)
    b += f_str(99, str(platform))
    b += f_str(100, str(platform))
    b += f_str(102, "42531243535e0e0531")
    b += f_vint(104, 84750)
    b += f_vint(105, 1)
    b += f_str(106, cdn_blob)
    b += f_str(107, vercfg_sign)
    b += f_str(108, jwt)
    return b


def _decode_session_blob(field_63_hex):
    try:
        raw = bytes.fromhex(field_63_hex)
        sub = parse_proto(raw)
        b64 = first_value(sub, 10, "string")
        if not b64:
            return {}
        padded = b64 + "=" * (-len(b64) % 4)
        return json.loads(base64.b64decode(padded))
    except Exception:
        return {}


def get_login_data(tag, open_id, access_token, cfg, platform, jwt):
    plain = build_get_login_data(open_id, access_token, cfg, platform, jwt)
    login_url = cfg["client_url"].rstrip("/") + "/GetLoginData"

    headers = {
        "User-Agent":      USER_AGENT_UNITY,
        "Accept":          "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Authorization":   f"Bearer {jwt}",
        "X-GA":            "v1 1",
        "X-GA-SV":         str(int(time.time())),
        "ReleaseVersion":  cfg["latest_release_version"],
        "Content-Type":    "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    r = requests.post(login_url, data=enc_aes(plain), headers=headers, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"GetLoginData HTTP {r.status_code}")

    fields = parse_proto(r.content)

    account_id  = first_value(fields, 1,  "varint")
    region      = first_value(fields, 3,  "string")
    nickname    = first_value(fields, 4,  "string")
    game_server = first_value(fields, 14, "string")
    event_url   = first_value(fields, 16, "string")
    chat_server = first_value(fields, 32, "string")

    session = {}
    nested_63 = first_value(fields, 63, "bytes")
    if nested_63:
        session = _decode_session_blob(nested_63)

    ok(tag, f"data     {D}game{R}={CY}{game_server}{R}  {D}chat{R}={CY}{chat_server}{R}")

    return {
        "account_id":  account_id,
        "region":      region,
        "nickname":    nickname,
        "game_server": game_server,
        "chat_server": chat_server,
        "event_url":   event_url,
        "session":     session,
    }


def print_account_block(idx, total, account, elapsed):
    with _print_lock:
        print()
        print(f"  {GN}{B}┌─ ACCOUNT {idx}/{total} ─ CREATED ──────────────────────────────┐{R}")
        print(f"  {GN}│{R}  {D}uid        {R}  {WH}{account['uid']}{R}")
        print(f"  {GN}│{R}  {D}name       {R}  {MG}{account['name']}{R}")
        print(f"  {GN}│{R}  {D}ingame_id  {R}  {WH}{account['ingame_id']}{R}")
        print(f"  {GN}│{R}  {D}region     {R}  {CY}{account['region']}{R}")
        print(f"  {GN}│{R}  {D}open_id    {R}  {GR}{account['open_id']}{R}")
        print(f"  {GN}│{R}  {D}pass       {R}  {GR}{account['pass']}{R}")
        print(f"  {GN}│{R}  {D}time       {R}  {GR}{elapsed:.2f}s{R}")
        print(f"  {GN}{B}└──────────────────────────────────────────────────────────┘{R}")
        print()


def create_one_account(index, total, cfg, custom_name=None):
    tag = _tag(index, total)
    t0 = time.time()
    time.sleep(random.uniform(0.05, 0.5))

    try:
        device_id = "02-" + str(uuid.uuid4())
        uid = guest_register(tag, device_id)

        tokens = guest_token(tag, uid, device_id)
        open_id      = tokens["open_id"]
        access_token = tokens["access_token"]
        platform     = int(tokens.get("platform", tokens.get("main_active_platform", 4)) or 4)

        if custom_name:
            nickname = decorate_name(custom_name)
            ok(tag, f"name     {MG}{nickname}{R}")
        else:
            nickname = generate_nickname(tag, open_id, cfg)

        major_register(tag, open_id, access_token, nickname, cfg)

        login = major_login(tag, open_id, access_token, cfg, platform, region=REGION)

        payload  = decode_jwt_payload(login["jwt"]) if login.get("jwt") else {}
        lock_reg = (payload.get("lock_region") or "").upper()

        if lock_reg != REGION:
            info(tag, f"lock     {D}current{R}={YL}{lock_reg or '—'}{R} → requesting {MG}{REGION}{R}")
            confirmed = choose_region(tag, login["jwt"], cfg, REGION)
            cfg_r = {**cfg, "country_code": confirmed, "region": confirmed}
            login = major_login(tag, open_id, access_token, cfg_r, platform, region=confirmed)
            confirmed_region = confirmed
        else:
            confirmed_region = lock_reg
            cfg_r = cfg

        ld = get_login_data(tag, open_id, access_token, cfg_r, platform, login["jwt"])

        account = {
            "uid":           uid,
            "pass":          PASSWORD,
            "name":          nickname,
            "ingame_id":     login.get("account_id"),
            "region":        ld.get("region") or confirmed_region or REGION,
            "open_id":       open_id,
            "access_token":  access_token,
            "refresh_token": tokens.get("refresh_token"),
            "jwt":           login.get("jwt"),
            "game_server":   ld.get("game_server"),
            "chat_server":   ld.get("chat_server"),
            "session_key":   (ld.get("session") or {}).get("key"),
            "session_nonce": (ld.get("session") or {}).get("nonce"),
            "created_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        append_account(account)

        global _success_count
        with _count_lock:
            _success_count += 1
            done = _success_count

        print_account_block(done, total, account, time.time() - t0)
        return account

    except Exception as e:
        global _failure_count
        with _count_lock:
            _failure_count += 1
            done = _failure_count
        fail(tag, f"{RD}FAILED{R} ({done}/{total}) {D}{e}{R}")
        return None


def banner():
    region_display = REGION if REGION else "—"
    lang_display   = LANG_CODE if LANG_CODE else "—"
    server_display = SERVER_URL if SERVER_URL else "—"
    client_display = CLIENT_URL if CLIENT_URL else "—"
    lines = [
        f"{RD}{B}╔══════════════════════════════════════════════════════════╗{R}",
        f"{RD}{B}║{R}  {WH}{B}FREE  FIRE{R}  {GR}·{R}  {RD}{B}GUEST  CREATOR  ·  ALL  REGIONS{R}        {RD}{B}║{R}",
        f"{RD}{B}╠══════════════════════════════════════════════════════════╣{R}",
        f"{RD}{B}║{R}  {D}region{R}  {CY}{region_display:<10}{R}  {D}lang{R}  {CY}{lang_display:<10}{R}                  {RD}{B}║{R}",
        f"{RD}{B}║{R}  {D}server{R}  {GR}{server_display[:42]:<42}{R}      {RD}{B}║{R}",
        f"{RD}{B}║{R}  {D}client{R}  {GR}{client_display[:42]:<42}{R}      {RD}{B}║{R}",
        f"{RD}{B}╚══════════════════════════════════════════════════════════╝{R}",
    ]
    print()
    for l in lines:
        print(l)
    print()


def ask_region():
    print(f"  {CY}?{R} {B}Choose region:{R}")
    cols = 3
    for i, r in enumerate(REGION_LIST, 1):
        marker = f"{GN}●{R}" if r == "IND" else f"{GR}○{R}"
        cell = f"  {marker} {D}{i:>2}.{R} {WH}{r:<8}{R}"
        if i % cols == 0:
            print(cell)
        else:
            print(cell, end="")
    if len(REGION_LIST) % cols != 0:
        print()
    while True:
        try:
            raw = input(f"  {CY}›{R} ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if not raw:
            return REGION_LIST[0]
        if raw in REGION_LIST:
            return raw
        if raw.isdigit() and 1 <= int(raw) <= len(REGION_LIST):
            return REGION_LIST[int(raw) - 1]
        print(f"  {YL}·{R} invalid, try again")


def ask_count():
    while True:
        try:
            raw = input(f"  {CY}?{R} {B}How many accounts to create?{R} ").strip()
            n = int(raw)
            if n <= 0:
                print(f"  {YL}·{R} enter a positive number")
                continue
            return n
        except ValueError:
            print(f"  {YL}·{R} enter a number")
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)


def ask_name():
    try:
        raw = input(f"  {CY}?{R} {B}Name prefix{R} {D}(blank = auto-generate){R}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return raw


def print_startup_summary(count, custom_name, cfg):
    print()
    print(f"  {GR}─────────────────────────────────────────────────────────{R}")
    print(f"  {D}target{R}      {WH}{count}{R}   {D}region{R}  {CY}{REGION}{R}")
    if custom_name:
        print(f"  {D}name{R}        {YL}custom{R}  {GR}('{custom_name}' → decorated){R}")
    else:
        print(f"  {D}name{R}        {YL}auto{R}  {GR}(server GenerateNickname){R}")
    print(f"  {D}OB{R}          {CY}{cfg.get('latest_release_version')}{R}   "
          f"{D}remote{R}  {CY}{cfg.get('remote_version')}{R}")
    print(f"  {D}cdn{R}         {GR}{cfg.get('cdn_url')}{R}")
    print(f"  {D}sign{R}        {GR}{cfg.get('vercfg_sign')}{R}")
    print(f"  {D}pacing{R}      {GR}{MIN_REGISTER_INTERVAL:.1f}s between register calls{R}")
    print(f"  {GR}─────────────────────────────────────────────────────────{R}")
    print()


def print_final_summary():
    elapsed = time.time() - _start_time
    rate = _success_count / elapsed * 60 if elapsed > 0 else 0
    print()
    print(f"  {GN}{B}╔══════════════════════════════════════════════════════════╗{R}")
    print(f"  {GN}{B}║{R}  {WH}{B}DONE{R}  {GR}·{R}  {CY}{REGION}{R}                                            {GN}{B}║{R}")
    print(f"  {GN}{B}╠══════════════════════════════════════════════════════════╣{R}")
    print(f"  {GN}{B}║{R}  {D}created{R}   {GN}{_success_count:<10}{R}  "
          f"{D}failed{R}   {RD}{_failure_count:<10}{R}                 {GN}{B}║{R}")
    print(f"  {GN}{B}║{R}  {D}elapsed{R}   {WH}{elapsed:>6.1f}s{R}      "
          f"{D}rate{R}     {CY}{rate:>5.1f}/min{R}                  {GN}{B}║{R}")
    print(f"  {GN}{B}║{R}  {D}saved{R}     {GR}{os.path.abspath(ACCOUNT_FILE)[:42]:<42}{R}     {GN}{B}║{R}")
    print(f"  {GN}{B}╚══════════════════════════════════════════════════════════╝{R}")
    print()


def main():
    global _total_target, CFG, _start_time
    global REGION, LANG_CODE, SERVER_URL, CLIENT_URL, ACCOUNT_FILE

    banner()
    REGION    = ask_region()
    LANG_CODE = REGION_LANG.get(REGION, "en")
    group     = REGION_GROUP.get(REGION, "OTHERS")
    SERVER_URL = REGION_URLS[group]["server"]
    CLIENT_URL = REGION_URLS[group]["client"]
    ACCOUNT_FILE = ACCOUNT_FILE_TEMPLATE.format(region=REGION)

    print()
    print(f"  {GN}✔{R} region {WH}{REGION}{R}  {GR}·{R}  lang {CY}{LANG_CODE}{R}  "
          f"{GR}·{R}  group {MG}{group}{R}")

    count       = ask_count()
    custom_name = ask_name()
    _total_target = count

    print(f"\n  {GR}·{R} fetching OB config…")
    pv = get_play_store_version()
    info("main", f"playstore version = {pv}")
    CFG = fetch_ver_config(pv)
    ok("main", f"ver.php {D}OB{R}={CY}{CFG['latest_release_version']}{R}  "
               f"{D}remote{R}={CY}{CFG['remote_version']}{R}  "
               f"{D}cdn{R}={GR}{CFG['cdn_url']}{R}")

    print_startup_summary(count, custom_name, CFG)

    _start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(create_one_account, i, count, CFG, custom_name)
                   for i in range(1, count + 1)]
        for _ in as_completed(futures):
            pass

    print_final_summary()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n  {YL}interrupted{R}")
        print_final_summary()
        sys.exit(0)