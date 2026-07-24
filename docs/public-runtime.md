# 公网运行清单

## 登录 CORS

后端启动时把前端的真实来源写成精确白名单：

```text
APP_WEB_ALLOWED_ORIGIN_PATTERNS=https://www.example.com
SPRING_PROFILES_ACTIVE=prod
```

推荐将前端与接口部署为同源：浏览器访问 `https://www.example.com`，Nginx 把 `/api/**` 转发到 `127.0.0.1:8080`。前端构建时设置 `VITE_API_BASE=/api`。不要在生产环境使用 `*` 搭配凭证请求。

## 首次上线

1. 复制根目录的 `.env.public.example` 到服务器的密钥管理或未纳入 Git 的环境文件，替换全部 `replace_me`。
2. `APP_AUTH_TOKEN_SECRET` 至少 32 个随机字符。升级后旧的无签名 token 会失效，用户重新登录一次即可。
3. 真实短信参数必须完整；`prod` 配置会强制关闭模拟验证码。
4. MySQL、Redis、Kafka、Milvus、MinIO、Elasticsearch 和 Python 内部服务只监听本机或内网，不开放公网端口。
5. 为推荐模型准备持久化目录，并让训练、索引发布与在线服务共用同一个 `VIBELO_RECOMMENDATION_MODEL_DIR`。
6. 启动推荐服务，确认 `GET http://127.0.0.1:8092/health` 中 Milvus 已就绪。
7. 使用 `--spring.profiles.active=prod` 启动后端，再部署前端 `dist`。
8. 对公网只开放 80/443；数据库和模型端口由安全组拒绝公网访问。

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
- 发布、头像和背景图上传均要求登录，内容安全服务失败时生产环境拒绝发布。
