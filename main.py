import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import json
import os
from dotenv import load_dotenv
from io import BytesIO
from datetime import datetime, timedelta

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

GUILD_ID = 1510681614919794868
GUILD = discord.Object(id=GUILD_ID)

DATA_FILE = "/data/furina_maro_fishing.json"
os.makedirs("/data", exist_ok=True)


class NormalizedDict(dict):
    """디스코드 ID가 int/string으로 섞여도 같은 키로 처리하는 딕셔너리."""
    def _key(self, key):
        return str(key)

    def __contains__(self, key):
        return super().__contains__(self._key(key))

    def __getitem__(self, key):
        return super().__getitem__(self._key(key))

    def __setitem__(self, key, value):
        super().__setitem__(self._key(key), value)

    def get(self, key, default=None):
        return super().get(self._key(key), default)

    def setdefault(self, key, default=None):
        return super().setdefault(self._key(key), default)

    def pop(self, key, default=None):
        return super().pop(self._key(key), default)


money_data = NormalizedDict()
fish_tanks = NormalizedDict()
fish_dex = NormalizedDict()
item_bags = NormalizedDict()
chest_pity = NormalizedDict()
gacha_pity = NormalizedDict()

owned_rods = NormalizedDict()
equipped_rods = NormalizedDict()
owned_baits = NormalizedDict()
equipped_baits = NormalizedDict()

fish_market = {}
last_market_update = None
fishing_cooldowns = {}


def _serialize_save(obj):
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"{type(obj)} is not JSON serializable")


def _restore_datetime(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def load_maro():
    global money_data
    global fish_tanks, fish_dex, item_bags, chest_pity, gacha_pity
    global owned_rods, equipped_rods, owned_baits, equipped_baits
    global fish_market, last_market_update, fishing_cooldowns

    if not os.path.exists(DATA_FILE):
        save_data()
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        loaded = json.load(f)

    money_data = NormalizedDict({
        str(k): int(v)
        for k, v in loaded.get("money_data", {}).items()
    })

    fish_tanks = NormalizedDict(loaded.get("fish_tanks", {}))

    fish_dex = NormalizedDict()
    for uid, value in loaded.get("fish_dex", {}).items():
        fish_dex[uid] = set(value) if isinstance(value, list) else set()

    item_bags = NormalizedDict(loaded.get("item_bags", {}))
    chest_pity = NormalizedDict({
        str(k): int(v)
        for k, v in loaded.get("chest_pity", {}).items()
    })
    gacha_pity = NormalizedDict({
        str(k): int(v)
        for k, v in loaded.get("gacha_pity", {}).items()
    })

    owned_rods = NormalizedDict(loaded.get("owned_rods", {}))
    equipped_rods = NormalizedDict(loaded.get("equipped_rods", {}))
    owned_baits = NormalizedDict(loaded.get("owned_baits", {}))
    equipped_baits = NormalizedDict(loaded.get("equipped_baits", {}))

    fish_market = loaded.get("fish_market", {})
    last_market_update = _restore_datetime(loaded.get("last_market_update"))

    fishing_cooldowns = {}
    for uid, value in loaded.get("fishing_cooldowns", {}).items():
        fishing_cooldowns[str(uid)] = _restore_datetime(value)


def save_data():
    payload = {
        "money_data": dict(globals().get("money_data", {})),
        "fish_tanks": dict(globals().get("fish_tanks", {})),
        "fish_dex": dict(globals().get("fish_dex", {})),
        "item_bags": dict(globals().get("item_bags", {})),
        "chest_pity": dict(globals().get("chest_pity", {})),
        "gacha_pity": dict(globals().get("gacha_pity", {})),
        "owned_rods": dict(globals().get("owned_rods", {})),
        "equipped_rods": dict(globals().get("equipped_rods", {})),
        "owned_baits": dict(globals().get("owned_baits", {})),
        "equipped_baits": dict(globals().get("equipped_baits", {})),
        "fish_market": globals().get("fish_market", {}),
        "last_market_update": globals().get("last_market_update", None),
        "fishing_cooldowns": globals().get("fishing_cooldowns", {}),
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4, default=_serialize_save)


def get_wallet(user_id):
    uid = str(user_id)

    if uid not in money_data:
        money_data[uid] = 0
        save_data()

    return money_data[uid]


def add_maro(user_id, amount):
    uid = str(user_id)
    get_wallet(uid)
    money_data[uid] += int(amount)
    save_data()


def remove_maro(user_id, amount):
    uid = str(user_id)
    get_wallet(uid)

    if money_data[uid] < amount:
        return False

    money_data[uid] -= int(amount)
    save_data()
    return True


def money(amount):
    return f"{int(amount):,}원"


def get_item_display_name(item, fallback="알 수 없음"):
    if not isinstance(item, dict):
        return fallback
    return item.get("display_name") or item.get("name") or fallback


load_maro()

# =========================
# 낚시 시스템
# =========================

FISH_TRAIT_CHANCE = 50

FISH_DATA = {

    # ===== 쓰레기 =====

    "젖은 종이": {
        "min_kg": 0.05,
        "max_kg": 0.2,
        "habitat": "강",
        "base_price": 5,
        "kg_price": 1,
        "chance": 15
    },

    "비닐봉지": {
        "min_kg": 0.05,
        "max_kg": 0.3,
        "habitat": "물 위",
        "base_price": 10,
        "kg_price": 3,
        "chance": 20
    },

    "찢어진 양말": {
        "min_kg": 0.1,
        "max_kg": 0.5,
        "habitat": "하수구",
        "base_price": 20,
        "kg_price": 5,
        "chance": 18
    },

    "해초": {
        "min_kg": 0.1,
        "max_kg": 1.0,
        "habitat": "얕은 바다",
        "base_price": 30,
        "kg_price": 8,
        "chance": 25
    },

    "낡은 신발": {
        "min_kg": 0.3,
        "max_kg": 1.5,
        "habitat": "하수구",
        "base_price": 50,
        "kg_price": 10,
        "chance": 20
    },

    "녹슨 깡통": {
        "min_kg": 0.2,
        "max_kg": 2.0,
        "habitat": "강바닥",
        "base_price": 80,
        "kg_price": 15,
        "chance": 16
    },

    "폐타이어": {
        "min_kg": 3.0,
        "max_kg": 15.0,
        "habitat": "강바닥",
        "base_price": 100,
        "kg_price": 20,
        "chance": 7
    },

    "구피": {
        "min_kg": 0.05,
        "max_kg": 0.3,
        "habitat": "수족관",
        "base_price": 250,
        "kg_price": 50,
        "chance": 47
    },

    "피라미": {
        "min_kg": 0.1,
        "max_kg": 0.7,
        "habitat": "시냇물",
        "base_price": 320,
        "kg_price": 90,
        "chance": 40
    },

    "부러진 낚싯대": {
        "min_kg": 1.0,
        "max_kg": 4.0,
        "habitat": "호수",
        "base_price": 300,
        "kg_price": 40,
        "chance": 5
    },

    "누군가의 지갑": {
        "min_kg": 0.1,
        "max_kg": 0.5,
        "habitat": "호수",
        "base_price": 500000,
        "kg_price": 500,
        "chance": 1
    },

    "잃어버린 카드": {
        "min_kg": 0.1,
        "max_kg": 0.1,
        "habitat": "호수",
        "base_price": 200000,
        "kg_price": 5000,
        "chance": 0.1
    },

    "카시오 시계": {
        "min_kg": 0.02,
        "max_kg": 0.04,
        "habitat": "호수",
        "base_price": 25000,
        "kg_price": 1000,
        "chance": 0.1
    },
    
    "붕어": {
        "min_kg": 0.3,
        "max_kg": 2.0,
        "habitat": "연못",
        "base_price": 500,
        "kg_price": 120,
        "chance": 35
    },

    "금붕어": {
        "min_kg": 0.2,
        "max_kg": 1.0,
        "habitat": "연못",
        "base_price": 680,
        "kg_price": 150,
        "chance": 20
    },

    "잉어": {
        "min_kg": 1.0,
        "max_kg": 8.0,
        "habitat": "강",
        "base_price": 1300,
        "kg_price": 380,
        "chance": 25
    },

    "고등어": {
        "min_kg": 0.5,
        "max_kg": 5.0,
        "habitat": "바다",
        "base_price": 2500,
        "kg_price": 180,
        "chance": 25
    },

    "고장난 스마트폰": {
        "min_kg": 0.2,
        "max_kg": 0.6,
        "habitat": "강바닥",
        "base_price": 3000,
        "kg_price": 50,
        "chance": 2
    },

    "메기": {
        "min_kg": 2.0,
        "max_kg": 15.0,
        "habitat": "늪 / 강바닥",
        "base_price": 5200,
        "kg_price": 350,
        "chance": 15
    },

    "병어": {
        "min_kg": 0.5,
        "max_kg": 3.0,
        "habitat": "바다",
        "base_price": 5300,
        "kg_price": 370,
        "chance": 21
    },

    "송어": {
        "min_kg": 1.0,
        "max_kg": 6.0,
        "habitat": "계곡",
        "base_price": 6400,
        "kg_price": 400,
        "chance": 18
    },

    "배스": {
        "min_kg": 1.0,
        "max_kg": 10.0,
        "habitat": "강",
        "base_price": 8500,
        "kg_price": 560,
        "chance": 16
    },

    "놀래미": {
        "min_kg": 0.5,
        "max_kg": 4.0,
        "habitat": "바다",
        "base_price": 10700,
        "kg_price": 520,
        "chance": 20
    },

    "은어": {
        "min_kg": 0.3,
        "max_kg": 2.0,
        "habitat": "맑은 강",
        "base_price": 15100,
        "kg_price": 570,
        "chance": 24
    },

    "농어": {
        "min_kg": 1.0,
        "max_kg": 9.0,
        "habitat": "연안 바다",
        "base_price": 28000,
        "kg_price": 660,
        "chance": 18
    },

    "숭어": {
        "min_kg": 0.8,
        "max_kg": 6.0,
        "habitat": "강 하구",
        "base_price": 9500,
        "kg_price": 700,
        "chance": 22
    },

    "전어": {
        "min_kg": 0.2,
        "max_kg": 1.2,
        "habitat": "바다",
        "base_price": 42000,
        "kg_price": 750,
        "chance": 28
    },

    "도루묵": {
        "min_kg": 0.4,
        "max_kg": 2.5,
        "habitat": "차가운 바다",
        "base_price": 35600,
        "kg_price": 830,
        "chance": 20
    },

    "쏘가리": {
        "min_kg": 1.0,
        "max_kg": 8.0,
        "habitat": "강 상류",
        "base_price": 55200,
        "kg_price": 1050,
        "chance": 9
    },

    "볼락": {
        "min_kg": 0.5,
        "max_kg": 3.0,
        "habitat": "암초 지대",
        "base_price": 22700,
        "kg_price": 840,
        "chance": 19
    },

    "문어": {
        "min_kg": 2.0,
        "max_kg": 15.0,
        "habitat": "깊은 바다",
        "base_price": 68800,
        "kg_price": 1900,
        "chance": 7
    },

    "해마": {
        "min_kg": 0.1,
        "max_kg": 0.8,
        "habitat": "산호초",
        "base_price": 43100,
        "kg_price": 980,
        "chance": 12
    },

    "가재": {
        "min_kg": 0.3,
        "max_kg": 2.0,
        "habitat": "민물 바닥",
        "base_price": 15500,
        "kg_price": 1050,
        "chance": 23
    },

    "청어": {
        "min_kg": 0.5,
        "max_kg": 4.0,
        "habitat": "차가운 바다",
        "base_price": 16300,
        "kg_price": 1090,
        "chance": 25
    },

    "붉은 해파리": {
        "min_kg": 0.8,
        "max_kg": 5.0,
        "habitat": "붉은 해역",
        "base_price": 43600,
        "kg_price": 1330,
        "chance": 11
    },

    "검은 농어": {
        "min_kg": 2.0,
        "max_kg": 12.0,
        "habitat": "폭풍 해안",
        "base_price": 76900,
        "kg_price": 1550,
        "chance": 6
    },

    "도미": {
        "min_kg": 2.0,
        "max_kg": 12.0,
        "habitat": "깊은 바다",
        "base_price": 30100,
        "kg_price": 1610,
        "chance": 14
    },

    "청새치": {
        "min_kg": 40.0,
        "max_kg": 300.0,
        "habitat": "원양",
        "base_price": 120000,
        "kg_price": 1850,
        "chance": 4
    },

    "황금 잉어": {
        "min_kg": 5.0,
        "max_kg": 25.0,
        "habitat": "전설의 연못",
        "base_price": 480000,
        "kg_price": 2400,
        "chance": 2
    },

    # ===== 중상급 =====

    "가물치": {
        "min_kg": 3.0,
        "max_kg": 20.0,
        "habitat": "늪",
        "base_price": 75000,
        "kg_price": 1200,
        "chance": 10
    },

    "우럭": {
        "min_kg": 1.0,
        "max_kg": 8.0,
        "habitat": "바다",
        "base_price": 32000,
        "kg_price": 1100,
        "chance": 16
    },

    "광어": {
        "min_kg": 1.0,
        "max_kg": 10.0,
        "habitat": "바다",
        "base_price": 43000,
        "kg_price": 1400,
        "chance": 13
    },

    "연어": {
        "min_kg": 2.0,
        "max_kg": 18.0,
        "habitat": "강 / 바다",
        "base_price": 45000,
        "kg_price": 1350,
        "chance": 13
    },

    "갈치": {
        "min_kg": 2.0,
        "max_kg": 12.0,
        "habitat": "심해",
        "base_price": 35000,
        "kg_price": 1450,
        "chance": 12
    },

    "장어": {
        "min_kg": 1.0,
        "max_kg": 12.0,
        "habitat": "강 / 바다",
        "base_price": 35000,
        "kg_price": 1600,
        "chance": 9
    },

    "대구": {
        "min_kg": 3.0,
        "max_kg": 25.0,
        "habitat": "심해",
        "base_price": 45000,
        "kg_price": 1700,
        "chance": 10
    },

    "복어": {
        "min_kg": 1.0,
        "max_kg": 6.0,
        "habitat": "바다",
        "base_price": 65000,
        "kg_price": 900,
        "chance": 7
    },

    "민어": {
        "min_kg": 3.0,
        "max_kg": 20.0,
        "habitat": "바다",
        "base_price": 90000,
        "kg_price": 1250,
        "chance": 8
    },

    "참치": {
        "min_kg": 20.0,
        "max_kg": 250.0,
        "habitat": "먼바다",
        "base_price": 56000,
        "kg_price": 900,
        "chance": 7
    },

    "무지개송어": {
        "min_kg": 1.0,
        "max_kg": 7.0,
        "habitat": "차가운 계곡",
        "base_price": 75000,
        "kg_price": 1000,
        "chance": 8
    },

    "아귀": {
        "min_kg": 5.0,
        "max_kg": 40.0,
        "habitat": "심해",
        "base_price": 125000,
        "kg_price": 1500,
        "chance": 5
    },

    "비단잉어": {
        "min_kg": 2.0,
        "max_kg": 15.0,
        "habitat": "고급 연못",
        "base_price": 130000,
        "kg_price": 1500,
        "chance": 5
    },

    "철갑상어": {
        "min_kg": 20.0,
        "max_kg": 200.0,
        "habitat": "심해 강",
        "base_price": 260000,
        "kg_price": 1200,
        "chance": 2
    },

    "다금바리": {
        "min_kg": 10.0,
        "max_kg": 80.0,
        "habitat": "심해 암초",
        "base_price": 240000,
        "kg_price": 2200,
        "chance": 3
    },

    "얼음 송어": {
        "min_kg": 3.0,
        "max_kg": 15.0,
        "habitat": "빙하 호수",
        "base_price": 220000,
        "kg_price": 2500,
        "chance": 2
    },

    "그림자 메기": {
        "min_kg": 5.0,
        "max_kg": 30.0,
        "habitat": "어둠의 늪",
        "base_price": 320000,
        "kg_price": 3000,
        "chance": 1
    },

    "전기 뱀장어": {
        "min_kg": 4.0,
        "max_kg": 25.0,
        "habitat": "폭풍의 강",
        "base_price": 300000,
        "kg_price": 3200,
        "chance": 0.9
    },

    "별빛 해파리": {
        "min_kg": 1.0,
        "max_kg": 8.0,
        "habitat": "밤바다",
        "base_price": 450000,
        "kg_price": 6500,
        "chance": 0.4
    },

    "무지개 고래어": {
        "min_kg": 100.0,
        "max_kg": 800.0,
        "habitat": "환상의 바다",
        "base_price": 900000,
        "kg_price": 2500,
        "chance": 0.1
    },

    "심연의 포식어": {
        "min_kg": 150.0,
        "max_kg": 900.0,
        "habitat": "심연",
        "base_price": 1300000,
        "kg_price": 3500,
        "chance": 0.08
    },

    "아카브 심해종": {
        "min_kg": 200.0,
        "max_kg": 1200.0,
        "habitat": "아카브 심해",
        "base_price": 2200000,
        "kg_price": 5000,
        "chance": 0.005
    },

    # ===== 새 비싼 물고기 =====

    "심해룡": {
        "min_kg": 500.0,
        "max_kg": 3000.0,
        "habitat": "용의 해구",
        "base_price": 3200000,
        "kg_price": 6500,
        "chance": 0.003
    },

    "심연 크라운": {
        "min_kg": 800.0,
        "max_kg": 5000.0,
        "habitat": "왕의 심연",
        "base_price": 4500000,
        "kg_price": 8000,
        "chance": 0.0015
    },

    "공허의 포식자": {
        "min_kg": 3000.0,
        "max_kg": 20000.0,
        "habitat": "공허 해역",
        "base_price": 7000000,
        "kg_price": 90000,
        "chance": 0.0005
    },

    "메갈로돈": {
        "min_kg": 3000.0,
        "max_kg": 120000.0,
        "habitat": "고대의 심연",
        "base_price": 2800000,
        "kg_price": 500,
        "chance": 0.001
    },

    "크라켄": {
        "min_kg": 300.0,
        "max_kg": 1000.0,
        "habitat": "심연의 균열",
        "base_price": 3500000,
        "kg_price": 7000,
        "chance": 0.001
    }
}

FISH_TRAITS = {

    # =========================
    # 안 좋은 특성
    # =========================

    "상처난": {
        "price_mult": 0.75,
        "kg_mult": 0.9,
        "type": "bad",
        "chance": 35
    },

    "비린내 나는": {
        "price_mult": 0.8,
        "kg_mult": 1.0,
        "type": "bad",
        "chance": 30
    },

    "마른": {
        "price_mult": 0.9,
        "kg_mult": 0.75,
        "type": "bad",
        "chance": 25
    },

    "썩어가는": {
        "price_mult": 0.5,
        "kg_mult": 1.0,
        "type": "bad",
        "chance": 10
    },

    # =========================
    # 좋은 특성
    # =========================

    "싱싱한": {
        "price_mult": 1.2,
        "kg_mult": 1.1,
        "type": "good",
        "chance": 100
    },

    "윤기나는": {
        "price_mult": 1.25,
        "kg_mult": 1.0,
        "type": "good",
        "chance": 90
    },

    "튼실한": {
        "price_mult": 1.2,
        "kg_mult": 1.35,
        "type": "good",
        "chance": 85
    },

    "거대한": {
        "price_mult": 0.9,
        "kg_mult": 10,
        "type": "good",
        "chance": 60
    },

    "황금빛": {
        "price_mult": 2,
        "kg_mult": 1.0,
        "type": "good",
        "chance": 40
    },

    "무지개빛": {
        "price_mult": 2.0,
        "kg_mult": 1.0,
        "type": "good",
        "chance": 25
    },

    "심연의": {
        "price_mult": 2.6,
        "kg_mult": 1.2,
        "type": "good",
        "chance": 18
    },

    "고대의": {
        "price_mult": 3.5,
        "kg_mult": 1.15,
        "type": "good",
        "chance": 14
    },

    "축복받은": {
        "price_mult": 4.8,
        "kg_mult": 1.0,
        "type": "good",
        "chance": 10
    },

    "왕관을 쓴": {
        "price_mult": 3.5,
        "kg_mult": 1.1,
        "type": "good",
        "chance": 8
    },

    "폭풍을 머금은": {
        "price_mult": 3.2,
        "kg_mult": 1.15,
        "type": "good",
        "chance": 12
    },

    "별빛을 품은": {
        "price_mult": 3.6,
        "kg_mult": 1.15,
        "type": "good",
        "chance": 7
    },

    "공허에 물든": {
        "price_mult": 4.5,
        "kg_mult": 1.4,
        "type": "good",
        "chance": 4
    },

    "신의": {
        "price_mult": 6.0,
        "kg_mult": 1.0,
        "type": "good",
        "chance": 2
    },

    "혼돈의": {
        "price_mult": 10.0,
        "kg_mult": 1.5,
        "type": "good",
        "chance": 1
    }
}

ROD_DATA = {
    "기본 낚싯대": {
        "price": 0,
        "luck": 0, "time_reduce": 0,
        "double_chance": 0, "triple_chance": 0,
        "gauge_bonus": 0
    },
    "초급 낚싯대": {
        "price": 150000,
        "luck": 5, "time_reduce": 5,
        "double_chance": 2, "triple_chance": 0.1,
        "gauge_bonus": 3
    },
    "중급 낚싯대": {
        "price": 600000,
        "luck": 12, "time_reduce": 12,
        "double_chance": 5, "triple_chance": 1,
        "gauge_bonus": 5
    },
    "고급 낚싯대": {
        "price": 1300000,
        "luck": 23, "time_reduce": 25,
        "double_chance": 8, "triple_chance": 2,
        "gauge_bonus": 10
    },
    "개쩌는 낚싯대": {
        "price": 3000000,
        "luck": 37, "time_reduce": 25,
        "double_chance": 10, "triple_chance": 5,
        "gauge_bonus": 15
    },
    "최상의 낚싯대": {
        "price": 8000000,
        "luck": 55, "time_reduce": 30,
        "double_chance": 15, "triple_chance": 7,
        "gauge_bonus": 18
    },
    "장인의 낚싯대": {
        "price": 20000000,
        "luck": 75, "time_reduce": 40,
        "double_chance": 18, "triple_chance": 10,
        "gauge_bonus": 22
    },
    "엘프의 낚싯대": {
        "price": 60000000,
        "luck": 100, "time_reduce": 45,
        "double_chance": 20, "triple_chance": 12,
        "gauge_bonus": 25
    },
    "강태공의 낚싯대": {
        "price": 180000000,
        "luck": 235, "time_reduce": 55,
        "double_chance": 35, "triple_chance": 15,
        "gauge_bonus": 30
    },
    "신의 낚싯대": {
        "price": 500000000,
        "luck": 450, "time_reduce": 60,
        "double_chance": 40, "triple_chance": 30,
        "gauge_bonus": 40
    },
    "도로롱의 낚싯대": {
        "price": 800000000,
        "luck": 900, "time_reduce": 70,
        "double_chance": 25, "triple_chance": 75,
        "gauge_bonus": 55
    }
}

BAIT_DATA = {
    "미끼 없음": {
        "price": 0,
        "luck": 0
    },
    "장구벌레": {
        "price": 300,
        "luck": 5
    },
    "지렁이": {
        "price": 700,
        "luck": 10
    },
    "귀뚜라미": {
        "price": 1300,
        "luck": 18
    },
    "거미": {
        "price": 2300,
        "luck": 28
    },
    "영양볼": {
        "price": 4500,
        "luck": 45
    },
    "세계수 잎사귀": {
        "price": 12000,
        "luck": 65
    },
    "장인의 미끼": {
        "price": 15000,
        "luck": 85
    },
    "강태공의 미끼": {
        "price": 35000,
        "luck": 105
    },
    "신의 미끼": {
        "price": 150000,
        "luck": 185
    },
    "도로롱": {
        "price": 500000,
        "luck": 300
    }
}


# =========================
# 제작 재료 / 상자 아이템 시스템
# =========================

ITEM_DATA = {
    "낡은 부품 상자": {"type": "chest", "price": 25000, "grade": "일반"},
    "신비한 부품 상자": {"type": "chest", "price": 150000, "grade": "희귀"},
    "심해의 보물 상자": {"type": "chest", "price": 900000, "grade": "전설"},

    "낡은 릴": {"type": "material", "price": 8000, "grade": "일반"},
    "질긴 낚싯줄": {"type": "material", "price": 9000, "grade": "일반"},
    "강철 바늘": {"type": "material", "price": 18000, "grade": "일반"},
    "튼튼한 손잡이": {"type": "material", "price": 22000, "grade": "일반"},
    "방수 접착제": {"type": "material", "price": 30000, "grade": "일반"},
    "반짝이는 비늘": {"type": "material", "price": 75000, "grade": "희귀"},
    "마력 깃든 나무": {"type": "material", "price": 120000, "grade": "희귀"},
    "정교한 릴": {"type": "material", "price": 180000, "grade": "희귀"},
    "심해의 수정": {"type": "material", "price": 500000, "grade": "영웅"},
    "고대 물고기 비늘": {"type": "material", "price": 900000, "grade": "영웅"},
    "엘프의 실": {"type": "material", "price": 1600000, "grade": "전설"},
    "신성한 파편": {"type": "material", "price": 5000000, "grade": "전설"},
}

CHEST_DROP_TABLE = {
    "낡은 부품 상자": [
        ("낡은 릴", 24), ("질긴 낚싯줄", 24), ("강철 바늘", 20),
        ("튼튼한 손잡이", 16), ("방수 접착제", 10), ("반짝이는 비늘", 6),
    ],
    "신비한 부품 상자": [
        ("방수 접착제", 20), ("반짝이는 비늘", 25), ("마력 깃든 나무", 22),
        ("정교한 릴", 18), ("심해의 수정", 10), ("고대 물고기 비늘", 5),
    ],
    "심해의 보물 상자": [
        ("심해의 수정", 24), ("고대 물고기 비늘", 24), ("엘프의 실", 15),
        ("신성한 파편", 7), ("정교한 릴", 15), ("마력 깃든 나무", 15),
    ],
}


GACHA_PRICE = 50000
HIGH_GACHA_PRICE = 250000

GACHA_CHEST_TABLE = [
    ("낡은 부품 상자", 78),
    ("신비한 부품 상자", 20),
    ("심해의 보물 상자", 2),
]

HIGH_GACHA_CHEST_TABLE = [
    ("낡은 부품 상자", 35),
    ("신비한 부품 상자", 50),
    ("심해의 보물 상자", 15),
]


def roll_chest_from_table(table):
    names = [name for name, weight in table]
    weights = [weight for name, weight in table]
    return random.choices(names, weights=weights, k=1)[0]


def roll_gacha_chest():
    return roll_chest_from_table(GACHA_CHEST_TABLE)


def roll_high_gacha_chest():
    return roll_chest_from_table(HIGH_GACHA_CHEST_TABLE)


def gacha_rate_text(table=None):
    if table is None:
        table = GACHA_CHEST_TABLE
    total = sum(weight for name, weight in table)
    return "\n".join(
        f"{name}: **{weight / total * 100:.2f}%**"
        for name, weight in table
    )


ROD_CRAFT_COSTS = {
    "초급 낚싯대": {"낡은 릴": 1, "질긴 낚싯줄": 2},
    "중급 낚싯대": {"낡은 릴": 2, "질긴 낚싯줄": 4, "강철 바늘": 2},
    "고급 낚싯대": {"강철 바늘": 4, "튼튼한 손잡이": 3, "방수 접착제": 2},
    "개쩌는 낚싯대": {"반짝이는 비늘": 4, "마력 깃든 나무": 2, "정교한 릴": 1},
    "최상의 낚싯대": {"마력 깃든 나무": 5, "정교한 릴": 3, "심해의 수정": 1},
    "장인의 낚싯대": {"정교한 릴": 5, "심해의 수정": 3, "고대 물고기 비늘": 1},
    "엘프의 낚싯대": {"엘프의 실": 2, "마력 깃든 나무": 10, "고대 물고기 비늘": 3},
    "강태공의 낚싯대": {"엘프의 실": 4, "심해의 수정": 8, "고대 물고기 비늘": 6},
    "신의 낚싯대": {"신성한 파편": 2, "엘프의 실": 8, "고대 물고기 비늘": 10},
    "도로롱의 낚싯대": {"신성한 파편": 5, "엘프의 실": 12, "심해의 수정": 20},
}

for _rod_name, _costs in ROD_CRAFT_COSTS.items():
    if _rod_name in ROD_DATA:
        ROD_DATA[_rod_name]["items"] = _costs


def get_item_bag(user_id):
    uid = str(user_id)
    if uid not in item_bags or not isinstance(item_bags[uid], dict):
        item_bags[uid] = {}
        save_data()
    return item_bags[uid]


def get_item_count(user_id, item_name):
    return int(get_item_bag(user_id).get(item_name, 0))


def add_item(user_id, item_name, count=1):
    if item_name not in ITEM_DATA:
        return False
    bag = get_item_bag(user_id)
    bag[item_name] = int(bag.get(item_name, 0)) + int(count)
    save_data()
    return True


def remove_item(user_id, item_name, count=1):
    bag = get_item_bag(user_id)
    if int(bag.get(item_name, 0)) < count:
        return False
    bag[item_name] -= int(count)
    if bag[item_name] <= 0:
        del bag[item_name]
    save_data()
    return True


def weighted_item_choice(drop_table):
    names = [name for name, weight in drop_table]
    weights = [weight for name, weight in drop_table]
    return random.choices(names, weights=weights, k=1)[0]


def open_chest_once(user_id, chest_name):
    if chest_name not in CHEST_DROP_TABLE:
        return None
    if not remove_item(user_id, chest_name, 1):
        return None
    item_name = weighted_item_choice(CHEST_DROP_TABLE[chest_name])
    add_item(user_id, item_name, 1)
    return item_name


def roll_fishing_chest(user_id):
    """낚시 성공 보상용 상자 드랍. 실패가 쌓이면 확률이 조금씩 오른다."""
    uid = str(user_id)
    pity = int(chest_pity.get(uid, 0))
    chance = min(35, 8 + pity * 2)

    if random.randint(1, 100) > chance:
        chest_pity[uid] = pity + 1
        save_data()
        return None

    chest_pity[uid] = 0
    chest_name = random.choices(
        ["낡은 부품 상자", "신비한 부품 상자", "심해의 보물 상자"],
        weights=[75, 22, 3],
        k=1
    )[0]
    add_item(user_id, chest_name, 1)
    return chest_name


def item_cost_text(costs):
    if not costs:
        return "없음"
    return ", ".join(f"{name} x{count}" for name, count in costs.items())

    pity = int(chest_pity.get(uid, 0))
    chance = min(35, 8 + pity * 2)

    if random.randint(1, 100) > chance:
        chest_pity[uid] = pity + 1
        save_data()
        return None

    chest_pity[uid] = 0
    chest_name = random.choices(
        ["낡은 부품 상자", "신비한 부품 상자", "심해의 보물 상자"],
        weights=[75, 22, 3],
        k=1
    )[0]
    add_item(user_id, chest_name, 1)
    return chest_name


def item_cost_text(costs):
    if not costs:
        return "없음"
    return ", ".join(f"{name} x{count}" for name, count in costs.items())


FISH_DESCRIPTIONS = {
    '젖은 종이': "물에 푹 젖어 글씨조차 읽기 어려운 종이다. 원래 무엇이 적혀 있었는지는 알 수 없다.",
    '비닐봉지': "바다를 떠돌다 걸려 올라온 비닐봉지다. 물고기보다 먼저 낚이는 경우가 많다.",
    '찢어진 양말': "이곳저곳 찢어져 본래 모습을 알아보기 힘든 양말이다. 주인은 이미 포기했을지도 모른다.",
    '해초': "물속 바위에 붙어 자라는 해초다. 낚시꾼에게는 꽝이지만 바다 생물들에게는 소중한 보금자리다.",
    '낡은 신발': "오랜 시간 물속에 잠겨 있던 신발이다. 누가 신고 있었는지는 아무도 모른다.",
    '녹슨 깡통': "녹이 잔뜩 슨 통조림 깡통이다. 희미하게 Mutti라는 글자가 남아 있다.",
    '폐타이어': "수명을 다한 낡은 타이어다. 물고기보다 이런 걸 낚으면 기분이 묘해진다.",
    '구피': "화려한 꼬리와 작은 몸집을 가진 관상어. 수조 속을 유유히 헤엄치는 모습으로 많은 사랑을 받고 있다.",
    '피라미': "맑은 강에서 무리를 지어 다니는 작은 민물고기. 크기는 작지만 움직임이 빨라 잡기 쉽지 않다.",
    '부러진 낚싯대': "반으로 부러진 낚싯대의 잔해다. 거대한 물고기와 싸우다 부러졌을지도 모른다.",
    '누군가의 지갑': "누군가 잃어버린 지갑이다. 생각보다 상태가 멀쩡해 주인을 찾을 수 있을지도 모른다.",
    '잃어버린 카드': "방수팩 안에 보관되어 있던 카드다. 아직 사용할 수 있을 것처럼 깨끗하다.",
    '카시오 시계': "오랜 시간 물에 잠겨 있었지만 아직도 작동하는 시계다. 대체 어떻게 버틴 걸까?",
    '붕어': "연못과 강에서 흔히 볼 수 있는 친숙한 민물고기. 둥글고 통통한 몸이 특징이다.",
    '금붕어': "붉고 주황빛 비늘이 아름다운 관상어. 사실 붕어를 오랜 세월 개량해 만들어진 품종이다.",
    '잉어': "굵은 몸과 입가의 수염이 특징인 대형 민물고기. 강한 힘 덕분에 낚시꾼들에게 인기가 많다.",
    '고등어': "따뜻한 바다를 무리 지어 이동하는 회유성 물고기. 등에는 푸른 줄무늬가 선명하게 나 있다.",
    '고장난 스마트폰': "액정이 산산조각 난 스마트폰이다. 데이터는 이미 바다의 품으로 사라졌을지도 모른다.",
    '메기': "긴 수염과 넓은 입을 가진 민물고기. 비늘이 없는 미끌미끌한 몸을 가지고 있다.",
    '병어': "납작한 은빛 몸을 가진 바닷물고기. 무리를 지어 다니며 부드러운 살로 유명하다.",
    '송어': "맑고 차가운 강과 계곡에 서식하는 육식성 물고기. 힘이 좋아 낚싯대를 크게 휘게 만든다.",
    '배스': "큰 입과 강한 힘을 가진 대형 민물 포식어. 낚시꾼들 사이에서는 손맛 좋은 물고기로 유명하다.",
    '놀래미': "바위가 많은 연안에서 자주 발견되는 물고기. 화려한 무늬와 강한 생명력을 가지고 있다.",
    '은어': "맑고 깨끗한 강에서 서식하는 물고기. 오이 향과 비슷한 독특한 향기가 나는 것으로 유명하다.",
    '농어': "바다와 강 하구를 오가며 살아가는 대형 포식어. 작은 물고기들을 사냥하며 빠른 돌진이 특징이다.",
    '숭어': "강 하구와 연안에서 무리를 지어 다니는 물고기. 수면 위로 높이 뛰어오르는 모습이 자주 목격된다.",
    '전어': "가을철이 되면 특히 맛이 좋아지는 은빛 물고기. 커다란 무리를 이루어 이동한다.",
    '도루묵': "차가운 바다에서 살아가는 작은 물고기. 알이 가득 찬 겨울철에 특히 유명하다.",
    '쏘가리': "맑은 강의 최상위 포식자로 불리는 민물고기. 몸의 검은 반점과 강한 힘이 특징이다.",
    '볼락': "암초 주변에서 살아가는 야행성 물고기. 밤이 되면 더욱 활발하게 움직인다.",
    '문어': "여덟 개의 다리를 가진 영리한 연체동물. 위험을 느끼면 먹물을 뿜어 적을 따돌린다.",
    '해마': "말을 닮은 머리를 가진 작은 바다 생물. 수컷이 알을 품는 독특한 생태를 가지고 있다.",
    '가재': "단단한 껍질과 큰 집게를 가진 갑각류. 바위 틈이나 강바닥에 숨어 지낸다.",
    '청어': "은빛 비늘이 아름다운 회유성 물고기. 거대한 무리를 이루어 바다를 이동한다.",
    '붉은 해파리': "붉은빛 몸체를 가진 해파리. 촉수에는 약한 독이 있어 함부로 만지면 위험하다.",
    '검은 농어': "어두운 비늘을 가진 농어의 희귀한 변종. 일반 농어보다 더욱 공격적인 성향을 보인다.",
    '도미': "붉은빛 비늘이 아름다운 바닷물고기. 예로부터 귀한 생선으로 취급받아 왔다.",
    '청새치': "날카로운 창처럼 긴 주둥이를 가진 초대형 포식어. 바다에서 가장 빠른 물고기 중 하나다.",
    '황금 잉어': "황금빛 비늘을 가진 희귀한 잉어. 행운을 가져다준다는 전설이 전해진다.",
    '가물치': "거대한 입과 강한 생명력을 가진 민물 포식어. 산소가 부족한 환경에서도 오래 버틴다.",
    '우럭': "바위가 많은 연안에서 자주 발견되는 물고기. 위장 능력이 뛰어나 주변 환경에 잘 녹아든다.",
    '광어': "몸이 납작하고 두 눈이 한쪽으로 몰려 있는 독특한 물고기. 모래 바닥에 몸을 숨기고 사냥한다.",
    '연어': "강에서 태어나 바다에서 성장한 뒤 다시 고향 강으로 돌아오는 회유성 물고기.",
    '갈치': "칼날처럼 길고 은빛으로 빛나는 바닷물고기. 날카로운 이빨을 가지고 있다.",
    '장어': "뱀처럼 길쭉한 몸을 가진 물고기. 강과 바다를 오가며 살아간다.",
    '대구': "차가운 바다를 좋아하는 대형 물고기. 입 아래에 짧은 수염이 달려 있다.",
    '복어': "위협을 느끼면 몸을 크게 부풀리는 독특한 물고기. 일부 부위에는 강한 독이 존재한다.",
    '민어': "커다란 몸집과 뛰어난 힘을 가진 바닷물고기. 여름철 대표 어종으로 유명하다.",
    '참치': "끊임없이 헤엄쳐야 살아갈 수 있는 대형 회유성 어류. 강력한 힘과 속도를 자랑한다.",
    '무지개송어': "몸 옆을 따라 무지갯빛 줄무늬가 이어지는 송어. 양식장에서도 자주 볼 수 있다.",
    '아귀': "거대한 입과 기괴한 외형을 가진 심해성 물고기. 머리 위의 돌기로 먹잇감을 유인한다.",
    '비단잉어': "붉은색과 흰색 무늬가 아름다운 관상용 잉어. 연못의 보석이라 불린다.",
    '철갑상어': "갑옷 같은 단단한 비늘을 가진 고대 어류. 수백만 년 전부터 거의 모습이 변하지 않았다.",
    '다금바리': "거대한 몸집을 가진 고급 어종. 바위 틈에 숨어 먹잇감을 노린다.",
    '얼음 송어': "차가운 마력이 흐르는 강에서 발견되는 송어. 비늘에서는 희미한 냉기가 흘러나온다.",
    '그림자 메기': "어둠 속에 몸을 숨기는 희귀한 메기. 물속 그림자와 구별하기 어려울 정도다.",
    '전기 뱀장어': "몸속에 강력한 전기를 저장하는 위험한 생물. 건드리면 감전될 수 있다.",
    '별빛 해파리': "밤이 되면 은은하게 빛나는 신비로운 해파리. 마치 별이 바다에 떠 있는 것 같다.",
    '무지개 고래어': "거대한 몸집과 무지갯빛 비늘을 가진 전설의 물고기. 목격담만 드물게 전해진다.",
    '심연의 포식어': "빛조차 닿지 않는 심해에 서식하는 괴물 같은 물고기. 거대한 이빨을 가지고 있다.",
    '아카브 심해종': "아카브 해역의 깊은 바다에서 발견된 미확인 생물. 인근 마족들이 주된 사냥감이라고 한다.",
    '심해룡': "용을 닮은 거대한 심해 생물. 긴 몸체와 푸른 발광 기관을 가지고 있다.",
    '심연 크라운': "머리 위에 왕관처럼 빛나는 기관을 가진 희귀종. 심해 생태계의 왕으로 불린다.",
    '공허의 포식자': "심연보다 더 깊은 공허에서 나타난 존재. 주변의 빛과 생명력을 집어삼킨다.",
    '메갈로돈': "고대 바다를 지배했던 초대형 상어. 전설 속에서는 아직까지 살아 있다고 전해진다.",
    '크라켄': "거대한 촉수로 배를 바다 밑으로 끌어당긴다는 전설의 해양 괴수다."
}


FISH_CATCH_SETTINGS = {
    '젖은 종이': {"catch_level": 1, "gauge_min": 45, "gauge_max": 80},
    '비닐봉지': {"catch_level": 1, "gauge_min": 45, "gauge_max": 80},
    '찢어진 양말': {"catch_level": 1, "gauge_min": 45, "gauge_max": 80},
    '해초': {"catch_level": 1, "gauge_min": 45, "gauge_max": 80},
    '낡은 신발': {"catch_level": 1, "gauge_min": 45, "gauge_max": 80},
    '녹슨 깡통': {"catch_level": 1, "gauge_min": 45, "gauge_max": 80},
    '폐타이어': {"catch_level": 8, "gauge_min": 60, "gauge_max": 105},
    '구피': {"catch_level": 2, "gauge_min": 45, "gauge_max": 80},
    '피라미': {"catch_level": 3, "gauge_min": 45, "gauge_max": 80},
    '부러진 낚싯대': {"catch_level": 8, "gauge_min": 60, "gauge_max": 105},
    '누군가의 지갑': {"catch_level": 30, "gauge_min": 120, "gauge_max": 210},
    '잃어버린 카드': {"catch_level": 83, "gauge_min": 420, "gauge_max": 720},
    '카시오 시계': {"catch_level": 79, "gauge_min": 260, "gauge_max": 460},
    '붕어': {"catch_level": 4, "gauge_min": 45, "gauge_max": 80},
    '금붕어': {"catch_level": 4, "gauge_min": 45, "gauge_max": 80},
    '잉어': {"catch_level": 8, "gauge_min": 60, "gauge_max": 105},
    '고등어': {"catch_level": 8, "gauge_min": 60, "gauge_max": 105},
    '고장난 스마트폰': {"catch_level": 13, "gauge_min": 80, "gauge_max": 140},
    '메기': {"catch_level": 12, "gauge_min": 80, "gauge_max": 140},
    '병어': {"catch_level": 8, "gauge_min": 60, "gauge_max": 105},
    '송어': {"catch_level": 9, "gauge_min": 60, "gauge_max": 105},
    '배스': {"catch_level": 11, "gauge_min": 80, "gauge_max": 140},
    '놀래미': {"catch_level": 9, "gauge_min": 60, "gauge_max": 105},
    '은어': {"catch_level": 9, "gauge_min": 60, "gauge_max": 105},
    '농어': {"catch_level": 12, "gauge_min": 80, "gauge_max": 140},
    '숭어': {"catch_level": 10, "gauge_min": 60, "gauge_max": 105},
    '전어': {"catch_level": 11, "gauge_min": 80, "gauge_max": 140},
    '도루묵': {"catch_level": 11, "gauge_min": 80, "gauge_max": 140},
    '쏘가리': {"catch_level": 14, "gauge_min": 80, "gauge_max": 140},
    '볼락': {"catch_level": 10, "gauge_min": 60, "gauge_max": 105},
    '문어': {"catch_level": 16, "gauge_min": 80, "gauge_max": 140},
    '해마': {"catch_level": 11, "gauge_min": 80, "gauge_max": 140},
    '가재': {"catch_level": 9, "gauge_min": 60, "gauge_max": 105},
    '청어': {"catch_level": 10, "gauge_min": 60, "gauge_max": 105},
    '붉은 해파리': {"catch_level": 13, "gauge_min": 80, "gauge_max": 140},
    '검은 농어': {"catch_level": 16, "gauge_min": 80, "gauge_max": 140},
    '도미': {"catch_level": 13, "gauge_min": 80, "gauge_max": 140},
    '청새치': {"catch_level": 26, "gauge_min": 120, "gauge_max": 210},
    '황금 잉어': {"catch_level": 27, "gauge_min": 120, "gauge_max": 210},
    '가물치': {"catch_level": 17, "gauge_min": 80, "gauge_max": 140},
    '우럭': {"catch_level": 12, "gauge_min": 80, "gauge_max": 140},
    '광어': {"catch_level": 14, "gauge_min": 80, "gauge_max": 140},
    '연어': {"catch_level": 15, "gauge_min": 80, "gauge_max": 140},
    '갈치': {"catch_level": 13, "gauge_min": 80, "gauge_max": 140},
    '장어': {"catch_level": 14, "gauge_min": 80, "gauge_max": 140},
    '대구': {"catch_level": 18, "gauge_min": 80, "gauge_max": 140},
    '복어': {"catch_level": 14, "gauge_min": 80, "gauge_max": 140},
    '민어': {"catch_level": 18, "gauge_min": 80, "gauge_max": 140},
    '참치': {"catch_level": 21, "gauge_min": 120, "gauge_max": 210},
    '무지개송어': {"catch_level": 14, "gauge_min": 80, "gauge_max": 140},
    '아귀': {"catch_level": 17, "gauge_min": 80, "gauge_max": 140},
    '비단잉어': {"catch_level": 18, "gauge_min": 80, "gauge_max": 140},
    '철갑상어': {"catch_level": 27, "gauge_min": 120, "gauge_max": 210},
    '다금바리': {"catch_level": 22, "gauge_min": 120, "gauge_max": 210},
    '얼음 송어': {"catch_level": 24, "gauge_min": 120, "gauge_max": 210},
    '그림자 메기': {"catch_level": 36, "gauge_min": 180, "gauge_max": 320},
    '전기 뱀장어': {"catch_level": 37, "gauge_min": 180, "gauge_max": 320},
    '별빛 해파리': {"catch_level": 50, "gauge_min": 180, "gauge_max": 320},
    '무지개 고래어': {"catch_level": 107, "gauge_min": 650, "gauge_max": 1100},
    '심연의 포식어': {"catch_level": 108, "gauge_min": 650, "gauge_max": 1100},
    '아카브 심해종': {"catch_level": 109, "gauge_min": 650, "gauge_max": 1100},
    '심해룡': {"catch_level": 111, "gauge_min": 650, "gauge_max": 1100},
    '심연 크라운': {"catch_level": 112, "gauge_min": 650, "gauge_max": 1100},
    '공허의 포식자': {"catch_level": 120, "gauge_min": 650, "gauge_max": 1100},
    '메갈로돈': {"catch_level": 113, "gauge_min": 650, "gauge_max": 1100},
    '크라켄': {"catch_level": 110, "gauge_min": 650, "gauge_max": 1100},
}

for _fish_name, _setting in FISH_CATCH_SETTINGS.items():
    if _fish_name in FISH_DATA:
        FISH_DATA[_fish_name].update(_setting)


def get_fish_description(fish_name):
    desc = FISH_DESCRIPTIONS.get(fish_name, "")
    return desc if desc else "설명 준비 중..."


def fish_detail_text(fish_name, user_id=None):
    update_fish_market()
    data = FISH_DATA[fish_name]
    caught_text = ""
    if user_id is not None:
        dex = fish_dex.get(user_id, set())
        caught_text = "✅ 등록됨" if fish_name in dex else "❌ 미등록"
        caught_text = f"도감 상태: **{caught_text}**\n"

    chance = data.get("chance", 0)
    shown_chance = chance * 2 if globals().get("_FISH_CHANCE_HALVED", False) else chance

    return (
        f"📖🐟 **{fish_name} 정보**\n\n"
        f"{caught_text}"
        f"이름: **{fish_name}**\n"
        f"최대 무게: **{data['max_kg']}kg**\n"
        f"포획 레벨: **{data.get('catch_level', 1)}**\n"
        f"힘겨루기 게이지: **{data.get('gauge_min', 100)}~{data.get('gauge_max', 100)}**\n"
        f"확률 가중치: **{shown_chance}**\n"
        f"기본 판매가: **{money(data['base_price'])}**\n"
        f"kg당 추가 가격: **{money(data['kg_price'])}**\n"
        f"{get_market_text(fish_name)}\n"
        f"장소: **{data['habitat']}**\n\n"
        f"설명: {get_fish_description(fish_name)}"
    )

BOSS_FISH = ["메갈로돈", "크라켄"]

# FISH_DATA chance는 한 번만 절반으로 줄어들게 처리
if not globals().get("_FISH_CHANCE_HALVED", False):
    for fish in FISH_DATA.values():
        fish["chance"] /= 2
    _FISH_CHANCE_HALVED = True


# =========================
# 낚시 전투 메시지
# =========================



# =========================
# 저장용 데이터
# =========================

fish_tanks = globals().get("fish_tanks", {})
fish_dex = globals().get("fish_dex", {})
item_bags = globals().get("item_bags", {})
chest_pity = globals().get("chest_pity", {})
gacha_pity = globals().get("gacha_pity", {})

owned_rods = globals().get("owned_rods", {})
equipped_rods = globals().get("equipped_rods", {})
owned_baits = globals().get("owned_baits", {})
equipped_baits = globals().get("equipped_baits", {})

fishing_cooldowns = {}
FISHING_COOLDOWN = timedelta(seconds=10)

fish_market = globals().get("fish_market", {})
last_market_update = globals().get("last_market_update", None)

MARKET_MIN = 0.70
MARKET_MAX = 2.00


# =========================
# 시세 시스템
# =========================

def init_fish_market():
    for fish_name in FISH_DATA.keys():
        if fish_name not in fish_market:
            fish_market[fish_name] = 1.0


def update_fish_market():
    global last_market_update

    init_fish_market()
    now = datetime.now()

    if last_market_update is not None:
        if (now - last_market_update).total_seconds() < 3600:
            return False

    for fish_name in FISH_DATA.keys():
        change = random.uniform(0.01, 0.07)

        if random.choice([True, False]):
            fish_market[fish_name] += change
        else:
            fish_market[fish_name] -= change

        fish_market[fish_name] = max(
            MARKET_MIN,
            min(MARKET_MAX, fish_market[fish_name])
        )

    last_market_update = now
    save_data()
    return True


def get_market_price(fish_name, price):
    init_fish_market()
    return int(price * fish_market.get(fish_name, 1.0))


def get_market_text(fish_name):
    init_fish_market()
    rate = fish_market.get(fish_name, 1.0)
    percent = int(rate * 100)

    if rate > 1:
        return f"📈 현재 시세: **{percent}%**"
    elif rate < 1:
        return f"📉 현재 시세: **{percent}%**"

    return "➖ 현재 시세: **100%**"


# =========================
# 기본 함수
# =========================

def get_tank(user_id):
    changed = False

    if user_id not in fish_tanks or not isinstance(fish_tanks[user_id], list):
        fish_tanks[user_id] = []
        changed = True


    if user_id not in fish_dex:
        fish_dex[user_id] = set()
        changed = True

    if changed:
        save_data()

    return changed


def fish_price(fish_name, kg):
    fish = FISH_DATA[fish_name]
    return int(fish["base_price"] + kg * fish["kg_price"])


def pick_fish(luck_bonus=0):
    names = list(FISH_DATA.keys())
    weights = []

    for name in names:
        fish = FISH_DATA[name]
        chance = fish["chance"]
        price_score = fish["base_price"] + fish["max_kg"] * fish["kg_price"]

        if price_score >= 100000:
            chance *= 1 + (luck_bonus / 45)
        elif price_score >= 30000:
            chance *= 1 + (luck_bonus / 70)
        elif price_score >= 10000:
            chance *= 1 + (luck_bonus / 100)
        else:
            chance *= max(0.2, 1 - (luck_bonus / 250))

        weights.append(chance)

    return random.choices(names, weights=weights, k=1)[0]


def weighted_trait_choice(traits):
    names = []
    weights = []

    for name in traits:
        names.append(name)
        weights.append(FISH_TRAITS[name]["chance"])

    return random.choices(names, weights=weights, k=1)[0]


def roll_fish_trait():
    if random.randint(1, 100) > FISH_TRAIT_CHANCE:
        return None

    bad_traits = [
        name for name, data in FISH_TRAITS.items()
        if data["type"] == "bad"
    ]

    good_traits = [
        name for name, data in FISH_TRAITS.items()
        if data["type"] == "good"
    ]

    if random.randint(1, 100) <= 80:
        return weighted_trait_choice(good_traits)

    return weighted_trait_choice(bad_traits)

def make_fish(user_id, fish_name):
    fish_data = FISH_DATA[fish_name]

    trait_name = roll_fish_trait()

    kg = random.uniform(
        fish_data["min_kg"],
        fish_data["max_kg"]
    )

    display_name = fish_name

    if trait_name:
        trait = FISH_TRAITS[trait_name]
        kg *= trait["kg_mult"]
        display_name = f"{trait_name} {fish_name}"

    kg = round(kg, 2)

    price = fish_price(fish_name, kg)

    if trait_name:
        price = int(price * FISH_TRAITS[trait_name]["price_mult"])

    fish = {
        "name": fish_name,
        "display_name": display_name,
        "trait": trait_name,
        "kg": kg,
        "price": price
    }

    fish_tanks[user_id].append(fish)
    fish_dex[user_id].add(fish_name)

    return fish


def get_fishing_gear(user_id):
    changed = False

    if user_id not in owned_rods:
        owned_rods[user_id] = ["기본 낚싯대"]
        changed = True

    before = len(owned_rods[user_id])
    owned_rods[user_id] = [
        rod for rod in owned_rods[user_id]
        if rod in ROD_DATA
    ]

    if len(owned_rods[user_id]) != before:
        changed = True

    if not owned_rods[user_id]:
        owned_rods[user_id] = ["기본 낚싯대"]
        changed = True

    if user_id not in equipped_rods:
        equipped_rods[user_id] = "기본 낚싯대"
        changed = True

    if equipped_rods[user_id] not in ROD_DATA:
        equipped_rods[user_id] = "기본 낚싯대"
        changed = True

    if user_id not in owned_baits:
        owned_baits[user_id] = {}
        changed = True

    if user_id not in equipped_baits:
        equipped_baits[user_id] = "미끼 없음"
        changed = True

    if changed:
        save_data()

    return changed

# =========================
# 기본 낚시 타이밍 버튼
# =========================

FISH_WAIT_MESSAGES = [
    "🍃 바람이 선선하게 분다...",
    "☀️ 하늘이 맑다...",
    "🌊 물결이 잔잔하다...",
    "🎣 찌가 조용히 떠 있다...",
    "🐟 물속에서 뭔가 스친 것 같다...",
    "💧 잔물결이 퍼진다...",
    "🌫️ 안개가 천천히 걷히고 있다...",
    "🍂 낙엽 하나가 물 위에 떨어졌다...",
    "🐦 새소리가 들려온다...",
    "🌊 먼 곳에서 작은 물보라가 튄다...",
    "🎣 낚싯줄이 살짝 흔들린다...",
    "💨 바람이 방향을 바꾼다...",
    "🐟 물속 그림자가 지나간 것 같다...",
    "🌤️ 구름이 천천히 흘러간다...",
    "💧 물방울이 수면에 떨어졌다...",
    "🦆 오리가 멀리서 헤엄쳐 간다...",
    "🌊 수초가 물결에 흔들린다...",
    "🐸 개구리 울음소리가 들린다...",
    "🎣 아직은 조용하다...",
    "💭 오늘은 뭔가 잡힐 것 같은 기분이다...",
    "🌅 햇빛이 수면에 반사된다...",
    "🐟 작은 물고기 떼가 지나간다...",
    "🌊 수면 아래에서 기포가 올라온다...",
    "🍃 바람에 찌가 살짝 움직인다...",
    "🎣 시간이 천천히 흐른다...",
    "💧 물결이 원을 그리며 퍼져나간다...",
    "🐦 갈매기 한 마리가 지나간다...",
    "🌊 깊은 곳에서 뭔가 움직인 것 같다...",
    "🎣 낚싯대를 쥔 손에 긴장감이 돈다...",
    "🐟 큰 놈이 근처에 있는 것 같은 느낌이다..."
]

FISH_FAKE_MESSAGES = [
    ("앗?!", "기분탓이었다..."),
    ("뭔가 느낌이!", "감이 틀렸던 모양이다..."),
    ("찌가 흔들렸다!", "물결이었다..."),
    ("🐟 무언가 왔다!", "해초가 스친 것 같다..."),
    ("💥 강한 입질이다!", "줄에 걸린 나뭇가지였다..."),
    ("🌊 수면이 크게 흔들린다!", "바람 때문이었다..."),
    ("🎣 찌가 가라앉는다!", "다시 떠올랐다..."),
    ("👀 큰 놈인가?!", "착각이었던 것 같다...")
]

FISH_ACTION_MESSAGES = [
    "🐟 물고기가 찌를 물었다!",
    "🎣 낚싯줄이 팽팽해진다!",
    "🌊 수면 아래에서 그림자가 흔들린다!",
    "💥 강한 저항이 손끝에 전해진다!",
    "🐟 찌가 강하게 당겨진다!",
    "🌊 수면에 큰 파문이 번진다!",
    "🐟 물고기가 옆으로 튀어 오른다!",
    "🎣 릴이 빠르게 돌아가기 시작한다!",
    "💨 무언가가 깊은 곳으로 달아난다!",
    "🌊 거센 물보라가 일어난다!",
    "🐟 놈이 방향을 급하게 바꾼다!",
    "🎣 낚싯대가 크게 휘어진다!",
    "🌊 수면 아래 거대한 그림자가 스친다!",
    "💥 엄청난 힘이 전해진다!",
    "🐟 놈이 필사적으로 버틴다!",
    "🌊 깊은 곳에서 기포가 올라온다!",
    "🐟 물고기가 수초 사이로 파고든다!",
    "🎣 줄이 좌우로 흔들린다!",
    "💧 수면이 크게 흔들린다!",
    "🐟 무언가가 낚싯줄을 끌고 간다!",
    "🌊 물속에서 번쩍이는 비늘이 보인다!",
    "🐟 놈이 수면 근처까지 올라온다!",
    "🎣 릴에서 끼익거리는 소리가 난다!",
    "💥 손목이 저릴 정도의 힘이다!",
    "🐟 갑자기 움직임이 빨라진다!",
    "🌊 파문이 점점 커진다!",
    "🐟 물고기가 몸부림친다!",
    "🎣 낚싯줄이 끊어질 듯 팽팽하다!",
    "💨 놈이 멀리 달아나려 한다!",
    "🌊 수면 아래에서 물살이 뒤집힌다!",
    "🐟 강한 입질이 느껴진다!",
    "🎣 손끝에 진동이 전해진다!",
    "🌊 물결이 이상하게 흔들린다!",
    "💥 놈의 힘이 점점 강해진다!",
    "🐟 찌가 물속으로 빨려 들어간다!",
    "🌊 수면 아래에서 거대한 꼬리가 스친다!",
    "🐟 놈이 마지막 발악을 시작한다!",
    "🎣 낚싯대가 비명을 지르는 것 같다!",
    "💥 이건 꽤 큰 놈인 것 같다!",
    "🐟 무언가가 계속 줄을 끌어당긴다!"
]


def make_gauge_bar(value, max_value):
    filled = int((value / max_value) * 10)
    filled = max(0, min(10, filled))
    empty = 10 - filled
    return "🟩" * filled + "⬛" * empty + f" **{value}/{max_value}**"


class FishingButtonView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=35)
        self.user_id = user_id
        self.message = None
        self.started = False
        self.done = False

        self.ready_button = discord.ui.Button(
            label="기다리는 중...",
            style=discord.ButtonStyle.gray
        )
        self.ready_button.callback = self.ready_callback
        self.add_item(self.ready_button)

    async def ready_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 니 낚싯대 아님.", ephemeral=True)
            return

        if not self.started or self.ready_button.label != "지금이다!":
            self.done = True

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(
                content="🐟 너무 성급하게 낚싯대를 당겨버렸다...\n물고기가 도망갔다.",
                view=self
            )

            self.stop()
            return

        self.done = True
        await fishing_success(interaction)
        self.stop()

    async def start_waiting(self):
        rod_name = equipped_rods.get(self.user_id, "기본 낚싯대")
        rod = ROD_DATA.get(rod_name, ROD_DATA["기본 낚싯대"])

        max_wait = max(5, int(30 * (1 - rod["time_reduce"] / 100)))
        wait_time = random.randint(5, max_wait)

        elapsed = 0

        while elapsed < wait_time:
            if self.done:
                return

            if random.randint(1, 100) <= 25 and elapsed + 4 < wait_time:
                fake_start, fake_end = random.choice(FISH_FAKE_MESSAGES)

                self.started = False
                self.ready_button.label = fake_start
                self.ready_button.style = discord.ButtonStyle.red

                await self.message.edit(content=f"🎣 {fake_start}", view=self)
                await asyncio.sleep(3)

                self.ready_button.label = "기다리는 중..."
                self.ready_button.style = discord.ButtonStyle.gray

                await self.message.edit(content=f"🎣 {fake_end}", view=self)
                await asyncio.sleep(1)

                elapsed += 4
                continue

            await self.message.edit(
                content=f"🎣 {random.choice(FISH_WAIT_MESSAGES)}",
                view=self
            )

            await asyncio.sleep(5)
            elapsed += 5

        if self.done:
            return

        self.started = True
        self.ready_button.label = "지금이다!"
        self.ready_button.style = discord.ButtonStyle.green

        await self.message.edit(
            content="🎣 **지금이다!**",
            view=self
        )

    async def on_timeout(self):
        if self.done:
            return

        for item in self.children:
            item.disabled = True

        if self.message:
            await self.message.edit(
                content="🐟 물고기가 도망갔다...",
                view=self
            )


class FishBattleView(discord.ui.View):
    def __init__(self, user_id, fish_list, rod_name, bait_name, max_gauge):
        super().__init__(timeout=120)

        self.user_id = user_id
        self.fish_list = fish_list
        self.rod_name = rod_name
        self.bait_name = bait_name
        self.message = None

        self.max_gauge = max_gauge
        self.gauge = 0

        self.fail_count = 0
        self.hit_count = 0
        self.need_hits = random.randint(1, 3)

        self.target_index = None
        self.trap_indices = []
        self.gold_index = None
        self.round_active = False
        self.round_token = 0
        self.force_trap_next = False
        self.force_move_next = False
        self.last_event_text = ""
        self.last_event_effect = ""

        for i in range(5):
            self.add_item(FishGaugeButton(i))

    def gauge_step(self):
        """게이지 1칸 = 전체 게이지의 1/10."""
        return max(1, self.max_gauge // 10)

    def apply_battle_message_effect(self, message):
        """특정 힘겨루기 메시지가 뜰 때마다 특수 효과를 적용."""
        self.last_event_effect = ""

        gauge_down_messages = {
            "💨 무언가가 깊은 곳으로 달아난다!",
            "🐟 물고기가 수초 사이로 파고든다!",
            "💨 놈이 멀리 달아나려 한다!",
            "🌊 수면 아래에서 물살이 뒤집힌다!",
            "💥 놈의 힘이 점점 강해진다!",
            "🐟 무언가가 계속 줄을 끌어당긴다!",
        }

        gauge_up_messages = {
            "🐟 놈이 수면 근처까지 올라온다!",
            "🌊 물속에서 번쩍이는 비늘이 보인다!",
            "🎣 손끝에 진동이 전해진다!",
            "🐟 강한 입질이 느껴진다!",
            "💧 수면이 크게 흔들린다!",
        }

        trap_messages = {
            "💥 엄청난 힘이 전해진다!",
            "🎣 낚싯대가 비명을 지르는 것 같다!",
            "🎣 낚싯줄이 끊어질 듯 팽팽하다!",
            "💥 손목이 저릴 정도의 힘이다!",
            "🐟 놈이 필사적으로 버틴다!",
        }

        move_messages = {
            "🐟 놈이 방향을 급하게 바꾼다!",
            "🐟 갑자기 움직임이 빨라진다!",
            "🎣 줄이 좌우로 흔들린다!",
            "🐟 물고기가 옆으로 튀어 오른다!",
            "🌊 파문이 점점 커진다!",
        }

        if message in gauge_down_messages:
            self.gauge = max(0, self.gauge - self.gauge_step())
            self.last_event_effect = f"📉 물고기가 버텨서 게이지가 **1칸 감소**했다!"

        elif message in gauge_up_messages:
            self.gauge = min(self.max_gauge, self.gauge + self.gauge_step())
            self.last_event_effect = f"📈 빈틈을 잡아서 게이지가 **1칸 증가**했다!"

        elif message in trap_messages:
            self.force_trap_next = True
            self.last_event_effect = "🟥 위험하다! 다음 박스에 **빨간 함정 칸**이 나온다!"

        elif message in move_messages:
            self.force_move_next = True
            self.last_event_effect = "🔄 놈이 날뛴다! 다음 초록 칸 위치가 한 번 더 바뀐다!"

    def reset_buttons(self, disabled=True):
        for item in self.children:
            item.label = "⬛"
            item.style = discord.ButtonStyle.gray
            item.disabled = disabled

    async def start_battle(self):
        await self.start_hit_round()

    async def wait_for_chance(self):
        # 대기 구간 제거: 초록 버튼이 계속 뜨는 방식으로 즉시 다음 라운드 시작.
        await self.start_hit_round()

    def setup_round_buttons(self):
        previous_target = self.target_index
        self.target_index = random.randint(0, 4)
        self.trap_indices = []
        self.gold_index = None

        if self.force_move_next and previous_target is not None:
            possible = [i for i in range(5) if i != previous_target]
            self.target_index = random.choice(possible)
            self.force_move_next = False

        # 빨간 함정 칸은 한 번에 0~3개까지 등장할 수 있음.
        # 특수 메시지가 터졌으면 최소 1개는 보장.
        possible_traps = [i for i in range(5) if i != self.target_index]

        if self.force_trap_next:
            trap_count = random.randint(1, min(3, len(possible_traps)))
            self.force_trap_next = False
        else:
            trap_count = random.choices(
                [0, 1, 2, 3],
                weights=[55, 25, 15, 5],
                k=1
            )[0]
            trap_count = min(trap_count, len(possible_traps))

        self.trap_indices = random.sample(possible_traps, trap_count) if trap_count > 0 else []

        # 가끔 초록 버튼과 황금 버튼이 같이 나옴.
        # 황금 버튼은 남은 타이밍 수를 무시하고 게이지를 원래 증가량의 2배로 채움.
        if random.randint(1, 100) <= 15:
            possible = [
                i for i in range(5)
                if i != self.target_index and i not in self.trap_indices
            ]
            if possible:
                self.gold_index = random.choice(possible)

        # 검은 박스는 아예 비활성화해서 상호작용이 안 되게 둠.
        self.reset_buttons(disabled=True)

        self.children[self.target_index].label = "🟩"
        self.children[self.target_index].style = discord.ButtonStyle.green
        self.children[self.target_index].disabled = False

        for trap_index in self.trap_indices:
            self.children[trap_index].label = "🟥"
            self.children[trap_index].style = discord.ButtonStyle.red
            self.children[trap_index].disabled = False

        if self.gold_index is not None:
            self.children[self.gold_index].label = "🟨"
            self.children[self.gold_index].style = discord.ButtonStyle.blurple
            self.children[self.gold_index].disabled = False

    async def start_hit_round(self):
        self.round_active = True
        self.round_token += 1
        token = self.round_token

        # 초록 버튼은 기다리지 않고 계속 뜨며, 5초 안에 눌러야 함.
        # 라운드가 살아있는 동안 2초마다 초록 버튼 위치와 판이 다시 바뀜.
        total_time = 5
        move_interval = 2
        elapsed = 0

        while elapsed < total_time:
            if not self.round_active or token != self.round_token:
                return

            if self.gauge >= self.max_gauge:
                await self.success()
                return

            message = random.choice(FISH_ACTION_MESSAGES)
            self.last_event_text = message
            self.apply_battle_message_effect(message)

            if self.gauge >= self.max_gauge:
                await self.success()
                return

            self.setup_round_buttons()

            effect_text = f"\n{self.last_event_effect}" if self.last_event_effect else ""
            gold_text = "\n🟨 황금 칸: 누르면 남은 타이밍 무시 + 게이지 2배 증가!" if self.gold_index is not None else ""
            remaining = total_time - elapsed

            await self.message.edit(
                content=(
                    f"🎣 **지금이다!**\n\n"
                    f"{message}{effect_text}\n\n"
                    f"**{remaining}초 안에** 초록 칸을 누르자!{gold_text}\n"
                    f"초록 칸 위치는 **2초마다 변경**됨.\n"
                    f"게이지: {make_gauge_bar(self.gauge, self.max_gauge)}\n"
                    f"이번 타이밍: **{self.hit_count}/{self.need_hits}**\n"
                    f"실수: **{self.fail_count}/3**"
                ),
                view=self
            )

            sleep_time = min(move_interval, total_time - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time

        if self.round_active and token == self.round_token:
            self.fail_count += 1
            self.round_active = False
            self.reset_buttons(disabled=True)

            if self.fail_count >= 3:
                await self.fail()
                return

            await self.message.edit(
                content=(
                    f"⏱️ 너무 늦었다!\n"
                    f"실수: **{self.fail_count}/3**\n\n"
                    f"바로 다음 타이밍으로 넘어간다!"
                ),
                view=self
            )

            await asyncio.sleep(0.5)
            await self.start_hit_round()

    async def add_gauge(self, multiplier=1):
        rod = ROD_DATA.get(self.rod_name, ROD_DATA["기본 낚싯대"])
        bonus = rod.get("gauge_bonus", 0)

        base_add = random.randint(10, 25) + bonus
        add = base_add * multiplier
        self.gauge = min(self.max_gauge, self.gauge + add)

        self.hit_count = 0
        self.need_hits = random.randint(1, 3)

        if self.gauge >= self.max_gauge:
            await self.success()
            return

        multiplier_text = "\n🟨 황금 칸 보너스: **2배 적용!**" if multiplier > 1 else ""

        await self.message.edit(
            content=(
                f"✅ 제대로 감았다!\n"
                f"🎣 낚싯대 보너스: +{bonus}{multiplier_text}\n"
                f"게이지가 **{add}** 올랐다.\n\n"
                f"게이지: {make_gauge_bar(self.gauge, self.max_gauge)}"
            ),
            view=self
        )

        await asyncio.sleep(0.5)
        await self.start_hit_round()

    async def success(self):
        caught_text = []
        caught_fish = []

        for fish_name in self.fish_list:
            fish = make_fish(self.user_id, fish_name)
            caught_fish.append(fish)

            trait_text = ""
            if fish["trait"]:
                trait_text = f"\n특성: **{fish['trait']}**"

            caught_text.append(
                f"잡은 물고기: **{fish['display_name']}**\n"
                f"무게: **{fish['kg']}kg**\n"
                f"기본 판매가: **{money(fish['price'])}**\n"
                f"{get_market_text(fish['name'])}\n"
                f"현재 판매가: **{money(get_market_price(fish['name'], fish['price']))}**"
                f"{trait_text}"
            )

        chest_name = roll_fishing_chest(self.user_id)
        chest_text = f"\n\n📦 추가 보상: **{chest_name}** 획득! `/상자열기 {chest_name}`로 열 수 있음." if chest_name else ""

        save_data()

        lost_rewards = globals().get("LOST_ITEM_REWARDS", {})
        lost_items = [
            fish for fish in caught_fish
            if fish["name"] in lost_rewards
        ]

        if len(lost_items) == 1 and "LostItemReturnView" in globals():
            lost_item = lost_items[0]
            view = LostItemReturnView(self.user_id, lost_item)

            await self.message.edit(
                content=(
                    f"🎣 **낚시 성공!**\n\n"
                    f"사용 낚싯대: **{self.rod_name}**\n"
                    f"사용 미끼: **{self.bait_name}**\n\n"
                    + "\n\n".join(caught_text)
                    + chest_text
                    + "\n\n📦 뭔가 귀중품 같다...\n"
                    f"**{lost_item['display_name']}**의 주인을 찾을까?"
                ),
                view=view
            )
            self.stop()
            return

        await self.message.edit(
            content=(
                f"🎣 **낚시 성공!**\n\n"
                f"사용 낚싯대: **{self.rod_name}**\n"
                f"사용 미끼: **{self.bait_name}**\n\n"
                + "\n\n".join(caught_text)
                + chest_text
            ),
            view=None
        )

        self.stop()
        return

    async def fail(self):
        await self.message.edit(
            content="🐟 실수를 너무 많이 해서 물고기가 도망쳤다...",
            view=None
        )
        self.stop()
        return

    async def on_timeout(self):
        await self.fail()


class FishGaugeButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(
            label="⬛",
            style=discord.ButtonStyle.gray,
            row=0
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: FishBattleView = self.view

        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ 니 물고기 아님.", ephemeral=True)
            return

        if not view.round_active:
            await interaction.response.send_message("❌ 이미 지나간 타이밍이다.", ephemeral=True)
            return

        if self.index in view.trap_indices:
            view.fail_count += 1
            view.round_active = False
            view.round_token += 1
            view.reset_buttons(disabled=True)

            if view.fail_count >= 3:
                await interaction.response.defer()
                await view.fail()
                return

            await interaction.response.edit_message(
                content=(
                    f"💥 실수했다!\n"
                    f"빨간 칸을 눌러버렸다...\n\n"
                    f"실수: **{view.fail_count}/3**\n"
                    f"다시 시도하자."
                ),
                view=view
            )

            await asyncio.sleep(0.5)
            await view.start_hit_round()
            return

        if self.index == view.gold_index:
            view.round_active = False
            view.round_token += 1
            view.hit_count = view.need_hits
            view.reset_buttons(disabled=True)

            await interaction.response.defer()
            await view.add_gauge(multiplier=2)
            return

        if self.index != view.target_index:
            # 검은 칸은 disabled=True라 보통 여기까지 못 오지만,
            # 혹시 UI 상태가 꼬였을 때도 아무 변화 없이 응답만 처리.
            await interaction.response.defer()
            return

        view.round_active = False
        view.round_token += 1
        view.hit_count += 1
        view.reset_buttons(disabled=True)

        if view.hit_count >= view.need_hits:
            await interaction.response.defer()
            await view.add_gauge()
            return

        await interaction.response.edit_message(
            content=(
                f"✅ 초록 칸을 눌렀다!\n"
                f"연속으로 더 잡아당겨야 한다.\n\n"
                f"게이지: {make_gauge_bar(view.gauge, view.max_gauge)}\n"
                f"이번 타이밍: **{view.hit_count}/{view.need_hits}**"
            ),
            view=view
        )

        await asyncio.sleep(0.5)
        await view.start_hit_round()


# =========================
# 보스 낚시
# =========================

class BossFishingView(discord.ui.View):
    def __init__(self, user_id, boss_name, rod_name, bait_name):
        super().__init__(timeout=40)
        self.user_id = user_id
        self.boss_name = boss_name
        self.rod_name = rod_name
        self.bait_name = bait_name

        self.required_hits = random.randint(5, 12)
        self.current_hits = 0
        self.target_index = None
        self.failed = False
        self.message = None

        for i in range(9):
            self.add_item(BossFishingButton(i))

    async def start_round(self):
        while self.current_hits < self.required_hits and not self.failed:
            self.target_index = random.randint(0, 8)

            for item in self.children:
                item.label = "⬛"
                item.style = discord.ButtonStyle.gray
                item.disabled = False

            self.children[self.target_index].label = "🟩"
            self.children[self.target_index].style = discord.ButtonStyle.green

            await self.message.edit(
                content=(
                    f"🐲 **보스 출현: {self.boss_name}**\n\n"
                    f"초록 칸을 3초 안에 눌러!\n"
                    f"진행도: **{self.current_hits}/{self.required_hits}**"
                ),
                view=self
            )

            before = self.current_hits
            await asyncio.sleep(3)

            if self.current_hits == before:
                await self.fail_boss("시간 초과")
                return

        if not self.failed:
            await self.success_boss()

    async def fail_boss(self, reason):
        self.failed = True

        for item in self.children:
            item.disabled = True

        await self.message.edit(
            content=(
                f"💀 **{self.boss_name} 도주**\n\n"
                f"사유: **{reason}**\n"
                f"진행도: **{self.current_hits}/{self.required_hits}**"
            ),
            view=self
        )

        self.stop()
        return

    async def success_boss(self):
        fish = make_fish(self.user_id, self.boss_name)
        chest_name = roll_fishing_chest(self.user_id)
        chest_text = f"\n\n📦 추가 보상: **{chest_name}** 획득! `/상자열기 {chest_name}`로 열 수 있음." if chest_name else ""
        save_data()

        for item in self.children:
            item.disabled = True

        trait_text = ""
        if fish["trait"]:
            trait_text = f"\n특성: **{fish['trait']}**"

        await self.message.edit(
            content=(
                f"🔥🐲 **보스 낚시 성공!**\n\n"
                f"잡은 보스: **{fish['display_name']}**\n"
                f"무게: **{fish['kg']}kg**\n"
                f"기본 판매가: **{money(fish['price'])}**\n"
                f"{get_market_text(fish['name'])}\n"
                f"현재 판매가: **{money(get_market_price(fish['name'], fish['price']))}**"
                f"{trait_text}\n\n"
                f"사용 낚싯대: **{self.rod_name}**\n"
                f"사용 미끼: **{self.bait_name}**"
                f"{chest_text}"
            ),
            view=None
        )

        self.stop()
        return


class BossFishingButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(
            label="⬛",
            style=discord.ButtonStyle.gray,
            row=index // 3
        )
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: BossFishingView = self.view

        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ 니 보스 아님.", ephemeral=True)
            return

        if self.index != view.target_index:
            await interaction.response.defer()
            await view.fail_boss("잘못된 칸 클릭")
            return

        view.current_hits += 1
        view.target_index = None

        for item in view.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                f"✅ 명중!\n\n"
                f"보스: **{view.boss_name}**\n"
                f"진행도: **{view.current_hits}/{view.required_hits}**"
            ),
            view=view
        )


# =========================
# 낚시 성공 처리
# =========================

async def fishing_success(interaction: discord.Interaction):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_tank(user_id)
    get_fishing_gear(user_id)
    update_fish_market()

    if random.randint(1, 100) == 1:
        stolen = int(money_data[user_id] * 0.05)
        money_data[user_id] -= stolen
        save_data()

        await interaction.response.edit_message(
            content=(
                f"🐟💀 간고등어 출현\n\n"
                f"간고등어가 당신의 지갑을 물고 튀었다..\n"
                f"💸 -{money(stolen)}\n\n"
                f"현재 잔액: **{money(money_data[user_id])}**"
            ),
            view=None
        )
        return

    rod_name = equipped_rods.get(user_id, "기본 낚싯대")
    bait_name = equipped_baits.get(user_id, "미끼 없음")

    rod = ROD_DATA.get(rod_name, ROD_DATA["기본 낚싯대"])
    bait = BAIT_DATA.get(bait_name, BAIT_DATA["미끼 없음"])

    luck_bonus = rod["luck"] + bait["luck"]

    def use_bait():
        if bait_name != "미끼 없음":
            owned_baits[user_id][bait_name] -= 1

            if owned_baits[user_id][bait_name] <= 0:
                del owned_baits[user_id][bait_name]
                equipped_baits[user_id] = "미끼 없음"

    first_fish = pick_fish(luck_bonus)

    use_bait()
    save_data()

    if first_fish in BOSS_FISH:
        view = BossFishingView(user_id, first_fish, rod_name, bait_name)

        await interaction.response.edit_message(
            content=(
                f"🌊⚠️ **수면 아래에서 거대한 그림자가 움직인다...**\n\n"
                f"🐲 보스 몹 **{first_fish}** 출현!\n"
                f"잠시 후 9칸 보스전 시작."
            ),
            view=view
        )

        view.message = await interaction.original_response()
        asyncio.create_task(view.start_round())
        return

    catch_count = 1
    roll = random.uniform(0, 100)

    if roll <= rod.get("triple_chance", 0):
        catch_count = 3
    elif roll <= rod.get("triple_chance", 0) + rod.get("double_chance", 0):
        catch_count = 2

    fish_list = [first_fish]

    for _ in range(catch_count - 1):
        fish_name = pick_fish(luck_bonus)

        while fish_name in BOSS_FISH:
            fish_name = pick_fish(luck_bonus)

        fish_list.append(fish_name)

    bonus_text = ""

    if catch_count == 3:
        bonus_text = "\n🌊🔥 **트리플 낚시 발동!**"
    elif catch_count == 2:
        bonus_text = "\n🔥 **더블 낚시 발동!**"

    main_fish = fish_list[0]
    main_fish_data = FISH_DATA[main_fish]
    max_gauge = random.randint(
        int(main_fish_data.get("gauge_min", 100)),
        int(main_fish_data.get("gauge_max", 100))
    )

    view = FishBattleView(user_id, fish_list, rod_name, bait_name, max_gauge)

    await interaction.response.edit_message(
        content=(
            f"🌊 물고기가 걸렸다...{bonus_text}\n"
            f"상황에 맞게 대응해야 한다!"
        ),
        view=view
    )

    view.message = await interaction.original_response()
    asyncio.create_task(view.start_battle())

# =========================
# 뽑기 / 상자 선택 설정
# =========================

PITY_LIMIT = 50
PITY_CHEST = "심해의 보물 상자"

GACHA_COUNT_CHOICES = [
    app_commands.Choice(name="1회", value=1),
    app_commands.Choice(name="10회", value=10),
    app_commands.Choice(name="30회", value=30),
    app_commands.Choice(name="50회", value=50),
    app_commands.Choice(name="100회", value=100),
]


def get_gacha_pity(user_id):
    uid = str(user_id)
    if uid not in gacha_pity:
        gacha_pity[uid] = 0
        save_data()
    return int(gacha_pity[uid])


def roll_gacha_chest_with_pity(user_id):
    uid = str(user_id)
    gacha_pity[uid] = int(gacha_pity.get(uid, 0)) + 1

    if gacha_pity[uid] >= PITY_LIMIT:
        gacha_pity[uid] = 0
        save_data()
        return PITY_CHEST

    chest_name = roll_gacha_chest()

    if chest_name == PITY_CHEST:
        gacha_pity[uid] = 0

    save_data()
    return chest_name


async def chest_autocomplete(interaction: discord.Interaction, current: str):
    try:
        user_id = interaction.user.id
        bag = get_item_bag(user_id)
        current_lower = (current or "").lower()

        choices = []
        for item_name, count in sorted(bag.items()):
            if int(count) <= 0:
                continue
            if ITEM_DATA.get(item_name, {}).get("type") != "chest":
                continue
            if current_lower and current_lower not in item_name.lower():
                continue
            choices.append(app_commands.Choice(
                name=f"{item_name} x{count}",
                value=item_name
            ))

        return choices[:25]

    except Exception as e:
        print(f"[상자 자동완성 오류] {repr(e)}")
        return []


async def chest_count_autocomplete(interaction: discord.Interaction, current: str):
    try:
        user_id = interaction.user.id
        bag = get_item_bag(user_id)
        selected_chest = getattr(interaction.namespace, "상자", None)

        if not selected_chest:
            return []

        owned_count = int(bag.get(selected_chest, 0))
        if owned_count <= 0:
            return []

        counts = [1, 5, 10, 30, 50, 100]
        counts = [c for c in counts if c <= owned_count]

        if owned_count not in counts:
            counts.append(owned_count)

        current_text = str(current or "")
        choices = []
        for count in counts:
            if current_text and current_text not in str(count):
                continue
            choices.append(app_commands.Choice(
                name=f"{count}개 열기",
                value=count
            ))

        return choices[:25]

    except Exception as e:
        print(f"[상자 갯수 자동완성 오류] {repr(e)}")
        return []


async def sell_item_autocomplete(interaction: discord.Interaction, current: str):
    try:
        user_id = interaction.user.id
        bag = get_item_bag(user_id)
        current_lower = (current or "").lower()

        choices = []
        for item_name, count in sorted(bag.items()):
            count = int(count)
            if count <= 0:
                continue
            if item_name not in ITEM_DATA:
                continue
            if current_lower and current_lower not in item_name.lower():
                continue

            data = ITEM_DATA.get(item_name, {})
            type_text = "상자" if data.get("type") == "chest" else "재료"
            price = int(data.get("price", 0))

            choices.append(app_commands.Choice(
                name=f"{item_name} x{count} / {type_text} / 개당 {money(price)}",
                value=item_name
            ))

        return choices[:25]

    except Exception as e:
        print(f"[아이템 판매 자동완성 오류] {repr(e)}")
        return []


async def sell_item_count_autocomplete(interaction: discord.Interaction, current: str):
    try:
        user_id = interaction.user.id
        bag = get_item_bag(user_id)
        selected_item = getattr(interaction.namespace, "아이템", None)

        if not selected_item:
            return []

        owned_count = int(bag.get(selected_item, 0))
        if owned_count <= 0:
            return []

        counts = [1, 5, 10, 30, 50, 100]
        counts = [c for c in counts if c <= owned_count]

        if owned_count not in counts:
            counts.append(owned_count)

        current_text = str(current or "")
        choices = []
        for count in counts:
            if current_text and current_text not in str(count):
                continue
            choices.append(app_commands.Choice(
                name=f"{count}개 팔기",
                value=count
            ))

        return choices[:25]

    except Exception as e:
        print(f"[아이템 판매 갯수 자동완성 오류] {repr(e)}")
        return []

# =========================
# 명령어
# =========================

@bot.tree.command(name="낚시", description="버튼 타이밍에 맞춰 물고기를 낚는다", guild=GUILD)
async def fishing(interaction: discord.Interaction):
    user_id = interaction.user.id
    now = datetime.now()

    get_wallet(user_id)
    get_tank(user_id)
    get_fishing_gear(user_id)

    cooldown = fishing_cooldowns.get(user_id)

    if cooldown and now < cooldown:
        remain = int((cooldown - now).total_seconds())
        await interaction.response.send_message(
            f"🎣 아직 낚시 준비중임. {remain}초 남음.",
            ephemeral=True
        )
        return

    fishing_cooldowns[user_id] = now + FISHING_COOLDOWN
    save_data()

    view = FishingButtonView(user_id)

    await interaction.response.send_message(
        "🎣 낚싯대를 던졌다...\n상태를 잘 보다가 **지금이다!**가 뜨면 초록 버튼을 누르자!",
        view=view
    )

    view.message = await interaction.original_response()
    asyncio.create_task(view.start_waiting())


@bot.tree.command(name="어항", description="내가 잡은 물고기 목록 확인", guild=GUILD)
async def fish_tank(interaction: discord.Interaction):
    user_id = interaction.user.id
    get_tank(user_id)
    update_fish_market()

    tank = fish_tanks[user_id]

    if not tank:
        await interaction.response.send_message("🐠 어항이 비어있다.")
        return

    grouped = {}
    total_value = 0

    for fish in tank:
        base_name = fish.get("name", "알 수 없음")
        trait = fish.get("trait")
        display_name = fish.get("display_name") or (f"{trait} {base_name}" if trait else base_name)
        kg = fish.get("kg", 0)
        price = get_market_price(base_name, fish.get("price", 0))
        total_value += price

        key = (base_name, trait)
        if key not in grouped:
            grouped[key] = {
                "display_name": display_name,
                "count": 0,
                "kg": 0,
                "price": 0,
            }

        grouped[key]["count"] += 1
        grouped[key]["kg"] += kg
        grouped[key]["price"] += price

    lines = []

    for (base_name, trait), info in sorted(grouped.items(), key=lambda x: x[1]["display_name"]):
        lines.append(
            f"🐟 **{info['display_name']}** x{info['count']}마리 / "
            f"총 {info['kg']:.2f}kg / 현재 판매가 {money(info['price'])}"
        )

    save_data()

    header = f"🐠 **내 어항** | 총 {len(tank)}마리 / 묶음 {len(grouped)}개 / 예상가 {money(total_value)}\n\n"
    content = header + "\n".join(lines)

    if len(content) <= 2000:
        await interaction.response.send_message(content)
        return

    file = discord.File(
        BytesIO(content.encode("utf-8")),
        filename=f"fish_tank_{user_id}.txt"
    )
    await interaction.response.send_message("📄 어항 목록이 길어서 txt 파일로 뽑았음.", file=file)

@bot.tree.command(name="상세어항", description="물고기 상세 정보를 txt 파일로 확인한다", guild=GUILD)
async def detail_fish_tank(interaction: discord.Interaction):
    user_id = interaction.user.id
    get_tank(user_id)
    update_fish_market()

    tank = fish_tanks[user_id]

    if not tank:
        await interaction.response.send_message("🐠 어항이 비어있다.")
        return

    lines = ["🐠 물고기 상세 어항", ""]

    for fish in tank:
        name = get_item_display_name(fish, fish.get("name", "알 수 없음"))
        trait = fish.get("trait") or "특성 없음"
        kg = fish.get("kg", 0)
        price = get_market_price(fish.get("name", name), fish.get("price", 0))

        lines.append(
            f"{name} | [{trait}] | {kg:.2f}kg | {money(price)}"
        )

    save_data()
    content = "\n".join(lines)

    file = discord.File(
        BytesIO(content.encode("utf-8")),
        filename=f"fish_tank_detail_{user_id}.txt"
    )
    await interaction.response.send_message("📄 물고기 상세 어항을 txt 파일로 뽑았음.", file=file)


@bot.tree.command(name="팔기", description="물고기를 판매한다.", guild=GUILD)
@app_commands.describe(
    물고기="판매할 물고기 이름",
    갯수="판매할 갯수"
)
async def sell_fish(interaction: discord.Interaction, 물고기: str, 갯수: int):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_tank(user_id)
    update_fish_market()

    if 갯수 <= 0:
        await interaction.response.send_message("❌ 1마리 이상 팔아야 한다.", ephemeral=True)
        return

    owned = [
        fish for fish in fish_tanks[user_id]
        if fish.get("display_name", fish["name"]) == 물고기
        or fish["name"] == 물고기
    ]

    if len(owned) < 갯수:
        await interaction.response.send_message(
            f"❌ {물고기} 부족함.\n보유: {len(owned)}마리",
            ephemeral=True
        )
        return

    sell_list = owned[:갯수]
    total_price = sum(
        get_market_price(fish["name"], fish["price"])
        for fish in sell_list
    )

    removed = 0
    new_tank = []

    for fish in fish_tanks[user_id]:
        same_fish = (
            fish.get("display_name", fish["name"]) == 물고기
            or fish["name"] == 물고기
        )

        if same_fish and removed < 갯수:
            removed += 1
            continue

        new_tank.append(fish)

    fish_tanks[user_id] = new_tank
    money_data[user_id] += total_price
    save_data()

    await interaction.response.send_message(
        f"💰 판매 완료!\n\n"
        f"판매 물고기: **{물고기}**\n"
        f"판매 수량: **{갯수}마리**\n"
        f"획득 금액: **{money(total_price)}**\n\n"
        f"현재 잔액: **{money(money_data[user_id])}**"
    )


@bot.tree.command(name="전체팔기", description="어항에 있는 모든 물고기를 판매한다.", guild=GUILD)
async def sell_all_fish(interaction: discord.Interaction):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_tank(user_id)
    update_fish_market()

    tank = fish_tanks[user_id]

    if not tank:
        await interaction.response.send_message("🐠 어항이 비어있다.", ephemeral=True)
        return

    total_price = sum(
        get_market_price(fish["name"], fish["price"])
        for fish in tank
    )

    total_count = len(tank)

    count_data = {}

    for fish in tank:
        name = fish.get("display_name", fish["name"])
        count_data[name] = count_data.get(name, 0) + 1

    fish_tanks[user_id] = []
    money_data[user_id] += total_price
    save_data()

    sold_text = "\n".join(
        f"{name}: {count}마리"
        for name, count in count_data.items()
    )

    await interaction.response.send_message(
        f"💰 **전체 판매 완료!**\n\n"
        f"{sold_text}\n\n"
        f"판매 수량: **{total_count}마리**\n"
        f"획득 금액: **{money(total_price)}**\n\n"
        f"현재 잔액: **{money(money_data[user_id])}**"
    )



@bot.tree.command(name="가방", description="보유한 제작 재료와 상자를 확인한다", guild=GUILD)
async def my_items(interaction: discord.Interaction):
    user_id = interaction.user.id
    get_item_bag(user_id)

    bag = item_bags[str(user_id)]

    if not bag:
        await interaction.response.send_message("🎒 아이템 가방이 비어있다.")
        return

    lines = []
    total_value = 0

    for name, count in sorted(bag.items()):
        data = ITEM_DATA.get(name, {"price": 0, "grade": "알 수 없음", "type": "unknown"})
        price = int(data.get("price", 0)) * int(count)
        total_value += price
        type_text = "상자" if data.get("type") == "chest" else "재료"
        lines.append(
            f"📦 **{name}** x{count} / {type_text} / {data.get('grade', '알 수 없음')} / 판매가 {money(price)}"
        )

    content = (
        f"🎒 **내 아이템** | 종류 {len(bag)}개 / 예상가 {money(total_value)}\n\n"
        + "\n".join(lines)
    )

    if len(content) <= 2000:
        await interaction.response.send_message(content)
        return

    file = discord.File(BytesIO(content.encode("utf-8")), filename=f"items_{user_id}.txt")
    await interaction.response.send_message("📄 아이템 목록이 길어서 txt 파일로 뽑았음.", file=file)


@bot.tree.command(name="상자열기", description="보유한 재료 상자를 연다", guild=GUILD)
@app_commands.describe(상자="열 상자를 선택하세요", 갯수="열 갯수를 선택하세요")
@app_commands.autocomplete(상자=chest_autocomplete, 갯수=chest_count_autocomplete)
async def open_chest(
    interaction: discord.Interaction,
    상자: str,
    갯수: int = 1
):
    user_id = interaction.user.id
    bag = get_item_bag(user_id)

    if 갯수 <= 0:
        await interaction.response.send_message("❌ 1개 이상 열어야 함.", ephemeral=True)
        return

    if 상자 not in CHEST_DROP_TABLE or ITEM_DATA.get(상자, {}).get("type") != "chest":
        await interaction.response.send_message("❌ 열 수 있는 상자가 아님.", ephemeral=True)
        return

    owned_count = int(bag.get(상자, 0))

    if owned_count <= 0:
        await interaction.response.send_message(
            f"❌ **{상자}**를 보유하고 있지 않음.",
            ephemeral=True
        )
        return

    if owned_count < 갯수:
        await interaction.response.send_message(
            f"❌ 상자가 부족함.\n"
            f"보유: **{owned_count}개**\n"
            f"요청: **{갯수}개**",
            ephemeral=True
        )
        return

    results = {}

    for _ in range(갯수):
        item_name = open_chest_once(user_id, 상자)
        if item_name is None:
            break
        results[item_name] = results.get(item_name, 0) + 1

    remaining = get_item_count(user_id, 상자)

    result_text = "\n".join(
        f"🧩 **{name}** x{amount}"
        for name, amount in sorted(results.items())
    ) if results else "없음"

    await interaction.response.send_message(
        f"📦 **상자 개봉 완료!**\n\n"
        f"상자: **{상자}**\n"
        f"개봉 수: **{sum(results.values())}개**\n"
        f"남은 상자: **{remaining}개**\n\n"
        f"획득:\n{result_text}"
    )
@bot.tree.command(name="팔기2", description="아이템을 판매한다", guild=GUILD)
@app_commands.describe(아이템="판매할 아이템을 선택하세요", 갯수="판매할 갯수를 선택하세요")
@app_commands.autocomplete(아이템=sell_item_autocomplete, 갯수=sell_item_count_autocomplete)
async def sell_item(interaction: discord.Interaction, 아이템: str, 갯수: int = 1):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_item_bag(user_id)

    if 아이템 not in ITEM_DATA:
        await interaction.response.send_message("❌ 그런 아이템은 없음.", ephemeral=True)
        return

    if 갯수 <= 0:
        await interaction.response.send_message("❌ 1개 이상 팔아야 한다.", ephemeral=True)
        return

    have = get_item_count(user_id, 아이템)

    if have < 갯수:
        await interaction.response.send_message(
            f"❌ {아이템} 부족함.\n보유: **{have}개**",
            ephemeral=True
        )
        return

    total_price = int(ITEM_DATA[아이템]["price"]) * 갯수
    remove_item(user_id, 아이템, 갯수)
    money_data[str(user_id)] += total_price
    save_data()

    await interaction.response.send_message(
        f"💰 아이템 판매 완료!\n\n"
        f"판매 아이템: **{아이템}**\n"
        f"판매 수량: **{갯수}개**\n"
        f"획득 금액: **{money(total_price)}**\n\n"
        f"현재 잔액: **{money(money_data[str(user_id)])}**"
    )


@bot.tree.command(name="전체팔기2", description="보유한 모든 아이템을 판매한다", guild=GUILD)
async def sell_all_items(interaction: discord.Interaction):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_item_bag(user_id)

    bag = item_bags[str(user_id)]

    if not bag:
        await interaction.response.send_message("🎒 아이템 가방이 비어있다.", ephemeral=True)
        return

    total_price = 0
    sold_lines = []

    for name, count in list(bag.items()):
        if name not in ITEM_DATA:
            continue
        price = int(ITEM_DATA[name]["price"]) * int(count)
        total_price += price
        sold_lines.append(f"{name}: {count}개")

    if total_price <= 0:
        await interaction.response.send_message("❌ 판매 가능한 아이템이 없음.", ephemeral=True)
        return

    item_bags[str(user_id)] = {}
    money_data[str(user_id)] += total_price
    save_data()

    sold_text = "\n".join(sold_lines)

    await interaction.response.send_message(
        f"💰 **아이템 전체 판매 완료!**\n\n"
        f"{sold_text}\n\n"
        f"획득 금액: **{money(total_price)}**\n\n"
        f"현재 잔액: **{money(money_data[str(user_id)])}**"
    )



FISH_DEX_PAGE_SIZE = 8


class FishDexJumpModal(discord.ui.Modal, title="도감 페이지 이동"):
    page = discord.ui.TextInput(label="이동할 페이지 번호", placeholder="예: 3", required=True, max_length=4)

    def __init__(self, dex_view):
        super().__init__()
        self.dex_view = dex_view

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.dex_view.user_id:
            await interaction.response.send_message("❌ 니 도감 아님.", ephemeral=True)
            return

        try:
            page_num = int(str(self.page.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ 숫자로 입력해야 함.", ephemeral=True)
            return

        self.dex_view.page = max(0, min(self.dex_view.max_page - 1, page_num - 1))
        self.dex_view.mode = "list"
        self.dex_view.selected_fish = None
        self.dex_view.refresh_items()
        await interaction.response.edit_message(content=self.dex_view.render(), view=self.dex_view)


class FishDexNavButton(discord.ui.Button):
    def __init__(self, label, action):
        style = discord.ButtonStyle.danger if action == "close" else discord.ButtonStyle.gray
        super().__init__(label=label, style=style, row=4)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view: FishDexView = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ 니 도감 아님.", ephemeral=True)
            return

        if self.action == "prev":
            view.page = max(0, view.page - 1)
        elif self.action == "next":
            view.page = min(view.max_page - 1, view.page + 1)
        elif self.action == "jump":
            await interaction.response.send_modal(FishDexJumpModal(view))
            return
        elif self.action == "back":
            view.mode = "list"
            view.selected_fish = None
        elif self.action == "close":
            await interaction.response.edit_message(
                content="📖 도감을 닫았습니다.",
                view=None
            )
            return

        view.refresh_items()
        await interaction.response.edit_message(content=view.render(), view=view)

class FishDexFishButton(discord.ui.Button):
    def __init__(self, fish_name, caught, row):
        emoji = "✅" if caught else "❌"
        super().__init__(label=fish_name, emoji=emoji, style=discord.ButtonStyle.secondary, row=row)
        self.fish_name = fish_name

    async def callback(self, interaction: discord.Interaction):
        view: FishDexView = self.view
        if interaction.user.id != view.user_id:
            await interaction.response.send_message("❌ 니 도감 아님.", ephemeral=True)
            return

        view.mode = "detail"
        view.selected_fish = self.fish_name
        view.refresh_items()
        await interaction.response.edit_message(content=view.render(), view=view)


class FishDexView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.page = 0
        self.mode = "list"
        self.selected_fish = None
        self.fish_names = list(FISH_DATA.keys())
        self.max_page = max(1, (len(self.fish_names) + FISH_DEX_PAGE_SIZE - 1) // FISH_DEX_PAGE_SIZE)
        self.refresh_items()

    def user_dex(self):
        return fish_dex.get(self.user_id, set())

    def refresh_items(self):
        self.clear_items()

        if self.mode == "detail" and self.selected_fish:
            self.add_item(FishDexNavButton("뒤로가기", "back"))
            return

        start = self.page * FISH_DEX_PAGE_SIZE
        current = self.fish_names[start:start + FISH_DEX_PAGE_SIZE]
        dex = self.user_dex()

        for i, fish_name in enumerate(current):
            self.add_item(FishDexFishButton(fish_name, fish_name in dex, row=i // 2))

        prev_button = FishDexNavButton("<", "prev")
        page_button = FishDexNavButton(f"{self.page + 1}/{self.max_page}", "jump")
        next_button = FishDexNavButton(">", "next")

        prev_button.disabled = self.page <= 0
        next_button.disabled = self.page >= self.max_page - 1

        self.add_item(prev_button)
        self.add_item(page_button)
        self.add_item(next_button)

    def render(self):
        dex = self.user_dex()

        if self.mode == "detail" and self.selected_fish:
            return fish_detail_text(self.selected_fish, self.user_id)

        start = self.page * FISH_DEX_PAGE_SIZE
        current = self.fish_names[start:start + FISH_DEX_PAGE_SIZE]
        lines = []
        for fish_name in current:
            mark = "✅" if fish_name in dex else "❌"
            data = FISH_DATA[fish_name]
            lines.append(f"{mark} **{fish_name}** (포획 레벨: {data.get('catch_level', 1)}) | {data['habitat']}")

        return (
            f"📖 **물고기 도감**\n"
            f"등록: **{len(dex)}/{len(self.fish_names)}종**\n"
            f"페이지: **< {self.page + 1}/{self.max_page} >**\n\n"
            + "\n".join(lines)
            + "\n\n아래 버튼을 누르면 자세한 정보가 뜸."
        )


@bot.tree.command(name="도감", description="물고기 도감을 페이지로 확인한다", guild=GUILD)
async def fish_book(interaction: discord.Interaction):
    user_id = interaction.user.id
    get_tank(user_id)
    update_fish_market()

    view = FishDexView(user_id)
    await interaction.response.send_message(view.render(), view=view)


@bot.tree.command(name="물고기정보", description="물고기 정보를 확인한다", guild=GUILD)
@app_commands.describe(물고기="정보를 볼 물고기 이름")
async def fish_info(interaction: discord.Interaction, 물고기: str):
    if 물고기 not in FISH_DATA:
        await interaction.response.send_message("❌ 그런 물고기는 없음.", ephemeral=True)
        return

    await interaction.response.send_message(fish_detail_text(물고기, interaction.user.id))


@bot.tree.command(name="뽑기", description="돈을 써서 제작 재료 상자를 뽑는다", guild=GUILD)
@app_commands.describe(횟수="뽑기 횟수")
@app_commands.choices(횟수=GACHA_COUNT_CHOICES)
async def item_gacha(
    interaction: discord.Interaction,
    횟수: int = 1
):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_item_bag(user_id)

    total_price = GACHA_PRICE * 횟수

    if money_data[user_id] < total_price:
        await interaction.response.send_message(
            f"❌ 돈 부족.\n"
            f"필요 금액: **{money(total_price)}**\n"
            f"현재 잔액: **{money(money_data[user_id])}**",
            ephemeral=True
        )
        return

    money_data[user_id] -= total_price

    results = {}
    pity_hit = 0

    for _ in range(횟수):
        chest_name = roll_gacha_chest_with_pity(user_id)

        if chest_name == PITY_CHEST:
            pity_hit += 1

        add_item(user_id, chest_name, 1)

        results[chest_name] = results.get(chest_name, 0) + 1

    save_data()

    result_text = "\n".join(
        f"📦 **{name}** x{count}"
        for name, count in sorted(results.items())
    )

    current_pity = get_gacha_pity(user_id)

    msg = (
        f"🎰 **아이템 뽑기 완료!**\n\n"
        f"횟수: **{횟수}회**\n"
        f"사용 금액: **{money(total_price)}**\n\n"
        f"획득:\n{result_text}\n\n"
        f"📈 천장 진행도: **{current_pity}/{PITY_LIMIT}**\n"
        f"💰 현재 잔액: **{money(money_data[user_id])}**\n\n"
        f"상자는 `/상자열기` 로 열 수 있음."
    )

    if pity_hit > 0:
        msg += f"\n\n🔥 천장 발동 횟수: **{pity_hit}회**"

    await interaction.response.send_message(msg)



@bot.tree.command(name="고급뽑기", description="비싼 대신 좋은 상자 확률이 높은 제작 재료 상자 뽑기", guild=GUILD)
@app_commands.describe(횟수="고급 뽑기 횟수")
@app_commands.choices(횟수=GACHA_COUNT_CHOICES)
async def high_item_gacha(
    interaction: discord.Interaction,
    횟수: int = 1
):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_item_bag(user_id)

    total_price = HIGH_GACHA_PRICE * 횟수

    if money_data[user_id] < total_price:
        await interaction.response.send_message(
            f"❌ 돈 부족.\n"
            f"필요 금액: **{money(total_price)}**\n"
            f"현재 잔액: **{money(money_data[user_id])}**",
            ephemeral=True
        )
        return

    money_data[user_id] -= total_price

    results = {}

    for _ in range(횟수):
        chest_name = roll_high_gacha_chest()
        add_item(user_id, chest_name, 1)
        results[chest_name] = results.get(chest_name, 0) + 1

    save_data()

    result_text = "\n".join(
        f"📦 **{name}** x{count}"
        for name, count in sorted(results.items())
    )

    msg = (
        f"💎 **고급 아이템 뽑기 완료!**\n\n"
        f"횟수: **{횟수}회**\n"
        f"사용 금액: **{money(total_price)}**\n"
        f"천장: **없음**\n\n"
        f"획득:\n{result_text}\n\n"
        f"💰 현재 잔액: **{money(money_data[user_id])}**\n\n"
        f"상자는 `/상자열기` 로 열 수 있음."
    )

    await interaction.response.send_message(msg)

@bot.tree.command(name="어시장", description="현재 물고기 시세를 확인한다", guild=GUILD)
async def fish_market_command(interaction: discord.Interaction):
    update_fish_market()
    init_fish_market()

    sorted_market = sorted(
        fish_market.items(),
        key=lambda x: x[1],
        reverse=True
    )

    top = sorted_market[:5]
    bottom = sorted_market[-5:]

    top_text = "\n".join(
        f"📈 **{name}**: {int(rate * 100)}%"
        for name, rate in top
    )

    bottom_text = "\n".join(
        f"📉 **{name}**: {int(rate * 100)}%"
        for name, rate in bottom
    )

    await interaction.response.send_message(
        f"🏪 **현재 어시장 시세**\n\n"
        f"## 떡상 어종\n{top_text}\n\n"
        f"## 떡락 어종\n{bottom_text}\n\n"
        f"시세는 1시간마다 1~7% 변동됨.\n"
        f"최소 70%, 최대 200%."
    )


@bot.tree.command(name="낚시상점", description="낚싯대와 미끼를 구매한다", guild=GUILD)
@app_commands.describe(
    종류="낚싯대 또는 미끼",
    이름="구매할 낚싯대/미끼 이름",
    갯수="미끼 구매 수량"
)
async def fishing_shop(
    interaction: discord.Interaction,
    종류: str,
    이름: str,
    갯수: int = 1
):
    user_id = interaction.user.id

    get_wallet(user_id)
    get_fishing_gear(user_id)
    get_item_bag(user_id)

    if 종류 not in ["낚싯대", "미끼"]:
        await interaction.response.send_message(
            "❌ 종류는 `낚싯대` 또는 `미끼`로 입력해야 함.",
            ephemeral=True
        )
        return

    if 종류 == "낚싯대":
        if 이름 not in ROD_DATA or 이름 == "기본 낚싯대":
            await interaction.response.send_message("❌ 그런 낚싯대는 없음.", ephemeral=True)
            return

        if 이름 in owned_rods[user_id]:
            await interaction.response.send_message("❌ 이미 가진 낚싯대임.", ephemeral=True)
            return

        rod = ROD_DATA[이름]
        price = rod["price"]
        item_costs = rod.get("items", {})

        if money_data[user_id] < price:
            await interaction.response.send_message(
                f"❌ 돈 부족.\n필요 금액: {money(price)}\n현재 잔액: {money(money_data[user_id])}",
                ephemeral=True
            )
            return

        for item_name, need_count in item_costs.items():
            have_count = get_item_count(user_id, item_name)

            if have_count < need_count:
                await interaction.response.send_message(
                    f"❌ 제작 재료 부족.\n"
                    f"필요: **{item_name} x{need_count}**\n"
                    f"보유: **{have_count}개**",
                    ephemeral=True
                )
                return

        money_data[user_id] -= price

        for item_name, need_count in item_costs.items():
            remove_item(user_id, item_name, need_count)

        owned_rods[user_id].append(이름)
        equipped_rods[user_id] = 이름
        save_data()

        item_text = item_cost_text(item_costs)

        await interaction.response.send_message(
            f"🎣 낚싯대 구매 완료!\n\n"
            f"구매: **{이름}**\n"
            f"가격: **{money(price)}**\n"
            f"사용 재료: **{item_text}**\n"
            f"자동 장착됨.\n\n"
            f"현재 잔액: **{money(money_data[user_id])}**"
        )
        return

    if 종류 == "미끼":
        if 이름 not in BAIT_DATA or 이름 == "미끼 없음":
            await interaction.response.send_message("❌ 그런 미끼는 없음.", ephemeral=True)
            return

        if 갯수 <= 0:
            await interaction.response.send_message("❌ 1개 이상 구매해야 함.", ephemeral=True)
            return

        price = BAIT_DATA[이름]["price"] * 갯수

        if money_data[user_id] < price:
            await interaction.response.send_message(
                f"❌ 돈 부족.\n필요 금액: {money(price)}\n현재 잔액: {money(money_data[user_id])}",
                ephemeral=True
            )
            return

        money_data[user_id] -= price
        owned_baits[user_id][이름] = owned_baits[user_id].get(이름, 0) + 갯수
        equipped_baits[user_id] = 이름
        save_data()

        await interaction.response.send_message(
            f"🪱 미끼 구매 완료!\n\n"
            f"구매: **{이름} x{갯수}개**\n"
            f"가격: **{money(price)}**\n"
            f"자동 장착됨.\n\n"
            f"현재 잔액: **{money(money_data[user_id])}**"
        )


@bot.tree.command(name="낚시상점목록", description="낚시상점 판매 목록 확인", guild=GUILD)
async def fishing_shop_list(interaction: discord.Interaction):
    rod_lines = []

    for name, data in ROD_DATA.items():
        if name == "기본 낚싯대":
            continue

        item_text = item_cost_text(data.get("items", {}))

        rod_lines.append(
            f"**{name}**\n"
            f"가격: **{money(data['price'])}**\n"
            f"재료: **{item_text}**\n"
            f"운빨: **+{data['luck']}%**\n"
            f"시간 감소: **{data['time_reduce']}%**\n"
            f"더블 확률: **{data['double_chance']}%**\n"
            f"트리플 확률: **{data['triple_chance']}%**"
        )

    rod_text = "\n\n".join(rod_lines)

    bait_text = "\n".join(
        f"**{name}** - {money(data['price'])} / 희귀 확률 +{data['luck']}%"
        for name, data in BAIT_DATA.items()
        if name != "미끼 없음"
    )

    await interaction.response.send_message(
        f"🎣 **낚시상점 목록**\n\n"
        f"## 낚싯대\n{rod_text}\n\n"
        f"## 미끼\n{bait_text}\n\n"
        f"구매법: `/낚시상점 종류 이름 갯수`\n"
        f"예시: `/낚시상점 낚싯대 강태공의 낚싯대`\n"
        f"예시: `/낚시상점 미끼 지렁이 5`"
    )


@bot.tree.command(name="보유낚싯대", description="내가 가진 낚싯대를 확인한다", guild=GUILD)
async def my_rods(interaction: discord.Interaction):
    user_id = interaction.user.id
    get_fishing_gear(user_id)

    equipped = equipped_rods[user_id]

    text = []

    for rod_name in owned_rods[user_id]:
        rod = ROD_DATA[rod_name]
        mark = "✅ 장착중" if rod_name == equipped else ""

        text.append(
            f"{mark} **{rod_name}**\n"
            f"운빨 증가: **{rod['luck']}%**\n"
            f"잡히는 시간 감소율: **{rod['time_reduce']}%**\n"
            f"더블 확률: **{rod['double_chance']}%**\n"
            f"트리플 확률: **{rod['triple_chance']}%**"
        )

    await interaction.response.send_message(
        "🎣 **보유 낚싯대**\n\n" + "\n\n".join(text)
    )


@bot.tree.command(name="낚싯대", description="보유한 낚싯대를 장착한다", guild=GUILD)
@app_commands.describe(이름="장착할 낚싯대 이름")
async def equip_rod(interaction: discord.Interaction, 이름: str):
    user_id = interaction.user.id
    get_fishing_gear(user_id)

    if 이름 not in owned_rods[user_id]:
        await interaction.response.send_message("❌ 그 낚싯대는 보유중이 아님.", ephemeral=True)
        return

    equipped_rods[user_id] = 이름
    save_data()

    await interaction.response.send_message(
        f"🎣 낚싯대 장착 완료!\n현재 낚싯대: **{이름}**"
    )


@bot.tree.command(name="미끼", description="보유한 미끼를 장착하거나 목록을 확인한다", guild=GUILD)
@app_commands.describe(이름="장착할 미끼 이름. 비워두면 목록 확인")
async def equip_bait(interaction: discord.Interaction, 이름: str = None):
    user_id = interaction.user.id
    get_fishing_gear(user_id)

    if 이름 is None:
        bait_items = owned_baits[user_id]

        if not bait_items:
            bait_text = "보유 미끼 없음."
        else:
            bait_text = "\n".join(
                f"**{name}**: {count}개 / 희귀 확률 +{BAIT_DATA[name]['luck']}%"
                for name, count in bait_items.items()
            )

        await interaction.response.send_message(
            f"🪱 **보유 미끼**\n\n"
            f"현재 장착: **{equipped_baits[user_id]}**\n\n"
            f"{bait_text}\n\n"
            f"미끼 해제는 `/미끼 미끼 없음`"
        )
        return

    if 이름 == "미끼 없음":
        equipped_baits[user_id] = "미끼 없음"
        save_data()

        await interaction.response.send_message("🪱 미끼를 해제함.")
        return

    if 이름 not in BAIT_DATA:
        await interaction.response.send_message("❌ 그 미끼는 없음.", ephemeral=True)
        return

    if owned_baits[user_id].get(이름, 0) <= 0:
        await interaction.response.send_message("❌ 그 미끼는 보유중이 아님.", ephemeral=True)
        return

    equipped_baits[user_id] = 이름
    save_data()

    await interaction.response.send_message(
        f"🪱 미끼 장착 완료!\n현재 미끼: **{이름}**"
    )

LOST_ITEM_REWARDS = ["누군가의 지갑", "잃어버린 카드", "카시오 시계"]


class LostItemReturnView(discord.ui.View):
    def __init__(self, user_id, fish):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.fish = fish
        self.message = None

    @discord.ui.button(label="주인 찾기", style=discord.ButtonStyle.green)
    async def find_owner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 니가 주운 거 아님.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True

        wait_time = random.randint(100, 300)

        await interaction.response.edit_message(
            content=(
                f"🔎 **{self.fish['display_name']}**의 주인을 찾는 중...\n\n"
                f"⏳ 예상 시간: **{wait_time}초**"
            ),
            view=self
        )

        await asyncio.sleep(wait_time)

        reward = random.randint(100000, 5000000)

        get_wallet(self.user_id)
        money_data[self.user_id] += reward
        save_data()

        await interaction.edit_original_response(
            content=(
                f"🙇‍♂️ 주인이 찾아왔다!\n\n"
                f"“정말 감사합니다! 이거라도 받아주세요.”\n\n"
                f"🎁 보상금: **{money(reward)} **\n"
                f"현재 잔액: **{money(money_data[self.user_id])} **"
            ),
            view=None
        )

        self.stop()

    @discord.ui.button(label="그냥 보관하기", style=discord.ButtonStyle.gray)
    async def keep_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 니가 주운 거 아님.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content=f"🎒 **{self.fish['display_name']}**을 그냥 어항에 보관했다.",
            view=None
        )

        self.stop()

@bot.tree.command(name="지갑", description="내 잔액 확인", guild=GUILD)
async def check_maro(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    get_wallet(user_id)

    await interaction.response.send_message(
        f"💰 {interaction.user.mention}의 잔액: **{money(money_data[user_id])}**"
    )

@bot.tree.command(name="돈지급", description="유저에게 돈을 지급한다", guild=GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def give_maro(
    interaction: discord.Interaction,
    유저: discord.Member,
    금액: int
):
    if 금액 <= 0:
        await interaction.response.send_message("❌ 1원 이상 지급해야 함.", ephemeral=True)
        return

    add_maro(유저.id, 금액)

    await interaction.response.send_message(
        f"✅ {유저.mention}에게 **{money(금액)}** 지급 완료!\n"
        f"현재 잔액: **{money(money_data[str(유저.id)])}**"
    )
    
@bot.tree.command(name="어시장리셋", description="어시장 시세를 초기화한다", guild=GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def reset_fish_market(interaction: discord.Interaction):

    init_fish_market()

    for fish_name in FISH_DATA.keys():
        fish_market[fish_name] = 1.0

    global last_market_update
    last_market_update = datetime.now()

    save_data()

    text = "\n".join(
        f"{name}: 100%"
        for name in list(FISH_DATA.keys())[:10]
    )

    await interaction.response.send_message(
        f"🔄 **어시장 시세 초기화 완료!**\n\n"
        f"모든 물고기 시세가 **100%**로 초기화됨."
    )


@reset_fish_market.error
async def reset_fish_market_error(
    interaction: discord.Interaction,
    error
):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message(
            "❌ 관리자만 사용 가능.",
            ephemeral=True
        )

exchange_cooldowns = {}
EXCHANGE_COOLDOWN = timedelta(hours=12)

FURINA_DATA_FILE = "/data/data.json"
MORA_RATE = 100

def add_furina_mora(user_id, amount):
    uid = str(user_id)

    if not os.path.exists(FURINA_DATA_FILE):
        data = {
            "poker_money": {},
            "poker_last_claim": {},
            "favor": {},
            "memory": {},
            "characters": {}
        }
    else:
        with open(FURINA_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

    data.setdefault("poker_money", {})
    data["poker_money"][uid] = int(data["poker_money"].get(uid, 0)) + int(amount)

    with open(FURINA_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


@bot.tree.command(name="모라송금", description="오브 돈을 모라로 환전", guild=GUILD)
@app_commands.describe(금액="환전할 금액")
async def mora_transfer(interaction: discord.Interaction, 금액: int):
    uid = str(interaction.user.id)
    now = datetime.now()

    last = exchange_cooldowns.get(uid)
    if last:
        remain = EXCHANGE_COOLDOWN - (now - last)
        if remain.total_seconds() > 0:
            hours = int(remain.total_seconds() // 3600)
            minutes = int((remain.total_seconds() % 3600) // 60)

            await interaction.response.send_message(
                f"❌ 모라 송금 쿨타임 남음!\n⏳ {hours}시간 {minutes}분 후 가능",
                ephemeral=True
            )
            return

    if 금액 < MORA_RATE:
        await interaction.response.send_message(
            "❌ 최소 100원부터 환전 가능.",
            ephemeral=True
        )
        return

    wallet = get_wallet(uid)

    if wallet < 금액:
        await interaction.response.send_message(
            f"❌ 돈 부족. 현재 잔액: {money(wallet)}",
            ephemeral=True
        )
        return

    mora = 금액 // MORA_RATE
    used_money = mora * MORA_RATE

    remove_maro(uid, used_money)
    add_furina_mora(uid, mora)

    exchange_cooldowns[uid] = now

    await interaction.response.send_message(
        f"💱 {money(used_money)} → **{mora:,}모라** 송금 완료!"
    )

@bot.event
async def on_ready():
    await bot.tree.sync(guild=GUILD)
    print(f"{bot.user} 로그인 완료")
    
bot.run(TOKEN)
