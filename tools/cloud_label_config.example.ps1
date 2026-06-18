# Copy this file to tools/cloud_label_config.local.ps1, then fill your API key.
# The local file is ignored by git.

# DashScope Model Studio, Beijing region.
# API key help: https://help.aliyun.com/zh/model-studio/get-api-key
$env:VIBELO_CLOUD_LABEL_API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:VIBELO_CLOUD_LABEL_API_KEY = "sk-your-api-key"

# Recommended cheap/fast vision model for image tagging.
# If unavailable in your account, try qwen3-vl-plus or qwen-vl-plus.
$env:VIBELO_CLOUD_LABEL_MODEL = "qwen3-vl-flash"

# Start small. Set 0 after the first test batch looks good.
$env:VIBELO_LABEL_LIMIT = "20"
$env:VIBELO_LABEL_WORKERS = "1"
$env:VIBELO_LABEL_IMAGE_MAX_SIDE = "1024"
$env:VIBELO_LABEL_JPEG_QUALITY = "85"

# A DB row is treated as already complete only when it has category + description + at least this many tags.
$env:VIBELO_LABEL_MIN_TAGS_TO_SKIP = "3"

# Keep retrying previously failed rows by default. Set to 0 only when you want to ignore old failed records.
$env:VIBELO_LABEL_RETRY_FAILED = "1"

# Default 1 means resume from the largest source_index already attempted in cloud_label_results.jsonl.
# Set to 0 when you explicitly want to backfill old failed/incomplete images before that cursor.
$env:VIBELO_LABEL_RESUME_FROM_LAST_ATTEMPT = "1"
# Optional manual cursor, for example "62810".
# $env:VIBELO_LABEL_START_AFTER_SOURCE_INDEX = "0"

# Usually keep this 0 so MySQL is the source of truth. Set to 1 only if the result JSONL is more complete than DB.
$env:VIBELO_LABEL_TRUST_RESULT_FILE = "0"

# Enable only if your API call must go through the local proxy.
# $env:VIBELO_CLOUD_LABEL_PROXY_URL = "http://127.0.0.1:12000"

# Optional database overrides. Defaults usually match the local dev database.
# $env:VIBELO_MYSQL_HOST = "127.0.0.1"
# $env:VIBELO_MYSQL_PORT = "3306"
# $env:VIBELO_MYSQL_DATABASE = "rangwaz_image_dev"
# $env:VIBELO_MYSQL_USER = "rangwaz"
# $env:VIBELO_MYSQL_PASSWORD = "rangwaz123"
