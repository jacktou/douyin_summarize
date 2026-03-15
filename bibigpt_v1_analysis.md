# BibiGPT v1 源码分析报告

> 仓库地址：https://github.com/JimmyLv/BibiGPT-v1
> 分析日期：2026-03-15

## 核心发现

BibiGPT v1 开源版**只实现了 Bilibili 和 YouTube 两个平台**，其他平台（抖音、TikTok 等）只存在于 README 中，属于商业版 BibiGPT Pro（bibigpt.co）的功能。**全程不下载任何视频文件，只获取平台已有的字幕数据。**

---

## 1. 整体架构

```
用户输入 URL
  → 前端判断平台 (YouTube / Bilibili)
  → POST /api/chat
  → fetchSubtitle() 按平台分发
  → 获取字幕文本（不下载视频）
  → 压缩字幕 → 构建 prompt → 调 OpenAI
  → 流式返回结果 + Redis 缓存
```

### 关键文件

| 文件 | 职责 |
|------|------|
| `/pages/[...slug].tsx` | 前端入口，解析 URL，判断平台 |
| `/pages/api/chat.ts` | API 端点，接收 videoConfig，编排流程 |
| `/proxy.ts` | 中间件，Upstash Redis 限流 + 缓存 |
| `/lib/fetchSubtitle.ts` | **分发器**，按平台路由到对应采集器 |
| `/lib/bilibili/fetchBilibiliSubtitleUrls.ts` | 获取 B站字幕元数据 |
| `/lib/bilibili/fetchBilibiliSubtitle.ts` | 下载并处理 B站字幕 JSON |
| `/lib/youtube/fetchYoutubeSubtitleUrls.ts` | 从 SaveSubs.com 获取 YouTube 字幕列表 |
| `/lib/youtube/fetchYoutubeSubtitle.ts` | 下载并处理 YouTube 字幕 |
| `/utils/reduceSubtitleTimestamp.ts` | 字幕分组（每 7 条合并） |
| `/lib/openai/getSmallSizeTranscripts.ts` | 压缩字幕至 6200 字节内 |
| `/lib/openai/prompt.ts` | 构建 LLM prompt |
| `/lib/openai/fetchOpenAIResult.ts` | 调用 OpenAI API，流式返回 + 缓存 |

---

## 2. 平台采集实现

### 2.1 Bilibili — 直接调官方 API

**流程：**

```
api.bilibili.com/x/web-interface/view?bvid=BVxxx
  → 拿到 subtitle.list（字幕 CDN 地址）
  → 下载 JSON 字幕文件 (i0.hdslb.com/bfs/ai_subtitle/...)
```

**多 P 视频额外步骤：**

```
api.bilibili.com/x/player/v2?aid={aid}&cid={cid}
  → 拿到该分 P 的 subtitle.subtitles
```

**核心代码：**

```typescript
// lib/bilibili/fetchBilibiliSubtitleUrls.ts
const sessdata = sample(process.env.BILIBILI_SESSION_TOKEN?.split(','))
const params = videoId.startsWith('av') ? `?aid=${videoId.slice(2)}` : `?bvid=${videoId}`
const requestUrl = `https://api.bilibili.com/x/web-interface/view${params}`

const headers = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    Host: 'api.bilibili.com',
    Cookie: `SESSDATA=${sessdata}`,
}
```

**字幕语言偏好：**

```typescript
const betterSubtitle = subtitleList.find(({ lan }) => lan === 'zh-CN') || subtitleList[0]
```

**反爬手段：**

| 手段 | 实现 |
|------|------|
| SESSDATA 轮换 | 环境变量存多个 session token，逗号分隔，每次请求 `sample()` 随机选一个 |
| UA 伪装 | Chrome macOS User-Agent |
| Host 头 | 显式设置 `Host: api.bilibili.com` |
| 无缓存 | `cache: 'no-cache', referrerPolicy: 'no-referrer'` |

### 2.2 YouTube — 第三方服务 SaveSubs.com

**流程：**

```
POST savesubs.com/action/extract（发送 YouTube URL）
  → 返回可用字幕列表
  → GET savesubs.com/{subtitle_url}?ext=json（下载字幕）
```

**核心代码：**

```typescript
// lib/youtube/fetchYoutubeSubtitleUrls.ts
export const SUBTITLE_DOWNLOADER_URL = 'https://savesubs.com'

const response = await fetch(SUBTITLE_DOWNLOADER_URL + '/action/extract', {
    method: 'POST',
    body: JSON.stringify({
        data: { url: `https://www.youtube.com/watch?v=${videoId}` },
    }),
    headers: {
        'Content-Type': 'text/plain',
        'User-Agent': 'Mozilla/5.0 (Macintosh; ...)',
        'X-Auth-Token': `${process.env.SAVESUBS_X_AUTH_TOKEN}`,
        'X-Requested-Domain': 'savesubs.com',
        'X-Requested-With': 'xmlhttprequest',
    },
})
```

**字幕语言偏好：**

```typescript
const betterSubtitle =
    find(subtitleList, { quality: 'zh-CN' }) ||
    find(subtitleList, { quality: 'English' }) ||
    find(subtitleList, { quality: 'English (auto' }) ||
    subtitleList[0]

// 带时间戳 → JSON 格式
const subtitleUrl = `${SUBTITLE_DOWNLOADER_URL}${betterSubtitle.url}?ext=json`
// 纯文本 → txt 格式
const subtitleUrl = `${SUBTITLE_DOWNLOADER_URL}${betterSubtitle.url}?ext=txt`
```

### 2.3 Douyin / TikTok — 完全未实现

v1 源码中没有任何抖音相关代码。`VideoService` 枚举：

```typescript
export enum VideoService {
  Bilibili = 'bilibili',
  Youtube = 'youtube',
  // todo: integrate with whisper API
  Podcast = 'podcast',    // 未实现
  Meeting = 'meeting',    // 未实现
  LocalVideo = 'local-video',  // 未实现
  LocalAudio = 'local-audio',  // 未实现
}
```

`fetchSubtitle.ts` 分发器只处理两个平台：

```typescript
if (service === VideoService.Youtube) {
    return await fetchYoutubeSubtitle(videoId, shouldShowTimestamp)
}
return await fetchBilibiliSubtitle(videoId, pageNumber, shouldShowTimestamp)
```

---

## 3. 没有字幕时的降级策略

v1 **没有 Whisper / 语音识别**（代码里标注 `// todo: integrate with whisper API`）。

降级链路：

1. 优先获取字幕 JSON
2. 没字幕 → 用视频描述（`desc` + `dynamic` 字段）
3. 描述也没有 → 返回 HTTP 501

```typescript
// buildSummarizeRequest.ts
const inputText = subtitlesArray
    ? getSmallSizeTranscripts(subtitlesArray, subtitlesArray)
    : descriptionText   // ← 降级到视频描述

if (!subtitlesArray && !descriptionText) {
    throw new SummarizeRequestError(501, 'No subtitle in the video')
}
```

前端错误提示：

```typescript
if (statusCode === 501) {
    toast({
        title: '啊叻？视频字幕不见了？！',
        description: `\n（这个视频太短了...\n或者还没有字幕哦！）`,
    })
}
```

---

## 4. 字幕后处理流水线

| 步骤 | 文件 | 逻辑 |
|------|------|------|
| 分组 | `reduceSubtitleTimestamp.ts` | 每 7 条字幕合并为 1 组，带时间戳 |
| 压缩 | `getSmallSizeTranscripts.ts` | 超过 6200 字节 → 随机删一半 → 递归，直到 fit |
| 构建 prompt | `prompt.ts` | `Title: "xxx"\nTranscript: "xxx"` 拼接 |

**压缩算法：**

```typescript
// getSmallSizeTranscripts.ts
if (byteLength > byteLimit) {
    const filtedData = filterHalfRandomly(newTextData)  // 随机删一半
    return getSmallSizeTranscripts(filtedData, oldTextData, byteLimit)  // 递归
}
```

---

## 5. 缓存与限流

- **Redis 缓存**（Upstash）：key 格式 `{videoId}-{language}-{detailLevel}-{model}`，命中缓存直接返回，不调 OpenAI
- **短链解析**：前端处理 `b23.tv` 短链，通过 `/api/b23tv` 接口解析为完整 BV 号

---

## 6. v1 开源版 vs BibiGPT Pro 对比

| 能力 | v1 开源版 | BibiGPT Pro (bibigpt.co API) |
|------|-----------|------------------------------|
| Bilibili | 直接调 API + SESSDATA 轮换 | ✅ |
| YouTube | SaveSubs.com 中转 | ✅ |
| 抖音 / TikTok | ❌ 不支持 | ✅ |
| 小红书 / Twitter | ❌ 不支持 | ✅ |
| 语音识别 (Whisper) | ❌ 不支持 (todo) | ✅ |
| 视频下载 | ❌ 不下载 | 云端处理 |
| 部署方式 | Next.js 自部署 | SaaS API |

---

## 7. 结论

BibiGPT v1 的核心思路是**不碰视频文件，只拿字幕文本**。Bilibili 用官方 API + 多账号轮换，YouTube 用 SaveSubs 第三方服务。抖音等平台的采集能力是商业版 BibiGPT Pro 的闭源实现，v1 开源代码中完全看不到。

我们的 `video_summarize` 项目调用的 `api.bibigpt.co` 接口，背后正是这个商业版的闭源能力。
