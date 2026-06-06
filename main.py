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
    global fish_tanks, fish_dex
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
    return f"{int(amount):,} 마로"


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
        "price": 0, "ores": {},
        "luck": 0, "time_reduce": 0,
        "double_chance": 0, "triple_chance": 0,
        "gauge_bonus": 0
    },
    "초급 낚싯대": {
        "price": 150000, "ores": {"돌": 10, "구리": 7},
        "luck": 5, "time_reduce": 5,
        "double_chance": 2, "triple_chance": 0.1,
        "gauge_bonus": 3
    },
    "중급 낚싯대": {
        "price": 600000, "ores": {"구리": 10, "철광석": 10},
        "luck": 12, "time_reduce": 12,
        "double_chance": 5, "triple_chance": 1,
        "gauge_bonus": 5
    },
    "고급 낚싯대": {
        "price": 1300000, "ores": {"철광석": 40, "은광석": 15},
        "luck": 23, "time_reduce": 25,
        "double_chance": 8, "triple_chance": 2,
        "gauge_bonus": 10
    },
    "개쩌는 낚싯대": {
        "price": 3000000, "ores": {"금광석": 25, "다이아몬드": 5},
        "luck": 37, "time_reduce": 25,
        "double_chance": 10, "triple_chance": 5,
        "gauge_bonus": 15
    },
    "최상의 낚싯대": {
        "price": 8000000, "ores": {"사파이어": 7, "다이아몬드": 5, "에메랄드": 3},
        "luck": 55, "time_reduce": 30,
        "double_chance": 15, "triple_chance": 7,
        "gauge_bonus": 18
    },
    "장인의 낚싯대": {
        "price": 20000000, "ores": {"네더라이트": 2, "다이아몬드": 5, "철광석": 20},
        "luck": 75, "time_reduce": 40,
        "double_chance": 18, "triple_chance": 10,
        "gauge_bonus": 22
    },
    "엘프의 낚싯대": {
        "price": 60000000, "ores": {"레인보우 다이아몬드": 1, "네더라이트": 3, "에메랄드": 2},
        "luck": 100, "time_reduce": 45,
        "double_chance": 20, "triple_chance": 12,
        "gauge_bonus": 25
    },
    "강태공의 낚싯대": {
        "price": 180000000, "ores": {"레인보우 다이아몬드": 3, "레드 다이아몬드": 5, "네더라이트": 3},
        "luck": 235, "time_reduce": 55,
        "double_chance": 35, "triple_chance": 15,
        "gauge_bonus": 30
    },
    "신의 낚싯대": {
        "price": 500000000, "ores": {"신기루": 3, "레인보우 다이아몬드": 10, "우라늄": 1, "레드 다이아몬드": 3},
        "luck": 450, "time_reduce": 60,
        "double_chance": 40, "triple_chance": 30,
        "gauge_bonus": 40
    },
    "도로롱의 낚싯대": {
        "price": 800000000, "ores": {"신기루": 30},
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
        self.trap_index = None
        self.round_active = False
        self.round_token = 0

        for i in range(5):
            self.add_item(FishGaugeButton(i))

    async def start_battle(self):
        await self.wait_for_chance()

    async def wait_for_chance(self):
        self.round_active = False

        for item in self.children:
            item.label = "⬛"
            item.style = discord.ButtonStyle.gray
            item.disabled = True

        wait_time = random.randint(2, 6)

        for _ in range(wait_time):
            await self.message.edit(
                content=(
                    f"🎣 **물고기와 힘겨루기 중...**\n\n"
                    f"{random.choice(FISH_ACTION_MESSAGES)}\n\n"
                    f"게이지: {make_gauge_bar(self.gauge, self.max_gauge)}\n"
                    f"실수: **{self.fail_count}/3**"
                ),
                view=self
            )
            await asyncio.sleep(1)

        await self.start_hit_round()

    async def start_hit_round(self):
        self.round_active = True
        self.round_token += 1
        token = self.round_token

        self.target_index = random.randint(0, 4)
        self.trap_index = None

        if random.randint(1, 100) <= 25:
            possible = [i for i in range(5) if i != self.target_index]
            self.trap_index = random.choice(possible)

        for item in self.children:
            item.label = "⬛"
            item.style = discord.ButtonStyle.gray
            item.disabled = False

        self.children[self.target_index].label = "🟩"
        self.children[self.target_index].style = discord.ButtonStyle.green

        if self.trap_index is not None:
            self.children[self.trap_index].label = "🟥"
            self.children[self.trap_index].style = discord.ButtonStyle.red

        await self.message.edit(
            content=(
                f"🎣 **지금이다!**\n\n"
                f"3초 안에 초록 칸을 누르자!\n"
                f"게이지: {make_gauge_bar(self.gauge, self.max_gauge)}\n"
                f"이번 타이밍: **{self.hit_count}/{self.need_hits}**\n"
                f"실수: **{self.fail_count}/3**"
            ),
            view=self
        )

        await asyncio.sleep(3)

        if self.round_active and token == self.round_token:
            self.fail_count += 1
            self.round_active = False

            for item in self.children:
                item.disabled = True

            if self.fail_count >= 3:
                await self.fail()
                return

            await self.message.edit(
                content=(
                    f"⏱️ 너무 늦었다!\n"
                    f"실수: **{self.fail_count}/3**\n\n"
                    f"다시 타이밍을 기다리자..."
                ),
                view=self
            )

            await asyncio.sleep(1)
            await self.wait_for_chance()

    async def add_gauge(self):
        rod = ROD_DATA.get(self.rod_name, ROD_DATA["기본 낚싯대"])
        bonus = rod.get("gauge_bonus", 0)

        add = random.randint(10, 25) + bonus
        self.gauge = min(self.max_gauge, self.gauge + add)

        self.hit_count = 0
        self.need_hits = random.randint(1, 3)

        if self.gauge >= self.max_gauge:
            await self.success()
            return

        await self.message.edit(
            content=(
                f"✅ 제대로 감았다!\n"
                f"🎣 낚싯대 보너스: +{bonus}\n"
                f"게이지가 **{add}** 올랐다.\n\n"
                f"게이지: {make_gauge_bar(self.gauge, self.max_gauge)}"
            ),
            view=self
        )

        await asyncio.sleep(1)
        await self.wait_for_chance()

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
                f"기본 판매가: **{money(fish['price'])}원**\n"
                f"{get_market_text(fish['name'])}\n"
                f"현재 판매가: **{money(get_market_price(fish['name'], fish['price']))}원**"
                f"{trait_text}"
            )

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

        if self.index == view.trap_index:
            view.fail_count += 1
            view.round_active = False
            view.round_token += 1

            for item in view.children:
                item.disabled = True

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

            await asyncio.sleep(1)
            await view.wait_for_chance()
            return

        if self.index != view.target_index:
            await interaction.response.send_message("⬛ 빈 칸이다.", ephemeral=True)
            return

        view.round_active = False
        view.round_token += 1
        view.hit_count += 1

        for item in view.children:
            item.disabled = True

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
                f"기본 판매가: **{money(fish['price'])}원**\n"
                f"{get_market_text(fish['name'])}\n"
                f"현재 판매가: **{money(get_market_price(fish['name'], fish['price']))}원**"
                f"{trait_text}\n\n"
                f"사용 낚싯대: **{self.rod_name}**\n"
                f"사용 미끼: **{self.bait_name}**"
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
                f"💸 -{money(stolen)}원\n\n"
                f"현재 잔액: **{money(money_data[user_id])}원**"
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
    chance = FISH_DATA[main_fish]["chance"]

    if chance <= 1:
        max_gauge = random.randint(270, 470)
    elif chance <= 5:
        max_gauge = random.randint(120, 250)
    else:
        max_gauge = 100

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
            f"총 {info['kg']:.2f}kg / 현재 판매가 {money(info['price'])}원"
        )

    save_data()

    header = f"🐠 **내 어항** | 총 {len(tank)}마리 / 묶음 {len(grouped)}개 / 예상가 {money(total_value)}원\n\n"
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
            f"{name} | [{trait}] | {kg:.2f}kg | {money(price)}원"
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
        f"획득 금액: **{money(total_price)}원**\n\n"
        f"현재 잔액: **{money(money_data[user_id])}원**"
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
        f"획득 금액: **{money(total_price)}원**\n\n"
        f"현재 잔액: **{money(money_data[user_id])}원**"
    )


@bot.tree.command(name="도감", description="내가 잡아본 물고기 도감 확인", guild=GUILD)
async def fish_book(interaction: discord.Interaction):
    user_id = interaction.user.id
    get_tank(user_id)

    if not fish_dex[user_id]:
        await interaction.response.send_message("📖 아직 도감에 등록된 물고기가 없음.")
        return

    text = "\n".join(
        f"✅ {fish_name}"
        for fish_name in fish_dex[user_id]
    )

    await interaction.response.send_message(
        f"📖 **물고기 도감**\n\n{text}"
    )


@bot.tree.command(name="물고기정보", description="물고기 정보를 확인한다", guild=GUILD)
@app_commands.describe(물고기="정보를 볼 물고기 이름")
async def fish_info(interaction: discord.Interaction, 물고기: str):
    update_fish_market()

    if 물고기 not in FISH_DATA:
        await interaction.response.send_message("❌ 그런 물고기는 없음.", ephemeral=True)
        return

    data = FISH_DATA[물고기]

    await interaction.response.send_message(
        f"🐟 **{물고기} 정보**\n\n"
        f"무게 범위: **{data['min_kg']}kg ~ {data['max_kg']}kg**\n"
        f"서식지: **{data['habitat']}**\n"
        f"기본 판매가격: **{money(data['base_price'])}원**\n"
        f"kg당 추가 가격: **{money(data['kg_price'])}원**\n"
        f"{get_market_text(물고기)}\n\n"
        f"판매가 계산식:\n"
        f"`기본 가격 + kg × kg당 가격 × 현재 시세`"
    )


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
    get_mining(user_id)

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
        ore_costs = rod.get("ores", {})

        if money_data[user_id] < price:
            await interaction.response.send_message(
                f"❌ 돈 부족.\n필요 금액: {money(price)}원\n현재 잔액: {money(money_data[user_id])}원",
                ephemeral=True
            )
            return

        for ore_name, need_count in ore_costs.items():
            have_count = get_ore_count(user_id, ore_name)

            if have_count < need_count:
                await interaction.response.send_message(
                    f"❌ 광석 부족.\n"
                    f"필요: **{ore_name} x{need_count}**\n"
                    f"보유: **{have_count}개**",
                    ephemeral=True
                )
                return

        money_data[user_id] -= price

        for ore_name, need_count in ore_costs.items():
            remove_ore_from_bag(user_id, ore_name, need_count)

        owned_rods[user_id].append(이름)
        equipped_rods[user_id] = 이름
        save_data()

        ore_text = ", ".join(
            f"{ore} x{count}"
            for ore, count in ore_costs.items()
        )

        if not ore_text:
            ore_text = "없음"

        await interaction.response.send_message(
            f"🎣 낚싯대 구매 완료!\n\n"
            f"구매: **{이름}**\n"
            f"가격: **{money(price)}원**\n"
            f"사용 광석: **{ore_text}**\n"
            f"자동 장착됨.\n\n"
            f"현재 잔액: **{money(money_data[user_id])}원**"
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
                f"❌ 돈 부족.\n필요 금액: {money(price)}원\n현재 잔액: {money(money_data[user_id])}원",
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
            f"가격: **{money(price)}원**\n"
            f"자동 장착됨.\n\n"
            f"현재 잔액: **{money(money_data[user_id])}원**"
        )


@bot.tree.command(name="낚시상점목록", description="낚시상점 판매 목록 확인", guild=GUILD)
async def fishing_shop_list(interaction: discord.Interaction):
    rod_lines = []

    for name, data in ROD_DATA.items():
        if name == "기본 낚싯대":
            continue

        ore_text = ", ".join(
            f"{ore} x{count}"
            for ore, count in data.get("ores", {}).items()
        )

        if not ore_text:
            ore_text = "없음"

        rod_lines.append(
            f"**{name}**\n"
            f"가격: **{money(data['price'])}원**\n"
            f"재료: **{ore_text}**\n"
            f"운빨: **+{data['luck']}%**\n"
            f"시간 감소: **{data['time_reduce']}%**\n"
            f"더블 확률: **{data['double_chance']}%**\n"
            f"트리플 확률: **{data['triple_chance']}%**"
        )

    rod_text = "\n\n".join(rod_lines)

    bait_text = "\n".join(
        f"**{name}** - {money(data['price'])}원 / 희귀 확률 +{data['luck']}%"
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
                f"🎁 보상금: **{money(reward)}원**\n"
                f"현재 잔액: **{money(money_data[self.user_id])}원**"
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

@bot.tree.command(name="잔액", description="내 마로 잔액 확인", guild=GUILD)
async def check_maro(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    get_wallet(user_id)

    await interaction.response.send_message(
        f"💰 {interaction.user.mention}의 잔액: **{money(money_data[user_id])}**"
    )

@bot.tree.command(name="마로지급", description="유저에게 마로를 지급한다", guild=GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def give_maro(
    interaction: discord.Interaction,
    유저: discord.Member,
    금액: int
):
    if 금액 <= 0:
        await interaction.response.send_message("❌ 1 마로 이상 지급해야 함.", ephemeral=True)
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

@bot.event
async def on_ready():
    await bot.tree.sync(guild=GUILD)
    print(f"{bot.user} 로그인 완료")
    
bot.run(TOKEN)
