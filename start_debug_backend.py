#!/usr/bin/env python3
"""Debug backend startup script."""

import os
import sys

import uvicorn

# Add repository root to path so `backend.*` imports resolve.
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == "__main__":
    print("🚀 Starting AutoDev Agent Backend (Debug Mode)")
    print("📝 Note: Starts the same FastAPI app as production scripts")
    print("🔗 Backend will be available at: http://localhost:8000")
    print("🔌 WebSocket endpoint: ws://localhost:8000/ws/{dialog_id}")
    print()
    
    try:
        uvicorn.run(
            "backend.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n⏹️  Backend stopped by user")
    except Exception as e:
        print(f"\n❌ Error starting backend: {e}")
        sys.exit(1) 