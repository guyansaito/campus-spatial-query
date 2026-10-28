import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

_client: MongoClient | None = None


def mongo_settings() -> dict:
    return {
        "host": "127.0.0.1",
        "port": int(os.getenv("MONGO_PORT", "27017")),
        "username": os.getenv("MONGO_ROOT_USERNAME"),
        "password": os.getenv("MONGO_ROOT_PASSWORD"),
        "database": os.getenv("MONGO_DATABASE", "campus_service"),
    }


def get_client() -> MongoClient:
    global _client
    if _client is None:
        settings = mongo_settings()
        if not settings["username"] or not settings["password"]:
            raise RuntimeError("缺少 MongoDB 账号，请检查 .env")
        _client = MongoClient(
            host=settings["host"],
            port=settings["port"],
            username=settings["username"],
            password=settings["password"],
            authSource="admin",
            serverSelectionTimeoutMS=8000,
            socketTimeoutMS=180000,
            appname="campus-spatial-query",
            tz_aware=True,
        )
    return _client


def get_database():
    return get_client()[mongo_settings()["database"]]
