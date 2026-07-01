"""
千川 OAuth2.0 Token 管理 — 只读权限

仅申请素材报表读取权限：
  ✅ advertiser_report — 广告主报表
  ✅ creative_read — 素材只读
  ❌ ad_manage — 广告创建/修改
  ❌ campaign_manage — 计划管理
  ❌ bid_manage — 出价管理

存储: SQLite 表 qianchuan_tokens
"""

import os
import sqlite3
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import httpx

from .schemas import QianchuanToken


class QianchuanTokenManager:
    """千川 OAuth2.0 只读 Token 管理"""

    # 只读权限范围
    OAUTH_SCOPES = [
        "advertiser_report",         # 广告主报表（只读）
        "creative_read",             # 素材只读
    ]
    # 明确不申请: ad_manage, campaign_manage, bid_manage

    OAUTH_AUTH_URL = "https://ad.oceanengine.com/openapi/audit/oauth.html"
    TOKEN_URL = "https://ad.oceanengine.com/open_api/oauth2/access_token/"
    REFRESH_URL = "https://ad.oceanengine.com/open_api/oauth2/refresh_token/"

    def __init__(self, db_path: str, client_id: str = "", client_secret: str = "", redirect_uri: str = ""):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.client_id = client_id or os.getenv("QIANCHUAN_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("QIANCHUAN_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.getenv("QIANCHUAN_REDIRECT_URI", "http://localhost:8000/oauth/callback")
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS qianchuan_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL UNIQUE,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    advertiser_ids TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # OAuth state 防 CSRF
            conn.execute("""
                CREATE TABLE IF NOT EXISTS oauth_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    # ─── OAuth 授权流程 ────────────────────────────

    def generate_auth_url(self, user_id: str) -> tuple[str, str]:
        """生成授权链接 + state 参数（防 CSRF）"""
        state = hashlib.sha256(
            f"{user_id}{datetime.now().isoformat()}{secrets.token_hex(8)}".encode()
        ).hexdigest()[:32]

        # 保存 state
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO oauth_states (state, user_id, created_at) VALUES (?,?,?)",
                (state, user_id, datetime.now().isoformat())
            )

        auth_url = (
            f"{self.OAUTH_AUTH_URL}"
            f"?app_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope={','.join(self.OAUTH_SCOPES)}"
            f"&state={state}"
        )

        return auth_url, state

    def handle_callback(self, auth_code: str, state: str) -> dict:
        """OAuth 回调处理：用授权码换取 token"""
        # 验证 state
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM oauth_states WHERE state=?",
                (state,)
            ).fetchone()

            if not row:
                raise ValueError("无效的 OAuth state 参数，可能遭遇 CSRF 攻击")

            user_id = row["user_id"]
            conn.execute("DELETE FROM oauth_states WHERE state=?", (state,))

        # 换取 token
        resp = httpx.post(self.TOKEN_URL, json={
            "app_id": self.client_id,
            "secret": self.client_secret,
            "auth_code": auth_code,
        })
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Token 换取失败: {data.get('message', '未知错误')}")

        token = QianchuanToken(
            user_id=user_id,
            access_token=data["data"]["access_token"],
            refresh_token=data["data"]["refresh_token"],
            expires_at=(datetime.now() + timedelta(seconds=data["data"]["expires_in"])).isoformat(),
            advertiser_ids=data["data"].get("advertiser_ids", []),
        )

        self._save_token(token)
        return {"user_id": user_id, "advertiser_ids": token.advertiser_ids}

    # ─── Token 管理 ───────────────────────────────

    def _save_token(self, token: QianchuanToken):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO qianchuan_tokens
                    (user_id, access_token, refresh_token, expires_at, advertiser_ids, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    access_token=excluded.access_token,
                    refresh_token=excluded.refresh_token,
                    expires_at=excluded.expires_at,
                    advertiser_ids=excluded.advertiser_ids,
                    updated_at=excluded.updated_at
            """, (
                token.user_id, token.access_token, token.refresh_token,
                token.expires_at, str(token.advertiser_ids),
                token.created_at, token.updated_at
            ))

    def get_valid_token(self, user_id: str) -> Optional[str]:
        """获取有效 Token。过期自动刷新。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM qianchuan_tokens WHERE user_id=?",
                (user_id,)
            ).fetchone()

        if not row:
            return None

        expires = datetime.fromisoformat(row["expires_at"])
        if expires <= datetime.now() + timedelta(minutes=10):
            # 快过期了，刷新
            return self._refresh(row)

        return row["access_token"]

    def _refresh(self, token_row) -> str:
        """刷新 access_token"""
        resp = httpx.post(self.REFRESH_URL, json={
            "app_id": self.client_id,
            "secret": self.client_secret,
            "refresh_token": token_row["refresh_token"],
        })
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Token 刷新失败: {data.get('message', '')}")

        new_token = QianchuanToken(
            user_id=token_row["user_id"],
            access_token=data["data"]["access_token"],
            refresh_token=data["data"].get("refresh_token", token_row["refresh_token"]),
            expires_at=(datetime.now() + timedelta(seconds=data["data"]["expires_in"])).isoformat(),
            advertiser_ids=eval(token_row["advertiser_ids"]),
        )
        self._save_token(new_token)
        return new_token.access_token

    def is_authorized(self, user_id: str) -> bool:
        """用户是否已授权千川"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM qianchuan_tokens WHERE user_id=?",
                (user_id,)
            ).fetchone()
        return row is not None

    def get_advertiser_ids(self, user_id: str) -> list[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT advertiser_ids FROM qianchuan_tokens WHERE user_id=?",
                (user_id,)
            ).fetchone()
        if row:
            return eval(row["advertiser_ids"])
        return []
