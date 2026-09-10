"""Run the retail reference host with ``python -m commerce_agents``."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("commerce_agents.app:app", host="127.0.0.1", port=8000, reload=True)
