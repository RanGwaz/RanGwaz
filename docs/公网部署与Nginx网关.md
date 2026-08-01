# Vibelo 公网部署与 Nginx 网关

本文是当前项目的正式中文上线手册。当前代码已经准备好 Dockerfile、Nginx 网关和公网 Compose，但按要求尚未构建任何项目镜像。只有确认本地验收全部通过并决定上线时，才执行文中的构建命令。

## 1. 公网架构

公网只有 Nginx Gateway 映射宿主机端口：

```text
浏览器 / 云 HTTPS 负载均衡
              |
        Nginx Gateway :80
         /            \ /api/**
  frontend          backend
                        |
      RDS MySQL / Redis / Kafka / MinIO / Elasticsearch
                        |
          可选模型服务 / Milvus
```

相关文件：

- `infra/nginx/gateway.conf`：公网 API 网关、限流、请求头和负载均衡。
- `infra/docker-compose.public.yml`：当前 8 GB 主机使用单前端、单后端和中间件编排。
- `frontend/nginx.conf`：每个前端实例内部的静态文件与 SPA 回退。
- `frontend/Dockerfile`：构建 React 静态文件，再交给轻量 Nginx 提供。
- `backend/Dockerfile`：构建 Spring Boot JAR，再用 JRE 运行。

## 2. 前端负载均衡如何工作

当前 7.1 GiB 服务器先运行一个 `frontend` 和一个 `backend`。单机本身就是故障单点，在同一台小内存主机上复制应用容器不能消除这个单点，反而会挤占 Elasticsearch、Kafka 和操作系统的内存。

Nginx Gateway 仍是唯一入口。它处理同源 `/api` 转发、短信限流、真实 IP/协议请求头和静态页面代理：

```nginx
upstream frontend_pool {
    least_conn;
    server frontend:80;
}
```

访问 `/`、`/home`、`/profile` 等页面时，请求进入前端。前端容器通过 `try_files ... /index.html` 支持 React Router 刷新，静态哈希资源缓存一年，`index.html` 不缓存，发布新版本后浏览器能立即拿到新入口文件。

`/api/**` 在 Gateway 中去掉 `/api` 前缀后进入 Spring Boot。前端和后端都不在容器内保存登录会话，因此以后扩容时不需要粘性会话。升级到至少 16 GB 内存或多台应用服务器后，可扩为多个副本并重启 Gateway，让 Nginx 重新解析副本地址：

```bash
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --scale frontend=2 --scale backend=2
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  restart gateway
```

这不是当前 7.1 GiB 服务器的首发命令。真正的宿主机高可用需要两台以上服务器，并由云负载均衡分流；一台服务器内的多容器只能应对单个应用进程故障。

## 3. 网关公开哪些路径

| 公网路径 | 目标 | 说明 |
| --- | --- | --- |
| `/` | 前端池 | React SPA |
| `/api/**` | 后端池 | 所有业务 API 的统一入口 |
| `/api/auth/sms-code` | 后端池 | 独立的每 IP 短信限流 |
| `/media/object/**` | 后端池 | 兼容数据库里的旧媒体 URL |
| `/uploads/**` | 后端池 | 兼容历史本地上传 URL |
| `/gateway/health` | Gateway | 网关健康检查 |

MySQL、Redis、Kafka、MinIO、Elasticsearch 和 Milvus 不绑定公网地址；需要宿主机工具访问的端口只绑定 `127.0.0.1`。安全组只允许 80/443，数据库端口全部拒绝公网。

## 4. 当前首发开关

首次上线以稳定浏览和行为收集为目标：

```text
APP_FEATURE_PUBLISHING_ENABLED=false
APP_FEATURE_MEDIA_UPLOAD_ENABLED=false
CONTENT_SAFETY_ENABLED=false
CONTENT_SAFETY_CLOUD_ENABLED=false
VECTOR_ENABLED=false
MODEL_RECALL_ENABLED=false
MODEL_RANKING_ENABLED=false
```

- 前端没有发布页面，旧 `/publish` 地址跳回首页。
- `POST /api/images` 返回统一 JSON 错误 `PUBLISHING_DISABLED`。
- `POST /api/media/upload` 同样返回 `PUBLISHING_DISABLED`；资料编辑页隐藏头像和背景上传，只保留昵称、简介。
- 不启动 8093 图片检测服务。
- 推荐先使用数据库冷启动/fallback，继续收集曝光、点击、停留、点赞、收藏和评论。
- ES 启动慢或短暂故障不会再杀死后端；建索引会后台重试，搜索临时回退 MySQL。
- 公网数据库使用同 VPC 的 RDS MySQL；上线前必须先验证内网地址、白名单和账号权限。Redis 和 Kafka 首次健康后才启动后端，避免验证码不可用或首批行为数据丢失。
- Milvus 位于 Compose 的 `recommendation` profile，首次上线默认不启动，减少内存和启动时间。

## 5. 发布前本地验收

以下命令不构建 Docker 镜像：

```powershell
docker compose -f infra/docker-compose.yml up -d

cd backend
mvn test
mvn spring-boot:run

cd ..\frontend
npm run build
npm run dev
```

另开终端检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/actuator/health
Invoke-RestMethod "http://127.0.0.1:8080/feed?page=1&pageSize=2"
```

只校验公网 Compose，不构建、不启动：

```powershell
cd ..
$env:SPRING_DATASOURCE_URL="jdbc:mysql://rds.invalid:3306/rangwaz_image_dev"
$env:SPRING_DATASOURCE_USERNAME="validation-only"
$env:SPRING_DATASOURCE_PASSWORD="validation-only"
$env:MINIO_ACCESS_KEY="validation-only"
$env:MINIO_SECRET_KEY="validation-only"
$env:APP_AUTH_TOKEN_SECRET="validation-only-token-secret-at-least-32-characters"
docker compose -f infra/docker-compose.public.yml config --quiet
```

## 6. 准备服务器

### 6.1 当前服务器结论

已确认服务器为 Ubuntu Server 26.04 LTS（Resolute Raccoon）x86_64，Linux 7.0.0-28-generic，4 vCPU、7.1 GiB 内存、40 GB 系统盘。安装 Docker 与 4 GB swapfile 后约有 31 GB 可用，80/443 未被占用。

- 可以运行当前“单前端 + 单后端 + 基础中间件”的首发栈。
- 不能在这台机器上同时启动 `recommendation` profile、Milvus 和模型训练任务。
- 公网 Compose 已给每个容器设置内存/PID 上限；默认 RDS 栈硬上限合计约 5.1 GiB，其中主 MinIO 为 1 GiB、预留 512 MiB，并给 Docker JSON 日志设置 `20m × 3` 轮转。
- Elasticsearch 固定使用 768 MiB JVM heap、1.5 GiB 容器上限，并禁止该容器使用 Swap。
- Ubuntu 26.04 LTS 是 Docker Engine 当前明确支持的发行版，避免继续承担 CentOS 7 已结束生命周期和旧内核带来的风险。
- 已安装 Docker Engine 29.6.2、Docker Compose 5.3.1，Docker 服务为 `active`，使用 `overlayfs`、systemd cgroup driver 和 cgroup v2。
- 4 GB swapfile、`vm.max_map_count=1048576` 和 `vm.swappiness=10` 均已生效。Swap 只用于承接瞬时峰值，不能代替内存扩容。

以下是新服务器已经执行过的初始化记录；重建服务器时按同样步骤操作。先更新系统并安装基础工具：

```bash
sudo apt update
sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y
sudo apt install -y ca-certificates curl git
```

若系统升级安装了新内核，再单独执行下面的重启命令。它会立即中断当前 SSH
连接；执行前确认没有正在运行的数据迁移或其他维护任务，然后等待 ECS 重新启动并
再次登录。不要把这条命令与上面的安装命令整段粘贴执行：

```bash
sudo reboot
```

重新登录后，按 Docker 官方 APT 仓库方式安装 Engine、Buildx 和 Compose 插件。不要使用系统提示的 `apt install docker.io` 或 `podman-docker`：

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

这里只安装运行环境，不构建 Vibelo 项目镜像。然后记录主机信息：

```bash
cat /etc/os-release
uname -r
nproc
free -h
df -h /
docker --version
docker compose version
docker info | grep -E 'Storage Driver|Backing Filesystem|Supports d_type|Cgroup|WARNING'
swapon --show
sudo ss -lntp | grep -E ':(80|443)\s' || true
```

Ubuntu 默认的 `overlay2`/ext4 组合可直接使用。若实际 `Backing Filesystem` 是 XFS，`Supports d_type` 必须为 `true`。

### 6.2 初始化 160 GB 数据盘并挂载到 `/data`

阿里云控制台购买并“挂载到 ECS”的数据盘是独立块设备，不会自动扩大系统盘。当前输出中：

- `/dev/vda3` 仍是 40 GB 系统盘，挂载点是 `/`；
- `/dev/vdb` 已被 ECS 识别，但 `FSTYPE` 和 `MOUNTPOINTS` 为空，说明它还没有可用文件系统和挂载点；
- `df -hT /` 只统计 `/` 所在的 `/dev/vda3`，所以它保持 40 GB 是正常现象。数据盘挂载后应使用 `df -hT /data` 查看。

格式化会清空目标设备。先执行以下**只读检查**，不要把设备名想当然地替换成其他磁盘：

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL
wipefs -n /dev/vdb
findmnt /dev/vdb || true
blkid /dev/vdb || true
```

只有同时满足以下条件才继续：`/dev/vdb` 大小约为 160 GB、没有挂载点、`wipefs -n` 没有发现任何已有文件系统/分区签名，并且已在阿里云控制台再次确认它就是新购的空数据盘。只要看到已有签名或不能确认，立即停止，不能执行 `mkfs`。

确认是空盘后，当前用途只需要一个文件系统，可以直接在整块盘上建立 ext4，无需再分多个分区：

```bash
apt update
apt install -y e2fsprogs
cp -a /etc/fstab "/etc/fstab.bak.$(date +%F-%H%M%S)"

mkfs.ext4 -F -L vibelo-data /dev/vdb
mkdir -p /data

DATA_UUID="$(blkid -s UUID -o value /dev/vdb)"
test -n "$DATA_UUID"
grep -qF "UUID=$DATA_UUID " /etc/fstab || \
  printf 'UUID=%s /data ext4 defaults,nofail 0 2\n' "$DATA_UUID" >> /etc/fstab

systemctl daemon-reload
mount -a
findmnt /data
df -hT /data
lsblk -f
```

`findmnt /data` 必须显示来源为 `/dev/vdb`，`df -hT /data` 应显示约 149 GiB 的 ext4 可用总容量（云盘标称 GB 与 Linux 显示的 GiB 口径不同）。如果 `mount -a` 报错，先用备份恢复 `/etc/fstab`，不要继续迁移 Docker 数据。

### 6.3 把 Docker 与 containerd 数据目录放到数据盘

仅把项目源码放进 `/data` 不够。Docker 的命名卷、配置等数据默认在 `/var/lib/docker`；全新安装的 Docker Engine 29 默认启用 containerd image store，镜像内容和容器 snapshot 还会单独写入 `/var/lib/containerd`。Docker 的 `data-root` **不会自动迁移 containerd 的目录**，因此两个目录都必须放到数据盘。先检查现状：

```bash
docker info --format 'DockerRoot={{.DockerRootDir}} Driver={{.Driver}} DriverStatus={{json .DriverStatus}}'
docker ps -a
docker volume ls
test -f /etc/docker/daemon.json && cat /etc/docker/daemon.json || \
  echo "NO_DAEMON_JSON"
test -f /etc/containerd/config.toml && cat /etc/containerd/config.toml || \
  echo "NO_CONTAINERD_CONFIG"
df -hT /data
```

如果 Docker 中还没有需要保留的容器、镜像和卷，可跳过对应的 `rsync`。如果已经有数据，先停止所有 Compose 项目，并在 Docker 与 containerd 完全停止后原样复制；不要边运行边复制：

```bash
apt install -y rsync jq
systemctl stop docker docker.socket containerd
mkdir -p /data/docker /data/containerd

# 仅在源目录中已有需要保留的数据时执行
test ! -d /var/lib/docker ||
  rsync -aHAXx --numeric-ids /var/lib/docker/ /data/docker/
test ! -d /var/lib/containerd ||
  rsync -aHAXx --numeric-ids /var/lib/containerd/ /data/containerd/
```

若 `/etc/docker/daemon.json` 不存在，创建最小配置：

```bash
install -d -m 0755 /etc/docker
printf '{\n  "data-root": "/data/docker"\n}\n' \
  > /etc/docker/daemon.json
```

若该文件已经存在，不要覆盖其他 Docker 设置，使用 `jq` 合并 `data-root`：

```bash
tmp_json="$(mktemp)"
jq '. + {"data-root":"/data/docker"}' /etc/docker/daemon.json > "$tmp_json" &&
  jq empty "$tmp_json" &&
  install -m 0644 "$tmp_json" /etc/docker/daemon.json &&
  rm -f "$tmp_json"
```

containerd 使用 `/etc/containerd/config.toml` 顶层的 `root`。先备份现有文件；若文件存在，必须保留其中其他配置并只修改顶层 `root`，若不存在则创建最小配置：

```bash
install -d -m 0755 /etc/containerd
test ! -f /etc/containerd/config.toml ||
  cp -a /etc/containerd/config.toml \
    "/etc/containerd/config.toml.bak.$(date +%F-%H%M%S)"

if test -s /etc/containerd/config.toml; then
  tmp_toml="$(mktemp)"
  awk '
    BEGIN { top = 1; written = 0 }
    top && /^[[:space:]]*\[/ {
      if (!written) print "root = \"/data/containerd\""
      top = 0
    }
    top && /^[[:space:]]*root[[:space:]]*=/ {
      if (!written) print "root = \"/data/containerd\""
      written = 1
      next
    }
    { print }
    END {
      if (top && !written) print "root = \"/data/containerd\""
    }
  ' /etc/containerd/config.toml > "$tmp_toml"
  install -m 0644 "$tmp_toml" /etc/containerd/config.toml
  rm -f "$tmp_toml"
else
  printf 'version = 2\nroot = "/data/containerd"\n' \
    > /etc/containerd/config.toml
fi
```

再让 Docker 和 containerd 明确依赖 `/data` 已成功挂载，避免重启后数据盘挂载失败时误把目录建到 40 GB 系统盘：

```bash
mkdir -p /etc/systemd/system/docker.service.d \
  /etc/systemd/system/containerd.service.d
cat > /etc/systemd/system/docker.service.d/data-root.conf <<'EOF'
[Unit]
RequiresMountsFor=/data
EOF
cat > /etc/systemd/system/containerd.service.d/data-root.conf <<'EOF'
[Unit]
RequiresMountsFor=/data
EOF

systemctl daemon-reload
systemctl enable --now containerd docker
docker info --format '{{.DockerRootDir}}'
containerd config dump | grep -m1 '^root = '
docker volume create vibelo-data-root-check
docker volume inspect vibelo-data-root-check --format '{{.Mountpoint}}'
docker volume rm vibelo-data-root-check
df -hT / /data
```

最后一组检查必须显示 Docker Root Dir 为 `/data/docker`、containerd root 为 `/data/containerd`，测试卷路径也必须位于 `/data/docker`。已有 Docker 数据时，还要检查原容器、镜像和卷是否完整。验证项目正常运行并完成备份前，不要删除旧的 `/var/lib/docker` 或 `/var/lib/containerd`；也不要在同一数据盘上额外留一份 65.5 GiB 的 MinIO 临时副本。

### 6.4 Elasticsearch 与 Swap 前置配置

以 root 身份设置 Elasticsearch 所需的虚拟内存映射数量和较低的 Swap 积极度：

```bash
printf 'vm.max_map_count=1048576\nvm.swappiness=10\n' \
  > /etc/sysctl.d/99-vibelo.conf
sysctl --system
sysctl vm.max_map_count vm.swappiness
```

以下命令已在当前服务器成功创建 4 GB Swap；只在新服务器首次初始化时执行一次：

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
grep -q '^/swapfile ' /etc/fstab || \
  echo '/swapfile swap swap defaults 0 0' >> /etc/fstab
free -h
swapon --show
```

看到约 4 GB Swap 后再继续。若任一步报错，不要重复执行 `fallocate` 覆盖一个已经启用的 swapfile。

### 6.5 安全组与 HTTPS

安全组建议：

- SSH 22：只允许自己的固定公网 IP。
- 80/443：直接部署 TLS 时对公网开放；使用云负载均衡/CDN 时，只允许其回源地址访问 80。
- 3306、6379、9092/29092、9000/9001、9200、19530、8091/8092：全部禁止公网访问。

最快的 HTTPS 方式是在云负载均衡、CDN 或托管网关上绑定证书，HTTPS 在云入口终止，再以 HTTP 回源当前 Nginx 80 端口。此时应：

1. 云入口只回源服务器的 `PUBLIC_HTTP_PORT`。
2. 服务器安全组只允许云入口节点访问回源端口。
3. 对用户只开放 HTTPS 443，并把 HTTP 80 重定向到 HTTPS。
4. 云入口必须透传 `X-Forwarded-For`、`X-Forwarded-Proto` 和 Host。

如果没有云 TLS 终止层，不要直接用当前纯 HTTP 配置承载真实登录和短信；先申请证书并在 Nginx 增加 443 server。

## 7. 环境变量

在服务器项目根目录执行：

```bash
cp .env.public.example .env.public
chmod 600 .env.public
```

至少替换：

- `SPRING_DATASOURCE_URL`：RDS MySQL 的内网地址、端口和数据库名
- `SPRING_DATASOURCE_USERNAME`、`SPRING_DATASOURCE_PASSWORD`：RDS 业务账号；不要使用高权限管理账号
- `MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`
- `APP_AUTH_TOKEN_SECRET`：至少 32 个随机字符；以后扩容出的所有后端必须完全一致
- `ALIYUN_SMS_ACCESS_KEY_ID`、`ALIYUN_SMS_ACCESS_KEY_SECRET`
- `ALIYUN_SMS_SIGN_NAME`、`ALIYUN_SMS_TEMPLATE_CODE`
- `APP_WEB_ALLOWED_ORIGIN_PATTERNS`：真实 HTTPS 站点来源

`.env.public` 已被 `.gitignore` 排除，不要提交。项目不再使用 `application-prod.yml` 或 `SPRING_PROFILES_ACTIVE=prod`。

### 7.1 RDS 同 VPC 内网配置

公网部署默认使用已购买的 RDS MySQL，不再让 ECS 上的本地 MySQL 承担正式数据。按以下顺序配置：

1. 确认 RDS 为 MySQL 8.0 或 8.4；现有 schema 使用 `utf8mb4_0900_ai_ci`，不能直接导入 MySQL 5.7。
2. 确认 RDS 与 ECS 位于同一地域、同一 VPC，优先使用 RDS 控制台显示的**内网地址**，不申请或使用公网连接地址。
3. 在 RDS 创建数据库 `rangwaz_image_dev`，字符集使用 `utf8mb4`；在 RDS“账号管理”中创建专用标准业务账号（建议 `vibelo_app`），并只授予该库读写（DDL + DML）权限。不要把高权限账号或 DMS 自动生成的 `dms_user_*` 安全托管账号写入应用配置。
4. 在 RDS 白名单中加入 ECS 的私网 IP（通常使用 `/32` 精确授权），不要配置 `0.0.0.0/0`。ECS 私网 IP 可用 `hostname -I` 或阿里云控制台核对。
5. 在 RDS 控制台启用 SSL 后，JDBC 使用 `sslMode=REQUIRED`；SSL 尚未启用时先使用 `sslMode=PREFERRED` 完成内网迁移与验证。
6. `.env.public` 中只写内网连接信息，不把密码写进 Compose、Git 或文档。

示例仅包含占位符：

```dotenv
SPRING_DATASOURCE_URL=jdbc:mysql://rm-xxxxxxxx.mysql.rds.aliyuncs.com:3306/rangwaz_image_dev?useUnicode=true&characterEncoding=UTF-8&serverTimezone=Asia/Shanghai&sslMode=PREFERRED
SPRING_DATASOURCE_USERNAME=vibelo_app
SPRING_DATASOURCE_PASSWORD=<RDS业务账号密码>
```

先从 ECS 验证 DNS、3306 连通性和账号权限，再启动后端：

```bash
getent hosts rm-xxxxxxxx.mysql.rds.aliyuncs.com
timeout 5 bash -c '</dev/tcp/rm-xxxxxxxx.mysql.rds.aliyuncs.com/3306'

apt update
apt install -y default-mysql-client
mysql --protocol=TCP --connect-timeout=5 \
  -h rm-xxxxxxxx.mysql.rds.aliyuncs.com -P 3306 \
  -u vibelo_app -p -e 'SELECT VERSION(), CURRENT_USER();'
```

命令中的地址和账号必须替换为控制台真实值；`-p` 会交互读取密码，不要把密码直接写在命令行中。如果 TCP 不通，依次核对地域/VPC、RDS 运行状态、内网地址和白名单，不要通过开放公网 3306 绕过问题。

若 Compose 保留了本地 MySQL profile，它只用于临时开发或灾难排查；公网常规启动不要启用该 profile，也不需要设置 `MYSQL_ROOT_PASSWORD`。

## 8. 迁移现有数据

公网 Compose 使用独立持久卷，不会自动读取本机开发 Compose 的卷。上线前至少迁移：

1. MySQL：导出当前 `rangwaz_image_dev`，再恢复到 RDS 的同名数据库；导入前先确认字符集、账号权限和备份。
2. 业务 MinIO：同步 `rangwaz-media` bucket，数据库中的 object key 必须保持不变。
3. Elasticsearch：可以不搬，后端启动后重新建立索引。
4. Milvus：首次推荐服务关闭，可暂不搬；以后用原图向量脚本重建更稳妥。
5. 推荐模型目录：以后启用双塔时再同步 `VIBELO_RECOMMENDATION_MODEL_DIR`。

### 8.1 固定执行顺序

仓库已经提供三套操作工具：

- [`ops/public/README.md`](../ops/public/README.md)：安全生成 `.env.public`，并在 ECS 做只读预检。
- [`ops/migration/mysql/README.md`](../ops/migration/mysql/README.md)：生成一致性快照、在本机 MySQL 8.0.36 完整恢复演练、导入空 RDS 并逐表精确验收。
- [`ops/migration/minio/README.md`](../ops/migration/minio/README.md)：通过 SSH 回环隧道把本机 MinIO 直接流式同步到 ECS，并做全量 key/size 与分层 SHA256 抽样校验。

必须按以下顺序执行：

1. 在 ECS 完成第 6.2、6.3 节，确认 `/data`、Docker Root 和 containerd root 都已经落在 160 GB 数据盘。
2. 在 RDS 控制台创建标准账号 `vibelo_app`，只授权 `rangwaz_image_dev` 读写；保留高权限账号仅用于一次性导入，不使用 `dms_user_*`。
3. 拉取最新代码，在 ECS 仓库根目录执行：

   ```bash
   bash ops/public/configure-rds-env.sh \
     --sms-sign-name '你的短信签名' \
     --sms-template-code '你的模板代码'

   sudo bash ops/public/preflight.sh
   ```

   配置脚本会交互询问真实公网 origin；不能把“你的ECS公网IP”或
   “你的正式域名”原样当成配置值。它只在终端静默读取密码和
   AccessKey；预检只读，不构建、不拉取、不启动容器。存在任何 `[失败]`
   时不要继续。

4. 进入统一维护窗口，同时停止后端、数据库导入/标签/训练发布任务，以及所有上传、删除和其他 MinIO 写入方；从这一步开始一直冻结到第 7 步 MinIO 独立验证结束，确保数据库对象 key 与对象存储处于同一个一致性窗口。按 MySQL 迁移手册运行 `Export-MySqlSnapshot.ps1`，再用 `Test-MySql80Restore.ps1` 完成 MySQL 8.0.36 恢复演练。只有得到同一前缀的七个文件并出现 `*.restore-tested.json` 才允许上传。
5. 把七个 MySQL 快照文件复制到 ECS 的 `/data/migration/mysql/`。确认 RDS 目标库仍严格为空，然后运行 `import-mysql-snapshot-to-rds.sh`。脚本会分别静默读取一次性迁移账号和 `vibelo_app` 密码，并在导入后比较表集合、逐表精确行数、Flyway 与所有数据库对象。
6. RDS 验收通过后，把固定的 MinIO 与 `mc` 离线文件上传到
   `/data/migration/minio/`，再用仓库门禁脚本准备并只启动 MinIO。这不会联网
   拉取或构建业务镜像：

   ```bash
   cd /opt/vibelo
   chmod 700 /data/migration/minio
   chmod 600 /data/migration/minio/*
   sudo bash ops/migration/minio/prepare-minio-target.sh
   sudo bash ops/migration/minio/start-minio-target.sh
   ```

   准备脚本会校验文件 SHA256、OCI `linux/amd64` manifest/config/layer、
   `/data` 至少 101 GiB 可用空间与 200 万 inode、回环端口、Compose 项目名、
   1 GiB MinIO 内存上限和目标卷不存在；启动脚本内部固定使用
   `--pull never --no-build --no-deps`，并证明项目中只有 `minio` 在运行。

   如果首次启动已经创建容器，但 SSH 中断或后置验收尚未完成，不要删除
   容器或数据卷，改用严格的只读验收：

   ```bash
   sudo bash ops/migration/minio/start-minio-target.sh --verify-existing
   ```

   该模式不会启动、重启、重建或删除任何容器/数据卷；只有容器身份、
   Compose 配置哈希、固定镜像、健康状态、回环端口与数据卷落点全部通过，
   才允许进入下一步。

7. 在 Windows 建立只监听 ECS `127.0.0.1:19090` 的 SSH 反向隧道。按 MinIO 迁移手册依次运行：

   ```bash
   bash ops/migration/minio/minio-migrate.sh --bucket rangwaz-media

   bash ops/migration/minio/minio-validate.sh \
     --bucket rangwaz-media \
     --sample-count 1000 \
     --audit-dir /root/minio-audit/validate-01
   ```

   不要在安全组开放 9000、9001 或 19090。只有源清单在迁移前后未变化、对象数和总字节完全相同、全量 key/size 无差异、SHA256 抽样零失败，才关闭隧道并进入应用发布。

8. 保持后端停止，先保存 RDS 与 MinIO 验收日志。最后按第 9 节决定是否构建应用镜像并启动公网服务。

RDS 目标库必须在导入前保持为空。MySQL DDL 无法整体回滚；导入开始后若失败，应重建或清空业务库并从同一快照重新执行，不能在半成品库上继续导入。Windows 源 MinIO 在公网读取验收、备份和稳定观察期结束前不要删除。

### 8.2 当前数据量与磁盘门槛

2026-07-28 本机只读盘点结果：

- MySQL：`126,945` 张已发布图片、`1,670,881` 条图片标签关系、`8,609` 条行为；逻辑表约 `787 MiB`，数据卷约 `1.3 GiB`。
- 业务 MinIO `rangwaz-media`：`317,076` 个对象，共 `70,349,795,919` 字节，约 `65.5 GiB`。
- 40 GB 系统盘当前约有 `30 GiB` 可用，不能容纳完整 MinIO、Docker 镜像、构建缓存和 Elasticsearch 索引。
- 新购 160 GB 数据盘在 ext4 格式化后约显示为 `149 GiB`；放入当前 `65.5 GiB` MinIO 对象后，理论上还剩约 `83 GiB`，尚未扣除文件系统预留、Docker 镜像、构建缓存、日志、Kafka 和 Elasticsearch 数据。

结论是：160 GB 数据盘足够当前首发和一段时间的低增长运行，前提是按 6.2、6.3 节把它挂载到 `/data`，并同时迁移 Docker `data-root` 与 containerd 数据目录。RDS 已接管 MySQL 后，ECS 不再承担数据库数据盘压力；但当前容量不适合同时保留两份 65.5 GiB 媒体副本，也不适合在同机运行 Milvus 或模型训练。

上线后给 `/data` 设置容量告警：使用率达到 70% 时评估增长，达到 80% 前必须扩容或迁移 OSS。全量迁移时直接从源 MinIO 流式同步到目标 MinIO，不要先在数据盘生成完整中间包。系统盘只保留操作系统、项目源码和少量系统日志。

迁移阶段只启动目标 MinIO，不提前启动 Redis、Elasticsearch、Kafka 或应用容器：

```bash
sudo bash ops/migration/minio/prepare-minio-target.sh
sudo bash ops/migration/minio/start-minio-target.sh
```

先把 MySQL 完整备份（包括表结构、业务数据和 `flyway_schema_history`）恢复到 RDS，并把 MinIO 数据直接同步到数据盘中的目标卷；确认 RDS 行数、MinIO 对象数和抽样图片都无误后再启动其余服务及应用。当前 Flyway 迁移依赖已有基础表，不能把刚创建的空库直接交给后端自动初始化。

### 8.3 是否现在购买 OSS 或 CDN

阿里云的对象存储产品名是 **OSS**；“OBS”通常指其他云厂商的对象存储。云盘、OSS、CDN 解决的是三个不同问题：

- 云盘是挂载给单台 ECS 使用的块存储；需要格式化、挂载，并由 ECS/MinIO 自己管理数据。
- OSS 是托管对象存储，适合保存原图和缩略图，减少单台 ECS 或单块云盘故障带来的风险。
- CDN 缓存 OSS 或 ECS 回源的图片和前端静态资源，减少跨地域延迟、ECS 出网带宽和源站请求压力；它不是永久存储。

当前建议分三阶段执行：

1. **最快首发：暂不购买 OSS/CDN。** 使用“RDS + 160 GB 数据盘 + 本机 MinIO + Nginx Gateway”，先完成数据迁移、HTTPS 和功能验收。当前已关闭图片发布，媒体增长有限，这条路线改动最少。
2. **稳定运营：优先迁移 OSS。** 单 ECS 上的 MinIO 仍是单点。准备好对象存储适配层、私有 bucket、备份/校验和迁移脚本后，将 `rangwaz-media` 的 317,076 个对象迁入 OSS；保持数据库 object key 不变。迁移完成前不要删除 MinIO 数据。
3. **有域名和实际流量后启用 CDN。** CDN 可以先回源当前 ECS/Nginx，也可以在 OSS 迁移后直接回源 OSS。中国内地加速通常还需要已备案域名。私有 OSS bucket 应配置私有回源鉴权或签名 URL，不能为了接 CDN 把全部图片意外改成公开读。

如果现在直接购买 OSS/CDN，但应用仍只会访问 MinIO，它们不会自动生效；因此应先按当前首发路线上线，再把“存储适配、对象校验迁移、URL 切换与回滚、CDN 缓存规则”作为独立发布。OSS 按存储量、请求和流量计费，CDN 按流量或带宽计费，正式购买前再用实际图片访问量估算套餐。

阿里云官方参考：

- [Linux ECS 初始化不超过 2 TiB 的数据盘](https://help.aliyun.com/zh/ecs/user-guide/initialize-a-data-disk-whose-size-does-not-exceed-2-tib-on-a-linux-instance)
- [ECS 与 RDS MySQL 连接和网络配置](https://help.aliyun.com/zh/rds/apsaradb-rds-for-mysql/connections-and-networks/)
- [RDS MySQL 账号与权限](https://help.aliyun.com/en/rds/apsaradb-rds-for-mysql/account-or-permission/)
- [DMS 注册实例与自动创建账号说明](https://help.aliyun.com/en/dms/getting-started/register-an-apsaradb-instance)
- [OSS 使用 CDN 加速](https://help.aliyun.com/zh/oss/user-guide/cdn-acceleration)
- [Docker 29 containerd image store 的数据目录](https://docs.docker.com/engine/storage/containerd/)

## 9. 首次构建与发布

只有决定上线时执行：

```bash
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  config --quiet

docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --build
```

此命令会首次构建前端和后端项目镜像。当前开发阶段不要执行。

查看状态与日志：

```bash
docker compose --env-file .env.public -f infra/docker-compose.public.yml ps
docker compose --env-file .env.public -f infra/docker-compose.public.yml logs -f gateway
docker compose --env-file .env.public -f infra/docker-compose.public.yml logs -f backend
docker stats --no-stream
```

## 10. 上线验收

将 `example.com` 替换为真实域名：

```bash
curl -fsS https://example.com/gateway/health
curl -fsS https://example.com/api/actuator/health
curl -fsS "https://example.com/api/feed?page=1&pageSize=2"
```

还要人工确认：

1. 首页、详情、搜索、资料页与资料编辑页可用。
2. 手机验证码接口返回 JSON，不出现 `Invalid CORS request` 或 HTML。
3. 登录后刷新页面仍保持登录，后端日志能看到请求。
4. `/publish` 回到首页，直接调用 `POST /api/images` 返回 `PUBLISHING_DISABLED`。
5. Gateway 日志包含 upstream 地址、request id 和响应时间。
6. `docker stats --no-stream` 显示所有容器都没有触碰内存上限。
7. `/gateway/health` 只表示 Nginx 进程存活，还必须分别验证 `/` 与 `/api/actuator/health`。

## 11. 启用推荐与 Milvus

当前 7.1 GiB 主机不要执行本节命令。先升级到至少 16 GB 内存，或把 Milvus/模型服务迁移到独立服务器。资源满足后，才启动 Milvus profile：

```bash
docker compose --profile recommendation --env-file .env.public \
  -f infra/docker-compose.public.yml up -d
```

先在宿主机确认向量服务 8091、模型服务 8092 健康，再把：

```text
VECTOR_ENABLED=true
MODEL_RECALL_ENABLED=true
MODEL_RANKING_ENABLED=true
```

写入 `.env.public`，随后只重建/重启后端服务。模型版本注册中心、安全流水线和 Milvus 发布器的详细原理与命令见 README 的“学习型双塔召回”和 `docs/训练模型文档.md`。

## 12. 更新与回滚

更新应用前先记录 Git commit：

```bash
git rev-parse HEAD
git pull --ff-only
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --build frontend backend gateway
```

如果新版本异常，切回刚才记录的 commit，重新执行同一构建命令。数据库迁移必须保持向前兼容；发布前先备份 MySQL、MinIO 和推荐模型目录。

模型回滚不需要回滚整站：registry 会保留 `previous`，使用训练文档中的 rollback 命令交换 `current/previous`，在线模型服务检测 registry 修改后自动热加载。
