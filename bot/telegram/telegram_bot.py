"""
Telegram bot for Open-LLM-VTuber
Connects to the VTuber WebSocket and handles Telegram messages
"""
import asyncio
import os
import tempfile
import aiohttp
from typing import Optional
from telegram import Update, Message
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from loguru import logger
import numpy as np
from pydub import AudioSegment

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from base_client import VTuberWebSocketClient

class TelegramVTuberBot:
    """Telegram bot that interfaces with Open-LLM-VTuber"""
    
    def __init__(self, 
                 telegram_token: str,
                 vtuber_ws_url: str = "ws://localhost:12393/client-ws",
                 character_name: str = "VTuber"):
        """
        Initialize Telegram bot
        
        Args:
            telegram_token: Telegram bot token from BotFather
            vtuber_ws_url: WebSocket URL for VTuber server
            character_name: Name of the VTuber character
        """
        self.telegram_token = telegram_token
        self.vtuber_ws_url = vtuber_ws_url
        self.character_name = character_name
        
        # Initialize Telegram application
        self.application = Application.builder().token(telegram_token).build()
        
        # WebSocket client per chat (to handle multiple conversations)
        self.chat_clients: dict[int, VTuberWebSocketClient] = {}
        
        # Setup handlers
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup Telegram message handlers"""
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stop", self.stop_command))
        self.application.add_handler(CommandHandler("interrupt", self.interrupt_command))
        
        # Message handlers
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo_message))
        self.application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.handle_audio_message))
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        chat_id = update.effective_chat.id
        
        # Create WebSocket client for this chat
        if chat_id not in self.chat_clients:
            client = VTuberWebSocketClient(self.vtuber_ws_url)
            
            # Setup event handlers
            client.on_text_response = lambda text: self.send_text_response(chat_id, text)
            client.on_audio_response = lambda audio, data: self.send_audio_response(chat_id, audio, data)
            client.on_error = lambda error: self.send_error_message(chat_id, error)
            client.on_connection_established = lambda uid: self.send_connection_message(chat_id, uid)
            
            # Connect to VTuber server
            if await client.connect():
                self.chat_clients[chat_id] = client
                await update.message.reply_text(
                    f"🎭 Hello! I'm {self.character_name}. I'm connecting to the VTuber server...\n\n"
                    "You can:\n"
                    "• Send me text messages\n"
                    "• Send photos with captions\n"
                    "• Send voice messages\n"
                    "• Use /interrupt to stop me mid-conversation\n"
                    "• Use /stop to disconnect"
                )
            else:
                await update.message.reply_text(
                    "❌ Failed to connect to VTuber server. Please try again later."
                )
        else:
            await update.message.reply_text(
                f"✅ Already connected to {self.character_name}!"
            )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = f"""
🎭 **{self.character_name} Telegram Bot**

**Commands:**
/start - Connect to the VTuber
/help - Show this help message
/interrupt - Interrupt current conversation
/stop - Disconnect from VTuber

**Features:**
• **Text Chat** - Send any text message
• **Photo Chat** - Send photos with optional captions
• **Voice Chat** - Send voice messages (will be transcribed)
• **Audio Chat** - Send audio files (will be transcribed)

**Supported Audio Formats:**
OGG, MP3, WAV, M4A, AAC

The VTuber will respond with text and may include audio responses depending on the server configuration.
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command"""
        chat_id = update.effective_chat.id
        
        if chat_id in self.chat_clients:
            await self.chat_clients[chat_id].disconnect()
            del self.chat_clients[chat_id]
            await update.message.reply_text(f"👋 Disconnected from {self.character_name}. Use /start to reconnect.")
        else:
            await update.message.reply_text("❌ Not connected to any VTuber session.")
    
    async def interrupt_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /interrupt command"""
        chat_id = update.effective_chat.id
        
        if chat_id in self.chat_clients:
            await self.chat_clients[chat_id].send_interrupt()
            await update.message.reply_text("⏹️ Sent interrupt signal to VTuber.")
        else:
            await update.message.reply_text("❌ Not connected to any VTuber session. Use /start first.")
    
    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages"""
        chat_id = update.effective_chat.id
        text = update.message.text
        user_name = update.effective_user.first_name or "User"
        
        if chat_id not in self.chat_clients:
            await update.message.reply_text("❌ Not connected. Use /start to connect first.")
            return
          # Send typing indicator
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        # Send to VTuber
        success = await self.chat_clients[chat_id].send_text_input(text)
        if not success:
            await update.message.reply_text("❌ Failed to send message to VTuber.")
    
    async def handle_photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages"""
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name or "User"
        
        if chat_id not in self.chat_clients:
            await update.message.reply_text("❌ Not connected. Use /start to connect first.")
            return
        
        try:
            # Send typing indicator
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            
            # Get the largest photo
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            # Download photo
            async with aiohttp.ClientSession() as session:
                async with session.get(file.file_path) as response:
                    image_bytes = await response.read()
            
            # Convert to base64
            image_b64 = VTuberWebSocketClient.bytes_to_base64(image_bytes, "image/jpeg")
            
            # Get caption or default text
            caption = update.message.caption or "Here's an image for you to see."
              # Send to VTuber
            success = await self.chat_clients[chat_id].send_text_input(
                caption, [image_b64]
            )
            if not success:
                await update.message.reply_text("❌ Failed to send image to VTuber.")
                
        except Exception as e:
            logger.error(f"Error handling photo: {e}")
            await update.message.reply_text("❌ Error processing image.")
    
    async def handle_audio_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice and audio messages"""
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name or "User"
        
        if chat_id not in self.chat_clients:
            await update.message.reply_text("❌ Not connected. Use /start to connect first.")
            return
        
        try:
            # Send typing indicator
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            
            # Get audio file
            if update.message.voice:
                file = await context.bot.get_file(update.message.voice.file_id)
            else:
                file = await context.bot.get_file(update.message.audio.file_id)
            
            # Download audio
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
                await file.download_to_drive(tmp_file.name)
                
                # Convert to required format (16kHz mono float32)
                audio_data = self._convert_audio_to_vtuber_format(tmp_file.name)
                  # Clean up temp file
                os.unlink(tmp_file.name)
            
            if audio_data is not None:
                # Send to VTuber
                success = await self.chat_clients[chat_id].send_audio_input(audio_data)
                if not success:
                    await update.message.reply_text("❌ Failed to send audio to VTuber.")
            else:
                await update.message.reply_text("❌ Error processing audio file.")
                
        except Exception as e:
            logger.error(f"Error handling audio: {e}")
            await update.message.reply_text("❌ Error processing audio.")
    
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
    
    async def send_text_response(self, chat_id: int, text: str):
        """Send text response to Telegram chat"""
        try:
            await self.application.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Error sending text response: {e}")
    
    async def send_audio_response(self, chat_id: int, audio_data: str, data: dict):
        """Send audio response to Telegram chat"""
        try:
            # For now, just send the text content
            # TODO: Implement audio playback if needed
            display_text = data.get("display_text", {})
            if display_text and display_text.get("text"):
                await self.application.bot.send_message(
                    chat_id=chat_id, 
                    text=f"🔊 {display_text['text']}"
                )
        except Exception as e:
            logger.error(f"Error sending audio response: {e}")
    
    async def send_error_message(self, chat_id: int, error: str):
        """Send error message to Telegram chat"""
        try:
            await self.application.bot.send_message(
                chat_id=chat_id, 
                text=f"❌ Error: {error}"
            )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")
    
    async def send_connection_message(self, chat_id: int, client_uid: str):
        """Send connection established message"""
        try:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Connected to {self.character_name}! (Session: {client_uid[:8]})\n"
                      "You can now start chatting!"
            )
        except Exception as e:
            logger.error(f"Error sending connection message: {e}")
    
    async def run(self):
        """Start the Telegram bot"""
        logger.info("Starting Telegram VTuber bot...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
    
    async def stop(self):
        """Stop the Telegram bot"""
        logger.info("Stopping Telegram VTuber bot...")
        
        # Disconnect all WebSocket clients
        for client in self.chat_clients.values():
            await client.disconnect()
        self.chat_clients.clear()
        
        # Stop Telegram bot
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()


async def main():
    """Main function to run the Telegram bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Telegram VTuber Bot")
    parser.add_argument("--token", required=True, help="Telegram bot token")
    parser.add_argument("--ws-url", default="ws://localhost:12393/client-ws", 
                       help="VTuber WebSocket URL")
    parser.add_argument("--character-name", default="VTuber", 
                       help="Character name")
    
    args = parser.parse_args()
    
    bot = TelegramVTuberBot(
        telegram_token=args.token,
        vtuber_ws_url=args.ws_url,
        character_name=args.character_name
    )
    
    try:
        await bot.run()
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
