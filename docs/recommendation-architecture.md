# Vibelo 深度学习推荐架构

Vibelo 的推荐平台采用图片类内容站常见的稳定架构：业务数据放 MySQL，图片文件放 MinIO，图片向量放 Milvus，在线后端负责编排召回和轻量排序，离线/准实时 worker 负责模型计算。

## 总体链路

```text
图片入库 -> MinIO + MySQL images
图片向量化 -> SigLIP2/后续微调模型 -> Milvus
行为采集 -> Kafka -> user_behaviors + feed_impressions
在线召回 -> vector_recall_service.py
业务补全 -> MySQL images/users/interactions
排序编排 -> FeedServiceImpl
前端展示 -> 首页流 / 详情页相似内容
```

## 两个场景必须分开

### 首页：推荐场景

首页不是简单找相似图，而是个性化推荐。

当前实现：

- 登录用户：读取最近正反馈图片，生成用户兴趣向量，向 Milvus 召回候选。
- 召回后：Java 后端根据向量分数、真实互动热度、新鲜度、元数据完整度做轻量排序。
- 游客或缺少行为：使用真实热度、新鲜度和质量字段做冷启动。

后续可扩展：

- 多路召回：用户兴趣向量、热门新图、关注作者、搜索词相关图。
- 排序模型：把用户特征、图片特征、上下文特征喂给 ranker。
- 缓存：`recommendation_candidates` 存准实时首页候选。

### 详情页：相似内容场景

详情页周围的图片应该围绕当前图片本身，不应该走首页推荐逻辑。

当前实现：

- 主召回：用当前图片向量从 Milvus 找视觉相似图片。
- 辅助召回：用标签、分类、比例、热度从 MySQL 找语义相似图片。
- 编排：向量相似和标签相似统一打分、去重、排序，再返回给前端。

这样即使某些图片还没打完标签，只要已经向量化，也能找到相似内容；反过来，如果向量服务暂时不可用，标签/分类仍然能提供相似补充。

## 表职责

- `images`：唯一图片内容主表。
- `image_embeddings`：图片向量生成状态，记录 `model_name`、`vector_version`、`vector_dimension`、`milvus_collection`、`milvus_pk`、`status`，不保存向量本体。
- `user_behaviors`：Kafka 消费者异步写入的点击、浏览、点赞、收藏、评论、分享等行为日志。
- `feed_impressions`：Kafka 消费者异步写入的首页和详情页相关推荐曝光日志。
- `recommendation_candidates`：后续可用于准实时首页候选缓存和调试。
- `user_interest_snapshots`：后续可保存用户兴趣向量摘要或兴趣 JSON。
- `categories`、`tags`、`image_tags`：解释、筛选、搜索和相似内容辅助。

## 模型版本

当前默认使用更强的视觉 embedding 模型：

```text
model_name      = google/siglip2-giant-opt-patch16-384
vector_version  = siglip2-giant-p384-v1
dimension       = 1536
metric          = COSINE
index           = HNSW
collection      = vibelo_image_vectors_siglip2_giant_p384
```

旧的 CLIP baseline 可以保留在数据库历史状态里，但在线召回服务默认只读新的 SigLIP2 collection。因为 `image_embeddings` 使用 `image_id + model_name + vector_version` 作为主键，换模型不会破坏旧向量状态。

## 运行模块

所有中间件：

```powershell
docker compose -f infra\docker-compose.yml up -d
```

向量化 worker：

```powershell
python tools\vectorize_images.py
```

向量召回服务：

```powershell
python tools\vector_recall_service.py
```

Java 后端：

- `/feed`：首页推荐，优先走用户兴趣向量召回和轻量排序。
- `/feed/images/{imageId}/similar`：详情页相似内容，混合向量相似和标签相似。
- `/behaviors/batch`：批量写曝光、点击等行为，为后续训练和排序准备数据。

## 后续升级

1. 训练用户侧向量模型，替代当前“最近正反馈图片平均向量”。
2. 增加文本向量，把标题、描述、标签、搜索词接入同一召回体系。
3. 增加 ranker，把 Milvus 召回结果按用户、图片、上下文特征重排。
4. 把 `recommendation_candidates` 升级成准实时首页候选缓存，Redis 做在线缓存。
5. 基于曝光和点击日志构建正负样本，做离线评估和线上 A/B。
