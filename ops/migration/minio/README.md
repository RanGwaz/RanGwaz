# MinIO 安全迁移手册

这套脚本把 Windows 本地 MinIO 的 `rangwaz-media` 直接流式同步到 ECS
MinIO，不生成完整压缩包或中间副本，也不开放任何 MinIO 公网端口。

```text
Windows 127.0.0.1:9000
        │ SSH 反向隧道（公网只有 SSH）
        ▼
ECS 127.0.0.1:19090  ── mc mirror ──>  ECS 127.0.0.1:9000
        源                                  目标
```

脚本只处理 bucket 当前可见的对象版本和对象标签，不复制历史版本、删除标记
或其他对象元数据。若这些内容也必须迁移，请先停止本流程并改用 MinIO
replication 方案。当前项目按对象 key 推断图片 Content-Type，因此对象读取不
依赖源对象的 Content-Type 元数据。

当前固定的 MinIO OSS 2025 版本只允许用于**严格回环隔离的迁移和临时首发**。
它受 2026 年公开的签名绕过写入漏洞影响，9000/9001 绝不能暴露公网，Gateway
也不能代理原始 S3 API；流量稳定后应迁移到阿里云 OSS 或受支持的已修复对象存储。
详见 [GitHub 官方安全公告](https://github.com/minio/minio/security/advisories/GHSA-hv4r-mvr4-25vw)。

## 一、上线前硬门禁

开始前必须同时满足：

1. Windows Docker Desktop 和源 MinIO 正常，源地址是
   `http://127.0.0.1:9000`。
2. 停止本地后端、上传任务和任何会写入 `rangwaz-media` 的程序；迁移和验证
   全程保持只读。仅“关闭图片发布页面”不等于已经冻结全部后台写入。
3. ECS 目标 MinIO 尚未存在旧容器或旧卷；通过本目录的准备/启动脚本创建后，
   宿主机地址是 `http://127.0.0.1:9000`，数据卷位于 `/data/docker`。
4. ECS 安全组只开放 SSH、HTTP、HTTPS；**不要开放 9000、9001 或 19090**。
5. ECS 使用固定 `mc RELEASE.2025-08-13T08-35-41Z`、`curl`、`python3`；准备
   脚本会校验二进制 SHA256 和平台，迁移脚本还会检查 `--max-workers`、
   `--summary`。`--md5` 在该版本中是隐藏兼容参数，真实迁移时仍会使用。
6. 迁移开始前 `/data` 至少还有 101 GiB 可用空间和 200 万可用 inode。历史
   基线是 `317,076` 个对象、`70,349,795,919` 字节；实际以新清单为准。
7. 源和目标的 Access Key/Secret Key 已准备好，但不要写进脚本、命令历史或
   Git 文件。迁移和验证脚本默认在 `/dev/tty` 中隐藏两类凭据的输入。仅当受限
   SSH 运维密钥明确禁止 PTY 时，可信调用方才可设置
   `VIBELO_MINIO_CREDENTIAL_INPUT=stdin`，通过不记录日志的私有标准输入管道依次
   传入每组 Access Key、Secret Key。需要执行迁移确认时，可另外设置
   `VIBELO_MINIO_CONFIRMATION_INPUT=stdin`，在凭据后传入精确确认词。这两个开关
   本身都不含秘密。不要把凭据放进命令行参数、环境变量或可被记录的自动化日志。

当前 ECS 无法稳定访问 Docker Hub，因此使用已经在 Windows 本机按
`linux/amd64` 导出并校验的两个固定离线文件：

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `minio-RELEASE.2025-04-22T22-12-26Z-linux-amd64.tar` | `64,023,552` | `c220e4e0ef61abe83a084fdc4942af30c9f00e539fabc63b619ef73f01429d0f` |
| `mc-RELEASE.2025-08-13T08-35-41Z-linux-amd64` | `30,535,864` | `01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891` |

把它们传到 ECS 的 `/data/migration/minio/` 后，从仓库根目录依次运行：

```bash
cd /opt/vibelo
chmod 700 /data/migration/minio
chmod 600 /data/migration/minio/*

sudo bash ops/migration/minio/prepare-minio-target.sh
sudo bash ops/migration/minio/start-minio-target.sh
```

`prepare-minio-target.sh` 校验外层文件 SHA256、包内 `linux/amd64` manifest、
config 与所有 layer，再安装 `mc`、执行 `docker load`；它不会启动服务。
`start-minio-target.sh` 只执行带 `--pull never --no-build --no-deps` 的 MinIO
单服务启动，并验证只有 `minio` 在运行、9000/9001 仅绑定回环、实际卷是
`vibelo-public_public-minio-data` 且落在 `/data/docker`。任一门禁失败都停止，
不会自动删除已有容器或卷。

如果首次启动已经创建容器/卷，但随后因健康检查或后置门禁失败，脚本会故意保留
现场，默认首次启动模式也会拒绝覆盖。此时不要执行 `docker rm` 或
`docker volume rm`；改用严格的只读验收模式：

```bash
sudo bash ops/migration/minio/start-minio-target.sh --verify-existing
```

`--verify-existing` 不会调用 `compose up`、`start`、`restart`、重建或删除。它会精确
核对容器名与 Compose 标签、当前配置哈希、固定镜像 ID、资源限制、运行与健康
状态、回环端口、唯一可写数据卷、卷标签及 `/data/docker` 落点。全部通过即可继续
建立隧道；任一项失败都要保留现场并先诊断，尤其在 mirror 开始后绝不能删除
目标卷。

三个 Bash 入口的纯 fixture/mock 回归测试不会真实加载镜像或启动服务：

```bash
bash ops/migration/minio/test-minio-target-scripts.sh
```

## 二、建立仅回环可见的 SSH 反向隧道

在 Windows PowerShell 窗口 A 中进入本目录并运行：

```powershell
.\Start-MinioReverseTunnel.ps1 `
  -Mode Start `
  -EcsHost <ECS公网IP> `
  -EcsUser root `
  -IdentityFile <SSH私钥路径>
```

如果使用 SSH 密码登录，省略 `-IdentityFile`。首次连接使用 OpenSSH 的
`accept-new` 策略：可接受新主机，但主机密钥发生变化时会拒绝连接。
显式传入 `-IdentityFile` 时，脚本同时开启 `BatchMode=yes` 和
`IdentitiesOnly=yes`：私钥不可用或服务端拒绝时会立即失败，不会退回密码提示并在
后台长时间卡住。

窗口 A 必须一直保持运行。然后在 PowerShell 窗口 B 验证：

```powershell
.\Start-MinioReverseTunnel.ps1 `
  -Mode Verify `
  -EcsHost <ECS公网IP> `
  -EcsUser root `
  -IdentityFile <SSH私钥路径>
```

验证会在 ECS 内同时检查：

- 监听地址确实是 `127.0.0.1:19090`；
- 经隧道访问源 MinIO 的 `/minio/health/live` 成功。

如果 SSH 报 remote forwarding 被禁止，只检查 ECS 的
`/etc/ssh/sshd_config` 是否允许 `AllowTcpForwarding`。不要启用
`GatewayPorts yes`，也不要为了方便把 19090 放进安全组。

## 三、流式 mirror

在 ECS 本目录执行：

```bash
./minio-migrate.sh --bucket rangwaz-media
```

脚本会依次：

1. 验证两个回环 endpoint 的健康状态；
2. 通过 `/dev/tty` 交互读取源、目标凭据；
3. 为 `mc` 创建权限为 `700` 的临时配置目录，配置文件权限收紧为 `600`；
4. 生成迁移前源、目标的精确对象清单；
5. 要求输入 `MIRROR rangwaz-media` 二次确认；
6. 默认执行 `mc mirror --overwrite --retry --md5 --max-workers 4 --summary`；
7. 再次生成清单，证明迁移期间源未变化；
8. 对源、目标执行全量 key+size 比较。

脚本刻意不使用：

- `--remove`：绝不自动删除目标多余对象；
- `--skip-errors`：任何复制错误都必须让流程失败。

`--md5` 会让每个实际上传对象计算 MD5；最终完整性仍由后续全量 key+size 和
SHA256 抽样门禁确认。`--max-workers 4` 是当前 4 核 ECS 的保守默认值，只限制
对象复制并发，不等于限制总带宽或总 CPU；需要调整时可显式传
`--max-workers 1..32`。`--summary` 会在结束时输出同步汇总，但迁移期间可能
长时间没有逐对象进度，这是预期现象。

如果网络、SSH 或进程中断，保持源不写入，恢复隧道后重新运行同一命令。
`mc mirror` 会重新检查目标并继续协调缺失或变化的对象；源不会被修改。重跑
可能重新传输被判定为变化的对象，这是安全性优先的预期行为。

每次运行默认生成 `minio-audit-UTC时间` 目录。也可以指定：

```bash
./minio-migrate.sh \
  --bucket rangwaz-media \
  --audit-dir /root/minio-audit/mirror-01
```

若目标存在源没有的 key，脚本会保留它并让全量比较失败。不要在未确认来源前
手工删除；优先使用一个确定为空的新 bucket/卷，或者先单独备份并调查差异。

## 四、独立验证

mirror 门禁通过后，仍需运行独立验证：

```bash
./minio-validate.sh \
  --bucket rangwaz-media \
  --sample-count 1000 \
  --audit-dir /root/minio-audit/validate-01
```

验证包含三层：

1. **精确清单**：递归列举源和目标，分别计算对象数和总字节；
2. **全量比较**：比较每一个 key 和 size，差异完整写入
   `key-size-differences.jsonl`；
3. **内容抽样**：按 `0 字节`、`1~64 KiB`、`64 KiB~1 MiB`、
   `1~16 MiB`、`16 MiB 以上` 分层，再用 key 的确定性散列选择约 1000 个
   对象；每个对象从源和目标分别流式读取并计算 SHA256。

SHA256 不会把对象落盘。结果写入 `sha256-report.jsonl`，执行中断时会留下
`sha256-report.jsonl.partial`。使用**同一个审计目录**重跑验证，会复用清单
未变化且已经匹配的抽样项。若源或目标内容发生过变化，应使用新的审计目录，
强制重新计算全部抽样哈希。

只有同时满足以下条件才允许启动后端并切换流量：

- 迁移期间源清单前后完全一致；
- 源、目标对象数相等；
- 源、目标总字节相等；
- `key-size-differences.jsonl` 是空文件；
- SHA256 报告完整，失败数为 0。

## 五、安全与清理

- 凭据和确认词默认通过终端交互输入；无 PTY 的受限自动化只能使用上述私有
  stdin 模式。脚本不会硬编码、打印凭据或把凭据写入审计文件。
- 临时 `mc` 配置会在正常退出、失败或收到中断信号时自动删除。
- 审计目录权限是 `700`、文件权限是 `600`。其中包含完整对象 key，应按敏感
  运维资料管理。
- 完成验证后，在 Windows 隧道窗口按 `Ctrl+C` 关闭隧道；确认 ECS 上
  `127.0.0.1:19090` 已不再监听。
- 不要立即删除 Windows 源 MinIO。至少等公网后端读取验收、数据库对象 key
  对应检查、备份和一段稳定运行期全部完成后，再制定单独的下线操作。
- 脚本不构建镜像，不修改源 bucket，不删除目标对象，也不会接触数据库。

官方参考：

- [MinIO Client 下载与安装](https://github.com/minio/mc)
- [`mc mirror` 参数与同步边界](https://docs.min.io/aistor/reference/cli/mc-mirror/)
