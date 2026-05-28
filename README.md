# RanGwaz

RanGwaz 是一个图片类网站。当前目标是先把中小型图片站的主链路做稳：图片入库、MinIO 存储、分类标签、搜索、详情、点赞收藏评论、用户主页。推荐系统和 Milvus 向量库后续单独接入。

## 当前架构

- 前端：`frontend`，React + Vite。
- 后端：`backend`，Spring Boot。
- 存储：MySQL + MinIO。
- 数据工具：`tools/import_images.py` 直接导入本地授权图片，`tools/auto_label_images.py` 调用本地视觉模型打标签。

核心内容只存一张主表：`images`。没有 `posts` 内容表，也不再双写图片 URL。

## 数据库说明

当前开发库 schema 在：

```text
backend/src/main/resources/db/schema.sql
```

主要表：

- `images`：图片内容核心表，保存作者、标题、描述、URL、缩略图、宽高、hash、互动计数、发布时间等。
- `categories` / `tags` / `image_tags`：分类、标签、图片标签关联。
- `image_topics` / `topics`：轻量话题。
- `comments` / `user_interactions` / `user_behaviors`：评论、点赞收藏、行为事件。
- `app_users` / `follows`：用户和关注。

后端启动不会自动清空数据库。`spring.sql.init.mode` 已设为 `never`。

## 本地启动

```powershell
docker compose -f infra/docker-compose.yml up -d
```

```powershell
cd backend
mvn spring-boot:run
```

```powershell
cd frontend
npm install
npm run dev
```

默认开发账号：

```text
mira / RanGwaz147..
```

## 导入图片

先安装依赖：

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

导入逻辑：

- 上传原图和缩略图到 MinIO。
- 直接写入 MySQL 的 `images` 表。
- 按 sha256 跳过重复图片。
- 点赞、收藏、评论、分享、浏览、热度全部从 0 开始。
- 如果检测到旧版 `posts + images` 表结构，会按新版 `schema.sql` 重建一次开发库。
- 如果已经是新版结构，不会清空已有数据。

## 自动打标签

导入后运行：

```powershell
python tools/auto_label_images.py
```

脚本读取 `tools/import_results.jsonl`，调用本地 Ollama 视觉模型，生成：

- `description`
- `categoryPath`
- typed tags

结果直接写入 `categories`、`tags`、`image_tags` 和 `images.main_category_id`。

默认模型是：

```text
qwen2.5vl:7b
```

这类视觉语言模型适合生成描述、主题、风格、颜色、场景、对象等标签。真正用于相似图片检索和推荐召回的高质量向量，后续再接 CLIP、SigLIP、Chinese-CLIP 或同类 embedding 模型写入 Milvus。
