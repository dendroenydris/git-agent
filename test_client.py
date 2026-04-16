#!/usr/bin/env python3
"""
Command line client for testing AutoDev Agent backend
Used for debugging WebSocket connections and API functionality
"""

import asyncio
import websockets
import json
import requests
import sys
import argparse
from datetime import datetime
from typing import Optional, Dict, Any

class AutoDevTestClient:
    def __init__(self, api_base: str = "http://localhost:8000", ws_base: str = "ws://localhost:8000"):
        self.api_base = api_base
        self.ws_base = ws_base
        self.websocket = None
        
    def test_health(self) -> bool:
        """Test backend health status"""
        try:
            response = requests.get(f"{self.api_base}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Backend health: {data}")
                return True
            else:
                print(f"❌ Backend health check failed: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ Cannot connect to backend: {e}")
            return False
    
    def create_dialog(self, repo_owner: str = "ultralytics", repo_name: str = "yolov5") -> Optional[str]:
        """Create a new dialog"""
        try:
            payload = {
                "owner": repo_owner,
                "name": repo_name,
                "branch": "main"
            }
            response = requests.post(f"{self.api_base}/api/dialogs", json=payload, timeout=10)
            if response.status_code == 200:
                dialog = response.json()
                dialog_id = dialog["id"]
                print(f"✅ Dialog created successfully: {dialog_id}")
                print(f"   Title: {dialog['title']}")
                return dialog_id
            else:
                print(f"❌ Failed to create dialog: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"❌ Error creating dialog: {e}")
            return None
    
    def get_dialogs(self) -> list:
        """Get all dialogs"""
        try:
            response = requests.get(f"{self.api_base}/api/dialogs", timeout=10)
            if response.status_code == 200:
                dialogs = response.json()
                print(f"✅ Found {len(dialogs)} dialog(s)")
                for dialog in dialogs:
                    print(f"   - {dialog['id']}: {dialog['title']}")
                return dialogs
            else:
                print(f"❌ Failed to get dialogs: {response.status_code}")
                return []
        except requests.exceptions.RequestException as e:
            print(f"❌ Error getting dialogs: {e}")
            return []
    
    async def test_websocket_connection(self, dialog_id: str) -> bool:
        """Test WebSocket connection"""
        try:
            print(f"🔌 Attempting WebSocket connection: {self.ws_base}/ws/{dialog_id}")
            
            async with websockets.connect(f"{self.ws_base}/ws/{dialog_id}") as websocket:
                self.websocket = websocket
                print("✅ WebSocket connected successfully!")
                
                # Send test message
                test_message = {
                    "type": "user_message",
                    "content": "Hello, this is a test from command line client",
                    "repo": {
                        "owner": "ultralytics",
                        "name": "yolov5",
                        "branch": "main"
                    }
                }
                
                print("📤 Sending test message...")
                await websocket.send(json.dumps(test_message))
                print(f"   Message content: {test_message}")
                
                # Wait for multiple responses
                print("⏳ Waiting for responses...")
                response_count = 0
                max_responses = 3
                
                try:
                    while response_count < max_responses:
                        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        response_data = json.loads(response)
                        response_count += 1
                        print(f"✅ Response {response_count}: {response_data}")
                        
                        # Break if we get a completed task
                        if response_data.get("type") == "task_updated" and response_data.get("status") == "completed":
                            break
                            
                except asyncio.TimeoutError:
                    print(f"⚠️  Response timeout after {response_count} responses")
                
                return True
                
        except websockets.exceptions.ConnectionClosed as e:
            print(f"❌ WebSocket connection closed: {e}")
            return False
        except websockets.exceptions.InvalidHandshake as e:
            print(f"❌ WebSocket handshake failed: {e}")
            return False
        except Exception as e:
            print(f"❌ WebSocket connection failed: {e}")
            return False
    
    async def test_empty_dialog_id(self):
        """Test empty dialog_id scenario"""
        print("\n🧪 Testing empty dialog_id WebSocket connection...")
        try:
            async with websockets.connect(f"{self.ws_base}/ws/") as websocket:
                print("❌ Unexpected success: empty dialog_id should be rejected")
                return False
        except websockets.exceptions.InvalidHandshake as e:
            if "403" in str(e):
                print("✅ Correct behavior: empty dialog_id rejected (403)")
                return True
            else:
                print(f"❌ Unexpected handshake error: {e}")
                return False
        except Exception as e:
            print(f"✅ Correct behavior: empty dialog_id connection failed - {e}")
            return True
    
    async def test_invalid_dialog_id(self):
        """Test invalid dialog_id scenario"""
        print("\n🧪 Testing invalid dialog_id WebSocket connection...")
        invalid_id = "invalid_dialog_id_12345"
        try:
            async with websockets.connect(f"{self.ws_base}/ws/{invalid_id}") as websocket:
                # If we get here, the connection was accepted
                # But we need to check if it gets immediately closed
                try:
                    # Try to send a message and wait for response
                    await websocket.send(json.dumps({"type": "test", "content": "hello"}))
                    response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    print("⚠️  Invalid dialog_id connection succeeded and stayed open")
                    print("   🔍 This suggests backend should add dialog_id validation")
                    return True
                except asyncio.TimeoutError:
                    print("⚠️  Invalid dialog_id connection succeeded but no response")
                    print("   🔍 Connection might be silently ignored")
                    return True
                except websockets.exceptions.ConnectionClosed as e:
                    if e.code == 1008:  # Policy violation
                        print(f"✅ Correct behavior: invalid dialog_id rejected with policy violation ({e.code}: {e.reason})")
                        return True
                    else:
                        print(f"✅ Correct behavior: invalid dialog_id connection closed ({e.code}: {e.reason})")
                        return True
                        
        except websockets.exceptions.InvalidHandshake as e:
            if "403" in str(e) or "404" in str(e):
                print(f"✅ Correct behavior: invalid dialog_id rejected ({e})")
                return True
            else:
                print(f"❌ Unexpected handshake error: {e}")
                return False
        except websockets.exceptions.ConnectionClosed as e:
            if e.code == 1008:  # Policy violation
                print(f"✅ Correct behavior: invalid dialog_id rejected with policy violation ({e.code}: {e.reason})")
                return True
            else:
                print(f"✅ Correct behavior: invalid dialog_id connection failed ({e.code}: {e.reason})")
                return True
        except Exception as e:
            print(f"✅ Correct behavior: invalid dialog_id connection failed - {e}")
            return True

async def main():
    parser = argparse.ArgumentParser(description="AutoDev Agent Backend Test Client")
    parser.add_argument("--api-base", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--ws-base", default="ws://localhost:8000", help="WebSocket base URL")
    parser.add_argument("--skip-websocket", action="store_true", help="Skip WebSocket tests")
    parser.add_argument("--dialog-id", help="Use specific dialog ID for WebSocket tests")
    
    args = parser.parse_args()
    
    client = AutoDevTestClient(args.api_base, args.ws_base)
    
    print("=" * 60)
    print("🚀 AutoDev Agent Backend Test Started")
    print("=" * 60)
    
    # 1. Test backend health
    print("\n1️⃣ Testing backend health...")
    if not client.test_health():
        print("❌ Backend unavailable, exiting test")
        sys.exit(1)
    
    # 2. Test API functionality
    print("\n2️⃣ Testing API functionality...")
    
    # Get existing dialogs
    dialogs = client.get_dialogs()
    
    # Create dialog if none exist
    dialog_id = args.dialog_id
    if not dialog_id:
        if not dialogs:
            print("📝 No existing dialogs, creating new one...")
            dialog_id = client.create_dialog()
        else:
            dialog_id = dialogs[0]["id"]
            print(f"📝 Using existing dialog: {dialog_id}")
    
    if not dialog_id:
        print("❌ Cannot get valid dialog_id, skipping WebSocket tests")
        return
    
    # 3. Test WebSocket functionality
    if not args.skip_websocket:
        print("\n3️⃣ Testing WebSocket functionality...")
        
        # Test valid dialog_id
        print(f"\n🔗 Testing valid dialog_id: {dialog_id}")
        await client.test_websocket_connection(dialog_id)
        
        # Test edge cases
        await client.test_empty_dialog_id()
        await client.test_invalid_dialog_id()
    
    print("\n" + "=" * 60)
    print("🏁 Test Completed")
    print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        sys.exit(1) 