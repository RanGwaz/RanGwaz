# Vibelo 数据处理与推荐链路文档

这是当前唯一保留的项目数据文档，覆盖图片入库、打标签、向量化、Milvus 召回和后续推荐系统升级。

## 当前目标

Vibelo 是图片内容与推荐平台，核心不是简单标签站。标签、分类、描述用于搜索、解释、冷启动和辅助召回；真正的推荐主链路会逐步走图片向量、用户行为、多路召回、粗排和精排。

```text
图片入库 -> MinIO + MySQL images
图片描述/分类/标签 -> 本地 GPU VLM -> MySQL categories/tags/image_tags/images.description
图片向量化 -> SigLIP2 Base + 512 维投影 -> Milvus
用户行为 -> Kafka -> user_behaviors + feed_impressions
首页推荐 -> 多路召回 + 轻量排序
详情页相似 -> 当前图片向量相似 + 标签/分类辅助相似
```

## 表职责

- `images`：唯一图片内容主表，保存图片 URL、缩略图、宽高、比例、hash、主分类、描述和真实互动计数。
- `categories`：稳定分类词典，分类名应全局规范，不要让模型输出的脏分类直接无限膨胀。
- `tags`：标签词典，`id` 映射是正常范式，不是问题。
- `image_tags`：图片和标签的多对多关系，保存置信度和来源。
- `topics` / `image_topics`：后续用于运营主题或模型聚类主题，暂时为空不是故障。
- `image_embeddings`：向量生成状态表，只记录模型名、版本、维度、Milvus collection 和状态，不保存向量本体。
- `user_behaviors`：Kafka 消费后异步写入的点击、浏览、点赞、收藏、评论、分享等行为。
- `feed_impressions`：Kafka 消费后异步写入的首页和详情页曝光日志。
- `recommendation_candidates`：后续准实时首页候选缓存。

## 本地 GPU 环境

所有大文件默认放在项目目录内：

```text
tools/.venv                  Python 虚拟环境
tools/.pip-cache             pip 缓存
tools/models/ollama          Ollama 标签模型
tools/models/huggingface     Hugging Face 向量模型
tools/models/torch           Torch 缓存
```

初始化环境：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
.\tools\setup_local_gpu.ps1
```

如果需要走本机 12000 代理，且想明确使用非 C 盘 Python：

```powershell
.\tools\setup_local_gpu.ps1 -Python "D:\Python316\python.exe" -ProxyUrl "http://127.0.0.1:12000"
```

如果本机 CUDA/PyTorch 需要其它 wheel 源，可以指定：

```powershell
.\tools\setup_local_gpu.ps1 -TorchIndexUrl "https://download.pytorch.org/whl/cu124"
```

下载默认模型：

```powershell
.\tools\.venv\Scripts\python.exe tools\download_local_models.py
```

如果 Hugging Face 访问慢，可以临时使用镜像：

```powershell
$env:HF_ENDPOINT="https://hf-mirror.com"
.\tools\.venv\Scripts\python.exe tools\download_local_models.py --skip-label
```

如果你开的是本机代理，端口是 12000，推荐这样续下向量模型：

```powershell
.\tools\.venv\Scripts\python.exe tools\download_local_models.py --skip-label --use-hf-proxy --hf-proxy-url http://127.0.0.1:12000
```

注意：如果 Ollama 已经提前启动，它可能还在使用旧的模型目录。为了确保模型不写到 C 盘，先关闭已运行的 Ollama，再运行下载脚本或 `tools/auto_label_images.py`，让脚本带着 `OLLAMA_MODELS=tools/models/ollama` 启动 Ollama。

## 本地 GPU 打标签

默认标签模型：

```text
qwen3-vl:8b
```

这是当前本地打标签的优先选择：视觉理解、中文输出和结构化 JSON 能力比小模型更稳，Ollama 运行也比自己维护 vLLM 省事。显存紧张时可临时降级：

```powershell
$env:VIBELO_LABEL_MODEL="qwen2.5vl:7b"
.\tools\.venv\Scripts\python.exe tools\download_local_models.py --skip-embedding
```

批量打标签：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
.\tools\.venv\Scripts\python.exe tools\auto_label_images.py
```

脚本会读取 `tools/import_results.jsonl` 里的本地图片路径，生成描述、主分类和标签，写入：

```text
images.description
images.main_category_id
categories
tags
image_tags
```

常用调参：

```powershell
$env:VIBELO_LABEL_LIMIT="200"              # 先试跑 200 张；0 表示不限
$env:VIBELO_LABEL_IMAGE_MAX_SIDE="1024"   # 更大更准但更慢
$env:VIBELO_LABEL_TIMEOUT_SECONDS="300"
```

脚本支持断点续跑，结果写入 `tools/auto_label_results.jsonl`。默认会跳过数据库中已经有描述或标签的图片。

## 云端打标签

如果本机 GTX 1650 显存/内存不足以跑 Qwen-VL，本地打标签可以换成云端视觉模型。脚本是 OpenAI-compatible 写法，不绑定某一家服务商；只要服务提供 `/chat/completions` 且支持 `image_url` 输入即可。

常见配置示例：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
.\tools\run_cloud_label.ps1 -InitConfig
# edit tools\cloud_label_config.local.ps1 and replace sk-your-api-key
.\tools\run_cloud_label.ps1
```

如果云端 API 也需要走本机代理：

```powershell
$env:VIBELO_CLOUD_LABEL_PROXY_URL="http://127.0.0.1:12000"
```

脚本结果写入 `tools/cloud_label_results.jsonl`，并和本地脚本一样写回：

```text
images.description
images.main_category_id
categories
tags
image_tags
```

建议先用 `VIBELO_LABEL_LIMIT=20` 小批量试跑，确认标签质量和费用后再放开。

## 本地 GPU 向量化

当前默认向量配置：

```text
model_name      = google/siglip2-base-patch16-224
vector_version  = siglip2-base-p224-d512-v1
dimension       = 512
metric          = COSINE
index           = HNSW
collection      = vibelo_image_vectors_siglip2_base_p224_d512
```

说明：GTX 1650 只有 4GB 显存，默认使用 SigLIP2 Base。它比 Giant 更适合本机批处理，显存占用低很多；脚本仍会用固定随机投影降到 512 维并重新 L2 归一化，降低 Milvus 存储和检索成本。

下载脚本会把 SigLIP2 Base 放到：

```text
tools/models/huggingface/google__siglip2-base-patch16-224
```

如果以后换到 8GB/12GB 以上显卡，可以手动切回 Giant：

```powershell
$env:VIBELO_EMBED_MODEL="google/siglip2-giant-opt-patch16-384"
$env:VIBELO_EMBED_VECTOR_VERSION="siglip2-giant-p384-d512-v1"
$env:VIBELO_MILVUS_COLLECTION="vibelo_image_vectors_siglip2_giant_p384_d512"
```

清空旧向量状态和旧 Milvus collection：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
.\tools\.venv\Scripts\python.exe tools\reset_vectors.py
```

生成 512 维向量并写入本机 Milvus/MySQL：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
.\tools\.venv\Scripts\python.exe tools\vectorize_images.py
```

注意：不要用 `G:\Anaconda\envs\DL\python.exe` 跑向量脚本。那个环境的 `transformers` 是 4.30.2，不能识别 SigLIP2；请使用项目内 `tools\.venv`。

常用调参：

```powershell
$env:VIBELO_EMBED_LIMIT="1000"       # 先试跑 1000 张；0 表示不限
$env:VIBELO_EMBED_BATCH_SIZE="8"     # 显存够可调大，OOM 就调小
$env:VIBELO_EMBED_DEVICE="cuda"      # 默认 auto
$env:VIBELO_USE_HF_PROXY="1"         # 如果本地模型缺文件，需要临时联网补下载
$env:VIBELO_HF_PROXY_URL="http://127.0.0.1:12000"
```

启动向量召回服务：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
.\tools\.venv\Scripts\python.exe tools\vector_recall_service.py
```

## 推荐链路

首页推荐不是简单找相似图。当前工程版多路召回包括：

- 向量兴趣召回：用用户最近正反馈图片的平均向量请求 Milvus。
- 标签兴趣召回：用用户正反馈图片的 `image_tags` 反推兴趣标签，再找同标签图片。
- 话题兴趣召回：用 `image_topics` 找用户看过或喜欢过的话题图片。
- 分类兴趣召回：用 `main_category_id` 找同分类候选。
- 关注作者召回：找用户关注作者的新图。
- 全站冷启动召回：按真实热度、新鲜度和元数据质量补齐候选。

当前工程版排序：

```text
最终分 = 召回路权重 + 多路命中奖励 + 真实互动热度 + 新鲜度 + 元数据质量 - 最近曝光惩罚
```

详情页周围图片围绕当前图片本身：

- 主召回：当前图片向量从 Milvus 找视觉相似图片。
- 辅助召回：标签、分类、比例、热度等 MySQL 元数据相似。
- 编排：统一打分、去重、排序后返回前端。

## 后续升级

1. 累积曝光、点击、点赞、收藏、评论、停留等行为数据。
2. 构建训练样本，包括用户特征、图片特征、上下文特征和真实反馈。
3. 训练双塔召回模型或用户兴趣向量模型，替换“最近正反馈图片平均向量”。
4. 训练排序模型，把当前工程版粗排替换成模型排序。
5. 将 `recommendation_candidates` 升级成准实时候选缓存，Redis 做在线缓存。
