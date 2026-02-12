# Crypto Monitor 加密貨幣監控系統

自動監控 BTC/ETH 的價格、OI、訂單塊(Order Block)，並透過 Discord Webhook 發送通知。

## 功能

- 📊 **價格監控** - 關鍵支撐壓力位警報
- 📈 **OI 變動** - 未平倉合約異常變動通知
- 🎯 **Order Block** - 15m/30m 訂單塊識別與交易信號
- 💼 **倉位顧問** - 補倉條件評估

## 設定方式

1. Fork 這個 Repo
2. 到 Settings → Secrets and variables → Actions
3. 新增 Secret: `DISCORD_WEBHOOK_URL`
4. GitHub Actions 會自動每 15 分鐘執行監控

## 監控頻率

| 任務 | 頻率 |
|------|------|
| 價格/OI/OB | 每 15 分鐘 |
| 倉位顧問 | 每小時 |

## 免責聲明

本工具僅供參考，不構成投資建議。加密貨幣交易有高風險，請謹慎操作。
