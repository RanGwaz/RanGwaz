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
      MySQL / Redis / Kafka / MinIO / Elasticsearch
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
CONTENT_SAFETY_ENABLED=false
CONTENT_SAFETY_CLOUD_ENABLED=false
VECTOR_ENABLED=false
MODEL_RECALL_ENABLED=false
MODEL_RANKING_ENABLED=false
```

- 前端没有发布页面，旧 `/publish` 地址跳回首页。
- `POST /api/images` 返回统一 JSON 错误 `PUBLISHING_DISABLED`。
- 不启动 8093 图片检测服务。
- 推荐先使用数据库冷启动/fallback，继续收集曝光、点击、停留、点赞、收藏和评论。
- ES 启动慢或短暂故障不会再杀死后端；建索引会后台重试，搜索临时回退 MySQL。
- MySQL、Redis 和 Kafka 首次健康后才启动后端，避免数据库初始化失败、验证码不可用或首批行为数据丢失。
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
$env:MYSQL_ROOT_PASSWORD="validation-only"
$env:MYSQL_PASSWORD="validation-only"
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
- 公网 Compose 已给每个容器设置内存/PID 上限，所有容器的内存硬上限合计约 5.4 GiB，并给 Docker JSON 日志设置 `20m × 3` 轮转。
- Elasticsearch 固定使用 768 MiB JVM heap、1.5 GiB 容器上限，并禁止该容器使用 Swap。
- Ubuntu 26.04 LTS 是 Docker Engine 当前明确支持的发行版，避免继续承担 CentOS 7 已结束生命周期和旧内核带来的风险。
- 已安装 Docker Engine 29.6.2、Docker Compose 5.3.1，Docker 服务为 `active`，使用 `overlayfs`、systemd cgroup driver 和 cgroup v2。
- 4 GB swapfile、`vm.max_map_count=1048576` 和 `vm.swappiness=10` 均已生效。Swap 只用于承接瞬时峰值，不能代替内存扩容。

以下是新服务器已经执行过的初始化记录；重建服务器时按同样步骤操作。先更新系统并安装基础工具：

```bash
sudo apt update
sudo DEBIAN_FRONTEND=noninteractive apt upgrade -y
sudo apt install -y ca-certificates curl git
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

### 6.2 Elasticsearch 与 Swap 前置配置

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

### 6.3 安全组与 HTTPS

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

- `MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`
- `MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`
- `APP_AUTH_TOKEN_SECRET`：至少 32 个随机字符；以后扩容出的所有后端必须完全一致
- `ALIYUN_SMS_ACCESS_KEY_ID`、`ALIYUN_SMS_ACCESS_KEY_SECRET`
- `ALIYUN_SMS_SIGN_NAME`、`ALIYUN_SMS_TEMPLATE_CODE`
- `APP_WEB_ALLOWED_ORIGIN_PATTERNS`：真实 HTTPS 站点来源

`.env.public` 已被 `.gitignore` 排除，不要提交。项目不再使用 `application-prod.yml` 或 `SPRING_PROFILES_ACTIVE=prod`。

## 8. 迁移现有数据

公网 Compose 使用独立持久卷，不会自动读取本机开发 Compose 的卷。上线前至少迁移：

1. MySQL：导出当前 `rangwaz_image_dev`，在服务器 MySQL 初始化后恢复。
2. 业务 MinIO：同步 `rangwaz-media` bucket，数据库中的 object key 必须保持不变。
3. Elasticsearch：可以不搬，后端启动后重新建立索引。
4. Milvus：首次推荐服务关闭，可暂不搬；以后用原图向量脚本重建更稳妥。
5. 推荐模型目录：以后启用双塔时再同步 `VIBELO_RECOMMENDATION_MODEL_DIR`。

首次只启动数据服务时不构建项目镜像：

```bash
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d mysql redis elasticsearch zookeeper kafka minio
```

恢复 MySQL 和 MinIO 数据，确认无误后再启动应用。

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
