# 数据采集工具说明

`dataset_collector.py` 用可见浏览器采集已授权来源里的图片数据。它会自动滚动入口页，收集详情页链接，再逐个进入详情页滚动、采集和下载图片。

工具不会绕过验证码、登录墙或平台风控。提供账号密码时，它只会尝试自动填写正常登录表单；遇到验证码、二次验证或风控确认时，需要你在浏览器里手动处理。

## 输出目录

```text
tools/downloaded_dataset
```

主要文件：

- `images/`：实际下载的图片。
- `manifest.jsonl`：下载结果、sha256、content-type、本地路径、来源页。
- `candidates.jsonl`：去重后的候选图片 URL 和来源信息。
- `detail_urls.jsonl`：访问过或排队过的详情页链接。

## 启动窗口

```powershell
python tools/dataset_collector.py
```

入口页可以填完整 URL，也可以只填首页域名，例如 `www.pinterest.com`。

## 依赖

```powershell
python -m pip install playwright
python -m playwright install chromium
```

## 后续导入

采集完成后运行：

```powershell
python tools/import_images.py
```

导入脚本会读取 `tools/downloaded_dataset/images`，把图片写入 MinIO 和 MySQL 的 `images` 表。

然后运行：

```powershell
python tools/auto_label_images.py
```

打标签脚本会读取导入结果，用本地视觉模型生成分类和标签，并直接写入 MySQL。
