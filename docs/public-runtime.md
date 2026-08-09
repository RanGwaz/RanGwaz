# 公网运行清单

## 登录 CORS

后端启动时把前端的真实来源写成精确白名单：

```text
APP_WEB_ALLOWED_ORIGIN_PATTERNS=https://www.example.com
```

项目只有 `application.yml` 一套运行配置，部署差异全部由环境变量覆盖，不再使用 `prod` profile。推荐将前端与接口部署为同源：浏览器访问 `https://www.example.com`，Nginx 把 `/api/**` 转发到后端池。前端构建时固定 `VITE_API_BASE=/api`。

## 首次上线

1. 复制根目录的 `.env.public.example` 到服务器的密钥管理或未纳入 Git 的环境文件，填写 RDS、MinIO、令牌与短信等必填项。
2. `APP_AUTH_TOKEN_SECRET` 至少 32 个随机字符。升级后旧的无签名 token 会失效，用户重新登录一次即可。
3. `APP_MODERATION_TOKEN` 使用另一份至少 32 个随机字符的秘密，不能复用登录签名密钥；它只用于人工审核接口。
4. 真实短信参数必须完整；公网 Compose 显式设置 `APP_SMS_MOCK=false`。
5. 公网 Compose 同时固定 `APP_FEATURE_PUBLISHING_ENABLED=false`、`APP_FEATURE_MEDIA_UPLOAD_ENABLED=false`；前端也在构建时隐藏个人图片上传入口，昵称和简介编辑不受影响。
6. 公网业务库使用同 VPC 的 RDS MySQL 内网地址，并只在白名单中放行 ECS 私网 IP；Redis、Kafka、Milvus、MinIO、Elasticsearch 和 Python 内部服务只监听本机或内网，不开放公网端口。
7. 为推荐模型准备持久化目录，并让训练、索引发布与在线服务共用同一个 `VIBELO_RECOMMENDATION_MODEL_DIR`。
8. 推荐服务可以延后启用；首次上线保持 `VECTOR_ENABLED=false`、`MODEL_RECALL_ENABLED=false`，先由数据库 fallback 收集真实行为。
9. 当前 7.1 GiB 首发服务器使用 `infra/docker-compose.public.yml` 启动 Nginx、单前端和单后端，不传任何 profile；Compose 内置 MySQL 仅保留在 `local-database` profile，Milvus 仅保留在 `recommendation` profile，首发都不启用。
10. 对公网只开放 80/443；数据库和模型端口由安全组拒绝公网访问。
11. 160 GB 数据盘挂载到 `/data` 后，将 Docker `data-root` 迁到 `/data/docker`，并将 Docker 29 的 containerd 数据目录迁到 `/data/containerd`，不要让 MinIO、Elasticsearch 和镜像继续占用 40 GB 系统盘。

## Nginx 网关与负载均衡

`infra/nginx/gateway.conf` 定义唯一公网入口：

- `/api/**` 代理到 `backend`，并透传真实 IP、协议和 request id。
- `/api/auth/sms-code` 使用独立的每 IP 频率限制。
- `/` 代理到无状态的 `frontend` 静态 SPA；Nginx upstream 保留以后水平扩容能力。
- `/media/object/**` 与 `/uploads/**` 仅用于兼容已有数据库中的旧媒体 URL。
- 数据库、中间件和后端没有公网端口；只有 `gateway` 映射 `PUBLIC_HTTP_PORT`。

本地只做配置校验，不构建镜像：

```powershell
$env:SPRING_DATASOURCE_URL="jdbc:mysql://rds-internal.example:3306/rangwaz_image_dev?sslMode=PREFERRED"
$env:SPRING_DATASOURCE_USERNAME="validation-only"
$env:SPRING_DATASOURCE_PASSWORD="validation-only"
$env:MINIO_ACCESS_KEY="validation-only"
$env:MINIO_SECRET_KEY="validation-only"
$env:APP_AUTH_TOKEN_SECRET="validation-only-token-secret-at-least-32-characters"
$env:APP_MODERATION_TOKEN="distinct-validation-moderation-token-32-characters"
docker compose -f infra/docker-compose.public.yml config --quiet
```

决定上线时先生成 `.env.public`，但不要立即启动全栈。本机必须先提交全部跟踪变更，并确认 `backend/`、`frontend/` 没有未跟踪构建输入，再以完整 40 位 Git SHA 和 `--pull=false --platform linux/amd64` 构建两个带 `org.opencontainers.image.revision` 标签的 commit 镜像；随后运行 `Export-PublicImageBundle.ps1`。固定 PyMySQL wheel 单独准备、单独上传。ECS 用 `import-public-image-bundle.sh` 验收归档，并在 `.env.public` 中固定：

```text
VIBELO_BACKEND_IMAGE=vibelo-public-backend:<完整的 40 位 Git SHA>
VIBELO_FRONTEND_IMAGE=vibelo-public-frontend:<完整的 40 位 Git SHA>
```

ECS 不运行 `docker build`、`up --build`、在线 `pip install` 或镜像拉取。导入镜像并离线安装 PyMySQL 后，严格按下列顺序发布；每条 `up` 都禁止构建和拉取，并显式指定服务：

```bash
sudo bash ops/migration/minio/start-minio-target.sh --verify-existing

docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --wait --no-build --pull never elasticsearch

# 此处必须完成 tools/reindex_search_es.py 的认证与 alias 原子发布，且退出码为 0。

docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --wait --no-build --pull never redis zookeeper kafka
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --wait --no-build --pull never --no-deps backend frontend
docker compose --env-file .env.public -f infra/docker-compose.public.yml \
  up -d --wait --no-build --pull never --no-deps gateway
```

完整构建、上传、镜像导入、搜索命令与更新/回滚流程见[公网部署与 Nginx 网关第 9、12 节](./公网部署与Nginx网关.md#9-首次构建与发布)。不要启用 `local-database`/`recommendation` profile，也不要执行 `docker compose down -v`。

数据盘初始化、Docker 数据目录迁移、RDS 内网配置和 OSS/CDN 采购顺序见 [公网部署与 Nginx 网关](./公网部署与Nginx网关.md)。

## 推荐链路

公网可以在没有双塔模型时先运行并收集真实行为：

- 基础图片向量：SigLIP2 的 512 维图片向量保存在原始 Milvus collection。
- 安全 fallback：按点赞、收藏、点击、浏览时长和时间衰减生成多兴趣向量，分别检索后融合去重。
- 学习召回：当真实数据和离线指标通过门禁后，序列用户塔与共享图片投影输出 256 维向量，检索版本化 learned Milvus collection。
- 多路融合：向量、关注、标签/主题和全局热度共同进入候选集。
- 精排：数据不足时使用可解释的冷启动排序；真实曝光和正反馈达到阈值后使用行为排序器。
- 曝光记账：仅图片进入可视区后上报，携带 `decisionId`、`eventId`、位置、召回来源和分数，数据库对事件去重。

在线服务只加载 registry 的 `current`，绝不加载 `candidate`。当前模型、checkpoint、checksum、维度或 learned collection 任一异常时会回退到多兴趣 SigLIP 召回；Java 侧的规则多路链路仍继续兜底。

## 模型目录持久化

示例：

```text
VIBELO_RECOMMENDATION_MODEL_DIR=D:\vibelo-data\recommendation-models
```

该目录至少包含 `two_tower/registry.json` 与 `two_tower/versions/<version>/`。它必须位于持久化磁盘或挂载卷，并与 Milvus 数据卷一起备份。不要删除 registry 中 `current`/`previous` 引用的模型版本或 collection。

## 双塔训练与发布

生产推荐使用安全流水线：

```powershell
.\tools\run_two_tower_pipeline.ps1 `
  -ModelDir "D:\vibelo-data\recommendation-models"
```

流水线按顺序执行：

1. 从真实行为构造 next-positive 样本并训练双塔；
2. 要求至少 50 个有效 actor、500 条样本，并检查 validation/test `recall@50`；
3. 仅在门禁通过时注册 `candidate`；
4. 读取 candidate 版本，构建完整 learned Milvus collection；
5. 校验 checksum、维度、实体数量和抽样向量范数；
6. promote 为 `current`，原 `current` 自动进入 `previous`。

任一步失败都会停止，线上 `current` 保持不变。流水线不使用 synthetic 数据、partial index、`--allow-unsafe` 或 `--rebuild`。完整手动命令、dry-run 和回滚方式见 [训练模型文档](./训练模型文档.md)。

`tools/train_recommendation_recall.py` 只调优启发式 fallback 权重，不是神经双塔训练脚本；不要把其 `recall_metadata.json` 当成模型 checkpoint。

## 定时任务

在每天低峰期运行一次安全流水线：

```text
程序: powershell.exe
参数: -NoProfile -ExecutionPolicy Bypass -File "G:\path\RanGwaz\tools\run_two_tower_pipeline.ps1" -ModelDir "D:\vibelo-data\recommendation-models"
起始位置: G:\path\RanGwaz
```

行为不足时任务会因门禁失败，这不是故障，也不会覆盖现网模型。继续收集真实曝光、点击、长浏览、点赞、收藏、评论和分享即可。启发式 fallback 与精排可独立更新：

```powershell
.\tools\.venv\Scripts\python.exe tools\train_recommendation_recall.py --mode auto --days 60
.\tools\.venv\Scripts\python.exe tools\train_recommendation_ranker.py --mode auto --days 45 --min-behavior-positives 200
```

## 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8092/health | ConvertTo-Json -Depth 8
```

启用学习召回后确认：

- `milvusReady=true`；
- `twoTowerLoaded=true`；
- `twoTowerVersion` 等于 registry 的 `current.version`；
- `twoTowerIndexCollection` 与 current 的 READY index 一致；
- `twoTowerLoadError` 为空。

没有 current 时 `twoTowerLoaded=false` 是允许的冷启动状态，但首页必须能通过 fallback 正常返回。上线监控至少覆盖推荐耗时、fallback 比例、CTR、详情到达率、长浏览率、收藏率和重复曝光率。

## 上线验收

- 预检 `OPTIONS /auth/sms-code` 对正确域名返回 2xx，对其他域名返回 403。
- 验证码只能使用一次，错误 5 次后失效，冷却时间内不能重复发送。
- 首页首屏接口耗时、图片首字节和推荐服务耗时有监控；推荐服务异常时仍能回退多路规则排序。
- `feed_impressions` 能看到真实可视曝光，`event_id` 无重复。
- 双塔已发布时，`POST /recall/home` 返回 `mode=trained-two-tower`、正确版本和 index collection。
- 临时停止 learned collection 后，首页仍可通过 fallback 返回内容。
- 首发时前端 `/publish` 重定向首页，`POST /api/images` 返回 `PUBLISHING_DISABLED`，且无需启动图片检测服务。
