# Vibelo 数据处理与推荐链路文档

这是当前唯一保留的项目数据文档，覆盖图片入库、打标签、向量化、Milvus 召回和后续推荐系统升级。

## 当前目标

Vibelo 是图片内容与推荐平台，核心不是简单标签站。标签、分类、描述用于搜索、解释、冷启动和辅助召回；真正的推荐主链路会逐步走图片向量、用户行为、多路召回、粗排和精排。

```text
图片入库 -> MinIO + MySQL images
图片描述/分类/标签 -> 远端 GPU VLM -> MySQL categories/tags/image_tags/images.description
图片向量化 -> SigLIP2 Giant + 512 维投影 -> Milvus
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

## 远端 GPU 打标签

当前使用远端 vLLM OpenAI-compatible 服务生成描述、分类和标签。

模型：

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

启动 vLLM。当前服务器需要禁用 FlashInfer sampler：

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

本机批量打标签：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
G:\Anaconda\envs\DL\python.exe tools\fast_label_images_openai_compatible.py
```

## 远端 GPU 向量化

当前默认向量配置：

```text
model_name      = google/siglip2-giant-opt-patch16-384
vector_version  = siglip2-giant-p384-d512-v1
dimension       = 512
metric          = COSINE
index           = HNSW
collection      = vibelo_image_vectors_siglip2_giant_p384_d512
```

说明：SigLIP2 Giant 原始视觉特征较强，但原始维度较高。当前服务会先提取强特征，再用固定随机投影降到 512 维并重新 L2 归一化。这样可以明显降低 Milvus 存储、传输和检索成本，同时保留足够支撑推荐召回的语义信息。

远端服务器先下载 SigLIP2 Giant：

```bash
export HF_ENDPOINT=https://hf-mirror.com
hf download google/siglip2-giant-opt-patch16-384 \
  --local-dir /root/models/siglip2-giant-opt-patch16-384
```

把本机脚本放到远端：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
scp -P 17270 .\tools\remote_siglip_embedding_service.py root@connect.westb.seetacloud.com:/root/remote_siglip_embedding_service.py
```

远端启动 6008 端口 embedding 服务：

```bash
pkill -f "remote_siglip_embedding_service.py" || true

nohup python /root/remote_siglip_embedding_service.py \
  > siglip_embed.log 2>&1 &

tail -f siglip_embed.log
```

远端本地测试：

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

清空旧向量状态和旧 Milvus collection：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
G:\Anaconda\envs\DL\python.exe tools\reset_vectors.py
```

生成 512 维向量并写入本机 Milvus/MySQL：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
G:\Anaconda\envs\DL\python.exe tools\vectorize_images_remote.py
```

启动向量召回服务：

```powershell
Set-Location 'H:\桌面\一坨屎\RanGwaz'
G:\Anaconda\envs\DL\python.exe tools\vector_recall_service.py
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
