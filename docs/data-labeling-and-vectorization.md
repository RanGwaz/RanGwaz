# Vibelo 数据处理与推荐系统文档

这份文档是当前唯一保留的项目文档，覆盖图片打标、向量重建、数据表职责和推荐链路。其它旧的分散文档已删除。

## 当前目标

Vibelo 的目标是图片类内容平台，不是简单标签站。分类、标签和主题用于解释、筛选、搜索、冷启动和辅助召回；真正的推荐主链路优先走图片向量、用户行为、多路召回和排序。

```text
图片入库 -> MinIO + MySQL images
图片描述/标签 -> 远端 GPU VLM -> MySQL categories/tags/image_tags/images.description
图片向量化 -> SigLIP2/后续微调模型 -> Milvus
行为采集 -> Kafka -> user_behaviors + feed_impressions
首页推荐 -> 多路召回 + 轻量排序
详情页相似 -> 当前图片向量相似 + 元数据相似
```

## 表职责

- `images`：唯一图片内容主表，保存图片 URL、缩略图、宽高、比例、hash、主分类、描述和真实互动计数。
- `categories`：稳定大类，全局唯一，当前脚本只写一层，不再写模型随机生成的多层分类树。
- `tags`：标签词典，`id` 映射是正常范式，不是问题。
- `image_tags`：图片和标签的多对多关系，保存置信度和来源。
- `topics` / `image_topics`：运营或模型聚类沉淀后的主题，不把每个 AI 标签直接塞进去；为空不是故障。
- `image_embeddings`：向量生成状态，记录模型名、版本、维度、Milvus collection 和状态，不保存向量本体。
- `user_behaviors`：Kafka 消费者异步写入的点击、浏览、点赞、收藏、评论、分享等行为。
- `feed_impressions`：Kafka 消费者异步写入的首页和详情页曝光日志。
- `recommendation_candidates`：后续准实时首页候选缓存。

## 远端 GPU 打标

本机 Ollama + `qwen2.5vl:7b` 只适合验证链路，不适合处理 3 万张图片。批量生产描述、分类和标签时，使用远端 GPU 上的 vLLM OpenAI-compatible 服务。

当前已跑通的远端模型：

```text
Qwen/Qwen2.5-VL-3B-Instruct
```

如果服务器不能访问 Hugging Face，先用 ModelScope 下载模型：

```bash
pip install -U modelscope

modelscope download \
  --model Qwen/Qwen2.5-VL-3B-Instruct \
  --local_dir /root/models/Qwen2.5-VL-3B-Instruct
```

启动 vLLM。当前服务器需要禁用 FlashInfer sampler，否则会出现 `FlashInfer requires GPUs with sm75 or higher`：

```bash
pkill -f "vllm serve" || true

nohup env VLLM_USE_FLASHINFER_SAMPLER=0 \
  VLLM_ATTENTION_BACKEND=FLASH_ATTN \
  vllm serve /root/models/Qwen2.5-VL-3B-Instruct \
  --served-model-name Qwen/Qwen2.5-VL-3B-Instruct \
  --host 0.0.0.0 \
  --port 6006 \
  --api-key VibeloGPU_20260606_QwenVL \
  --limit-mm-per-prompt '{"image": 1}' \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 4 \
  > vllm.log 2>&1 &
```

查看日志：

```bash
tail -f vllm.log
```

远程服务器本地测试：

```bash
curl -H "Authorization: Bearer VibeloGPU_20260606_QwenVL" \
  http://127.0.0.1:6006/v1/models
```

本机测试公网映射：

```powershell
Invoke-RestMethod `
  -Uri "https://u1040521-ba3c-2fe32904.westb.seetacloud.com:8443/v1/models" `
  -Headers @{Authorization="Bearer VibeloGPU_20260606_QwenVL"} |
  ConvertTo-Json -Depth 5
```

## 本机打标脚本

本机脚本直接读取 `tools/import_results.jsonl` 里的本地图片路径，请求远端 vLLM，然后直接写 MySQL。

确认 `tools/fast_label_images_openai_compatible.py` 常量：

```python
API_BASE_URL = "https://u1040521-ba3c-2fe32904.westb.seetacloud.com:8443/v1"
API_KEY = "VibeloGPU_20260606_QwenVL"
MODEL_NAME = "Qwen/Qwen2.5-VL-3B-Instruct"
MAX_WORKERS = 8
RELABEL_EXISTING = False
```

如果要把旧的低质量描述、分类和标签全部重做，把 `RELABEL_EXISTING` 改成 `True`。脚本会覆盖 `images.description`、`images.main_category_id`，并重建对应图片的 `image_tags`。

先测一张，不写数据库：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
G:\Anaconda\envs\DL\python.exe tools\test_fast_label_api.py
```

测试成功后全量写库：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
G:\Anaconda\envs\DL\python.exe tools\fast_label_images_openai_compatible.py
```

脚本会断点续跑。远端并发不稳或显存紧张时，把 `MAX_WORKERS` 降到 `4` 或 `2`。

## 向量重建

旧 CLIP 向量已清空，当前默认向量模型：

```text
model_name      = google/siglip2-giant-opt-patch16-384
vector_version  = siglip2-giant-p384-v1
dimension       = 1536
metric          = COSINE
index           = HNSW
collection      = vibelo_image_vectors_siglip2_giant_p384
```

推荐使用远端 GPU 生成向量。本机只负责读取图片、调用远端 embedding 服务，并写入本机 Milvus/MySQL。

远端服务器先下载 SigLIP2 Giant：

```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download google/siglip2-giant-opt-patch16-384 \
  --local-dir /root/models/siglip2-giant-opt-patch16-384 \
  --local-dir-use-symlinks False
```

把本机的 `tools/remote_siglip_embedding_service.py` 放到远端服务器 `/root/remote_siglip_embedding_service.py`，然后启动 6008 端口服务：

```bash
pkill -f "remote_siglip_embedding_service.py" || true

nohup python /root/remote_siglip_embedding_service.py \
  > siglip_embed.log 2>&1 &
```

查看日志：

```bash
tail -f siglip_embed.log
```

远程服务器本地测试：

```bash
curl -H "Authorization: Bearer VibeloGPU_20260606_SigLIP2" \
  http://127.0.0.1:6008/health
```

本机测试公网映射：

```powershell
Invoke-RestMethod `
  -Uri "https://uu1040521-ba3c-2fe32904.westb.seetacloud.com:8443/health" `
  -Headers @{Authorization="Bearer VibeloGPU_20260606_SigLIP2"} |
  ConvertTo-Json -Depth 5
```

清空向量状态和 Milvus collection：

```powershell
G:\Anaconda\envs\DL\python.exe tools\reset_vectors.py
```

安装或更新依赖：

```powershell
G:\Anaconda\envs\DL\python.exe -m pip install -U -r tools\requirements_recommendation.txt
```

远端 GPU 生成向量并写入本机 Milvus/MySQL：

```powershell
G:\Anaconda\envs\DL\python.exe tools\vectorize_images_remote.py
```

如果只想在本机生成向量，使用旧的本机 worker：

```powershell
G:\Anaconda\envs\DL\python.exe tools\vectorize_images.py
```

启动向量召回服务：

```powershell
G:\Anaconda\envs\DL\python.exe tools\vector_recall_service.py
```

SigLIP2 Giant 不适合在当前本机 CPU 上完整跑 3 万张。远端服务建议使用 `6008`，不要和 Qwen2.5-VL 打标服务的 `6006` 混用。

## 推荐链路

首页不是找相似图，而是个性化推荐。当前首页多路召回包括：

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

1. 积累曝光、点击、点赞、收藏、评论、停留等行为数据。
2. 构建训练样本，包括用户特征、图片特征、上下文特征和真实反馈。
3. 训练双塔召回模型或用户兴趣向量模型，替换“最近正反馈图片平均向量”。
4. 训练排序模型，把当前工程版粗排替换成模型排序。
5. 将 `recommendation_candidates` 升级成准实时候选缓存，Redis 做在线缓存。
