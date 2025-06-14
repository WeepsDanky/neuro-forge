# config_manager/discord_bot.py
from pydantic import BaseModel, Field
from typing import Dict, ClassVar
from .i18n import I18nMixin, Description


class DiscordBotConfig(I18nMixin, BaseModel):
    """Configuration for Discord bot settings."""

    discord_bot_token: str = Field(..., alias="discord_bot_token")
    vtuber_ws_url: str = Field(..., alias="vtuber_ws_url")
    character_name: str = Field(..., alias="character_name")
    command_prefix: str = Field(default="!", alias="command_prefix")
    log_level: str = Field(default="INFO", alias="log_level")

    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "discord_bot_token": Description(
            en="Discord bot token from Discord Developer Portal",
            zh="从Discord开发者门户获取的Discord机器人令牌"
        ),
        "vtuber_ws_url": Description(
            en="WebSocket URL for VTuber connection", zh="VTuber连接的WebSocket URL"
        ),
        "character_name": Description(
            en="Name of the character for the bot", zh="机器人的角色名称"
        ),
        "command_prefix": Description(
            en="The prefix for commands in Discord", zh="Discord中命令的前缀"
        ),
        "log_level": Description(
            en="Log level for Discord bot (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
            zh="Discord机器人的日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
        ),
    }
