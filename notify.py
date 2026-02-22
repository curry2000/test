"""
Discord 通知模組
統一處理 webhook 發送，支援 thread、錯誤處理、重試
"""
import requests
import time
from typing import Optional
from config import DISCORD_WEBHOOK_URL, API_RETRY_MAX, API_RETRY_DELAY


def send_discord_message(
    message: str,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None,
    max_retries: int = API_RETRY_MAX
) -> bool:
    """
    發送 Discord 訊息
    
    Args:
        message: 訊息內容
        webhook_url: Webhook URL（可選，預設使用 config 中的）
        thread_id: Thread ID（可選）
        max_retries: 最大重試次數
    
    Returns:
        bool: 是否發送成功
    """
    if not webhook_url:
        webhook_url = DISCORD_WEBHOOK_URL
    
    if not webhook_url:
        print("[WARNING] Discord webhook URL 未設定")
        return False
    
    payload = {"content": message}
    
    # 如果指定了 thread_id，加入參數
    params = {}
    if thread_id:
        params["thread_id"] = thread_id
    
    # 重試邏輯
    for attempt in range(max_retries):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                params=params,
                timeout=10
            )
            
            if response.status_code in [200, 204]:
                return True
            
            # Rate limit (429)
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 1)
                print(f"[Discord] Rate limited, retry after {retry_after}s")
                time.sleep(retry_after)
                continue
            
            # 其他錯誤
            print(f"[Discord] Send failed: {response.status_code} - {response.text}")
            
        except requests.exceptions.Timeout:
            print(f"[Discord] Timeout (attempt {attempt + 1}/{max_retries})")
        except Exception as e:
            print(f"[Discord] Error: {e}")
        
        # 重試延遲
        if attempt < max_retries - 1:
            time.sleep(API_RETRY_DELAY * (attempt + 1))
    
    print(f"[Discord] Failed to send after {max_retries} attempts")
    return False


def send_alert(
    title: str,
    message: str,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None,
    emoji: str = "🚨"
) -> bool:
    """
    發送警報訊息（帶格式）
    
    Args:
        title: 標題
        message: 內容
        webhook_url: Webhook URL
        thread_id: Thread ID
        emoji: 表情符號
    
    Returns:
        bool: 是否發送成功
    """
    formatted_message = f"{emoji} **{title}**\n{message}"
    return send_discord_message(formatted_message, webhook_url, thread_id)


def send_signal(
    symbol: str,
    direction: str,
    strength: str,
    details: dict,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None
) -> bool:
    """
    發送交易信號
    
    Args:
        symbol: 交易對
        direction: 方向（LONG/SHORT）
        strength: 強度（S/A/B/C）
        details: 詳細資訊（字典）
        webhook_url: Webhook URL
        thread_id: Thread ID
    
    Returns:
        bool: 是否發送成功
    """
    emoji = "🔥" if strength == "S" else "⚡" if strength == "A" else "💡" if strength == "B" else "📊"
    direction_emoji = "📈" if direction == "LONG" else "📉"
    
    message_lines = [
        f"{emoji} **{strength} 級信號** {direction_emoji} **{direction}** `{symbol}`",
        ""
    ]
    
    # 加入詳細資訊
    for key, value in details.items():
        if value is not None:
            message_lines.append(f"• {key}: {value}")
    
    formatted_message = "\n".join(message_lines)
    return send_discord_message(formatted_message, webhook_url, thread_id)


def send_position_alert(
    position_name: str,
    alert_level: str,
    details: dict,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None
) -> bool:
    """
    發送倉位警報
    
    Args:
        position_name: 倉位名稱
        alert_level: 警報等級（danger/warning/caution）
        details: 詳細資訊
        webhook_url: Webhook URL
        thread_id: Thread ID
    
    Returns:
        bool: 是否發送成功
    """
    emoji_map = {
        "danger": "🚨",
        "warning": "⚠️",
        "caution": "⚡"
    }
    
    emoji = emoji_map.get(alert_level, "📊")
    
    message_lines = [
        f"{emoji} **倉位警報** - {position_name}",
        ""
    ]
    
    for key, value in details.items():
        if value is not None:
            message_lines.append(f"• {key}: {value}")
    
    formatted_message = "\n".join(message_lines)
    return send_discord_message(formatted_message, webhook_url, thread_id)


def send_trade_update(
    action: str,
    symbol: str,
    details: dict,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None
) -> bool:
    """
    發送交易更新（開倉、平倉、止損等）
    
    Args:
        action: 動作（OPEN/CLOSE/SL/TP）
        symbol: 交易對
        details: 詳細資訊
        webhook_url: Webhook URL
        thread_id: Thread ID
    
    Returns:
        bool: 是否發送成功
    """
    action_map = {
        "OPEN": ("📍", "開倉"),
        "CLOSE": ("✅", "平倉"),
        "SL": ("🛑", "止損"),
        "TP": ("🎯", "止盈"),
        "PARTIAL": ("📊", "部分平倉")
    }
    
    emoji, action_text = action_map.get(action, ("📊", action))
    
    message_lines = [
        f"{emoji} **{action_text}** `{symbol}`",
        ""
    ]
    
    for key, value in details.items():
        if value is not None:
            message_lines.append(f"• {key}: {value}")
    
    formatted_message = "\n".join(message_lines)
    return send_discord_message(formatted_message, webhook_url, thread_id)


def send_report(
    title: str,
    report_lines: list,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None,
    emoji: str = "📊"
) -> bool:
    """
    發送報表
    
    Args:
        title: 報表標題
        report_lines: 報表內容（行列表）
        webhook_url: Webhook URL
        thread_id: Thread ID
        emoji: 表情符號
    
    Returns:
        bool: 是否發送成功
    """
    message_lines = [f"{emoji} **{title}**", ""]
    message_lines.extend(report_lines)
    
    formatted_message = "\n".join(message_lines)
    
    # Discord 訊息長度限制
    if len(formatted_message) > 2000:
        # 分割成多條訊息
        chunks = []
        current_chunk = f"{emoji} **{title}**\n"
        
        for line in report_lines:
            if len(current_chunk) + len(line) + 1 > 1900:
                chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # 發送每個分塊
        success = True
        for chunk in chunks:
            if not send_discord_message(chunk, webhook_url, thread_id):
                success = False
        return success
    
    return send_discord_message(formatted_message, webhook_url, thread_id)


def send_error(
    error_message: str,
    context: Optional[str] = None,
    webhook_url: Optional[str] = None,
    thread_id: Optional[str] = None
) -> bool:
    """
    發送錯誤訊息
    
    Args:
        error_message: 錯誤訊息
        context: 上下文資訊
        webhook_url: Webhook URL
        thread_id: Thread ID
    
    Returns:
        bool: 是否發送成功
    """
    message = f"❌ **錯誤**\n{error_message}"
    if context:
        message += f"\n\n**Context:** {context}"
    
    return send_discord_message(message, webhook_url, thread_id)


# 向後兼容的簡化函數
def notify(message: str, thread_id: Optional[str] = None) -> bool:
    """簡化的通知函數（向後兼容）"""
    return send_discord_message(message, thread_id=thread_id)
