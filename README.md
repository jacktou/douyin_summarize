# Douyin Summarize

抖音视频批量分析工作流：输入视频/主页链接 → 提取字幕 → AI 总结主题、关键词、情绪。

支持两种模式：**BibiGPT 云端模式**（推荐，无需下载视频）和**本地模式**（下载视频 + faster-whisper 转录）。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填入 API Key
cp config.yaml.example config.yaml

# 运行（BibiGPT + Kimi，默认模式）
python main.py "https://www.douyin.com/video/xxx"
```

## 使用方式

```bash
# BibiGPT 提取字幕 + Kimi 结构化分析（默认，推荐）
python main.py "https://www.douyin.com/video/xxx"

# BibiGPT 一站式总结（无需 Kimi Key）
python main.py "https://www.douyin.com/video/xxx" --summarizer bibigpt

# 本地模式：下载视频 + whisper 转录 + Kimi 分析（需要国内 IP）
python main.py "https://www.douyin.com/video/xxx" --mode local
```

## 两种模式对比

| | BibiGPT 模式（默认） | 本地模式 |
|---|---|---|
| 命令 | `python main.py <url>` | `python main.py <url> --mode local` |
| 原理 | BibiGPT 云端 API 提取字幕 | 下载视频 → ffmpeg 提取音频 → whisper 转录 |
| 依赖 | httpx, openai | ffmpeg, faster-whisper |
| IP 限制 | 无 | 需要国内 IP（抖音地域限制） |
| 速度 | 快（几秒） | 慢（取决于视频长度和 CPU/GPU） |
| 适用场景 | 服务器部署，海外机器 | 本地开发，有 GPU 加速 |

## 两种总结器

| | Kimi（默认） | BibiGPT |
|---|---|---|
| 命令 | `python main.py <url>` | `python main.py <url> --summarizer bibigpt` |
| 输出 | 结构化 JSON（主题/关键词/情绪/摘要/受众） | 自由文本（摘要/亮点/思考/术语） |
| 需要 | `kimi_api_key` | 仅 `bibigpt_api_key` |

## 配置

复制 `config.yaml.example` 为 `config.yaml`：

```yaml
# API Keys
kimi_api_key: "sk-your-moonshot-api-key"    # https://platform.moonshot.cn
bibigpt_api_key: "your-bibigpt-key"         # https://bibigpt.co

# 本地模式配置
cookies_path: "./cookies.txt"    # Netscape 格式 cookie 文件
whisper_model: "small"           # small/medium/large-v3
whisper_device: "cpu"            # cpu/cuda
whisper_compute_type: "int8"     # int8(CPU) / float16(GPU)

# 通用
output_dir: "./output"
max_videos: 1
proxy: ""
```

也支持环境变量覆盖：`KIMI_API_KEY`、`BIBIGPT_API_KEY`、`PROXY` 等。

## Cookie 导出（仅本地模式）

本地模式需要抖音登录态 cookie：

```bash
# 从浏览器复制 cookie 字符串后，用工具转换为 Netscape 格式
python convert_cookies.py
```

## 输出

分析结果保存到 `output/` 目录，包含 JSON 和 Markdown 两种格式：

```
output/
├── analysis_20260315_191758.json
└── analysis_20260315_191758.md
```

## 项目结构

```
douyin_summarize/
├── main.py              # CLI 入口，双模式 + 双总结器
├── bibigpt.py           # BibiGPT API 客户端（字幕 + 总结 + 异步任务兜底）
├── downloader.py        # iesdouyin.com SSR 解析器（本地模式）
├── transcriber.py       # faster-whisper 转录（本地模式）
├── summarizer.py        # Kimi 结构化分析
├── config.py            # 配置加载（YAML + 环境变量）
├── convert_cookies.py   # 浏览器 cookie 转 Netscape 格式
├── config.yaml.example  # 配置模板
├── SKILL.md             # OpenClaw Skill 定义
├── run.sh               # 快捷运行脚本
├── setup.sh             # 环境初始化脚本
└── requirements.txt     # Python 依赖
```

## OpenClaw 部署

本项目可作为 [OpenClaw](https://docs.openclaw.ai) Skill 使用。轻量版（纯 BibiGPT API）见独立仓库：[video_summarize](https://github.com/jacktou/video_summarize)。

## 相关文档

- [BibiGPT v1 源码分析报告](bibigpt_v1_analysis.md)

## License

MIT
