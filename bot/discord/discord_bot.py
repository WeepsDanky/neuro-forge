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
        client.on_proactive_message = lambda text: self.handle_proactive_message(text)
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
        
        logger.info(f"Processing message from user {user_name} in channel {channel_id}")
        logger.info(f"Message content: '{message.content}'")
        logger.info(f"Number of attachments: {len(message.attachments)}")
        
        # Check if connected
        if channel_id not in self.channel_clients:
            logger.warning(f"Channel {channel_id} not connected to VTuber")
            embed = discord.Embed(
                title="❌ Not Connected",
                description=f"Not connected to {self.character_name}. Use `{self.command_prefix}connect` to connect first.",
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed)
            return
        
        try:
            logger.info("Starting message processing...")
            # Show typing indicator
            async with message.channel.typing():
                
                # Handle attachments (images/audio)
                images = []
                has_audio = False
                
                logger.info(f"Processing {len(message.attachments)} attachments...")
                for i, attachment in enumerate(message.attachments):
                    logger.info(f"Attachment {i+1}: filename='{attachment.filename}', content_type='{attachment.content_type}', size={attachment.size} bytes")
                    
                    if attachment.content_type:
                        if attachment.content_type.startswith('image/'):
                            logger.info(f"Processing image attachment: {attachment.filename}")
                            try:
                                # Download and convert image
                                async with aiohttp.ClientSession() as session:
                                    logger.info(f"Downloading image from: {attachment.url}")
                                    async with session.get(attachment.url) as response:
                                        if response.status == 200:
                                            image_bytes = await response.read()
                                            logger.info(f"Image downloaded successfully: {len(image_bytes)} bytes")
                                        else:
                                            logger.error(f"Failed to download image: HTTP {response.status}")
                                            continue
                                
                                logger.info("Converting image to base64...")
                                image_b64 = VTuberWebSocketClient.bytes_to_base64(
                                    image_bytes, attachment.content_type
                                )
                                images.append(image_b64)
                                logger.info(f"Image converted successfully, base64 length: {len(image_b64)}")
                                
                            except Exception as img_error:
                                logger.error(f"Error processing image {attachment.filename}: {img_error}", exc_info=True)
                                await message.channel.send(f"❌ Error processing image {attachment.filename}: {str(img_error)}")
                                continue
                            
                        elif attachment.content_type.startswith('audio/'):
                            logger.info(f"Processing audio attachment: {attachment.filename}")
                            # Download and convert audio
                            has_audio = True
                            
                            try:
                                with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{attachment.filename}") as tmp_file:
                                    logger.info(f"Downloading audio to temporary file: {tmp_file.name}")
                                    await attachment.save(tmp_file.name)
                                    
                                    # Check if file was downloaded successfully
                                    if os.path.exists(tmp_file.name):
                                        file_size = os.path.getsize(tmp_file.name)
                                        logger.info(f"Audio file downloaded successfully: {file_size} bytes")
                                    else:
                                        logger.error(f"Failed to download audio file to {tmp_file.name}")
                                        await message.channel.send("❌ Failed to download audio file.")
                                        return
                                    
                                    # Convert to required format
                                    logger.info("Starting audio conversion to VTuber format...")
                                    audio_data = self._convert_audio_to_vtuber_format(tmp_file.name)
                                
                                # Clean up temp file
                                try:
                                    os.unlink(tmp_file.name)
                                    logger.info("Temporary file cleaned up successfully")
                                except Exception as cleanup_error:
                                    logger.warning(f"Failed to cleanup temporary file: {cleanup_error}")
                                
                                if audio_data is not None:
                                    logger.info(f"Audio conversion successful. Array shape: {audio_data.shape}, dtype: {audio_data.dtype}")
                                    # Send audio to VTuber
                                    logger.info("Sending audio data to VTuber...")
                                    success = await self.channel_clients[channel_id].send_audio_input(
                                        audio_data
                                    )
                                    if success:
                                        logger.info("Audio sent to VTuber successfully")
                                    else:
                                        logger.error("Failed to send audio to VTuber")
                                        await message.channel.send("❌ Failed to send audio to VTuber.")
                                    return
                                else:
                                    logger.error("Audio conversion failed - audio_data is None")
                                    await message.channel.send("❌ Error processing audio file. Check logs for details.")
                                    return
                                    
                            except Exception as audio_error:
                                logger.error(f"Error processing audio {attachment.filename}: {audio_error}", exc_info=True)
                                await message.channel.send(f"❌ Error processing audio {attachment.filename}: {str(audio_error)}")
                                return
                        else:
                            logger.info(f"Skipping attachment with unsupported content type: {attachment.content_type}")
                    else:
                        logger.warning(f"Attachment {attachment.filename} has no content_type")
                
                # Handle text message (with optional images)
                if not has_audio:
                    logger.info("Processing text message...")
                    # Get message content, removing mentions
                    content = message.content
                    original_content = content
                    if self.user in message.mentions:
                        content = content.replace(f'<@{self.user.id}>', '').strip()
                        logger.info(f"Removed bot mention. Original: '{original_content}', Cleaned: '{content}'")
                    
                    if not content and not images:
                        content = "Hello!"  # Default message if only mention
                        logger.info("No content and no images, using default greeting")
                    
                    logger.info(f"Final content to send: '{content}', Images: {len(images)}")
                    
                    if content or images:
                        try:
                            # Send to VTuber
                            logger.info("Sending text/image input to VTuber...")
                            success = await self.channel_clients[channel_id].send_text_input(
                                content, images if images else None
                            )
                            if success:
                                logger.info("Text/image sent to VTuber successfully")
                            else:
                                logger.error("Failed to send text/image to VTuber")
                                await message.channel.send("❌ Failed to send message to VTuber.")
                        except Exception as send_error:
                            logger.error(f"Error sending text/image to VTuber: {send_error}", exc_info=True)
                            await message.channel.send(f"❌ Error sending message to VTuber: {str(send_error)}")
                    else:
                        logger.info("No content to send (empty message)")
                
        except Exception as e:
            logger.error(f"Error handling user message from {user_name}: {type(e).__name__}: {e}", exc_info=True)
            await message.channel.send(f"❌ Error processing your message: {str(e)}")
    
    def _convert_audio_to_vtuber_format(self, audio_path: str) -> Optional[np.ndarray]:
        """
        Convert audio file to VTuber required format (16kHz mono float32)
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            np.ndarray: Audio data or None if conversion failed
        """
        try:
            logger.info(f"Converting audio file: {audio_path}")
            
            # Check if file exists and has content
            if not os.path.exists(audio_path):
                logger.error(f"Audio file does not exist: {audio_path}")
                return None
            
            file_size = os.path.getsize(audio_path)
            if file_size == 0:
                logger.error(f"Audio file is empty: {audio_path} (0 bytes)")
                return None
            
            logger.info(f"Audio file size: {file_size} bytes")
            
            # Load audio with pydub
            logger.info("Loading audio with pydub...")
            audio = AudioSegment.from_file(audio_path)
            logger.info(f"Audio loaded successfully - Duration: {len(audio)}ms, Channels: {audio.channels}, Frame rate: {audio.frame_rate}Hz, Sample width: {audio.sample_width} bytes")
            
            # Convert to mono
            if audio.channels > 1:
                logger.info(f"Converting from {audio.channels} channels to mono")
                audio = audio.set_channels(1)
            
            # Convert to 16kHz
            if audio.frame_rate != 16000:
                logger.info(f"Resampling from {audio.frame_rate}Hz to 16000Hz")
                audio = audio.set_frame_rate(16000)
            
            # Convert to numpy array (float32, normalized)
            logger.info("Converting to numpy array...")
            audio_array = np.array(audio.get_array_of_samples(), dtype=np.float32)
            logger.info(f"Raw audio array shape: {audio_array.shape}, dtype: {audio_array.dtype}")
            
            # Normalize to [-1, 1] range
            if audio.sample_width == 1:  # 8-bit
                logger.info("Normalizing 8-bit audio")
                audio_array = audio_array / 128.0
            elif audio.sample_width == 2:  # 16-bit
                logger.info("Normalizing 16-bit audio")
                audio_array = audio_array / 32768.0
            elif audio.sample_width == 4:  # 32-bit
                logger.info("Normalizing 32-bit audio")
                audio_array = audio_array / 2147483648.0
            else:
                logger.warning(f"Unknown sample width: {audio.sample_width} bytes, using 16-bit normalization")
                audio_array = audio_array / 32768.0
            
            logger.info(f"Final audio array - Shape: {audio_array.shape}, dtype: {audio_array.dtype}, min: {audio_array.min():.3f}, max: {audio_array.max():.3f}")
            
            return audio_array
            
        except FileNotFoundError as e:
            logger.error(f"Audio file not found: {e}")
            return None
        except PermissionError as e:
            logger.error(f"Permission denied accessing audio file: {e}")
            return None
        except Exception as e:
            logger.error(f"Error converting audio: {type(e).__name__}: {e}", exc_info=True)
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
                    await channel.send(f"{display_text['text']}")
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
    
    async def handle_proactive_message(self, text: str):
        """Handle proactive messages from the VTuber and broadcast to all connected channels"""
        logger.info(f"Broadcasting proactive message to {len(self.channel_clients)} channels: {text}")
        
        # Send proactive message to all connected channels
        for channel_id in list(self.channel_clients.keys()):
            try:
                channel = self.get_channel(channel_id)
                if channel:
                    embed = discord.Embed(
                        title="🌟 Proactive Message",
                        description=text,
                        color=discord.Color.gold()
                    )
                    await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Failed to send proactive message to channel {channel_id}: {e}")
                # Remove invalid channel connections
                if channel_id in self.channel_clients:
                    try:
                        await self.channel_clients[channel_id].disconnect()
                    except:
                        pass
                    del self.channel_clients[channel_id]
    
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
