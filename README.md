# RanGwaz / Vibelo

RanGwaz 是一个图片类网站，当前目标是搭建一个类似 Pinterest 的图片内容与推荐系统平台。核心主表是 `images`，图片文件放 MinIO，业务数据放 MySQL，行为事件进入 Kafka，图片向量放 Milvus。

## 当前架构

- 前端：`frontend`，React + Vite。
- 后端：`backend`，Spring Boot + MyBatis。
- 中间件：MySQL、Redis、Kafka、MinIO、Milvus，统一由 `infra/docker-compose.yml` 启动。
- 数据工具：`tools/import_images.py` 导入授权图片，`tools/auto_label_images.py` 调用本地视觉模型打标签，`tools/vectorize_images.py` 生成图片向量写入 Milvus。

## 本地启动

所有中间件只使用一个 compose 文件：

```powershell
docker compose -f infra/docker-compose.yml up -d
```

后端：

```powershell
cd backend
mvn spring-boot:run
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

默认开发账号：

```text
mira / RanGwaz147..
```

## 中间件端口

- MySQL：`localhost:3306`
- Redis：`localhost:6379`
- Kafka：`localhost:9092`
- 业务 MinIO：`localhost:9000`，控制台 `localhost:9001`
- Milvus：`localhost:19530`
- Milvus 内部 MinIO：`localhost:19000`，控制台 `localhost:19001`

业务 MinIO 和 Milvus 内部 MinIO 是两个容器，职责不同，但都在同一个 compose 文件里。

## 数据库

开发库 schema：

```text
backend/src/main/resources/db/schema.sql
```

字段变更和新增表通过 Flyway SQL migration 管理：

```text
backend/src/main/resources/db/migration
```

后端不会自动清空数据库，`spring.sql.init.mode` 已设为 `never`。

## 行为打点

曝光、点击、浏览、点赞、收藏、评论等行为先写入 Kafka topic：

```text
vibelo.user-behaviors
```

后端消费者再异步落库到：

- `user_behaviors`
- `feed_impressions`

点赞、收藏、评论这类强业务状态仍然同步更新计数，行为日志异步写入，避免前端打点拖慢页面。

## 导入图片

安装依赖：

```powershell
python -m pip install pymysql minio pycryptodome pillow
```

运行：

```powershell
python tools/import_images.py
```

脚本默认读取：

```text
tools/downloaded_dataset/images
```

## 自动打标签

```powershell
python tools/auto_label_images.py
```

默认调用本地 Ollama 视觉模型：

```text
qwen2.5vl:7b
```

结果写入 `categories`、`tags`、`image_tags` 和 `images.main_category_id`。

## 图片向量与推荐召回

安装推荐依赖：

```powershell
python -m pip install -r tools/requirements_recommendation.txt
```

生成图片向量：

```powershell
python tools/vectorize_images.py
```

启动向量召回服务：

```powershell
python tools/vector_recall_service.py
```

当前向量模型：

```text
google/siglip2-giant-opt-patch16-384
```

首页走推荐召回和排序，详情页周围数据走相似图片召回。
