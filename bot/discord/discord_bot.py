"""
Discord bot for Open-LLM-VTuber
Connects to the VTuber WebSocket and handles Discord messages
"""
import asyncio
import os
import tempfile
import aiohttp
from typing import Optional
import discord
from discord.ext import commands
from loguru import logger
import numpy as np
from pydub import AudioSegment


import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from base_client import VTuberWebSocketClient

class DiscordVTuberBot(commands.Bot):
    """Discord bot that interfaces with Open-LLM-VTuber"""
    
    def __init__(self, 
                 discord_token: str,
                 vtuber_ws_url: str = "ws://localhost:12393/client-ws",
                 character_name: str = "VTuber",
                 command_prefix: str = "!"):
        """
        Initialize Discord bot
        
        Args:
            discord_token: Discord bot token
            vtuber_ws_url: WebSocket URL for VTuber server
            character_name: Name of the VTuber character
            command_prefix: Command prefix for bot commands
        """
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(command_prefix=command_prefix, intents=intents)
        
        self.discord_token = discord_token
        self.vtuber_ws_url = vtuber_ws_url
        self.character_name = character_name
        
        # WebSocket client per channel (to handle multiple conversations)
        self.channel_clients: dict[int, VTuberWebSocketClient] = {}
        
        # Setup event handlers
        self._setup_events()
        self._setup_commands()
    
    def _setup_events(self):
        """Setup Discord event handlers"""
        
        @self.event
        async def on_ready():
            logger.info(f'{self.user} has connected to Discord!')
            await self.change_presence(
                activity=discord.Game(name=f"🎭 {self.character_name}")
            )
        
        @self.event
        async def on_message(message):
            # Ignore bot messages
            if message.author == self.user:
                return
            
            # Handle DMs or mentions
            if isinstance(message.channel, discord.DMChannel) or self.user in message.mentions:
                await self.handle_user_message(message)
            
            # Process commands
            await self.process_commands(message)
    
    def _setup_commands(self):
        """Setup Discord commands"""
        
        @self.command(name='connect', help=f'Connect to {self.character_name}')
        async def connect_command(ctx):
            await self.connect_to_vtuber(ctx)
        
        @self.command(name='disconnect', help=f'Disconnect from {self.character_name}')
        async def disconnect_command(ctx):
            await self.disconnect_from_vtuber(ctx)
        
        @self.command(name='interrupt', help='Interrupt current conversation')
        async def interrupt_command(ctx):
            await self.interrupt_conversation(ctx)
        
        @self.command(name='help_vtuber', help='Show VTuber bot help')
        async def help_vtuber_command(ctx):
            await self.show_help(ctx)
    
    async def connect_to_vtuber(self, ctx):
        """Connect to VTuber WebSocket"""
        channel_id = ctx.channel.id
        
        if channel_id in self.channel_clients:
            await ctx.send(f"✅ Already connected to {self.character_name}!")
            return
        
        # Create WebSocket client for this channel
        client = VTuberWebSocketClient(self.vtuber_ws_url)
        
        # Setup event handlers
        client.on_text_response = lambda text: self.send_text_response(channel_id, text)
        client.on_audio_response = lambda audio, data: self.send_audio_response(channel_id, audio, data)
        client.on_error = lambda error: self.send_error_message(channel_id, error)
        client.on_connection_established = lambda uid: self.send_connection_message(channel_id, uid)
        
        # Show connecting message
        embed = discord.Embed(
            title="🎭 Connecting to VTuber",
            description=f"Connecting to {self.character_name}...",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
        
        # Connect to VTuber server
        if await client.connect():
            self.channel_clients[channel_id] = client
        else:
            embed = discord.Embed(
                title="❌ Connection Failed",
                description="Failed to connect to VTuber server. Please try again later.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
    
    async def disconnect_from_vtuber(self, ctx):
        """Disconnect from VTuber WebSocket"""
        channel_id = ctx.channel.id
        
        if channel_id in self.channel_clients:
            await self.channel_clients[channel_id].disconnect()
            del self.channel_clients[channel_id]
            
            embed = discord.Embed(
                title="👋 Disconnected",
                description=f"Disconnected from {self.character_name}. Use `{self.command_prefix}connect` to reconnect.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Not connected to any VTuber session.")
    
    async def interrupt_conversation(self, ctx):
        """Interrupt current conversation"""
        channel_id = ctx.channel.id
        
        if channel_id in self.channel_clients:
            await self.channel_clients[channel_id].send_interrupt()
            await ctx.send("⏹️ Sent interrupt signal to VTuber.")
        else:
            await ctx.send(f"❌ Not connected to any VTuber session. Use `{self.command_prefix}connect` first.")
    
    async def show_help(self, ctx):
        """Show help information"""
        embed = discord.Embed(
            title=f"🎭 {self.character_name} Discord Bot",
            description="A VTuber bot that supports text, image, and audio interactions",
            color=discord.Color.purple()
        )
        
        embed.add_field(
            name="Commands",
            value=f"""
            `{self.command_prefix}connect` - Connect to the VTuber
            `{self.command_prefix}disconnect` - Disconnect from VTuber
            `{self.command_prefix}interrupt` - Interrupt current conversation
            `{self.command_prefix}help_vtuber` - Show this help message
            """,
            inline=False
        )
        
        embed.add_field(
            name="Features",
            value="""
            • **Text Chat** - Send messages or mention the bot
            • **Image Chat** - Send images with optional messages
            • **Audio Chat** - Send audio files (will be transcribed)
            • **DM Support** - Works in DMs and server channels
            """,
            inline=False
        )
        
        embed.add_field(
            name="Supported Audio Formats",
            value="MP3, WAV, OGG, M4A, AAC, FLAC",
            inline=False
        )
        
        embed.set_footer(text="The VTuber will respond with text and may include audio responses.")
        
        await ctx.send(embed=embed)
    
    async def handle_user_message(self, message):
        """Handle user messages (text, images, audio)"""
        channel_id = message.channel.id
        user_name = message.author.display_name or message.author.name
        
        # Check if connected
        if channel_id not in self.channel_clients:
            embed = discord.Embed(
                title="❌ Not Connected",
                description=f"Not connected to {self.character_name}. Use `{self.command_prefix}connect` to connect first.",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
            return
        
        try:
            # Show typing indicator
            async with message.channel.typing():
                
                # Handle attachments (images/audio)
                images = []
                has_audio = False
                
                for attachment in message.attachments:
                    if attachment.content_type:
                        if attachment.content_type.startswith('image/'):
                            # Download and convert image
                            async with aiohttp.ClientSession() as session:
                                async with session.get(attachment.url) as response:                                    image_bytes = await response.read()
                            
                            image_b64 = VTuberWebSocketClient.bytes_to_base64(
                                image_bytes, attachment.content_type
                            )
                            images.append(image_b64)
                            
                        elif attachment.content_type.startswith('audio/'):
                            # Download and convert audio
                            has_audio = True
                            
                            with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                                await attachment.save(tmp_file.name)
                                
                                # Convert to required format
                                audio_data = self._convert_audio_to_vtuber_format(tmp_file.name)
                                
                                # Clean up temp file
                                os.unlink(tmp_file.name)
                            
                            if audio_data is not None:
                                # Send audio to VTuber
                                success = await self.channel_clients[channel_id].send_audio_input(
                                    audio_data
                                )
                                if not success:
                                    await message.channel.send("❌ Failed to send audio to VTuber.")
                                return
                            else:
                                await message.channel.send("❌ Error processing audio file.")
                                return
                  # Handle text message (with optional images)
                if not has_audio:
                    # Get message content, removing mentions
                    content = message.content
                    if self.user in message.mentions:
                        content = content.replace(f'<@{self.user.id}>', '').strip()
                    
                    if not content and not images:
                        content = "Hello!"  # Default message if only mention
                    
                    if content or images:
                        # Send to VTuber
                        success = await self.channel_clients[channel_id].send_text_input(
                            content, images if images else None
                        )
                        if not success:
                            await message.channel.send("❌ Failed to send message to VTuber.")
                
        except Exception as e:
            logger.error(f"Error handling user message: {e}")
            await message.channel.send("❌ Error processing your message.")
    
    def _convert_audio_to_vtuber_format(self, audio_path: str) -> Optional[np.ndarray]:
        """
        Convert audio file to VTuber required format (16kHz mono float32)
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            np.ndarray: Audio data or None if conversion failed
        """
        try:
            # Load audio with pydub
            audio = AudioSegment.from_file(audio_path)
            
            # Convert to mono
            if audio.channels > 1:
                audio = audio.set_channels(1)
            
            # Convert to 16kHz
            if audio.frame_rate != 16000:
                audio = audio.set_frame_rate(16000)
            
            # Convert to numpy array (float32, normalized)
            audio_array = np.array(audio.get_array_of_samples(), dtype=np.float32)
            
            # Normalize to [-1, 1] range
            if audio.sample_width == 1:  # 8-bit
                audio_array = audio_array / 128.0
            elif audio.sample_width == 2:  # 16-bit
                audio_array = audio_array / 32768.0
            elif audio.sample_width == 4:  # 32-bit
                audio_array = audio_array / 2147483648.0
            
            return audio_array
            
        except Exception as e:
            logger.error(f"Error converting audio: {e}")
            return None
    
    async def send_text_response(self, channel_id: int, text: str):
        """Send text response to Discord channel"""
        try:
            channel = self.get_channel(channel_id)
            if channel:
                # Split long messages
                if len(text) > 2000:
                    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
                    for chunk in chunks:
                        await channel.send(chunk)
                else:
                    await channel.send(text)
        except Exception as e:
            logger.error(f"Error sending text response: {e}")
    
    async def send_audio_response(self, channel_id: int, audio_data: str, data: dict):
        """Send audio response to Discord channel"""
        try:
            channel = self.get_channel(channel_id)
            if channel:
                # For now, just send the text content with audio indicator
                # TODO: Implement audio playback if needed
                display_text = data.get("display_text", {})
                if display_text and display_text.get("text"):
                    await channel.send(f"🔊 {display_text['text']}")
        except Exception as e:
            logger.error(f"Error sending audio response: {e}")
    
    async def send_error_message(self, channel_id: int, error: str):
        """Send error message to Discord channel"""
        try:
            channel = self.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    title="❌ Error",
                    description=error,
                    color=discord.Color.red()
                )
                await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error sending error message: {e}")
    
    async def send_connection_message(self, channel_id: int, client_uid: str):
        """Send connection established message"""
        try:
            channel = self.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    title="✅ Connected",
                    description=f"Connected to {self.character_name}!\nSession: {client_uid[:8]}\n\nYou can now start chatting!",
                    color=discord.Color.green()
                )
                await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error sending connection message: {e}")
    
    async def start_bot(self):
        """Start the Discord bot"""
        logger.info("Starting Discord VTuber bot...")
        await self.start(self.discord_token)
    
    async def stop_bot(self):
        """Stop the Discord bot"""
        logger.info("Stopping Discord VTuber bot...")
        
        # Disconnect all WebSocket clients
        for client in self.channel_clients.values():
            await client.disconnect()
        self.channel_clients.clear()
        
        # Close Discord connection
        await self.close()


async def main():
    """Main function to run the Discord bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Discord VTuber Bot")
    parser.add_argument("--token", required=True, help="Discord bot token")
    parser.add_argument("--ws-url", default="ws://localhost:12393/client-ws", 
                       help="VTuber WebSocket URL")
    parser.add_argument("--character-name", default="VTuber", 
                       help="Character name")
    parser.add_argument("--prefix", default="!", 
                       help="Command prefix")
    
    args = parser.parse_args()
    
    bot = DiscordVTuberBot(
        discord_token=args.token,
        vtuber_ws_url=args.ws_url,
        character_name=args.character_name,
        command_prefix=args.prefix
    )
    
    try:
        await bot.start_bot()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    finally:
        await bot.stop_bot()


if __name__ == "__main__":
    asyncio.run(main())
