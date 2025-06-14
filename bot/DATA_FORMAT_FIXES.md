# Data Format Compatibility Fixes

This document describes the data format fixes made to ensure compatibility between the bot implementations and the Open-LLM-VTuber WebSocket handler.

## Issues Fixed

### 1. Image Data Format
**Problem**: Images were being sent with data URL prefixes (`data:image/jpeg;base64,`) but the websocket handler expects raw base64 data.

**Solution**: Updated `VTuberWebSocketClient.bytes_to_base64()` and `VTuberWebSocketClient.image_to_base64()` methods to return only the base64 encoded string without the data URL prefix.

### 2. Image Source Enum Values
**Problem**: Image source was set to `"input"` but the `ImageSource` enum only accepts `"camera"`, `"screen"`, `"clipboard"`, and `"upload"`.

**Solution**: Changed image source to `"upload"` which is the appropriate value for user-uploaded images.

### 3. Message Structure Compatibility
**Problem**: Bot implementations were sending extra fields that aren't defined in the `WSMessage` TypedDict.

**Solution**: Removed unused fields like `from_name` from message structures to match the exact WSMessage format:
```python
{
    "type": "text-input",
    "text": "message text",
    "images": [  # Optional
        {
            "source": "upload",
            "data": "base64_encoded_data",
            "mime_type": "image/jpeg"
        }
    ]
}
```

### 4. Audio Message Format
**Problem**: Audio end messages were including unnecessary fields.

**Solution**: Simplified audio end message to only include the required type:
```python
{
    "type": "mic-audio-end"
}
```

## Verified Message Types

The following message types are correctly implemented and match the websocket handler expectations:

- `text-input`: For text messages with optional images
- `mic-audio-data`: For streaming audio data (float32 arrays)
- `mic-audio-end`: To signal end of audio input
- `interrupt-signal`: To interrupt ongoing conversations

## Image Processing

Images are now processed as follows:
1. Downloaded from Telegram/Discord
2. Converted to base64 using `base64.b64encode(image_bytes).decode()`
3. Sent with proper metadata:
   - `source`: "upload"
   - `data`: raw base64 string (no data URL prefix)
   - `mime_type`: actual MIME type from the attachment

## Audio Processing

Audio is processed as follows:
1. Downloaded and converted to 16kHz mono using pydub
2. Normalized to float32 values between -1.0 and 1.0
3. Sent as array in `mic-audio-data` message
4. Followed by `mic-audio-end` signal

## Testing

To test the compatibility:

1. Start the Open-LLM-VTuber server
2. Run either bot (Telegram or Discord)
3. Connect to a channel/chat
4. Send text, images, and voice messages
5. Verify the VTuber responds appropriately

All message formats now match the exact specifications in the websocket handler's `WSMessage` TypedDict and `ImageSource`/`MessageType` enums.
