#!/usr/bin/env python3
"""
Discord VTuber Bot Launcher
Run this script to start the Discord bot
"""
import asyncio
import os
from bot.discord.discord_bot import DiscordVTuberBot
from src.open_llm_vtuber.config_manager import Config, read_yaml, validate_config

def main():
    # Load configurations from yaml file
    config: Config = validate_config(read_yaml("conf.yaml"))
    
    # Get configuration values from discord_bot_config section
    discord_config = config.discord_bot_config
    discord_token = discord_config.discord_bot_token
    vtuber_ws_url = discord_config.vtuber_ws_url
    character_name = discord_config.character_name
    command_prefix = discord_config.command_prefix
    
    if not discord_token:
        print("❌ Error: DISCORD_BOT_TOKEN not found in configuration")
        print("Please check your conf.yaml file and ensure discord_bot_config.discord_bot_token is set")
        return
    
    print(f"🚀 Starting Discord VTuber Bot...")
    print(f"Character: {character_name}")
    print(f"Command Prefix: {command_prefix}")
    print(f"VTuber Server: {vtuber_ws_url}")
    
    # Create and run bot
    bot = DiscordVTuberBot(
        discord_token=discord_token,
        vtuber_ws_url=vtuber_ws_url,
        character_name=character_name,
        command_prefix=command_prefix
    )
    
    async def run_bot():
        try:
            await bot.start_bot()
        except KeyboardInterrupt:
            print("\n🛑 Received interrupt signal, shutting down...")
        finally:
            await bot.stop_bot()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
