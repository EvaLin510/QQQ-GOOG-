import sys
import os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ==========================================
# 1. 環境變數與設定
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")

CONFIG_FILE = "config.csv"
THRESHOLD = 0.07  # 7% 門檻


# ==========================================
# 2. 雙平台訊息發送功能 (TG + LINE)
# ==========================================
def send_telegram_msg(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }
    requests.post(url, json=payload)


def send_telegram_photo(photo_path):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as photo:
        payload = {"chat_id": TELEGRAM_CHAT_ID}
        files = {"photo": photo}
        requests.post(url, data=payload, files=files)


def send_line_msg(text):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        return
    clean_text = (
        text.replace("*", "").replace("`", "").replace("-------------------", "----------------")
    )
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID.strip(),
        "messages": [{"type": "text", "text": clean_text}],
    }
    requests.post(url, headers=headers, json=payload)


def send_dual_notify(text):
    send_telegram_msg(text)
    send_line_msg(text)


# ==========================================
# 3. 繪製資產走勢圖 (直接讀取 config.csv)
# ==========================================
def generate_chart(df_cfg, is_triggered=False, diff_pct=0.0):
    start_date = str(df_cfg["trade_date"].iloc[0])
    df = yf.download(["QQQM", "GOOG"], start=start_date, auto_adjust=True)[
        "Close"
    ].dropna()

    portfolio_values = []
    trade_dates = []

    current_idx = 0
    init_shares = float(df_cfg["shares_held"].iloc[0])
    init_goog_price = float(df_cfg["base_goog_price"].iloc[0])
    init_qqq_price = float(df_cfg["base_qqq_price"].iloc[0])

    init_cap = init_shares * init_goog_price

    current_shares = init_shares
    current_hold = (
        "GOOG" if "GOOG" in str(df_cfg["action"].iloc[0]) else "QQQM"
    )

    for date, row in df.iterrows():
        date_str = date.strftime("%Y-%m-%d")

        if (
            current_idx + 1 < len(df_cfg)
            and str(df_cfg["trade_date"].iloc[current_idx + 1]) <= date_str
        ):
            current_idx += 1
            event = df_cfg.iloc[current_idx]
            current_shares = float(event["shares_held"])
            current_hold = "GOOG" if "GOOG" in str(event["action"]) else "QQQM"
            trade_dates.append(date)

        p_qqq = row["QQQM"]
        p_goog = row["GOOG"]
        val = current_shares * (p_goog if current_hold == "GOOG" else p_qqq)
        portfolio_values.append(val)

    df["My_Portfolio"] = portfolio_values
    df["B&H_QQQM"] = (init_cap / init_qqq_price) * df["QQQM"]
    df["B&H_GOOG"] = (init_cap / init_goog_price) * df["GOOG"]

    last_my_val = df["My_Portfolio"].iloc[-1]
    last_qqq_val = df["B&H_QQQM"].iloc[-1]
    last_goog_val = df["B&H_GOOG"].iloc[-1]

    ret_my = ((last_my_val - init_cap) / init_cap) * 100
    ret_qqq = ((last_qqq_val - init_cap) / init_cap) * 100
    ret_goog = ((last_goog_val - init_cap) / init_cap) * 100

    plt.figure(figsize=(10, 5))

    plt.plot(
        df.index,
        df["B&H_GOOG"],
        label=f"Buy & Hold GOOG: ${last_goog_val:,.0f} ({ret_goog:+.2f}%)",
        color="limegreen",
        linestyle="--",
        linewidth=2.8,
        alpha=0.7,
        zorder=1,
    )

    plt.plot(
        df.index,
        df["B&H_QQQM"],
        label=f"Buy & Hold QQQM: ${last_qqq_val:,.0f} ({ret_qqq:+.2f}%)",
        color="royalblue",
        linestyle="--",
        linewidth=1.5,
        alpha=0.7,
        zorder=2,
    )

    plt.plot(
        df.index,
        df["My_Portfolio"],
        label=f"My Live Strategy: ${last_my_val:,.0f} ({ret_my:+.2f}%)",
        color="crimson",
        linewidth=1.8,
        zorder=3,
    )

    for t_date in trade_dates:
        plt.scatter(
            t_date,
            df.loc[t_date, "My_Portfolio"],
            color="gold",
            edgecolors="black",
            s=100,
            zorder=5,
        )

    latest_date = df.index[-1]
    latest_val = df["My_Portfolio"].iloc[-1]

    if is_triggered:
        plt.scatter(
            latest_date,
            latest_val,
            color="red",
            marker="*",
            s=250,
            edgecolors="black",
            zorder=6,
        )
        plt.annotate(
            f"Trigger Signal!\n({diff_pct:+.2f}%)",
            xy=(latest_date, latest_val),
            xytext=(-50, 25),
            textcoords="offset points",
            arrowprops=dict(arrowstyle="->", color="red", lw=1.5),
            fontsize=9,
            fontweight="bold",
            color="darkred",
            bbox=dict(boxstyle="round,pad=0.3", fc="yellow", ec="red", alpha=0.9),
        )

    plt.title("Live Performance: Real-time Portfolio vs B&H (7% Threshold)")
    plt.xlabel("Date")
    plt.ylabel("Value (USD)")
    plt.legend(loc="upper left")
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.tight_layout()

    chart_file = "live_chart.png"
    plt.savefig(chart_file)
    plt.close()
    return chart_file


# ==========================================
# 4. 核心檢測邏輯
# ==========================================
def run_monitor(force_report=False):
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 找不到 {CONFIG_FILE}，請確保專案根目錄有此檔案。")
        return

    df_cfg = pd.read_csv(CONFIG_FILE)
    last_cfg = df_cfg.iloc[-1].to_dict()

    curr_hold = str(last_cfg["current_hold"]).strip().upper()
    base_qqq = float(last_cfg["base_qqq_price"])
    base_goog = float(last_cfg["base_goog_price"])
    current_shares = float(last_cfg["shares_held"])

    tickers = yf.Tickers("QQQM GOOG")
    p_qqq = float(tickers.tickers["QQQM"].fast_info["last_price"])
    p_goog = float(tickers.tickers["GOOG"].fast_info["last_price"])

    ret_qqq = (p_qqq - base_qqq) / base_qqq
    ret_goog = (p_goog - base_goog) / base_goog
    diff = ret_qqq - ret_goog

    target_hold = "GOOG" if curr_hold == "QQQM" else "QQQM"
    triggered = False

    if curr_hold == "QQQM" and diff > THRESHOLD:
        triggered = True
        diff_pct = diff * 100
        sell_price, buy_price = p_qqq, p_goog
    elif curr_hold == "GOOG" and -diff > THRESHOLD:
        triggered = True
        diff_pct = -diff * 100
        sell_price, buy_price = p_goog, p_qqq
    else:
        diff_pct = (diff if curr_hold == "QQQM" else -diff) * 100

    now_taipei = pd.Timestamp.now(tz="Asia/Taipei")
    is_morning_report_time = (now_taipei.hour == 9)

    # 情境 A：觸發 7% 門檻 (盤中每 15 分鐘通知)
    if triggered:
        est_cash = current_shares * sell_price
        est_buy_shares = int(est_cash // buy_price)

        msg = f"🚨 *【盤中輪動觸發警報 (7% 門檻)】*\n\n"
        msg += f"當前策略持股：`{curr_hold}`\n"
        msg += f"相對價差漲幅：`{diff_pct:.2f}%` (門檻 7%)\n\n"
        msg += f"-----------------------------------\n"
        msg += f"📋 *Firstrade 專屬策略帳戶下單指示：*\n"
        msg += f"1. **賣出 {curr_hold}**：指定賣出 `{current_shares}` 股 (預估收回 ${est_cash:,.2f})\n"
        msg += f"2. **買入 {target_hold}**：預估可買入 `{est_buy_shares}` 股\n"
        msg += f"*(⚠️ 注意：請僅操作上述股數，勿動到其他長期持有的部位)*\n\n"
        msg += f"-----------------------------------\n"
        msg += f"💡 *完成交易後，請至 GitHub 的 `config.csv` 最下方新增一列轉單紀錄。*"

        send_dual_notify(msg)
        chart_path = generate_chart(df_cfg, is_triggered=True, diff_pct=diff_pct)
        send_telegram_photo(chart_path)
        print("🚨 已發送 7% 轉單警報。")
        return

    # 情境 B：未達門檻，但屬於早上 09:00 或手動執行 (發送日報)
    if is_morning_report_time or force_report:
        msg = f"ℹ️ *【每日策略狀態報告】*\n\n" if is_morning_report_time else f"ℹ️ *【手動檢查狀態報告】*\n\n"
        msg += f"當前持股：`{curr_hold}` ({current_shares} 股)\n"
        msg += f"QQQM 現價：`${p_qqq:.2f}` (基準價 ${base_qqq:.2f})\n"
        msg += f"GOOG 現價：`${p_goog:.2f}` (基準價 ${base_goog:.2f})\n"
        msg += f"相對價差變動：`{diff_pct:.2f}%` (門檻 7%)\n\n"
        msg += f"📌 **結論：目前未達 7% 轉單門檻，維持原持股即可。**"

        send_dual_notify(msg)
        chart_path = generate_chart(df_cfg, is_triggered=False, diff_pct=diff_pct)
        send_telegram_photo(chart_path)
        print("ℹ️ 已發送每日策略報告。")
        return

    # 情境 C：盤中監控未達門檻 (靜默關閉，不打擾)
    print(f"⏱️ 當前價差變動 {diff_pct:.2f}%，未達 7% 門檻，保持靜默。")


# ==========================================
# 5. 主程式
# ==========================================
if __name__ == "__main__":
    is_manual = len(sys.argv) > 1 and sys.argv[1] == "--manual"
    run_monitor(force_report=is_manual)