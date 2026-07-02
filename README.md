# 佛系云音乐每日推荐自动下载

一个帮你**自动下载网易云音乐每日推荐**歌曲的小工具，专为**已有音乐库、需要增量更新**的场景设计：
你每天把「每日推荐」里喜欢的歌手动加进一个以当天日期命名的歌单，工具会定时扫描它，
**跳过库里/本地已有的歌**，只把新歌下载下来并写好完整标签。每日推荐通常约 30 首，
**不适合大批量下载**。

> ⚠️ 前提：需要一个**网易云黑胶会员（VIP）**账号，否则拿不到无损/高音质下载链接。
> 非 VIP 账号会在校验阶段直接终止本轮任务。

---

## 特性

- **按日期歌单增量下载**：只处理名字正好等于当天日期（如 `20251025`）的歌单。
- **多级去重，省流量省时间**（顺序：先便宜的检查，后昂贵的网络请求）：
  1. 音乐库去重：接入 **Navidrome** 或 **music-tag-web** 后，库里已有的歌直接跳过；
  2. 本地文件去重：本地已下载过的（按「歌手 - 歌名」匹配）跳过，**零网络请求**；
  3. 格式过滤：只有 MP3 可下的歌**主动跳过**（音乐库统一走无损）。
- **完整元信息**：下载后用 mutagen 写入标题、歌手、专辑、年份、音轨号、**歌词/翻译歌词**、
  **封面**（>5MB 自动压缩）。
- **原子下载**：先写临时 `.part` 文件并按接口给出的大小校验，完整后才改名为正式文件，
  避免下到一半的残缺文件被后续运行误认成「已下载」。
- **Bark 推送**（可选）：每轮任务推送「筛选统计」与「下载结果」两条通知。
- **纯定时批处理**：容器内用 cron 定时跑，一次跑完即退出，日志落到挂载目录。

---

## 工作原理

```
校验 Cookie/VIP ──▶ 找到当天日期命名的歌单 ──▶ 逐首筛选 ──▶ 下载并写标签 ──▶ Bark 通知
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    │ 1) 库里已有？(Navidrome / music-tag-web) → 跳过     │
                    │ 2) 本地已下载？(按 歌手-歌名 匹配，无网络)   → 跳过 │
                    │ 3) 只有 MP3？(库统一无损)                    → 跳过 │
                    └───────────────────────────────────────────────────┘
```

---

## 前置准备

1. **黑胶会员账号**（VIP）。
2. **Cookie**：登录网易云音乐网页版 → 按 F12 打开开发者工具 → Network 标签页 →
   刷新后点任意一条 `music.163.com` 请求 → 复制其请求头里的 `Cookie` 值。
   必须包含 `MUSIC_U`，形如 `MUSIC_U=xxxx;os=pc;appver=8.9.75`（**填进配置时不要加引号**）。
3. **uid**：你的网易云用户 ID（打开自己的个人主页，地址栏 `user/home?id=` 后面那串数字）。

---

## 快速开始（Docker Compose）

1. 新建一个目录，放入 `docker-compose.yml` 和 `config.yaml`（两者需在同一目录）。

   `docker-compose.yml`：

   ```yaml
   services:
     autoMusicDown:
       image: leonautilus/auto-music-downloader:latest
       container_name: auto-music-downloader
       restart: always
       volumes:
         - ./config.yaml:/app/config.yaml:ro    # 配置（只读）
         - ./logs:/app/logs                     # 日志
         - ./downloads:/app/downloads           # 下载目录（可映射到 music-tag-web 的下载目录）
       environment:
         - TZ=Asia/Shanghai                     # 时区（日期歌单匹配依赖本地时区，务必设对）
         - CRON_SCHEDULE=0 20-23,0 * * *        # 执行时间：每天 20-23 点及 0 点，每小时一次
         # - RUN_ON_START=true                  # 可选：容器启动即先同步一次（默认 false）
   ```

2. 参照下方「配置详解」写好 `config.yaml`（可从仓库的 `config.example.yaml` 复制起步）。

3. 启动：

   ```bash
   docker compose up -d
   docker compose logs -f        # 观察运行日志
   ```

4. **日常使用**：每天在云音乐客户端把喜欢的每日推荐歌曲，加入一个**名字正好是当天日期**
   （如 `20251025`）的歌单即可，剩下的交给定时任务。

---

## 配置详解（`config.yaml`）

| 配置项 | 说明 | 默认/示例 |
|---|---|---|
| `cookie` | 网易云登录 Cookie，须含 `MUSIC_U`；**不要加引号** | `MUSIC_U=xxx;os=pc;appver=8.9.75` |
| `uid` | 你的网易云用户 ID | `123456` |
| `LEVEL` | 日志级别（`DEBUG`/`INFO`/`WARNING`/`ERROR`） | `INFO` |
| `QUALITY_LEVEL` | 下载音质等级，见下表 | `lossless` |
| `NAVIDROME.USE_NAVIDROME` | 是否启用 Navidrome 库去重 | `false` |
| `NAVIDROME.NAVIDROME_HOST` | Navidrome 地址（带协议，如 `http://192.168.0.6:4533`） | — |
| `NAVIDROME.NAVIDROME_USER` / `NAVIDROME_PASS` | Navidrome 账号/密码（用 Subsonic token 认证，密码不进 URL/日志） | — |
| `music-tag-web.USE_MYSQL` | 是否启用 music-tag-web 的 MySQL 库去重 | `false` |
| `music-tag-web.host` / `port` / `user` / `password` / `database` | music-tag-web 使用的 MySQL 连接信息 | `3306` / `music_tag` 等 |
| `BARK_API` | 可选，Bark 推送地址；留空则不推送 | `https://api.day.app/your_key/` |
| `REQUEST_DELAY` | 可选，处理每首歌之间的间隔秒数，降低被限流概率；想更快可设 `0` | `0.5` |

> **去重后端二选一**：`NAVIDROME` 与 `music-tag-web` 同时开启时，优先使用 Navidrome；
> 两者都不开则只做本地文件去重。

### 音质等级

| 值 | 含义 |
|---|---|
| `standard` | 标准 |
| `exhigh` | 极高 |
| `lossless` | 无损（推荐） |
| `hires` | Hi-Res |
| `sky` | 沉浸环绕声 |
| `jyeffect` | 高清环绕声 |
| `jymaster` | 超清母带 |

---

## 环境变量（`docker-compose.yml`）

| 变量 | 说明 | 默认 |
|---|---|---|
| `TZ` | 容器时区。**日期命名的歌单匹配依赖本地时区**，跨零点时尤其重要 | `Asia/Shanghai` |
| `CRON_SCHEDULE` | 执行 `main.py` 的 cron 表达式 | `0 20-23,0 * * *`（每天 20-23 点及 0 点整点各一次） |
| `RUN_ON_START` | 设为 `true` 时容器启动立即先同步一次；否则只等定时触发 | `false` |

---

## 去重与格式说明

- **库里的 MP3 视为「不存在」**：若音乐库里某首只有 MP3 版本，工具仍会去下载它的无损版本
  （库统一无损）。
- **只有 MP3 可下的歌会被跳过**：网易云只返回 MP3 时，直接跳过该曲并省去后续详情/歌词请求。
- **本地去重按文件名**：以「`歌手&歌手 - 歌名`」为文件名判断本地是否已存在，命中即跳过。

---

## 更新与回滚

镜像已把代码打包在内（不再运行时拉取代码），因此升级 = 拉取新镜像：

```bash
docker compose pull        # 拉取最新镜像
docker compose up -d       # 用新镜像重建容器
```

如需**固定/回滚到某个版本**，把 `image` 的 `:latest` 换成具体版本 tag 即可，例如：

```yaml
image: leonautilus/auto-music-downloader:v3.1.0
```

---

## 目录与日志

- **下载目录**：容器内 `/app/downloads`（映射到宿主机 `./downloads`）。可直接指向
  music-tag-web 的下载目录，便于统一管理。
- **日志**：容器内 `/app/logs/<日期>.log`（映射到宿主机 `./logs`）；每轮任务的运行输出
  同时可在 `docker compose logs` 里看到。

---

## 常见问题

- **提示非 VIP / 取消下载**：账号不是黑胶会员，或 Cookie 失效。请更新 `cookie`。
- **「未找到今日播放列表」**：检查歌单名是否**正好等于当天日期**（如 `20251025`，无空格），
  以及容器 `TZ` 是否与你所在时区一致。
- **歌曲没被下载**：可能库里/本地已有，或该曲只有 MP3（会被主动跳过）——查看日志的筛选统计。
- **担心被限流**：适当调大 `REQUEST_DELAY`。

---

## 致谢

感谢 [苏晓晴](https://github.com/Suxiaoqinx) 的贡献。

---

## 支持

如果觉得工具有用，欢迎随意打赏：

| 微信 | 支付宝 |
|------|--------|
| ![微信收款码](./assets/wechat.png) | ![支付宝收款码](./assets/alipay.png) |
