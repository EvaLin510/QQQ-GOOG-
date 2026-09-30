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
# Config 讀取
# ==========================================

def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"找不到 {CONFIG_FILE}")

    df = pd.read_csv(CONFIG_FILE)

    required = [
        "trade_date",
        "action",
        "base_hold",
        "base_hold_price",
        "current_hold",
        "current_hold_price",
        "shares_held"
    ]

    missing = [x for x in required if x not in df.columns]

    if missing:
        raise ValueError("config.csv 缺少欄位：" + ", ".join(missing))

    if df.empty:
        raise ValueError("config.csv 是空的")

    return df


# ==========================================
# 即時價格抓取
# ==========================================

def get_prices(base_hold, current_hold):
    tickers = yf.Tickers(f"{base_hold} {current_hold}")

    p_base = float(tickers.tickers[base_hold].fast_info["last_price"])
    p_current = float(tickers.tickers[current_hold].fast_info["last_price"])

    if not np.isfinite(p_base) or not np.isfinite(p_current):
        raise ValueError(f"無效價格：{base_hold}={p_base}, {current_hold}={p_current}")

    return p_base, p_current


# ==========================================
# 策略與績效計算
# ==========================================

def calculate(base_hold, current_hold, shares, p_base_init, p_curr_init, p_base_now, p_curr_now):

    # 計算自基準點以來的各自報酬率
    ret_base = p_base_now / p_base_init - 1
    ret_curr = p_curr_now / p_curr_init - 1

    # 計算基準標的相對目前持股的領先/落後幅度 (當 base 表現遠優於 current 時觸發換回)
    diff = ret_base - ret_curr

    # 現有持股市值
    current_val = shares * p_curr_now

    # 若留在原本對照標的（base_hold）的市值
    hypo_val = (shares * p_curr_init / p_base_init) * p_base_now

    # 機會成本損益
    pnl_diff = current_val - hypo_val

    return {
        "ret_base": ret_base,
        "ret_curr": ret_curr,
        "strategy_diff": diff,
        "triggered": diff > THRESHOLD,
        "sell": p_curr_now,
        "buy": p_base_now,
        "current_val": current_val,
        "hypo_val": hypo_val,
        "pnl_diff": pnl_diff
    }


# ==========================================
# 每日 / 手動報告
# ==========================================

def build_report(base_hold, current_hold, shares, p_base_init, p_curr_init, p_base_now, p_curr_now, s):

    base_pct = s["ret_base"] * 100
    curr_pct = s["ret_curr"] * 100
    diff_pct = s["strategy_diff"] * 100

    remaining = (THRESHOLD - s["strategy_diff"]) * 100

    if s["triggered"]:
        status = (
            f"🚨 已達 7% 轉單門檻\n"
            f"轉單方向：{current_hold} → {base_hold}"
        )
    else:
        status = (
            f"📌 目前維持：{current_hold}\n"
            f"距離 {current_hold} → {base_hold} "
            f"門檻還有：{remaining:.2f}%"
        )

    now = pd.Timestamp.now(tz="Asia/Taipei")
    pnl_status = "領先" if s["pnl_diff"] >= 0 else "落後"

    return (
        f"ℹ️️ *【{current_hold} / {base_hold} 策略追蹤報告】*\n\n"

        f"時間：`{now.strftime('%Y-%m-%d %H:%M')}`\n"
        f"目前持股：`{current_hold}`\n"
        f"持股股數：`{shares:.5f}`\n\n"

        "-------------------------------\n"

        "📊 *目前價格*\n"
        f"{current_hold}：`${p_curr_now:.2f}`\n"
        f"{base_hold}：`${p_base_now:.2f}`\n\n"

        "📈 *自基準價格報酬*\n"
        f"{current_hold}：`{curr_pct:+.2f}%` (基準 ${p_curr_init:.2f})\n"
        f"{base_hold}：`{base_pct:+.2f}%` (基準 ${p_base_init:.2f})\n\n"

        "-------------------------------\n"

        "⚖️ *相對績效與損益追蹤*\n"
        f"持股相對價差落後：`{diff_pct:+.2f}%`\n"
        f"目前持股市值：`${s['current_val']:,.2f}`\n"
        f"若留在 {base_hold} 市值：`${s['hypo_val']:,.2f}`\n"
        f"機會成本{pnl_status}：`${s['pnl_diff']:,.2f}`\n\n"

        f"{status}"
    )


# ==========================================
# 轉單警報
# ==========================================

def build_trigger(base_hold, current_hold, shares, sell, buy, diff):

    cash = shares * sell
    buy_shares = int(cash // buy)

    return (
        f"🚨 *【{current_hold} / {base_hold} 7% 輪動警報】*\n\n"

        f"目前持股：`{current_hold}`\n"
        f"相對價差落後：`{diff:+.2f}%`\n"
        f"觸發門檻：`7.00%`\n\n"

        "-------------------------------\n"

        f"1. *賣出 {current_hold}*\n"
        f"股數：`{shares:.5f}`\n"
        f"參考價格：`${sell:.2f}`\n"
        f"預估金額：`${cash:,.2f}`\n\n"

        f"2. *買入 {base_hold}*\n"
        f"預估股數：`{buy_shares}`\n"
        f"參考價格：`${buy:.2f}`\n\n"

        "⚠️ 請僅操作上述策略部位。\n\n"

        "完成交易後，請在 config.csv 最下方新增一列：\n"
        f"base_hold 改為 `{current_hold}`，current_hold 改為 `{base_hold}`。"
    )


# ==========================================
# 績效圖生成
# ==========================================

def generate_chart(cfg, base_hold, current_hold, triggered=False, diff=0):

    try:
        start = str(cfg["trade_date"].iloc[0])

        data = yf.download(
            [base_hold, current_hold],
            start=start,
            auto_adjust=True,
            progress=False
        )

        if isinstance(data.columns, pd.MultiIndex):
            data = data["Close"]
        else:
            data = data[[base_hold, current_hold]]

        data = data.dropna()

        if data.empty:
            return None

        first = cfg.iloc[0]
        f_base_hold = str(first["base_hold"]).upper()
        f_curr_hold = str(first["current_hold"]).upper()
        f_base_price = float(first["base_hold_price"])
        f_curr_price = float(first["current_hold_price"])
        f_shares = float(first["shares_held"])

        initial_cash = f_shares * f_curr_price

        data[f"B&H_{f_base_hold}"] = (initial_cash / f_base_price) * data[f_base_hold]
        data[f"B&H_{f_curr_hold}"] = (initial_cash / f_curr_price) * data[f_curr_hold]

        plt.figure(figsize=(10, 5))

        plt.plot(
            data.index,
            data[f"B&H_{f_curr_hold}"],
            label=f"Current Hold ({f_curr_hold})",
            color="limegreen",
            linestyle="--"
        )

        plt.plot(
            data.index,
            data[f"B&H_{f_base_hold}"],
            label=f"Base Target ({f_base_hold})",
            color="royalblue",
            linestyle="--"
        )

        if triggered:
            plt.scatter(
                data.index[-1],
                data[f"B&H_{f_curr_hold}"].iloc[-1],
                color="red",
                marker="*",
                s=250,
                edgecolors="black",
                zorder=5
            )

        plt.title(f"{f_curr_hold} vs {f_base_hold} Rotation Strategy")
        plt.xlabel("Date")
        plt.ylabel("Value (USD)")

        plt.legend()
        plt.grid(True, linestyle=":", alpha=0.6)

        plt.tight_layout()
        plt.savefig(CHART_FILE, dpi=150)
        plt.close()

        return CHART_FILE

    except Exception as e:
        print(f"⚠️ 績效圖失敗：{e}")
        traceback.print_exc()
        return None


# ==========================================
# 主監控流程
# ==========================================

def run(mode="intraday"):

    print("=" * 60)
    print("📡 Portfolio Rotation Monitor")
    print("=" * 60)

    cfg = load_config()
    last = cfg.iloc[-1]

    base_hold = str(last["base_hold"]).upper().strip()
    current_hold = str(last["current_hold"]).upper().strip()

    p_base_init = float(last["base_hold_price"])
    p_curr_init = float(last["current_hold_price"])
    shares = float(last["shares_held"])

    p_base_now, p_curr_now = get_prices(base_hold, current_hold)

    s = calculate(
        base_hold,
        current_hold,
        shares,
        p_base_init,
        p_curr_init,
        p_base_now,
        p_curr_now
    )

    if mode in ["daily", "manual"]:
        msg = build_report(
            base_hold,
            current_hold,
            shares,
            p_base_init,
            p_curr_init,
            p_base_now,
            p_curr_now,
            s
        )
        notify(msg, line=(mode == "daily"))
        chart = generate_chart(
            cfg,
            base_hold,
            current_hold,
            triggered=s["triggered"],
            diff=s["strategy_diff"] * 100
        )
        if chart:
            send_photo(chart)
        print("✅ 報告完成")
        return

    if s["triggered"]:
        msg = build_trigger(
            base_hold,
            current_hold,
            shares,
            s["sell"],
            s["buy"],
            s["strategy_diff"] * 100
        )
        notify(msg, line=True)
        chart = generate_chart(
            cfg,
            base_hold,
            current_hold,
            triggered=True,
            diff=s["strategy_diff"] * 100
        )
        if chart:
            send_photo(chart)
        print("🚨 7% 轉單警報已發送")
    else:
        remaining = (THRESHOLD - s["strategy_diff"]) * 100
        print(f"🔕 未達門檻，距離觸發還有 {remaining:.2f}%")


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
            "❌ *【Rotation Monitor 程式錯誤】*\n\n"
            f"`{str(e)[:3000]}`"
        )
