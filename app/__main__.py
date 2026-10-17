"""Pornește serverul:  python -m app   (apoi deschideți http://localhost:8000)"""
import logging
import os

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")),
                reload=os.getenv("RELOAD", "0") == "1")
