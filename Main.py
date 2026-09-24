# ==========================================
# 4. 核心檢測邏輯
# ==========================================
import os

def run_monitor(force_report=False):
    # 若為 GitHub 手動觸發 (workflow_dispatch)，則強制發送報告
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        force_report = True

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

    # 情境 B：未達門檻，但符合早上 09:00 定時報告或手動執行 (force_report)
    if is_morning_report_time or force_report:
        chart_path, ret_my, ret_qqq, ret_goog = generate_chart(df_cfg, is_triggered=False, diff_pct=diff_pct)
        
        diff_vs_qqq = ret_my - ret_qqq
        diff_vs_goog = ret_my - ret_goog

        report_title = "【每日策略狀態報告】" if is_morning_report_time else "【手動檢查狀態報告】"
        msg = f"ℹ️ *{report_title}*\n\n"
        msg += f"當前持股：`{curr_hold}` ({current_shares} 股)\n"
        msg += f"QQQM 現價：`${p_qqq:.2f}` (基準價 ${base_qqq:.2f})\n"
        msg += f"GOOG 現價：`${p_goog:.2f}` (基準價 ${base_goog:.2f})\n"
        msg += f"相對價差變動：`{diff_pct:.2f}%` (門檻 7%)\n\n"
        msg += f"📊 *【目前累積績效比較】*\n"
        msg += f"• 我的策略總報酬：`{ret_my:+.2f}%`\n"
        msg += f"• B&H QQQM 報酬：`{ret_qqq:+.2f}%` (落後 `{diff_vs_qqq:+.2f}%`)\n"
        msg += f"• B&H GOOG 報酬：`{ret_goog:+.2f}%` (落後 `{diff_vs_goog:+.2f}%`)\n\n"
        msg += f"📌 **結論：目前未達 7% 門檻，維持原持股即可。**"

        send_dual_notify(msg)
        send_telegram_photo(chart_path)
        print("ℹ️ 已發送狀態報告。")
        return

    # 情境 C：盤中自動排程監控且未達門檻 (靜默關閉，不打擾)
    print(f"⏱️ 當前價差變動 {diff_pct:.2f}%，未達 7% 門檻，保持靜默。")
