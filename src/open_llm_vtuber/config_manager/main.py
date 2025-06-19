# config_manager/main.py
from pydantic import BaseModel, Field
from typing import Dict, ClassVar, Optional

from .system import SystemConfig
from .character import CharacterConfig
from .telegram_bot import TelegramBotConfig
from .discord_bot import DiscordBotConfig
from .i18n import I18nMixin, Description


class Config(I18nMixin, BaseModel):
    """
    Main configuration for the application.
    """
    
    system_config: SystemConfig = Field(default=None, alias="system_config")
    character_config: CharacterConfig = Field(..., alias="character_config")
    telegram_bot_config: Optional[TelegramBotConfig] = Field(
        default=None, alias="telegram_bot_config"
    )
    discord_bot_config: Optional[DiscordBotConfig] = Field(
        default=None, alias="discord_bot_config"
    )
    
    DESCRIPTIONS: ClassVar[Dict[str, Description]] = {
        "system_config": Description(
            en="System configuration settings", zh="系统配置设置"
        ),
        "character_config": Description(
            en="Character configuration settings", zh="角色配置设置"
        ),
        "telegram_bot_config": Description(
            en="Telegram bot configuration settings", zh="Telegram机器人配置设置"
        ),
        "discord_bot_config": Description(
            en="Discord bot configuration settings", zh="Discord机器人配置设置"
        ),
    }
