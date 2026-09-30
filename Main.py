```python
import sys
import os
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

# 績效圖
CHART_FILE = "live_chart.png"


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
            print("✅ Telegram 文字訊息發送成功")
            return True

        print(
            f"❌ Telegram 發送失敗："
            f"{response.status_code}"
        )
        print(response.text)

        return False

    except Exception as e:

        print(
            f"❌ Telegram 發送例外：{e}"
        )

        return False


# ==========================================
# 3. Telegram 圖片
# ==========================================

def send_telegram_photo(photo_path):
    """
    發送 Telegram 圖片
    "
```
