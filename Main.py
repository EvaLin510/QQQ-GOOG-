import sys
import os
import traceback

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf


# ==========================================
# 設定
# ==========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.getenv("LINE_USER_ID")

CONFIG_FILE = "config.csv"
THRESHOLD = 0.07
CHART_FILE = "live_chart.png"


# ==========================================
# 通知
# ==========================================

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram 環境變數未設定")
        return False

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown"
            },
            timeout=15
        )

        print(
            "✅ Telegram 已發送"
            if r.ok else
            f"❌ Telegram 失敗：{r.status_code} {r.text}"
        )

        return r.ok

    except Exception as e:
        print(f"❌ Telegram 例外：{e}")
        return False


def send_line(text):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ LINE 環境變數未設定")
        return False

    text = (
        text
        .replace("*", "")
        .replace("`", "")
    )

    try:
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
            },
            json={
                "to": LINE_USER_ID.strip(),
                "messages": [
                    {
                        "type": "text",
                        "text": text
                    }
                ]
            },
            timeout=15
        )

        print(
            "✅ LINE 已發送"
            if r.ok else
            f"❌ LINE 失敗：{r.status_code} {r.text}"
        )

        return r.ok

    except Exception as e:
        print(f"❌ LINE 例外：{e}")
        return False


def notify(text, line=True):
    tg = send_telegram(text)
    ln = send_line(text) if line else None
    return tg, ln


def send_photo(path):
    if not os.path.exists(path):
        return False

    try:
        with open(path, "rb") as f:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID},
                files={"photo": f},
                timeout=30
            )

        print(
            "✅ Telegram 圖片已發送"
            if r.ok else
            f"❌ Telegram 圖片失敗：{r.status_code}"
        )

        return r.ok

    except Exception as e:
        print(f"❌ 圖片發送例外：{e}")
        return False


# ==========================================
# Config
# ==========================================

def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(
            f"找不到 {CONFIG_FILE}"
        )

    df = pd.read_csv(CONFIG_FILE)

    required = [
        "trade_date",
        "action",
        "current_hold",
        "base_qqq_price",
        "base_goog_price",
        "shares_held"
    ]

    missing = [
        x for x in required
        if x not in df.columns
    ]

    if missing:
        raise ValueError(
            "config.csv 缺少欄位："
            + ", ".join(missing)
        )

    if df.empty:
        raise ValueError(
            "config.csv 是空的"
        )

    return df


# ==========================================
# 即時價格
# ==========================================

def get_prices():
    tickers = yf.Tickers("QQQM GOOG")

    qqqm = float(
        tickers.tickers["QQQM"]
        .fast_info["last_price"]
    )

    goog = float(
        tickers.tickers["GOOG"]
        .fast_info["last_price"]
    )

    if not np.isfinite(qqqm) or not np.isfinite(goog):
        raise ValueError(
            f"無效價格：QQQM={qqqm}, GOOG={goog}"
        )

    return qqqm, goog


# ==========================================
# 策略計算
# ==========================================

def calculate(hold, base_qqq, base_goog, qqqm, goog):

    ret_qqq = qqqm / base_qqq - 1
    ret_goog = goog / base_goog - 1

    diff = ret_qqq - ret_goog

    hold = hold.upper().strip()

    if hold == "GOOG":
        strategy_diff = diff
        target = "QQQM"
        sell = goog
        buy = qqqm

    elif hold == "QQQM":
        strategy_diff = -diff
        target = "GOOG"
        sell = qqqm
        buy = goog

    else:
        raise ValueError(
            f"current_hold 無法辨識：{hold}"
        )

    return {
        "ret_qqq": ret_qqq,
        "ret_goog": ret_goog,
        "diff": diff,
        "strategy_diff": strategy_diff,
        "target": target,
        "triggered": strategy_diff > THRESHOLD,
        "sell": sell,
        "buy": buy
    }


# ==========================================
# 每日 / 手動報告
# ==========================================

def build_report(
    hold,
    shares,
    base_qqq,
    base_goog,
    qqqm,
    goog,
    s
):

    qqq_pct = s["ret_qqq"] * 100
    goog_pct = s["ret_goog"] * 100
    diff_pct = s["strategy_diff"] * 100

    remaining = (
        THRESHOLD
        - s["strategy_diff"]
    ) * 100

    if s["triggered"]:
        status = (
            f"🚨 已達 7% 轉單門檻\n"
            f"轉單方向：{hold} → {s['target']}"
        )
    else:
        status = (
            f"📌 目前維持：{hold}\n"
            f"距離 {hold} → {s['target']} "
            f"門檻還有：{remaining:.2f}%"
        )

    if s["diff"] > 0:
        relative = (
            f"QQQM 領先 GOOG："
            f"{s['diff'] * 100:.2f}%"
        )
    elif s["diff"] < 0:
        relative = (
            f"GOOG 領先 QQQM："
            f"{abs(s['diff']) * 100:.2f}%"
        )
    else:
        relative = "QQQM / GOOG 績效相同"

    now = pd.Timestamp.now(
        tz="Asia/Taipei"
    )

    return (
        "ℹ️ *【QQQM / GOOG 每日策略報告】*\n\n"

        f"時間：`{now.strftime('%Y-%m-%d %H:%M')}`\n"
        f"目前持股：`{hold}`\n"
        f"持股股數：`{shares:.5f}`\n\n"

        "-------------------------------\n"

        "📊 *目前價格*\n"
        f"QQQM：`${qqqm:.2f}`\n"
        f"GOOG：`${goog:.2f}`\n\n"

        "📈 *自基準價格報酬*\n"
        f"QQQM：`{qqq_pct:+.2f}%` "
        f"(基準 ${base_qqq:.2f})\n"
        f"GOOG：`{goog_pct:+.2f}%` "
        f"(基準 ${base_goog:.2f})\n\n"

        "-------------------------------\n"

        "⚖️ *相對績效*\n"
        f"{relative}\n"
        f"目前持股角度差距：`{diff_pct:+.2f}%`\n"
        f"轉單門檻：`7.00%`\n\n"

        f"{status}"
    )


# ==========================================
# 轉單警報
# ==========================================

def build_trigger(
    hold,
    target,
    shares,
    sell,
    buy,
    diff
):

    cash = shares * sell
    buy_shares = int(cash // buy)

    return (
        "🚨 *【QQQM / GOOG 7% 輪動警報】*\n\n"

        f"目前持股：`{hold}`\n"
        f"相對價差：`{diff:+.2f}%`\n"
        f"觸發門檻：`7.00%`\n\n"

        "-------------------------------\n"

        f"1. *賣出 {hold}*\n"
        f"股數：`{shares:.5f}`\n"
        f"參考價格：`${sell:.2f}`\n"
        f"預估金額：`${cash:,.2f}`\n\n"

        f"2. *買入 {target}*\n"
        f"預估股數：`{buy_shares}`\n"
        f"參考價格：`${buy:.2f}`\n\n"

        "⚠️ 請僅操作上述策略部位。\n\n"

        "完成交易後，"
        "請在 config.csv 最下方新增一列，"
        f"current_hold 改成 `{target}`。"
    )


# ==========================================
# 績效圖
# ==========================================

def generate_chart(cfg, triggered=False, diff=0):

    try:

        start = str(
            cfg["trade_date"].iloc[0]
        )

        data = yf.download(
            ["QQQM", "GOOG"],
            start=start,
            auto_adjust=True,
            progress=False
        )

        if isinstance(
            data.columns,
            pd.MultiIndex
        ):
            data = data["Close"]

        else:
            data = data[
                ["QQQM", "GOOG"]
            ]

        data = data.dropna()

        if data.empty:
            return None

        first = cfg.iloc[0]

        first_hold = str(
            first["current_hold"]
        ).upper()

        qqq_base = float(
            first["base_qqq_price"]
        )

        goog_base = float(
            first["base_goog_price"]
        )

        shares = float(
            first["shares_held"]
        )

        if first_hold == "QQQM":
            initial = shares * qqq_base
        else:
            initial = shares * goog_base

        # ----------------------------------
        # 策略資產曲線
        # ----------------------------------

        values = []
        idx = 0
        hold = first_hold
        current_shares = shares

        for date, row in data.iterrows():

            date_str = date.strftime(
                "%Y-%m-%d"
            )

            while (
                idx + 1 < len(cfg)
                and str(
                    cfg["trade_date"].iloc[
                        idx + 1
                    ]
                ) <= date_str
            ):

                idx += 1

                current_shares = float(
                    cfg["shares_held"].iloc[idx]
                )

                hold = str(
                    cfg["current_hold"].iloc[idx]
                ).upper()

            price = (
                row["GOOG"]
                if hold == "GOOG"
                else row["QQQM"]
            )

            values.append(
                current_shares * float(price)
            )

        data["Strategy"] = values

        data["B&H_QQQM"] = (
            initial / qqq_base
        ) * data["QQQM"]

        data["B&H_GOOG"] = (
            initial / goog_base
        ) * data["GOOG"]

        final_strategy = data[
            "Strategy"
        ].iloc[-1]

        final_qqq = data[
            "B&H_QQQM"
        ].iloc[-1]

        final_goog = data[
            "B&H_GOOG"
        ].iloc[-1]

        ret_strategy = (
            final_strategy / initial - 1
        ) * 100

        ret_qqq = (
            final_qqq / initial - 1
        ) * 100

        ret_goog = (
            final_goog / initial - 1
        ) * 100

        # ----------------------------------
        # 畫圖
        # ----------------------------------

        plt.figure(figsize=(10, 5))

        plt.plot(
            data.index,
            data["B&H_GOOG"],
            label=(
                f"B&H GOOG "
                f"{ret_goog:+.2f}%"
            ),
            color="limegreen",
            linestyle="--",
            linewidth=2
        )

        plt.plot(
            data.index,
            data["B&H_QQQM"],
            label=(
                f"B&H QQQM "
                f"{ret_qqq:+.2f}%"
            ),
            color="royalblue",
            linestyle="--"
        )

        plt.plot(
            data.index,
            data["Strategy"],
            label=(
                f"My Strategy "
                f"{ret_strategy:+.2f}%"
            ),
            color="crimson",
            linewidth=2
        )

        if triggered:

            plt.scatter(
                data.index[-1],
                data["Strategy"].iloc[-1],
                color="red",
                marker="*",
                s=250,
                edgecolors="black",
                zorder=5
            )

            plt.annotate(
                f"Trigger\n{diff:+.2f}%",
                xy=(
                    data.index[-1],
                    data["Strategy"].iloc[-1]
                ),
                xytext=(-50, 25),
                textcoords="offset points",
                arrowprops={
                    "arrowstyle": "->",
                    "color": "red"
                }
            )

        plt.title(
            "QQQM / GOOG Rotation Strategy"
        )

        plt.xlabel("Date")
        plt.ylabel("Value (USD)")

        plt.legend()
        plt.grid(
            True,
            linestyle=":",
            alpha=0.6
        )

        plt.tight_layout()
        plt.savefig(
            CHART_FILE,
            dpi=150
        )
        plt.close()

        return CHART_FILE

    except Exception as e:

        print(
            f"⚠️ 績效圖失敗：{e}"
        )

        traceback.print_exc()

        return None


# ==========================================
# 主監控
# ==========================================

def run(mode="intraday"):

    print("=" * 60)
    print(
        "📡 QQQM / GOOG "
        "Rotation Monitor"
    )
    print("=" * 60)

    cfg = load_config()
    last = cfg.iloc[-1]

    hold = str(
        last["current_hold"]
    ).upper().strip()

    base_qqq = float(
        last["base_qqq_price"]
    )

    base_goog = float(
        last["base_goog_price"]
    )

    shares = float(
        last["shares_held"]
    )

    print(
        f"目前持股：{hold}"
    )

    print(
        f"持股股數：{shares}"
    )

    print(
        f"QQQM 基準：${base_qqq:.2f}"
    )

    print(
        f"GOOG 基準：${base_goog:.2f}"
    )

    # --------------------------------------
    # 即時價格
    # --------------------------------------

    qqqm, goog = get_prices()

    print()
    print(
        f"QQQM：${qqqm:.2f}"
    )

    print(
        f"GOOG：${goog:.2f}"
    )

    # --------------------------------------
    # 策略
    # --------------------------------------

    s = calculate(
        hold,
        base_qqq,
        base_goog,
        qqqm,
        goog
    )

    print()
    print(
        f"QQQM 報酬："
        f"{s['ret_qqq'] * 100:+.2f}%"
    )

    print(
        f"GOOG 報酬："
        f"{s['ret_goog'] * 100:+.2f}%"
    )

    print(
        f"QQQM - GOOG："
        f"{s['diff'] * 100:+.2f}%"
    )

    print(
        f"目前持股相對差距："
        f"{s['strategy_diff'] * 100:+.2f}%"
    )

    print(
        f"轉單方向："
        f"{hold} → {s['target']}"
    )

    print(
        f"7% 門檻："
        f"{'已觸發' if s['triggered'] else '未觸發'}"
    )

    # ======================================
    # DAILY / MANUAL
    #
    # 直接發結果
    # ======================================

    if mode in ["daily", "manual"]:

        msg = build_report(
            hold,
            shares,
            base_qqq,
            base_goog,
            qqqm,
            goog,
            s
        )

        notify(
            msg,
            line=(mode == "daily")
        )

        chart = generate_chart(
            cfg,
            triggered=s["triggered"],
            diff=s["strategy_diff"] * 100
        )

        if chart:
            send_photo(chart)

        print(
            "✅ 報告完成"
        )

        return

    # ======================================
    # INTRADAY
    #
    # 達 7% 才通知
    # ======================================

    if s["triggered"]:

        msg = build_trigger(
            hold,
            s["target"],
            shares,
            s["sell"],
            s["buy"],
            s["strategy_diff"] * 100
        )

        notify(
            msg,
            line=True
        )

        chart = generate_chart(
            cfg,
            triggered=True,
            diff=s["strategy_diff"] * 100
        )

        if chart:
            send_photo(chart)

        print(
            "🚨 7% 轉單警報已發送"
        )

    else:

        remaining = (
            THRESHOLD
            - s["strategy_diff"]
        ) * 100

        print(
            f"🔕 未達門檻，"
            f"距離觸發還有 "
            f"{remaining:.2f}%"
        )


# ==========================================
# Main
# ==========================================

if __name__ == "__main__":

    if len(sys.argv) > 1:

        if sys.argv[1] == "--manual":
            mode = "manual"

        elif sys.argv[1] == "--daily":
            mode = "daily"

        else:
            mode = "intraday"

    else:

        mode = "intraday"

    try:

        run(mode)

    except Exception as e:

        print("=" * 60)
        print("❌ 程式發生錯誤")
        print("=" * 60)

        print(e)

        traceback.print_exc()

        send_telegram(
            "❌ *【QQQM / GOOG Monitor 程式錯誤】*\n\n"
            f"`{str(e)[:3000]}`"
        )

