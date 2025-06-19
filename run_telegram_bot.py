#!/usr/bin/env python3
"""
Telegram VTuber Bot Launcher
Run this script to start the Telegram bot
"""
import asyncio
import os
from bot.telegram.telegram_bot import TelegramVTuberBot
from src.open_llm_vtuber.config_manager import Config, read_yaml, validate_config


def main():
    # Load configuration from YAML file
    config: Config = validate_config(read_yaml("conf.yaml"))

    # Get configuration values from telegram_bot_config section
    telegram_config = config.telegram_bot_config
    telegram_token = telegram_config.telegram_bot_token
    vtuber_ws_url = telegram_config.vtuber_ws_url
    character_name = telegram_config.character_name
    
    if not telegram_token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in configuration")
        print("Please check your conf.yaml file and ensure telegram_bot_config.telegram_bot_token is set")
        return
    
    print(f"🚀 Starting Telegram VTuber Bot...")
    print(f"Character: {character_name}")
    print(f"VTuber Server: {vtuber_ws_url}")
    
    # Create and run bot
    bot = TelegramVTuberBot(
        telegram_token=telegram_token,
        vtuber_ws_url=vtuber_ws_url,
        character_name=character_name
    )
    
    async def run_bot():
        try:
            await bot.run()
            # Keep running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Received interrupt signal, shutting down...")
        finally:
            await bot.stop()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
