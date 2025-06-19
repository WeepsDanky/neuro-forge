# Open-LLM-VTuber Bot Integration

This directory contains Telegram and Discord bot implementations that interface with the Open-LLM-VTuber WebSocket server.

## Features

Both bots support:
- **Text messaging** - Send text to the VTuber and receive responses
- **Image sharing** - Send images with optional captions for visual interaction
- **Audio messages** - Send voice/audio files that get transcribed and processed
- **Multiple conversations** - Each chat/channel has its own VTuber session
- **Interruption support** - Stop the VTuber mid-conversation
- **Connection management** - Connect/disconnect from VTuber sessions

## Directory Structure

```
bot/
├── __init__.py                 # Package initialization
├── base_client.py             # Base WebSocket client for VTuber communication
├── requirements.txt           # Python dependencies
├── telegram/                  # Telegram bot implementation
│   ├── __init__.py
│   ├── telegram_bot.py        # Main Telegram bot class
│   ├── run_telegram_bot.py    # Telegram bot launcher
│   └── .env.example          # Environment configuration template
└── discord/                   # Discord bot implementation
    ├── __init__.py
    ├── discord_bot.py         # Main Discord bot class
    ├── run_discord_bot.py     # Discord bot launcher
    └── .env.example          # Environment configuration template
```

## Installation

1. **Install dependencies:**
   ```bash
   cd bot
   pip install -r requirements.txt
   ```

2. **Additional requirements:**
   - FFmpeg (for audio processing)
   - Open-LLM-VTuber server running on `localhost:12393`

## Configuration

### Telegram Bot Setup

1. **Create a Telegram bot:**
   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Use `/newbot` command to create a new bot
   - Get your bot token

2. **Configure the bot:**
   ```bash
   cd telegram
   cp .env.example .env
   # Edit .env and add your TELEGRAM_BOT_TOKEN
   ```

3. **Run the bot:**
   ```bash
   python run_telegram_bot.py
   ```

### Discord Bot Setup

1. **Create a Discord application:**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a new application
   - Go to "Bot" section and create a bot
   - Copy the bot token
   - Enable "Message Content Intent" in Bot settings

2. **Invite bot to server:**
   - Go to "OAuth2" > "URL Generator"
   - Select "bot" scope
   - Select required permissions: "Send Messages", "Read Messages", "Use Slash Commands"
   - Use the generated URL to invite the bot

3. **Configure the bot:**
   ```bash
   cd discord
   cp .env.example .env
   # Edit .env and add your DISCORD_BOT_TOKEN
   ```

4. **Run the bot:**
   ```bash
   python run_discord_bot.py
   ```

## Usage

### Telegram Bot

1. **Start a conversation:**
   - Send `/start` to connect to the VTuber
   - Send any text message to chat
   - Send photos with captions
   - Send voice messages

2. **Commands:**
   - `/start` - Connect to VTuber
   - `/stop` - Disconnect from VTuber
   - `/interrupt` - Stop current VTuber response
   - `/help` - Show help information

### Discord Bot

1. **Start a conversation:**
   - Use `!connect` to connect to the VTuber
   - Mention the bot or send DM to chat
   - Send images and audio files

2. **Commands:**
   - `!connect` - Connect to VTuber
   - `!disconnect` - Disconnect from VTuber
   - `!interrupt` - Stop current VTuber response
   - `!help_vtuber` - Show help information

## Message Format

The bots communicate with the VTuber WebSocket using these message types:

### Text Input
```json
{
  "type": "text-input",
  "text": "Hello VTuber!",
  "from_name": "User",
  "images": [
    {
      "source": "input",
      "data": "data:image/jpeg;base64,...",
      "mime_type": "image/jpeg"
    }
  ]
}
```

### Audio Input
```json
{
  "type": "mic-audio-data",
  "audio": [0.1, -0.2, 0.3, ...]
}
{
  "type": "mic-audio-end",
  "from_name": "User"
}
```

### Interrupt Signal
```json
{
  "type": "interrupt-signal",
  "text": "stop"
}
```

## Supported Audio Formats

- **Input**: MP3, WAV, OGG, M4A, AAC, FLAC
- **Processing**: Automatically converted to 16kHz mono float32 for VTuber server
- **Output**: Text responses (audio playback support can be added)

## Error Handling

- Connection failures are handled gracefully
- Audio conversion errors are reported to users
- WebSocket disconnections trigger automatic cleanup
- Invalid file formats are rejected with helpful messages

## Development

### Adding New Features

1. **Extend base_client.py** for new WebSocket message types
2. **Add handlers** in the respective bot files
3. **Update message routing** in the VTuber WebSocket handler

### Customization

- Modify character names and personalities
- Add custom commands
- Implement audio playback for responses
- Add support for more file formats
- Integrate with other platforms

## Troubleshooting

### Common Issues

1. **"Not connected" errors:**
   - Ensure VTuber server is running on the correct port
   - Check WebSocket URL in configuration

2. **Audio processing failures:**
   - Install FFmpeg: `sudo apt install ffmpeg` (Linux) or download from [ffmpeg.org](https://ffmpeg.org)
   - Check audio file format is supported

3. **Bot not responding:**
   - Verify bot tokens are correct
   - Check bot permissions in Discord server
   - Ensure Message Content Intent is enabled for Discord

4. **Import errors:**
   - Install all dependencies: `pip install -r requirements.txt`
   - Check Python version compatibility (3.8+)

### Logs

Both bots use `loguru` for logging. Check console output for detailed error information.

## License

This project follows the same license as Open-LLM-VTuber.
