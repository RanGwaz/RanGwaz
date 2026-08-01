# MySQL 8.4 → RDS MySQL 8.0.36 安全迁移

这套脚本迁移完整的 `rangwaz_image_dev`：表结构、业务数据、视图、触发器、存储程序、事件以及 `flyway_schema_history`。路线固定为：

1. Windows 本机停止全部写入并导出；
2. 本机用临时 `mysql:8.0.36` 完整恢复演练；
3. 把同一份快照导入 RDS 空库；
4. 使用 `vibelo_app` 对表集合、逐表精确行数、Flyway 和对象清单做最终验收；
5. 验收通过后才启动后端。

脚本不会构建镜像。恢复演练和 ECS 导入在缺少 `mysql:8.0.36` 时只会执行 `docker pull`。

## 账号边界

- RDS 高权限账号：只用于一次性导入，不能写入应用的 `.env.public`。
- `vibelo_app`：RDS 标准账号，只授权 `rangwaz_image_dev` 的读写（DDL + DML），用于验收和应用运行。
- `dms_user_*`：DMS 自动托管服务账号，禁止用于迁移或应用运行，也不要修改、删除。

两个 RDS 账号必须不同。脚本会拒绝 `dms_user_*`，也会拒绝把迁移账号与应用账号设成同一个。

不要把任何密码写进命令行、Git、README、聊天记录或快照目录。已经暴露过的密码应在上线前轮换。

## 产物

一次成功导出会生成同名前缀的六个文件；恢复演练再生成第七个门禁文件：

| 文件 | 用途 |
| --- | --- |
| `*.sql.gz` | 完整 SQL dump |
| `*.sha256` | dump 的 SHA256 |
| `*.row-counts.tsv` | 每个基础表通过 `COUNT(*)` 得到的精确行数 |
| `*.flyway.tsv` | 按 `installed_rank` 排序的完整 Flyway 清单 |
| `*.objects.tsv` | 表、视图、过程、函数、触发器、事件清单 |
| `*.meta.json` | 源版本、导出时间、总行数与 dump 哈希 |
| `*.restore-tested.json` | MySQL 8.0.36 恢复演练通过证明 |

默认导出目录是 `%TEMP%\VibeloMysqlSnapshots`，位于仓库外，避免误提交大文件。也可以用 `-OutputDirectory` 指定其他仓库外目录。

## 第 0 步：维护窗口

先停止所有可能写 MySQL 的进程，包括后端、数据导入、标签任务、训练/发布任务。只保留 `rangwaz-mysql` 容器运行。

`-MaintenanceConfirmed` 是操作确认，不会替你停止进程。脚本会在 dump 前后分别读取：

- 基础表集合和每张表的精确 `COUNT(*)`；
- Flyway 清单；
- 数据库对象清单。

任一清单变化都会删除宿主端不可信产物并失败。由于“行数不变”不能证明行内容绝对未变，维护窗口仍是硬性门禁。

脚本还会拒绝任何非 InnoDB 基础表，因为 `--single-transaction` 不能为非事务表提供同等一致性保证。

## 第 1 步：Windows 导出

在仓库根目录用 Windows PowerShell 5.1 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\ops\migration\mysql\Export-MySqlSnapshot.ps1 `
  -ContainerName rangwaz-mysql `
  -Database rangwaz_image_dev `
  -DatabaseUser root `
  -UseContainerRootPassword `
  -MaintenanceConfirmed
```

当前 Compose 容器已有 `MYSQL_ROOT_PASSWORD`，推荐使用
`-UseContainerRootPassword`：脚本只在容器内部生成临时客户端配置，密码不会
离开容器。若不传该开关，脚本会静默询问本机 MySQL 密码；若使用普通数据库
账号，可替换 `-DatabaseUser`，但该账号必须有导出全部对象所需权限。

Windows PowerShell 5.1 的文本管道可能损坏 gzip 二进制，因此脚本采用以下字节安全流程：

1. 在 MySQL 容器内部由 `mysqldump | gzip` 生成临时文件；
2. 容器内先执行 `gzip -t`；
3. 用 `docker cp` 复制到宿主；
4. 宿主用 .NET gzip 流读到 EOF，再校验 CRC 和 SHA256；
5. 复制与校验成功后才清理容器临时 dump。

脚本绝不会通过 PowerShell 管道或 `>` 重定向 gzip 内容。

导出固定启用 `--output-as-version=BEFORE_8_2_0`，并关闭 dump 中的表锁、附加锁和列统计语句；同时把客户端包上限设为 `1G`。这些设置减少 MySQL 8.4 dump 恢复到 8.0.36/RDS 时的语法与权限差异。

查看最新快照：

```powershell
$dump = Get-ChildItem "$env:TEMP\VibeloMysqlSnapshots\*.sql.gz" |
  Sort-Object LastWriteTimeUtc -Descending |
  Select-Object -First 1
$dump.FullName
```

## 第 2 步：本机 MySQL 8.0.36 恢复演练

继续在仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\ops\migration\mysql\Test-MySql80Restore.ps1 `
  -DumpPath $dump.FullName
```

恢复演练会：

- 先校验 gzip、SHA256、所有清单；
- 启动一个不映射端口、`--network=none`、无持久卷的临时 `mysql:8.0.36`；
- 确认临时目标库为空；
- 不使用 `--force`，任一 SQL 错误立即失败；
- 比较基础表集合、逐表精确行数、Flyway 和全部对象；
- 成功后写出 `*.restore-tested.json`，再删除临时容器。

如需保留失败现场，可加 `-KeepContainer`；它没有网络且只包含临时数据。排查后手工删除脚本输出的容器名。

MySQL 8.4 dump 开头可能含 8.0 客户端不识别的 sandbox 指令，数据库对象还可能含本机 `DEFINER`。恢复演练和 RDS 导入使用同一套流式规则：只删除开头的 sandbox 元数据行，以及 mysqldump 条件注释/`CREATE DEFINER` DDL 元数据中的显式 `DEFINER`；业务 `INSERT` 数据不会被匹配或改写。

## 第 3 步：把七个文件传到 ECS

建议在 ECS 数据盘建立仅 root 可读的临时目录，例如 `/data/migration/mysql`。复制同一前缀的全部七个文件，不能只传 `.sql.gz`。

复制后可先在 ECS 查看：

```bash
ls -lh /data/migration/mysql/
sha256sum /data/migration/mysql/*.sql.gz
```

不要把密码文件与快照同步到公开对象存储。

## 第 4 步：RDS 导入

前置条件：

- RDS 版本是 MySQL `8.0.36`；
- `rangwaz_image_dev` 已存在，字符集 `utf8mb4`、排序规则 `utf8mb4_0900_ai_ci`；
- 目标库没有任何表、视图、存储程序、触发器或事件；
- RDS 白名单允许 ECS 内网访问；
- 已有一次性高权限迁移账号；
- 已创建标准账号 `vibelo_app`，并仅授权该业务库读写。

最安全的方式是让脚本分别静默询问两个密码：

```bash
cd /path/to/RanGwaz

bash ops/migration/mysql/import-mysql-snapshot-to-rds.sh \
  --dump /data/migration/mysql/rangwaz_image_dev-YYYYMMDDTHHMMSSZ.sql.gz \
  --host rm-xxxx.mysql.rds.aliyuncs.com \
  --port 3306 \
  --database rangwaz_image_dev \
  --admin-user YOUR_RDS_MIGRATION_ADMIN \
  --app-user vibelo_app \
  --confirm-import
```

也可以提供密码文件。文件必须由当前用户拥有、权限恰好为 `0600`，且只包含一行密码：

```bash
umask 077
read -r -s -p '迁移账号密码：' ADMIN_SECRET; echo
printf '%s' "$ADMIN_SECRET" > /root/rds-admin.password
unset ADMIN_SECRET

read -r -s -p 'vibelo_app 密码：' APP_SECRET; echo
printf '%s' "$APP_SECRET" > /root/rds-app.password
unset APP_SECRET

chmod 600 /root/rds-admin.password /root/rds-app.password
```

导入命令增加：

```bash
  --admin-password-file /root/rds-admin.password \
  --app-password-file /root/rds-app.password
```

脚本会把密码转换成 `/tmp` 下权限为 `0600` 的临时 MySQL option file，以只读方式挂载进临时客户端容器，并在退出时删除。用户提供的原始密码文件不会自动删除；迁移结束后应立即手工删除并清理 shell 变量。

## RDS 导入门禁

导入前会依次验证：

1. gzip CRC、SHA256、元数据与本机恢复演练证明属于同一个 dump；
2. 所有 TSV 格式正确、没有重复表/对象、没有失败 Flyway；
3. 客户端和 RDS 服务端均符合 `8.0.36`；
4. 目标库字符集、排序规则正确且严格为空；
5. `vibelo_app` 可连接，并能完成临时建表、插入、更新、删除、改表、创建/删除索引、创建/删除视图、创建/删除存储过程和删表；
6. 探针对象已清理，目标库再次严格为空。

导入由高权限迁移账号执行。导入后改用 `vibelo_app`：

- 对比基础表集合；
- 对每一张表执行精确 `COUNT(*)`；
- 对比完整 Flyway 清单；
- 对比数据库对象清单；
- 确认不存在失败 Flyway。

任何一步失败都会返回非零，且导入命令没有 `--force`。如果 gzip、SQL 兼容化或 MySQL 导入管道本身失败，数据库可能只完成了部分 DDL/DML，不能在半成品库上“继续导”。如果三段导入管道已经成功、失败只发生在后续验收，则先保留现状并使用下方只读模式复验，不能直接清库或重复导入。

### 导入只显示统一失败提示

`99a6019` 及更早版本的 ECS 导入脚本启动 MySQL 客户端容器时没有保持标准输入，管道中的 SQL 不会进入容器。典型现象是：门禁通过后只显示“开始导入”和“导入已经开始但未成功完成”，中间没有任何 MySQL `ERROR ... at line ...`。这种情况下 MySQL 实际收到的是空输入，目标库通常仍为空。

新版本已经修复该问题，并增加两层保护：

- Docker 明确保持标准输入，SQL 才能进入 MySQL 客户端；
- 失败时分别显示 `gzip`、SQL 兼容化和 `mysql` 三段退出码，并保留原始错误文本。

更新代码后先执行回归测试：

```bash
cd /opt/vibelo
git pull --ff-only origin main
bash ops/migration/mysql/test-import-mysql-snapshot-to-rds.sh
bash ops/migration/mysql/test-verify-existing-rds-snapshot.sh
```

只有同时看到“RDS 导入与逐表验收回归测试通过”和“RDS 现有数据库只读验收回归测试通过”后，才重新执行原导入命令或只读验收。脚本每次都会在真正导入前重新检查目标数据库是否严格为空：若上次确实没有写入，它会继续；若发现任何残留对象，它会在导入前停止，此时不要使用 `--force`，也不要自行续传，把完整输出保留下来再处理。

不要用 `bash -x` 排查该脚本。脚本虽然会主动关闭跟踪，但数据库迁移过程仍应避免开启可能记录秘密值的全局 shell 跟踪。

### SQL 导入完成、后续验收失败时

如果输出已经明确说明 SQL 导入流水线成功，但在逐表行数、Flyway 或对象清单阶段失败，先保留 RDS 现状，不能直接重复导入。可以用同一脚本的 `--verify-existing` 模式重新执行完整验收：

```bash
cd /opt/vibelo

bash ops/migration/mysql/import-mysql-snapshot-to-rds.sh \
  --verify-existing \
  --dump /data/migration/mysql/rangwaz_image_dev-YYYYMMDDTHHMMSSZ.sql.gz \
  --host rm-xxxx.mysql.rds.aliyuncs.com \
  --port 3306 \
  --database rangwaz_image_dev \
  --app-user vibelo_app \
  --mysql-image mysql:8.0.36 \
  --no-pull
```

该模式只会静默询问 `vibelo_app` 密码，并执行以下只读检查：

- 七个快照及门禁文件、dump SHA256 和 gzip 完整性；
- RDS 版本、数据库字符集和排序规则；
- 全部基础表集合和每张表的精确 `COUNT(*)`；
- 完整 Flyway 清单及失败迁移数量；
- 表、视图、过程、函数、触发器和事件的完整对象清单。

它不接受 `--admin-user`、`--admin-password-file` 或 `--confirm-import`，不会读取高权限迁移账号密码，也不会执行空库权限探针、DDL、DML 或 dump 导入。所有 RDS 查询都使用只读会话，并且查询容器不接管脚本的标准输入。

只有看到以下两行才表示现有 RDS 已经精确验收通过，无需清库或重新导入：

```text
RDS 现有数据只读精确验收全部通过。
本次未请求迁移账号密码，未执行导入或数据库写入。
```

如果只读验收仍报告真实的表、行数、Flyway 或对象差异，再保留完整输出判断是否需要重建空库并执行一次完整导入；不要对非空库覆盖导入，也不要使用 `--force`。

## 验收后

`.env.public` 可以在导入前先安全写好，但后端必须保持停止。只有脚本输出
“RDS 导入与精确验收全部通过”后，才允许后端实际使用这份 RDS 配置：

```dotenv
SPRING_DATASOURCE_USERNAME=vibelo_app
```

密码只写入 ECS 上权限为 `0600` 的 `.env.public`。不要使用高权限迁移账号，也不要使用 `dms_user_*`。

后端当前依赖已有基础表和 `flyway_schema_history`，不能让后端先连接空库“自动初始化”。顺序必须是：恢复演练 → RDS 导入 → 精确验收 → 启动后端。
