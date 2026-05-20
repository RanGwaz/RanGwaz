# RanGwaz 推荐系统分阶段路线

## x-algorithm 对 RanGwaz 的启发

`x-algorithm` 的价值不是直接复用代码，而是复用推荐系统的分层方式：

- Home Mixer：推荐编排层，负责把用户上下文、候选来源、过滤、打分、排序和副作用串起来。
- Thunder：关注流候选层，负责快速拿到关注作者的最新内容。
- Phoenix Retrieval：向量召回层，负责从全站图片池里找到可能感兴趣的内容。
- Phoenix Ranking：精排层，负责预测点赞、收藏、点击、停留、关注作者等多目标概率。
- Grox：内容理解层，负责图片/文本 embedding、分类、安全审核、质量评分。
- Candidate Pipeline：流水线抽象，定义 source、hydrator、filter、scorer、selector、side effect。

RanGwaz 当前是图片网站，不需要一开始就做完整大模型链路。应该先把数据资产、行为事件、媒体存储和候选流水线做稳，再逐步替换打分模块。

## 阶段 1：媒体资产和行为数据打底

目标：让所有图片都进入统一对象存储，并沉淀推荐必需的数据。

- 用户发布图片直接写入 MinIO。
- 上传时生成原图对象和缩略图对象。
- `post_assets` 保留 object key、原图 URL、缩略图 URL、宽高。
- `user_behaviors` 记录曝光、点击、详情浏览、分享、停留等行为。
- `feed_impressions` 记录每次推荐响应实际展示的 post、source、rank、score。

本阶段不做复杂模型，只保证后续训练和召回需要的数据不会缺。

## 阶段 2：合规数据导入

目标：建立可持续的数据导入通道。

- 先做通用导入器：输入合法图片 URL 或数据集清单，下载到本地临时目录，上传 MinIO，写入帖子和素材表。
- 图片保留 `source_platform`、`source_url`、`license_type`、`external_id`，避免后续版权和去重混乱。
- 对 Pinterest 这类平台，不做绕过登录、绕过反爬、批量规避限制的抓取；优先使用自有素材、授权数据、公开许可数据集或人工导出的合法清单。

## 阶段 3：RanGwaz Home Mixer

目标：把当前 `FeedService` 从单 SQL 热度流改成推荐编排模块。

推荐接口内部拆成：

- Query Hydrator：加载用户关注、最近行为、已曝光内容、兴趣主题。
- Source：热门、新内容、关注作者、相似图片、主题候选。
- Hydrator：补齐作者、互动数、素材、主题、质量分。
- Filter：去重、过滤已看、过滤自己、过滤不可见内容。
- Scorer：新鲜度、互动热度、主题匹配、作者多样性。
- Selector：按分数排序并限制同作者密度。
- Side Effect：写入曝光、已服务历史和推荐日志。

## 阶段 4：向量召回和内容理解

目标：接近 Phoenix/Grox 的核心能力。

- 为图片生成 visual embedding。
- 为标题、描述、话题生成 text embedding。
- 建立 `post_recommendation_features` 的 embedding 引用和质量分。
- 引入向量索引服务，先可以用轻量方案，后续再迁移到 Milvus、Qdrant、Elasticsearch vector 或 pgvector。
- 详情页相似推荐从主题 SQL 升级为向量召回。

## 阶段 5：多目标排序

目标：把规则分数替换成可学习排序。

- 训练样本来自 `user_behaviors` 和 `feed_impressions`。
- 标签包括点击、详情浏览、点赞、收藏、评论、关注作者、快速划走。
- 第一版可以用轻量模型或离线打分表。
- 后续再接入 Phoenix 风格的 retrieval + ranking 双阶段模型。

## 当前实现状态

本阶段已开始落地 MinIO 媒体资产层。下一步适合做“合规图片导入器”，先支持从本地 JSON/CSV 清单导入图片，而不是直接写复杂爬虫。
