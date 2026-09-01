import asyncio
import json
import time
import urllib.request
import urllib.parse
import sys
import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# ============================================================
# CRYPTO RADAR V5
# ============================================================

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

# GitHub Secret'tan alınır.
# Secret yoksa mevcut varsayılan kanal kullanılır.
TARGET_CHAT_ID = os.getenv(
    "TARGET_CHAT_ID",
    "@realistcoinman"
).strip()


# ============================================================
# TARAMA AYARLARI
# ============================================================

SCAN_MINUTES = 5
MAX_COINS = 50


# ============================================================
# ALARM AYARLARI
# ============================================================

ALERT_COOLDOWN = 30 * 60
ALERT_SCORE = 70


# ============================================================
# ATR HEDEFLERİ
# ============================================================

TARGET_1_ATR = 1.0
TARGET_2_ATR = 2.0
TARGET_3_ATR = 3.0
STOP_ATR = 1.2


# ============================================================
# WINDOWS CMD UTF-8 / GÜVENLİ YAZDIRMA
# ============================================================

try:
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

except Exception:
    pass


def safe_print(*args):
    try:
        print(*args)

    except Exception:

        try:
            text = " ".join(
                str(x) for x in args
            )

            print(
                text.encode(
                    "ascii",
                    "replace"
                ).decode("ascii")
            )

        except Exception:
            pass


# ============================================================
# GENEL DEĞİŞKENLER
# ============================================================

last_alerts = {}
previous_oi = {}

last_hour_report = -1

scanner_running = False
scan_lock = asyncio.Lock()


# ============================================================
# BINANCE API
# ============================================================

BINANCE_BASE = "https://fapi.binance.com"


def get_json(url):

    try:

        url = str(url).strip()

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CryptoRadarV5/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            raw_data = response.read()

        return json.loads(
            raw_data.decode("utf-8")
        )

    except Exception as e:

        safe_print(
            "BINANCE VERİ HATASI:",
            type(e).__name__
        )

        return None


# ============================================================
# BINANCE BAĞLANTI TESTİ
# ============================================================

def test_binance():

    url = (
        BINANCE_BASE
        + "/fapi/v1/ping"
    )

    data = get_json(url)

    if data is not None:

        safe_print(
            "Binance bağlantısı OK."
        )

        return True

    safe_print(
        "Binance bağlantısı BAŞARISIZ."
    )

    return False


# ============================================================
# COINLER
# ============================================================

def get_symbols():

    url = (
        BINANCE_BASE
        + "/fapi/v1/exchangeInfo"
    )

    data = get_json(url)

    if not data:
        return []

    symbols = []

    for item in data.get(
        "symbols",
        []
    ):

        try:

            if (
                item.get("status") == "TRADING"
                and
                item.get("quoteAsset") == "USDT"
                and
                item.get("contractType") == "PERPETUAL"
            ):

                symbols.append(
                    item["symbol"]
                )

        except Exception:
            continue

    return symbols


# ============================================================
# 24 SAATLİK TICKER
# ============================================================

def get_tickers():

    url = (
        BINANCE_BASE
        + "/fapi/v1/ticker/24hr"
    )

    return get_json(url)


# ============================================================
# KLINE
# ============================================================

def get_klines(symbol):

    safe_symbol = urllib.parse.quote(
        str(symbol),
        safe=""
    )

    url = (
        BINANCE_BASE
        + "/fapi/v1/klines"
        + "?symbol="
        + safe_symbol
        + "&interval=15m"
        + "&limit=30"
    )

    return get_json(url)


# ============================================================
# OPEN INTEREST
# ============================================================

def get_oi(symbol):

    safe_symbol = urllib.parse.quote(
        str(symbol),
        safe=""
    )

    url = (
        BINANCE_BASE
        + "/fapi/v1/openInterest"
        + "?symbol="
        + safe_symbol
    )

    data = get_json(url)

    if not data:
        return None

    try:

        return float(
            data["openInterest"]
        )

    except Exception:

        return None


# ============================================================
# LONG / SHORT
# ============================================================

def get_long_short(symbol):

    safe_symbol = urllib.parse.quote(
        str(symbol),
        safe=""
    )

    url = (
        BINANCE_BASE
        + "/futures/data/globalLongShortAccountRatio"
        + "?symbol="
        + safe_symbol
        + "&period=1h"
        + "&limit=1"
    )

    data = get_json(url)

    if not data:
        return None

    try:

        result = data[0]

        return {
            "long": float(
                result["longAccount"]
            ),
            "short": float(
                result["shortAccount"]
            ),
            "ratio": float(
                result["longShortRatio"]
            )
        }

    except Exception:

        return None


# ============================================================
# FUNDING
# ============================================================

def get_funding(symbol):

    safe_symbol = urllib.parse.quote(
        str(symbol),
        safe=""
    )

    url = (
        BINANCE_BASE
        + "/fapi/v1/premiumIndex"
        + "?symbol="
        + safe_symbol
    )

    data = get_json(url)

    if not data:
        return None

    try:

        return float(
            data["lastFundingRate"]
        )

    except Exception:

        return None


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    klines,
    period=14
):

    if len(klines) < period + 1:
        return None

    true_ranges = []

    for i in range(
        1,
        len(klines)
    ):

        try:

            high = float(
                klines[i][2]
            )

            low = float(
                klines[i][3]
            )

            previous_close = float(
                klines[i - 1][4]
            )

            true_range = max(
                high - low,
                abs(
                    high - previous_close
                ),
                abs(
                    low - previous_close
                )
            )

            true_ranges.append(
                true_range
            )

        except Exception:

            continue

    if not true_ranges:
        return None

    return (
        sum(
            true_ranges[-period:]
        )
        /
        min(
            period,
            len(true_ranges)
        )
    )


# ============================================================
# COIN ANALİZ
# ============================================================

def analyze_coin(
    symbol,
    ticker
):

    global previous_oi

    try:

        price = float(
            ticker["lastPrice"]
        )

        change_24h = float(
            ticker["priceChangePercent"]
        )

        klines = get_klines(
            symbol
        )

        if not klines:
            return None

        if len(klines) < 18:
            return None

        closes = [
            float(k[4])
            for k in klines
        ]

        volumes = [
            float(k[7])
            for k in klines
        ]


        # ----------------------------------------------------
        # FİYAT HAREKETLERİ
        # ----------------------------------------------------

        old_15m = closes[-2]

        price_change_15m = (
            (
                price - old_15m
            )
            /
            old_15m
        ) * 100


        old_1h = closes[-5]

        price_change_1h = (
            (
                price - old_1h
            )
            /
            old_1h
        ) * 100


        old_4h = closes[-17]

        price_change_4h = (
            (
                price - old_4h
            )
            /
            old_4h
        ) * 100


        # ----------------------------------------------------
        # HACİM
        # ----------------------------------------------------

        previous_volumes = volumes[-9:-1]

        if previous_volumes:

            avg_volume = (
                sum(previous_volumes)
                /
                len(previous_volumes)
            )

        else:

            avg_volume = 0


        current_volume = volumes[-1]

        if avg_volume > 0:

            volume_change = (
                (
                    current_volume
                    -
                    avg_volume
                )
                /
                avg_volume
            ) * 100

        else:

            volume_change = 0


        # ----------------------------------------------------
        # ATR
        # ----------------------------------------------------

        atr = calculate_atr(
            klines,
            14
        )


        # ----------------------------------------------------
        # OPEN INTEREST
        # ----------------------------------------------------

        oi = get_oi(
            symbol
        )

        oi_change = 0
        oi_available = False

        if oi is not None:

            old_oi = previous_oi.get(
                symbol
            )

            if (
                old_oi is not None
                and
                old_oi > 0
            ):

                oi_change = (
                    (
                        oi
                        -
                        old_oi
                    )
                    /
                    old_oi
                ) * 100

                oi_available = True

            previous_oi[symbol] = oi


        # ----------------------------------------------------
        # LONG / SHORT
        # ----------------------------------------------------

        ls = get_long_short(
            symbol
        )


        # ----------------------------------------------------
        # FUNDING
        # ----------------------------------------------------

        funding = get_funding(
            symbol
        )


        # ----------------------------------------------------
        # SKOR
        # ----------------------------------------------------

        score = 0

        reasons = []


        # 15M

        if abs(price_change_15m) >= 3:

            score += 30

            reasons.append(
                "15M güçlü hareket: "
                + f"{price_change_15m:+.2f}%"
            )

        elif abs(price_change_15m) >= 2:

            score += 20

            reasons.append(
                "15M hareket: "
                + f"{price_change_15m:+.2f}%"
            )

        elif abs(price_change_15m) >= 1:

            score += 10


        # 1H

        if abs(price_change_1h) >= 6:

            score += 25

            reasons.append(
                "1H güçlü momentum: "
                + f"{price_change_1h:+.2f}%"
            )

        elif abs(price_change_1h) >= 3:

            score += 15

            reasons.append(
                "1H momentum: "
                + f"{price_change_1h:+.2f}%"
            )


        # HACİM

        if volume_change >= 150:

            score += 25

            reasons.append(
                "Hacim patlaması: "
                + f"+{volume_change:.0f}%"
            )

        elif volume_change >= 100:

            score += 20

            reasons.append(
                "Hacim artışı: "
                + f"+{volume_change:.0f}%"
            )

        elif volume_change >= 50:

            score += 10


        # OI

        if oi_available:

            if abs(oi_change) >= 5:

                score += 20

                reasons.append(
                    "OI değişimi: "
                    + f"{oi_change:+.2f}%"
                )

            elif abs(oi_change) >= 2:

                score += 10


        # LONG / SHORT

        if ls:

            ratio = ls["ratio"]

            if ratio >= 1.5:

                score += 5

                reasons.append(
                    "Long ağırlığı: "
                    + f"{ratio:.2f}"
                )

            elif ratio <= 0.67:

                score += 5

                reasons.append(
                    "Short ağırlığı: "
                    + f"{ratio:.2f}"
                )


        # ----------------------------------------------------
        # YÖN
        # ----------------------------------------------------

        if price_change_15m >= 0:

            direction = "YUKSELIS"

        else:

            direction = "DUSUS"


        # ----------------------------------------------------
        # OI + FİYAT YORUMU
        # ----------------------------------------------------

        if (
            price_change_15m > 0
            and
            oi_change > 2
        ):

            market_comment = (
                "Fiyat yükseliyor ve OI artıyor. "
                "Yeni pozisyon girişleri hareketi "
                "destekliyor olabilir."
            )

        elif (
            price_change_15m > 0
            and
            oi_change < -2
        ):

            market_comment = (
                "Fiyat yükseliyor ancak OI düşüyor. "
                "Short kapanışları etkili olabilir."
            )

        elif (
            price_change_15m < 0
            and
            oi_change > 2
        ):

            market_comment = (
                "Fiyat düşüyor ve OI artıyor. "
                "Yeni short pozisyonları düşüşü "
                "destekliyor olabilir."
            )

        elif (
            price_change_15m < 0
            and
            oi_change < -2
        ):

            market_comment = (
                "Fiyat düşüyor ve OI azalıyor. "
                "Long kapanışları etkili olabilir."
            )

        else:

            market_comment = (
                "Fiyat ve OI arasında güçlü "
                "bir doğrulama yok."
            )


        # ----------------------------------------------------
        # HEDEFLER
        # ----------------------------------------------------

        target1 = None
        target2 = None
        target3 = None
        stop = None

        if atr:

            if price_change_15m >= 0:

                target1 = (
                    price
                    +
                    atr * TARGET_1_ATR
                )

                target2 = (
                    price
                    +
                    atr * TARGET_2_ATR
                )

                target3 = (
                    price
                    +
                    atr * TARGET_3_ATR
                )

                stop = (
                    price
                    -
                    atr * STOP_ATR
                )

            else:

                target1 = (
                    price
                    -
                    atr * TARGET_1_ATR
                )

                target2 = (
                    price
                    -
                    atr * TARGET_2_ATR
                )

                target3 = (
                    price
                    -
                    atr * TARGET_3_ATR
                )

                stop = (
                    price
                    +
                    atr * STOP_ATR
                )


        return {

            "symbol": symbol,

            "price": price,

            "change_15m":
                price_change_15m,

            "change_1h":
                price_change_1h,

            "change_4h":
                price_change_4h,

            "change_24h":
                change_24h,

            "volume_change":
                volume_change,

            "oi":
                oi,

            "oi_change":
                oi_change,

            "oi_available":
                oi_available,

            "ls":
                ls,

            "funding":
                funding,

            "atr":
                atr,

            "target1":
                target1,

            "target2":
                target2,

            "target3":
                target3,

            "stop":
                stop,

            "score":
                min(score, 100),

            "direction":
                direction,

            "market_comment":
                market_comment,

            "reasons":
                reasons
        }


    except Exception as e:

        safe_print(
            "Coin analiz hatası:",
            symbol,
            type(e).__name__
        )

        return None


# ============================================================
# FİYAT FORMAT
# ============================================================

def format_price(price):

    if price is None:
        return "Bilinmiyor"

    if price >= 1:
        return f"{price:,.4f}"

    if price >= 0.01:
        return f"{price:.5f}"

    return f"{price:.8f}"


# ============================================================
# ALARM MESAJI
# ============================================================

def create_alert(result):

    if result["direction"] == "YUKSELIS":

        direction_text = "🟢 YUKSELİŞ"

    else:

        direction_text = "🔴 DÜŞÜŞ"


    ls_text = "Bilinmiyor"

    if result["ls"]:

        ls_text = (
            f'{result["ls"]["long"] * 100:.1f}% Long / '
            f'{result["ls"]["short"] * 100:.1f}% Short'
        )


    funding_text = "Bilinmiyor"

    if result["funding"] is not None:

        funding_text = (
            f'{result["funding"] * 100:.5f}%'
        )


    reasons = "\n".join(
        "• " + x
        for x in result["reasons"]
    )


    return (

        "🚨 CRYPTO RADAR V5\n"

        "━━━━━━━━━━━━━━━━━━\n"

        f'🔥 {result["symbol"]}\n'

        f'{direction_text}\n\n'

        f'💰 Fiyat: '
        f'{format_price(result["price"])}\n'

        "━━━━━━━━━━━━━━━━━━\n"

        "📈 HAREKET\n"

        f'15M: {result["change_15m"]:+.2f}%\n'

        f'1H: {result["change_1h"]:+.2f}%\n'

        f'4H: {result["change_4h"]:+.2f}%\n'

        f'24H: {result["change_24h"]:+.2f}%\n'

        "━━━━━━━━━━━━━━━━━━\n"

        "📊 PIYASA GÜCÜ\n"

        f'Hacim: {result["volume_change"]:+.0f}%\n'

        f'OI: {result["oi_change"]:+.2f}%\n'

        f'Long / Short: {ls_text}\n'

        f'Funding: {funding_text}\n'

        "━━━━━━━━━━━━━━━━━━\n"

        "🧠 RADAR YORUMU\n"

        f'{result["market_comment"]}\n'

        "━━━━━━━━━━━━━━━━━━\n"

        f'🔥 SKOR: {result["score"]}/100\n'

        f'{reasons}\n'

        "━━━━━━━━━━━━━━━━━━\n"

        "🎯 TEKNİK TAKİP SEVİYELERİ\n"

        f'Hedef 1: '
        f'{format_price(result["target1"])}\n'

        f'Hedef 2: '
        f'{format_price(result["target2"])}\n'

        f'Hedef 3: '
        f'{format_price(result["target3"])}\n'

        f'⚠️ Geçersizlik: '
        f'{format_price(result["stop"])}\n'

        "━━━━━━━━━━━━━━━━━━\n"

        "⚠️ Otomatik piyasa analizidir.\n"

        "İşlem emri veya garanti fiyat tahmini değildir."
    )


# ============================================================
# SAATLİK RAPOR
# ============================================================

def create_hourly_report(results):

    results = sorted(
        results,
        key=lambda x: x["score"],
        reverse=True
    )

    top = results[:5]


    message = (

        "🕐 CRYPTO RADAR V5\n"

        "SAATLİK PİYASA RAPORU\n"

        "━━━━━━━━━━━━━━━━━━\n"

        "🔥 EN AKTİF COİNLER\n"

        "━━━━━━━━━━━━━━━━━━"
    )


    for i, result in enumerate(
        top,
        start=1
    ):

        if result["direction"] == "YUKSELIS":

            direction = "🟢 YÜKSELİŞ"

        else:

            direction = "🔴 DÜŞÜŞ"


        message += (

            f"\n\n{i}. {result['symbol']} "
            f"{direction}\n"

            f"💰 Fiyat: "
            f"{format_price(result['price'])}\n"

            f"15M: "
            f"{result['change_15m']:+.2f}%
