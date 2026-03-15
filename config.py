"""Configuration loading from environment variables or config.yaml."""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.yaml"


@dataclass
class Config:
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "moonshot-v1-8k"
    cookies_path: str = str(Path(__file__).parent / "cookies.txt")
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    bibigpt_api_key: str = ""
    output_dir: str = str(Path(__file__).parent / "output")
    max_videos: int = 1
    proxy: str = ""  # e.g. http://127.0.0.1:7890


def load_config() -> Config:
    """Load config from config.yaml, then override with environment variables."""
    cfg = Config()

    # Load from YAML if exists
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            data = yaml.safe_load(f) or {}
        for key, val in data.items():
            if hasattr(cfg, key) and val is not None:
                setattr(cfg, key, val)

    # Environment overrides (higher priority)
    env_map = {
        "KIMI_API_KEY": "kimi_api_key",
        "KIMI_BASE_URL": "kimi_base_url",
        "KIMI_MODEL": "kimi_model",
        "COOKIES_PATH": "cookies_path",
        "WHISPER_MODEL": "whisper_model",
        "WHISPER_DEVICE": "whisper_device",
        "OUTPUT_DIR": "output_dir",
        "MAX_VIDEOS": "max_videos",
        "BIBIGPT_API_KEY": "bibigpt_api_key",
        "PROXY": "proxy",
    }
    for env_key, attr in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if attr == "max_videos":
                val = int(val)
            setattr(cfg, attr, val)

    # Ensure output dir exists
    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)

    return cfg
