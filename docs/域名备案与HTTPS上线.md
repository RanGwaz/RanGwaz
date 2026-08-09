# Vibelo 域名备案、DNS 与 HTTPS 上线

本文只处理 `vibelo.xin` 的中国内地公网入口。默认公网 Compose 仍然使用
`infra/nginx/gateway.conf` 提供 HTTP；证书缺失时不会加载 TLS 配置，也不会影响
现有 HTTP 容器。只有备案、DNS 和证书门禁全部通过后，才显式叠加
`infra/docker-compose.public.tls.yml`。

如果当前按量试用 ECS 不具备备案资格，就先保持 TLS 覆盖文件停用，仅把公网 IP
用于所有者自己的临时验收；不要在纯 HTTP 上邀请真实用户登录或接收短信验证码。
等更换为支持备案的中国内地实例后，再从本文第 2 节继续。

## 1. 当前结论

- `dns3.hichina.com`、`dns4.hichina.com` 已经是阿里云公网权威 DNS，不需要再购买
  DNS 套餐。免费版足够当前单域名首发。
- 根域名 `vibelo.xin` 的 A 记录已经指向 ECS；出现阿里云备案拦截页说明请求已经到达
  中国内地云入口，不是“域名没买好”或“DNS 服务器没生效”。
- 域名实名认证只证明域名持有人身份，**不等于 ICP 备案**。中国内地 ECS 对外提供
  网站前必须完成阿里云 ICP 备案；首次备案审核期间应保持站点不可访问。
- `www.vibelo.xin` 还需要单独的 DNS 记录。HTTPS 也必须在备案完成、证书覆盖两个
  域名且 443 已放行后再启用。

因此当前正确顺序是：**先关站并完成 ICP 备案，再补全 DNS，再申请证书，最后启用
TLS**。不要购买 ESA、付费 DNS 或注册局安全锁来尝试绕过备案；这些产品不能替代
ICP 备案。

## 2. 首次备案期间保持关站

在阿里云 ICP 备案控制台提交首次备案，并按控制台要求完成真实性核验。审核期间可选
以下任一方式保证网站不可访问：

1. 直接停止 ECS；或
2. 在 ECS 安全组暂时删除/禁用公网入方向的 TCP 80、443 规则；或
3. 停止公网 Gateway，并确认没有其他进程监听 80、443。

仅停止 Gateway 时使用现有 Compose 文件，不要删除数据卷：

```bash
cd /opt/vibelo
docker compose --env-file .env.public \
  -f infra/docker-compose.public.yml \
  stop gateway
```

不要执行 `docker compose down -v`。备案通过前不要加入 TLS 覆盖文件，也不要因为
HTTP 能返回页面就提前开站。

## 3. 备案通过后配置 DNS

在阿里云云解析 DNS 的 `vibelo.xin` 解析设置中保留/新增以下记录：

| 记录类型 | 主机记录 | 记录值 | TTL |
| --- | --- | --- | --- |
| A | `@` | ECS 当前公网 IPv4 | 默认值或 600 秒 |
| CNAME | `www` | `vibelo.xin` | 默认值或 600 秒 |

根域名记录中的 `@` 就是 `vibelo.xin`。`www` 使用 CNAME 后会跟随根域名；不要同时
为同一个 `www` 主机记录创建冲突的 A/CNAME 记录。ECS 更换公网 IP 时只需更新根域名
A 记录。当前是单 ECS IPv4 方案：根域和 `www` 最终都只能得到这一个 A 地址；没有
配置 IPv6 入口时不要保留 AAAA 记录，否则一部分客户端可能绕到未部署的网站入口。

在 ECS 上确认两个域名最终都解析到同一个公网 IP：

```bash
getent ahostsv4 vibelo.xin
getent ahostsv4 www.vibelo.xin
```

DNS 生效可能受 TTL 和本地缓存影响。不要因为短时间缓存未更新而购买付费 DNS。

## 4. 申请并放置证书

在阿里云数字证书管理服务中申请证书，证书域名必须同时包含：

```text
vibelo.xin
www.vibelo.xin
```

下载 Nginx 格式证书。不要把证书私钥提交到 Git，也不要粘贴到聊天或命令行参数。
在 ECS 创建 Git 仓库之外的专用目录，并把下载文件分别放成固定名称：

```bash
sudo install -d -o root -g root -m 700 /data/vibelo-tls
sudo install -o root -g root -m 644 你的证书链.pem \
  /data/vibelo-tls/fullchain.pem
sudo install -o root -g root -m 600 你的私钥.key \
  /data/vibelo-tls/privkey.pem
```

`fullchain.pem` 应包含服务器证书以及阿里云提供的中间证书链；`privkey.pem` 必须是
与其匹配、没有交互口令的私钥。公网 Compose 只读挂载整个目录，容器不能修改证书。

## 5. 更新同源与运行参数

HTTPS 正式入口固定为根域名，`www` 只做 308 跳转。因此后端 CORS 只允许一个来源：

```text
APP_WEB_ALLOWED_ORIGIN_PATTERNS=https://vibelo.xin
PUBLIC_HTTPS_PORT=443
VIBELO_TLS_CERT_DIR=/data/vibelo-tls
```

可以重跑已有安全配置脚本；秘密值提示时按 Enter 保留：

```bash
cd /opt/vibelo
bash ops/public/configure-rds-env.sh \
  --allowed-origin 'https://vibelo.xin' \
  --sms-sign-name '你的短信签名' \
  --sms-template-code '你的短信模板代码'
chmod 600 .env.public
```

`.env.public.example` 已包含 TLS 非秘密变量。TLS 覆盖文件未被显式加入命令时，这些
变量不会让默认 HTTP 配置读取证书或监听 443。

## 6. 上线前只读门禁

备案通过、DNS 生效、证书就位后执行：

```bash
cd /opt/vibelo
bash ops/public/validate-domain-tls.sh \
  --cert-dir /data/vibelo-tls \
  --expected-ip '<ECS当前公网IPv4>'
```

脚本会检查：

- `.env.public` 权限仍为 600，CORS 唯一来源为 `https://vibelo.xin`；
- 根域名和 `www` 均且仅解析到传入的 ECS IPv4，并且没有额外 AAAA 路由；
- 证书链可解析、至少还有 14 天有效期，并覆盖根域名与 `www`；
- 私钥权限不向 group/other 开放、没有交互口令且与证书匹配；
- 基础 Compose 与 TLS 覆盖文件能安全展开；
- 固定的本地 Nginx 镜像能通过 `nginx -t`。

脚本不会修改 `.env.public`、证书、现有容器或数据卷，不会拉取或构建镜像。它只创建
一个 `--pull=never` 的临时 Nginx 语法检查容器，检查结束后自动删除。任一检查失败都
不要继续上线。

## 7. 显式启用 TLS

先在阿里云 ECS 安全组放行公网入方向 TCP 80、443；不要开放 3306、6379、9000、
9001、9200、19530 等内部端口。然后只重建 Gateway：

```bash
cd /opt/vibelo
docker compose --env-file .env.public \
  -f infra/docker-compose.public.yml \
  -f infra/docker-compose.public.tls.yml \
  up -d --wait --no-build --pull never --no-deps gateway
```

TLS 一旦启用，今后所有可能创建或重建 `gateway` 的 Compose 命令都必须同时携带上述
两个 `-f` 参数，包括版本更新、故障恢复和开机后人工 `up`。只带基础文件执行
`up ... gateway` 会按 HTTP 配置重建容器并静默丢掉 443。日常更新 Gateway 使用：

```bash
docker compose --env-file .env.public \
  -f infra/docker-compose.public.yml \
  -f infra/docker-compose.public.tls.yml \
  up -d --wait --no-build --pull never --no-deps gateway
```

只有第 8 节的显式 TLS 回退才故意省略覆盖文件。`ps`、`logs`、`stop` 等不重建容器
的只读/停止操作不会改变挂载，但为了减少误操作，也建议启用后统一使用双文件命令。

TLS 配置的行为如下：

- `http://127.0.0.1/gateway/health` 继续返回 200，Docker healthcheck 不会被重定向；
- 其他 HTTP 请求固定 308 到 `https://vibelo.xin`，不信任外部传入的 Host；
- `https://www.vibelo.xin/**` 固定 308 到根域名并保留路径与查询参数；
- `https://vibelo.xin/**` 使用与原 HTTP 网关完全相同的前端/API/媒体代理和限流；
- 直接访问 IP 或未知 SNI 的 TLS 握手会被拒绝。

上线后逐项验收：

```bash
curl -fsS http://127.0.0.1/gateway/health
curl -I http://vibelo.xin/
curl -I https://vibelo.xin/
curl -I https://www.vibelo.xin/
curl -fsS https://vibelo.xin/api/actuator/health
```

预期 HTTP 根路径返回 308，HTTPS 根域名返回 200，HTTPS `www` 返回指向根域名的
308，两个健康接口成功。浏览器再验证短信登录，不应出现混合内容或 CORS 错误。

## 8. 回退与续期

TLS 启用失败时，仅用基础 Compose 强制重建 Gateway 即可回到原 HTTP 配置：

```bash
cd /opt/vibelo
docker compose --env-file .env.public \
  -f infra/docker-compose.public.yml \
  up -d --wait --no-build --pull never --no-deps --force-recreate gateway
```

回退不会删除前端、后端或数据卷。证书续期时先把两个新文件安全替换到
`/data/vibelo-tls`，再次运行第 6 节门禁，再重复第 7 节的 Gateway 命令。当前配置
没有预先发送 HSTS，避免首次备案/TLS 调试阶段把错误证书状态长期缓存；稳定运行后再
单独评估 HSTS。

## 9. 阿里云官方参考

- [网站备案全流程（含首次备案期间必须关站）](https://help.aliyun.com/zh/dws/icp-filing)
- [备案期间对网站访问的影响](https://help.aliyun.com/zh/icp-filing/the-influence-of-the-record-during-the-site-visit)
- [公网权威解析添加 A/CNAME 记录](https://help.aliyun.com/zh/dns/pubz-add-parsing-record)
- [下载 Nginx 格式 SSL 证书](https://help.aliyun.com/zh/ssl-certificate/download-an-ssl-certificate)
- [Linux Nginx 安装与验证 SSL 证书](https://help.aliyun.com/en/ssl-certificate/install-ssl-certificates-on-nginx-servers-or-tengine-servers)
