# 百度搜索信息流投放管理平台

面向内部投放团队的搜索广告管理平台。当前版本默认处于安全的只读模式，百度真实写操作只有在 `BAIDU_WRITES_ENABLED=true`、目标账户明确、操作已预检并由管理员确认后才允许进入执行阶段。

## 本地启动

1. 将 `.env.example` 复制为 `.env`，替换所有密钥和数据库配置。
2. 安装 Docker Desktop 后先执行 `docker compose build api`。
3. 创建本机登录账号（密码输入时不会显示）：

```powershell
New-Item -ItemType Directory -Path .\data\secrets -Force | Out-Null
docker run --rm -it -v "${PWD}\data\secrets:/secrets" baidu-search-backend:local `
  python /app/backend/scripts/manage_login_user.py admin --file /secrets/web-login.htpasswd
```

4. 执行 `docker compose up -d`，打开 `http://127.0.0.1:8281`。热更新开发地址为
   `http://127.0.0.1:8280`，后台健康检查为 `http://127.0.0.1:8000/api/v1/health`。

所有项目持久数据固定写入 `E:\百度搜索信息流\data`：PostgreSQL、Redis、DuckDB、采集文件和上传文件均不使用 Docker 命名卷。

由于 Docker BuildKit 无法可靠处理中文构建路径，请先把 Docker Desktop 的 Disk image location 改为 `E:\百度搜索信息流\data\DockerDesktopWSL`，再运行 `powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1`。启动脚本会临时创建纯英文盘符映射，只作为路径别名，不在 C 盘保存数据。

没有 Docker 时可分别启动后端与前端，具体命令见各目录的配置文件。

Windows 本地开发可使用：

```powershell
$env:PYTHONPATH="$PWD\backend\src;$PWD\packages\baidu_platform_core\src"
.\.venv\Scripts\python.exe -m uvicorn search_console.main:app --app-dir backend\src --reload
```

另开终端进入 `frontend`，执行 `cmd /c npm run dev`。生产环境必须先执行 `alembic upgrade head`，应用进程不会在生产模式自动建表。

## 安全提示

- 不要把百度 Token、App Secret、数据库密码或好多粉凭据提交到仓库。
- 网页登录密码只以不可逆哈希保存在 `data\secrets\web-login.htpasswd`；成员登录账号必须与成员管理中的登录账号一致。
- 修改密码时重复执行上面的账号命令即可。线上沿用服务器受保护的凭据文件，不随发布包上传。
- 需求文档中曾出现的第三方密码应先轮换，再填入本地或阿里云密钥管理。
- 首期账户淘汰和关键词优化只产生告警或建议，不执行自动删除。

## 一键发布线上版

双击项目根目录的 `一键发布线上版.cmd`，输入 `YES` 后即可发布到
`https://www.pztxwx.cn`。发布工具会依次检查后台与网页、生成不含密钥的发布包、
备份线上 PostgreSQL、执行数据库迁移、切换容器并检查线上健康状态。线上密钥、
OAuth Token、业务数据和 Nginx 登录密码始终留在服务器，不从本地发布包覆盖。

如果新版本未能通过健康检查，工具会恢复上一应用版本并保留发布前数据库备份。
本地业务数据不会在日常发布时自动覆盖线上数据；首次上线或明确需要迁移数据时，
使用单独的数据迁移流程。
