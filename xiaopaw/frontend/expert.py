"""SQLite-backed expert registry for the 玄机 platform.

Each expert is a pre-configured AI persona combining:
- A system prompt (role instructions injected into conversations)
- A set of associated skills (auto-enabled when the expert is selected)
- Display metadata (name, description, icon, category, tags, team)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Built-in experts (8 teams, matching workbuddy UI) ─────────────────────

_DEFAULT_EXPERTS = [
    {
        "name": "dev_team",
        "display_name": "软件开发团队",
        "description": "高效软件研发团队，产品经理定需求、架构师设计 + 拆任务、工程师批量实现代码、QA验证质量，协同完成从需求到交付的全流程。",
        "icon": "dev",
        "category": "技术工程",
        "tags": ["软件公司", "组织管理", "产品交付"],
        "team": "玄机团队",
        "usage_count": 28.5,
        "system_prompt": (
            "你是一个高效的软件开发团队协作系统。团队包含以下角色：\n"
            "- 产品经理：负责需求分析和优先级排序\n"
            "- 架构师：负责技术方案设计和任务拆解\n"
            "- 工程师：负责代码实现和单元测试\n"
            "- QA工程师：负责质量验证和缺陷管理\n\n"
            "请根据用户的开发需求，协调各角色完成从需求分析到代码交付的完整流程。"
        ),
        "skills": ["baidu_search", "web_browse"],
    },
    {
        "name": "trading_team",
        "display_name": "交易分析团队",
        "description": "13位专业角色分5阶段协作完成投资分析：技术面、基本面、新闻面、情绪面数据采集 → 多空辩论 → 风险评估 → 决策建议输出。",
        "icon": "trading",
        "category": "金融投资",
        "tags": ["交易策略", "风险管理", "市场分析"],
        "team": "玄机团队",
        "usage_count": 31.83,
        "system_prompt": (
            "你是一个专业的投资分析团队，包含以下专业角色：\n"
            "- 技术分析师：负责K线图和技术指标分析\n"
            "- 基本面分析师：负责财务报表和行业分析\n"
            "- 新闻分析师：负责实时新闻和事件影响分析\n"
            "- 情绪分析师：负责市场情绪和资金流向分析\n"
            "- 风控经理：负责风险评估和仓位管理建议\n\n"
            "请按照 数据采集→多空辩论→风险评估→决策建议 的流程为用户提供投资分析。"
        ),
        "skills": ["baidu_search", "web_browse"],
    },
    {
        "name": "content_team",
        "display_name": "内容创作专家团",
        "description": "AI驱动的多模态内容生产团队，覆盖文案创作、视频生成、图片设计、智能剪辑和跨语言改编，提供从创意到成品的全流程服务。",
        "icon": "content",
        "category": "内容创作",
        "tags": ["文案创作", "AI视频生成", "图片设计"],
        "team": "玄机团队",
        "usage_count": 31.07,
        "system_prompt": (
            "你是一个多模态内容创作团队，包含以下角色：\n"
            "- 创意总监：负责内容策划和创意方向\n"
            "- 文案专家：负责各类文案撰写（广告、社交媒体、长文）\n"
            "- 视觉设计师：负责图片设计和视觉呈现\n"
            "- 视频制作人：负责视频脚本和制作\n\n"
            "请根据用户的内容需求，协调各角色完成高质量的内容输出。"
        ),
        "skills": ["docx", "pdf"],
    },
    {
        "name": "ip_partner",
        "display_name": "IP智能资产合伙人",
        "description": "面向90后00后的 AI 合伙人来了。帮您把智能转型、创业IP、家族发展需求，整理成可落地的商业方案和可带走的智能资产包。",
        "icon": "ip",
        "category": "行业顾问",
        "tags": ["智能转型", "创业IP", "家族发展"],
        "team": "福帮手",
        "usage_count": 1.01,
        "system_prompt": (
            "你是一位专业的IP智能资产顾问，专注于帮助年轻创业者：\n"
            "1. 智能转型：将传统业务与AI技术结合\n"
            "2. 创业IP：打造个人品牌和商业IP\n"
            "3. 家族发展：规划家族事业和传承方案\n\n"
            "请以合伙人的角度，提供务实、可落地的商业建议。"
        ),
        "skills": ["baidu_search", "docx"],
    },
    {
        "name": "research_team",
        "display_name": "深度研究团队",
        "description": "深度研究报告输出，7角色5阶段聚合多源信息，经审稿修订循环输出带引用的专业报告。",
        "icon": "research",
        "category": "数据智能",
        "tags": ["深度调研", "报告撰写", "多源研究"],
        "team": "玄机团队",
        "usage_count": 21.49,
        "system_prompt": (
            "你是一个专业的深度研究团队，工作流程如下：\n"
            "1. 需求分析：明确研究问题和范围\n"
            "2. 数据采集：从多个来源收集信息（搜索引擎、学术数据库等）\n"
            "3. 信息整合：交叉验证不同来源，提炼关键发现\n"
            "4. 报告撰写：结构化输出，附带引用来源\n"
            "5. 审稿修订：质量检查和完善\n\n"
            "请为用户提供深度研究报告输出服务。"
        ),
        "skills": ["baidu_search", "web_browse", "search_memory", "docx"],
    },
    {
        "name": "cloud_support",
        "display_name": "云技术支持",
        "description": "三位专家组成的运维团队 — CloudQ 负责多云统一治理与架构可视化，AndonQ 负责工单管理与智能诊断，OpsQ 负责自动化运维与成本优化。",
        "icon": "cloud",
        "category": "技术工程",
        "tags": ["云运维", "多云治理", "云迁移"],
        "team": "云产品技术支持",
        "usage_count": 1.65,
        "system_prompt": (
            "你是一个专业的云技术支持团队，包含三位专家：\n"
            "- CloudQ：多云统一治理、架构可视化、云资源规划\n"
            "- AndonQ：工单管理、故障诊断、问题排查\n"
            "- OpsQ：自动化运维、CI/CD、成本优化\n\n"
            "请根据用户的云运维需求，提供专业技术支持。"
        ),
        "skills": ["baidu_search", "web_browse"],
    },
    {
        "name": "opc_team",
        "display_name": "一人公司专家团",
        "description": "基于《一人企业方法论》，9位专家陪你走完从资源盘点、利基定位到MVP、转化、复购的全流程。让一个人也能拥有一家「公司」。",
        "icon": "opc",
        "category": "OPC一人公司",
        "tags": ["一人公司", "商业模式", "经营复盘"],
        "team": "Easy",
        "usage_count": 20.62,
        "system_prompt": (
            "你是一个一人公司创业顾问团队，帮助个人创业者：\n"
            "1. 资源盘点：分析个人技能和资源优势\n"
            "2. 利基定位：找到适合自己的细分市场\n"
            "3. MVP设计：最小可行产品规划\n"
            "4. 转化策略：从流量到收入的转化设计\n"
            "5. 经营复盘：持续优化商业模式\n\n"
            "请以创业导师的角度，帮助一个人也能建立可持续的商业模式。"
        ),
        "skills": ["baidu_search", "docx"],
    },
    {
        "name": "stock_research",
        "display_name": "股票投研专家团",
        "description": "蒸馏了六位真实的炒股大神的实战经验，涵盖产业策略、信号捕捉、估值评估、抄底布局、基本面分析和资金风向研判。",
        "icon": "stock",
        "category": "金融投资",
        "tags": ["产业研判", "估值定价", "资金风向"],
        "team": "自选股",
        "usage_count": 15.41,
        "system_prompt": (
            "你是一个专业的股票投研团队，融合了六位投资专家的经验：\n"
            "- 产业策略师：行业周期和产业趋势分析\n"
            "- 信号捕捉师：技术信号和量价关系分析\n"
            "- 估值评估师：公司估值和安全边际计算\n"
            "- 布局策略师：仓位管理和买卖时机\n"
            "- 基本面分析师：财务报表和商业模式分析\n"
            "- 资金风向师：主力资金流向和市场情绪\n\n"
            "请为用户提供专业的股票投研分析（注：仅供参考，不构成投资建议）。"
        ),
        "skills": ["baidu_search", "web_browse"],
    },
]

# ── New columns to add (for migration) ────────────────────────────────────

_NEW_COLUMNS = [
    ("category", "TEXT", "'技术工程'"),
    ("tags", "TEXT", "'[]'"),
    ("team", "TEXT", "''"),
    ("usage_count", "REAL", "0"),
    ("avatar_url", "TEXT", "''"),
]


class ExpertRegistry:
    """Manages expert configurations in a SQLite database.

    Schema
    ------
    experts(id, name, display_name, description, icon, system_prompt, skills,
            category, tags, team, usage_count, avatar_url, created_at, updated_at)
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()
        self._migrate_schema()
        self._init_defaults()

    # ── schema ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS experts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    icon TEXT NOT NULL DEFAULT 'expert',
                    system_prompt TEXT NOT NULL DEFAULT '',
                    skills TEXT NOT NULL DEFAULT '[]',
                    category TEXT NOT NULL DEFAULT '技术工程',
                    tags TEXT NOT NULL DEFAULT '[]',
                    team TEXT NOT NULL DEFAULT '',
                    usage_count REAL NOT NULL DEFAULT 0,
                    avatar_url TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    def _migrate_schema(self) -> None:
        """Add new columns to existing table if missing."""
        with self._connect() as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(experts)").fetchall()}
            for col_name, col_type, col_default in _NEW_COLUMNS:
                if col_name not in existing:
                    try:
                        conn.execute(
                            f"ALTER TABLE experts ADD COLUMN {col_name} {col_type} NOT NULL DEFAULT {col_default}"
                        )
                        logger.info("expert: migrated schema — added column '%s'", col_name)
                    except sqlite3.OperationalError:
                        pass  # column already exists

    def _init_defaults(self) -> None:
        """Insert built-in experts if missing."""
        with self._connect() as conn:
            existing = {
                row[0]
                for row in conn.execute("SELECT name FROM experts").fetchall()
            }
            now = datetime.now(timezone.utc).isoformat()
            inserted = 0
            for exp in _DEFAULT_EXPERTS:
                if exp["name"] not in existing:
                    conn.execute(
                        """INSERT INTO experts
                           (name, display_name, description, icon, system_prompt, skills,
                            category, tags, team, usage_count, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            exp["name"],
                            exp["display_name"],
                            exp["description"],
                            exp["icon"],
                            exp["system_prompt"],
                            json.dumps(exp["skills"], ensure_ascii=False),
                            exp["category"],
                            json.dumps(exp["tags"], ensure_ascii=False),
                            exp["team"],
                            exp["usage_count"],
                            now,
                            now,
                        ),
                    )
                    inserted += 1
            if inserted:
                logger.info("expert: created %d default experts", inserted)

    # ── public API ────────────────────────────────────────────────────

    def list_all(self, category: str = "") -> list[dict]:
        """Return all experts, optionally filtered by category."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute(
                    "SELECT * FROM experts WHERE category = ? ORDER BY usage_count DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM experts ORDER BY usage_count DESC"
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_categories(self) -> list[dict]:
        """Return all categories with counts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM experts GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
        return [{"name": row[0], "count": row[1]} for row in rows]

    def get(self, name: str) -> dict | None:
        """Get a single expert by name."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM experts WHERE name = ?", (name,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def create(self, data: dict) -> dict:
        """Create a new expert. Raises ValueError on duplicate or invalid data."""
        name = (data.get("name") or "").strip()
        if not name or len(name) < 2 or len(name) > 40:
            raise ValueError("专家标识需要 2-40 个字符")
        display_name = (data.get("display_name") or "").strip()
        if not display_name:
            raise ValueError("显示名称不能为空")

        now = datetime.now(timezone.utc).isoformat()
        skills = data.get("skills", [])
        if isinstance(skills, list):
            skills = json.dumps(skills, ensure_ascii=False)
        tags = data.get("tags", [])
        if isinstance(tags, list):
            tags = json.dumps(tags, ensure_ascii=False)

        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO experts
                       (name, display_name, description, icon, system_prompt, skills,
                        category, tags, team, usage_count, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        name,
                        display_name,
                        data.get("description", ""),
                        data.get("icon", "expert"),
                        data.get("system_prompt", ""),
                        skills,
                        data.get("category", "技术工程"),
                        tags,
                        data.get("team", ""),
                        data.get("usage_count", 0),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"专家标识 '{name}' 已存在")

        return self.get(name)  # type: ignore[return-value]

    def update(self, name: str, data: dict) -> dict | None:
        """Update an existing expert. Returns updated dict or None if not found."""
        existing = self.get(name)
        if not existing:
            return None

        now = datetime.now(timezone.utc).isoformat()
        skills = data.get("skills", existing["skills"])
        if isinstance(skills, list):
            skills = json.dumps(skills, ensure_ascii=False)
        elif not isinstance(skills, str):
            skills = json.dumps(skills, ensure_ascii=False)

        tags = data.get("tags", existing["tags"])
        if isinstance(tags, list):
            tags = json.dumps(tags, ensure_ascii=False)
        elif not isinstance(tags, str):
            tags = json.dumps(tags, ensure_ascii=False)

        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE experts SET
                    display_name = COALESCE(?, display_name),
                    description = COALESCE(?, description),
                    icon = COALESCE(?, icon),
                    system_prompt = COALESCE(?, system_prompt),
                    skills = ?,
                    category = COALESCE(?, category),
                    tags = ?,
                    team = COALESCE(?, team),
                    usage_count = COALESCE(?, usage_count),
                    updated_at = ?
                   WHERE name = ?""",
                (
                    data.get("display_name"),
                    data.get("description"),
                    data.get("icon"),
                    data.get("system_prompt"),
                    skills,
                    data.get("category"),
                    tags,
                    data.get("team"),
                    data.get("usage_count"),
                    now,
                    name,
                ),
            )
        return self.get(name)

    def delete(self, name: str) -> bool:
        """Delete an expert. Returns True if deleted."""
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM experts WHERE name = ?", (name,))
            return cur.rowcount > 0

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row) -> dict | None:
        if row is None:
            return None
        skills_raw = row["skills"]
        try:
            skills = json.loads(skills_raw) if isinstance(skills_raw, str) else skills_raw
        except (json.JSONDecodeError, TypeError):
            skills = []
        tags_raw = row["tags"]
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        except (json.JSONDecodeError, TypeError):
            tags = []
        return {
            "id": row["id"],
            "name": row["name"],
            "display_name": row["display_name"],
            "description": row["description"],
            "icon": row["icon"],
            "system_prompt": row["system_prompt"],
            "skills": skills,
            "category": row["category"],
            "tags": tags,
            "team": row["team"],
            "usage_count": row["usage_count"],
            "avatar_url": row["avatar_url"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
