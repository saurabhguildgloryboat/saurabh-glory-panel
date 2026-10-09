import requests , re , json
Uid = "8009458532"
Password = "B4C932E05745CDCF4632C4926FE921D26591E8E847E7BF7BAC8822231DA8BCB9"
Play_Version = "1.132.1"
Ob_VeR = "OB55"
LoGiN_UrL = "https://loginbp.ppmainecoonghj.com/"
DEV_SUFFIX = "2609"
Protocol = {
    0: "Proto_NONE",
    1: "INIT",
    2: "HEARTBEAT",
    3: "MATCHMAKING",
    4: "STATS",
    5: "GROUP",
    6: "FRIEND",
    7: "MAIL",
    8: "INVENTORY",
    9: "BACKPACK",
    10: "ACTIVITY",
    11: "ACCOUNT",
    12: "CLAN",
    13: "PROFILE",
    14: "ROOM",
    15: "PRESENCE",
    16: "ELITEPASS",
    17: "RECONNECTION",
    18: "CHANNEL",
    19: "STORE",
    21: "PET",
    22: "MANUAL",
    23: "CHAMPIONSHIP",
    24: "ANTIADDICTION",
    25: "FRESH",
    26: "LINKAGE",
    27: "ATTENDANCE",
    28: "LIMITEDEVENT",
    29: "FFANTI",
    30: "CHAT",
    31: "CUP",
    32: "VIPCARD",
    34: "CREDITSCORE",
    35: "GAMESERVERMANAGER",
    36: "MINIGAME",
    37: "WORKSHOP",
    38: "CUSTOMEVENT",
    39: "ACHIEVEMENT",
    40: "GIN",
    41: "WEAPONPOWER",
    42: "CSRANKINGMATCH",
    43: "BRRANKINGMATCH",
    44: "OCCUPATION",
    45: "MODESTATS",
    46: "HIPPOINVENTORY",
    47: "PRIME",
    48: "TEAMTOPUP",
    49: "RELAYMART",
    50: "REMATCH",
    51: "GOOGLE_PLAY",
    52: "LBS",
    53: "SHAREDGACHA",
    54: "ESPORTS",
    55: "SOCIALHALL",
    101: "INITRANDOMMIN",
    150: "INITRANDOMMAX",
    151: "HEARTBEATRANDOMMIN",
    255: "HEARTBEATRANDOMMAX"
}

def get_freefire_update_info():
    url = f"https://play.google.com/store/apps/details?id=com.dts.freefireth&hl=ar&gl=DZ"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    html = response.text
    versions = re.findall(r"\b(1\.\d{1,3}\.\d{1,3})\b", html)
    
    if not versions:
        raise Exception("No version found in Play Store page")
    playstore_version = versions[-1]
    return playstore_version
    
def GeT_OB(PlAy_VerSioN):
    UrL = f"https://version.ggwhitehawk.com/live/ver.php?version={PlAy_VerSioN}&lang=en&device=android&channel=3rd_party&appstore=thirdparty&region=IND&whitelist_version=1.7.0&whitelist_sp_version=1.0.0&device_name=vivo%20V2538&device_CPU=ARM64%20FP%20ASIMD%20AES&device_GPU=Adreno%20%28TM%29%20722&device_mem=7282"
    ReSp = requests.get(UrL)
    ReSp = ReSp.json()
    OB_VeRsIon = ReSp.get("latest_release_version")
    LogIn_UrL = ReSp.get("server_url")
    print(json.dumps(ReSp , indent=1))
    return OB_VeRsIon , LogIn_UrL

if __name__ == "__main__":
    PlAy_VeR = get_freefire_update_info()
    Ob_VeR , LoGiN_UrL = GeT_OB(PlAy_VeR)
    print(f"PlAy_VeR: {PlAy_VeR}, Ob_VeR: {Ob_VeR}, LoGiN_UrL: {LoGiN_UrL}")
    if PlAy_VeR:
        with open(__file__, "r") as f:
            lines = f.readlines()
        with open(__file__, "w") as f:
            for line in lines:              
                if line.lstrip().startswith("Play_Version ="):
                    f.write(f'Play_Version = "{PlAy_VeR}"\n')
                elif line.lstrip().startswith("Ob_VeR ="):
                    f.write(f'Ob_VeR = "{Ob_VeR}"\n')
                elif line.lstrip().startswith("LoGiN_UrL ="):
                    f.write(f'LoGiN_UrL = "{LoGiN_UrL}"\n')
                else:
                    f.write(line)
        print("✅ Version updated.")
    else:
        print("No changes.")