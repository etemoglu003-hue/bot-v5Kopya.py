import asyncio
import json
import time
import urllib.request
import urllib.parse
import urllib.error
import sys
import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# ============================================================
# AYARLAR
# ============================================================

TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()

SCAN_MINUTES = 5
MAX_COINS = 15

ALERT_COOLDOWN = 30 * 60
ALERT_SCORE = 70

TARGET_1_ATR = 1.0
TARGET_2_ATR = 2.0
TARGET_3_ATR = 3.0
STOP_ATR = 1.2

BINANCE_BASE = "https://fapi.binance.com"


# ============================================================
# TERMINAL YAZDIRMA
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
        print(*args, flush=True)

    except Exception:

        try:
            text = " ".join(
                str(x)
                for x in args
            )

            print(
                text.encode(
                    "ascii",
                    "replace"
                ).decode("ascii"),
                flush=True
            )

        except Exception:
            pass


# ============================================================
# GLOBAL DEGISKENLER
# ============================================================

last_alerts = {}
previous_oi = {}

TARGET_CHAT_ID = (
    os.getenv(
        "TARGET_CHAT_ID",
        ""
    ).strip()
    or
    "@realistcoinman"
)

last_hour_report = -1
scanner_running = False


# ============================================================
# BINANCE JSON
# ============================================================

def get_json(url):

    try:

        url = str(url).strip()

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/151.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Connection": "close"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            status_code = response.getcode()
            raw_data = response.read()

        safe_print(
            "BINANCE HTTP:",
            status_code,
            url
        )

        return json.loads(
            raw_data.decode("utf-8")
        )

    except urllib.error.HTTPError as e:

        safe_print(
            "========================================"
        )

        safe_print(
            "BINANCE HTTP HATASI"
        )

        safe_print(
            "KOD:",
            e.code
        )

        safe_print(
            "SEBEP:",
            e.reason
        )

        try:

            error_body = e.read().decode(
                "utf-8",
                errors="replace"
            )

            safe_print(
                "BINANCE CEVABI:",
                error_body[:1000]
            )

        except Exception:

            safe_print(
                "BINANCE CEVABI OKUNAMADI."
            )

        safe_print(
            "URL:",
            url
        )

        safe_print(
            "========================================"
        )

        return None

    except urllib.error.URLError as e:

        safe_print(
            "========================================"
        )

        safe_print(
            "BINANCE URL HATASI"
        )

        safe_print(
            "SEBEP:",
            str(e.reason)
        )

        safe_print(
            "URL:",
            url
        )

        safe_print(
            "========================================"
        )

        return None

    except TimeoutError:

        safe_print(
            "BINANCE BAGLANTI ZAMAN ASIMI."
        )

        safe_print(
            "URL:",
            url
        )

        return None

    except Exception as e:

        safe_print(
            "========================================"
        )

        safe_print(
            "BINANCE VERI HATASI:",
            type(e).__name__
        )

        safe_print(
            "DETAY:",
            str(e)
        )

        safe_print(
            "URL:",
            url
        )

        safe_print(
            "========================================"
        )

        return None


# ============================================================
# BINANCE TEST
# ============================================================

def test_binance():

    url = (
        BINANCE_BASE
        + "/fapi/v1/ping"
    )

    data = get_json(url)

    if data is not None:

        safe_print(
            "Binance baglantisi OK."
        )

        return True

    safe_print(
        "Binance baglantisi BASARISIZ."
    )

    return False


# ============================================================
# COIN LISTESI
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
                item.get("status")
                == "TRADING"
                and
                item.get("quoteAsset")
                == "USDT"
                and
                item.get("contractType")
                == "PERPETUAL"
            ):

                symbols.append(
                    item["symbol"]
                )

        except Exception:
            continue

    return symbols


# ============================================================
# TICKER
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
# LONG SHORT
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
                    high
                    -
                    previous_close
                ),
                abs(
                    low
                    -
                    previous_close
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
# COIN ANALIZ
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

        old_15m = closes[-2]

        price_change_15m = (
            (
                price
                -
                old_15m
            )
            /
            old_15m
        ) * 100

        old_1h = closes[-5]

        price_change_1h = (
            (
                price
                -
                old_1h
            )
            /
            old_1h
        ) * 100

        old_4h = closes[-17]

        price_change_4h = (
            (
                price
                -
                old_4h
            )
            /
            old_4h
        ) * 100

        previous_volumes = (
            volumes[-9:-1]
        )

        if previous_volumes:

            avg_volume = (
                sum(
                    previous_volumes
                )
                /
                len(
                    previous_volumes
                )
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

        atr = calculate_atr(
            klines,
            14
        )

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

        ls = get_long_short(
            symbol
        )

        funding = get_funding(
            symbol
        )

        score = 0
        reasons = []

        # 15M
        if abs(
            price_change_15m
        ) >= 3:

            score += 30

            reasons.append(
                "15M guclu hareket: "
                +
                f"{price_change_15m:+.2f}%"
            )

        elif abs(
            price_change_15m
        ) >= 2:

            score += 20

            reasons.append(
                "15M hareket: "
                +
                f"{price_change_15m:+.2f}%"
            )

        elif abs(
            price_change_15m
        ) >= 1:

            score += 10

        # 1H
        if abs(
            price_change_1h
        ) >= 6:

            score += 25

            reasons.append(
                "1H guclu momentum: "
                +
                f"{price_change_1h:+.2f}%"
            )

        elif abs(
            price_change_1h
        ) >= 3:

            score += 15

            reasons.append(
                "1H momentum: "
                +
                f"{price_change_1h:+.2f}%"
            )

        # HACIM
        if volume_change >= 150:

            score += 25

            reasons.append(
                "Hacim patlamasi: "
                +
                f"+{volume_change:.0f}%"
            )

        elif volume_change >= 100:

            score += 20

            reasons.append(
                "Hacim artisi: "
                +
                f"+{volume_change:.0f}%"
            )

        elif volume_change >= 50:

            score += 10

        # OI
        if oi_available:

            if abs(
                oi_change
            ) >= 5:

                score += 20

                reasons.append(
                    "OI degisimi: "
                    +
                    f"{oi_change:+.2f}%"
                )

            elif abs(
                oi_change
            ) >= 2:

                score += 10

        # LONG SHORT
        if ls:

            ratio = ls["ratio"]

            if ratio >= 1.5:

                score += 5

                reasons.append(
                    "Long agirligi: "
                    +
                    f"{ratio:.2f}"
                )

            elif ratio <= 0.67:

                score += 5

                reasons.append(
                    "Short agirligi: "
                    +
                    f"{ratio:.2f}"
                )

        # YON
        if price_change_15m >= 0:

            direction = "YUKSELIS"

        else:

            direction = "DUSUS"

        # PIYASA YORUMU
        if (
            price_change_15m > 0
            and
            oi_change > 2
        ):

            market_comment = (
                "Fiyat yukseliyor ve OI artiyor. "
                "Yeni pozisyon girisleri hareketi "
                "destekliyor olabilir."
            )

        elif (
            price_change_15m > 0
            and
            oi_change < -2
        ):

            market_comment = (
                "Fiyat yukseliyor ancak OI dusuyor. "
                "Short kapanislari etkili olabilir."
            )

        elif (
            price_change_15m < 0
            and
            oi_change > 2
        ):

            market_comment = (
                "Fiyat dusuyor ve OI artiyor. "
                "Yeni short pozisyonlari dususu "
                "destekliyor olabilir."
            )

        elif (
            price_change_15m < 0
            and
            oi_change < -2
        ):

            market_comment = (
                "Fiyat dusuyor ve OI azaliyor. "
                "Long kapanislari etkili olabilir."
            )

        else:

            market_comment = (
                "Fiyat ve OI arasinda guclu "
                "bir dogrulama yok."
            )

        # HEDEF / STOP
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
            "change_15m": price_change_15m,
            "change_1h": price_change_1h,
            "change_4h": price_change_4h,
            "change_24h": change_24h,
            "volume_change": volume_change,
            "oi": oi,
            "oi_change": oi_change,
            "oi_available": oi_available,
            "ls": ls,
            "funding": funding,
            "atr": atr,
            "target1": target1,
            "target2": target2,
            "target3": target3,
            "stop": stop,
            "score": min(
                score,
                100
            ),
            "direction": direction,
            "market_comment": market_comment,
            "reasons": reasons
        }

    except Exception as e:

        safe_print(
            "Coin analiz hatasi:",
            symbol,
            type(e).__name__,
            str(e)
        )

        return None


# ============================================================
# FIYAT FORMAT
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

        direction_text = "🟢 YUKSELIS"

    else:

        direction_text = "🔴 DUSUS"

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

    if not reasons:

        reasons = "• Teknik hareket mevcut"

    return (
        "🚨 CRYPTO RADAR V5\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f'🔥 {result["symbol"]}\n'
        f'{direction_text}\n\n'
        f'💰 Fiyat: {format_price(result["price"])}\n'
        "━━━━━━━━━━━━━━━━━━\n"
        "📈 HAREKET\n"
        f'15M: {result["change_15m"]:+.2f}%\n'
        f'1H: {result["change_1h"]:+.2f}%\n'
        f'4H: {result["change_4h"]:+.2f}%\n'
        f'24H: {result["change_24h"]:+.2f}%\n'
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 PIYASA GUCU\n"
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
        "🎯 TEKNIK TAKIP SEVIYELERI\n"
        f'Hedef 1: {format_price(result["target1"])}\n'
        f'Hedef 2: {format_price(result["target2"])}\n'
        f'Hedef 3: {format_price(result["target3"])}\n'
        f'⚠️ Gecersizlik: {format_price(result["stop"])}\n'
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Otomatik piyasa analizidir.\n"
        "Islem emri veya garanti fiyat tahmini degildir."
    )


# ============================================================
# SAATLIK RAPOR
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
        "SAATLIK PIYASA RAPORU\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔥 EN AKTIF COINLER\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    for i, result in enumerate(
        top,
        start=1
    ):

        if result["direction"] == "YUKSELIS":

            direction = "🟢 YUKSELIS"

        else:

            direction = "🔴 DUSUS"

        message += (
            f"\n\n{i}. {result['symbol']} "
            f"{direction}\n"
            f"💰 Fiyat: "
            f"{format_price(result['price'])}\n"
            f"15M: "
            f"{result['change_15m']:+.2f}%\n"
            f"1H: "
            f"{result['change_1h']:+.2f}%\n"
            f"4H: "
            f"{result['change_4h']:+.2f}%\n"
            f"📊 Hacim: "
            f"{result['volume_change']:+.0f}%\n"
            f"💰 OI: "
            f"{result['oi_change']:+.2f}%\n"
            f"🧠 Skor: "
            f"{result['score']}/100\n"
        )

        if result["score"] >= 80:

            message += (
                "🚨 Cok guclu hareket\n"
            )

        elif result["score"] >= 70:

            message += (
                "🔥 Guclu hareket\n"
            )

        elif result["score"] >= 60:

            message += (
                "🟡 Izlenmeli\n"
            )

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📌 RAPOR NE ANLATIYOR?\n\n"
        "15M = Son 15 dakikalik hareket\n"
        "1H = Son 1 saatteki hareket\n"
        "4H = Son 4 saatteki momentum\n"
        "Hacim = Normal hacme gore degisim\n"
        "OI = Acik pozisyon degisimi\n"
        "Skor = Fiyat + hacim + OI + "
        "pozisyonlanma degerlendirmesi.\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Otomatik piyasa analizidir.\n"
        "Kesin fiyat tahmini veya yatirim tavsiyesi degildir."
    )

    return message


# ============================================================
# PIYASA TARAMA
# ============================================================

async def scan_market(application):

    global last_alerts

    safe_print(
        "========================================"
    )

    safe_print(
        "PIYASA TARAMASI BASLADI"
    )

    safe_print(
        "========================================"
    )

    symbols = get_symbols()

    if not symbols:

        safe_print(
            "Coin listesi alinamadi."
        )

        return []

    safe_print(
        "Toplam Binance Futures coin:",
        len(symbols)
    )

    tickers = get_tickers()

    if not tickers:

        safe_print(
            "Ticker verisi alinamadi."
        )

        return []

    ticker_map = {
        x["symbol"]: x
        for x in tickers
        if "symbol" in x
    }

    candidates = []

    for symbol in symbols:

        ticker = ticker_map.get(
            symbol
        )

        if not ticker:
            continue

        try:

            change = abs(
                float(
                    ticker[
                        "priceChangePercent"
                    ]
                )
            )

            volume = float(
                ticker[
                    "quoteVolume"
                ]
            )

            candidates.append(
                (
                    symbol,
                    ticker,
                    change,
                    volume
                )
            )

        except Exception:

            continue

    candidates.sort(
        key=lambda x: (
            x[2],
            x[3]
        ),
        reverse=True
    )

    candidates = candidates[
        :MAX_COINS
    ]

    safe_print(
        "Analiz edilecek coin:",
        len(candidates)
    )

    results = []

    for index, (
        symbol,
        ticker,
        _,
        _
    ) in enumerate(
        candidates,
        start=1
    ):

        safe_print(
            f"[{index}/{len(candidates)}]",
            symbol
        )

        result = analyze_coin(
            symbol,
            ticker
        )

        if not result:
            continue

        results.append(
            result
        )

        price_strong = (
            abs(
                result["change_15m"]
            ) >= 2
        )

        volume_strong = (
            result["volume_change"]
            >= 50
        )

        oi_strong = (
            result["oi_available"]
            and
            abs(
                result["oi_change"]
            ) >= 2
        )

        confirmations = sum(
            [
                price_strong,
                volume_strong,
                oi_strong
            ]
        )

        if (
            result["score"]
            >= ALERT_SCORE
            and
            price_strong
            and
            confirmations >= 2
        ):

            now = time.time()

            last_time = last_alerts.get(
                symbol,
                0
            )

            cooldown_ok = (
                now - last_time
                >= ALERT_COOLDOWN
            )

            if (
                cooldown_ok
                and
                TARGET_CHAT_ID
            ):

                try:

                    await application.bot.send_message(
                        chat_id=TARGET_CHAT_ID,
                        text=create_alert(
                            result
                        )
                    )

                    last_alerts[
                        symbol
                    ] = now

                    safe_print(
                        "ALARM GONDERILDI:",
                        symbol
                    )

                except Exception as e:

                    safe_print(
                        "Telegram alarm hatasi:",
                        type(e).__name__,
                        str(e)
                    )

        await asyncio.sleep(
            0.15
        )

    safe_print(
        "========================================"
    )

    safe_print(
        "TARAMA TAMAMLANDI:",
        len(results),
        "coin"
    )

    safe_print(
        "========================================"
    )

    return results


# ============================================================
# ARKA PLAN TARAMA
# ============================================================

async def background_scanner(
    application
):

    global last_hour_report
    global scanner_running

    scanner_running = True

    safe_print(
        "ARKA PLAN TARAMA SISTEMI AKTIF."
    )

    while True:

        try:

            results = await scan_market(
                application
            )

            current_hour = (
                datetime.now().hour
            )

            if (
                current_hour
                !=
                last_hour_report
            ):

                if (
                    results
                    and
                    TARGET_CHAT_ID
                ):

                    try:

                        await application.bot.send_message(
                            chat_id=TARGET_CHAT_ID,
                            text=create_hourly_report(
                                results
                            )
                        )

                        safe_print(
                            "SAATLIK RAPOR GONDERILDI."
                        )

                    except Exception as e:

                        safe_print(
                            "Saatlik rapor hatasi:",
                            type(e).__name__,
                            str(e)
                        )

                last_hour_report = (
                    current_hour
                )

        except Exception as e:

            safe_print(
                "Tarama sistemi hatasi:",
                type(e).__name__,
                str(e)
            )

        safe_print(
            f"{SCAN_MINUTES} dakika bekleniyor..."
        )

        await asyncio.sleep(
            SCAN_MINUTES * 60
        )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 CRYPTO RADAR V5 AKTIF!\n\n"
        "Binance Futures piyasasini "
        "otomatik tarayacagim.\n\n"
        "/analiz - Anlik piyasa taramasi\n"
        "/durum - Sistem durumu\n"
        "/id - Bu sohbeti hedef olarak tanimla\n"
        "/gonder - Kanala mesaj gonder"
    )


# ============================================================
# /DURUM
# ============================================================

async def durum(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if TARGET_CHAT_ID:

        chat_status = "🟢 Tanimli"

    else:

        chat_status = "❌ Tanimli degil"

    scanner_status = (
        "🟢 Calisiyor"
        if scanner_running
        else
        "🟡 Baslatiliyor"
    )

    await update.message.reply_text(
        "🤖 CRYPTO RADAR V5 DURUM\n\n"
        "🟢 Bot aktif\n"
        "🟢 Binance API aktif\n"
        f"{scanner_status} Otomatik tarama\n"
        f"⏱ Tarama: {SCAN_MINUTES} dakika\n"
        f"📡 Hedef sohbet: {chat_status}\n"
        f"🎯 Alarm skoru: {ALERT_SCORE}/100\n"
        "⏳ Cooldown: 30 dakika"
    )


# ============================================================
# /ANALIZ
# ============================================================

async def analiz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🔎 Binance Futures taraniyor...\n"
        "Biraz bekle."
    )

    try:

        results = await scan_market(
            context.application
        )

        if not results:

            await update.message.reply_text(
                "❌ Binance verisi alinamadi."
            )

            return

        await update.message.reply_text(
            create_hourly_report(
                results
            )
        )

    except Exception as e:

        safe_print(
            "Analiz komutu hatasi:",
            type(e).__name__,
            str(e)
        )

        await update.message.reply_text(
            "❌ Analiz sirasinda hata olustu.\n"
            "Actions ekranini kontrol et."
        )


# ============================================================
# /ID
# ============================================================

async def capture_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global TARGET_CHAT_ID

    TARGET_CHAT_ID = (
        update.effective_chat.id
    )

    await update.message.reply_text(
        "✅ BU SOHBET HEDEF OLARAK TANIMLANDI.\n\n"
        f"Chat ID: {TARGET_CHAT_ID}\n\n"
        "Otomatik alarm ve saatlik raporlar "
        "bu sohbete gonderilecek."
    )

    safe_print(
        "TARGET CHAT ID:",
        TARGET_CHAT_ID
    )


# ============================================================
# /GONDER
# ============================================================

async def gonder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "❌ Mesaj yazmalısın.\n\n"
            "Örnek:\n"
            "/gonder BTC yükseliş sinyali verdi 🚀"
        )

        return

    message = " ".join(
        context.args
    )

    if not TARGET_CHAT_ID:

        await update.message.reply_text(
            "❌ Hedef kanal tanımlı değil."
        )

        return

    try:

        await context.bot.send_message(
            chat_id=TARGET_CHAT_ID,
            text=message
        )

        await update.message.reply_text(
            "✅ Mesaj kanala gönderildi."
        )

        safe_print(
            "MANUEL MESAJ GONDERILDI:",
            message
        )

    except Exception as e:

        safe_print(
            "Manuel mesaj gonderme hatasi:",
            type(e).__name__,
            str(e)
        )

        await update.message.reply_text(
            "❌ Mesaj gönderilemedi.\n\n"
            f"Hata: {type(e).__name__}\n"
            f"Detay: {str(e)}"
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(
    application
):

    safe_print(
        "========================================"
    )

    safe_print(
        "CRYPTO RADAR V5 BASLATILIYOR"
    )

    safe_print(
        "========================================"
    )

    safe_print(
        "HEDEF KANAL:",
        TARGET_CHAT_ID
    )

    safe_print(
        "TARAMA ARALIGI:",
        SCAN_MINUTES,
        "dakika"
    )

    safe_print(
        "ANALIZ EDILECEK COIN:",
        MAX_COINS
    )

    if test_binance():

        safe_print(
            "Binance API testi BASARILI."
        )

    else:

        safe_print(
            "UYARI: Binance API testi BASARISIZ."
        )

    asyncio.create_task(
        background_scanner(
            application
        )
    )

    safe_print(
        "ARKA PLAN SCANNER BASLATILDI."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if (
        not TOKEN
        or
        TOKEN == "BURAYA_YENI_TOKENINI_YAZ"
    ):

        safe_print(
            "HATA: Telegram tokeni bulunamadi."
        )

        return

    safe_print(
        "Telegram bot hazirlaniyor..."
    )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "durum",
            durum
        )
    )

    app.add_handler(
        CommandHandler(
            "analiz",
            analiz
        )
    )

    app.add_handler(
        CommandHandler(
            "id",
            capture_chat_id
        )
    )

    app.add_handler(
        CommandHandler(
            "gonder",
            gonder
        )
    )

    safe_print(
        "========================================"
    )

    safe_print(
        "       CRYPTO RADAR V5"
    )

    safe_print(
        "========================================"
    )

    safe_print(
        "Bot Telegram polling baslatiliyor..."
    )

    app.run_polling()


# ============================================================
# PROGRAM BASLANGICI
# ============================================================

if __name__ == "__main__":
    main()
