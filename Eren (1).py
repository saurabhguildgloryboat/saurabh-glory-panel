# eren.py — 1 master + 3 slaves; reads accounts from squad_accounts.json
import asyncio, socket, struct, time, json, os, uuid, random
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from protobuf_decoder.protobuf_decoder import Parser

import app
from Config import Play_Version, Ob_VeR

REGION = "IND"
LANG   = "hi"

ACCOUNTS_FILE         = "squad_accounts.json"   # written by gen.py
TOTAL_ACCOUNTS        = 4                       # 1 master + 3 slaves
SETTLE_AFTER_ALL_JOIN = 1.5

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

UDP_LOG_FILE = "udp_logs.txt"
_LOGIN_LOCK = asyncio.Lock()

AUTH_AES_KEY = bytes([0x19, 0x47, 0xB9, 0x74, 0xD9, 0x73, 0xF3, 0x7F,
                      0x42, 0x06, 0x01, 0x38, 0x42, 0x00, 0x10, 0x30])
AUTH_AES_IV  = bytes([0x28, 0x7F, 0xCA, 0x7A, 0xF9, 0x67, 0xF3, 0x7A,
                      0x65, 0x02, 0x01, 0x10, 0x40, 0x40, 0x00, 0x30])
AUTH_CMD     = 0x65
AUTH_REGION  = 0x15


# ─────────── xDL helpers (inlined) ───────────
Key, Iv = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56]), \
          bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])


async def EnC_AEs(HeX):
    cipher = AES.new(Key, AES.MODE_CBC, Iv)
    return cipher.encrypt(pad(bytes.fromhex(HeX), AES.block_size)).hex()


async def DEc_AEs(HeX):
    cipher = AES.new(Key, AES.MODE_CBC, Iv)
    return unpad(cipher.decrypt(bytes.fromhex(HeX)), AES.block_size).hex()


async def EnC_PacKeT(HeX, K, V):
    return AES.new(K, AES.MODE_CBC, V).encrypt(pad(bytes.fromhex(HeX), 16)).hex()


async def DEc_PacKeT(HeX, K, V):
    return unpad(AES.new(K, AES.MODE_CBC, V).decrypt(bytes.fromhex(HeX)), 16).hex()


async def EnC_Uid(H, Tp):
    e, H = [], int(H)
    while H:
        e.append((H & 0x7F) | (0x80 if H > 0x7F else 0)); H >>= 7
    return bytes(e).hex() if Tp == 'Uid' else None


async def EnC_Vr(N):
    if N < 0: ''
    H = []
    while True:
        BesTo = N & 0x7F; N >>= 7
        if N: BesTo |= 0x80
        H.append(BesTo)
        if not N: break
    return bytes(H)


def DEc_Uid(H):
    n = s = 0
    for b in bytes.fromhex(H):
        n |= (b & 0x7F) << s
        if not b & 0x80: break
        s += 7
    return n


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
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    nested = await CrEaTe_ProTo(item)
                    packet.extend(await CrEaTe_LenGTh(field, nested))
                elif isinstance(item, int):
                    packet.extend(await CrEaTe_VarianT(field, item))
                elif isinstance(item, (str, bytes)):
                    packet.extend(await CrEaTe_LenGTh(field, item))
        elif isinstance(value, dict):
            nested_packet = await CrEaTe_ProTo(value)
            packet.extend(await CrEaTe_LenGTh(field, nested_packet))
        elif isinstance(value, int):
            packet.extend(await CrEaTe_VarianT(field, value))
        elif isinstance(value, (str, bytes)):
            packet.extend(await CrEaTe_LenGTh(field, value))
    return packet


async def DecodE_HeX(H):
    R = hex(H)
    F = str(R)[2:]
    if len(F) == 1:
        F = "0" + F
        return F
    else:
        return F


async def Fix_PackEt(parsed_results):
    result_dict = {}
    for result in parsed_results:
        wt = result.wire_type
        if wt == "varint":
            value = result.data
        elif wt == "string":
            value = result.data
        elif wt == "bytes":
            v = result.data
            value = v.hex() if isinstance(v, (bytes, bytearray)) else v
        elif wt == "length_delimited":
            try:
                value = await Fix_PackEt(result.data.results)
            except Exception:
                value = str(result.data)
        else:
            value = result.data
        result_dict[str(result.field)] = value
    return result_dict


async def DeCode_PackEt(input_text):
    try:
        parsed_results = Parser().parse(input_text)
        return await Fix_PackEt(parsed_results)
    except Exception as e:
        print(f"[decode error] {e}")
        return None


async def GeneRaTePk(Pk, N, K, V):
    PkEnc = await EnC_PacKeT(Pk, K, V)
    _ = await DecodE_HeX(int(len(PkEnc) // 2))
    if len(_) == 2: HeadEr = N + "000000"
    elif len(_) == 3: HeadEr = N + "00000"
    elif len(_) == 4: HeadEr = N + "0000"
    elif len(_) == 5: HeadEr = N + "000"
    else: print('ErroR => GeneRatinG ThE PacKeT !! ')
    return bytes.fromhex(HeadEr + _ + PkEnc)


def _udp_log(line):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    try:
        with open(UDP_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception: pass

def udp_log_print(line):
    print(line); _udp_log(line)


def _auth_region_byte(region):
    reg = str(region or "IND").upper()
    if reg == "IND": return 0x14
    if reg == "BD":  return 0x19
    if reg == "ME":  return 0x15
    return 0x15


def build_auth_datagram(token, account_id):
    payload = token.encode("utf-8") if isinstance(token, str) else token
    p = 16 - (len(payload) % 16)
    data = AES.new(AUTH_AES_KEY, AES.MODE_CBC, AUTH_AES_IV).encrypt(
        payload + bytes([p]) * p)
    out = bytearray()
    out.append(AUTH_CMD & 0xFF)
    out.append(_auth_region_byte(REGION) & 0xFF)
    out += struct.pack(">Q", int(account_id) & 0xFFFFFFFFFFFFFFFF)
    out += struct.pack(">I", int(time.time()) & 0xFFFFFFFF)
    out += struct.pack(">i", len(data))
    out += data
    return bytes(out)


PROTOCOL = {0:"NONE",1:"INIT",2:"HEARTBEAT",3:"MATCHMAKING",4:"STATS",5:"GROUP",
            6:"FRIEND",7:"MAIL",8:"INVENTORY",9:"BACKPACK",10:"ACTIVITY",11:"ACCOUNT",
            12:"CLAN",13:"PROFILE",14:"ROOM",15:"PRESENCE",16:"ELITEPASS",
            17:"RECONNECTION",18:"CHANNEL",19:"STORE",21:"PET",22:"MANUAL",
            23:"CHAMPIONSHIP",24:"ANTIADDICTION",25:"FRESH",26:"LINKAGE",27:"ATTENDANCE",
            28:"LIMITEDEVENT",29:"FFANTI",30:"CHAT",31:"CUP",32:"VIPCARD",34:"CREDITSCORE",
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
STATS_CMD = {0:"NONE",1:"MATCHSTATS_NTF",2:"UPDATEMMR_NTF"}
CMD_TABLES = {3:MATCHMAKING_CMD,4:STATS_CMD,5:GROUP_CMD}

UDP_CMD = {1:"UDP_HELLO",2:"UDP_ACK",3:"UDP_PING",4:"UDP_BYEBYE",5:"UDP_LONGTIMENOSEE",
           6:"MUDP_CONNECT_ACK",100:"RUDP_JOIN_MATCH",101:"RUDP_PLAYER_JOIN",
           102:"RUDP_PLAYER_QUIT",103:"RUDP_MATCH_END",110:"RUDP_BATTLE_START",
           116:"RUDP_SYNC_SCENE_INFO",130:"RUDP_JOIN_MATCH_FINISHED",
           447:"RUDP_JOIN_MATCH_PREPARE",448:"RUDP_JOIN_MATCH_POST"}

def describe(ptype, cmd):
    p = PROTOCOL.get(ptype, f"UNKNOWN_{ptype}")
    if isinstance(cmd, int):
        return f"{p}/{CMD_TABLES.get(ptype, {}).get(cmd, f'CMD_{cmd}')}"
    return p

def udp_cmd_name(cmd): return UDP_CMD.get(cmd, f"CMD_{cmd}")

def _to_bytes(v):
    if isinstance(v, bytes): return v
    if isinstance(v, str):
        try: return bytes.fromhex(v)
        except ValueError: return v.encode()
    if v is None: raise ValueError("cannot convert None")
    return bytes(v)

def _rbyte(region):
    reg = str(region or "IND").upper()
    return 0x14 if reg == "IND" else (0x19 if reg == "BD" else 0x15)

async def _frame(op, region, proto, key, iv):
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(proto, 16))
    return bytes([op, _rbyte(region)]) + len(enc).to_bytes(4, "big") + enc

def _idc_entries():
    reg = REGION.upper()
    return [{1:"IDC1",2:75,3:reg}, {1:"IDC2",2:123,3:reg}]


# ─────────── TCP packets ───────────
async def OpEnSq(K, V, region, remote_version):
    fields = {
        1: 1,
        2: {
            2: b"\x01",
            3: 1,
            4: 3,
            5: "en",
            8: _idc_entries(),
            9: 2,
            10: bytes.fromhex("01090a0b12191a202729"),
            11: 1,
            13: 1,
            14: {2: 5756, 6: 11, 8: remote_version, 9: 2, 10: 4},
            19: 329,
            21: "374f521955",
            24: [
                {1: 3, 2: 360},
                {1: 4, 2: 391},
                {1: 5, 2: 156},
                {1: 29, 2: 204},
                {1: 22, 2: 118},
                {1: 14, 2: 139},
                {1: 21},
            ],
            30: ("https://dl-ind-production.freefiremobile.com/"
                 "2832022628717E276054_7104117490_107_1767713981_0"),
        },
    }
    packet = "0514" if region.lower() == "ind" else ("0519" if region.lower() == "bd" else "0515")
    return await GeneRaTePk((await CrEaTe_ProTo(fields)).hex(), packet, K, V)


async def invite_pkt(invitee_id, secret, key, iv):
    inner = {1: int(invitee_id), 2: REGION, 4: 1}
    if secret is not None:
        inner[5] = str(secret)
    fields = {1: 2, 2: inner}
    proto = await CrEaTe_ProTo(fields)
    pkt = "0514" if REGION.lower() == "ind" else ("0519" if REGION.lower() == "bd" else "0515")
    return await GeneRaTePk(proto.hex(), pkt, key, iv)


async def DeViLAccepted(uid, code, key, iv, remote_version):
    fields = {
        1: 4,
        2: {
            1: int(uid),
            3: int(uid),
            4: bytes.fromhex("010708090a0b0c120d0f131618191a202326224d242729"),
            8: 1,
            9: {2: 5756, 6: 11, 8: remote_version, 9: 2, 10: 4},
            10: str(code),
            11: {1: "IDC3", 2: 118, 3: "IND"},
            13: "en",
            16: "374f5219",
            20: {1: 21},
            27: {1: 2, 2: 8},
        },
    }
    return await GeneRaTePk((await CrEaTe_ProTo(fields)).hex(), "0514", key, iv)


async def start_squad_pkt(group_id, key, iv):
    fields = {1: 9, 2: {1: int(group_id), 7: _idc_entries()}}
    proto = await CrEaTe_ProTo(fields)
    pkt = "0514" if REGION.lower() == "ind" else ("0519" if REGION.lower() == "bd" else "0515")
    return await GeneRaTePk(proto.hex(), pkt, key, iv)


async def build_auth_packet(account_id, token, server_time, key, iv, region=REGION, typ="OnLine"):
    uid_hex = f"{int(account_id):016x}"; ts_hex = f"{int(server_time):08x}"
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(token.encode(), 16)).hex()
    enc_len = f"{len(enc) // 2:08x}"
    reg = str(region).upper()
    if reg == "BD":     pre_on, pre_chat = "7119", "9219"
    elif reg == "IND":  pre_on, pre_chat = "7114", "9214"
    else:               pre_on, pre_chat = "7115", "9215"
    if typ == "OnLine":
        return bytes.fromhex(pre_on + uid_hex + ts_hex + "00000000" + enc_len + enc)
    return bytes.fromhex(pre_chat + uid_hex + ts_hex + enc_len + enc)


async def send_keep_alive(region=REGION):
    reg = str(region).upper()
    return bytes.fromhex("0214" if reg == "IND" else ("0219" if reg == "BD" else "0215"))


# ─────────── UDP crypto ───────────
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
    93,98,107,112,121,
])
_DELTA = 0x9E3779B9; _ROUNDS = 16
_FIELD_SIZES = {0:1, 1:2, 2:2, 3:1, 4:2}
_FIELD_NAMES = {0:"sendOption", 1:"cmd", 2:"orderId", 3:"flags", 4:"length"}

def optimize_udp_socket(sock):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
    except Exception: pass

async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

async def has_ssan_zig(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF; out = bytearray()
    while z >= 0x80: out.append((z & 0x7F) | 0x80); z >>= 7
    out.append(z); return bytes(out)

async def uleb_encode(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)

async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^ ((v1 + s) & 0xFFFFFFFF) ^ (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^ ((v0 + s) & 0xFFFFFFFF) ^ (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1

async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^ ((v0 + s) & 0xFFFFFFFF) ^ (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^ ((v1 + s) & 0xFFFFFFFF) ^ (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

async def tea_cbc_encrypt(padded, key_bytes):
    k0,k1,k2,k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0,4,8,12))
    out = bytearray(len(padded))
    prev_cipher = bytearray(8); prev_intermediate = bytearray(8)
    for i in range(0, len(padded), 8):
        xored = bytearray(8)
        for j in range(8): xored[j] = padded[i+j] ^ prev_cipher[j]
        e0, e1 = await tea_enc(struct.unpack_from("<I", xored, 0)[0],
                               struct.unpack_from("<I", xored, 4)[0], k0,k1,k2,k3)
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0); struct.pack_into("<I", enc, 4, e1)
        for j in range(8): out[i+j] = enc[j] ^ prev_intermediate[j]
        prev_cipher[:] = out[i:i+8]; prev_intermediate[:] = xored
        if i % 64 == 0: await asyncio.sleep(0)
    return bytes(out)

async def tea_cbc_decrypt(body, key_bytes):
    k0,k1,k2,k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0,4,8,12))
    out = bytearray(len(body))
    prev_intermediate = bytearray(8); prev_cipher = bytearray(8)
    xored = bytearray(8); dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8): xored[j] = body[i+j] ^ prev_intermediate[j]
        d0, d1 = await tea_dec(struct.unpack_from("<I", xored, 0)[0],
                               struct.unpack_from("<I", xored, 4)[0], k0,k1,k2,k3)
        struct.pack_into("<I", dec, 0, d0); struct.pack_into("<I", dec, 4, d1)
        for j in range(8): out[i+j] = dec[j] ^ prev_cipher[j]
        prev_cipher[:] = body[i:i+8]; prev_intermediate[:] = dec
        if i % 64 == 0: await asyncio.sleep(0)
    return bytes(out)

async def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7

async def oicq_unpad(padded):
    if not padded or len(padded) < 8: return None
    if not all(padded[-1-i] == 0 for i in range(7)): return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len; e = len(padded) - 7
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
    try:
        ru = [int(c) for c in s]
    except ValueError:
        ru = [0, 1, 2, 3, 4]
    if sorted(ru) != [0, 1, 2, 3, 4]:
        ru = [0, 1, 2, 3, 4]
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
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")[:25]
    content = len(data).to_bytes(4, "little") + data + b"\x00" * 9
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    layout = [int(c) for c in str(layout).strip()]
    enc_body = await tea_cbc_encrypt(await build_padded(content), key)
    header_bytes = await encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    packet = bytearray([0x63, 0x00]) + header_bytes + enc_body
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet).hex()


# ─────────── ported join-body encoders ───────────
HDR_RELIABLE = 10
UDP_HEAD_AND_ENCRY_SIZE = 40
MTU_LIMIT = 1300
_SALT_LEN, _ZERO_LEN = 2, 7

def _tea_encrypt_len(n):
    t = 1 + _SALT_LEN + n + _ZERO_LEN
    r = t % 8
    return t + (8 - r if r else 0)

def _dg_size(token_len, reliable=True):
    zv = bytearray()
    _put_zigvarint(zv, token_len)
    body = len(zv) + token_len
    return (HDR_RELIABLE if reliable else 8) + _tea_encrypt_len(body)

def _zig(v):
    return (v << 1) ^ (v >> 63)

def _put_varint(out, v):
    while v >= 0x80:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)

def _put_zigvarint(out, v):
    _put_varint(out, _zig(v))

def _put_string(out, s):
    raw = s.encode("utf-8") if isinstance(s, str) else s
    _put_zigvarint(out, len(raw))
    out += raw

def split_token_bytes(token_bytes):
    n = len(token_bytes)
    raw = int(n * 0.85)
    p1 = raw - (raw % 40)
    while UDP_HEAD_AND_ENCRY_SIZE + _dg_size(p1) > MTU_LIMIT and p1 > 40:
        p1 -= 40
    return token_bytes[:p1], token_bytes[p1:]

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
    _put_varint(b, int(account_id))
    _put_varint(b, room)
    b.append(1)
    b.append(int(game_mode) & 0xFF)
    _put_varint(b, room)
    b.append(int(map_id) & 0xFF)
    b.append(0)
    _put_varint(b, 0)
    _put_varint(b, 0)
    b.append(0)
    b.append(int(is_emulator) & 0xFF)
    b.append(0)
    b.append(1)
    b.append(2)
    b.append(3)
    b.append(int(enable_antihack_tick) & 0xFF)
    b.append(1)
    _put_string(b, country)
    _put_varint(b, 0)
    b.append(1)
    b.append(2)
    b.append(0)
    b.append(1)
    b.append(0)
    b.append(0)
    b.append(4)
    _put_string(b, client_version)
    _put_string(b, client_version_code)
    _put_string(b, client_url)
    b.append(0)
    b.append(0)
    _put_varint(b, int(friend_count))
    b.append(0)
    _put_varint(b, int(drift_bottle_owner_id))
    _put_string(b, drift_bottle_owner_name or "")
    b.append(1)
    _put_string(b, "")
    _put_string(b, "")
    b.append(0)
    _put_varint(b, 0)
    _put_varint(b, 0)
    b.append(0)
    b.append(0)
    b.append(0)
    _put_varint(b, 0)
    _put_string(b, "")
    _put_varint(b, 0)
    b.append(0)
    b.append(1)
    b.append(0)
    b.append(0)
    _put_varint(b, 0)
    _put_varint(b, 0)
    b.append(0)
    b.append(1)
    _put_string(b, "")
    _put_varint(b, 0)
    b.append(0)
    b.append(0)
    b.append(0)
    b.append(int(match_mode) & 0xFF)
    b.append(0)
    _put_varint(b, int(session_tag))
    b.append(2)
    b.append(0)
    _put_string(b, client_ip or "")
    _put_string(b, client_fingerprint or "")
    return bytes(b)

def build_join_post_body(account_id, token_part2, **kw):
    body = bytearray()
    body += build_join_info_head(account_id, **kw)
    _put_string(body, token_part2)
    return bytes(body)


async def build_join_match_startup(join_token, udp_key, match_code, account_id, block_val,
                                   server_ip="", region="BD",
                                   client_version="1.132.9",
                                   client_version_code="2019121229",
                                   access_token="",
                                   match_id=0, country="IN",
                                   map_id=1, game_mode=15, match_mode=1):
    join_token = join_token.strip()
    udp_key_b = bytes.fromhex(udp_key)
    match_code = [int(c) for c in str(match_code).strip()]
    enc_token = join_token.encode("utf-8") if isinstance(join_token, str) else join_token

    part1, part2 = split_token_bytes(enc_token)

    prepare_body = bytearray()
    _put_string(prepare_body, part1)
    prepare_pkt = (await build_packet(0x5E, match_code, 2, 447, 0, 1,
                                      bytes(prepare_body), udp_key_b)).hex()

    post_body = build_join_post_body(
        account_id, part2,
        game_mode=game_mode, match_mode=match_mode, map_id=map_id,
        country=country,
        client_version=client_version,
        client_version_code=client_version_code,
        match_id=int(match_id or block_val),
        client_ip=server_ip.split(":")[0] if server_ip else "",
    )
    post_pkt = await build_packet(0x5A, match_code, 2, 448, 1, 1, post_body, udp_key_b)
    return [prepare_pkt], post_pkt.hex()


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

async def send_anti_afk_movement(sock, server_addr, udp_key_b, match_code, account_id):
    try:
        nr = (await layouts_from_mask(match_code))[1]
        rx = random.randint(-100,100); ry = random.randint(-50,50); rz = random.randint(-100,100)
        ts = int(time.time()*1000) & 0xFFFFFFFF
        body = struct.pack("<IIIiiiH", int(account_id) & 0xFFFFFFFF, ts, rx, ry, rz, 1)
        pkt = await build_packet(0x6B, nr, 0, 2001, None, 0, body, udp_key_b, encrypted=False)
        await asyncio.get_event_loop().sock_sendto(sock, pkt, server_addr)
    except Exception: pass

async def anti_afk_loop(sock, server_addr, udp_key_b, match_code, account_id, stop_event):
    while not stop_event.is_set():
        try:
            await send_anti_afk_movement(sock, server_addr, udp_key_b, match_code, account_id)
            try: await asyncio.wait_for(stop_event.wait(), timeout=3.0)
            except asyncio.TimeoutError: pass
        except Exception: await asyncio.sleep(0.5)

async def play_game(server_ip_port, prepare_packets, post_packet, udp_key, match_code,
                    account_id, player_region, client_version, tag="[?]",
                    account_jwt="", sleep_ms=0):
    match_start = time.time()
    ping_task = afk_task = hello_task = sock = None
    ping_stop = asyncio.Event(); afk_stop = asyncio.Event()
    try:
        ip, port = server_ip_port.split(":"); port = int(port)
        resolved_ip = socket.gethostbyname(ip)
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        optimize_udp_socket(sock); sock.setblocking(False)
        udp_key_b = bytes.fromhex(udp_key)
        gap = sleep_ms / 1000.0 if sleep_ms else 0.02

        if account_jwt:
            auth_pkt = build_auth_datagram(account_jwt, account_id)
            await loop.sock_sendto(sock, auth_pkt, (resolved_ip, port))
            udp_log_print(f"{tag} auth   raw AES datagram sent ({len(auth_pkt)}B)")

        hello_hex = await build_hello_packet(f"{account_id}_2585", udp_key_b, match_code)
        hello_bytes = bytes.fromhex(hello_hex)
        await loop.sock_sendto(sock, hello_bytes, (resolved_ip, port))
        udp_log_print(f"{tag} UDP connected  remote={resolved_ip}:{port}")

        ack_state = "waiting_for_hello_reply"
        startup_sent = False; local_closed = False
        send_lock = asyncio.Lock()
        nr = (await layouts_from_mask(match_code))[1]

        async def ka_loop():
            pklist = [0x66,0x6D,0x69,0x6C,0x6B,0x6E,0x6F,0x70]; i = 0
            while not ping_stop.is_set():
                if ack_state != "waiting_for_hello_reply": break
                try: await asyncio.wait_for(ping_stop.wait(), timeout=0.1)
                except asyncio.TimeoutError: pass
            while not ping_stop.is_set():
                pk = pklist[i % len(pklist)]
                cnt = int(time.time()*1000) & 0xFFFFFFFF
                pkt = await build_packet(pk, nr, 0, 3, None, 0,
                                         cnt.to_bytes(4,"little") + b"\x00\x00\x00",
                                         udp_key_b, encrypted=False)
                try: await loop.sock_sendto(sock, pkt, (resolved_ip, port))
                except Exception: pass
                i += 1
                try: await asyncio.wait_for(ping_stop.wait(), timeout=3.0)
                except asyncio.TimeoutError: pass

        async def hello_retry_loop():
            for _ in range(8):
                if ping_stop.is_set() or ack_state != "waiting_for_hello_reply":
                    return
                try: await asyncio.wait_for(ping_stop.wait(), timeout=0.8)
                except asyncio.TimeoutError: pass
                if ping_stop.is_set() or ack_state != "waiting_for_hello_reply":
                    return
                try:
                    await loop.sock_sendto(sock, hello_bytes, (resolved_ip, port))
                    udp_log_print(f"{tag}   HELLO retry")
                except Exception:
                    pass

        ping_task = asyncio.create_task(ka_loop())
        hello_task = asyncio.create_task(hello_retry_loop())
        afk_task = asyncio.create_task(anti_afk_loop(sock, (resolved_ip, port),
                                                     udp_key_b, match_code, account_id, afk_stop))
        last_activity = time.time()

        async def send_join_match():
            nonlocal ack_state, startup_sent
            if startup_sent: return
            async with send_lock:
                if startup_sent: return
                for p in prepare_packets:
                    await loop.sock_sendto(sock, bytes.fromhex(p), (resolved_ip, port))
                    await asyncio.sleep(gap)
                await asyncio.sleep(gap)
                await loop.sock_sendto(sock, bytes.fromhex(post_packet), (resolved_ip, port))
                startup_sent = True
                ack_state = "startup_sent"
                udp_log_print(f"{tag} → PREPARE×{len(prepare_packets)}+POST sent")

        while not local_closed:
            if time.time() - match_start > 700: break
            try:
                resp, sa = await asyncio.wait_for(loop.sock_recvfrom(sock, 65535), timeout=1.5)
                if resp:
                    last_activity = time.time()
                    frame = await decode_packet(resp, udp_key_b, match_code)
                    if frame:
                        cmd = frame.get('cmd'); oid = frame.get('orderId')
                        msg_key = frame.get('msgKey', 0)
                        udp_log_print(f"{tag} ← cmd={cmd}({udp_cmd_name(cmd)}) "
                                      f"oid={oid} len={len(resp)}")

                        if msg_key < 100 and oid is not None:
                            da = await build_packet(0x68, nr, 0, 2, None, 1,
                                                    ((oid + 1) & 0xFFFF).to_bytes(2, "little"),
                                                    udp_key_b)
                            await loop.sock_sendto(sock, da, sa)

                        if cmd == 1:
                            if ack_state == "waiting_for_hello_reply":
                                ack_state = "ready_to_send_startup"
                                udp_log_print(f"{tag}   HELLO reply received → ready")

                        elif cmd == 3:
                            c = frame.get("content") or b""
                            cnt = c[:4] if len(c) >= 4 else c
                            rp = await build_packet(0x6D, nr, 0, 3, None, 0,
                                                    cnt + b"\x00\x00\x00", udp_key_b,
                                                    encrypted=False)
                            await loop.sock_sendto(sock, rp, sa)

                        elif cmd == 100:
                            body = frame.get("content")
                            if body:
                                udp_log_print(f"{tag}   JOIN_MATCH body len={len(body)} "
                                              f"hex={body.hex()[:200]}")
                            udp_log_print(f"{tag}   JOIN_MATCH received (acked)")

                        elif cmd == 130:
                            udp_log_print(f"{tag}   JOIN_MATCH_FINISHED ✅ — in game!")

                        elif cmd == 103:
                            udp_log_print(f"{tag}   MATCH_END"); local_closed = True

            except asyncio.TimeoutError:
                pass
            except Exception as e:
                udp_log_print(f"{tag} UDP err: {e}"); await asyncio.sleep(0.5)

            if ack_state == "ready_to_send_startup" and not startup_sent:
                await send_join_match()
            elif ack_state == "startup_sent" and (time.time() - last_activity) > 30:
                break

    except Exception as e:
        udp_log_print(f"{tag} UDP err: {e}")
    finally:
        ping_stop.set(); afk_stop.set()
        if ping_task: ping_task.cancel()
        if hello_task: hello_task.cancel()
        if afk_task: afk_task.cancel()
        if sock:
            try: sock.close()
            except Exception: pass
        udp_log_print(f"{tag} UDP closed")


# ─────────── region setup ───────────
def setup_app_region():
    app.REGION = REGION; app.LANG_CODE = LANG
    app.ACCOUNT_FILE = f"{REGION}_Account.json"
    grp = app.REGION_GROUP[REGION]
    app.SERVER_URL = app.REGION_URLS[grp]["server"]
    app.CLIENT_URL = app.REGION_URLS[grp]["client"]


# ─────────── load accounts from gen.py's file ───────────
def load_generated_accounts(path=ACCOUNTS_FILE):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        out = []
        for rec in data:
            if not isinstance(rec, dict):
                continue
            if not rec.get("uid") or not rec.get("open_id") or not rec.get("access_token"):
                continue
            out.append(rec)
        return out
    except Exception as e:
        print(f"[!] failed to read {path}: {e}")
        return []


async def login_new_account(rec, cfg, tag, max_retries=6):
    open_id      = rec["open_id"]
    access_token = rec["access_token"]
    platform     = int(rec.get("platform", 4) or 4)

    login = None; last_err = None
    async with _LOGIN_LOCK:
        for attempt in range(1, max_retries + 1):
            try:
                login = await asyncio.to_thread(app.major_login, tag, open_id,
                                                access_token, cfg, platform, REGION)
                break
            except Exception as e:
                last_err = e
                wait = min(2.0 * attempt, 15.0)
                print(f"{tag} major_login retry {attempt}/{max_retries} "
                      f"after {wait:.1f}s ({e})")
                await asyncio.sleep(wait)
        if login is None:
            raise RuntimeError(f"{tag} major_login gave up: {last_err}")

    payload = app.decode_jwt_payload(login["jwt"]) if login.get("jwt") else {}
    lock_reg = (payload.get("lock_region") or "").upper()
    cfg_use = cfg
    if lock_reg != REGION:
        confirmed = await asyncio.to_thread(app.choose_region, tag, login["jwt"], cfg, REGION)
        cfg_use = {**cfg, "country_code": confirmed, "region": confirmed}
        login = await asyncio.to_thread(app.major_login, tag, open_id,
                                        access_token, cfg_use, platform, confirmed)

    ld = await asyncio.to_thread(app.get_login_data, tag, open_id, access_token,
                                 cfg_use, platform, login["jwt"])
    fields = login["fields"]
    ts      = app.first_value(fields, 21, "varint")
    key_raw = app.first_value(fields, 22, "bytes") or app.first_value(fields, 22, "string")
    iv_raw  = app.first_value(fields, 23, "bytes") or app.first_value(fields, 23, "string")
    if ts is None or key_raw is None or iv_raw is None:
        raise RuntimeError(f"{tag} missing key/iv/ts")
    print(f"{tag} login ok id={login['account_id']} online={ld['game_server']}")
    return {
        "tag": tag, "uid": rec["uid"], "ingame_id": login["account_id"],
        "open_id": open_id, "access_token": access_token, "jwt": login["jwt"],
        "key": _to_bytes(key_raw), "iv": _to_bytes(iv_raw), "ts": ts,
        "game_server": ld["game_server"], "chat_server": ld["chat_server"],
        "server_url": login.get("game_url"), "name": rec.get("name", "?"),
        "cfg": cfg_use,
    }


def collect_all_ints(obj, out):
    if isinstance(obj, dict):
        if "data" in obj and isinstance(obj["data"], int):
            out.add(obj["data"])
        for v in obj.values():
            collect_all_ints(v, out)
    elif isinstance(obj, list):
        for x in obj:
            collect_all_ints(x, out)
    elif isinstance(obj, int):
        out.add(obj)


# ─────────── Slave ───────────
async def slave_loop(acct, holder, match_infos, stop_evt):
    tag = acct["tag"]
    ip, port = acct["game_server"].split(":")
    key, iv = acct["key"], acct["iv"]
    jwt = acct["jwt"]; ingame_id = int(acct["ingame_id"]); ts = acct["ts"]
    auth_online = await build_auth_packet(ingame_id, jwt, ts, key, iv, REGION, "OnLine")
    ka_bytes = await send_keep_alive(REGION)
    remote_version = acct["cfg"].get("remote_version", Play_Version)

    while not stop_evt.is_set():
        try:
            reader, writer = await asyncio.open_connection(ip, int(port))
            writer.write(auth_online); await writer.drain()
            writer.write(ka_bytes); await writer.drain()
            print(f"{tag} ONLINE auth sent  id={ingame_id}")

            ka_stop = asyncio.Event()
            async def ka_loop():
                while not ka_stop.is_set():
                    try:
                        await asyncio.sleep(15)
                        writer.write(ka_bytes); await writer.drain()
                    except Exception: return
            ka_task = asyncio.create_task(ka_loop())

            print(f"{tag} waiting for master's squad code…")
            while not stop_evt.is_set():
                if holder.get("code") and holder.get("group_id"):
                    break
                try: await asyncio.wait_for(stop_evt.wait(), timeout=0.5)
                except asyncio.TimeoutError: pass

            if stop_evt.is_set(): return

            cached_gid  = int(holder["group_id"])
            cached_code = holder["code"]

            async def send_accept():
                acc = await DeViLAccepted(cached_gid, cached_code, key, iv, remote_version)
                writer.write(acc); await writer.drain()
                print(f"{tag} 📡 ACCEPT sent  group_id={cached_gid}  code={cached_code!r}")

            await send_accept()

            buf = bytearray()
            while not stop_evt.is_set():
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=30)
                except asyncio.TimeoutError: continue
                except Exception: break
                if not chunk: break
                buf.extend(chunk)
                while len(buf) >= 5:
                    ptype = buf[0]; plen = int.from_bytes(buf[1:5], "big")
                    if plen > 100_000 or len(buf) < 5 + plen: break
                    payload = bytes(buf[5:5+plen]); del buf[:5+plen]
                    decoded = None
                    try:
                        decoded = await DeCode_PackEt(payload.hex())
                    except Exception: pass
                    cmd = decoded.get("4") if isinstance(decoded, dict) else None
                    print(f"{tag}  ↳ {describe(ptype, cmd)}  len={plen}")

                    if ptype == 0x05 and isinstance(decoded, dict):
                        if cmd == 13:
                            print(f"{tag} ⚠ DISMISS_NTF — group destroyed")
                        elif cmd == 10:
                            print(f"{tag} ✅ START_NTF")

                    if ptype == 0x03 and isinstance(decoded, dict) and cmd == 5:
                        r5 = decoded.get("5") or {}
                        if isinstance(r5, dict) and r5.get("2") and r5.get("3") and r5.get("4") and r5.get("42"):
                            if tag not in match_infos:
                                match_infos[tag] = r5
                                print(f"{tag} ⚡ MATCHMAKINGSUSS — server={r5['2']} "
                                      f"match_id={r5.get('1')}")

            ka_stop.set(); ka_task.cancel()
            writer.close()
            try: await writer.wait_closed()
            except Exception: pass
            if stop_evt.is_set(): break
        except Exception as e:
            print(f"{tag} conn err: {e}"); await asyncio.sleep(2.0)


# ─────────── Master ───────────
async def master_loop(acct, slave_ids, holder, match_infos):
    tag = acct["tag"]
    ip, port = acct["game_server"].split(":")
    key, iv = acct["key"], acct["iv"]
    jwt = acct["jwt"]; ingame_id = int(acct["ingame_id"]); ts = acct["ts"]
    slave_set = {int(x) for x in slave_ids}
    remote_version = acct["cfg"].get("remote_version", Play_Version)

    auth_online = await build_auth_packet(ingame_id, jwt, ts, key, iv, REGION, "OnLine")
    ka_bytes = await send_keep_alive(REGION)

    reader, writer = await asyncio.open_connection(ip, int(port))
    writer.write(auth_online); await writer.drain()
    writer.write(ka_bytes); await writer.drain()
    print(f"{tag} ONLINE auth sent  id={ingame_id}")

    ka_stop = asyncio.Event()
    async def ka_loop():
        while not ka_stop.is_set():
            try:
                await asyncio.sleep(15)
                writer.write(ka_bytes); await writer.drain()
            except Exception: return
    ka_task = asyncio.create_task(ka_loop())

    await asyncio.sleep(1.0)
    c = await OpEnSq(key, iv, REGION, remote_version)
    writer.write(c); await writer.drain()
    print(f"{tag} 📡 OPEN SQUAD sent ({len(c)}B)")

    created = started = invited = False
    joined = set(); group_id = None
    buf = bytearray()

    try:
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(65536), timeout=30)
            except asyncio.TimeoutError: continue
            except Exception as e:
                print(f"{tag} read err: {e}"); break
            if not chunk: break
            buf.extend(chunk)
            while len(buf) >= 5:
                ptype = buf[0]; plen = int.from_bytes(buf[1:5], "big")
                if plen > 100_000 or len(buf) < 5 + plen: break
                payload = bytes(buf[5:5+plen]); del buf[:5+plen]
                decoded = None
                try:
                    decoded = await DeCode_PackEt(payload.hex())
                except Exception as e:
                    print(f"{tag}  [decode error] {e}")
                cmd = decoded.get("4") if isinstance(decoded, dict) else None
                print(f"{tag}  ↳ {describe(ptype, cmd)}  len={plen}")

                if ptype == 0x05 and isinstance(decoded, dict):
                    data = decoded.get("5", {})

                    if cmd == 1 and not created:
                        gid = data.get("1") if isinstance(data, dict) else None
                        if isinstance(gid, dict): gid = gid.get("data")
                        code = data.get("14") if isinstance(data, dict) else None
                        if isinstance(code, dict): code = code.get("data")
                        secret = data.get("31") if isinstance(data, dict) else None
                        if isinstance(secret, dict): secret = secret.get("data")
                        if not secret: secret = code

                        if gid:
                            created = True
                            group_id = int(gid)
                            print(f"{tag} ✅ CREATE_NTF group_id={group_id}  "
                                  f"code={code!r}  secret={secret!r}")
                            holder["group_id"] = group_id
                            holder["code"] = code

                            for sid in slave_ids:
                                inv = await invite_pkt(int(sid), secret, key, iv)
                                writer.write(inv); await writer.drain()
                                print(f"{tag} 📨 INVITE → {sid}")
                                await asyncio.sleep(0.5)
                            invited = True

                    elif cmd == 6 and invited:
                        found = set()
                        collect_all_ints(decoded, found)
                        new_joins = found & slave_set

                        if new_joins:
                            joined |= new_joins
                            print(f"{tag} ✅ JOIN_NTF  seen={sorted(new_joins)}  "
                                  f"({len(joined)}/{len(slave_ids)})")

                        if joined == slave_set and not started:
                            started = True
                            await asyncio.sleep(SETTLE_AFTER_ALL_JOIN)
                            s = await start_squad_pkt(group_id, key, iv)
                            writer.write(s); await writer.drain()
                            print(f"{tag} 📡 START sent ({len(s)}B) — all "
                                  f"{len(slave_ids)} members joined")

                    elif cmd == 8 and created:
                        leave_set = set()
                        collect_all_ints(decoded, leave_set)
                        kicked = leave_set & slave_set
                        if kicked:
                            print(f"{tag} 🔁 LEAVE_NTF seen={sorted(kicked)} — "
                                  f"removing from joined")
                            joined -= kicked
                            started = False

                    elif cmd == 10:
                        print(f"{tag} ✅ START_NTF")

                    elif cmd == 13:
                        print(f"{tag} ⚠ DISMISS_NTF — group destroyed")

                    elif cmd == 56:
                        print(f"{tag} ⚠ MIGRATE_GROUP_NTF")

                elif ptype == 0x03 and isinstance(decoded, dict) and cmd == 5:
                    r5 = decoded.get("5") or {}
                    if isinstance(r5, dict) and r5.get("2") and r5.get("3") and r5.get("4") and r5.get("42"):
                        if tag not in match_infos:
                            match_infos[tag] = r5
                            print(f"{tag} ⚡ MATCHMAKINGSUSS — server={r5['2']} "
                                  f"match_id={r5.get('1')}")
    finally:
        ka_stop.set(); ka_task.cancel()
        writer.close()
        try: await writer.wait_closed()
        except Exception: pass


# ─────────── MAIN ───────────
async def main():
    try:
        with open(UDP_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(f"# UDP log — run at {datetime.now().isoformat()}\n")
    except Exception: pass

    setup_app_region()
    cfg = dict(HARDCODED_CONFIG)

    raw_records = load_generated_accounts()
    if len(raw_records) < TOTAL_ACCOUNTS:
        print(f"[!] {ACCOUNTS_FILE} has {len(raw_records)} accounts, "
              f"need {TOTAL_ACCOUNTS}. Run gen.py first.")
        return
    records = raw_records[:TOTAL_ACCOUNTS]

    print(f"[*] using {len(records)} account(s) from {ACCOUNTS_FILE}")

    accounts = []
    for i, rec in enumerate(records):
        tag = "[M]" if i == 0 else f"[S{i}]"
        try:
            acct = await login_new_account(rec, cfg, tag)
            accounts.append(acct)
        except Exception as e:
            print(f"{tag} login failed: {e}")
            return
        await asyncio.sleep(1.5)

    master = accounts[0]
    slaves = accounts[1:]
    slave_ids = [int(s["ingame_id"]) for s in slaves]

    print()
    print(f"[*] master [M] id={master['ingame_id']} name={master['name']}")
    for s in slaves:
        print(f"[*] slave  {s['tag']} id={s['ingame_id']} name={s['name']}")
    print()

    holder = {"group_id": None, "code": None}
    match_infos = {}
    slave_stop = asyncio.Event()

    slave_tasks = [asyncio.create_task(slave_loop(s, holder, match_infos, slave_stop)) for s in slaves]
    await asyncio.sleep(2.0)
    master_task = asyncio.create_task(master_loop(master, slave_ids, holder, match_infos))

    expected_tags = [a["tag"] for a in accounts]
    print(f"[*] waiting for MATCHMAKINGSUSS from {expected_tags} …")
    deadline = time.time() + 120
    while time.time() < deadline:
        if all(t in match_infos for t in expected_tags):
            break
        await asyncio.sleep(0.5)

    missing = [t for t in expected_tags if t not in match_infos]
    if missing:
        print(f"[!] no match info for {missing} — aborting")
        slave_stop.set()
        for t in slave_tasks + [master_task]: t.cancel()
        return

    udp_tasks = []
    for a in accounts:
        r5 = match_infos[a["tag"]]
        server_ip_port = r5["2"]
        udp_key        = r5["3"]
        join_token     = r5["4"]
        match_code     = r5["42"]
        real_match_id  = r5.get("1") or 0
        real_map_id    = r5.get("6") or 1
        real_game_mode = r5.get("7") or 15
        real_match_mode = r5.get("8") or 1
        real_sleep_ms  = r5.get("5") or 0

        print(f"[+] {a['tag']} MATCH server={server_ip_port} code={match_code} "
              f"match_id={real_match_id} mode={real_game_mode} map={real_map_id}")

        prepare_packets, post_packet = await build_join_match_startup(
            join_token, udp_key, match_code,
            int(a["ingame_id"]), real_match_id,
            server_ip=server_ip_port, region=REGION,
            client_version=a["cfg"].get("remote_version", Play_Version),
            client_version_code="2019121229",
            access_token=a["access_token"],
            match_id=real_match_id,
            country="IN",
            map_id=real_map_id,
            game_mode=real_game_mode,
            match_mode=real_match_mode,
        )
        udp_tasks.append(asyncio.create_task(play_game(
            server_ip_port, prepare_packets, post_packet, udp_key, match_code,
            int(a["ingame_id"]), REGION,
            a["cfg"].get("remote_version", Play_Version),
            tag=a["tag"],
            account_jwt=join_token,
            sleep_ms=real_sleep_ms,
        )))

    tcp_tasks = slave_tasks + [master_task]
    try:
        await asyncio.gather(*udp_tasks, *tcp_tasks)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        slave_stop.set()
        for t in tcp_tasks: t.cancel()
        await asyncio.gather(*tcp_tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\ninterrupted")