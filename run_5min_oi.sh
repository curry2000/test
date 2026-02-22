#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate

export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/1471211329862766614/lQDUbFc_YQnI7CRfZ8S5p3RlMx5sHC1PIcyusA2D7x4-YhlMhkIASF_seLEvnOMJub0J"
export DISCORD_5MIN_THREAD_ID="1475086012194754650"

python3 oi_5min_alert.py >> ~/Library/Logs/com.crypto.oi5min.log 2>&1
