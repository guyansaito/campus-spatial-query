import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def main() -> int:
    username = os.getenv("MONGO_ROOT_USERNAME")
    password = os.getenv("MONGO_ROOT_PASSWORD")
    database_name = os.getenv("MONGO_DATABASE", "campus_service")

    if not username or not password:
        print("[FAIL] 缺少 MongoDB 用户名或密码，请检查 .env。")
        return 1

    try:
        port = int(os.getenv("MONGO_PORT", "27017"))
    except ValueError:
        print("[FAIL] MONGO_PORT 必须是整数。")
        return 1

    client = MongoClient(
        host="127.0.0.1",
        port=port,
        username=username,
        password=password,
        authSource="admin",
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        appname="campus-environment-check",
        tz_aware=True,
    )

    try:
        # 1. 连通性和身份认证
        client.admin.command("ping")
        print("[OK] MongoDB 连接及认证成功")

        # 2. 数据库版本
        server_info = client.server_info()
        print(f"[OK] MongoDB 版本: {server_info['version']}")

        database = client[database_name]
        collection = database["_environment_checks"]

        # 固定 ID，重复执行不会不断增加检查数据。
        document_id = "mongodb-connection-check"

        # 3. 写入
        collection.replace_one(
            {"_id": document_id},
            {
                "_id": document_id,
                "project": "campus-spatial-query",
                "checked_at": datetime.now(timezone.utc),
                "message": "MongoDB environment is ready",
            },
            upsert=True,
        )
        print("[OK] 测试文档写入成功")

        # 4. 读取并校验
        result = collection.find_one({"_id": document_id})

        if result is None or result.get("project") != "campus-spatial-query":
            print("[FAIL] 测试文档读取校验失败")
            return 1

        print("[OK] 测试文档读取成功")

        # 5. 删除测试文档，不污染正式业务数据
        collection.delete_one({"_id": document_id})
        print("[OK] 测试文档清理成功")

        print()
        print(f"业务数据库: {database_name}")
        print(f"连接地址: 127.0.0.1:{port}")
        print("环境检查通过，可以进入数据模型与索引初始化阶段。")
        return 0

    except PyMongoError as exc:
        print(f"[FAIL] MongoDB 检查失败: {exc}")
        print("请检查容器状态、端口和 .env 中的账号密码。")
        return 1

    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())