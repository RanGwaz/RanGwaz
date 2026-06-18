# RanGwaz / Vibelo

RanGwaz 当前产品名是 Vibelo，目标是搭建一个类似 Pinterest 的图片内容与推荐系统平台。核心内容主表是 `images`，图片文件放 MinIO，业务数据放 MySQL，行为事件进入 Kafka，图片向量放 Milvus。

## 当前架构

- 前端：`frontend`，React + Vite。
- 后端：`backend`，Spring Boot + MyBatis。
- 中间件：MySQL、Redis、Kafka、MinIO、Milvus，统一由 `infra/docker-compose.yml` 启动。
- 数据工具：`tools/import_images.py` 导入授权图片，`tools/auto_label_images.py` 本地 GPU 打标签，`tools/vectorize_images.py` 本地 GPU 生成图片向量并写入 Milvus。

## 本地启动

所有中间件使用一个 compose 文件：

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

## 图片导入

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

推荐先在项目目录内创建本地 GPU Python 环境，依赖、缓存和模型都放在 `tools` 下，避免写到 C 盘：

```powershell
.\tools\setup_local_gpu.ps1
```

如果需要走本机 12000 代理，且想明确使用非 C 盘的 Python：

```powershell
.\tools\setup_local_gpu.ps1 -Python "D:\Python316\python.exe" -ProxyUrl "http://127.0.0.1:12000"
```

下载本地模型：

```powershell
.\tools\.venv\Scripts\python.exe tools\download_local_models.py
```

如果 Hugging Face 需要走本机 12000 代理，Ollama 模型已成功时可只续下向量模型：

```powershell
.\tools\.venv\Scripts\python.exe tools\download_local_models.py --skip-label --use-hf-proxy --hf-proxy-url http://127.0.0.1:12000
```

默认模型：

```text
打标签: qwen3-vl:8b                 -> tools/models/ollama
取向量: google/siglip2-base-patch16-224 -> tools/models/huggingface
```

批量打标签：

```powershell
.\tools\.venv\Scripts\python.exe tools\auto_label_images.py
```

如果本机显存/内存不够跑 Qwen-VL，用云端 OpenAI-compatible 视觉模型：

```powershell
.\tools\run_cloud_label.ps1 -InitConfig
# edit tools\cloud_label_config.local.ps1 and replace sk-your-api-key
.\tools\run_cloud_label.ps1
```

结果写入 `images.description`、`images.main_category_id`、`categories`、`tags` 和 `image_tags`。

## 图片向量与推荐召回

推荐依赖已由 `tools/setup_local_gpu.ps1` 安装到项目内虚拟环境。单独补装时也使用该虚拟环境：

```powershell
.\tools\.venv\Scripts\python.exe -m pip install -r tools\requirements_recommendation.txt
```

本地 GPU 生成图片向量：

```powershell
.\tools\.venv\Scripts\python.exe tools\vectorize_images.py
```

不要用 `G:\Anaconda\envs\DL\python.exe` 跑向量脚本；那个环境的 `transformers` 太旧，不认识 SigLIP2。

启动向量召回服务：

```powershell
.\tools\.venv\Scripts\python.exe tools\vector_recall_service.py
```

当前向量配置：

```text
model: google/siglip2-base-patch16-224
version: siglip2-base-p224-d512-v1
dimension: 512
collection: vibelo_image_vectors_siglip2_base_p224_d512
```

首页走推荐召回和排序，详情页周围数据优先走当前图片的向量相似召回，再用标签、分类、比例和热度做辅助排序。

更多数据处理和推荐链路说明见：

```text
docs/data-labeling-and-vectorization.md
```

## 手机号登录与短信

前端登录弹窗已支持手机号验证码登录。开发环境默认使用本地 mock 验证码，不会真实发送短信。

短信服务配置说明见：

```text
docs/sms-login.md
```

```java
Set-Location "H:\桌面\一坨屎\RanGwaz"
.\tools\.venv\Scripts\python.exe tools\vectorize_images.py
```
