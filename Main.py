import sys
import os
import sqlite3
import time
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ==========================================
# 1. 環境變數與設定
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_USER_ID = os.environ.get("LINE_USER_ID")

DB_FILE = "strategy_data.db"
THRESHOLD = 0.07  # 7% 門檻


# ==========================================
# 2. 資料庫初始化與讀寫 (SQLite)
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS state (
            id INTEGER PRIMARY KEY,
            current_hold TEXT,
            base_qqq_price REAL,
            base_goog_price REAL,
            is_waiting_trade INTEGER,
            last_notify_time REAL,
            last_daily_chart_date TEXT
        )
    """
    )
    
    # 檢查並動態補充欄位 (相容舊資料庫)
    c.execute("PRAGMA table_info(state)")
    columns = [col[1] for col in c.fetchall()]
    if "last_daily_chart_date" not in columns:
        c.execute("ALTER TABLE state ADD COLUMN last_daily_chart_date TEXT DEFAULT ''")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT,
            action TEXT,
            qqq_price REAL,
            goog_price REAL,
            shares_held REAL
        )
    """
    )

    c.execute("SELECT COUNT(*) FROM state")
    if c.fetchone()[0] == 0:
        c.execute(
            """
            INSERT INTO state (id, current_hold, base_qqq_price, base_goog_price, is_waiting_trade, last_notify_time, last_daily_chart_date)
            VALUES (1, 'GOOG', 297.03, 348.00, 0, 0, '')
        """
        )
        c.execute(
            """
            INSERT INTO trade_history (trade_date, action, qqq_price, goog_price, shares_held)
            VALUES ('2026-06-15', 'BUY_GOOG', 297.03, 348.00, 85.35172)
        """
        )
        conn.commit()
    conn.close()


def get_state():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT current_hold, base_qqq_price, base_goog_price,"
        " is_waiting_trade, last_notify_time, last_daily_chart_date FROM state WHERE id=1"
    )
    row = c.fetchone()
    conn.close()
    return {
        "hold": row[0],
        "base_qqq": row[1],
        "base_goog": row[2],
        "is_waiting": row[3],
        "last_notify_time": row[4],
        "last_daily_chart_date": row[5] if len(row) > 5 and row[5] else "",
    }


def update_state_after_trade(new_hold, new_qqq, new_goog, today_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        UPDATE state 
        SET current_hold = ?, base_qqq_price = ?, base_goog_price = ?, is_waiting_trade = 0, last_notify_time = 0
        WHERE id = 1
    """,
        (new_hold, new_qqq, new_goog),
    )

    c.execute(
        """
        INSERT INTO trade_history (trade_date, action, qqq_price, goog_price, shares_held)
        VALUES (?, ?, ?, ?, ?)
    """,
        (today_str, f"BUY_{new_hold}", new_qqq, new_goog, 0),
    )
    conn.commit()
    conn.close()


def update_notify_status(is_waiting, notify_time):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        UPDATE state 
        SET is_waiting_trade = ?, last_notify_time = ?
        WHERE id = 1
    """,
        (is_waiting, notify_time),
    )
    conn.commit()
    conn.close()


def update_daily_chart_date(today_str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        UPDATE state 
        SET last_daily_chart_date = ?
        WHERE id = 1
    """,
        (today_str,),
    )
    conn.commit()
    conn.close()


# ==========================================
# 3. 雙平台訊息發送功能 (TG + LINE)
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
# 4. 繪製資產走勢圖
# ==========================================
def generate_chart():
    conn = sqlite3.connect(DB_FILE)
    trades_df = pd.read_sql_query(
        "SELECT * FROM trade_history ORDER BY trade_date ASC", conn
    )
    conn.close()

    start_date = trades_df["trade_date"].iloc[0]
    df = yf.download(["QQQM", "GOOG"], start=start_date, auto_adjust=True)[
        "Close"
    ].dropna()

    portfolio_values = []
    trade_dates = []

    current_idx = 0
    current_shares = trades_df["shares_held"].iloc[0]
    current_hold = (
        "GOOG" if "GOOG" in trades_df["action"].iloc[0] else "QQQM"
    )

    for date, row in df.iterrows():
        date_str = date.strftime("%Y-%m-%d")

        if (
            current_idx + 1 < len(trades_df)
            and trades_df["trade_date"].iloc[current_idx + 1] <= date_str
        ):
            current_idx += 1
            event = trades_df.iloc[current_idx]
            current_shares = event["shares_held"]
            current_hold = "GOOG" if "GOOG" in event["action"] else "QQQM"
            trade_dates.append(date)

        p_qqq = row["QQQM"]
        p_goog = row["GOOG"]
        val = current_shares * (p_goog if current_hold == "GOOG" else p_qqq)
        portfolio_values.append(val)

    df["My_Portfolio"] = portfolio_values
    init_cap = 100000.0
    df["B&H_QQQM"] = (
        init_cap / trades_df["qqq_price"].iloc[0]
    ) * df["QQQM"]
    df["B&H_GOOG"] = (
        init_cap / trades_df["goog_price"].iloc[0]
    ) * df["GOOG"]

    plt.figure(figsize=(10, 5))
    plt.plot(
        df.index,
        df["My_Portfolio"],
        label="My Live Strategy (7%)",
        color="red",
        linewidth=2,
    )
    plt.plot(
        df.index,
        df["B&H_QQQM"],
        label="Buy & Hold QQQM",
        color="blue",
        linestyle="--",
        alpha=0.5,
    )
    plt.plot(
        df.index,
        df["B&H_GOOG"],
        label="Buy & Hold GOOG",
        color="green",
        linestyle="--",
        alpha=0.5,
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

    plt.title("Live Performance: Real-time Portfolio vs B&H (7% Threshold)")
    plt.xlabel("Date")
    plt.ylabel("Value (USD)")
    plt.legend()
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.tight_layout()

    chart_file = "live_chart.png"
    plt.savefig(chart_file)
    plt.close()
    return chart_file


# ==========================================
# 5. 盤中監控與手動/自動訊號回覆邏輯
# ==========================================
def check_intraday_signal(is_manual=False):
    state = get_state()
    now_ts = time.time()
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT shares_held FROM trade_history ORDER BY id DESC LIMIT 1"
    )
    current_shares = c.fetchone()[0]
    conn.close()

    tickers = yf.Tickers("QQQM GOOG")
    p_qqq = float(tickers.tickers["QQQM"].fast_info["last_price"])
    p_goog = float(tickers.tickers["GOOG"].fast_info["last_price"])

    ret_qqq = (p_qqq - state["base_qqq"]) / state["base_qqq"]
    ret_goog = (p_goog - state["base_goog"]) / state["base_goog"]
    diff = ret_qqq - ret_goog

    curr_hold = state["hold"]
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

    # 情境 A：等待轉單狀態
    if state["is_waiting"] == 1:
        if now_ts - state["last_notify_time"] >= 3600 or is_manual:
            est_cash = current_shares * (p_qqq if curr_hold == "QQQM" else p_goog)
            est_buy_shares = int(est_cash // (p_goog if curr_hold == "QQQM" else p_qqq))

            msg = f"⏳ *【轉單催促提醒】*\n\n"
            msg += f"尚未收到轉單回報。當前相對價差：`{diff_pct:.2f}%`。\n\n"
            msg += f"📋 *請確認是否已完成 Firstrade 交易：*\n"
            msg += f"1. **賣出 {curr_hold}**：`{current_shares}` 股\n"
            msg += f"2. **買入 {target_hold}**：預估 `{est_buy_shares}` 股\n\n"
            msg += f"-----------------------------------\n"
            msg += f"💡 *完成後請至 Telegram 點擊指令複製並貼回更新：*\n"
            msg += f"*(三個數字依序為：QQQM單價 / GOOG單價 / 買入股數)*\n\n"
            msg += f"`/traded {target_hold} {p_qqq:.2f} {p_goog:.2f} {est_buy_shares}`"

            send_dual_notify(msg)
            update_notify_status(1, now_ts)

            chart_path = generate_chart()
            send_telegram_photo(chart_path)
        return

    # 情境 B：首次觸發轉單門檻 (7%)
    if triggered and state["is_waiting"] == 0:
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
        msg += f"💡 *完成後請至 Telegram 點擊指令複製並貼回更新：*\n"
        msg += f"*(三個數字依序為：QQQM單價 / GOOG單價 / 買入股數)*\n\n"
        msg += f"`/traded {target_hold} {p_qqq:.2f} {p_goog:.2f} {est_buy_shares}`"

        send_dual_notify(msg)
        update_notify_status(1, now_ts)

        chart_path = generate_chart()
        send_telegram_photo(chart_path)
        return

    # 情境 C：未達 7% 門檻（手動檢查 OR 每日自動傳送一次圖表）
    if not triggered:
        should_send_daily = state["last_daily_chart_date"] != today_str

        if is_manual or should_send_daily:
            msg = f"ℹ️ *【每日策略狀態報告】*\n\n" if should_send_daily and not is_manual else f"ℹ️ *【手動檢查狀態報告】*\n\n"
            msg += f"當前持股：`{curr_hold}` ({current_shares} 股)\n"
            msg += f"QQQM 現價：`${p_qqq:.2f}` (基準價 ${state['base_qqq']:.2f})\n"
            msg += f"GOOG 現價：`${p_goog:.2f}` (基準價 ${state['base_goog']:.2f})\n"
            msg += f"相對價差變動：`{diff_pct:.2f}%` (門檻 7%)\n\n"
            msg += f"📌 **結論：目前未達 7% 轉單門檻，維持原持股即可。**"

            send_dual_notify(msg)

            chart_path = generate_chart()
            send_telegram_photo(chart_path)

            update_daily_chart_date(today_str)


# ==========================================
# 6. Telegram 指令處理
# ==========================================
async def traded_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_hold = context.args[0].upper()
        new_qqq = float(context.args[1])
        new_goog = float(context.args[2])
        new_shares = float(context.args[3])
        today_str = pd.Timestamp.now().strftime("%Y-%m-%d")

        update_state_after_trade(new_hold, new_qqq, new_goog, today_str)

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            "UPDATE trade_history SET shares_held = ? WHERE id = (SELECT"
            " MAX(id) FROM trade_history)",
            (new_shares,),
        )
        conn.commit()
        conn.close()

        success_msg = (
            f"✅ *轉單完成！雙平台提醒已解除。*\n\n"
            f"當前持股：`{new_hold}` ({new_shares} 股)\n"
            f"QQQM 新基準價：`${new_qqq:.2f}`\n"
            f"GOOG 新基準價：`${new_goog:.2f}`"
        )

        send_line_msg(success_msg)

        await update.message.reply_text(
            f"{success_msg}\n\n正在繪製最新實盤資產走勢圖..."
        )

        chart_path = generate_chart()
        await context.bot.send_photo(
            chat_id=update.effective_chat.id, photo=open(chart_path, "rb")
        )

    except Exception as e:
        await update.message.reply_text(
            "❌ *格式錯誤！* 請參考預設格式複製貼上：\n"
            "`/traded [標的 QQQM/GOOG] [QQQM成交價] [GOOG成交價] [買入股數]`\n\n"
            "範例：`/traded QQQM 283.29 356.65 353`"
        )


async def img_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("📊 正在繪製最新實盤資產走勢圖...")
        chart_path = generate_chart()
        await context.bot.send_photo(
            chat_id=update.effective_chat.id, photo=open(chart_path, "rb")
        )
    except Exception as e:
        await update.message.reply_text(f"❌ 繪製圖片失敗: {e}")


# ==========================================
# 7. 主程式
# ==========================================
if __name__ == "__main__":
    init_db()

    if len(sys.argv) > 1 and sys.argv[1] == "--manual":
        print("🔍 執行單次手動狀態檢查...")
        check_intraday_signal(is_manual=True)
    else:
        if not TELEGRAM_TOKEN:
            print("⚠️ 未設定 TELEGRAM_TOKEN，改執行單次檢查...")
            check_intraday_signal(is_manual=True)
        else:
            try:
                app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
                app.add_handler(CommandHandler("traded", traded_command))
                app.add_handler(CommandHandler(["img", "IMG"], img_command))

                job_q = getattr(app, "job_queue", None)
                if job_q is not None:
                    job_q.run_repeating(
                        lambda ctx: check_intraday_signal(is_manual=False),
                        interval=900,
                        first=10,
                    )
                    print("🤖 盤中監控與 TG/LINE 雙推播系統已啟動...")
                    app.run_polling()
                else:
                    print("⚠️ 未載入 JobQueue，改執行單次檢查...")
                    check_intraday_signal(is_manual=False)
            except Exception as e:
                print(f"❌ 啟動 Bot 失敗: {e}")