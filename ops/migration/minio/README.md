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

## 一、上线前硬门禁

开始前必须同时满足：

1. Windows Docker Desktop 和源 MinIO 正常，源地址是
   `http://127.0.0.1:9000`。
2. 停止本地后端、上传任务和任何会写入 `rangwaz-media` 的程序；迁移和验证
   全程保持只读。仅“关闭图片发布页面”不等于已经冻结全部后台写入。
3. ECS 目标 MinIO 正常，宿主机地址是 `http://127.0.0.1:9000`，其数据卷位于
   `/data` 所在的 160 GB 数据盘。
4. ECS 安全组只开放 SSH、HTTP、HTTPS；**不要开放 9000、9001 或 19090**。
5. ECS 已安装最新官方 `mc`、`curl`、`python3`，并且 `mc mirror --help`
   同时列出 `--max-workers`、`--summary`；过旧客户端会被脚本拒绝。`--md5`
   在新版 `mc` 中可能是隐藏参数，因此不能靠帮助文本判断，但真实迁移命令仍会
   使用它，若客户端不支持就会立即失败。
6. 目标盘剩余空间足够。历史基线是 `317,076` 个对象、
   `70,349,795,919` 字节；实际迁移以脚本新生成的精确清单为准。
7. 源和目标的 Access Key/Secret Key 已准备好，但不要写进脚本、命令历史或
   Git 文件。

Ubuntu x86_64 可从 MinIO 官方稳定下载地址安装最新 `mc`。先下载到临时文件，
成功后再原子式安装，避免下载中断时破坏现有命令：

```bash
MC_TMP=$(mktemp)
curl --fail --location --retry 3 \
  https://dl.min.io/client/mc/release/linux-amd64/mc \
  --output "$MC_TMP"
sudo install -m 0755 "$MC_TMP" /usr/local/bin/mc
rm -f "$MC_TMP"

mc --version
mc mirror --help | grep -E -- '--max-workers|--summary'
```

复制本目录到 ECS 后，先赋予两个 Bash 入口执行权限：

```bash
chmod 700 minio-migrate.sh minio-validate.sh
chmod 600 minio-common.sh minio_manifest.py README.md
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

- 凭据只通过终端交互输入。脚本不会硬编码、打印或写入审计文件。
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
