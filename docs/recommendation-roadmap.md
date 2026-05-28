# RanGwaz 推荐系统分阶段路线

当前先做中小型图片站的稳定主链路，推荐系统后置。

## 阶段 1：图片站基础

目标：图片可以稳定上传、导入、浏览、搜索和互动。

- `images` 是唯一图片内容核心表。
- 正式发布接口写入 MinIO 和 `images`。
- 开发导入脚本直接写入 MinIO 和 `images`。
- 不再使用 `posts` 内容表。
- 点赞、收藏、评论、分享、浏览、热度全部来自真实交互，默认从 0 开始。

## 阶段 2：分类、标签、属性

目标：图片不要只靠文件夹分类，而是形成可搜索、可组合的标签体系。

- 分类：`categories`，支持多级树。
- 标签：`tags`，保存主题、风格、颜色、场景、对象、设备等。
- 图片标签：`image_tags`，保存 `confidence` 和 `source`。
- 图片自身属性：宽高、比例、文件大小、hash、主分类等保存在 `images`。

Java 后端不硬编码分类树和标签值。分类和标签来自模型输出、脚本规则或后续人工审核。

## 阶段 3：开发数据导入

目标：把授权图片批量导入开发环境。

脚本：

```text
tools/import_images.py
```

行为：

- 默认读取 `tools/downloaded_dataset/images`。
- 上传原图和缩略图到 MinIO。
- 直接写入 `images`。
- 按 sha256 去重。
- 如果检测到旧版表结构，自动重建开发库一次。
- 如果已经是新版表结构，不会清空数据。

## 阶段 4：模型打标签

脚本：

```text
tools/auto_label_images.py
```

默认调用本地 Ollama 模型 `qwen2.5vl:7b`，输出：

```json
{
  "description": "图片可见内容描述",
  "categoryPath": ["一级分类", "二级分类"],
  "tags": [
    {"type": "style", "name": "赛博朋克", "confidence": 0.9}
  ]
}
```

写入：

- `images.description`
- `images.main_category_id`
- `categories`
- `tags`
- `image_tags`

## 阶段 5：向量与 Milvus

目标：做相似图片检索和推荐召回。

- 图片向量：CLIP、SigLIP、Chinese-CLIP 或同类 embedding 模型。
- 文本向量：标题、描述、分类路径、标签。
- Milvus 保存向量和必要过滤字段。
- MySQL 继续保存业务主数据。

## 阶段 6：推荐系统

后续再引入：

- 召回：最新、同标签、相似图片、关注作者、用户兴趣。
- 排序：新鲜度、相似度、互动概率、质量分。
- 编排：去重、过滤、混排。
- 日志：曝光、点击、详情浏览、点赞、收藏、停留。
