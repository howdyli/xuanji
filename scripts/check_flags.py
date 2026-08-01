"""临时自检：打印记忆相关 feature flags 的最终生效值。"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

from xiaopaw.config.validator import load_config  # noqa: E402

c = load_config(Path("config.yaml"))
f = c.feature_flags
flags = [
    "enable_remote_memory",
    "enable_pgvector_indexing",
    "enable_structured_tables",
    "enable_graph_memory",
    "enable_memory_sync",
    "enable_memory_extraction",
    "enable_memory_lifecycle",
    "enable_layered_recall",
    "enable_graph_query",
    "enable_memory_save_filelock",
    "enable_memory_save_filter",
]
for k in flags:
    print(k.ljust(32), getattr(f, k))
print("remote_timeout =", c.memory.remote_timeout)
