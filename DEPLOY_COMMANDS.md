# 项目部署与常用命令手册

适用对象：

- 本地项目目录：`/Users/saksk/Desktop/codex-team-3/team-manage`
- 服务器项目目录：`/opt/team-manage`
- 线上域名：`https://team.saksk.top/`
- 代码仓库：`https://github.com/Saksk-IT/team-manage`

---

## 1. 本地常用命令

### 1.1 进入项目

```bash
cd /Users/saksk/Desktop/codex-team-3/team-manage
```

### 1.2 查看代码状态

```bash
git status
git log --oneline -n 5
git remote -v
```

### 1.3 提交并推送到远程仓库

```bash
cd /Users/saksk/Desktop/codex-team-3/team-manage
git add .
git commit -m "你的更新说明"
git push origin main
```

### 1.4 本地查看 Compose 配置是否有效

```bash
cd /Users/saksk/Desktop/codex-team-3/team-manage
docker compose config
```

---

## 2. 服务器常用命令

### 2.1 进入项目目录

```bash
cd /opt/team-manage
```

如果这里报：

```bash
No such file or directory
```

说明你大概率进错服务器了。

### 2.2 查看当前版本

```bash
cd /opt/team-manage
git log --oneline -n 5
git remote -v
```

### 2.3 更新服务器代码并重建容器

```bash
cd /opt/team-manage
git fetch origin
git reset --hard origin/main
docker compose up -d --build
```

### 2.4 查看容器状态

```bash
cd /opt/team-manage
docker compose ps
```

### 2.5 查看日志

```bash
cd /opt/team-manage
docker compose logs -f --tail=100
```

### 2.6 重启服务

```bash
cd /opt/team-manage
docker compose restart
```

### 2.7 停止服务

```bash
cd /opt/team-manage
docker compose down
```

### 2.8 启动服务

```bash
cd /opt/team-manage
docker compose up -d
```

---

## 3. 线上检查命令

### 3.1 健康检查

```bash
curl https://team.saksk.top/health
```

预期返回：

```json
{"status":"healthy"}
```

### 3.2 检查首页 HTML

```bash
curl -s https://team.saksk.top/ | sed -n '1,20p'
```

### 3.3 检查 CSS 是否正常

```bash
curl -I https://team.saksk.top/static/css/user.css
```

预期应包含：

```bash
HTTP/2 200
```

### 3.4 检查首页是否还在错误引用 HTTP 静态资源

```bash
curl -s https://team.saksk.top/ | grep -E 'http://team.saksk.top/static|/static/css|/static/js'
```

如果看到：

```bash
http://team.saksk.top/static/...
```

说明又出现了 mixed content 问题。

---

## 4. 当前部署关键文件

### 4.1 Docker Compose

文件：

```text
/opt/team-manage/docker-compose.yml
```

关键点：

- 端口只绑定到本机：`127.0.0.1`
- 使用：
  - `--proxy-headers`
  - `--forwarded-allow-ips='*'`

### 4.2 模板静态资源

文件：

```text
/opt/team-manage/app/templates/user/redeem.html
/opt/team-manage/app/templates/base.html
```

关键点：

- 静态资源应使用：

```html
/static/...
```

不要回到：

```html
http://team.saksk.top/static/...
```

---

## 5. 备份命令

### 5.1 备份 `.env`

```bash
cd /opt/team-manage
cp .env /root/team-manage.env.$(date +%F-%H%M%S).bak
```

### 5.2 备份数据库目录

```bash
cd /opt/team-manage
tar czf /root/team-manage-data.$(date +%F-%H%M%S).tgz data
```

---

## 6. 重置为全新空库状态

注意：下面命令会删除当前数据库数据。

```bash
cd /opt/team-manage
docker compose down
rm -rf data
mkdir -p data
docker compose up -d --build
```

---

## 7. Nginx 常用命令

### 7.1 检查配置

```bash
nginx -t
```

### 7.2 重载配置

```bash
systemctl reload nginx
```

### 7.3 查看 Nginx 状态

```bash
systemctl status nginx --no-pager
```

---

## 8. 常见问题排查

### 8.1 `cd /opt/team-manage` 不存在

说明你大概率进错服务器，或者当前服务器还没部署这个项目。

### 8.2 `git fetch origin` / `git pull` 报认证错误

如果仓库是私有仓库，需要配置：

- GitHub Deploy Key
- 或 GitHub PAT / `gh auth login`

如果仓库是公开仓库，直接拉取即可。

### 8.3 HTTPS 下页面没样式

先执行：

```bash
curl -s https://team.saksk.top/ | sed -n '1,20p'
curl -I https://team.saksk.top/static/css/user.css
```

重点看：

- 首页是否引用了 `http://team.saksk.top/static/...`
- CSS 是否返回 `200`

### 8.4 修改代码后线上没变化

按顺序执行：

```bash
cd /opt/team-manage
git fetch origin
git reset --hard origin/main
docker compose up -d --build
docker compose logs -f --tail=100
```

然后再看：

```bash
git log --oneline -n 3
```

是否已经切到最新提交。

---

## 9. 最常用的一套命令

### 本地更新

```bash
cd /Users/saksk/Desktop/codex-team-3/team-manage
git add .
git commit -m "update"
git push origin main
```

### 服务器更新

```bash
cd /opt/team-manage
git fetch origin
git reset --hard origin/main
docker compose up -d --build
docker compose logs -f --tail=100
```

### 线上验证

```bash
curl https://team.saksk.top/health
curl -s https://team.saksk.top/ | sed -n '1,20p'
curl -I https://team.saksk.top/static/css/user.css
```
