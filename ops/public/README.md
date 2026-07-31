# ECS 公网上线前置脚本

本目录只负责两件事：

1. 安全生成或更新仓库根目录的 `.env.public`；
2. 在 Ubuntu ECS 上做只读上线预检。

两个脚本都不会构建镜像，也不会启动、停止或修改任何容器。

## 先准备 RDS 应用账号

RDS 中应已存在：

- 数据库：`rangwaz_image_dev`
- 标准应用账号：`vibelo_app`
- 权限：只授权 `rangwaz_image_dev` 的读写权限（DDL + DML）

不要把 RDS 高权限账号用于应用。`dms_user_*` 是 DMS 自动服务账号，也不能写入
`.env.public`，不能修改或删除它；请始终使用独立的 `vibelo_app` 标准账号。

## 1. 安全配置 `.env.public`

在仓库根目录执行：

```bash
bash ops/public/configure-rds-env.sh \
  --allowed-origin 'https://你的正式域名' \
  --sms-sign-name '你的短信签名' \
  --sms-template-code '你的模板代码'
```

脚本默认写入以下非秘密目标：

- RDS：`rm-bp111eaxy9eeuvqcb.mysql.rds.aliyuncs.com:3306`
- 数据库：`rangwaz_image_dev`
- 应用账号：`vibelo_app`

随后会在终端中静默询问：

- RDS 应用账号密码；
- 登录 Token 签名密钥（至少 32 个字符）；
- MinIO Access Key 和 Secret Key；
- 阿里云短信 AccessKey ID 和 AccessKey Secret。

输入过程不回显，脚本也不会打印秘密。再次运行时，已有有效秘密可以直接按
Enter 保留。脚本以现有 `.env.public` 为基础更新，因此不会删除或覆盖不认识的
环境变量；模板新增的变量会自动补齐。最终文件会原子替换并设置为权限 `600`。

不要把秘密写在命令行参数中。脚本故意不提供密码、Token 或 AccessKey 参数，
避免它们进入 shell 历史和进程列表。

可选的非秘密参数：

```text
--rds-host HOST
--rds-port PORT
--database NAME
--app-user USER
--public-http-port PORT
--allowed-origin URL
--sms-mock true|false
--sms-sign-name NAME
--sms-template-code CODE
--ssl-mode PREFERRED|REQUIRED|VERIFY_CA|VERIFY_IDENTITY
```

若首发阶段确实要使用模拟短信，可显式传入 `--sms-mock true`。正式公网登录应使用
默认的 `false` 并配置真实短信凭据。当前 RDS 尚未启用 SSL 时使用默认
`PREFERRED`；启用后显式传 `--ssl-mode REQUIRED`（或已正确部署 CA/主机名校验时
使用更严格模式）。再次运行脚本会保留已有 SSL 模式，不会静默降级。

## 2. 运行只读预检

配置完成后，在仓库根目录执行：

```bash
sudo bash ops/public/preflight.sh
```

建议使用 `sudo`，否则普通账号可能无权读取 Docker 或 containerd 的生效配置。
预检会一次列出全部结果，检查：

- `/data` 是否为独立、可写挂载点；
- DockerRoot 是否为 `/data/docker`；
- containerd root 是否为 `/data/containerd`；
- Swap 是否启用且不少于 4 GB；
- `vm.max_map_count` 是否至少为 `1048576`；
- TCP 80、443 是否仍空闲；
- RDS 内网域名能否解析、3306 端口能否连接；
- `.env.public` 是否为普通文件、权限是否为 `600`；
- RDS、Token、MinIO、短信等必填变量是否仍是占位符；
- Spring 与训练任务是否都使用同一个 `vibelo_app` RDS 凭据；
- `docker compose ... config --quiet` 是否通过。

Compose 检查只解析配置，输出会被隐藏以免泄露秘密；它不会拉取、构建或启动镜像。
预检存在任一 `[失败]` 时退出码为 `1`，全部通过时退出码为 `0`。`[警告]` 不会单独
阻止通过，但上线前仍应确认其影响。

80/443 的检查是“上线前端口应空闲”。网关正式启动后再次运行该脚本，这两项会因
网关正在监听而失败，这是预期现象。

## 安全边界

- `.env.public` 已被仓库根目录 `.gitignore` 忽略，不要强制提交。
- 脚本不会验证 MySQL 用户名和密码是否能登录，只验证 RDS DNS/TCP；数据库导入和
  权限探测应在启动后端之前单独完成。
- 不要在聊天、工单、终端截图或命令行参数中粘贴任何真实密码或 AccessKey。
- 预检通过不代表业务数据已经迁移完成；数据库与 MinIO 数据校验仍需按迁移手册执行。
