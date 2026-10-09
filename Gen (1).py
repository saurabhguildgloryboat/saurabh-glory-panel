# gen.py — generate fresh Free Fire accounts and save them for eren.py to use
import asyncio, json, os, time, uuid
from datetime import datetime

import app

REGION = "IND"
LANG   = "hi"

ACCOUNTS_FILE = "squad_accounts.json"

HARDCODED_CONFIG = {
    "latest_release_version": "OB55",
    "remote_version":         "1.132.9",
    "cdn_url":                "https://dl-ind-production.freefiremobile.com/",
    "abhotupdate_cdn_url":    "https://dl-ind-production.freefiremobile.com/",
    "client_ip":              "49.15.84.6",
    "vercfg_sign":            "c8e41b7a93f02d56e1a94c7b8203f5d1",
    "region":                 REGION, "lang": LANG, "country_code": REGION,
    "server_url":             "https://loginbp.ggpolarbear.com/",
    "client_url":             "https://client.ind.freefiremobile.com/",
}


def _load_existing():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(accounts):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)


def _setup_region():
    app.REGION = REGION
    app.LANG_CODE = LANG
    app.ACCOUNT_FILE = f"{REGION}_Account.json"
    grp = app.REGION_GROUP[REGION]
    app.SERVER_URL = app.REGION_URLS[grp]["server"]
    app.CLIENT_URL = app.REGION_URLS[grp]["client"]


async def generate_one(cfg, tag):
    device_id = "02-" + str(uuid.uuid4())
    uid = await asyncio.to_thread(app.guest_register, tag, device_id)
    tokens = await asyncio.to_thread(app.guest_token, tag, uid, device_id)
    open_id      = tokens["open_id"]
    access_token = tokens["access_token"]
    platform     = int(tokens.get("platform", 4) or 4)
    nickname = await asyncio.to_thread(app.generate_nickname, tag, open_id, cfg)
    await asyncio.to_thread(app.major_register, tag, open_id, access_token, nickname, cfg)
    return {
        "uid":          uid,
        "pass":         app.PASSWORD,
        "name":         nickname,
        "open_id":      open_id,
        "access_token": access_token,
        "platform":     platform,
        "region":       REGION,
        "created_at":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


async def main():
    _setup_region()
    cfg = dict(HARDCODED_CONFIG)

    existing = _load_existing()
    print(f"[*] {ACCOUNTS_FILE} currently has {len(existing)} account(s)")

    try:
        raw = input("[?] How many fresh accounts to generate? ").strip()
        count = int(raw)
        if count <= 0:
            print("[!] must be positive")
            return
    except (ValueError, EOFError, KeyboardInterrupt):
        print("\n[!] cancelled")
        return

    print(f"[*] generating {count} account(s)…")
    accounts = list(existing)
    ok_count = 0
    for i in range(count):
        tag = f"[G{i+1:02d}]"
        try:
            acc = await generate_one(cfg, tag)
            accounts.append(acc)
            _save(accounts)
            ok_count += 1
            print(f"{tag} ✔ uid={acc['uid']}  name={acc['name']}")
        except Exception as e:
            print(f"{tag} ✘ failed: {e}")
        await asyncio.sleep(0.5)

    print()
    print(f"[+] done: {ok_count}/{count} new account(s) created")
    print(f"[+] total in {ACCOUNTS_FILE}: {len(accounts)}")
    for a in accounts:
        print(f"      uid={a['uid']:<12} name={a.get('name', '?')}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\ninterrupted")