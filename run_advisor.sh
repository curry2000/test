#!/bin/bash
cd /Users/xuan/.openclaw/workspace/crypto-monitor-deploy
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/1471211329862766614/lQDUbFc_YQnI7CRfZ8S5p3RlMx5sHC1PIcyusA2D7x4-YhlMhkIASF_seLEvnOMJub0J"
./venv/bin/python position_advisor.py
