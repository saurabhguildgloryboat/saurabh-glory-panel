import random, requests, json, aiohttp, asyncio, urllib3, ssl, binascii, datetime, re, traceback as tb
from datetime import datetime
from Crypto.Cipher import AES
from protobuf_decoder.protobuf_decoder import Parser
from Crypto.Util.Padding import pad, unpad
from ffproto import get_freefire_update_info

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
Key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
Iv  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])


def FreeFireVer():
    play_url = "https://play.google.com/store/apps/details?id=com.dts.freefireth&hl=ar&gl=DZ"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36")
    }
    response = requests.get(play_url, headers=headers)
    response.raise_for_status()
    html = response.text
    versions = re.findall(r"\b(1\.\d{1,3}\.\d{1,3})\b", html)
    if not versions:
        raise Exception("No version found in Play Store page")
    PlayStoRe_VerSiOn = versions[-1]
    ob_url = (f"https://version.ggwhitehawk.com/live/ver.php"
              f"?version={PlayStoRe_VerSiOn}"
              f"&lang=en&device=android&channel=3rd_party"
              f"&appstore=thirdparty&region=IND"
              f"&whitelist_version=1.7.0&whitelist_sp_version=1.0.0"
              f"&device_name=vivo%20V2538"
              f"&device_CPU=ARM64%20FP%20ASIMD%20AES"
              f"&device_GPU=Adreno%20%28TM%29%20722"
              f"&device_mem=7282")
    ob_response = requests.get(ob_url)
    ob_response.raise_for_status()
    ob_data = ob_response.json()
    if ob_data.get("code") == 0:
        PlayStoRe_VerSiOn = ob_data.get("remote_version")
    Ob_VerSiOn = ob_data.get("latest_release_version")
    lOgIn_UrL = ob_data.get("server_url")
    return lOgIn_UrL, Ob_VerSiOn, PlayStoRe_VerSiOn


lOgIn_UrL, Ob_VerSion, PlayStoRe_VerSioN = FreeFireVer()
print(f"LoGin UrL : {lOgIn_UrL} \nOb VerSiOn : {Ob_VerSion} \nClienT VerSioN : {PlayStoRe_VerSioN}")


async def Ua():
    versions = ['4.0.18P6', '4.0.19P7', '4.0.20P1', '4.1.0P3', '4.1.5P2', '4.2.1P8',
                '4.2.3P1', '5.0.1B2', '5.0.2P4', '5.1.0P1', '5.2.0B1', '5.2.5P3',
                '5.3.0B1', '5.3.2P2', '5.4.0P1', '5.4.3B2', '5.5.0P1', '5.5.2P3']
    models = ['SM-A125F', 'SM-A225F', 'SM-A325M', 'SM-A515F', 'SM-A725F', 'SM-M215F', 'SM-M325FV',
              'Redmi 9A', 'Redmi 9C', 'POCO M3', 'POCO M4 Pro', 'RMX2185', 'RMX3085',
              'moto g(9) play', 'CPH2239', 'V2027', 'OnePlus Nord', 'ASUS_Z01QD']
    android_versions = ['9', '10', '11', '12', '13', '14']
    languages = ['en-US', 'es-MX', 'pt-BR', 'id-ID', 'ru-RU', 'hi-IN']
    countries = ['USA', 'MEX', 'BRA', 'IDN', 'RUS', 'IND']
    return (f"GarenaMSDK/{random.choice(versions)}({random.choice(models)};"
            f"Android {random.choice(android_versions)};"
            f"{random.choice(languages)};{random.choice(countries)};)")


async def GeNeRaTeAccEss(uid, password):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    headers = {
        "Host": "100067.connect.garena.com",
        "User-Agent": (await Ua()),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "close"}
    data = {
        "uid": uid, "password": password,
        "response_type": "token", "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as response:
                if response.status != 200:
                    print(f"❌ Token request failed with status {response.status}")
                    try:
                        print(f"❌ Error response: {(await response.text())[:100]}")
                    except Exception:
                        pass
                    return None, None, None
                response_data = await response.json()
                open_id = response_data.get("open_id")
                access_token = response_data.get("access_token")
                platform = response_data.get("platform")
                if open_id and access_token:
                    return open_id, access_token, platform
                print(f"❌ Missing open_id or access_token in response")
                print(f"Response data: {response_data}")
                return None, None, None
    except Exception as e:
        print(f"❌ Network error getting token: {e}")
        tb.print_exc()
        return None, None, None


PLATFORM_NAMES = {
    0: "Guest", 1: "Garena", 3: "GarenaFacebook", 4: "GarenaGuest",
    5: "VK", 7: "GarenaHuawei", 8: "GarenaGoogle", 10: "GarenaApple",
    11: "GarenaTwitter",
}


async def EnC_Vr(N):
    if N < 0: return b''
    H = []
    while True:
        BesTo = N & 0x7F
        N >>= 7
        if N: BesTo |= 0x80
        H.append(BesTo)
        if not N: break
    return bytes(H)


async def CrEaTe_VarianT(field_number, value):
    field_header = (field_number << 3) | 0
    return await EnC_Vr(field_header) + await EnC_Vr(value)


async def CrEaTe_LenGTh(field_number, value):
    field_header = (field_number << 3) | 2
    encoded_value = value.encode() if isinstance(value, str) else value
    return await EnC_Vr(field_header) + await EnC_Vr(len(encoded_value)) + encoded_value


async def CrEaTe_ProTo(fields):
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(value, dict):
            nested_packet = await CrEaTe_ProTo(value)
            packet.extend(await CrEaTe_LenGTh(field, nested_packet))
        elif isinstance(value, int):
            packet.extend(await CrEaTe_VarianT(field, value))
        elif isinstance(value, (str, bytes)):
            packet.extend(await CrEaTe_LenGTh(field, value))
    return packet


async def encrypted_proto(encoded_hex):
    key = b'Yg&tc%DEuh6%Zc^8'
    iv = b'6oyZDr22E3ychjM%'
    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded_message = pad(bytes(encoded_hex), AES.block_size)
    return cipher.encrypt(padded_message)


async def Fix_PackEt_by_redzed(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {'wire_type': result.wire_type}
        if result.wire_type == "varint":
            field_data['data'] = result.data
        if result.wire_type == "string":
            field_data['data'] = result.data
        if result.wire_type == "bytes":
            field_data['data'] = result.data
        elif result.wire_type == 'length_delimited':
            field_data["data"] = await Fix_PackEt_by_redzed(result.data.results)
        result_dict[result.field] = field_data
    return result_dict


async def DeCode_PackEt(input_text):
    try:
        parsed_results = Parser().parse(input_text)
        parsed_results_dict = await Fix_PackEt_by_redzed(parsed_results)
        return json.dumps(parsed_results_dict)
    except Exception as e:
        print(f"error {e}")
        return None


async def EncryptMajorLoginManual(open_id: str, access_token: str, platform):
    region_code = "TW"
    fields = {
        1: open_id, 2: access_token,
        3: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        4: "free fire", 5: platform,
        7: PlayStoRe_VerSioN,
        8: "Android OS 13 / API-33 (TKQ1.221114.001/V14.0.7.0.TGEINXM)",
        9: "Handheld", 10: "Vi India", 11: "CarrierDataNetwork",
        12: 1650, 13: 720, 14: "320",
        15: "ARM64 FP ASIMD AES | 4800 | 8",
        16: 5652, 17: "Adreno (TM) 610",
        18: "OpenGL ES 3.2 V@0502.41 (GIT@43fc279f3a, I58833f8ed4, 1679659134) (Date:03/24/23)",
        19: "Google|c6c902a0-850c-4758-a75f-67851f122f07",
        20: "42.111.9.117", 21: "en", 22: open_id,
        23: str(platform), 24: "Handheld", 25: "Xiaomi 220333QBI",
        26: region_code, 29: access_token, 30: 1,
        41: "Vi India", 42: "4G",
        57: "7428b253defc164018c604a1ebbfebdf",
        60: 104713, 61: 45770, 62: 1309, 64: 45898, 65: 104713,
        66: 45898, 67: 104713, 73: 1,
        74: "/data/app/pFI9snPRb2TQRYoVb_zUMw==/com.dts.freefireth-43iCx1eWjkGkTkiDOKADZw==/lib/arm64",
        76: 1,
        77: "4c322aeb56444feaa151d1ea91a8f7f2|/data/app/pFI9snPRb2TQRYoVb_zUMw==/com.dts.freefireth-43iCx1eWjkGkTkiDOKADZw==/base.apk",
        78: 3, 79: 2, 81: "64", 83: "2019120776", 86: "OpenGLES2",
        87: 4095, 88: platform, 90: "Delhi", 91: "DL", 92: 6634,
        93: "android",
        94: "KqsHTwzBFanKbszglbFUUq6Kg5bccOrAkw1T6p8/RYB6/n1HQUQFiphekC0qve4ke3BiymNfrMhLuCrlgstRYpspkHs=",
        95: 111207,
        96: '{"cur_rate":null,"support_etc2":false}',
        97: 1, 99: str(platform), 100: str(platform),
        102: "4b004346025b0f0632", 103: 1,
    }
    serialized = await CrEaTe_ProTo(fields)
    return await encrypted_proto(serialized)


async def MajorLogin(payload):
    url = f"https://loginbp.ppmainecoonghj.com/MajorLogin"
    Hr = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-Ga-Sv": "1789534056",
        "Authorization": "Bearer ",
        "X-Ga": "v1 1",
        "ReleaseVersion": Ob_VerSion,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
        "Connection": "Keep-Alive",
        "Expect": "100-continue",
    }
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload, headers=Hr, ssl=ssl_context) as response:
            if response.status != 200:
                body = await response.read()
                print(f"❌ MajorLogin HTTP {response.status}: {body[:200]!r}")
                return None
            body = await response.read()
            if len(body) > 64:
                body = body[64:]
            return body


# =========================================================
#                    NEW: RequestJoinClan
# =========================================================

async def SendRequestJoinClan(base_url, jwt, clan_id, region):
    """
    Sends the RequestJoinClan packet to {base_url}/RequestJoinClan
    Body (protobuf): { 1: clan_id }  -> AES-CBC encrypted (same as MajorLogin)
    """
    url = f"{base_url}/RequestJoinClan"

    # Build protobuf body: field 1 = clan_id
    proto_body = await CrEaTe_ProTo({1: int(clan_id)})
    payload = await encrypted_proto(proto_body)

    headers = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-Ga-Sv": "1789534056",
        "Authorization": f"Bearer {jwt}",
        "X-Ga": "v1 1",
        "ReleaseVersion": Ob_VerSion,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
        "Connection": "Keep-Alive",
        "Expect": "100-continue",
        "X-Region": region,
    }

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload, headers=headers, ssl=ssl_context) as response:
            resp = await response.read()
            if len(resp) > 64:
                resp = resp[64:]
            return response.status, resp


async def ProcessAccount(account, clan_id, idx, total):
    tag = account.get("name") or account.get("uid")
    print(f"\n[{idx}/{total}] 👤 {tag} (uid={account.get('uid')})")

    try:
        open_id = account["open_id"]
        access_token = account["access_token"]
        platform = account["platform"]
    except KeyError as e:
        print(f"  ❌ Missing field in json: {e}")
        return

    # -------- 1. MajorLogin --------
    try:
        login_req = await EncryptMajorLoginManual(open_id, access_token, platform)
        login_resp = await MajorLogin(login_req)
    except Exception as e:
        print(f"  ❌ MajorLogin exception: {e}")
        return

    if not login_resp:
        print("  ❌ MajorLogin empty response")
        return

    decoded = await DeCode_PackEt(binascii.hexlify(login_resp).decode())
    if not decoded:
        print("  ❌ Failed to decode MajorLogin response")
        return

    try:
        data = json.loads(decoded)
    except Exception:
        print("  ❌ Invalid json from decode")
        return

    if "13" in data:
        print("  🚫 Account is BANNED — skipping")
        return

    if "8" not in data or "10" not in data:
        print(f"  ❌ Missing jwt/url in response: {list(data.keys())}")
        return

    jwt = data["8"]["data"]
    base_url = data["10"]["data"]
    region = data.get("25", {}).get("data", {}).get("1", {}).get("data", "IND")
    print(f"  ✅ Login ok — region={region}")

    # -------- 2. RequestJoinClan --------
    try:
        status, resp = await SendRequestJoinClan(base_url, jwt, clan_id, region)
    except Exception as e:
        print(f"  ❌ JoinClan exception: {e}")
        return

    print(f"  📤 HTTP {status}")
    if resp:
        hex_resp = binascii.hexlify(resp).decode()
        parsed = await DeCode_PackEt(hex_resp)
        print(f"  📥 Response: {parsed}")
    else:
        print("  ✅ Empty response (usually = success)")


async def main():
    with open("squad_accounts.json", "r", encoding="utf-8") as f:
        accounts = json.load(f)

    clan_id = input("Enter Clan ID: ").strip()
    if not clan_id.isdigit():
        print("❌ Clan ID must be numeric")
        return

    print(f"🔎 Sending RequestJoinClan for {len(accounts)} account(s) → clan {clan_id}\n")

    # Run all accounts concurrently (remove gather → for loop if you want sequential)
    await asyncio.gather(*[
        ProcessAccount(acc, clan_id, i, len(accounts))
        for i, acc in enumerate(accounts, 1)
    ])


if __name__ == "__main__":
    asyncio.run(main())