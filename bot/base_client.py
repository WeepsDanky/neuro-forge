"""
Base WebSocket client for interfacing with Open-LLM-VTuber WebSocket handler
"""
import asyncio
import json
import base64
import io
import uuid
from typing import Optional, Dict, Any, List, Callable, Awaitable
from urllib.parse import urlparse
import websockets
import numpy as np
from loguru import logger
from PIL import Image


class VTuberWebSocketClient:
    """Base client for connecting to Open-LLM-VTuber WebSocket endpoint"""
    
    def __init__(self, ws_url: str = "ws://localhost:12393/client-ws"):
        """
        Initialize WebSocket client
        
        Args:
            ws_url: WebSocket URL for the VTuber server
        """
        self.ws_url = ws_url
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.client_uid: Optional[str] = None
        self.is_connected = False
        
        # Event handlers
        self.on_audio_response: Optional[Callable[[str, dict], Awaitable[None]]] = None
        self.on_text_response: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_error: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_connection_established: Optional[Callable[[str], Awaitable[None]]] = None
        
    async def connect(self) -> bool:
        """
        Connect to the WebSocket server
        
        Returns:
            bool: True if connected successfully, False otherwise
        """
        try:
            self.websocket = await websockets.connect(self.ws_url)
            self.is_connected = True
            logger.info(f"Connected to VTuber WebSocket: {self.ws_url}")
            
            # Start listening for messages
            asyncio.create_task(self._listen_for_messages())
            return True
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            self.is_connected = False
            return False
    
    async def disconnect(self):
        """Disconnect from the WebSocket server"""
        if self.websocket:
            await self.websocket.close()
            self.is_connected = False
            logger.info("Disconnected from VTuber WebSocket")
    
    async def _listen_for_messages(self):
        """Listen for incoming messages from the WebSocket server"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._handle_server_message(data)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {message}")
                except Exception as e:
                    logger.error(f"Error handling server message: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Error in message listener: {e}")
            self.is_connected = False
    
    async def _handle_server_message(self, data: Dict[str, Any]):
        """Handle incoming messages from the server"""
        msg_type = data.get("type")
        
        if msg_type == "set-model-and-conf":
            self.client_uid = data.get("client_uid")
            logger.info(f"Client UID assigned: {self.client_uid}")
            if self.on_connection_established:
                await self.on_connection_established(self.client_uid)
                
        elif msg_type == "full-text":
            text = data.get("text", "")
            if self.on_text_response and text not in ["Connection established", "Thinking..."]:
                await self.on_text_response(text)
                
        elif msg_type == "audio":
            if self.on_audio_response:
                await self.on_audio_response(data.get("audio", ""), data)
                
        elif msg_type == "error":
            error_msg = data.get("message", "Unknown error")
            logger.error(f"Server error: {error_msg}")
            if self.on_error:
                await self.on_error(error_msg)
    
    async def send_text_input(self, text: str, images: Optional[List[str]] = None):
        """
        Send text input to the VTuber
        
        Args:
            text: Text message to send
            images: Optional list of base64 encoded images
        """
        if not self.is_connected or not self.websocket:
            logger.error("Not connected to WebSocket")
            return False
            
        message = {
            "type": "text-input",
            "text": text
        }
        
        if images:
            message["images"] = [
                {
                    "source": "upload",
                    "data": img,
                    "mime_type": "image/jpeg"
                }
                for img in images
            ]
        
        try:
            await self.websocket.send(json.dumps(message))
            logger.info(f"Sent text input: {text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Failed to send text input: {e}")
            return False
    
    async def send_audio_input(self, audio_data: np.ndarray):
        """
        Send audio input to the VTuber
        
        Args:
            audio_data: Audio data as numpy array (float32, 16kHz sample rate)
        """
        if not self.is_connected or not self.websocket:
            logger.error("Not connected to WebSocket")
            return False
        
        try:
            # Send audio data
            audio_message = {
                "type": "mic-audio-data",
                "audio": audio_data.tolist()
            }
            await self.websocket.send(json.dumps(audio_message))
            
            # Send audio end signal
            end_message = {
                "type": "mic-audio-end"
            }
            await self.websocket.send(json.dumps(end_message))
            
            logger.info(f"Sent audio input with {len(audio_data)} samples")
            return True
        except Exception as e:
            logger.error(f"Failed to send audio input: {e}")
            return False
    
    async def send_interrupt(self, heard_response: str = ""):
        """
        Send interrupt signal to stop current conversation
        
        Args:
            heard_response: What was heard before interrupting
        """
        if not self.is_connected or not self.websocket:
            logger.error("Not connected to WebSocket")
            return False
        
        message = {
            "type": "interrupt-signal",
            "text": heard_response
        }
        
        try:
            await self.websocket.send(json.dumps(message))
            logger.info("Sent interrupt signal")
            return True
        except Exception as e:
            logger.error(f"Failed to send interrupt: {e}")
            return False
    
    @staticmethod
    def image_to_base64(image_path: str) -> str:
        """
        Convert image file to base64 data
        
        Args:
            image_path: Path to image file
            
        Returns:
            str: Base64 encoded image data
        """
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize if too large
            if img.width > 1024 or img.height > 1024:
                img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            img_data = buffer.getvalue()
            
            return base64.b64encode(img_data).decode()
    
    @staticmethod
    def bytes_to_base64(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        """
        Convert image bytes to base64 data
        
        Args:
            image_bytes: Image data as bytes
            mime_type: MIME type of the image
            
        Returns:
            str: Base64 encoded image data
        """
        return base64.b64encode(image_bytes).decode()
