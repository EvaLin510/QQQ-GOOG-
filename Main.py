import sys
import os
import time
import traceback
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

# 相對價差觸發門檻
THRESHOLD = 0.07  # 7%

# 每日報告時間
DAILY_REPORT_HOUR = 9

# 每日報告允許的時間範圍
# 例如 GitHub Actions 可能因排程延遲幾分鐘
DAILY_REPORT_MAX_MINUTE = 15

# 用來記錄今天是否已經發過每日報告
DAILY_REPORT_STATE_FILE = "daily_report_state.txt"


# ==========================================
# 2. Telegram
# ==========================================

def send_telegram_msg(text):
    """
    發送 Telegram 文字訊息
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram 環境變數未設定，略過 Telegram。")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        if response.ok:
            return True

        print(f"❌ Telegram 發送失敗：{response.status_code}")
        print(response.text)
        return False

    except Exception as e:
        print(f"❌ Telegram 發送例外：{e}")
        return False


# ==========================================
# 3. Telegram 圖片
# ==========================================

def send_telegram_photo(photo_path):
    """
    發送 Telegram 圖片
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram 環境變數未設定，略過圖片。")
        return False

    if not os.path.exists(photo_path):
        print(f"❌ 找不到圖片：{photo_path}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"

    try:
        with open(photo_path, "rb") as photo:

            payload = {
                "chat_id": TELEGRAM_CHAT_ID
            }

            files = {
                "photo": photo
            }

            response = requests.post(
                url,
                data=payload,
                files=files,
                timeout=30
            )

        if response.ok:
            return True

        print(f"❌ Telegram 圖片發送失敗：{response.status_code}")
        print(response.text)
        return False

    except Exception as e:
        print(f"❌ Telegram 圖片發送例外：{e}")
        return False


# ==========================================
# 4. LINE
# ==========================================

def send_line_msg(text):
    """
    發送 LINE Push Message
    """
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ LINE 環境變數未設定，略過 LINE。")
        return False

    clean_text = (
        text
        .replace("*", "")
        .replace("`", "")
        .replace("-------------------", "----------------")
    )

    url = "https://api.line.me/v2/bot/message/push"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
    }

    payload = {
        "to": LINE_USER_ID.strip(),
        "messages": [
            {
                "type": "text",
                "text": clean_text
            }
        ],
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=15
        )

        if response.ok:
            return True

        print(f"❌ LINE 發送失敗：{response.status_code}")
        print(response.text)
        return False

    except Exception as e:
        print(f"❌ LINE 發送例外：{e}")
        return False


# ==========================================
# 5. 通知控制
# ==========================================

def send_dual_notify(text, send_line=True):
    """
    一般正式通知：
        Telegram + LINE

    send_line=False：
        只發 Telegram

    用於 --manual 測試。
    """

    send_telegram_msg(text)

    if send_line:
        send_line_msg(text)


# ==========================================
# 6. 取得目前台北時間
# ==========================================

def get_taipei_now():
    return pd.Timestamp.now(tz="Asia/Taipei")


# ==========================================
# 7. 每日報告防重複
# ==========================================

def already_sent_daily_report(today_str):
    """
    確認今天是否已經發送過每日報告。
    """

    if not os.path.exists(DAILY_REPORT_STATE_FILE):
        return False

    try:
        with open(
            DAILY_REPORT_STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            last_date = f.read().strip()

        return last_date == today_str

    except Exception as e:
        print(f"⚠️ 讀取每日報告狀態失敗：{e}")
        return False


def mark_daily_report_sent(today_str):
    """
    記錄今天已經發送每日報告。
    """

    try:
        with open(
            DAILY_REPORT_STATE_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(today_str)

        return True

    except Exception as e:
        print(f"⚠️ 寫入每日報告狀態失敗：{e}")
        return False


# ==========================================
# 8. 判斷是否該發每日報告
# ==========================================

def should_send_daily_report():
    """
    每天台灣時間約 09:00 發一次。

    允許：
        09:00 ~ 09:15

    避免 GitHub Actions 因排程延遲而漏掉。
    """

    now = get_taipei_now()

    today_str = now.strftime("%Y-%m-%d")

    if now.hour != DAILY_REPORT_HOUR:
        return False

    if now.minute > DAILY_REPORT_MAX_MINUTE:
        return False

    if already_sent_daily_report(today_str):
        return False

    return True


# ==========================================
# 9. 讀取 Config
# ==========================================

def load_config():
    """
    讀取 config.csv。

    設計規則：
    最後一筆 = 目前有效策略狀態
    """

    if not os.path.exists(CONFIG_FILE):

        print(
            f"❌ 找不到 {CONFIG_FILE}，"
            "請確保專案根目錄有此檔案。"
        )

        return None

    try:

        df_cfg = pd.read_csv(CONFIG_FILE)

    except Exception as e:

        print(f"❌ config.csv 讀取失敗：{e}")

        return None

    if df_cfg.empty:

        print("❌ config.csv 是空的。")

        return None

    required_columns = [
        "trade_date",
        "action",
        "current_hold",
        "base_qqq_price",
        "base_goog_price",
        "shares_held",
    ]

    missing_columns = [
        col for col in required_columns
        if col not in df_cfg.columns
    ]

    if missing_columns:

        print(
            "❌ config.csv 缺少欄位："
            + ", ".join(missing_columns)
        )

        return None

    return df_cfg


# ==========================================
# 10. 取得即時價格
# ==========================================

def get_current_prices():

    try:

        tickers = yf.Tickers("QQQM GOOG")

        qqqm = tickers.tickers["QQQM"]
        goog = tickers.tickers["GOOG"]

        p_qqq = qqqm.fast_info.get("last_price")
        p_goog = goog.fast_info.get("last_price")

        if p_qqq is None or p_goog is None:
            raise ValueError(
                f"無法取得即時價格："
                f"QQQM={p_qqq}, GOOG={p_goog}"
            )

        p_qqq = float(p_qqq)
        p_goog = float(p_goog)

        if not np.isfinite(p_qqq):
            raise ValueError("QQQM 價格不是有效數字。")

        if not np.isfinite(p_goog):
            raise ValueError("GOOG 價格不是有效數字。")

        return p_qqq, p_goog

    except Exception as e:

        print(f"❌ 即時價格取得失敗：{e}")

        raise


# ==========================================
# 11. 計算策略狀態
# ==========================================

def calculate_strategy(
    curr_hold,
    base_qqq,
    base_goog,
    p_qqq,
    p_goog
):

    # QQQM 自基準價格的報酬
    ret_qqq = (
        (p_qqq - base_qqq)
        / base_qqq
    )

    # GOOG 自基準價格的報酬
    ret_goog = (
        (p_goog - base_goog)
        / base_goog
    )

    # QQQM 相對 GOOG 的表現
    #
    # 例如：
    # QQQM +15%
    # GOOG +5%
    #
    # diff = +10%
    #
    diff = ret_qqq - ret_goog

    curr_hold = curr_hold.upper().strip()

    if curr_hold == "GOOG":

        # 目前持有 GOOG
        #
        # QQQM 比 GOOG 強 7%
        # → GOOG → QQQM

        strategy_diff = diff

        target_hold = "QQQM"

        triggered = strategy_diff > THRESHOLD

        if triggered:

            sell_price = p_goog
            buy_price = p_qqq

        else:

            sell_price = None
            buy_price = None

    elif curr_hold == "QQQM":

        # 目前持有 QQQM
        #
        # GOOG 比 QQQM 強 7%
        # → QQQM → GOOG

        strategy_diff = -diff

        target_hold = "GOOG"

        triggered = strategy_diff > THRESHOLD

        if triggered:

            sell_price = p_qqq
            buy_price = p_goog

        else:

            sell_price = None
            buy_price = None

    else:

        raise ValueError(
            f"config.csv 的 current_hold 無法辨識：{curr_hold}"
        )

    return {
        "ret_qqq": ret_qqq,
        "ret_goog": ret_goog,
        "diff": diff,
        "strategy_diff": strategy_diff,
        "target_hold": target_hold,
        "triggered": triggered,
        "sell_price": sell_price,
        "buy_price": buy_price,
    }


# ==========================================
# 12. 產生績效圖
# ==========================================

def generate_chart(
    df_cfg,
    is_triggered=False,
    diff_pct=0.0
):

    try:

        start_date = str(
            df_cfg["trade_date"].iloc[0]
        )

        df = yf.download(
            ["QQQM", "GOOG"],
            start=start_date,
            auto_adjust=True,
            progress=False
        )["Close"].dropna()

        if df.empty:

            print("⚠️ 無法產生績效圖：歷史資料為空。")

            return None

        portfolio_values = []
        trade_dates = []

        current_idx = 0

        init_shares = float(
            df_cfg["shares_held"].iloc[0]
        )

        init_goog_price = float(
            df_cfg["base_goog_price"].iloc[0]
        )

        init_qqq_price = float(
            df_cfg["base_qqq_price"].iloc[0]
        )

        init_cap = (
            init_shares
            * init_goog_price
        )

        current_shares = init_shares

        first_action = str(
            df_cfg["action"].iloc[0]
        ).upper()

        first_hold = str(
            df_cfg["current_hold"].iloc[0]
        ).upper()

        if "GOOG" in first_action or first_hold == "GOOG":
            current_hold = "GOOG"
        else:
            current_hold = "QQQM"

        for date, row in df.iterrows():

            date_str = date.strftime("%Y-%m-%d")

            # 如果進入下一筆交易日期
            if (
                current_idx + 1 < len(df_cfg)
                and str(
                    df_cfg["trade_date"].iloc[
                        current_idx + 1
                    ]
                ) <= date_str
            ):

                current_idx += 1

                event = df_cfg.iloc[current_idx]

                current_shares = float(
                    event["shares_held"]
                )

                event_hold = str(
                    event["current_hold"]
                ).upper().strip()

                event_action = str(
                    event["action"]
                ).upper()

                if (
                    event_hold == "GOOG"
                    or "GOOG" in event_action
                ):

                    current_hold = "GOOG"

                elif (
                    event_hold == "QQQM"
                    or "QQQM" in event_action
                ):

                    current_hold = "QQQM"

                trade_dates.append(date)

            p_qqq = float(row["QQQM"])
            p_goog = float(row["GOOG"])

            if current_hold == "GOOG":

                val = current_shares * p_goog

            else:

                val = current_shares * p_qqq

            portfolio_values.append(val)

        df["My_Portfolio"] = portfolio_values

        # Buy & Hold QQQM
        df["B&H_QQQM"] = (
            init_cap / init_qqq_price
        ) * df["QQQM"]

        # Buy & Hold GOOG
        df["B&H_GOOG"] = (
            init_cap / init_goog_price
        ) * df["GOOG"]

        last_my_val = df["My_Portfolio"].iloc[-1]
        last_qqq_val = df["B&H_QQQM"].iloc[-1]
        last_goog_val = df["B&H_GOOG"].iloc[-1]

        ret_my = (
            (last_my_val - init_cap)
            / init_cap
        ) * 100

        ret_qqq = (
            (last_qqq_val - init_cap)
            / init_cap
        ) * 100

        ret_goog = (
            (last_goog_val - init_cap)
            / init_cap
        ) * 100

        plt.figure(figsize=(10, 5))

        plt.plot(
            df.index,
            df["B&H_GOOG"],
            label=(
                f"Buy & Hold GOOG: "
                f"${last_goog_val:,.0f} "
                f"({ret_goog:+.2f}%)"
            ),
            color="limegreen",
            linestyle="--",
            linewidth=2.8,
            alpha=0.7,
            zorder=1,
        )

        plt.plot(
            df.index,
            df["B&H_QQQM"],
            label=(
                f"Buy & Hold QQQM: "
                f"${last_qqq_val:,.0f} "
                f"({ret_qqq:+.2f}%)"
            ),
            color="royalblue",
            linestyle="--",
            linewidth=1.5,
            alpha=0.7,
            zorder=2,
        )

        plt.plot(
            df.index,
            df["My_Portfolio"],
            label=(
                f"My Live Strategy: "
                f"${last_my_val:,.0f} "
                f"({ret_my:+.2f}%)"
            ),
            color="crimson",
            linewidth=1.8,
            zorder=3,
        )

        # 標示交易點
        for t_date in trade_dates:

            if t_date in df.index:

                plt.scatter(
                    t_date,
                    df.loc[
                        t_date,
                        "My_Portfolio"
                    ],
                    color="gold",
                    edgecolors="black",
                    s=100,
                    zorder=5,
                )

        # 最新點
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
                f"Trigger Signal!\n"
                f"({diff_pct:+.2f}%)",
                xy=(
                    latest_date,
                    latest_val
                ),
                xytext=(-50, 25),
                textcoords="offset points",
                arrowprops=dict(
                    arrowstyle="->",
                    color="red",
                    lw=1.5
                ),
                fontsize=9,
                fontweight="bold",
                color="darkred",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    fc="yellow",
                    ec="red",
                    alpha=0.9
                ),
            )

        plt.title(
            "Live Performance: "
            "Real-time Portfolio vs B&H "
            "(7% Threshold)"
        )

        plt.xlabel("Date")
        plt.ylabel("Value (USD)")

        plt.legend(loc="upper left")

        plt.grid(
            True,
            linestyle=":",
            alpha=0.6
        )

        plt.tight_layout()

        chart_file = "live_chart.png"

        plt.savefig(
            chart_file,
            dpi=150
        )

        plt.close()

        return chart_file

    except Exception as e:

        print(
            f"⚠️ 績效圖產生失敗：{e}"
        )

        traceback.print_exc()

        return None


# ==========================================
# 13. 建立每日狀態訊息
# ==========================================

def build_daily_report(
    curr_hold,
    current_shares,
    base_qqq,
    base_goog,
    p_qqq,
    p_goog,
    strategy
):

    ret_qqq_pct = (
        strategy["ret_qqq"] * 100
    )

    ret_goog_pct = (
        strategy["ret_goog"] * 100
    )

    diff_pct = (
        strategy["strategy_diff"] * 100
    )

    remaining_pct = (
        THRESHOLD
        - strategy["strategy_diff"]
    ) * 100

    target_hold = strategy["target_hold"]

    if strategy["triggered"]:

        conclusion = (
            f"🚨 已達 7% 轉單門檻\n"
            f"建議執行：{curr_hold} → {target_hold}"
        )

    else:

        conclusion = (
            f"📌 目前維持 {curr_hold}\n"
            f"距離 {curr_hold} → {target_hold} "
            f"的 7% 轉單門檻還有 "
            f"{remaining_pct:.2f}%"
        )

    now = get_taipei_now()

    msg = (
        f"ℹ️ *【每日策略狀態報告】*\n\n"

        f"時間：`{now.strftime('%Y-%m-%d %H:%M')}`\n\n"

        f"目前持股：`{curr_hold}`\n"
        f"持股股數：`{current_shares:.5f}`\n\n"

        f"-------------------------------\n"

        f"📊 *目前價格*\n"
        f"QQQM：`${p_qqq:.2f}`\n"
        f"GOOG：`${p_goog:.2f}`\n\n"

        f"📈 *自基準價格報酬*\n"
        f"QQQM：`{ret_qqq_pct:+.2f}%` "
        f"(基準 ${base_qqq:.2f})\n"

        f"GOOG：`{ret_goog_pct:+.2f}%` "
        f"(基準 ${base_goog:.2f})\n\n"

        f"-------------------------------\n"

        f"⚖️ *相對表現*\n"
        f"策略相對差距：`{diff_pct:+.2f}%`\n"
        f"轉單門檻：`7.00%`\n\n"

        f"{conclusion}"
    )

    return msg


# ==========================================
# 14. 建立轉單警報
# ==========================================

def build_trigger_message(
    curr_hold,
    target_hold,
    current_shares,
    sell_price,
    buy_price,
    diff_pct
):

    est_cash = (
        current_shares
        * sell_price
    )

    est_buy_shares = int(
        est_cash // buy_price
    )

    msg = (
        f"🚨 *【盤中輪動觸發警報 "
        f"(7% 門檻)】*\n\n"

        f"當前策略持股：`{curr_hold}`\n"

        f"相對價差："
        f"`{diff_pct:+.2f}%`\n"

        f"觸發門檻：`7.00%`\n\n"

        f"-----------------------------------\n"

        f"📋 *Firstrade 專屬策略帳戶下單指示：*\n\n"

        f"1. **賣出 {curr_hold}**\n"
        f"指定賣出：`{current_shares:.5f}` 股\n"
        f"預估收回：`${est_cash:,.2f}`\n"
        f"參考價格：`${sell_price:.2f}`\n\n"

        f"2. **買入 {target_hold}**\n"
        f"預估可買入：`{est_buy_shares}` 股\n"
        f"參考價格：`${buy_price:.2f}`\n\n"

        f"⚠️ 注意：請僅操作上述股數，"
        f"勿動到其他長期持有的部位。\n\n"

        f"-----------------------------------\n"

        f"💡 完成交易後，"
        f"請至 GitHub 的 `config.csv` "
        f"最下方新增一列轉單紀錄。\n\n"

        f"新的一列必須將 `current_hold` "
        f"改成 `{target_hold}`。"
    )

    return msg


# ==========================================
# 15. 核心監控
# ==========================================

def run_monitor(
    force_report=False
):

    print("=" * 60)
    print("📡 QQQM / GOOG 輪動策略監控")
    print("=" * 60)

    # --------------------------------------
    # 讀取 config
    # --------------------------------------

    df_cfg = load_config()

    if df_cfg is None:
        return

    # 最後一列 = 目前策略狀態
    last_cfg = (
        df_cfg.iloc[-1]
        .to_dict()
    )

    curr_hold = str(
        last_cfg["current_hold"]
    ).strip().upper()

    base_qqq = float(
        last_cfg["base_qqq_price"]
    )

    base_goog = float(
        last_cfg["base_goog_price"]
    )

    current_shares = float(
        last_cfg["shares_held"]
    )

    trade_date = str(
        last_cfg["trade_date"]
    )

    action = str(
        last_cfg["action"]
    )

    print(f"📅 最新交易日：{trade_date}")
    print(f"📝 最新 Action：{action}")
    print(f"💼 目前持股：{curr_hold}")
    print(f"💰 持股數量：{current_shares}")

    # --------------------------------------
    # 驗證持股
    # --------------------------------------

    if curr_hold not in ["GOOG", "QQQM"]:

        print(
            f"❌ current_hold 不合法：{curr_hold}"
        )

        return

    # --------------------------------------
    # 取得即時價格
    # --------------------------------------

    try:

        p_qqq, p_goog = get_current_prices()

    except Exception:

        print(
            "❌ 無法取得目前價格，"
            "本次監控結束。"
        )

        return

    print()
    print(f"QQQM：${p_qqq:.2f}")
    print(f"GOOG：${p_goog:.2f}")

    # --------------------------------------
    # 計算策略
    # --------------------------------------

    try:

        strategy = calculate_strategy(
            curr_hold,
            base_qqq,
            base_goog,
            p_qqq,
            p_goog
        )

    except Exception as e:

        print(
            f"❌ 策略計算失敗：{e}"
        )

        return

    ret_qqq_pct = (
        strategy["ret_qqq"] * 100
    )

    ret_goog_pct = (
        strategy["ret_goog"] * 100
    )

    diff_pct = (
        strategy["strategy_diff"] * 100
    )

    print()
    print(
        f"QQQM 報酬："
        f"{ret_qqq_pct:+.2f}%"
    )

    print(
        f"GOOG 報酬："
        f"{ret_goog_pct:+.2f}%"
    )

    print(
        f"目前持股角度的相對差距："
        f"{diff_pct:+.2f}%"
    )

    print(
        f"轉單方向："
        f"{curr_hold} → "
        f"{strategy['target_hold']}"
    )

    # ======================================
    # 情境 A
    # 已達 7% 轉單門檻
    # ======================================

    if strategy["triggered"]:

        sell_price = strategy["sell_price"]
        buy_price = strategy["buy_price"]

        msg = build_trigger_message(
            curr_hold=curr_hold,
            target_hold=strategy["target_hold"],
            current_shares=current_shares,
            sell_price=sell_price,
            buy_price=buy_price,
            diff_pct=diff_pct
        )

        # 正式觸發：
        # Telegram + LINE
        send_dual_notify(
            msg,
            send_line=True
        )

        chart_path = generate_chart(
            df_cfg,
            is_triggered=True,
            diff_pct=diff_pct
        )

        if chart_path:
            send_telegram_photo(chart_path)

        print()
        print(
            "🚨 已發送 7% 轉單警報 "
            "(Telegram + LINE)。"
        )

        return

    # ======================================
    # 情境 B
    # 每日報告
    # ======================================

    if force_report:

        msg = build_daily_report(
            curr_hold=curr_hold,
            current_shares=current_shares,
            base_qqq=base_qqq,
            base_goog=base_goog,
            p_qqq=p_qqq,
            p_goog=p_goog,
            strategy=strategy
        )

        # --manual：
        # Telegram only
        send_dual_notify(
            msg,
            send_line=False
        )

        chart_path = generate_chart(
            df_cfg,
            is_triggered=False,
            diff_pct=diff_pct
        )

        if chart_path:
            send_telegram_photo(chart_path)

        print()
        print(
            "🧪 已發送手動測試報告 "
            "(Telegram only，LINE 不發送)。"
        )

        return

    # ======================================
    # 情境 C
    # 每日 09:00 報告
    # ======================================

    if should_send_daily_report():

        msg = build_daily_report(
            curr_hold=curr_hold,
            current_shares=current_shares,
            base_qqq=base_qqq,
            base_goog=base_goog,
            p_qqq=p_qqq,
            p_goog=p_goog,
            strategy=strategy
        )

        # 正式每日報告：
        # Telegram + LINE
        send_dual_notify(
            msg,
            send_line=True
        )

        chart_path = generate_chart(
            df_cfg,
            is_triggered=False,
            diff_pct=diff_pct
        )

        if chart_path:
            send_telegram_photo(chart_path)

        now = get_taipei_now()

        mark_daily_report_sent(
            now.strftime("%Y-%m-%d")
        )

        print()
        print(
            "ℹ️ 已發送每日策略報告 "
            "(Telegram + LINE)。"
        )

        return

    # ======================================
    # 情境 D
    # 盤中未達門檻
    # ======================================

    remaining_pct = (
        THRESHOLD
        - strategy["strategy_diff"]
    ) * 100

    print()
    print(
        f"⏱️ 當前相對差距："
        f"{diff_pct:+.2f}%"
    )

    print(
        f"距離 7% 轉單門檻："
        f"{remaining_pct:.2f}%"
    )

    print(
        "🔕 未達轉單門檻，"
        "保持靜默。"
    )


# ==========================================
# 16. 主程式
# ==========================================

if __name__ == "__main__":

    # --------------------------------------
    # --manual
    #
    # 強制產生報告
    # 但只發 Telegram
    # 不發 LINE
    # --------------------------------------

    is_manual = (
        len(sys.argv) > 1
        and sys.argv[1] == "--manual"
    )

    try:

        run_monitor(
            force_report=is_manual
        )

    except Exception as e:

        print()
        print("=" * 60)
        print("❌ 程式發生未預期錯誤")
        print("=" * 60)
        print(e)

        traceback.print_exc()

        # 嘗試透過 Telegram 回報錯誤
        error_msg = (
            "❌ *【QQQM / GOOG Monitor 程式錯誤】*\n\n"
            f"`{str(e)[:3000]}`"
        )

        # 錯誤通知只發 Telegram
        send_telegram_msg(error_msg)
