# Docker Desktop 稳定运行备忘

## 这次崩溃的主要原因

Docker Desktop 的 WSL 数据盘位于：

```text
D:\Docker\wsl\DockerDesktopWSL\disk\docker_data.vhdx
```

当前日志里已经出现：

```text
input/output error
I/O error, dev loop1
SIGBUS: bus error
dockerd exited with error
```

同时 D 盘只剩十几 MB。Docker 的虚拟磁盘所在盘符空间耗尽时，MySQL、Milvus、MinIO 还在写入，就容易让 Docker engine 直接卡死或自动停止。

## 先恢复 Docker

1. 先让 D 盘至少空出 30-50GB。`D:\QQMusicCache` 当前约 21GB，可以优先手动迁移或清理。
2. 关闭 Docker Desktop。
3. 执行：

```powershell
wsl --shutdown
```

4. 重新打开 Docker Desktop。
5. 检查：

```powershell
docker ps -a
```

## 长期建议

- Docker Desktop 设置里把资源调大一些：Memory 建议 6-8GB，Swap 建议 4GB。
- Docker 数据盘不要放在只剩几十 GB 的盘。迁移前目标盘建议至少有 220GB 可用空间。
- 跑 13 万图时，不建议同时跑打标和向量化。先跑一个，结束后再跑另一个。

## 脚本限速建议

云端打标：

```powershell
$env:VIBELO_LABEL_WORKERS="1"
.\tools\run_cloud_label.ps1
```

向量化：

```powershell
$env:VIBELO_EMBED_BATCH_SIZE="4"
.\tools\.venv\Scripts\python.exe tools\vectorize_images.py
```
