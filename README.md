# 校园服务设施空间查询

基于 MongoDB 8 的校园设施和共享单车查询。楼宇、设施、车辆最新位置走地理索引；约 1700 万条历史上报放在时间序列集合里，不进“附近的车”这条查询。

提交时不要打包数据库，也不要提交 Docker volume。

## 环境

- Docker Desktop
- Python 3.12，依赖见 `requirements.txt`

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

## 一条命令起环境

在项目根目录：

```powershell
docker compose up -d
```

或 `.\scripts\up.ps1`。MongoDB 只监听本机 `127.0.0.1:27017`。

## 一条命令灌入种子数据

```powershell
.\.venv\Scripts\python.exe scripts\seed.py
```

或 `.\scripts\seed.ps1`。脚本会重建楼宇、2 万个设施、2000 辆车、3 天每 30 秒一条上报，并可以重复执行。全量上报大约要十几分钟，只写进本机数据库。

## 启动查询服务和地图

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
cd web
npm install
npm run dev
```

接口文档在 `http://127.0.0.1:8000/docs`，地图在 `http://localhost:5173/`。

## 八项功能

| 功能 | 脚本 |
| --- | --- |
| 写入 | `scripts/queries/01_write.py` |
| 附近查找 | `scripts/queries/02_nearby.py` |
| 区域检索 | `scripts/queries/03_within.py` |
| 包含判断 | `scripts/queries/04_contains.py` |
| 覆盖分析 | `scripts/queries/05_coverage.py` |
| 车辆热力 | `scripts/queries/06_heatmap.py` |
| 跳变识别 | `scripts/queries/07_anomalies.py` |
| 状态维护 | `scripts/queries/08_status.py` |

一次跑完并记录存储占用：

```powershell
.\.venv\Scripts\python.exe scripts\run_acceptance.py
```

结果在 `results/`。

## 压测

先启动 API，再执行。默认 50 并发、预热 20 秒、测量 10 分钟。

```powershell
.\.venv\Scripts\python.exe scripts\bench_nearby.py --concurrency 50 --seconds 600 --warmup 20
```

输出：`results/bench_output.txt`、`results/bench_summary.json`、`results/bench_per_second.csv`。
