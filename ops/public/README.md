# ECS 公网上线前置脚本

本目录提供四类公网发布门禁：

1. 安全生成或更新仓库根目录的 `.env.public`；
2. 在 Ubuntu ECS 上做只读上线预检。
3. 在干净的完整 Git SHA 上导出、导入并验收固定的 `linux/amd64` 公网镜像 release；
4. 下载、校验并在 ECS 离线安装搜索重建所需的固定 PyMySQL wheel。

日常发布不用再手工拼接这些底层步骤：Windows 运行
`New-PublicReleaseBundle.ps1` 完成本地测试、两个应用镜像各构建一次和 full-SHA
导出；上传三文件后，ECS 先运行 `public-release.sh validate`，再用同一脚本的
`deploy` 动作完成受控更新。简明命令、失败恢复和回滚见
[`docs/公网简化发布.md`](../../docs/公网简化发布.md)。底层脚本继续保留，供首次迁移、
审计和灾难恢复使用。

简化入口要求 `.env.public` 已有前后端同一 full-SHA 基线；没有基线的应用首次发布、
或 current→target 间 Flyway migration 目录有任何变化时都会 fail-closed，必须使用
完整发布流程。每次运行前先把 ECS `main` 快进到 `origin/main`：deploy 还要求
`HEAD == RELEASE == origin/main`，rollback 则保持最新 HEAD 并只切旧镜像，不执行旧
commit 中的 helper，也不切换/清理 Git 工作树。validate、deploy、rollback 都要求当前
release 与目标 release 的 Compose、Nginx、reindex/固定 requirements 完全一致；rollback
还要求旧目标与最新主线的这些真实运行契约一致。发布与 MinIO 控制脚本始终使用受信任
的最新主线版本，不属于旧应用运行契约；任一运行契约门禁失败都必须改走完整手册。

此外，`validate-domain-tls.sh` 提供域名 HTTPS 的只读上线门禁。域名实名认证不等于
ICP 备案；中国内地 ECS 首次备案审核期间必须关站，备案通过前不要启用 TLS 覆盖文件。
完整顺序和命令见 [`docs/域名备案与HTTPS上线.md`](../../docs/域名备案与HTTPS上线.md)。

配置与预检脚本不会构建镜像，也不会启动、停止或修改任何容器。镜像导出/导入脚本只处理已经构建好的镜像及归档，不联网拉取，也不启动服务；依赖安装脚本只使用指定 wheel，不访问 PyPI。服务启动必须按部署手册的显式顺序另行执行。

## 先准备 RDS 应用账号

RDS 中应已存在：

- 数据库：`rangwaz_image_dev`
- 标准应用账号：`vibelo_app`
- 权限：只授权 `rangwaz_image_dev` 的读写权限（DDL + DML）

不要把 RDS 高权限账号用于应用。`dms_user_*` 是 DMS 自动服务账号，也不能写入
`.env.public`，不能修改或删除它；请始终使用独立的 `vibelo_app` 标准账号。

## 1. 安全配置 `.env.public`

在仓库根目录执行：

```bash
bash ops/public/configure-rds-env.sh \
  --sms-sign-name '你的短信签名' \
  --sms-template-code '你的模板代码'
```

不传 `--allowed-origin` 时，脚本会要求交互输入浏览器真实访问
地址，格式是 `http://<ECS真实公网IPv4>` 或 `https://<你的真实域名>`。必须换成
你自己的公网 IP 或域名，不能把“你的ECS公网IP”等说明文字原样
复制进配置。该值必须是 origin，不能带路径、query 或 fragment。

脚本默认写入以下非秘密目标：

- RDS：`rm-bp111eaxy9eeuvqcb.mysql.rds.aliyuncs.com:3306`
- 数据库：`rangwaz_image_dev`
- 应用账号：`vibelo_app`

随后会在终端中静默询问：

- RDS 应用账号密码；
- 登录 Token 签名密钥（至少 32 个字符）；
- MinIO Access Key 和 Secret Key；
- 阿里云短信 AccessKey ID 和 AccessKey Secret。

输入过程不回显，脚本也不会打印秘密。再次运行时，已有有效秘密可以直接按
Enter 保留。脚本以现有 `.env.public` 为基础更新，因此不会删除或覆盖不认识的
环境变量；模板新增的变量会自动补齐。最终文件会原子替换并设置为权限 `600`。

不要把秘密写在命令行参数中。脚本故意不提供密码、Token 或 AccessKey 参数，
避免它们进入 shell 历史和进程列表。

可选的非秘密参数：

```text
--rds-host HOST
--rds-port PORT
--database NAME
--app-user USER
--public-http-port PORT
--allowed-origin URL
--sms-mock true|false
--sms-sign-name NAME
--sms-template-code CODE
--ssl-mode PREFERRED|REQUIRED|VERIFY_CA|VERIFY_IDENTITY
```

若首发阶段确实要使用模拟短信，可显式传入 `--sms-mock true`。正式公网登录应使用
默认的 `false` 并配置真实短信凭据。当前 RDS 尚未启用 SSL 时使用默认
`PREFERRED`；启用后显式传 `--ssl-mode REQUIRED`（或已正确部署 CA/主机名校验时
使用更严格模式）。再次运行脚本会保留已有 SSL 模式，不会静默降级。

## 2. 运行只读预检

配置完成后，在仓库根目录执行：

```bash
sudo bash ops/public/preflight.sh
```

建议使用 `sudo`，否则普通账号可能无权读取 Docker 或 containerd 的生效配置。
预检会一次列出全部结果，检查：

- `/data` 是否为独立、可写挂载点；
- DockerRoot 是否为 `/data/docker`；
- containerd root 是否为 `/data/containerd`；
- Swap 是否启用且不少于 4 GB；
- `vm.max_map_count` 是否至少为 `1048576`；
- TCP 80、443 是否仍空闲；
- RDS 内网域名能否解析、3306 端口能否连接；
- `.env.public` 是否为普通文件、权限是否为 `600`；
- RDS、Token、MinIO、短信等必填变量是否仍是占位符；
- Spring 与训练任务是否都使用同一个 `vibelo_app` RDS 凭据；
- `docker compose ... config --quiet` 是否通过。

Compose 检查只解析配置，输出会被隐藏以免泄露秘密；它不会拉取、构建或启动镜像。
受控入口固定 `-p vibelo-public` 和本机 `unix:///var/run/docker.sock`，并以白名单环境
执行；调用者 shell 的业务变量、`COMPOSE_*`、远程 `DOCKER_HOST` 或 context 不能覆盖
`.env.public` 或改变目标 Engine。
预检存在任一 `[失败]` 时退出码为 `1`，全部通过时退出码为 `0`。`[警告]` 不会单独
阻止通过，但上线前仍应确认其影响。

80/443 的检查是“上线前端口应空闲”。网关正式启动后再次运行该脚本，这两项会因
网关正在监听而失败，这是预期现象。

受控日常更新由 `public-release.sh` 调用
`preflight.sh --allow-running-gateway-ports`：该例外只有在每一个繁忙监听地址都与唯一
`vibelo-public` Gateway 的 Docker 端口发布完全一致时才通过，TLS/其他进程占用仍会
失败。不要把这个参数用于绕过未知端口占用。

修改预检公共校验逻辑后，可运行不接触系统配置的回归测试：

```bash
bash ops/public/test-public-common.sh
```

## 3. 导出并导入离线公网镜像 release

推荐直接使用：

```powershell
.\ops\public\New-PublicReleaseBundle.ps1 -ValidateOnly
.\ops\public\New-PublicReleaseBundle.ps1
```

下面是薄入口内部复用的底层等价步骤，排障时再单独执行。

先在联网 Windows 主机完成测试并提交所有发布内容。全部跟踪文件必须无改动，`backend/`、`frontend/` 不能有未跟踪构建输入；不参与镜像构建的个人未跟踪文档可以保留。`$release` 必须是当前 HEAD 的完整 40 位 SHA；所需基础镜像和固定中间件镜像也必须已经存在于本机：

```powershell
cd G:\你的路径\RanGwaz
$release = (git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $release -notmatch '^[0-9a-f]{40}$') {
  throw '无法读取完整 Git SHA'
}
$trackedDirty = @(git status --porcelain=v1 --untracked-files=no)
$untrackedBuildInputs = @(git ls-files --others --exclude-standard -- backend frontend)
if ($LASTEXITCODE -ne 0 -or $trackedDirty.Count -ne 0 -or $untrackedBuildInputs.Count -ne 0) {
  throw '已跟踪文件或前后端构建输入不干净，请先提交相关变更'
}

docker build --pull=false --platform linux/amd64 `
  --build-arg "VIBELO_GIT_REVISION=$release" `
  --tag "vibelo-public-backend:$release" `
  .\backend

docker build --pull=false --platform linux/amd64 `
  --build-arg "VIBELO_GIT_REVISION=$release" `
  --build-arg 'VITE_API_BASE=/api' `
  --build-arg 'VITE_MEDIA_UPLOAD_ENABLED=false' `
  --tag "vibelo-public-frontend:$release" `
  .\frontend

$bundleDir = Join-Path $env:TEMP "vibelo-public-$release"
if (Test-Path -LiteralPath $bundleDir) {
  throw "导出目录必须不存在或为空：$bundleDir"
}
.\ops\public\Export-PublicImageBundle.ps1 `
  -Release $release `
  -TargetDirectory $bundleDir
```

导出器会拒绝脏工作树、短 SHA、错误 commit tag、错误 revision label 和非 `linux/amd64` 镜像，并固定导出八个镜像。把导出目录中的三个文件原样上传到 ECS 的独立目录 `/data/releases/<完整 SHA>/`；该目录不能混入 wheel 或其他文件。然后在与该 SHA 完全一致且干净的 ECS 仓库中验收导入：

```bash
cd /opt/vibelo
RELEASE='<完整的 40 位 Git SHA>'
test "$(git rev-parse HEAD)" = "$RELEASE"
test -z "$(git status --porcelain=v1 --untracked-files=no)"

bash ops/public/import-public-image-bundle.sh \
  --release "$RELEASE" \
  --target-directory "/data/releases/$RELEASE" \
  --validate-only
```

去掉 `--validate-only` 才会把归档加载到 Docker；日常更新由
`public-release.sh deploy` 在全部只读门禁通过后完成。导入器会校验目录内容、
SHA256、八个固定引用、镜像 ID、平台，并直接解析归档内 OCI config 验证两个应用镜像
的 revision label；这些检查在 `--validate-only` 中已经完成，不依赖先加载镜像。它还会
输出归档中固定 MinIO 的内容 ID，受控发布会在正式 `docker image load` 前将该值与当前
运行 MinIO 容器的实际 Image ID 比较；即使 tag 相同，内容 ID 不同也会停止发布。底层
手工操作时只把其中两个应用镜像引用写入 `.env.public`，每个键只保留一条，并恢复权限
`600`：

```text
VIBELO_BACKEND_IMAGE=vibelo-public-backend:<完整的 40 位 Git SHA>
VIBELO_FRONTEND_IMAGE=vibelo-public-frontend:<完整的 40 位 Git SHA>
```

完整输出还包含只用于身份验收、不要写入 `.env.public` 的诊断值：

```text
VIBELO_MINIO_IMAGE_ID=sha256:<64 位十六进制内容 ID，仅用于身份验收，不写入 .env.public>
```

不要使用 `latest`、短 SHA、ECS 上的 `docker build`、公网 Compose 的 `up --build` 或任何镜像拉取。上传、首次启动和更新的完整顺序见部署手册第 9、12 节。

## 4. 离线准备搜索重建依赖

ECS 不直接访问 PyPI。先在联网的 Windows 主机运行：

```powershell
$wheelDir = Join-Path $env:TEMP 'vibelo-search-reindex'
.\ops\public\Prepare-SearchReindexDependencies.ps1 -OutputDirectory $wheelDir
```

脚本只下载固定的 `pymysql-1.1.2-py3-none-any.whl`，并校验固定尺寸和 SHA256。把该文件上传到 ECS 的 `/data/migration/search-reindex/` 后执行：

```bash
cd /opt/vibelo
bash ops/public/install-search-reindex-dependencies.sh \
  --wheel /data/migration/search-reindex/pymysql-1.1.2-py3-none-any.whl \
  --venv /opt/vibelo/.venv-ops \
  --validate-only
```

`--validate-only` 不创建或修改 venv；正式安装时去掉它。安装器强制
`--no-index --no-deps`，不会访问包索引或升级 pip；既有 venv 只有在包版本和 wheel
SHA256 凭据均匹配时才会复用。日常更新由 `public-release.sh` 自动选择只读/正式模式。
搜索索引的首次启动顺序、维护窗口和证书门禁见
[`docs/公网部署与Nginx网关.md`](../../docs/公网部署与Nginx网关.md#9-首次构建与发布)。

## 安全边界

- `.env.public` 已被仓库根目录 `.gitignore` 忽略，不要强制提交。
- 脚本不会验证 MySQL 用户名和密码是否能登录，只验证 RDS DNS/TCP；数据库导入和
  权限探测应在启动后端之前单独完成。
- 不要在聊天、工单、终端截图或命令行参数中粘贴任何真实密码或 AccessKey。
- 预检通过不代表业务数据已经迁移完成；数据库与 MinIO 数据校验仍需按迁移手册执行。
