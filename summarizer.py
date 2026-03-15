"""Kimi (Moonshot) API wrapper for video content summarization."""

import json
import logging
from dataclasses import dataclass
from openai import OpenAI

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个短视频内容分析专家。请根据提供的视频标题、描述和语音转录文本，输出以下结构化分析：

1. **主题**: 一句话概括视频核心主题
2. **关键词**: 提取 3-5 个关键词，用逗号分隔
3. **情绪基调**: 分析视频的情绪倾向（如：积极/消极/中性/幽默/煽情/教育/争议 等）
4. **内容摘要**: 50-100 字概括视频内容
5. **目标受众**: 推测视频的目标受众群体

请严格以 JSON 格式输出，字段名使用中文：
{
  "主题": "",
  "关键词": [],
  "情绪基调": "",
  "内容摘要": "",
  "目标受众": ""
}"""


@dataclass
class Summary:
    theme: str
    keywords: list[str]
    sentiment: str
    abstract: str
    audience: str
    raw_response: str


def summarize(
    title: str,
    description: str,
    transcript: str,
    author: str,
    api_key: str,
    base_url: str = "https://api.moonshot.cn/v1",
    model: str = "moonshot-v1-8k",
) -> Summary:
    """Summarize video content using Kimi API.

    Args:
        title: Video title.
        description: Video description.
        transcript: Transcribed audio text.
        author: Video author/uploader.
        api_key: Moonshot API key.
        base_url: API base URL.
        model: Model name.

    Returns:
        Structured Summary.
    """
    if not api_key:
        raise ValueError("Kimi API key is required. Set KIMI_API_KEY env or config.yaml")

    # Build user prompt
    user_content = f"""## 视频信息
- 作者: {author}
- 标题: {title}
- 描述: {description or '无'}

## 语音转录
{transcript if transcript else '（无语音内容）'}"""

    # Truncate if too long for 8k context
    if len(user_content) > 6000:
        user_content = user_content[:6000] + "\n...(已截断)"

    client = OpenAI(api_key=api_key, base_url=base_url)

    log.info("Calling Kimi API (model=%s)...", model)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    raw = response.choices[0].message.content.strip()
    log.info("Kimi response received")

    # Parse JSON from response
    try:
        # Handle markdown code block wrapping
        json_str = raw
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]

        data = json.loads(json_str.strip())
        return Summary(
            theme=data.get("主题", ""),
            keywords=data.get("关键词", []),
            sentiment=data.get("情绪基调", ""),
            abstract=data.get("内容摘要", ""),
            audience=data.get("目标受众", ""),
            raw_response=raw,
        )
    except (json.JSONDecodeError, IndexError) as e:
        log.warning("Failed to parse JSON from Kimi response: %s", e)
        # Return raw text as fallback
        return Summary(
            theme="",
            keywords=[],
            sentiment="",
            abstract=raw,
            audience="",
            raw_response=raw,
        )
