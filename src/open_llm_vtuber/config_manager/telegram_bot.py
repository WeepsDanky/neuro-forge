# config_manager/telegram_bot.py
from pydantic import BaseModel, Field
from typing import Dict, ClassVar
from .i18n import I18nMixin, Description


class TelegramBotConfig(I18nMixin, BaseModel):
    """Configuration for Telegram bot settings."""

    telegram_bot_token: str = Field(..., alias="telegram_bot_token")
    vtuber_ws_url: str = Field(..., alias="vtuber_ws_url")
    character_name: str = Field(..., alias="character_name")
    log_level: str = Field(default="INFO", alias="log_level")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "telegram_bot_token": Description(
            en="Telegram bot token from BotFather", zh="从BotFather获取的Telegram机器人令牌"
        ),
        "vtuber_ws_url": Description(
            en="WebSocket URL for VTuber connection", zh="VTuber连接的WebSocket URL"
        ),
        "character_name": Description(
            en="Name of the character for the bot", zh="机器人的角色名称"
        ),
        "log_level": Description(
            en="Log level for Telegram bot (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
            zh="Telegram机器人的日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
        ),
    }
