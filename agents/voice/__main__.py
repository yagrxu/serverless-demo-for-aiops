"""Run the voice agent server directly: python -m agents.voice"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "agents.voice.server:app",
        host="0.0.0.0",
        port=8084,
        reload=True,
    )
