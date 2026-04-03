import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import random
import re
import shlex
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode
from uuid import uuid4

import httpx
import paramiko
import uvicorn
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, case, create_engine, func, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, selectinload, sessionmaker


class Settings(BaseSettings):
    bot_token: str = ""
    internal_api_token: str = "change_me_internal_token"
    database_url: str = "sqlite:///./vpn.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"
    public_api_base_url: str = ""
    admin_telegram_id: int = 1549754103
    giveaway_admin_telegram_id: int = 0
    admin_panel_password: str = "change_me_admin_password"
    admin_session_secret: str = "change_me_admin_session_secret"
    admin_session_hours: int = 24
    subscription_price_rub: int = 199
    subscription_days_per_month: int = 30
    crypto_pay_api_token: str = ""
    crypto_pay_base_url: str = "https://pay.crypt.bot/api"
    crypto_pay_accepted_assets: str = "USDT,TON,BTC,ETH,LTC,BNB,TRX,USDC"
    crypto_pay_invoice_expires_in: int = 86400
    payment_gateway: str = "cryptopay"
    yoomoney_receiver: str = ""
    yoomoney_notification_secret: str = ""
    yoomoney_quickpay_form: str = "shop"
    yoomoney_payment_type: str = "AC"
    yoomoney_success_url: str = ""
    platega_merchant_id: str = ""
    platega_api_key: str = ""
    platega_base_url: str = "https://app.platega.io"
    platega_payment_method: int = 2
    # Platega payment method IDs (per docs): 2=SBP, 10=Cards (RUB), 13=Crypto.
    platega_payment_method_crypto: int = 13
    platega_payment_method_card: int = 10
    platega_payment_method_sbp: int = 2
    platega_return_url: str = ""
    platega_failed_url: str = ""
    referral_bonus_percent: int = 25
    min_topup_rub: int = 50
    max_topup_rub: int = 200000
    welcome_bonus_days: int = 3
    welcome_channel_url: str = "https://t.me/trumpxvpn"
    welcome_channel_chat: str = "@trumpxvpn"
    public_bot_url: str = "https://t.me/trumpvlessbot"
    public_help_url: str = "https://t.me/trumpvpnhelp"
    public_user_session_hours: int = 720
    payments_notify_chat_id: int = -1003861242059
    happ_import_url_template: str = "happ://add?url={url}"
    happ_download_url: str = "https://happ.su"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
SERVER_PROTOCOL_VLESS_REALITY = "vless_reality"
SERVER_PROTOCOL_HYSTERIA2 = "hysteria2"
SERVER_PROTOCOLS = {SERVER_PROTOCOL_VLESS_REALITY, SERVER_PROTOCOL_HYSTERIA2}
DEFAULT_VLESS_ADD_SCRIPT = "/opt/vpn/add_vless_user.sh"
DEFAULT_VLESS_REMOVE_SCRIPT = "/opt/vpn/remove_vless_user.sh"
DEFAULT_HYSTERIA2_ADD_SCRIPT = "/opt/vpn/add_hysteria2_user.sh"
DEFAULT_HYSTERIA2_REMOVE_SCRIPT = "/opt/vpn/remove_hysteria2_user.sh"
MAX_ACTIVE_CONFIGS_PER_USER = 3
SUBSCRIPTION_PLANS = [
    {
        "id": "m1",
        "label": "1 месяц",
        "months": 1,
        "price_rub": 199,
        "badge": "Старт",
    },
    {
        "id": "m3",
        "label": "3 месяца",
        "months": 3,
        "price_rub": 499,
        "badge": "Выгодно",
    },
    {
        "id": "m6",
        "label": "6 месяцев",
        "months": 6,
        "price_rub": 899,
        "badge": "Лучший выбор",
    },
    {
        "id": "y1",
        "label": "1 год",
        "months": 12,
        "price_rub": 1490,
        "badge": "Максимум выгоды",
    },
]


def referral_topup_bonus_percent() -> int:
    return max(25, int(settings.referral_bonus_percent or 0))


settings.referral_bonus_percent = referral_topup_bonus_percent()


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


engine = create_engine(settings.database_url, future=True, **_engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utc_now() -> datetime:
    return datetime.utcnow()


def subscription_plan_by_id(plan_id: str) -> dict[str, Any] | None:
    pid = str(plan_id or "").strip().lower()
    if not pid:
        return None
    for plan in SUBSCRIPTION_PLANS:
        if str(plan.get("id", "")).lower() == pid:
            return plan
    return None


def subscription_plan_days(plan: dict[str, Any]) -> int:
    months = int(plan.get("months") or 0)
    if months <= 0:
        return 0
    return max(1, int(settings.subscription_days_per_month)) * months


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return cur.fetchone() is not None


def _sqlite_column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    if not _sqlite_table_exists(conn, table):
        return False
    cur = conn.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols


def run_sqlite_migrations() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        return
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    conn = sqlite3.connect(db_path)
    try:
        # Users balance + referral binding
        if _sqlite_table_exists(conn, "users"):
            if not _sqlite_column_exists(conn, "users", "balance_rub"):
                conn.execute("ALTER TABLE users ADD COLUMN balance_rub INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "users", "trial_bonus_granted"):
                conn.execute("ALTER TABLE users ADD COLUMN trial_bonus_granted INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "users", "pending_discount_promo_id"):
                conn.execute("ALTER TABLE users ADD COLUMN pending_discount_promo_id INTEGER")
            if not _sqlite_column_exists(conn, "users", "referred_by_user_id"):
                conn.execute("ALTER TABLE users ADD COLUMN referred_by_user_id INTEGER")
            if not _sqlite_column_exists(conn, "users", "referral_signup_bonus_granted"):
                conn.execute("ALTER TABLE users ADD COLUMN referral_signup_bonus_granted INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "users", "referral_payment_bonus_granted"):
                conn.execute("ALTER TABLE users ADD COLUMN referral_payment_bonus_granted INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "users", "reminder_3d_until"):
                conn.execute("ALTER TABLE users ADD COLUMN reminder_3d_until DATETIME")
            if not _sqlite_column_exists(conn, "users", "reminder_1d_until"):
                conn.execute("ALTER TABLE users ADD COLUMN reminder_1d_until DATETIME")
        if _sqlite_table_exists(conn, "vpn_servers"):
            if not _sqlite_column_exists(conn, "vpn_servers", "protocol"):
                conn.execute(
                    f"ALTER TABLE vpn_servers ADD COLUMN protocol TEXT NOT NULL DEFAULT '{SERVER_PROTOCOL_VLESS_REALITY}'"
                )
            if not _sqlite_column_exists(conn, "vpn_servers", "hy2_obfs"):
                conn.execute("ALTER TABLE vpn_servers ADD COLUMN hy2_obfs TEXT")
            if not _sqlite_column_exists(conn, "vpn_servers", "hy2_obfs_password"):
                conn.execute("ALTER TABLE vpn_servers ADD COLUMN hy2_obfs_password TEXT")
            if not _sqlite_column_exists(conn, "vpn_servers", "hy2_alpn"):
                conn.execute("ALTER TABLE vpn_servers ADD COLUMN hy2_alpn TEXT NOT NULL DEFAULT 'h3'")
            if not _sqlite_column_exists(conn, "vpn_servers", "hy2_insecure"):
                conn.execute("ALTER TABLE vpn_servers ADD COLUMN hy2_insecure INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                f"UPDATE vpn_servers SET protocol = '{SERVER_PROTOCOL_VLESS_REALITY}' WHERE protocol IS NULL OR TRIM(protocol) = ''"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_vpn_servers_protocol ON vpn_servers (protocol)")
        if _sqlite_table_exists(conn, "payment_invoices"):
            if not _sqlite_column_exists(conn, "payment_invoices", "kind"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN kind TEXT NOT NULL DEFAULT 'topup'")
            if not _sqlite_column_exists(conn, "payment_invoices", "credited_rub"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN credited_rub INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "payment_invoices", "referral_bonus_rub"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN referral_bonus_rub INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "payment_invoices", "payable_rub"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN payable_rub INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE payment_invoices SET payable_rub = amount_rub WHERE payable_rub = 0")
            if not _sqlite_column_exists(conn, "payment_invoices", "promo_code_text"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN promo_code_text TEXT")
            if not _sqlite_column_exists(conn, "payment_invoices", "promo_discount_percent"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN promo_discount_percent INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "payment_invoices", "idempotency_key"):
                conn.execute("ALTER TABLE payment_invoices ADD COLUMN idempotency_key TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_payment_invoices_idempotency_key ON payment_invoices (idempotency_key)")
        if _sqlite_table_exists(conn, "server_load_samples"):
            if not _sqlite_column_exists(conn, "server_load_samples", "latency_ms"):
                conn.execute("ALTER TABLE server_load_samples ADD COLUMN latency_ms FLOAT NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "server_load_samples", "established_connections"):
                conn.execute("ALTER TABLE server_load_samples ADD COLUMN established_connections INTEGER NOT NULL DEFAULT 0")
            if not _sqlite_column_exists(conn, "server_load_samples", "active_devices_estimate"):
                conn.execute("ALTER TABLE server_load_samples ADD COLUMN active_devices_estimate INTEGER NOT NULL DEFAULT 0")
        if not _sqlite_table_exists(conn, "giveaways"):
            conn.execute(
                """
                CREATE TABLE giveaways (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    prize TEXT,
                    kind TEXT NOT NULL,
                    starts_at DATETIME,
                    ends_at DATETIME,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaways_kind ON giveaways (kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaways_enabled ON giveaways (enabled)")
        if not _sqlite_table_exists(conn, "giveaway_winners"):
            conn.execute(
                """
                CREATE TABLE giveaway_winners (
                    id INTEGER PRIMARY KEY,
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'draw',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaway_winners_giveaway_id ON giveaway_winners (giveaway_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaway_winners_user_id ON giveaway_winners (user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaway_winners_is_active ON giveaway_winners (is_active)")
        if not _sqlite_table_exists(conn, "giveaway_participants"):
            conn.execute(
                """
                CREATE TABLE giveaway_participants (
                    id INTEGER PRIMARY KEY,
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_giveaway_participants_giveaway_user ON giveaway_participants (giveaway_id, user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaway_participants_giveaway_id ON giveaway_participants (giveaway_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_giveaway_participants_user_id ON giveaway_participants (user_id)")
        if not _sqlite_table_exists(conn, "fortune_spins"):
            conn.execute(
                """
                CREATE TABLE fortune_spins (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    price_rub INTEGER NOT NULL DEFAULT 0,
                    prize_id TEXT NOT NULL,
                    prize_label TEXT NOT NULL,
                    prize_kind TEXT NOT NULL,
                    prize_value_int INTEGER NOT NULL DEFAULT 0,
                    reward_rub INTEGER NOT NULL DEFAULT 0,
                    reward_days INTEGER NOT NULL DEFAULT 0,
                    balance_before INTEGER NOT NULL DEFAULT 0,
                    balance_after INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_fortune_spins_user_id ON fortune_spins (user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_fortune_spins_created_at ON fortune_spins (created_at)")
        conn.commit()
    finally:
        conn.close()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    balance_rub: Mapped[int] = mapped_column(Integer, default=0)
    trial_bonus_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_discount_promo_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    referral_signup_bonus_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_payment_bonus_granted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_3d_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminder_1d_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    configs: Mapped[list["ClientConfig"]] = relationship(back_populates="user")
    payments: Mapped[list["PaymentInvoice"]] = relationship(back_populates="user")
    referral_rewards_earned: Mapped[list["ReferralReward"]] = relationship(
        back_populates="inviter",
        foreign_keys="ReferralReward.inviter_user_id",
    )
    referral_rewards_paid: Mapped[list["ReferralReward"]] = relationship(
        back_populates="payer",
        foreign_keys="ReferralReward.payer_user_id",
    )


class VpnServer(Base):
    __tablename__ = "vpn_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer, default=443)
    sni: Mapped[str] = mapped_column(String(255), default="www.cloudflare.com")
    public_key: Mapped[str] = mapped_column(String(255))
    short_id: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(32), default="chrome")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    protocol: Mapped[str] = mapped_column(String(32), default=SERVER_PROTOCOL_VLESS_REALITY, index=True)
    hy2_obfs: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hy2_obfs_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hy2_alpn: Mapped[str] = mapped_column(String(64), default="h3")
    hy2_insecure: Mapped[bool] = mapped_column(Boolean, default=False)

    ssh_host: Mapped[str] = mapped_column(String(255))
    ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), default="root")
    ssh_key_path: Mapped[str] = mapped_column(String(500))
    remote_add_script: Mapped[str] = mapped_column(String(500), default=DEFAULT_VLESS_ADD_SCRIPT)
    remote_remove_script: Mapped[str] = mapped_column(String(500), default=DEFAULT_VLESS_REMOVE_SCRIPT)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    configs: Mapped[list["ClientConfig"]] = relationship(back_populates="server")


class ClientConfig(Base):
    __tablename__ = "client_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("vpn_servers.id"), index=True)
    device_name: Mapped[str] = mapped_column(String(64))
    client_uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    email_tag: Mapped[str] = mapped_column(String(128))
    vless_url: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="configs")
    server: Mapped[VpnServer] = relationship(back_populates="configs")


class PaymentInvoice(Base):
    __tablename__ = "payment_invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    invoice_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    amount_rub: Mapped[int] = mapped_column(Integer)
    payable_rub: Mapped[int] = mapped_column(Integer, default=0)
    months: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(32), default="topup")
    promo_code_text: Mapped[str | None] = mapped_column(String(64), nullable=True)
    promo_discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    credited_rub: Mapped[int] = mapped_column(Integer, default=0)
    referral_bonus_rub: Mapped[int] = mapped_column(Integer, default=0)
    pay_url: Mapped[str] = mapped_column(Text)
    payload: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="payments")


class ServerLoadSample(Base):
    __tablename__ = "server_load_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("vpn_servers.id"), index=True)
    load1: Mapped[float] = mapped_column(Float, default=0.0)
    load5: Mapped[float] = mapped_column(Float, default=0.0)
    load15: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    established_connections: Mapped[int] = mapped_column(Integer, default=0)
    active_devices_estimate: Mapped[int] = mapped_column(Integer, default=0)
    xray_state: Mapped[str] = mapped_column(String(32), default="unknown")
    health: Mapped[str] = mapped_column(String(32), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    value_int: Mapped[int] = mapped_column(Integer)
    max_uses_total: Mapped[int] = mapped_column(Integer, default=0)
    max_uses_per_user: Mapped[int] = mapped_column(Integer, default=1)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    promo_code_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payment_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("payment_invoices.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    value_int: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class Giveaway(Base):
    __tablename__ = "giveaways"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prize: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class GiveawayParticipant(Base):
    __tablename__ = "giveaway_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey("giveaways.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class GiveawayWinner(Base):
    __tablename__ = "giveaway_winners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    giveaway_id: Mapped[int] = mapped_column(ForeignKey("giveaways.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(String(32), default="draw")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    user: Mapped[User] = relationship(foreign_keys=[user_id])


class FortuneSpin(Base):
    __tablename__ = "fortune_spins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    price_rub: Mapped[int] = mapped_column(Integer, default=0)
    prize_id: Mapped[str] = mapped_column(String(32))
    prize_label: Mapped[str] = mapped_column(String(128))
    prize_kind: Mapped[str] = mapped_column(String(32))
    prize_value_int: Mapped[int] = mapped_column(Integer, default=0)
    reward_rub: Mapped[int] = mapped_column(Integer, default=0)
    reward_days: Mapped[int] = mapped_column(Integer, default=0)
    balance_before: Mapped[int] = mapped_column(Integer, default=0)
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    inviter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payment_invoice_id: Mapped[int] = mapped_column(ForeignKey("payment_invoices.id"), unique=True, index=True)
    bonus_rub: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    payer: Mapped[User] = relationship(foreign_keys=[payer_user_id], back_populates="referral_rewards_paid")
    inviter: Mapped[User] = relationship(foreign_keys=[inviter_user_id], back_populates="referral_rewards_earned")


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    request_path: Mapped[str] = mapped_column(String(255), default="")
    remote_addr: Mapped[str] = mapped_column(String(64), default="")
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class RegisterUserRequest(BaseModel):
    telegram_id: int
    username: str | None = None
    referrer_telegram_id: int | None = None


class ExtendSubscriptionRequest(BaseModel):
    telegram_id: int
    days: int = Field(gt=0, le=3650)


class ConfigIssueRequest(BaseModel):
    telegram_id: int
    server_id: int
    device_name: str = Field(min_length=2, max_length=64)


class ConfigRevokeRequest(BaseModel):
    telegram_id: int
    config_id: int


class UpsertServerRequest(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    protocol: str = SERVER_PROTOCOL_VLESS_REALITY
    host: str
    port: int = 443
    sni: str = "www.cloudflare.com"
    public_key: str = ""
    short_id: str = ""
    fingerprint: str = "chrome"
    hy2_obfs: str | None = None
    hy2_obfs_password: str | None = None
    hy2_alpn: str = "h3"
    hy2_insecure: bool = False
    enabled: bool = True
    ssh_host: str
    ssh_port: int = 22
    ssh_user: str = "root"
    ssh_key_path: str
    remote_add_script: str = DEFAULT_VLESS_ADD_SCRIPT
    remote_remove_script: str = DEFAULT_VLESS_REMOVE_SCRIPT


class CreatePaymentRequest(BaseModel):
    telegram_id: int
    amount_rub: int = Field(ge=1, le=1_000_000)
    gateway: str | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)


class CheckPaymentRequest(BaseModel):
    telegram_id: int
    invoice_id: int


class RenewFromBalanceRequest(BaseModel):
    telegram_id: int


class PurchaseSubscriptionPlanRequest(BaseModel):
    telegram_id: int
    plan_id: str = Field(min_length=2, max_length=16)


class ClaimWelcomeBonusRequest(BaseModel):
    telegram_id: int


class ApplyPromoRequest(BaseModel):
    telegram_id: int
    code: str = Field(min_length=2, max_length=64)


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class TelegramMiniAppAuthRequest(BaseModel):
    init_data: str = Field(min_length=10, max_length=8192)


class PublicAnalyticsEventRequest(BaseModel):
    event: str = Field(min_length=2, max_length=64)
    meta: dict[str, Any] = Field(default_factory=dict)


def require_internal_token(x_internal_token: str = Header(default="")) -> None:
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


ADMIN_COOKIE = "vpn_admin_session"


def _session_secret() -> str:
    return settings.admin_session_secret or settings.internal_api_token


def _sign_session(raw_payload: str) -> str:
    return hmac.new(_session_secret().encode("utf-8"), raw_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_admin_session_token(admin_id: int) -> str:
    payload = {
        "admin_id": admin_id,
        "exp": int(time.time()) + max(1, settings.admin_session_hours) * 3600,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    body = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")
    signature = _sign_session(body)
    return f"{body}.{signature}"


def parse_admin_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign_session(body), signature):
        return None
    padded = body + "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = int(payload.get("exp", 0))
    admin_id = int(payload.get("admin_id", 0))
    if exp < int(time.time()) or admin_id != settings.admin_telegram_id:
        return None
    return payload


def require_admin_session(request: Request) -> int | None:
    token = request.cookies.get(ADMIN_COOKIE)
    payload = parse_admin_session_token(token)
    if not payload:
        return None
    return int(payload["admin_id"])


PUBLIC_USER_COOKIE = "vpn_user_session"


def make_public_user_session_token(telegram_id: int) -> str:
    payload = {
        "telegram_id": int(telegram_id),
        "exp": int(time.time()) + max(1, int(settings.public_user_session_hours or 720)) * 3600,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    body = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8").rstrip("=")
    signature = _sign_session(body)
    return f"{body}.{signature}"


def parse_public_user_session_token(token: str | None) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign_session(body), signature):
        return None
    padded = body + "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = int(payload.get("exp", 0))
    telegram_id = int(payload.get("telegram_id", 0))
    if exp < int(time.time()) or telegram_id <= 0:
        return None
    return payload


def _request_is_https(request: Request | None) -> bool:
    if not request:
        return False
    proto = str(request.headers.get("x-forwarded-proto", "")).strip().lower()
    if proto:
        return proto == "https"
    return str(getattr(request.url, "scheme", "")).lower() == "https"


def _set_public_user_cookie(response: Any, telegram_id: int, request: Request | None = None) -> None:
    is_https = _request_is_https(request)
    response.set_cookie(
        key=PUBLIC_USER_COOKIE,
        value=make_public_user_session_token(int(telegram_id)),
        max_age=max(1, int(settings.public_user_session_hours or 720)) * 3600,
        httponly=True,
        secure=is_https,
        # Telegram Mini App can treat requests as embedded context on some clients.
        # SameSite=None + Secure improves cookie delivery reliability there.
        samesite="none" if is_https else "lax",
        path="/",
    )


def _clear_public_user_cookie(response: Any) -> None:
    response.delete_cookie(key=PUBLIC_USER_COOKIE, path="/")


def _verify_telegram_auth_payload(payload: TelegramAuthRequest) -> tuple[int, str | None]:
    bot_token = str(settings.bot_token or "").strip()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram auth is not configured")

    auth_date = int(payload.auth_date or 0)
    now_ts = int(time.time())
    if auth_date <= 0 or auth_date < now_ts - 86400 or auth_date > now_ts + 600:
        raise HTTPException(status_code=401, detail="Telegram auth expired")

    data = payload.model_dump(exclude_none=True)
    provided_hash = str(data.pop("hash", "") or "").strip().lower()
    if not provided_hash:
        raise HTTPException(status_code=401, detail="Invalid Telegram auth payload")

    check_parts = [f"{key}={data[key]}" for key in sorted(data.keys())]
    data_check_string = "\n".join(check_parts)
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise HTTPException(status_code=401, detail="Telegram auth signature mismatch")

    telegram_id = int(payload.id or 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid Telegram user")
    return telegram_id, str(payload.username or "").strip() or None


def _verify_telegram_miniapp_init_data(init_data_raw: str) -> tuple[int, str | None]:
    bot_token = str(settings.bot_token or "").strip()
    if not bot_token:
        raise HTTPException(status_code=503, detail="Telegram auth is not configured")
    init_data = str(init_data_raw or "").strip()
    if not init_data or "=" not in init_data:
        raise HTTPException(status_code=401, detail="Invalid init_data")

    parsed = parse_qs(init_data, keep_blank_values=True, strict_parsing=False)
    provided_hash = str((parsed.pop("hash", [""])[0] or "")).strip().lower()
    if not provided_hash:
        raise HTTPException(status_code=401, detail="Invalid init_data hash")

    flat: dict[str, str] = {}
    for key, values in parsed.items():
        if not values:
            flat[str(key)] = ""
        else:
            flat[str(key)] = str(values[0] or "")
    auth_date = int(flat.get("auth_date") or 0)
    now_ts = int(time.time())
    if auth_date <= 0 or auth_date < now_ts - 86400 or auth_date > now_ts + 600:
        raise HTTPException(status_code=401, detail="Telegram auth expired")

    data_check_string = "\n".join(f"{key}={flat[key]}" for key in sorted(flat.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, provided_hash):
        raise HTTPException(status_code=401, detail="Telegram mini app signature mismatch")

    user_raw = str(flat.get("user") or "").strip()
    user_payload: dict[str, Any] = {}
    if user_raw:
        try:
            decoded = json.loads(user_raw)
            if isinstance(decoded, dict):
                user_payload = decoded
        except Exception:
            user_payload = {}
    telegram_id = int(user_payload.get("id") or 0)
    if telegram_id <= 0:
        raise HTTPException(status_code=401, detail="Telegram user not found in init_data")
    username = str(user_payload.get("username") or "").strip() or None
    return telegram_id, username


def _public_user_from_request(request: Request, db: Session) -> User:
    token = request.cookies.get(PUBLIC_USER_COOKIE)
    if not token:
        token = str(request.headers.get("x-public-session", "") or "").strip()
    payload = parse_public_user_session_token(token)
    telegram_id = int(payload.get("telegram_id") or 0) if payload else 0
    if telegram_id > 0:
        user = fetch_user_with_configs(db, telegram_id)
        if user:
            return user

    # Fallback for Telegram Mini App when client cookies are not persisted.
    init_data = str(request.headers.get("x-telegram-init-data", "") or "").strip()
    if init_data:
        telegram_id, username = _verify_telegram_miniapp_init_data(init_data)
        user = get_or_create_user(db, telegram_id=telegram_id, username=username)
        loaded = fetch_user_with_configs(db, telegram_id)
        if loaded:
            return loaded
        return user

    raise HTTPException(
        status_code=401,
        detail={
            "code": "auth_required",
            "message": "Требуется авторизация в Telegram Mini App.",
        },
    )


def _public_cabinet_payload(db: Session, user: User) -> dict[str, Any]:
    invited_count, total_bonus = user_referral_stats(db, int(user.id))
    active = active_giveaways(telegram_id=int(user.telegram_id), db=db)
    payments = list_payments(int(user.telegram_id), db=db)
    fortune = _fortune_state_for_user(db, user)
    return {
        "user": serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus),
        "plans": [
            {
                "id": str(plan.get("id") or ""),
                "label": str(plan.get("label") or ""),
                "months": int(plan.get("months") or 0),
                "price_rub": int(plan.get("price_rub") or 0),
                "badge": str(plan.get("badge") or ""),
                "days": int(subscription_plan_days(plan)),
            }
            for plan in SUBSCRIPTION_PLANS
        ],
        "payment": {
            "min_topup_rub": int(settings.min_topup_rub),
            "max_topup_rub": int(settings.max_topup_rub),
            "gateway": str(settings.payment_gateway or "cryptopay"),
            "price_rub": int(settings.subscription_price_rub),
        },
        "giveaways": active,
        "fortune": fortune,
        "payments": payments,
    }


def make_user_subscription_token(telegram_id: int) -> str:
    raw = f"sub:{int(telegram_id)}"
    return hmac.new(_session_secret().encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_user_subscription_token(telegram_id: int, token: str) -> bool:
    expected = make_user_subscription_token(telegram_id)
    return bool(token) and hmac.compare_digest(expected, str(token))


def public_api_base_url() -> str:
    base = str(settings.public_api_base_url or settings.api_base_url).strip()
    return base.rstrip("/")


def build_user_subscription_url(telegram_id: int) -> str:
    base = public_api_base_url()
    return f"{base}/sub/{int(telegram_id)}/{make_user_subscription_token(telegram_id)}"


def _normalize_device_token(raw: str, max_len: int = 64) -> str:
    filtered = "".join(ch for ch in str(raw or "").strip().lower() if ch.isalnum() or ch in ("-", "_"))
    return filtered[:max_len]


def build_user_subscription_url_for_device(
    telegram_id: int,
    device_name: str | None = None,
    device_id: str | None = None,
) -> str:
    base_url = build_user_subscription_url(telegram_id)
    params: dict[str, str] = {}
    name = _normalize_device_token(device_name or "", max_len=40)
    did = _normalize_device_token(device_id or "", max_len=32)
    if name:
        params["device_name"] = name
    if did:
        params["device_id"] = did
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def is_subscription_active(user: User) -> bool:
    return bool(user.subscription_until and user.subscription_until > utc_now())


def get_or_create_user(
    db: Session,
    telegram_id: int,
    username: str | None = None,
    referrer_telegram_id: int | None = None,
) -> User:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user:
        if username and user.username != username:
            user.username = username
            db.commit()
            db.refresh(user)
        return user

    referred_by_user_id = None
    inviter: User | None = None
    if referrer_telegram_id and referrer_telegram_id > 0 and referrer_telegram_id != telegram_id:
        referrer = db.scalar(select(User).where(User.telegram_id == referrer_telegram_id))
        if referrer:
            inviter = referrer
            referred_by_user_id = referrer.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        balance_rub=0,
        referred_by_user_id=referred_by_user_id,
    )
    db.add(user)
    db.flush()
    if inviter:
        apply_referral_signup_bonus(db, user, inviter)
    db.commit()
    db.refresh(user)
    return user


def extend_subscription(db: Session, user: User, days: int) -> User:
    base = utc_now()
    if user.subscription_until and user.subscription_until > base:
        base = user.subscription_until
    user.subscription_until = base + timedelta(days=days)
    db.commit()
    db.refresh(user)
    return user


def charge_balance_for_subscription(db: Session, user: User, periods: int = 1) -> bool:
    if periods <= 0:
        return False
    price = max(1, settings.subscription_price_rub) * periods
    if int(user.balance_rub or 0) < price:
        return False
    user.balance_rub = int(user.balance_rub or 0) - price
    days = max(1, settings.subscription_days_per_month) * periods
    base = utc_now()
    if user.subscription_until and user.subscription_until > base:
        base = user.subscription_until
    user.subscription_until = base + timedelta(days=days)
    db.commit()
    db.refresh(user)
    return True


def ensure_active_subscription_from_balance(db: Session, user: User) -> bool:
    if is_subscription_active(user):
        return True
    return charge_balance_for_subscription(db, user, periods=1)


def apply_referral_bonus(db: Session, payer: User, payment: PaymentInvoice) -> int:
    if not payer.referred_by_user_id:
        return 0
    exists = db.scalar(select(ReferralReward).where(ReferralReward.payment_invoice_id == payment.id))
    if exists:
        return int(exists.bonus_rub)
    inviter = db.scalar(select(User).where(User.id == payer.referred_by_user_id))
    if not inviter:
        return 0
    percent = referral_topup_bonus_percent()
    bonus = int(payment.amount_rub * percent / 100)
    if bonus <= 0:
        return 0
    inviter.balance_rub = int(inviter.balance_rub or 0) + bonus
    reward = ReferralReward(
        payer_user_id=payer.id,
        inviter_user_id=inviter.id,
        payment_invoice_id=payment.id,
        bonus_rub=bonus,
    )
    db.add(reward)
    payment.referral_bonus_rub = bonus
    return bonus


def apply_referral_signup_bonus(db: Session, invitee: User, inviter: User) -> bool:
    if invitee.referral_signup_bonus_granted:
        return False
    _apply_subscription_days_no_commit(invitee, 3)
    _apply_subscription_days_no_commit(inviter, 3)
    invitee.referral_signup_bonus_granted = True
    return True


def apply_referral_payment_days_bonus(
    db: Session,
    invitee: User,
    payment: PaymentInvoice,
    bonus_days: int = 7,
    window_days: int = 7,
) -> bool:
    if not invitee.referred_by_user_id or invitee.referral_payment_bonus_granted:
        return False
    if not invitee.created_at:
        return False
    paid_at = payment.paid_at or utc_now()
    if paid_at > invitee.created_at + timedelta(days=max(1, int(window_days))):
        return False
    inviter = db.scalar(select(User).where(User.id == invitee.referred_by_user_id))
    if not inviter:
        return False
    _apply_subscription_days_no_commit(inviter, max(1, int(bonus_days)))
    invitee.referral_payment_bonus_granted = True
    return True


def user_referral_stats(db: Session, user_id: int) -> tuple[int, int]:
    invited_count = int(db.scalar(select(func.count(User.id)).where(User.referred_by_user_id == user_id)) or 0)
    total_bonus = int(
        db.scalar(select(func.coalesce(func.sum(ReferralReward.bonus_rub), 0)).where(ReferralReward.inviter_user_id == user_id))
        or 0
    )
    return invited_count, total_bonus


PROMO_KIND_BALANCE = "balance_rub"
PROMO_KIND_TOPUP_DISCOUNT = "topup_discount_percent"
PROMO_KIND_SUBSCRIPTION_DAYS = "subscription_days"
PROMO_KINDS = {PROMO_KIND_BALANCE, PROMO_KIND_TOPUP_DISCOUNT, PROMO_KIND_SUBSCRIPTION_DAYS}

GIVEAWAY_KIND_CHANNEL_SUB = "channel_sub"
GIVEAWAY_KIND_ACTIVE_SUB_MIN_DEPOSIT = "active_sub_min_deposit"
GIVEAWAY_KIND_REFERRAL_LEADER = "referral_leader"
GIVEAWAY_KINDS = {
    GIVEAWAY_KIND_CHANNEL_SUB,
    GIVEAWAY_KIND_ACTIVE_SUB_MIN_DEPOSIT,
    GIVEAWAY_KIND_REFERRAL_LEADER,
}
GIVEAWAY_MAX_ACTIVE = 3
GIVEAWAY_MIN_DEPOSIT_RUB = 50

FORTUNE_SPIN_PRICE_RUB = 19
FORTUNE_PRIZES: list[dict[str, Any]] = [
    {"id": "rub_100", "label": "100 RUB", "kind": "balance_rub", "value_int": 100, "weight": 1, "color": "#facc15", "emoji": "💰"},
    {"id": "days_7", "label": "7 days subscription", "kind": "subscription_days", "value_int": 7, "weight": 2, "color": "#ef4444", "emoji": "📅"},
    {"id": "days_1", "label": "1 day subscription", "kind": "subscription_days", "value_int": 1, "weight": 6, "color": "#3b82f6", "emoji": "🗓️"},
    {"id": "rub_5", "label": "5 RUB", "kind": "balance_rub", "value_int": 5, "weight": 10, "color": "#a855f7", "emoji": "💸"},
    {"id": "rub_1", "label": "1 RUB", "kind": "balance_rub", "value_int": 1, "weight": 12, "color": "#60a5fa", "emoji": "🪙"},
    {"id": "try_next", "label": "Try next time", "kind": "nothing", "value_int": 0, "weight": 14, "color": "#64748b", "emoji": "🍀"},
    {"id": "nothing", "label": "Nothing", "kind": "nothing", "value_int": 0, "weight": 16, "color": "#6b4b5e", "emoji": "🙃"},
]


def _fortune_prize_public_item(prize: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(prize.get("id") or ""),
        "label": str(prize.get("label") or ""),
        "kind": str(prize.get("kind") or ""),
        "value_int": int(prize.get("value_int") or 0),
        "weight": int(prize.get("weight") or 0),
        "color": str(prize.get("color") or "#64748b"),
        "emoji": str(prize.get("emoji") or "🎁"),
    }


def _fortune_pick_prize() -> dict[str, Any]:
    pool = list(FORTUNE_PRIZES)
    weights = [max(1, int(item.get("weight") or 1)) for item in pool]
    return random.choices(pool, weights=weights, k=1)[0]


def _fortune_spin_to_dict(item: FortuneSpin) -> dict[str, Any]:
    return {
        "id": int(item.id),
        "price_rub": int(item.price_rub or 0),
        "prize_id": str(item.prize_id or ""),
        "prize_label": str(item.prize_label or ""),
        "prize_kind": str(item.prize_kind or ""),
        "prize_value_int": int(item.prize_value_int or 0),
        "reward_rub": int(item.reward_rub or 0),
        "reward_days": int(item.reward_days or 0),
        "balance_before": int(item.balance_before or 0),
        "balance_after": int(item.balance_after or 0),
        "created_at": _fmt_dt(item.created_at),
    }


def _fortune_recent_spins(db: Session, user_id: int, limit: int = 15) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(FortuneSpin)
        .where(FortuneSpin.user_id == int(user_id))
        .order_by(FortuneSpin.created_at.desc(), FortuneSpin.id.desc())
        .limit(max(1, int(limit)))
    ).all()
    return [_fortune_spin_to_dict(item) for item in rows]


def _fortune_state_for_user(db: Session, user: User, include_recent_limit: int = 15) -> dict[str, Any]:
    balance = int(user.balance_rub or 0)
    active_sub = is_subscription_active(user)
    can_spin = active_sub and balance >= int(FORTUNE_SPIN_PRICE_RUB)
    reason = ""
    if not active_sub:
        reason = "Active subscription required"
    elif balance < int(FORTUNE_SPIN_PRICE_RUB):
        reason = f"Need {FORTUNE_SPIN_PRICE_RUB} RUB to spin"

    return {
        "price_rub": int(FORTUNE_SPIN_PRICE_RUB),
        "can_spin": bool(can_spin),
        "reason": reason,
        "balance_rub": balance,
        "subscription_active": bool(active_sub),
        "prizes": [_fortune_prize_public_item(item) for item in FORTUNE_PRIZES],
        "recent": _fortune_recent_spins(db, int(user.id), limit=include_recent_limit),
    }


def _apply_fortune_spin(db: Session, user: User) -> dict[str, Any]:
    balance_before = int(user.balance_rub or 0)
    price = int(FORTUNE_SPIN_PRICE_RUB)
    if not is_subscription_active(user):
        raise HTTPException(status_code=400, detail="Active subscription required for Fortune Wheel")
    if balance_before < price:
        missing = price - balance_before
        raise HTTPException(status_code=400, detail=f"Insufficient balance. Need {price} RUB, missing {missing} RUB")

    user.balance_rub = balance_before - price
    prize = _fortune_pick_prize()
    prize_kind = str(prize.get("kind") or "nothing")
    prize_value_int = int(prize.get("value_int") or 0)
    reward_rub = 0
    reward_days = 0
    if prize_kind == "balance_rub" and prize_value_int > 0:
        reward_rub = prize_value_int
        user.balance_rub = int(user.balance_rub or 0) + reward_rub
    elif prize_kind == "subscription_days" and prize_value_int > 0:
        reward_days = prize_value_int
        _apply_subscription_days_no_commit(user, reward_days)

    balance_after = int(user.balance_rub or 0)
    spin = FortuneSpin(
        user_id=int(user.id),
        price_rub=price,
        prize_id=str(prize.get("id") or ""),
        prize_label=str(prize.get("label") or ""),
        prize_kind=prize_kind,
        prize_value_int=prize_value_int,
        reward_rub=reward_rub,
        reward_days=reward_days,
        balance_before=balance_before,
        balance_after=balance_after,
    )
    db.add(spin)
    db.commit()
    db.refresh(user)
    db.refresh(spin)
    return _fortune_spin_to_dict(spin)


def _is_giveaway_active(giveaway: Giveaway, now: datetime | None = None) -> bool:
    now = now or utc_now()
    if not bool(giveaway.enabled):
        return False
    if giveaway.starts_at and giveaway.starts_at > now:
        return False
    if giveaway.ends_at and giveaway.ends_at <= now:
        return False
    return True


def _giveaway_kind_title(kind: str) -> str:
    if kind == GIVEAWAY_KIND_CHANNEL_SUB:
        return "РџРѕРґРїРёСЃРєР° РЅР° РіСЂСѓРїРїСѓ"
    if kind == GIVEAWAY_KIND_ACTIVE_SUB_MIN_DEPOSIT:
        return "РђРєС‚РёРІРЅР°СЏ РїРѕРґРїРёСЃРєР° + РґРµРїРѕР·РёС‚"
    if kind == GIVEAWAY_KIND_REFERRAL_LEADER:
        return "Р›РёРґРµСЂ РїРѕ СЂРµС„РµСЂР°Р»Р°Рј"
    return kind


def _giveaway_condition_text(kind: str) -> str:
    if kind == GIVEAWAY_KIND_CHANNEL_SUB:
        return "РџРѕРґРїРёСЃРєР° РЅР° РіСЂСѓРїРїСѓ (С‚Р° Р¶Рµ, С‡С‚Рѕ РґР»СЏ Р±РѕРЅСѓСЃР° +3 РґРЅСЏ)."
    if kind == GIVEAWAY_KIND_ACTIVE_SUB_MIN_DEPOSIT:
        return f"РђРєС‚РёРІРЅР°СЏ РїРѕРґРїРёСЃРєР° Рё РґРµРїРѕР·РёС‚ РѕС‚ {GIVEAWAY_MIN_DEPOSIT_RUB} RUB."
    if kind == GIVEAWAY_KIND_REFERRAL_LEADER:
        return "Р‘РѕР»СЊС€Рµ РІСЃРµРіРѕ СЂРµС„РµСЂР°Р»РѕРІ Р·Р° РІСЂРµРјСЏ СЂРѕР·С‹РіСЂС‹С€Р°."
    return str(kind or "")


def _is_user_subscribed_to_welcome_channel_sync(telegram_id: int) -> bool:
    chat_id = _welcome_channel_chat_id()
    member = _telegram_get_chat_member(chat_id, telegram_id)
    if not member:
        return False
    status_value = str(member.get("status") or "").strip().lower()
    return status_value not in {"left", "kicked"}


def _giveaway_period_bounds(giveaway: Giveaway) -> tuple[datetime | None, datetime | None]:
    return giveaway.starts_at, giveaway.ends_at


def _giveaway_participant_ids(db: Session, giveaway_id: int) -> set[int]:
    rows = db.scalars(
        select(GiveawayParticipant.user_id).where(GiveawayParticipant.giveaway_id == giveaway_id)
    ).all()
    return {int(x) for x in rows if x}


def _giveaway_participant_count(db: Session, giveaway_id: int) -> int:
    return int(
        db.scalar(select(func.count(GiveawayParticipant.id)).where(GiveawayParticipant.giveaway_id == giveaway_id)) or 0
    )


def _eligible_users_for_giveaway(db: Session, giveaway: Giveaway) -> list[User]:
    kind = str(giveaway.kind or "")
    now = utc_now()
    participant_ids = _giveaway_participant_ids(db, int(giveaway.id or 0))
    if not participant_ids:
        return []
    if kind == GIVEAWAY_KIND_CHANNEL_SUB:
        users = db.scalars(select(User).where(User.is_blocked.is_(False), User.id.in_(participant_ids))).all()
        return [u for u in users if _is_user_subscribed_to_welcome_channel_sync(int(u.telegram_id or 0))]

    if kind == GIVEAWAY_KIND_ACTIVE_SUB_MIN_DEPOSIT:
        start_dt, end_dt = _giveaway_period_bounds(giveaway)
        payment_filters = [
            PaymentInvoice.status == "paid",
            PaymentInvoice.amount_rub >= GIVEAWAY_MIN_DEPOSIT_RUB,
            PaymentInvoice.kind.ilike("topup%"),
            PaymentInvoice.paid_at.is_not(None),
        ]
        if start_dt:
            payment_filters.append(PaymentInvoice.paid_at >= start_dt)
        if end_dt:
            payment_filters.append(PaymentInvoice.paid_at <= end_dt)
        paid_user_ids = db.scalars(select(PaymentInvoice.user_id).where(*payment_filters)).all()
        if not paid_user_ids:
            return []
        users = db.scalars(
            select(User).where(
                User.id.in_(list(set(int(x) for x in paid_user_ids))),
                User.id.in_(participant_ids),
                User.subscription_until.is_not(None),
                User.subscription_until > now,
                User.is_blocked.is_(False),
            )
        ).all()
        return list(users)

    if kind == GIVEAWAY_KIND_REFERRAL_LEADER:
        start_dt, end_dt = _giveaway_period_bounds(giveaway)
        user_filters = [User.referred_by_user_id.is_not(None)]
        if start_dt:
            user_filters.append(User.created_at >= start_dt)
        if end_dt:
            user_filters.append(User.created_at <= end_dt)
        rows = db.execute(
            select(User.referred_by_user_id, func.count(User.id))
            .where(*user_filters)
            .group_by(User.referred_by_user_id)
        ).all()
        if not rows:
            return []
        max_count = max(int(count) for _, count in rows if _ is not None)
        top_ids = [int(inviter_id) for inviter_id, count in rows if inviter_id and int(count) == max_count]
        if not top_ids:
            return []
        return list(
            db.scalars(select(User).where(User.id.in_(top_ids), User.id.in_(participant_ids), User.is_blocked.is_(False))).all()
        )

    return []


def _pick_giveaway_winner(db: Session, giveaway: Giveaway, exclude_user_ids: set[int] | None = None) -> User | None:
    exclude_user_ids = exclude_user_ids or set()
    candidates = _eligible_users_for_giveaway(db, giveaway)
    candidates = [u for u in candidates if int(u.id) not in exclude_user_ids]
    if not candidates:
        return None
    return random.choice(candidates)


def _giveaway_winners_summary(db: Session, giveaway_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(GiveawayWinner, User)
        .join(User, User.id == GiveawayWinner.user_id)
        .where(GiveawayWinner.giveaway_id == giveaway_id, GiveawayWinner.is_active.is_(True))
        .order_by(GiveawayWinner.created_at.desc())
    ).all()
    result = []
    for winner, user in rows:
        result.append(
            {
                "user_id": int(user.id),
                "telegram_id": int(user.telegram_id or 0),
                "username": user.username or "-",
                "reason": str(winner.reason or ""),
                "created_at": _fmt_dt(winner.created_at),
            }
        )
    return result



def _notify_giveaway_winners(
    giveaway: Giveaway,
    winners: list[dict[str, Any]],
    support_contact: str,
) -> None:
    admin_ids: list[int] = []
    giveaway_admin_id = int(settings.giveaway_admin_telegram_id or 0)
    if giveaway_admin_id:
        admin_ids.append(giveaway_admin_id)
    main_admin_id = int(settings.admin_telegram_id or 0)
    if main_admin_id and main_admin_id not in admin_ids:
        admin_ids.append(main_admin_id)
    title = str(giveaway.title or f"Giveaway #{giveaway.id}")
    if admin_ids:
        if winners:
            lines = [
                "рџЏЃ Р РѕР·С‹РіСЂС‹С€ Р·Р°РІРµСЂС€РµРЅ",
                f"{title}",
                f"РЈСЃР»РѕРІРёРµ: {_giveaway_condition_text(str(giveaway.kind or ''))}",
                "РџРѕР±РµРґРёС‚РµР»Рё:",
            ]
            for w in winners:
                username = f"@{w['username']}" if w.get("username") and w["username"] != "-" else "-"
                lines.append(f"- {w['telegram_id']} {username}")
        else:
            lines = [
                "рџЏЃ Р РѕР·С‹РіСЂС‹С€ Р·Р°РІРµСЂС€РµРЅ",
                f"{title}",
                "РџРѕР±РµРґРёС‚РµР»Рё РЅРµ РЅР°Р№РґРµРЅС‹ (РЅРµС‚ СѓС‡Р°СЃС‚РЅРёРєРѕРІ).",
            ]
        for admin_id in admin_ids:
            _send_telegram_message(admin_id, "\n".join(lines))

    for w in winners:
        winner_text = "\n".join(
            [
                "рџЋ‰ РџРѕР·РґСЂР°РІР»СЏРµРј, РІС‹ РїРѕР±РµРґРёР»Рё РІ СЂРѕР·С‹РіСЂС‹С€Рµ!",
                f"{title}",
                f"РЈСЃР»РѕРІРёРµ: {_giveaway_condition_text(str(giveaway.kind or ''))}",
                f"РЎРІСЏР¶РёС‚РµСЃСЊ СЃ РїРѕРґРґРµСЂР¶РєРѕР№: {support_contact}",
            ]
        )
        _send_telegram_message(int(w["telegram_id"]), winner_text)


def _normalize_promo_code(raw_code: str) -> str:
    filtered = "".join(ch for ch in str(raw_code or "").upper().strip() if ch.isalnum() or ch in ("-", "_"))
    return filtered[:64]


def _promo_usage_total(db: Session, promo_id: int) -> int:
    return int(db.scalar(select(func.count(PromoRedemption.id)).where(PromoRedemption.promo_code_id == promo_id)) or 0)


def _promo_usage_per_user(db: Session, promo_id: int, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(PromoRedemption.id)).where(
                PromoRedemption.promo_code_id == promo_id,
                PromoRedemption.user_id == user_id,
            )
        )
        or 0
    )


def _promo_validation_error(db: Session, promo: PromoCode, user: User) -> str | None:
    now = utc_now()
    if not promo.enabled:
        return "Promo is disabled"
    if promo.starts_at and promo.starts_at > now:
        return "Promo is not active yet"
    if promo.ends_at and promo.ends_at < now:
        return "Promo expired"
    if int(promo.max_uses_total or 0) > 0 and _promo_usage_total(db, promo.id) >= int(promo.max_uses_total):
        return "Promo usage limit reached"
    if int(promo.max_uses_per_user or 0) > 0 and _promo_usage_per_user(db, promo.id, user.id) >= int(promo.max_uses_per_user):
        return "You already used this promo maximum times"
    return None


def _apply_subscription_days_no_commit(user: User, days: int) -> None:
    days = max(1, int(days))
    base = utc_now()
    if user.subscription_until and user.subscription_until > base:
        base = user.subscription_until
    user.subscription_until = base + timedelta(days=days)


def apply_promo_for_user(db: Session, user: User, code_raw: str) -> dict[str, Any]:
    code = _normalize_promo_code(code_raw)
    if len(code) < 2:
        raise HTTPException(status_code=400, detail="Invalid promo code")
    promo = db.scalar(select(PromoCode).where(PromoCode.code == code))
    if not promo:
        raise HTTPException(status_code=404, detail="Promo not found")
    if promo.kind not in PROMO_KINDS:
        raise HTTPException(status_code=400, detail="Unsupported promo kind")
    error = _promo_validation_error(db, promo, user)
    if error:
        raise HTTPException(status_code=400, detail=error)

    value_int = int(promo.value_int or 0)
    if promo.kind == PROMO_KIND_TOPUP_DISCOUNT:
        percent = max(1, min(95, value_int))
        user.pending_discount_promo_id = promo.id
        db.commit()
        return {
            "status": "ok",
            "applied": "pending_topup_discount",
            "promo_code": promo.code,
            "discount_percent": percent,
            "message": f"Promo applied. Next top-up will have {percent}% discount.",
        }

    redemption = PromoRedemption(
        promo_code_id=promo.id,
        user_id=user.id,
        payment_invoice_id=None,
        kind=promo.kind,
        value_int=value_int,
    )
    db.add(redemption)
    if promo.kind == PROMO_KIND_BALANCE:
        rub = max(1, value_int)
        user.balance_rub = int(user.balance_rub or 0) + rub
    elif promo.kind == PROMO_KIND_SUBSCRIPTION_DAYS:
        _apply_subscription_days_no_commit(user, max(1, value_int))
    db.commit()
    return {
        "status": "ok",
        "applied": promo.kind,
        "promo_code": promo.code,
        "value_int": value_int,
        "balance_rub": int(user.balance_rub or 0),
        "subscription_until": user.subscription_until,
    }


def generate_email_tag(telegram_id: int, device_name: str) -> str:
    clean_name = "".join(ch for ch in device_name if ch.isalnum() or ch in ("-", "_")).lower() or "device"
    return f"tg{telegram_id}_{clean_name}_{str(uuid4())[:8]}"


def server_protocol(server: VpnServer | None) -> str:
    value = str(getattr(server, "protocol", "") or "").strip().lower()
    if value in SERVER_PROTOCOLS:
        return value
    return SERVER_PROTOCOL_VLESS_REALITY


def server_supports_xray_stats(server: VpnServer | None) -> bool:
    return server_protocol(server) == SERVER_PROTOCOL_VLESS_REALITY


def build_vless_url(server: VpnServer, client_uuid: str, label: str) -> str:
    params = (
        "encryption=none"
        "&security=reality"
        f"&sni={quote(server.sni, safe='')}"
        f"&fp={quote(server.fingerprint, safe='')}"
        f"&pbk={quote(server.public_key, safe='')}"
        f"&sid={quote(server.short_id, safe='')}"
        "&type=tcp"
        "&flow=xtls-rprx-vision"
    )
    return f"vless://{client_uuid}@{server.host}:{server.port}?{params}#{quote(label, safe='')}"


def build_hysteria2_url(server: VpnServer, password: str, label: str) -> str:
    params: list[str] = []
    sni = str(server.sni or "").strip()
    if sni:
        params.append(f"sni={quote(sni, safe='')}")
    alpn = str(server.hy2_alpn or "h3").strip()
    if alpn:
        params.append(f"alpn={quote(alpn, safe=',')}")
    if bool(server.hy2_insecure):
        params.append("insecure=1")
    obfs = str(server.hy2_obfs or "").strip()
    if obfs:
        params.append(f"obfs={quote(obfs, safe='')}")
        obfs_password = str(server.hy2_obfs_password or "").strip()
        if obfs_password:
            params.append(f"obfs-password={quote(obfs_password, safe='')}")
    query = f"?{'&'.join(params)}" if params else ""
    auth = quote(str(password or ""), safe="")
    return f"hy2://{auth}@{server.host}:{int(server.port)}{query}#{quote(label, safe='')}"


def build_client_url(server: VpnServer, client_secret: str, label: str) -> str:
    if server_protocol(server) == SERVER_PROTOCOL_HYSTERIA2:
        return build_hysteria2_url(server, client_secret, label)
    return build_vless_url(server, client_secret, label)


def fetch_user_with_configs(db: Session, telegram_id: int) -> User | None:
    query = (
        select(User)
        .where(User.telegram_id == telegram_id)
        .options(selectinload(User.configs).selectinload(ClientConfig.server))
    )
    return db.scalar(query)



def _device_name_key(device_name: str | None) -> str:
    return str(device_name or "").strip().lower()


def _count_active_devices(configs: list[ClientConfig]) -> int:
    return len({_device_name_key(cfg.device_name) for cfg in configs if _device_name_key(cfg.device_name)})


def _active_subscription_configs(user: User, max_configs: int) -> list[ClientConfig]:
    active = [
        cfg
        for cfg in list(user.configs or [])
        if cfg.is_active and cfg.server and bool(cfg.server.enabled)
    ]
    if not active:
        return []
    active_sorted = sorted(active, key=lambda cfg: cfg.created_at, reverse=True)
    allowed_device_keys: list[str] = []
    seen: set[str] = set()
    for cfg in active_sorted:
        key = _device_name_key(cfg.device_name)
        if not key or key in seen:
            continue
        seen.add(key)
        allowed_device_keys.append(key)
        if len(allowed_device_keys) >= max(1, int(max_configs)):
            break
    allowed = set(allowed_device_keys)
    return [cfg for cfg in active_sorted if _device_name_key(cfg.device_name) in allowed]


def _subscription_client_app_name(user_agent: str) -> str:
    ua = str(user_agent or "").lower()
    if "happ" in ua:
        return "happ"
    if "hiddify" in ua:
        return "hiddify"
    if "v2rayng" in ua:
        return "v2rayng"
    if "nekobox" in ua:
        return "nekobox"
    if "shadowrocket" in ua:
        return "shadowrocket"
    return "client"


def _is_browser_subscription_preview_request(request: Request | None, fmt: str) -> bool:
    if not request:
        return False
    query = request.query_params
    preview_flag = str(query.get("preview") or "").strip().lower()
    if preview_flag in {"0", "false", "no", "off"}:
        return False
    user_agent = str(request.headers.get("user-agent", "") or "")
    if not user_agent:
        return False
    # Never render browser preview for known VPN clients even if URL contains preview=1.
    # This protects client import buttons that accidentally reuse a browser preview URL.
    if _subscription_client_app_name(user_agent) != "client":
        return False
    if preview_flag in {"1", "true", "yes", "on"}:
        return True
    ua = user_agent.lower()
    browser_markers = ("mozilla/", "chrome/", "safari/", "edg/", "firefox/", "opera/")
    if not any(marker in ua for marker in browser_markers):
        return False
    accept = str(request.headers.get("accept", "") or "").lower()
    if "text/html" not in accept:
        return False
    # Browsers can still request explicit raw payloads for debugging.
    return str(fmt or "").strip().lower() not in {"raw", "plain", "txt"}


def _subscription_variant_url(request: Request, telegram_id: int, token: str, **updates: str) -> str:
    base = f"{public_api_base_url()}/sub/{int(telegram_id)}/{token}"
    params: dict[str, str] = {k: str(v) for k, v in request.query_params.items()}
    for key, value in updates.items():
        if value is None:
            params.pop(str(key), None)
        else:
            params[str(key)] = str(value)
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _render_subscription_preview_page(
    request: Request,
    telegram_id: int,
    token: str,
    user: User,
    active_configs: list[ClientConfig],
    links_count: int,
    days_left: int,
    expire_ts: int,
    upload: int,
    download: int,
) -> str:
    subscription_url = _subscription_variant_url(request, telegram_id, token, fmt=None, preview="1")
    raw_url = _subscription_variant_url(request, telegram_id, token, fmt="raw", preview="0")
    b64_url = _subscription_variant_url(request, telegram_id, token, fmt="b64", preview="0")
    stats_url = _subscription_variant_url(request, telegram_id, token, with_stats="1", preview="1")
    happ_import_url = ""
    # HApp deeplink import is more stable with the default/base64 subscription payload.
    # Force preview off, but keep b64 format.
    happ_payload_url = _subscription_variant_url(request, telegram_id, token, fmt="b64", preview="0", pool="all")
    try:
        happ_import_url = str(settings.happ_import_url_template or "").format(
            url=quote(happ_payload_url, safe=""),
            raw_url=happ_payload_url,
        )
    except Exception:
        happ_import_url = ""

    expire_text = "-"
    if expire_ts > 0:
        try:
            expire_text = datetime.fromtimestamp(expire_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            expire_text = str(expire_ts)

    device_names = sorted(
        {
            str(cfg.device_name or "").strip()
            for cfg in active_configs
            if str(cfg.device_name or "").strip()
        }
    )
    server_names = sorted(
        {
            str(cfg.server.name or "").strip()
            for cfg in active_configs
            if getattr(cfg, "server", None) and str(cfg.server.name or "").strip()
        }
    )
    cards = [
        ("Status", "Active" if is_subscription_active(user) else "Inactive"),
        ("Days Left", str(int(days_left or 0))),
        ("Servers", str(int(links_count or 0))),
        ("Devices", str(len(device_names))),
        ("Traffic Used", _format_bytes_short(int(upload or 0) + int(download or 0))),
        ("Expires", expire_text),
    ]
    cards_html = "".join(
        (
            "<div class='metric'>"
            f"<div class='k'>{escape(k)}</div>"
            f"<div class='v'>{escape(v)}</div>"
            "</div>"
        )
        for k, v in cards
    )
    devices_html = "".join(f"<span class='pill'>{escape(name)}</span>" for name in device_names[:20]) or "<span class='muted'>-</span>"
    servers_html = "".join(f"<span class='pill'>{escape(name)}</span>" for name in server_names[:20]) or "<span class='muted'>-</span>"
    username_text = f"@{user.username}" if user.username else "-"
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex,nofollow,noarchive" />
  <title>TrumpVPN Subscription</title>
  <style>
    :root {{
      --bg:#f2f5f3;
      --ink:#10201d;
      --muted:#5f726c;
      --card:rgba(255,255,255,.78);
      --line:#d2ddd8;
      --accent:#1f6b5f;
      --accent-ink:#f3fffb;
      --danger:#b84b42;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      color:var(--ink);
      font-family:"Avenir Next","Manrope","Segoe UI Variable",sans-serif;
      background:
        radial-gradient(900px 420px at 0% 0%, rgba(31,107,95,.13), transparent 62%),
        radial-gradient(800px 420px at 100% 0%, rgba(90,115,170,.12), transparent 60%),
        linear-gradient(180deg, #eff3f1 0%, #e8efec 100%);
      min-height:100vh;
    }}
    .page {{
      width:min(960px, 100%);
      margin:0 auto;
      padding:20px 14px 28px;
    }}
    .panel {{
      border:1px solid var(--line);
      background:var(--card);
      backdrop-filter: blur(10px);
      border-radius:18px;
      box-shadow:0 14px 36px rgba(19,34,30,.10);
      padding:16px;
    }}
    .head {{
      display:flex;
      justify-content:space-between;
      gap:10px;
      align-items:flex-start;
      flex-wrap:wrap;
    }}
    .head h1 {{
      margin:0;
      font-size:24px;
      letter-spacing:.01em;
    }}
    .sub {{
      margin-top:6px;
      color:var(--muted);
      font-size:13px;
      line-height:1.45;
      max-width:650px;
    }}
    .status {{
      border:1px solid var(--line);
      border-radius:999px;
      padding:6px 12px;
      font-size:12px;
      font-weight:700;
      letter-spacing:.04em;
      text-transform:uppercase;
      color:var(--accent);
      background:#eef8f5;
    }}
    .status.off {{
      color:var(--danger);
      background:#fdf1ef;
      border-color:#f1c8c3;
    }}
    .grid {{
      margin-top:14px;
      display:grid;
      grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
      gap:10px;
    }}
    .metric {{
      border:1px solid var(--line);
      border-radius:12px;
      padding:10px 11px;
      background:rgba(255,255,255,.56);
    }}
    .metric .k {{
      color:var(--muted);
      font-size:11px;
      text-transform:uppercase;
      letter-spacing:.05em;
    }}
    .metric .v {{
      margin-top:4px;
      font-size:16px;
      font-weight:700;
      word-break:break-word;
    }}
    .section {{
      margin-top:12px;
      border:1px solid var(--line);
      border-radius:14px;
      background:rgba(255,255,255,.6);
      padding:12px;
    }}
    .section h2 {{
      margin:0 0 8px;
      font-size:14px;
      letter-spacing:.01em;
    }}
    .row {{
      display:flex;
      gap:8px;
      flex-wrap:wrap;
      align-items:center;
    }}
    .btn {{
      appearance:none;
      border:1px solid var(--accent);
      background:var(--accent);
      color:var(--accent-ink);
      border-radius:10px;
      padding:8px 11px;
      font-size:13px;
      font-weight:600;
      text-decoration:none;
      cursor:pointer;
    }}
    .btn.ghost {{
      background:transparent;
      color:var(--ink);
      border-color:var(--line);
    }}
    .btn.ok {{
      background:#207b52;
      border-color:#207b52;
      color:#f5fff9;
    }}
    .url-box {{
      margin-top:8px;
      border:1px dashed #b8c9c3;
      border-radius:12px;
      padding:10px;
      background:#f7fbf9;
      font-family:"JetBrains Mono","Cascadia Mono","Consolas",monospace;
      font-size:12px;
      line-height:1.45;
      word-break:break-all;
    }}
    .muted {{
      color:var(--muted);
      font-size:12px;
      line-height:1.45;
    }}
    .pill-wrap {{
      display:flex;
      gap:7px;
      flex-wrap:wrap;
      margin-top:6px;
    }}
    .pill {{
      border:1px solid var(--line);
      background:rgba(255,255,255,.72);
      border-radius:999px;
      padding:5px 10px;
      font-size:12px;
    }}
    .note {{
      margin-top:9px;
      font-size:12px;
      color:#42544f;
      line-height:1.5;
    }}
    .note code {{
      font-family:"JetBrains Mono","Cascadia Mono","Consolas",monospace;
      font-size:11px;
      background:#edf3f0;
      border:1px solid #d8e2de;
      border-radius:6px;
      padding:1px 5px;
    }}
    @media (max-width: 760px) {{
      .page {{ padding:12px 10px 18px; }}
      .panel {{ border-radius:14px; padding:12px; }}
      .head h1 {{ font-size:20px; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .btn {{ width:100%; justify-content:center; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="panel">
      <div class="head">
        <div>
          <h1>TrumpVPN Subscription</h1>
          <div class="sub">РћС‚РєСЂРѕР№С‚Рµ СЌС‚РѕС‚ URL РІ VPN-РєР»РёРµРЅС‚Рµ РєР°Рє СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё. Р’ Р±СЂР°СѓР·РµСЂРµ СЌС‚Рѕ С‚РѕР»СЊРєРѕ СѓРґРѕР±РЅС‹Р№ РїСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ.</div>
        </div>
        <div class="status {'off' if not is_subscription_active(user) else ''}">{'Inactive' if not is_subscription_active(user) else 'Active'}</div>
      </div>

      <div class="grid">{cards_html}</div>

      <div class="section">
        <h2>РЎСЃС‹Р»РєР° РїРѕРґРїРёСЃРєРё</h2>
        <div class="row">
          <button class="btn" type="button" onclick="copyText('sub-url')">РЎРєРѕРїРёСЂРѕРІР°С‚СЊ URL</button>
          <a class="btn ghost" href="{escape(stats_url)}">РћР±РЅРѕРІРёС‚СЊ</a>
          <a class="btn ghost" href="{escape(raw_url)}">Raw</a>
          <a class="btn ghost" href="{escape(b64_url)}">Base64</a>
          {f'<a class="btn ok" href="{escape(happ_import_url)}">РћС‚РєСЂС‹С‚СЊ РІ HApp</a>' if happ_import_url else ''}
          {f'<a class="btn ghost" href="{escape(str(settings.happ_download_url or ""))}" target="_blank" rel="noopener">РЎРєР°С‡Р°С‚СЊ HApp</a>' if str(settings.happ_download_url or "").strip() else ''}
        </div>
        <div id="sub-url" class="url-box">{escape(subscription_url)}</div>
        <div class="note">Р”Р»СЏ HApp Р»СѓС‡С€Рµ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РєРЅРѕРїРєСѓ <code>РћС‚РєСЂС‹С‚СЊ РІ HApp</code> вЂ” СЃСЃС‹Р»РєР° РѕС‚РїСЂР°РІР»СЏРµС‚СЃСЏ РІ СЃРѕРІРјРµСЃС‚РёРјРѕРј С„РѕСЂРјР°С‚Рµ Р±РµР· <code>preview</code>.</div>
      </div>

      <div class="section">
        <h2>РђРєРєР°СѓРЅС‚</h2>
        <div class="muted">Telegram ID: {int(user.telegram_id)} В· Username: {escape(username_text)} В· Balance: {int(user.balance_rub or 0)} RUB</div>
        <div style="margin-top:10px;">
          <div class="muted">РЈСЃС‚СЂРѕР№СЃС‚РІР°</div>
          <div class="pill-wrap">{devices_html}</div>
        </div>
        <div style="margin-top:10px;">
          <div class="muted">РЎРµСЂРІРµСЂС‹ РІ С‚РµРєСѓС‰РµР№ РїРѕРґРїРёСЃРєРµ</div>
          <div class="pill-wrap">{servers_html}</div>
        </div>
      </div>
    </section>
  </main>
  <script>
    async function copyText(id) {{
      const el = document.getElementById(id);
      if (!el) return;
      const text = el.textContent || "";
      try {{
        await navigator.clipboard.writeText(text);
      }} catch (_) {{
        const r = document.createRange();
        r.selectNodeContents(el);
        const s = window.getSelection();
        if (s) {{
          s.removeAllRanges();
          s.addRange(r);
        }}
        document.execCommand('copy');
        if (s) s.removeAllRanges();
      }}
    }}
  </script>
</body>
</html>"""


def _derive_device_name_from_subscription_request(request: Request) -> str | None:
    query = request.query_params
    raw_name = str(query.get("device_name") or query.get("device") or "").strip()
    raw_device_id = str(query.get("device_id") or query.get("did") or "").strip()
    user_agent = str(request.headers.get("user-agent", "") or "")
    user_agent_lc = user_agent.lower()
    app_name = _subscription_client_app_name(user_agent)

    # HApp should consume the full subscription pool and not create per-installation
    # auto device ids on each import/open. Device auto-attach for HApp leads to
    # fragmented partial sets when a new happ_* id appears.
    if app_name == "happ":
        return None

    # Auto-attach for known VPN clients even without explicit query params.
    # This lets one subscription URL account for separate apps/devices.
    browser_markers = ("mozilla/", "chrome/", "safari/", "edg/", "firefox/")
    looks_like_browser = any(marker in user_agent_lc for marker in browser_markers)
    should_auto_attach = bool(raw_name or raw_device_id or app_name != "client" or (user_agent and not looks_like_browser))
    if not should_auto_attach:
        return None

    device_name = _normalize_device_token(raw_name, max_len=32)
    device_id = _normalize_device_token(raw_device_id, max_len=24)
    # If URL already contains full stable device token (e.g. "hiddify_ab12cd34ef"),
    # keep it as-is instead of appending a second hash suffix.
    if device_name and not device_id:
        parts = device_name.rsplit("_", 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{6,32}", parts[1] or ""):
            return device_name[:64]
    if not device_id:
        fingerprint = f"{user_agent}|{app_name}"
        device_id = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:10]
    if device_name:
        return f"{device_name}_{device_id}"[:64]
    return f"{app_name}_{device_id}"[:64]


def _provision_single_auto_device_config(
    db: Session,
    user: User,
    device_name: str,
    max_configs: int,
    timeout_seconds: float = 5.0,
    total_timeout_seconds: float = 20.0,
) -> ClientConfig | None:
    existing_active = db.scalars(
        select(ClientConfig)
        .where(ClientConfig.user_id == user.id, ClientConfig.is_active.is_(True))
        .order_by(ClientConfig.created_at.desc())
    ).all()
    normalized_name = _device_name_key(device_name)
    by_device = [cfg for cfg in existing_active if _device_name_key(cfg.device_name) == normalized_name]
    if not by_device and _count_active_devices(existing_active) >= max_configs:
        return None

    enabled_servers = db.scalars(select(VpnServer).where(VpnServer.enabled.is_(True)).order_by(VpnServer.id)).all()
    if not enabled_servers:
        return None

    existing_by_server: dict[int, ClientConfig] = {int(cfg.server_id): cfg for cfg in by_device}
    created: list[ClientConfig] = []
    deadline = time.monotonic() + max(3.0, float(total_timeout_seconds))
    for server in enabled_servers:
        sid = int(server.id)
        if sid in existing_by_server:
            cfg = existing_by_server[sid]
            expected_label = f"{server.name}-{cfg.device_name}"
            expected_url = build_client_url(server, cfg.client_uuid, expected_label)
            if str(cfg.vless_url or "") != expected_url:
                cfg.vless_url = expected_url
            continue

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        client_uuid = str(uuid4())
        email_tag = generate_email_tag(user.telegram_id, device_name)
        vless_label = f"{server.name}-{device_name}"
        vless_url = build_client_url(server, client_uuid, vless_label)
        try:
            add_client_on_server(
                server,
                client_uuid,
                email_tag,
                user.subscription_until,
                timeout=max(1.0, min(float(timeout_seconds), float(remaining))),
            )
        except VPNProvisionError as exc:
            logging.warning(
                "Subscription auto-device provisioning failed: user_id=%s telegram_id=%s server_id=%s device=%s error=%s",
                user.id,
                user.telegram_id,
                sid,
                device_name,
                exc,
            )
            continue
        cfg = ClientConfig(
            user_id=user.id,
            server_id=sid,
            device_name=device_name,
            client_uuid=client_uuid,
            email_tag=email_tag,
            vless_url=vless_url,
            is_active=True,
        )
        db.add(cfg)
        created.append(cfg)

    if created:
        db.commit()
        for cfg in created:
            db.refresh(cfg)
        return created[0]
    if by_device:
        return by_device[0]
    return None



class VPNProvisionError(Exception):
    pass


def _run_ssh(server: VpnServer, command: str, timeout: float = 20.0) -> str:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=server.ssh_host,
            port=server.ssh_port,
            username=server.ssh_user,
            key_filename=server.ssh_key_path,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        _ = stdin
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        if exit_code != 0:
            raise VPNProvisionError(f"SSH command failed: {err or out or f'code {exit_code}'}")
        return out
    except Exception as exc:
        if isinstance(exc, VPNProvisionError):
            raise
        raise VPNProvisionError(str(exc)) from exc
    finally:
        client.close()


def add_vless_client(
    server: VpnServer,
    client_uuid: str,
    email: str,
    expires_at: datetime | None,
    timeout: float = 20.0,
) -> None:
    expiry_arg = ""
    if expires_at:
        expiry_arg = f" --expiry {shlex.quote(expires_at.strftime('%Y-%m-%dT%H:%M:%SZ'))}"
    cmd = (
        f"sudo {shlex.quote(server.remote_add_script)} "
        f"--uuid {shlex.quote(client_uuid)} "
        f"--email {shlex.quote(email)}"
        f"{expiry_arg}"
    )
    _run_ssh(server, cmd, timeout=max(0.5, float(timeout)))


def add_hysteria2_client(
    server: VpnServer,
    password: str,
    username: str,
    expires_at: datetime | None,
    timeout: float = 20.0,
) -> None:
    expiry_arg = ""
    if expires_at:
        expiry_arg = f" --expiry {shlex.quote(expires_at.strftime('%Y-%m-%dT%H:%M:%SZ'))}"
    cmd = (
        f"sudo {shlex.quote(server.remote_add_script)} "
        f"--password {shlex.quote(password)} "
        f"--name {shlex.quote(username)}"
        f"{expiry_arg}"
    )
    _run_ssh(server, cmd, timeout=max(0.5, float(timeout)))


def server_service_name(server: VpnServer) -> str:
    if server_protocol(server) == SERVER_PROTOCOL_HYSTERIA2:
        return "hysteria-server"
    return "xray"


def restart_server_service(server: VpnServer, timeout: float = 60.0, no_block: bool = False) -> str:
    service_name = server_service_name(server)
    if no_block:
        cmd = (
            f"sudo systemctl restart --no-block {shlex.quote(service_name)} >/dev/null 2>&1 "
            f"|| sudo systemctl restart {shlex.quote(service_name)} >/dev/null 2>&1 "
            "|| true; echo queued"
        )
        return _run_ssh(server, cmd, timeout=max(0.5, float(timeout)))
    cmd = f"sudo systemctl restart {shlex.quote(service_name)} && systemctl is-active {shlex.quote(service_name)}"
    return _run_ssh(server, cmd, timeout=max(0.5, float(timeout)))


def remove_vless_client(
    server: VpnServer,
    client_uuid: str,
    timeout: float = 90.0,
    restart: bool = True,
) -> bool:
    def _looks_like_ssh_auth_error(raw_error: str) -> bool:
        text = str(raw_error or "").lower()
        return (
            "authentication failed" in text
            or "permission denied" in text
            or "bad authentication type" in text
            or "private key file is encrypted" in text
            or "not a valid rsa private key file" in text
        )

    def _looks_like_remote_remove_script_error(raw_error: str) -> bool:
        text = str(raw_error or "").lower()
        return (
            "jq: error" in text
            or "cannot iterate over null" in text
            or "failed to remove uuid from config" in text
            or "config not found" in text
            or "unknown argument" in text
            or "no such file or directory" in text
            or "not found" in text
        )

    def _remove_vless_client_inline_fallback() -> None:
        inline_body = (
            "set -euo pipefail; "
            "CONFIG=${XRAY_CONFIG:-}; "
            "if [ -z \"$CONFIG\" ]; then "
            "if [ -f /usr/local/etc/xray/config.json ]; then CONFIG=/usr/local/etc/xray/config.json; "
            "elif [ -f /etc/xray/config.json ]; then CONFIG=/etc/xray/config.json; "
            "else echo 'xray config not found' >&2; exit 1; fi; "
            "fi; "
            "[ -f \"$CONFIG\" ] || { echo \"xray config not found: $CONFIG\" >&2; exit 1; }; "
            "command -v jq >/dev/null 2>&1 || { echo 'jq is required' >&2; exit 1; }; "
            "TMP=$(mktemp); "
            "trap 'rm -f \"$TMP\"' EXIT; "
            f"jq --arg uuid {shlex.quote(client_uuid)} "
            "' .inbounds |= (if type == \"array\" then map(if (.settings? | type) == \"object\" and (.settings.clients? | type) == \"array\" then .settings.clients |= map(select((.id // \"\") != $uuid)) else . end) else . end) ' "
            "\"$CONFIG\" > \"$TMP\"; "
            "mv \"$TMP\" \"$CONFIG\"; "
            "chown root:root \"$CONFIG\" >/dev/null 2>&1 || true; "
            "chmod 644 \"$CONFIG\" >/dev/null 2>&1 || true; "
            "echo 'OK: inline remove applied'"
        )
        inline_cmd = f"sudo bash -lc {shlex.quote(inline_body)}"
        _run_ssh(server, inline_cmd, timeout=max(0.5, float(timeout)))

    no_restart_arg = "" if restart else " --no-restart"
    cmd = f"sudo {shlex.quote(server.remote_remove_script)} --uuid {shlex.quote(client_uuid)}{no_restart_arg}"
    try:
        _run_ssh(server, cmd, timeout=max(0.5, float(timeout)))
        return bool(restart)
    except VPNProvisionError as exc:
        # Backward compatibility for old remote scripts without --no-restart support.
        err_text = str(exc).lower()
        if (not restart) and ("unknown argument" in err_text) and ("--no-restart" in err_text):
            fallback = f"sudo {shlex.quote(server.remote_remove_script)} --uuid {shlex.quote(client_uuid)}"
            _run_ssh(server, fallback, timeout=max(0.5, float(timeout)))
            return True
        if (not _looks_like_ssh_auth_error(err_text)) and _looks_like_remote_remove_script_error(err_text):
            try:
                _remove_vless_client_inline_fallback()
                if restart:
                    restart_server_service(server, timeout=min(float(timeout), 30.0), no_block=False)
                return bool(restart)
            except Exception as fallback_exc:
                raise VPNProvisionError(f"{exc}; inline fallback failed: {fallback_exc}") from fallback_exc
        raise


def remove_hysteria2_client(
    server: VpnServer,
    password: str,
    username: str,
    timeout: float = 90.0,
    restart: bool = True,
) -> bool:
    no_restart_arg = "" if restart else " --no-restart"
    cmd = (
        f"sudo {shlex.quote(server.remote_remove_script)} "
        f"--password {shlex.quote(password)} "
        f"--name {shlex.quote(username)}"
        f"{no_restart_arg}"
    )
    try:
        _run_ssh(server, cmd, timeout=max(0.5, float(timeout)))
        return bool(restart)
    except VPNProvisionError as exc:
        err_text = str(exc).lower()
        if (not restart) and ("unknown argument" in err_text) and ("--no-restart" in err_text):
            fallback = (
                f"sudo {shlex.quote(server.remote_remove_script)} "
                f"--password {shlex.quote(password)} "
                f"--name {shlex.quote(username)}"
            )
            _run_ssh(server, fallback, timeout=max(0.5, float(timeout)))
            return True
        raise


def add_client_on_server(
    server: VpnServer,
    client_secret: str,
    email_tag: str,
    expires_at: datetime | None,
    timeout: float = 20.0,
) -> None:
    if server_protocol(server) == SERVER_PROTOCOL_HYSTERIA2:
        add_hysteria2_client(server, client_secret, email_tag, expires_at, timeout=timeout)
        return
    add_vless_client(server, client_secret, email_tag, expires_at, timeout=timeout)


def remove_client_on_server(
    server: VpnServer,
    client_secret: str,
    email_tag: str,
    timeout: float = 90.0,
    restart: bool = True,
) -> bool:
    if server_protocol(server) == SERVER_PROTOCOL_HYSTERIA2:
        return remove_hysteria2_client(
            server,
            password=client_secret,
            username=email_tag,
            timeout=timeout,
            restart=restart,
        )
    return remove_vless_client(server, client_secret, timeout=timeout, restart=restart)


def _remove_active_configs_remotely_grouped(
    db: Session,
    configs: list[ClientConfig],
    remove_timeout: float = 90.0,
    restart_timeout: float = 90.0,
) -> tuple[set[int], list[str], list[str]]:
    active_configs = [cfg for cfg in list(configs or []) if bool(getattr(cfg, "is_active", False))]
    if not active_configs:
        return set(), [], []

    grouped: dict[int, list[ClientConfig]] = {}
    errors: list[str] = []
    for cfg in active_configs:
        sid = int(getattr(cfg, "server_id", 0) or 0)
        if sid <= 0:
            errors.append(f"cfg#{int(getattr(cfg, 'id', 0) or 0)}: invalid server id")
            continue
        grouped.setdefault(sid, []).append(cfg)
    if not grouped:
        return set(), errors, []

    server_rows = db.scalars(select(VpnServer).where(VpnServer.id.in_(list(grouped.keys())))).all()
    server_map = {int(server.id): server for server in server_rows}
    removed_ids: set[int] = set()
    warnings: list[str] = []

    for server_id, rows in grouped.items():
        server = server_map.get(int(server_id))
        if not server:
            for cfg in rows:
                removed_ids.add(int(cfg.id))
            warnings.append(
                f"server#{int(server_id)}: server record not found, local revoke only for {len(rows)} config(s)"
            )
            continue

        if not bool(server.enabled):
            for cfg in rows:
                removed_ids.add(int(cfg.id))
            warnings.append(
                f"server#{int(server_id)}@{server.name}: server disabled, local revoke only for {len(rows)} config(s)"
            )
            continue

        removed_on_server: list[ClientConfig] = []
        removed_local_only: list[ClientConfig] = []
        restart_done_by_script = False
        for cfg in rows:
            try:
                restarted = remove_client_on_server(
                    server,
                    client_secret=str(cfg.client_uuid or ""),
                    email_tag=str(cfg.email_tag or ""),
                    timeout=remove_timeout,
                    restart=False,
                )
                restart_done_by_script = restart_done_by_script or bool(restarted)
                removed_on_server.append(cfg)
            except Exception as exc:
                text = str(exc or "").lower()
                local_only_markers = (
                    "authentication failed",
                    "timed out",
                    "timeout",
                    "unable to connect",
                    "connection refused",
                    "connection reset",
                    "network is unreachable",
                    "no route to host",
                    "name or service not known",
                    "temporary failure in name resolution",
                )
                if any(marker in text for marker in local_only_markers):
                    removed_local_only.append(cfg)
                    warnings.append(
                        f"cfg#{int(cfg.id)}@{server.name}: remote revoke unavailable ({exc}), local revoke only"
                    )
                    continue
                errors.append(f"cfg#{int(cfg.id)}@{server.name}: {exc}")

        if not removed_on_server and not removed_local_only:
            continue

        if removed_on_server and not restart_done_by_script:
            try:
                restart_server_service(server, timeout=restart_timeout, no_block=False)
            except Exception as exc:
                try:
                    restart_server_service(server, timeout=8.0, no_block=True)
                    warnings.append(f"server#{int(server_id)}: restart queued in background ({exc})")
                except Exception as exc2:
                    errors.append(f"server#{int(server_id)}: restart failed after removals: {exc2}")
        for cfg in removed_on_server:
            removed_ids.add(int(cfg.id))
        for cfg in removed_local_only:
            removed_ids.add(int(cfg.id))

    return removed_ids, errors, warnings


def _parse_non_negative_int(text: str) -> int:
    raw = str(text or "").strip()
    if raw.lstrip("-").isdigit():
        return max(0, int(raw))
    return 0


def _parse_xray_stats_output(raw_text: str) -> list[tuple[str, int]]:
    text = str(raw_text or "").strip()
    if not text:
        return []
    # Prefer JSON output (modern xray api statsquery format).
    try:
        data = json.loads(text)
        items: list[dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("stat"), list):
            items = [item for item in data["stat"] if isinstance(item, dict)]
        elif isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        pairs: list[tuple[str, int]] = []
        for item in items:
            name = item.get("name")
            value = item.get("value")
            if not name:
                continue
            pairs.append((str(name), _parse_non_negative_int(value)))
        if pairs:
            return pairs
    except Exception:
        pass

    # Fallback parser for legacy text output.
    pair_pattern = re.compile(
        r'name:\s*"([^"]+)"\s*value:\s*([0-9]+)',
        re.IGNORECASE | re.MULTILINE,
    )
    pairs = [(m.group(1), _parse_non_negative_int(m.group(2))) for m in pair_pattern.finditer(text)]
    if pairs:
        return pairs

    # Loose fallback: match any user>>>...>>>traffic>>>... with a value.
    fallback_pattern = re.compile(
        r"(user>>>[^\\s]+>>>traffic>>>[^\\s]+).*?([0-9]+)",
        re.IGNORECASE,
    )
    return [(m.group(1), _parse_non_negative_int(m.group(2))) for m in fallback_pattern.finditer(text)]


def _fetch_config_traffic_bytes(server: VpnServer, email_tag: str, timeout_seconds: float = 0.35) -> tuple[int, int]:
    # Requires xray API stats endpoint on VPN node; if unavailable, returns 0.
    if not server_supports_xray_stats(server):
        return 0, 0
    cmd = (
        f"EMAIL={shlex.quote(email_tag)}; "
        "xray api statsquery --server=127.0.0.1:10085 "
        "--pattern \"user>>>${EMAIL}>>>traffic>>>\" 2>/dev/null || true"
    )
    try:
        out = _run_ssh(server, cmd, timeout=max(0.3, float(timeout_seconds)))
    except Exception:
        return 0, 0
    pairs = _parse_xray_stats_output(out)
    uplink = 0
    downlink = 0
    for name, value in pairs:
        parts = str(name).split(">>>")
        if len(parts) < 4 or parts[0] != "user" or parts[2] != "traffic":
            continue
        if parts[1] != str(email_tag):
            continue
        metric = parts[3]
        if metric == "uplink":
            uplink += int(value)
        elif metric == "downlink":
            downlink += int(value)
    return int(uplink), int(downlink)


def _fetch_server_user_traffic_totals(server: VpnServer, timeout_seconds: float = 1.2) -> dict[str, int]:
    # Fetches total (uplink + downlink) by xray email tag for all users on a node.
    if not server_supports_xray_stats(server):
        return {}
    cmd = "xray api statsquery --server=127.0.0.1:10085 --pattern 'user>>>' 2>/dev/null || true"
    try:
        output = _run_ssh(server, cmd, timeout=max(0.5, float(timeout_seconds)))
    except Exception:
        return {}
    text = str(output or "")
    if not text.strip():
        return {}
    totals: dict[str, int] = {}
    pairs = _parse_xray_stats_output(text)
    if not pairs:
        return {}
    for name, value in pairs:
        parts = str(name).split(">>>")
        if len(parts) < 4 or parts[0] != "user" or parts[2] != "traffic":
            continue
        email = str(parts[1]).strip()
        if not email:
            continue
        totals[email] = int(totals.get(email, 0)) + int(value)
    return totals


def _fetch_server_user_traffic_breakdown(
    server: VpnServer,
    timeout_seconds: float = 1.2,
) -> dict[str, tuple[int, int]]:
    # Fetches (uplink, downlink) per xray email tag for all users on a node.
    if not server_supports_xray_stats(server):
        return {}
    cmd = "xray api statsquery --server=127.0.0.1:10085 --pattern 'user>>>' 2>/dev/null || true"
    try:
        output = _run_ssh(server, cmd, timeout=max(0.5, float(timeout_seconds)))
    except Exception:
        return {}
    text = str(output or "")
    if not text.strip():
        return {}
    pairs = _parse_xray_stats_output(text)
    if not pairs:
        return {}
    result: dict[str, tuple[int, int]] = {}
    for name, value in pairs:
        parts = str(name).split(">>>")
        if len(parts) < 4 or parts[0] != "user" or parts[2] != "traffic":
            continue
        email = str(parts[1]).strip()
        if not email:
            continue
        metric = str(parts[3]).strip()
        up, down = result.get(email, (0, 0))
        if metric == "uplink":
            up += int(value)
        elif metric == "downlink":
            down += int(value)
        result[email] = (up, down)
    return result


def _live_server_active_devices(
    server: VpnServer,
    active_configs: list[ClientConfig],
    sample_interval_seconds: float = 1.1,
    timeout_seconds: float = 6.0,
    top_n: int = 30,
) -> tuple[list[dict[str, Any]], str | None]:
    if not server_supports_xray_stats(server):
        return [], "live sampling is available only for vless_reality nodes"
    if not active_configs:
        return [], None
    deadline = time.monotonic() + max(2.0, float(timeout_seconds))
    first = _fetch_server_user_traffic_totals(server, timeout_seconds=1.4)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return [], "live sampling timeout"
    time.sleep(max(0.2, min(float(sample_interval_seconds), remaining)))
    second = _fetch_server_user_traffic_totals(server, timeout_seconds=1.4)
    if not first and not second:
        return [], "xray stats API unavailable on node"

    per_device_delta: dict[str, int] = {}
    per_device_meta: dict[str, dict[str, Any]] = {}
    for cfg in active_configs:
        email_tag = str(cfg.email_tag or "").strip()
        if not email_tag:
            continue
        before = int(first.get(email_tag, 0))
        after = int(second.get(email_tag, before))
        delta = max(0, after - before)
        key = _device_name_key(cfg.device_name)
        if not key:
            continue
        per_device_delta[key] = int(per_device_delta.get(key, 0)) + delta
        if key not in per_device_meta:
            per_device_meta[key] = {
                "device_name": str(cfg.device_name or "-"),
                "telegram_id": int(cfg.user.telegram_id) if cfg.user else 0,
                "server_config_count": 0,
            }
        per_device_meta[key]["server_config_count"] = int(per_device_meta[key]["server_config_count"]) + 1

    active_rows: list[dict[str, Any]] = []
    for key, meta in per_device_meta.items():
        delta_bytes = int(per_device_delta.get(key, 0))
        if delta_bytes <= 0:
            continue
        active_rows.append(
            {
                "device_name": str(meta["device_name"]),
                "telegram_id": int(meta["telegram_id"]),
                "traffic_delta_bytes": delta_bytes,
                "traffic_delta_text": _format_bytes_short(delta_bytes),
                "server_config_count": int(meta["server_config_count"]),
            }
        )
    active_rows.sort(key=lambda row: int(row.get("traffic_delta_bytes", 0)), reverse=True)
    return active_rows[: max(1, int(top_n))], None


def _sample_live_users_now(
    db: Session,
    servers: list[VpnServer],
    max_seconds: float = 8.0,
    sample_interval_seconds: float = 0.8,
    per_fetch_timeout_seconds: float = 1.0,
) -> dict[str, Any]:
    server_ids = [int(s.id) for s in servers if int(getattr(s, "id", 0) or 0) > 0]
    if not server_ids:
        return {"count": 0, "partial": False, "sampled_servers": 0}
    rows = db.execute(
        select(ClientConfig.server_id, ClientConfig.email_tag, User.telegram_id)
        .join(User, User.id == ClientConfig.user_id)
        .where(
            ClientConfig.is_active.is_(True),
            ClientConfig.server_id.in_(server_ids),
            User.is_blocked.is_(False),
        )
    ).all()
    by_server: dict[int, list[tuple[str, int]]] = {}
    for server_id, email_tag, telegram_id in rows:
        sid = int(server_id or 0)
        email = str(email_tag or "").strip()
        tg = int(telegram_id or 0)
        if sid <= 0 or not email or tg <= 0:
            continue
        by_server.setdefault(sid, []).append((email, tg))
    if not by_server:
        return {"count": 0, "partial": False, "sampled_servers": 0}

    live_tg_ids: set[int] = set()
    deadline = time.monotonic() + max(1.0, float(max_seconds))
    supported_server_ids = {
        int(getattr(server, "id", 0) or 0)
        for server in servers
        if int(getattr(server, "id", 0) or 0) > 0 and server_supports_xray_stats(server)
    }
    expected = len([sid for sid in by_server.keys() if sid in supported_server_ids])
    if expected <= 0:
        return {"count": 0, "partial": False, "sampled_servers": 0}
    sampled = 0
    for server in servers:
        sid = int(getattr(server, "id", 0) or 0)
        entries = by_server.get(sid)
        if not entries:
            continue
        if sid not in supported_server_ids:
            continue
        if time.monotonic() >= deadline:
            break
        first = _fetch_server_user_traffic_totals(server, timeout_seconds=per_fetch_timeout_seconds)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(max(0.2, min(float(sample_interval_seconds), float(remaining))))
        second = _fetch_server_user_traffic_totals(server, timeout_seconds=per_fetch_timeout_seconds)
        sampled += 1
        if not first and not second:
            continue
        for email, tg in entries:
            before = int(first.get(email, 0))
            after = int(second.get(email, before))
            if after > before:
                live_tg_ids.add(int(tg))
    return {
        "count": len(live_tg_ids),
        "partial": sampled < expected,
        "sampled_servers": sampled,
    }


def _aggregate_user_traffic_bytes(
    configs: list[ClientConfig],
    total_timeout_seconds: float = 1.6,
    per_server_timeout_seconds: float = 0.7,
) -> tuple[int, int]:
    upload = 0
    download = 0
    if not configs:
        return 0, 0
    server_map: dict[int, dict[str, Any]] = {}
    for cfg in configs:
        if not cfg.server:
            continue
        if not server_supports_xray_stats(cfg.server):
            continue
        email_tag = str(cfg.email_tag or "").strip()
        if not email_tag:
            continue
        sid = int(getattr(cfg.server, "id", 0) or cfg.server_id or 0)
        if sid <= 0:
            continue
        entry = server_map.get(sid)
        if not entry:
            entry = {"server": cfg.server, "emails": set()}
            server_map[sid] = entry
        entry["emails"].add(email_tag)
    if not server_map:
        return 0, 0
    dynamic_total = float(per_server_timeout_seconds) * len(server_map) + 0.4
    deadline = time.monotonic() + max(float(total_timeout_seconds), min(6.0, dynamic_total))
    for entry in server_map.values():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        timeout_seconds = max(0.4, min(float(per_server_timeout_seconds), float(remaining)))
        server = entry["server"]
        breakdown = _fetch_server_user_traffic_breakdown(server, timeout_seconds=timeout_seconds)
        if breakdown:
            for email in entry["emails"]:
                up, down = breakdown.get(email, (0, 0))
                upload += int(up)
                download += int(down)
            continue
        for email in entry["emails"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            fallback_timeout = max(0.3, min(0.5, float(remaining)))
            up, down = _fetch_config_traffic_bytes(server, email, timeout_seconds=fallback_timeout)
            upload += up
            download += down
    return upload, download


def _format_bytes_short(size_bytes: int) -> str:
    value = float(max(0, int(size_bytes)))
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for next_unit in units:
        unit = next_unit
        if value < 1024 or next_unit == units[-1]:
            break
        value /= 1024.0
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.2f} {unit}"


def _format_rate_short(bytes_per_sec: float | None) -> str:
    if bytes_per_sec is None:
        return "-"
    return f"{_format_bytes_short(int(bytes_per_sec))}/s"


def _cryptopay_headers() -> dict[str, str]:
    if not settings.crypto_pay_api_token:
        raise RuntimeError("CRYPTO_PAY_API_TOKEN is empty")
    return {"Crypto-Pay-API-Token": settings.crypto_pay_api_token}


def cryptopay_create_invoice(telegram_id: int, amount_rub: int) -> dict[str, Any]:
    description = f"TrumpVPN balance top-up: {amount_rub} RUB"
    payload_tag = f"tg:{telegram_id}:topup:{amount_rub}:{uuid4().hex[:12]}"
    body = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": str(int(amount_rub)),
        "description": description,
        "payload": payload_tag,
        "expires_in": max(300, settings.crypto_pay_invoice_expires_in),
        "accepted_assets": settings.crypto_pay_accepted_assets,
        "allow_anonymous": False,
    }
    url = f"{settings.crypto_pay_base_url.rstrip('/')}/createInvoice"
    response = httpx.post(url, json=body, headers=_cryptopay_headers(), timeout=20.0)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "CryptoPay createInvoice failed"))
    result = data.get("result", {})
    if not result.get("invoice_id") or not result.get("pay_url"):
        raise RuntimeError("CryptoPay returned incomplete invoice data")
    return result


def cryptopay_get_invoice(invoice_id: int) -> dict[str, Any]:
    url = f"{settings.crypto_pay_base_url.rstrip('/')}/getInvoices"
    body = {"invoice_ids": str(invoice_id)}
    response = httpx.post(url, json=body, headers=_cryptopay_headers(), timeout=20.0)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "CryptoPay getInvoices failed"))
    items = data.get("result", {}).get("items", [])
    if not items:
        raise RuntimeError("Invoice not found in CryptoPay")
    return items[0]


def _next_internal_invoice_id(db: Session) -> int:
    last = int(db.scalar(select(func.coalesce(func.max(PaymentInvoice.invoice_id), 0))) or 0)
    now_seed = int(time.time())
    return max(last + 1, now_seed)


def yoomoney_create_invoice(db: Session, telegram_id: int, amount_rub: int) -> dict[str, Any]:
    receiver = settings.yoomoney_receiver.strip()
    if not receiver:
        raise RuntimeError("YOOMONEY_RECEIVER is empty")

    invoice_id = _next_internal_invoice_id(db)
    label = f"ym_{telegram_id}_{uuid4().hex[:12]}"
    params = {
        "receiver": receiver,
        "quickpay-form": settings.yoomoney_quickpay_form or "shop",
        "targets": f"TrumpVPN topup {amount_rub} RUB",
        "paymentType": settings.yoomoney_payment_type or "AC",
        "sum": str(int(amount_rub)),
        "label": label,
    }
    if settings.yoomoney_success_url:
        params["successURL"] = settings.yoomoney_success_url
    pay_url = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(params)}"
    return {
        "invoice_id": invoice_id,
        "status": "active",
        "pay_url": pay_url,
        "label": label,
    }


def _platega_headers() -> dict[str, str]:
    merchant_id = str(settings.platega_merchant_id or "").strip()
    api_key = str(settings.platega_api_key or "").strip()
    if not merchant_id:
        raise RuntimeError("PLATEGA_MERCHANT_ID is empty")
    if not api_key:
        raise RuntimeError("PLATEGA_API_KEY is empty")
    return {
        "X-MerchantId": merchant_id,
        "X-Secret": api_key,
    }


def _platega_base_url() -> str:
    base = str(settings.platega_base_url or "").strip() or "https://app.platega.io"
    return base.rstrip("/")


def _platega_status_to_local(status_raw: str | None) -> str:
    value = str(status_raw or "").strip().upper()
    if value in {"CONFIRMED", "PAID", "SUCCESS", "COMPLETED"}:
        return "paid"
    if value in {"CANCELED", "CANCELLED", "CHARGEBACK", "FAILED", "EXPIRED", "REJECTED"}:
        return "rejected"
    return "active"


def _platega_extract_transaction_id(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("transactionId") or data.get("id")
    if direct:
        return str(direct).strip()
    for container_key in ("data", "result", "transaction"):
        container = data.get(container_key)
        if isinstance(container, dict):
            nested = container.get("transactionId") or container.get("id")
            if nested:
                return str(nested).strip()
    return ""


def _platega_extract_redirect_url(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    keys = ("redirectUrl", "redirect", "url", "payUrl", "paymentUrl")
    for key in keys:
        value = data.get(key)
        if value:
            return str(value).strip()
    for container_key in ("data", "result", "transaction"):
        container = data.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if value:
                return str(value).strip()
    return ""


def _platega_extract_status(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return ""
    direct = data.get("status")
    if direct:
        return str(direct).strip()
    for container_key in ("data", "result", "transaction"):
        container = data.get(container_key)
        if isinstance(container, dict) and container.get("status"):
            return str(container.get("status")).strip()
    return ""


def _platega_return_urls() -> tuple[str, str]:
    return_url = str(settings.platega_return_url or "").strip()
    failed_url = str(settings.platega_failed_url or "").strip()
    if not return_url:
        return_url = str(settings.yoomoney_success_url or "").strip()
    if not return_url:
        return_url = "https://t.me"
    if not failed_url:
        failed_url = return_url
    return return_url, failed_url


def _platega_payment_method_for_gateway_code(gateway_code: str) -> int:
    code = str(gateway_code or "").strip().lower()
    default_method = int(settings.platega_payment_method or 2)
    if code == "platega_crypto":
        return int(settings.platega_payment_method_crypto or 0) or default_method
    if code == "platega_card":
        return int(settings.platega_payment_method_card or 0) or default_method
    if code == "platega_sbp":
        return int(settings.platega_payment_method_sbp or 0) or default_method
    return default_method


def platega_create_invoice(
    db: Session,
    telegram_id: int,
    amount_rub: int,
    payment_method: int | None = None,
) -> dict[str, Any]:
    invoice_id = _next_internal_invoice_id(db)
    payload_tag = f"plg_tg:{telegram_id}:topup:{amount_rub}:{uuid4().hex[:12]}"
    return_url, failed_url = _platega_return_urls()
    # Platega docs currently use nested paymentDetails payload.
    body = {
        "paymentMethod": int(payment_method or settings.platega_payment_method or 2),
        "paymentDetails": {
            "amount": int(amount_rub),
            "currency": "RUB",
        },
        "description": f"TrumpVPN balance top-up: {amount_rub} RUB",
        "payload": payload_tag,
        "return": return_url,
        "failedUrl": failed_url,
    }
    url = f"{_platega_base_url()}/transaction/process"
    response = httpx.post(url, json=body, headers=_platega_headers(), timeout=20.0)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(str(data.get("error") or data.get("message") or "Platega create failed"))
    transaction_id = _platega_extract_transaction_id(data if isinstance(data, dict) else {})
    redirect_url = _platega_extract_redirect_url(data if isinstance(data, dict) else {})
    if not transaction_id or not redirect_url:
        raise RuntimeError("Platega returned incomplete invoice data")
    status_raw = _platega_extract_status(data if isinstance(data, dict) else {})
    return {
        "invoice_id": invoice_id,
        "status": _platega_status_to_local(status_raw or "PENDING"),
        "pay_url": redirect_url,
        "hash": transaction_id,
        "payload": payload_tag,
    }


def platega_get_invoice(transaction_id: str) -> dict[str, Any]:
    tx = str(transaction_id or "").strip()
    if not tx:
        raise RuntimeError("Platega transaction ID is empty")
    url = f"{_platega_base_url()}/transaction/{quote(tx, safe='')}"
    response = httpx.get(url, headers=_platega_headers(), timeout=20.0)
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(str(data.get("error") or data.get("message") or "Platega get failed"))
    if not isinstance(data, dict):
        raise RuntimeError("Platega returned invalid response")
    return data



def _verify_yoomoney_signature(form_data: dict[str, str], secret: str) -> bool:
    base = "&".join(
        [
            form_data.get("notification_type", ""),
            form_data.get("operation_id", ""),
            form_data.get("amount", ""),
            form_data.get("currency", ""),
            form_data.get("datetime", ""),
            form_data.get("sender", ""),
            form_data.get("codepro", ""),
            secret,
            form_data.get("label", ""),
        ]
    )
    expected = hashlib.sha1(base.encode("utf-8")).hexdigest()
    provided = str(form_data.get("sha1_hash", "")).lower()
    return hmac.compare_digest(expected, provided)


def _fmt_notify_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    msk_tz = timezone(timedelta(hours=3))
    return value.replace(tzinfo=timezone.utc).astimezone(msk_tz).strftime("%d.%m.%Y %H:%M MSK")


def _send_telegram_message(chat_id: int, text: str) -> None:
    text = _fix_mojibake_text(text)
    token = str(settings.bot_token or "").strip()
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok", False):
            logging.warning("Failed to send payment notification to chat %s: %s", chat_id, data)
    except Exception as exc:
        logging.warning("Failed to send payment notification to chat %s: %s", chat_id, exc)

def _telegram_get_chat_member(chat_id: str, user_id: int) -> dict[str, Any] | None:
    token = str(settings.bot_token or "").strip()
    if not token or not chat_id or not user_id:
        return None
    url = f"https://api.telegram.org/bot{token}/getChatMember"
    try:
        resp = httpx.get(url, params={"chat_id": chat_id, "user_id": user_id}, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok", False):
            return None
        return data.get("result") or None
    except Exception:
        return None

def notify_payment_paid(user: User, payment: PaymentInvoice, source: str) -> None:
    chat_id = int(settings.payments_notify_chat_id or 0)
    if not chat_id:
        return
    username = f"@{user.username}" if user.username else "-"
    lines = [
        "вњ… РћРїР»Р°С‚Р° РїРѕРґС‚РІРµСЂР¶РґРµРЅР°",
        f"РСЃС‚РѕС‡РЅРёРє: {source}",
        f"Telegram ID: {user.telegram_id}",
        f"Username: {username}",
        f"Invoice: {payment.invoice_id}",
        f"РЎСѓРјРјР° (face): {int(payment.amount_rub or 0)} RUB",
        f"РЎСѓРјРјР° (payable): {int(payment.payable_rub or 0)} RUB",
        f"РџСЂРѕРјРѕ: {payment.promo_code_text or '-'} ({int(payment.promo_discount_percent or 0)}%)",
        f"Р—Р°С‡РёСЃР»РµРЅРѕ: {int(payment.credited_rub or 0)} RUB",
        f"Р РµС„. Р±РѕРЅСѓСЃ: {int(payment.referral_bonus_rub or 0)} RUB",
        f"Р‘Р°Р»Р°РЅСЃ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ: {int(user.balance_rub or 0)} RUB",
        f"РџРѕРґРїРёСЃРєР° РґРѕ: {_fmt_notify_dt(user.subscription_until)}",
        f"РћРїР»Р°С‡РµРЅРѕ: {_fmt_notify_dt(payment.paid_at)}",
    ]
    _send_telegram_message(chat_id, "\n".join(lines))


def serialize_user(user: User | None, invited_count: int = 0, referral_bonus_rub: int = 0):
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    configs = [
        {
            "id": cfg.id,
            "server_name": cfg.server.name,
            "protocol": server_protocol(cfg.server),
            "device_name": cfg.device_name,
            "vless_url": cfg.vless_url,
            "is_active": cfg.is_active,
            "created_at": cfg.created_at,
        }
        for cfg in sorted(user.configs, key=lambda c: c.created_at, reverse=True)
    ]
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "balance_rub": int(user.balance_rub or 0),
        "trial_bonus_granted": bool(user.trial_bonus_granted),
        "pending_discount_promo_id": user.pending_discount_promo_id,
        "subscription_until": user.subscription_until,
        "subscription_active": is_subscription_active(user),
        "subscription_url": build_user_subscription_url(int(user.telegram_id)),
        "invited_count": invited_count,
        "referral_bonus_rub": referral_bonus_rub,
        "configs": configs,
    }


app = FastAPI(title="VPN One File", version="0.1.0")
PUBLIC_UI_DIST_DIR = Path(__file__).resolve().parent / "public-ui" / "dist"
PUBLIC_UI_INDEX_FILE = PUBLIC_UI_DIST_DIR / "index.html"
PUBLIC_UI_ASSETS_DIR = PUBLIC_UI_DIST_DIR / "assets"
if PUBLIC_UI_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(PUBLIC_UI_ASSETS_DIR)), name="public_ui_assets")

api_users = APIRouter(prefix="/api/users", tags=["users"])
api_servers = APIRouter(prefix="/api/servers", tags=["servers"])
api_configs = APIRouter(prefix="/api/configs", tags=["configs"])
api_admin = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_internal_token)])
api_maintenance = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
api_payments = APIRouter(prefix="/api/payments", tags=["payments"])
api_promos = APIRouter(prefix="/api/promos", tags=["promos"])
api_giveaways = APIRouter(prefix="/api/giveaways", tags=["giveaways"], dependencies=[Depends(require_internal_token)])


@app.on_event("startup")
def startup_event():
    run_sqlite_migrations()
    Base.metadata.create_all(bind=engine)
    _start_background_tasks()


def _public_ui_index_response() -> HTMLResponse | FileResponse:
    if not PUBLIC_UI_INDEX_FILE.exists():
        return HTMLResponse(
            "<h1>Public UI is not built</h1><p>Run: cd public-ui && npm install && npm run build</p>",
            status_code=503,
        )
    return FileResponse(str(PUBLIC_UI_INDEX_FILE), media_type="text/html", headers={"Cache-Control": "no-store"})


def _public_subscription_page_url(request: Request, telegram_id: int, token: str) -> str:
    base = f"{public_api_base_url()}/subscription/{int(telegram_id)}/{token}"
    params: dict[str, str] = {k: str(v) for k, v in request.query_params.items()}
    params.pop("preview", None)
    params.pop("fmt", None)
    params.pop("with_stats", None)
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


@dataclass
class SubscriptionPreparedData:
    telegram_id: int
    token: str
    user: User
    active_configs: list[ClientConfig]
    links: list[str]
    fmt_norm: str
    upload: int
    download: int
    expire_ts: int
    days_left: int


def _prepare_user_subscription_data(
    db: Session,
    telegram_id: int,
    token: str,
    request: Request,
    fmt: str = "b64",
    with_stats: int = 0,
) -> SubscriptionPreparedData:
    if telegram_id <= 0 or not verify_user_subscription_token(telegram_id, token):
        raise HTTPException(status_code=404, detail="Subscription not found")
    user = fetch_user_with_configs(db, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="User blocked")
    if not is_subscription_active(user):
        if not charge_balance_for_subscription(db, user, periods=1):
            raise HTTPException(
                status_code=403,
                detail=f"Subscription inactive. Need {settings.subscription_price_rub} RUB",
            )
        user = fetch_user_with_configs(db, telegram_id) or user

    client_app_name = _subscription_client_app_name(str(request.headers.get("user-agent", "") or "")) if request else "client"
    pool_mode = str(request.query_params.get("pool") or "").strip().lower() if request else ""
    force_pool_all = pool_mode in {"all", "1", "true", "yes"}
    fmt_norm = str(fmt or "").strip().lower()
    if client_app_name == "happ" and fmt_norm in {"raw", "plain", "txt"}:
        fmt_norm = "b64"

    max_configs = max(1, int(MAX_ACTIVE_CONFIGS_PER_USER))
    active_configs = _active_subscription_configs(user, max_configs)
    requested_device_name = _derive_device_name_from_subscription_request(request) if request else None
    if force_pool_all:
        requested_device_name = None

    if request and requested_device_name:
        requested_key = _device_name_key(requested_device_name)
        active_device_keys_all = {
            _device_name_key(cfg.device_name)
            for cfg in list(user.configs or [])
            if cfg.is_active and cfg.server and bool(cfg.server.enabled) and _device_name_key(cfg.device_name)
        }
        if requested_key not in active_device_keys_all and len(active_device_keys_all) >= max_configs:
            if client_app_name == "happ":
                requested_device_name = None
            else:
                raise HTTPException(status_code=403, detail=f"Device limit reached: {max_configs}")
        if requested_device_name:
            _provision_single_auto_device_config(db, user, requested_device_name, max_configs=max_configs)
            user = fetch_user_with_configs(db, telegram_id) or user
            requested_configs = [
                cfg
                for cfg in list(user.configs or [])
                if cfg.is_active and cfg.server and bool(cfg.server.enabled) and _device_name_key(cfg.device_name) == requested_key
            ]
            if requested_configs:
                active_configs = sorted(requested_configs, key=lambda cfg: cfg.created_at, reverse=True)
            else:
                active_configs = _active_subscription_configs(user, max_configs)

    # For HApp imports, try to backfill missing server configs for one existing device,
    # so subscription list contains all enabled servers.
    if client_app_name == "happ" or force_pool_all:
        device_candidates: list[str] = []
        if requested_device_name:
            device_candidates.append(str(requested_device_name))
        for cfg in list(active_configs or []):
            name = str(cfg.device_name or "").strip()
            if name and name not in device_candidates:
                device_candidates.append(name)
        if device_candidates:
            _provision_single_auto_device_config(
                db,
                user,
                device_candidates[0],
                max_configs=max_configs,
                timeout_seconds=6.0,
                total_timeout_seconds=35.0,
            )
            user = fetch_user_with_configs(db, telegram_id) or user
            active_configs = _active_subscription_configs(user, max_configs)

    # HApp should import full server pool for the account, not just one device slice.
    # Pick one latest active config per server to avoid duplicate entries for the same node.
    if client_app_name == "happ" or force_pool_all:
        by_server: dict[int, ClientConfig] = {}
        for cfg in list(user.configs or []):
            if not (cfg.is_active and cfg.server and bool(cfg.server.enabled)):
                continue
            sid = int(getattr(cfg, "server_id", 0) or 0)
            if sid <= 0:
                continue
            current = by_server.get(sid)
            if not current or cfg.created_at > current.created_at:
                by_server[sid] = cfg
        if by_server:
            active_configs = sorted(by_server.values(), key=lambda cfg: cfg.created_at, reverse=True)

    if not active_configs:
        raise HTTPException(status_code=404, detail="No active devices. Add device in bot first")
    links = [str(cfg.vless_url or "").strip() for cfg in active_configs if str(cfg.vless_url or "").strip()]
    if not links:
        raise HTTPException(status_code=404, detail="No available servers")

    upload = 0
    download = 0
    if int(with_stats or 0) > 0:
        traffic_configs = [cfg for cfg in list(user.configs or []) if cfg.is_active and cfg.server]
        try:
            upload, download = _aggregate_user_traffic_bytes(
                traffic_configs,
                total_timeout_seconds=1.6,
                per_server_timeout_seconds=0.7,
            )
        except Exception:
            upload, download = 0, 0

    expire_ts = 0
    if user.subscription_until:
        expire_ts = int(user.subscription_until.replace(tzinfo=timezone.utc).timestamp())
    days_left = 0
    if expire_ts > 0:
        delta = expire_ts - int(time.time())
        if delta > 0:
            days_left = max(1, int((delta + 86399) // 86400))

    return SubscriptionPreparedData(
        telegram_id=int(telegram_id),
        token=str(token),
        user=user,
        active_configs=list(active_configs),
        links=list(links),
        fmt_norm=fmt_norm,
        upload=int(upload),
        download=int(download),
        expire_ts=int(expire_ts),
        days_left=int(days_left),
    )


def _build_subscription_preview_payload(request: Request, prepared: SubscriptionPreparedData) -> dict[str, Any]:
    telegram_id = int(prepared.telegram_id)
    token = str(prepared.token)
    user = prepared.user
    active_configs = prepared.active_configs

    subscription_url = _subscription_variant_url(request, telegram_id, token, fmt="b64", preview="0", with_stats=None)
    raw_url = _subscription_variant_url(request, telegram_id, token, fmt="raw", preview="0", with_stats=None)
    b64_url = _subscription_variant_url(request, telegram_id, token, fmt="b64", preview="0", with_stats=None)
    stats_url = _public_subscription_page_url(request, telegram_id, token)

    happ_import_url = ""
    happ_payload_url = _subscription_variant_url(
        request,
        telegram_id,
        token,
        fmt="b64",
        preview="0",
        with_stats=None,
        pool="all",
    )
    try:
        happ_import_url = str(settings.happ_import_url_template or "").format(
            url=quote(happ_payload_url, safe=""),
            raw_url=happ_payload_url,
        )
    except Exception:
        happ_import_url = ""

    expire_text = "-"
    if prepared.expire_ts > 0:
        try:
            expire_text = datetime.fromtimestamp(prepared.expire_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            expire_text = str(prepared.expire_ts)

    device_names = sorted(
        {
            str(cfg.device_name or "").strip()
            for cfg in active_configs
            if str(cfg.device_name or "").strip()
        }
    )
    server_names = sorted(
        {
            str(cfg.server.name or "").strip()
            for cfg in active_configs
            if getattr(cfg, "server", None) and str(cfg.server.name or "").strip()
        }
    )

    return {
        "status": "ok",
        "metrics": {
            "subscription_active": bool(is_subscription_active(user)),
            "days_left": int(prepared.days_left),
            "servers_count": int(len(prepared.links)),
            "devices_count": int(len(device_names)),
            "traffic_used_text": _format_bytes_short(int(prepared.upload or 0) + int(prepared.download or 0)),
            "expires_text": expire_text,
        },
        "links": {
            "subscription_url": subscription_url,
            "raw_url": raw_url,
            "b64_url": b64_url,
            "stats_url": stats_url,
            "happ_import_url": happ_import_url,
            "happ_download_url": str(settings.happ_download_url or ""),
        },
        "account": {
            "telegram_id": int(user.telegram_id or 0),
            "username": str(user.username or ""),
            "balance_rub": int(user.balance_rub or 0),
        },
        "devices": device_names,
        "servers": server_names,
    }


@app.get("/")
def public_landing_page():
    return _public_ui_index_response()


@app.get("/subscription/{telegram_id}/{token}")
def public_subscription_page(telegram_id: int, token: str):
    _ = telegram_id, token
    return _public_ui_index_response()


@app.get("/cabinet")
def public_cabinet_page():
    return _public_ui_index_response()


@app.get("/cabinet/")
def public_cabinet_page_slash():
    return _public_ui_index_response()


@app.get("/cabinet/{path:path}")
def public_cabinet_nested_page(path: str):
    _ = path
    return _public_ui_index_response()


@app.get("/api/public/config")
def public_config_api():
    bot_url = str(settings.public_bot_url or "https://t.me/trumpvlessbot").strip() or "https://t.me/trumpvlessbot"
    bot_username = str(bot_url.rsplit("/", 1)[-1] or "").strip().lstrip("@")
    if not bot_username:
        bot_username = "trumpvlessbot"
    support_url = str(settings.public_help_url or "https://t.me/trumpvpnhelp").strip() or "https://t.me/trumpvpnhelp"
    return {
        "brand": "TrumpVPN",
        "bot_url": bot_url,
        "bot_username": bot_username,
        "support_url": support_url,
    }


@app.post("/api/public/auth/telegram")
def public_auth_telegram(payload: TelegramAuthRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    telegram_id, username = _verify_telegram_auth_payload(payload)
    user = get_or_create_user(db, telegram_id=telegram_id, username=username)
    _set_public_user_cookie(response, telegram_id=telegram_id, request=request)
    session_token = make_public_user_session_token(int(telegram_id))
    return {
        "ok": True,
        "session_token": session_token,
        "expires_in": max(1, int(settings.public_user_session_hours or 720)) * 3600,
        "user": {
            "telegram_id": int(user.telegram_id),
            "username": str(user.username or ""),
        },
    }


@app.post("/api/public/auth/miniapp")
def public_auth_miniapp(
    payload: TelegramMiniAppAuthRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    telegram_id, username = _verify_telegram_miniapp_init_data(payload.init_data)
    user = get_or_create_user(db, telegram_id=telegram_id, username=username)
    _set_public_user_cookie(response, telegram_id=telegram_id, request=request)
    session_token = make_public_user_session_token(int(telegram_id))
    return {
        "ok": True,
        "session_token": session_token,
        "expires_in": max(1, int(settings.public_user_session_hours or 720)) * 3600,
        "user": {
            "telegram_id": int(user.telegram_id),
            "username": str(user.username or ""),
        },
    }


@app.post("/api/public/auth/session/refresh")
def public_auth_session_refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    _set_public_user_cookie(response, telegram_id=int(user.telegram_id), request=request)
    return {
        "ok": True,
        "session_token": make_public_user_session_token(int(user.telegram_id)),
        "telegram_id": int(user.telegram_id),
        "expires_in": max(1, int(settings.public_user_session_hours or 720)) * 3600,
    }


@app.post("/api/public/auth/logout")
def public_auth_logout(response: Response):
    _clear_public_user_cookie(response)
    return {"ok": True}


@app.post("/api/public/analytics/event")
def public_analytics_event(payload: PublicAnalyticsEventRequest, request: Request, db: Session = Depends(get_db)):
    user: User | None = None
    try:
        user = _public_user_from_request(request, db)
    except HTTPException:
        user = None
    remote_addr = str(getattr(getattr(request, "client", None), "host", "") or "")
    details = {
        "event": str(payload.event or "")[:64],
        "meta": payload.meta if isinstance(payload.meta, dict) else {},
        "telegram_id": int(user.telegram_id) if user else 0,
        "ua": str(request.headers.get("user-agent", "") or "")[:255],
    }
    db.add(
        AdminAuditLog(
            admin_telegram_id=int(settings.admin_telegram_id or 0),
            action="public_event",
            entity_type="public_ui",
            entity_id=str(int(user.telegram_id) if user else ""),
            request_path=str(getattr(getattr(request, "url", None), "path", "") or "")[:255],
            remote_addr=remote_addr[:64],
            details_json=json.dumps(details, ensure_ascii=False),
        )
    )
    db.commit()
    return {"ok": True}


@app.get("/api/public/cabinet")
def public_cabinet(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    return _public_cabinet_payload(db, user)


@app.post("/api/public/cabinet/payments/create")
def public_cabinet_create_payment(payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    amount_rub = int(payload.get("amount_rub") or 0)
    gateway = str(payload.get("gateway") or "").strip() or None
    idempotency_key = str(payload.get("idempotency_key") or "").strip() or None
    req = CreatePaymentRequest(
        telegram_id=int(user.telegram_id),
        amount_rub=amount_rub,
        gateway=gateway,
        idempotency_key=idempotency_key,
    )
    return create_payment(req, db)


@app.post("/api/public/cabinet/payments/check")
def public_cabinet_check_payment(payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    invoice_id = int(payload.get("invoice_id") or 0)
    req = CheckPaymentRequest(telegram_id=int(user.telegram_id), invoice_id=invoice_id)
    return check_payment(req, db)


@app.get("/api/public/cabinet/payments")
def public_cabinet_payments(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    return list_payments(int(user.telegram_id), db)


@app.post("/api/public/cabinet/renew-from-balance")
def public_cabinet_renew_from_balance(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    return renew_from_balance(RenewFromBalanceRequest(telegram_id=int(user.telegram_id)), db)


@app.post("/api/public/cabinet/purchase-plan")
def public_cabinet_purchase_plan(payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    plan_id = str(payload.get("plan_id") or "").strip()
    return purchase_subscription_plan(PurchaseSubscriptionPlanRequest(telegram_id=int(user.telegram_id), plan_id=plan_id), db)


@app.post("/api/public/cabinet/promo/apply")
def public_cabinet_apply_promo(payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    code = str(payload.get("code") or "").strip()
    return apply_promo(ApplyPromoRequest(telegram_id=int(user.telegram_id), code=code), db)


@app.post("/api/public/cabinet/welcome/claim")
def public_cabinet_claim_welcome(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    return claim_welcome_bonus(ClaimWelcomeBonusRequest(telegram_id=int(user.telegram_id)), db)


@app.get("/api/public/cabinet/giveaways")
def public_cabinet_giveaways(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    return active_giveaways(telegram_id=int(user.telegram_id), db=db)


@app.post("/api/public/cabinet/giveaways/join")
def public_cabinet_join_giveaway(payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    giveaway_id = int(payload.get("giveaway_id") or 0)
    return join_giveaway({"telegram_id": int(user.telegram_id), "giveaway_id": giveaway_id}, db)


@app.get("/api/public/cabinet/fortune")
def public_cabinet_fortune(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    return _fortune_state_for_user(db, user)


@app.post("/api/public/cabinet/fortune/spin")
def public_cabinet_fortune_spin(request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    result = _apply_fortune_spin(db, user)
    user = fetch_user_with_configs(db, int(user.telegram_id)) or user
    return {
        "ok": True,
        "result": result,
        "fortune": _fortune_state_for_user(db, user),
        "user": serialize_user(user),
    }


@app.post("/api/public/cabinet/configs/revoke")
def public_cabinet_revoke_config(payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    user = _public_user_from_request(request, db)
    config_id = int(payload.get("config_id") or 0)
    if config_id <= 0:
        raise HTTPException(status_code=400, detail="config_id is required")
    target_cfg = db.scalar(
        select(ClientConfig).where(
            ClientConfig.id == config_id,
            ClientConfig.user_id == user.id,
            ClientConfig.is_active.is_(True),
        )
    )
    if not target_cfg:
        raise HTTPException(status_code=404, detail="Active config not found")
    device_name = str(target_cfg.device_name or "").strip()
    rows = db.scalars(
        select(ClientConfig).where(
            ClientConfig.user_id == user.id,
            ClientConfig.device_name == device_name,
            ClientConfig.is_active.is_(True),
        )
    ).all()
    removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
        db,
        rows,
        remove_timeout=90.0,
        restart_timeout=90.0,
    )
    now = utc_now()
    revoked = 0
    for cfg in rows:
        if int(cfg.id) not in removed_ids:
            continue
        cfg.is_active = False
        cfg.revoked_at = now
        revoked += 1
    db.commit()
    all_errors = list(errors) + list(warnings)
    local_only = any("local revoke only" in str(item or "").lower() for item in warnings)
    failed_count = max(0, len(rows) - int(revoked))
    if revoked <= 0 and all_errors:
        raise HTTPException(status_code=502, detail=f"VPN revoke failed: {all_errors[0]}")
    return {
        "status": "ok",
        "config_id": int(target_cfg.id),
        "revoked_count": int(revoked),
        "failed_count": int(failed_count),
        "revoked_mode": "local_only" if local_only else "remote",
        "errors": all_errors,
    }


@app.get("/api/public/subscription/{telegram_id}/{token}")
def public_subscription_preview_api(
    telegram_id: int,
    token: str,
    request: Request,
    fmt: str = "b64",
    with_stats: int = 0,
    db: Session = Depends(get_db),
):
    prepared = _prepare_user_subscription_data(
        db=db,
        telegram_id=telegram_id,
        token=token,
        request=request,
        fmt=fmt,
        with_stats=with_stats,
    )
    return _build_subscription_preview_payload(request, prepared)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sub/{telegram_id}/{token}", response_class=PlainTextResponse)
def user_subscription(
    telegram_id: int,
    token: str,
    request: Request,
    fmt: str = "b64",
    with_stats: int = 0,
    db: Session = Depends(get_db),
):
    prepared = _prepare_user_subscription_data(
        db=db,
        telegram_id=telegram_id,
        token=token,
        request=request,
        fmt=fmt,
        with_stats=with_stats,
    )

    if _is_browser_subscription_preview_request(request, fmt):
        target = _public_subscription_page_url(request, prepared.telegram_id, prepared.token)
        return RedirectResponse(target, status_code=307)

    payload = "\n".join(prepared.links)
    if prepared.fmt_norm in {"raw", "plain", "txt"}:
        response_payload = payload
    else:
        response_payload = base64.b64encode(payload.encode("utf-8")).decode("utf-8")

    profile_title = (
        f"TrumpVPN | days={prepared.days_left} | used={_format_bytes_short(prepared.upload + prepared.download)} | "
        f"servers={len(prepared.links)}"
    )
    profile_title_b64 = base64.b64encode(profile_title.encode("utf-8")).decode("ascii")
    headers = {
        "Cache-Control": "no-store",
        "Subscription-Userinfo": f"upload={prepared.upload}; download={prepared.download}; total=0; expire={prepared.expire_ts}",
        "Profile-Title": f"base64:{profile_title_b64}",
        "Profile-Update-Interval": "1",
    }
    return PlainTextResponse(response_payload, headers=headers)


@api_users.post("/register", dependencies=[Depends(require_internal_token)])
def register_user(payload: RegisterUserRequest, db: Session = Depends(get_db)):
    if payload.telegram_id <= 0:
        raise HTTPException(status_code=400, detail="telegram_id must be positive")
    is_new = db.scalar(select(User.id).where(User.telegram_id == payload.telegram_id)) is None
    get_or_create_user(
        db,
        telegram_id=payload.telegram_id,
        username=payload.username,
        referrer_telegram_id=payload.referrer_telegram_id,
    )
    user = fetch_user_with_configs(db, payload.telegram_id)
    invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
    result = serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)
    result["is_new"] = is_new
    return result


@api_users.get("/{telegram_id}", dependencies=[Depends(require_internal_token)])
def get_user(telegram_id: int, with_stats: int = 0, db: Session = Depends(get_db)):
    user = fetch_user_with_configs(db, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    invited_count, total_bonus = user_referral_stats(db, user.id)
    result = serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)
    if int(with_stats or 0) > 0:
        try:
            upload, download = _aggregate_user_traffic_bytes(
                [cfg for cfg in list(user.configs or []) if cfg.is_active and cfg.server],
                total_timeout_seconds=1.6,
                per_server_timeout_seconds=0.7,
            )
        except Exception:
            upload, download = 0, 0
        result.update(
            {
                "traffic_upload": int(upload),
                "traffic_download": int(download),
                "traffic_total": int(upload) + int(download),
            }
        )
    return result


@api_users.post("/extend", dependencies=[Depends(require_internal_token)])
def extend_user_subscription(payload: ExtendSubscriptionRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    extend_subscription(db, user, payload.days)
    user = fetch_user_with_configs(db, payload.telegram_id)
    invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
    return serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)


@api_users.post("/renew-from-balance", dependencies=[Depends(require_internal_token)])
def renew_from_balance(payload: RenewFromBalanceRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    if not charge_balance_for_subscription(db, user, periods=1):
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient balance. Need {settings.subscription_price_rub} RUB",
        )
    user = fetch_user_with_configs(db, payload.telegram_id)
    invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
    return serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)


@api_users.post("/purchase-plan", dependencies=[Depends(require_internal_token)])
def purchase_subscription_plan(payload: PurchaseSubscriptionPlanRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    plan = subscription_plan_by_id(payload.plan_id)
    if not plan:
        raise HTTPException(status_code=400, detail="Unknown subscription plan")
    price_rub = int(plan.get("price_rub") or 0)
    days = subscription_plan_days(plan)
    if price_rub <= 0 or days <= 0:
        raise HTTPException(status_code=400, detail="Invalid subscription plan")
    balance = int(user.balance_rub or 0)
    if balance < price_rub:
        missing = price_rub - balance
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient balance. Need {price_rub} RUB, missing {missing} RUB",
        )
    user.balance_rub = balance - price_rub
    _apply_subscription_days_no_commit(user, days)
    db.commit()
    user = fetch_user_with_configs(db, payload.telegram_id)
    invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
    result = serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)
    result.update(
        {
            "plan_id": str(plan.get("id") or ""),
            "charged_rub": price_rub,
            "days_added": days,
        }
    )
    return result


@api_users.post("/claim-welcome-bonus", dependencies=[Depends(require_internal_token)])
def claim_welcome_bonus(payload: ClaimWelcomeBonusRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    if user.trial_bonus_granted:
        user = fetch_user_with_configs(db, payload.telegram_id)
        invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
        result = serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)
        result["claimed"] = False
        result["days_added"] = 0
        return result

    bonus_days = max(1, int(settings.welcome_bonus_days))
    base = utc_now()
    if user.subscription_until and user.subscription_until > base:
        base = user.subscription_until
    user.subscription_until = base + timedelta(days=bonus_days)
    user.trial_bonus_granted = True
    db.commit()

    user = fetch_user_with_configs(db, payload.telegram_id)
    invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
    result = serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)
    result["claimed"] = True
    result["days_added"] = bonus_days
    return result


@api_servers.get("", dependencies=[Depends(require_internal_token)])
def list_servers(db: Session = Depends(get_db)):
    rows = db.scalars(select(VpnServer).where(VpnServer.enabled.is_(True)).order_by(VpnServer.id)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "host": s.host,
            "port": s.port,
            "sni": s.sni,
            "protocol": server_protocol(s),
        }
        for s in rows
    ]


@api_servers.get("/runtime", dependencies=[Depends(require_internal_token)])
def list_servers_runtime(db: Session = Depends(get_db)):
    rows = db.scalars(select(VpnServer).where(VpnServer.enabled.is_(True)).order_by(VpnServer.id)).all()
    result = []
    touched = False
    runtime_deadline = time.monotonic() + _runtime_checks_budget_seconds(len(rows), base_seconds=8.0)
    for s in rows:
        runtime = {
            "health": "skipped",
            "xray_state": "-",
            "port_open": False,
            "vpn_reachable": False,
            "vpn_latency_ms": None,
            "vpn_latency_text": "-",
            "loadavg": "-",
            "version": "-",
            "uptime": "-",
            "error": "runtime check skipped by deadline",
        }
        if time.monotonic() <= runtime_deadline:
            runtime = _check_server_runtime(s)
            _record_load_sample(db, s.id, runtime)
            touched = True
        result.append(
            {
                "id": s.id,
                "name": s.name,
                "host": s.host,
                "port": s.port,
                "protocol": server_protocol(s),
                "runtime": runtime,
            }
        )
    if touched:
        db.commit()
    return result


@api_configs.post("/issue", dependencies=[Depends(require_internal_token)])
def issue_config(payload: ConfigIssueRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    if not ensure_active_subscription_from_balance(db, user):
        raise HTTPException(
            status_code=402,
            detail=f"Service inactive. Top up balance or pay {settings.subscription_price_rub} RUB for 30 days.",
        )

    server = db.scalar(select(VpnServer).where(VpnServer.id == payload.server_id, VpnServer.enabled.is_(True)))
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    existing = db.scalar(
        select(ClientConfig).where(
            ClientConfig.user_id == user.id,
            ClientConfig.device_name == payload.device_name,
            ClientConfig.is_active.is_(True),
        )
    )
    if existing:
        return {
            "id": existing.id,
            "server_name": server.name,
            "protocol": server_protocol(server),
            "device_name": existing.device_name,
            "vless_url": existing.vless_url,
            "is_active": True,
            "reused": True,
        }

    active_devices_count = int(
        db.scalar(
            select(func.count(func.distinct(ClientConfig.device_name))).where(
                ClientConfig.user_id == user.id,
                ClientConfig.is_active.is_(True),
            )
        )
        or 0
    )
    if active_devices_count >= MAX_ACTIVE_CONFIGS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Device limit reached: max {MAX_ACTIVE_CONFIGS_PER_USER} active devices per account. Revoke one first.",
        )

    client_uuid = str(uuid4())
    email_tag = generate_email_tag(payload.telegram_id, payload.device_name)
    vless_label = f"{server.name}-{payload.device_name}"
    vless_url = build_client_url(server, client_uuid, vless_label)

    try:
        add_client_on_server(server, client_uuid, email_tag, user.subscription_until)
    except VPNProvisionError as exc:
        raise HTTPException(status_code=502, detail=f"VPN server provisioning failed: {exc}") from exc

    cfg = ClientConfig(
        user_id=user.id,
        server_id=server.id,
        device_name=payload.device_name,
        client_uuid=client_uuid,
        email_tag=email_tag,
        vless_url=vless_url,
        is_active=True,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return {
        "id": cfg.id,
        "server_name": server.name,
        "protocol": server_protocol(server),
        "device_name": cfg.device_name,
        "vless_url": cfg.vless_url,
        "is_active": cfg.is_active,
        "reused": False,
    }


@api_configs.post("/revoke", dependencies=[Depends(require_internal_token)])
def revoke_config(payload: ConfigRevokeRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    target_cfg = db.scalar(
        select(ClientConfig).where(
            ClientConfig.id == payload.config_id,
            ClientConfig.user_id == user.id,
            ClientConfig.is_active.is_(True),
        )
    )
    if not target_cfg:
        raise HTTPException(status_code=404, detail="Active config not found")
    device_name = str(target_cfg.device_name or "").strip()
    rows = db.scalars(
        select(ClientConfig).where(
            ClientConfig.user_id == user.id,
            ClientConfig.device_name == device_name,
            ClientConfig.is_active.is_(True),
        )
    ).all()
    removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
        db,
        rows,
        remove_timeout=90.0,
        restart_timeout=90.0,
    )
    now = utc_now()
    revoked = 0
    for cfg in rows:
        if int(cfg.id) not in removed_ids:
            continue
        cfg.is_active = False
        cfg.revoked_at = now
        revoked += 1
    db.commit()
    all_errors = list(errors) + list(warnings)
    if revoked <= 0 and all_errors:
        raise HTTPException(status_code=502, detail=f"VPN revoke failed: {all_errors[0]}")
    return {
        "status": "ok",
        "config_id": target_cfg.id,
        "revoked_count": revoked,
        "errors": all_errors,
    }


@api_admin.post("/servers")
def upsert_server(payload: UpsertServerRequest, db: Session = Depends(get_db)):
    protocol = str(payload.protocol or "").strip().lower()
    if protocol not in SERVER_PROTOCOLS:
        protocol = SERVER_PROTOCOL_VLESS_REALITY
    payload.protocol = protocol
    if protocol == SERVER_PROTOCOL_HYSTERIA2:
        payload.public_key = str(payload.public_key or "-")
        payload.short_id = str(payload.short_id or "-")
        add_script = str(payload.remote_add_script or "").strip()
        remove_script = str(payload.remote_remove_script or "").strip()
        if not add_script or add_script == DEFAULT_VLESS_ADD_SCRIPT:
            add_script = DEFAULT_HYSTERIA2_ADD_SCRIPT
        if not remove_script or remove_script == DEFAULT_VLESS_REMOVE_SCRIPT:
            remove_script = DEFAULT_HYSTERIA2_REMOVE_SCRIPT
        payload.remote_add_script = add_script
        payload.remote_remove_script = remove_script
    else:
        if not str(payload.public_key or "").strip() or not str(payload.short_id or "").strip():
            raise HTTPException(status_code=400, detail="public_key and short_id are required for vless_reality")
        add_script = str(payload.remote_add_script or "").strip()
        remove_script = str(payload.remote_remove_script or "").strip()
        if not add_script or add_script == DEFAULT_HYSTERIA2_ADD_SCRIPT:
            add_script = DEFAULT_VLESS_ADD_SCRIPT
        if not remove_script or remove_script == DEFAULT_HYSTERIA2_REMOVE_SCRIPT:
            remove_script = DEFAULT_VLESS_REMOVE_SCRIPT
        payload.remote_add_script = add_script
        payload.remote_remove_script = remove_script
    server = db.scalar(select(VpnServer).where(VpnServer.name == payload.name))
    if not server:
        server = VpnServer(name=payload.name)
        db.add(server)
    else:
        old_protocol = server_protocol(server)
        if old_protocol != protocol:
            active_on_server = _active_configs_count_for_server(db, int(server.id))
            if active_on_server > 0:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Cannot change protocol on server with active configs. "
                        f"Server '{server.name}' has {active_on_server} active configs. "
                        "Create a new server or revoke existing configs first."
                    ),
                )
    for field, value in payload.model_dump().items():
        setattr(server, field, value)
    db.commit()
    db.refresh(server)
    return {"status": "ok", "server_id": server.id}


@api_admin.get("/servers")
def list_all_servers(db: Session = Depends(get_db)):
    rows = db.scalars(select(VpnServer).order_by(VpnServer.id)).all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "enabled": s.enabled,
            "host": s.host,
            "ssh_host": s.ssh_host,
            "protocol": server_protocol(s),
        }
        for s in rows
    ]


@api_admin.delete("/servers/{server_id}")
def disable_server(server_id: int, db: Session = Depends(get_db)):
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.enabled = False
    db.commit()
    return {"status": "ok"}


def _normalize_idempotency_key(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    if not value:
        return ""
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in ("-", "_", "."))
    return cleaned[:80]


@api_payments.post("/create", dependencies=[Depends(require_internal_token)])
def create_payment(payload: CreatePaymentRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, payload.telegram_id)
    amount_rub = int(payload.amount_rub)
    idem_key = _normalize_idempotency_key(payload.idempotency_key)
    gateway_requested = (payload.gateway or settings.payment_gateway or "cryptopay").strip().lower()
    gateway = gateway_requested
    platega_payment_method: int | None = None
    if gateway_requested in {"platega_crypto", "platega_card", "platega_sbp"}:
        gateway = "platega"
        platega_payment_method = _platega_payment_method_for_gateway_code(gateway_requested)
    if gateway not in ("cryptopay", "yoomoney", "platega"):
        raise HTTPException(status_code=400, detail="Unsupported payment gateway")

    if idem_key:
        existing = db.scalar(
            select(PaymentInvoice)
            .where(PaymentInvoice.user_id == user.id, PaymentInvoice.idempotency_key == idem_key)
            .order_by(PaymentInvoice.created_at.desc())
        )
        if existing and str(existing.status or "").lower() in {"active", "pending", "created", "processing"}:
            return {
                "invoice_id": existing.invoice_id,
                "status": existing.status,
                "amount_rub": existing.amount_rub,
                "payable_rub": existing.payable_rub,
                "promo_code": existing.promo_code_text,
                "promo_discount_percent": existing.promo_discount_percent,
                "kind": existing.kind,
                "gateway": gateway_requested if gateway_requested else gateway,
                "pay_url": existing.pay_url,
                "created_at": existing.created_at,
                "idempotency_key": existing.idempotency_key,
                "idempotent_reuse": True,
            }
    if amount_rub < settings.min_topup_rub or amount_rub > settings.max_topup_rub:
        raise HTTPException(
            status_code=400,
            detail=f"Top up amount must be between {settings.min_topup_rub} and {settings.max_topup_rub} RUB",
        )
    payable_rub = int(amount_rub)
    promo_discount_percent = 0
    promo_code_text: str | None = None
    applied_discount_promo: PromoCode | None = None
    if user.pending_discount_promo_id:
        pending = db.scalar(select(PromoCode).where(PromoCode.id == int(user.pending_discount_promo_id)))
        # Pending discount promo is one-time: consume or clear it on invoice creation attempt.
        user.pending_discount_promo_id = None
        if pending and pending.kind == PROMO_KIND_TOPUP_DISCOUNT:
            pending_error = _promo_validation_error(db, pending, user)
            if not pending_error:
                promo_discount_percent = max(1, min(95, int(pending.value_int or 0)))
                payable_rub = max(1, int(round(amount_rub * (100 - promo_discount_percent) / 100)))
                promo_code_text = pending.code
                applied_discount_promo = pending

    # Anti-double-click fallback for clients without idempotency key:
    # reuse an active invoice created recently with same amount and gateway.
    if not idem_key:
        recent_active = db.scalar(
            select(PaymentInvoice)
            .where(
                PaymentInvoice.user_id == user.id,
                PaymentInvoice.amount_rub == amount_rub,
                PaymentInvoice.kind == f"topup_{gateway}",
                PaymentInvoice.status.in_(("active", "pending", "created", "processing")),
                PaymentInvoice.created_at >= utc_now() - timedelta(minutes=2),
            )
            .order_by(PaymentInvoice.created_at.desc())
        )
        if recent_active:
            return {
                "invoice_id": recent_active.invoice_id,
                "status": recent_active.status,
                "amount_rub": recent_active.amount_rub,
                "payable_rub": recent_active.payable_rub,
                "promo_code": recent_active.promo_code_text,
                "promo_discount_percent": recent_active.promo_discount_percent,
                "kind": recent_active.kind,
                "gateway": gateway_requested if gateway_requested else gateway,
                "pay_url": recent_active.pay_url,
                "created_at": recent_active.created_at,
                "idempotency_key": recent_active.idempotency_key,
                "idempotent_reuse": True,
            }
    try:
        if gateway == "yoomoney":
            invoice = yoomoney_create_invoice(db, payload.telegram_id, payable_rub)
        elif gateway == "platega":
            invoice = platega_create_invoice(
                db,
                payload.telegram_id,
                payable_rub,
                payment_method=platega_payment_method,
            )
        else:
            invoice = cryptopay_create_invoice(payload.telegram_id, payable_rub)
            gateway = "cryptopay"
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{gateway_requested} create invoice failed: {exc}") from exc

    payment = PaymentInvoice(
        user_id=user.id,
        invoice_id=int(invoice["invoice_id"]),
        invoice_hash=str(invoice.get("hash") or invoice.get("label") or f"inv_{invoice['invoice_id']}"),
        status=str(invoice.get("status", "active")),
        amount_rub=amount_rub,
        payable_rub=payable_rub,
        months=0,
        kind=f"topup_{gateway}",
        promo_code_text=promo_code_text,
        promo_discount_percent=promo_discount_percent,
        idempotency_key=idem_key or None,
        credited_rub=0,
        referral_bonus_rub=0,
        pay_url=str(invoice["pay_url"]),
        payload=str(invoice.get("payload") or invoice.get("label") or "") or None,
        raw_response=json.dumps(invoice, ensure_ascii=False),
    )
    db.add(payment)
    db.flush()
    if applied_discount_promo:
        db.add(
            PromoRedemption(
                promo_code_id=applied_discount_promo.id,
                user_id=user.id,
                payment_invoice_id=payment.id,
                kind=PROMO_KIND_TOPUP_DISCOUNT,
                value_int=promo_discount_percent,
            )
        )
    db.commit()
    db.refresh(payment)
    return {
        "invoice_id": payment.invoice_id,
        "status": payment.status,
        "amount_rub": payment.amount_rub,
        "payable_rub": payment.payable_rub,
        "promo_code": payment.promo_code_text,
        "promo_discount_percent": payment.promo_discount_percent,
        "kind": payment.kind,
        "gateway": gateway_requested if gateway_requested else gateway,
        "pay_url": payment.pay_url,
        "created_at": payment.created_at,
        "idempotency_key": payment.idempotency_key,
        "idempotent_reuse": False,
    }


@api_payments.post("/check", dependencies=[Depends(require_internal_token)])
def check_payment(payload: CheckPaymentRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, payload.telegram_id)
    payment = db.scalar(
        select(PaymentInvoice).where(
            PaymentInvoice.invoice_id == payload.invoice_id,
            PaymentInvoice.user_id == user.id,
        )
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment invoice not found")

    is_yoomoney = str(payment.kind or "").endswith("_yoomoney")
    is_platega = str(payment.kind or "").endswith("_platega")
    if is_yoomoney:
        db.refresh(payment)
        db.refresh(user)
        return {
            "invoice_id": payment.invoice_id,
            "status": payment.status,
            "amount_rub": payment.amount_rub,
            "payable_rub": payment.payable_rub,
            "promo_code": payment.promo_code_text,
            "promo_discount_percent": payment.promo_discount_percent,
            "credited_rub": payment.credited_rub,
            "referral_bonus_rub": payment.referral_bonus_rub,
            "paid_at": payment.paid_at,
            "balance_rub": int(user.balance_rub or 0),
            "subscription_until": user.subscription_until,
        }

    source = "cryptopay"
    try:
        if is_platega:
            invoice = platega_get_invoice(payment.invoice_hash)
            remote_status = _platega_status_to_local(_platega_extract_status(invoice))
            source = "platega"
        else:
            invoice = cryptopay_get_invoice(payment.invoice_id)
            remote_status = str(invoice.get("status", payment.status))
    except Exception as exc:
        gateway_title = "Platega" if is_platega else "CryptoPay"
        raise HTTPException(status_code=502, detail=f"{gateway_title} check invoice failed: {exc}") from exc

    newly_paid = remote_status == "paid" and payment.status != "paid"
    payment.status = remote_status
    payment.raw_response = json.dumps(invoice, ensure_ascii=False)
    if newly_paid:
        payment.paid_at = utc_now()
        user.balance_rub = int(user.balance_rub or 0) + int(payment.amount_rub or 0)
        payment.credited_rub = int(payment.amount_rub or 0)
        apply_referral_bonus(db, user, payment)
        apply_referral_payment_days_bonus(db, user, payment, bonus_days=7, window_days=7)
        # Auto-activate one paid period from balance when user had inactive service.
        if not is_subscription_active(user):
            charge_balance_for_subscription(db, user, periods=1)
    db.commit()
    db.refresh(payment)
    db.refresh(user)
    if newly_paid:
        notify_payment_paid(user, payment, source=source)
    return {
        "invoice_id": payment.invoice_id,
        "status": payment.status,
        "amount_rub": payment.amount_rub,
        "payable_rub": payment.payable_rub,
        "promo_code": payment.promo_code_text,
        "promo_discount_percent": payment.promo_discount_percent,
        "credited_rub": payment.credited_rub,
        "referral_bonus_rub": payment.referral_bonus_rub,
        "paid_at": payment.paid_at,
        "balance_rub": int(user.balance_rub or 0),
        "subscription_until": user.subscription_until,
    }


@api_payments.post("/yoomoney/webhook")
async def yoomoney_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = {k: v[0] for k, v in parse_qs(raw_body).items()}
    label = str(form.get("label", "")).strip()
    if not label:
        return {"status": "ignored", "reason": "empty label"}

    secret = settings.yoomoney_notification_secret.strip()
    if secret and not _verify_yoomoney_signature(form, secret):
        raise HTTPException(status_code=403, detail="Invalid yoomoney signature")

    payment = db.scalar(
        select(PaymentInvoice).where(
            PaymentInvoice.kind == "topup_yoomoney",
            PaymentInvoice.payload == label,
        )
    )
    if not payment:
        payment = db.scalar(
            select(PaymentInvoice).where(
                PaymentInvoice.kind == "topup_yoomoney",
                PaymentInvoice.invoice_hash == label,
            )
        )
    if not payment:
        return {"status": "ignored", "reason": "payment not found"}

    user = db.scalar(select(User).where(User.id == payment.user_id))
    if not user:
        return {"status": "ignored", "reason": "user not found"}

    was_paid = payment.status == "paid"
    payment.status = "paid"
    payment.raw_response = raw_body
    if not was_paid:
        payment.paid_at = utc_now()
        credited_amount = int(payment.amount_rub or 0)
        user.balance_rub = int(user.balance_rub or 0) + credited_amount
        payment.credited_rub = credited_amount
        apply_referral_bonus(db, user, payment)
        apply_referral_payment_days_bonus(db, user, payment, bonus_days=7, window_days=7)
        if not is_subscription_active(user):
            charge_balance_for_subscription(db, user, periods=1)
    db.commit()
    if not was_paid:
        notify_payment_paid(user, payment, source="yoomoney")
    return {"status": "ok"}


@api_payments.post("/platega/webhook")
async def platega_webhook(
    request: Request,
    x_merchant_id: str = Header(default="", alias="X-MerchantId"),
    x_secret: str = Header(default="", alias="X-Secret"),
    db: Session = Depends(get_db),
):
    merchant_expected = str(settings.platega_merchant_id or "").strip()
    secret_expected = str(settings.platega_api_key or "").strip()
    if merchant_expected and x_merchant_id.strip() != merchant_expected:
        raise HTTPException(status_code=403, detail="Invalid Platega merchant header")
    if secret_expected and x_secret.strip() != secret_expected:
        raise HTTPException(status_code=403, detail="Invalid Platega secret header")

    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored", "reason": "invalid json"}
    if not isinstance(payload, dict):
        return {"status": "ignored", "reason": "invalid payload"}

    transaction_id = _platega_extract_transaction_id(payload)
    if not transaction_id:
        return {"status": "ignored", "reason": "transaction id not found"}
    remote_status = _platega_status_to_local(_platega_extract_status(payload))

    payment = db.scalar(
        select(PaymentInvoice).where(
            PaymentInvoice.kind == "topup_platega",
            PaymentInvoice.invoice_hash == transaction_id,
        )
    )
    if not payment:
        return {"status": "ignored", "reason": "payment not found"}
    user = db.scalar(select(User).where(User.id == payment.user_id))
    if not user:
        return {"status": "ignored", "reason": "user not found"}

    was_paid = payment.status == "paid"
    payment.status = remote_status
    payment.raw_response = json.dumps(payload, ensure_ascii=False)
    if remote_status == "paid" and not was_paid:
        payment.paid_at = utc_now()
        credited_amount = int(payment.amount_rub or 0)
        user.balance_rub = int(user.balance_rub or 0) + credited_amount
        payment.credited_rub = credited_amount
        apply_referral_bonus(db, user, payment)
        apply_referral_payment_days_bonus(db, user, payment, bonus_days=7, window_days=7)
        if not is_subscription_active(user):
            charge_balance_for_subscription(db, user, periods=1)
    db.commit()
    if remote_status == "paid" and not was_paid:
        notify_payment_paid(user, payment, source="platega")
    return {"status": "ok"}


@api_payments.get("/{telegram_id}", dependencies=[Depends(require_internal_token)])
def list_payments(telegram_id: int, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        return []
    rows = db.scalars(
        select(PaymentInvoice)
        .where(PaymentInvoice.user_id == user.id)
        .order_by(PaymentInvoice.created_at.desc())
        .limit(30)
    ).all()
    return [
        {
            "invoice_id": p.invoice_id,
            "status": p.status,
            "amount_rub": p.amount_rub,
            "payable_rub": p.payable_rub,
            "kind": p.kind,
            "promo_code": p.promo_code_text,
            "promo_discount_percent": p.promo_discount_percent,
            "credited_rub": p.credited_rub,
            "referral_bonus_rub": p.referral_bonus_rub,
            "created_at": p.created_at,
            "paid_at": p.paid_at,
            "pay_url": p.pay_url,
        }
        for p in rows
    ]


@api_promos.post("/apply", dependencies=[Depends(require_internal_token)])
def apply_promo(payload: ApplyPromoRequest, db: Session = Depends(get_db)):
    user = get_or_create_user(db, telegram_id=payload.telegram_id)
    result = apply_promo_for_user(db, user, payload.code)
    user = fetch_user_with_configs(db, payload.telegram_id)
    invited_count, total_bonus = user_referral_stats(db, user.id) if user else (0, 0)
    result["user"] = serialize_user(user, invited_count=invited_count, referral_bonus_rub=total_bonus)
    return result


def serialize_giveaway(giveaway: Giveaway, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    return {
        "id": int(giveaway.id),
        "title": str(giveaway.title or ""),
        "description": str(giveaway.description or ""),
        "prize": str(giveaway.prize or ""),
        "kind": str(giveaway.kind or ""),
        "starts_at": giveaway.starts_at,
        "ends_at": giveaway.ends_at,
        "enabled": bool(giveaway.enabled),
        "active": _is_giveaway_active(giveaway, now),
    }


@api_giveaways.get("/active")
def active_giveaways(telegram_id: int | None = None, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    now = utc_now()
    rows = db.scalars(select(Giveaway).where(Giveaway.enabled.is_(True)).order_by(Giveaway.created_at.desc())).all()
    result: list[dict[str, Any]] = []
    user_id: int | None = None
    if telegram_id:
        user = db.scalar(select(User).where(User.telegram_id == int(telegram_id)))
        if user:
            user_id = int(user.id)
    for g in rows:
        if not _is_giveaway_active(g, now):
            continue
        item = serialize_giveaway(g, now)
        item["participants"] = _giveaway_participant_count(db, g.id)
        if user_id:
            joined = db.scalar(
                select(GiveawayParticipant.id).where(
                    GiveawayParticipant.giveaway_id == g.id,
                    GiveawayParticipant.user_id == user_id,
                )
            )
            item["joined"] = bool(joined)
        else:
            item["joined"] = False
        result.append(item)
    return result


@api_giveaways.post("/join")
def join_giveaway(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    telegram_id = int(payload.get("telegram_id") or 0)
    giveaway_id = int(payload.get("giveaway_id") or 0)
    if telegram_id <= 0 or giveaway_id <= 0:
        raise HTTPException(status_code=400, detail="telegram_id and giveaway_id are required")
    giveaway = db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id))
    if not giveaway or not _is_giveaway_active(giveaway):
        raise HTTPException(status_code=404, detail="Giveaway not found or inactive")
    user = get_or_create_user(db, telegram_id=telegram_id)
    exists = db.scalar(
        select(GiveawayParticipant.id).where(
            GiveawayParticipant.giveaway_id == giveaway.id,
            GiveawayParticipant.user_id == user.id,
        )
    )
    if exists:
        return {"ok": True, "joined": True, "participants": _giveaway_participant_count(db, giveaway.id)}
    db.add(GiveawayParticipant(giveaway_id=giveaway.id, user_id=user.id))
    db.commit()
    return {"ok": True, "joined": True, "participants": _giveaway_participant_count(db, giveaway.id)}


def sweep_expired_local() -> dict[str, Any]:
    db = SessionLocal()
    try:
        now = utc_now()
        users = db.scalars(select(User).where(User.subscription_until.is_not(None))).all()
        expired_user_ids = {u.id for u in users if u.subscription_until and u.subscription_until <= now}
        if not expired_user_ids:
            return {"revoked": 0, "errors": []}

        active_configs = db.scalars(
            select(ClientConfig).where(ClientConfig.is_active.is_(True), ClientConfig.user_id.in_(expired_user_ids))
        ).all()
        removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
            db,
            active_configs,
            remove_timeout=90.0,
            restart_timeout=90.0,
        )
        revoked = 0
        for cfg in active_configs:
            if int(cfg.id) not in removed_ids:
                continue
            cfg.is_active = False
            cfg.revoked_at = now
            revoked += 1
        db.commit()
        return {"revoked": revoked, "errors": list(errors) + list(warnings)}
    finally:
        db.close()


def _subscription_days_left_dt(until: datetime, now: datetime | None = None) -> int:
    now = now or utc_now()
    if not until:
        return 0
    delta = (until - now).total_seconds()
    if delta <= 0:
        return 0
    return int((delta + 86399) // 86400)


def _fmt_user_subscription_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    msk_tz = timezone(timedelta(hours=3))
    return value.replace(tzinfo=timezone.utc).astimezone(msk_tz).strftime("%d.%m.%Y %H:%M MSK")


def _subscription_reminder_text(days_left: int, subscription_until: datetime | None) -> str:
    tail = _fmt_user_subscription_dt(subscription_until)
    if days_left <= 1:
        return (
            "вЏі Р’Р°С€Р° РїРѕРґРїРёСЃРєР° Р·Р°РєР°РЅС‡РёРІР°РµС‚СЃСЏ С‡РµСЂРµР· 1 РґРµРЅСЊ.\n"
            f"Р”Рѕ: {tail}\n\n"
            "РџСЂРѕРґР»РёС‚СЊ РјРѕР¶РЅРѕ РІ Р±РѕС‚Рµ: /menu в†’ РџРѕРґРїРёСЃРєР°"
        )
    return (
        "вЏі Р”Рѕ РѕРєРѕРЅС‡Р°РЅРёСЏ РїРѕРґРїРёСЃРєРё РѕСЃС‚Р°Р»РѕСЃСЊ 3 РґРЅСЏ.\n"
        f"Р”Рѕ: {tail}\n\n"
        "РџСЂРѕРґР»РёС‚СЊ РјРѕР¶РЅРѕ РІ Р±РѕС‚Рµ: /menu в†’ РџРѕРґРїРёСЃРєР°"
    )


def _send_subscription_reminders_once() -> int:
    db = SessionLocal()
    sent = 0
    try:
        now = utc_now()
        users = db.scalars(
            select(User).where(User.subscription_until.is_not(None), User.is_blocked.is_(False))
        ).all()
        for user in users:
            until = user.subscription_until
            if not until:
                continue
            days_left = _subscription_days_left_dt(until, now)
            if days_left <= 0:
                continue
            if days_left == 3 and user.reminder_3d_until != until:
                _send_telegram_message(int(user.telegram_id), _subscription_reminder_text(3, until))
                user.reminder_3d_until = until
                sent += 1
            if days_left == 1 and user.reminder_1d_until != until:
                _send_telegram_message(int(user.telegram_id), _subscription_reminder_text(1, until))
                user.reminder_1d_until = until
                sent += 1
        if sent:
            db.commit()
    finally:
        db.close()
    return sent


def _start_background_tasks() -> None:
    def sweep_loop():
        while True:
            try:
                sweep_expired_local()
            except Exception as exc:
                logging.warning("sweep_expired_local failed: %s", exc)
            time.sleep(300)

    def reminders_loop():
        while True:
            try:
                _send_subscription_reminders_once()
            except Exception as exc:
                logging.warning("subscription reminders failed: %s", exc)
            time.sleep(3600)

    threading.Thread(target=sweep_loop, daemon=True).start()
    threading.Thread(target=reminders_loop, daemon=True).start()


@api_maintenance.post("/sweep-expired", dependencies=[Depends(require_internal_token)])
def sweep_expired_endpoint():
    return sweep_expired_local()


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_latency_ms(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw == "-":
        return None
    if raw.endswith("ms"):
        raw = raw[:-2].strip()
    try:
        return max(0.0, float(raw))
    except Exception:
        return None


def _runtime_severity(runtime: dict[str, Any] | None) -> str:
    if not runtime:
        return "red"
    health = str(runtime.get("health", "error"))
    xray_state = str(runtime.get("xray_state", "unknown"))
    port_open = bool(runtime.get("port_open", False))
    vpn_reachable = bool(runtime.get("vpn_reachable", False))
    if health == "error" or xray_state != "active" or not port_open or not vpn_reachable:
        return "red"
    latency_ms = _parse_latency_ms(runtime.get("vpn_latency_ms"))
    if latency_ms is None:
        return "yellow" if health == "degraded" else "green"
    if latency_ms < 120:
        sev = "green"
    elif latency_ms < 250:
        sev = "yellow"
    else:
        sev = "red"
    if health == "degraded" and sev == "green":
        return "yellow"
    return sev


def _severity_emoji(severity: str) -> str:
    if severity == "green":
        return "рџџў"
    if severity == "yellow":
        return "рџџЎ"
    return "рџ”ґ"


def _severity_color(severity: str) -> str:
    if severity == "green":
        return "#22c55e"
    if severity == "yellow":
        return "#f59e0b"
    return "#ef4444"


def _runtime_circle(runtime: dict[str, Any] | None) -> str:
    return _severity_emoji(_runtime_severity(runtime))


def _record_load_sample(db: Session, server_id: int, runtime: dict[str, Any], min_interval_seconds: int = 60) -> None:
    last = db.scalar(
        select(ServerLoadSample)
        .where(ServerLoadSample.server_id == server_id)
        .order_by(ServerLoadSample.created_at.desc())
    )
    now = utc_now()
    if last and (now - last.created_at).total_seconds() < min_interval_seconds:
        return

    latency_ms = _parse_latency_ms(runtime.get("vpn_latency_ms"))
    load1 = float(runtime.get("load1") or 0.0)
    load5 = float(runtime.get("load5") or 0.0)
    load15 = float(runtime.get("load15") or 0.0)
    established_connections = int(runtime.get("established_connections") or 0)
    active_devices_estimate = int(runtime.get("active_devices_estimate") or 0)
    db.add(
        ServerLoadSample(
            server_id=server_id,
            load1=load1,
            load5=load5,
            load15=load15,
            latency_ms=float(latency_ms or 0.0),
            established_connections=established_connections,
            active_devices_estimate=active_devices_estimate,
            xray_state=str(runtime.get("xray_state", "unknown")),
            health=str(runtime.get("health", "unknown")),
        )
    )


def _parse_key_value_block(raw_text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in str(raw_text or "").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _parse_reality_block(raw_text: str) -> tuple[str, str, str, int]:
    values = _parse_key_value_block(raw_text)
    public_key = values.get("PUBLIC_KEY", "").strip()
    short_id = values.get("SHORT_ID", "").strip()
    sni = values.get("SNI", "").strip()
    port_raw = values.get("PORT", "").strip()
    if not public_key:
        raise ValueError("PUBLIC_KEY is required")
    if not short_id:
        raise ValueError("SHORT_ID is required")
    if not sni:
        raise ValueError("SNI is required")
    if not port_raw:
        raise ValueError("PORT is required")
    try:
        port = int(port_raw)
    except Exception as exc:
        raise ValueError("PORT must be numeric") from exc
    if port <= 0 or port > 65535:
        raise ValueError("PORT must be in range 1..65535")
    return public_key, short_id, sni, port


def _admin_server_defaults(db: Session) -> dict[str, Any]:
    sample = db.scalar(select(VpnServer).order_by(VpnServer.id))
    if sample:
        return {
            "protocol": server_protocol(sample),
            "fingerprint": sample.fingerprint or "chrome",
            "ssh_host": sample.ssh_host or sample.host,
            "ssh_port": int(sample.ssh_port or 22),
            "ssh_user": sample.ssh_user or "root",
            "ssh_key_path": sample.ssh_key_path or "/root/.ssh/id_rsa",
            "remote_add_script": sample.remote_add_script or DEFAULT_VLESS_ADD_SCRIPT,
            "remote_remove_script": sample.remote_remove_script or DEFAULT_VLESS_REMOVE_SCRIPT,
            "hy2_alpn": sample.hy2_alpn or "h3",
            "hy2_obfs": sample.hy2_obfs or "salamander",
            "hy2_obfs_password": sample.hy2_obfs_password or "",
            "hy2_insecure": bool(sample.hy2_insecure),
            "remote_add_script_hy2": DEFAULT_HYSTERIA2_ADD_SCRIPT,
            "remote_remove_script_hy2": DEFAULT_HYSTERIA2_REMOVE_SCRIPT,
        }
    return {
        "protocol": SERVER_PROTOCOL_VLESS_REALITY,
        "fingerprint": "chrome",
        "ssh_host": "",
        "ssh_port": 22,
        "ssh_user": "root",
        "ssh_key_path": "/root/.ssh/id_rsa",
        "remote_add_script": DEFAULT_VLESS_ADD_SCRIPT,
        "remote_remove_script": DEFAULT_VLESS_REMOVE_SCRIPT,
        "hy2_alpn": "h3",
        "hy2_obfs": "salamander",
        "hy2_obfs_password": "",
        "hy2_insecure": False,
        "remote_add_script_hy2": DEFAULT_HYSTERIA2_ADD_SCRIPT,
        "remote_remove_script_hy2": DEFAULT_HYSTERIA2_REMOVE_SCRIPT,
    }


def _active_configs_count_for_server(db: Session, server_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(ClientConfig.id)).where(
                ClientConfig.server_id == int(server_id),
                ClientConfig.is_active.is_(True),
            )
        )
        or 0
    )


def _admin_redirect(msg: str = "", error: str = "", target: str = "/admin/overview") -> RedirectResponse:
    params: list[str] = []
    if msg:
        params.append(f"msg={quote(msg, safe='')}")
    if error:
        params.append(f"error={quote(error, safe='')}")
    suffix = f"?{'&'.join(params)}" if params else ""
    return RedirectResponse(f"{target}{suffix}", status_code=303)


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
START_PROMO_IMAGE_PATH = Path(__file__).resolve().parent / "img" / "start.png"
jinja_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render_template_to_str(template_name: str, **context: Any) -> str:
    template = jinja_templates.env.get_template(template_name)
    return str(template.render(**context))


def _admin_request_meta(request: Request) -> tuple[int, str, str]:
    admin_id = int(require_admin_session(request) or 0)
    remote_addr = str(getattr(getattr(request, "client", None), "host", "") or "")
    path = ""
    if request:
        path = str(getattr(getattr(request, "url", None), "path", "") or "")
    return admin_id, path, remote_addr


def _audit_log(
    db: Session,
    request: Request,
    action: str,
    entity_type: str,
    entity_id: str | int = "",
    **details: Any,
) -> None:
    admin_id, path, remote_addr = _admin_request_meta(request)
    if admin_id <= 0:
        admin_id = int(settings.admin_telegram_id or 0)
    payload: str | None = None
    if details:
        try:
            payload = json.dumps(details, ensure_ascii=False, default=str)
        except Exception:
            payload = json.dumps({k: str(v) for k, v in details.items()}, ensure_ascii=False)
    db.add(
        AdminAuditLog(
            admin_telegram_id=admin_id,
            action=str(action or "")[:64],
            entity_type=str(entity_type or "")[:64],
            entity_id=str(entity_id or "")[:128],
            request_path=path[:255],
            remote_addr=remote_addr[:64],
            details_json=payload,
        )
    )


def _parse_page(value: Any, default: int = 1) -> int:
    try:
        page = int(str(value or "").strip())
    except Exception:
        page = default
    return max(1, page)


def _pagination_dict(page: int, page_size: int, total: int) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    total = max(0, int(total))
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    page = min(page, total_pages)
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "offset": (page - 1) * page_size,
    }


def _admin_pagination_bar(base_path: str, pagination: dict[str, Any], params: dict[str, Any], page_param: str = "page") -> str:
    if int(pagination.get("total_pages", 1)) <= 1:
        return ""
    page = int(pagination["page"])
    total_pages = int(pagination["total_pages"])

    def link_html(target_page: int, label: str, disabled: bool = False) -> str:
        if disabled:
            return f"<span class='btn ghost small' style='opacity:.55;pointer-events:none;'>{escape(label)}</span>"
        q = {k: v for k, v in params.items() if v not in (None, "", 0)}
        q[page_param] = target_page
        href = f"{base_path}?{urlencode({k: str(v) for k, v in q.items()})}"
        return f"<a class='btn ghost small' href='{escape(href)}' style='text-decoration:none;'>{escape(label)}</a>"

    window_start = max(1, page - 2)
    window_end = min(total_pages, page + 2)
    numbered = []
    for p in range(window_start, window_end + 1):
        if p == page:
            numbered.append(f"<span class='btn small' style='pointer-events:none;'>{p}</span>")
        else:
            numbered.append(link_html(p, str(p)))
    return (
        "<div class='section-actions' style='margin-top:10px;'>"
        f"{link_html(page - 1, 'Prev', disabled=page <= 1)}"
        + "".join(numbered)
        + f"{link_html(page + 1, 'Next', disabled=page >= total_pages)}"
        + f"<span class='muted' style='align-self:center;margin-left:6px;'>Page {page}/{total_pages} В· total {int(pagination['total'])}</span>"
        "</div>"
    )


def _safe_ratio(numerator: float | int, denominator: float | int) -> float:
    denom = float(denominator or 0)
    if denom <= 0:
        return 0.0
    return float(numerator) / denom


def _series_stats(points: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = []
    for p in points:
        try:
            values.append(float(p.get(key, 0) or 0))
        except Exception:
            continue
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0, "last": 0.0, "sum": 0.0}
    total = float(sum(values))
    return {
        "min": float(min(values)),
        "max": float(max(values)),
        "avg": float(total / max(1, len(values))),
        "last": float(values[-1]),
        "sum": float(total),
    }


def _day_key(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value)
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_daily_series_counts(
    db: Session,
    dt_col,
    days: int,
    filters: list[Any] | None = None,
    count_distinct_col=None,
) -> list[dict[str, Any]]:
    now = utc_now()
    start_day = (now - timedelta(days=max(1, days) - 1)).date()
    start_dt = datetime.combine(start_day, datetime.min.time())
    day_expr = func.date(dt_col).label("day")
    count_expr = func.count() if count_distinct_col is None else func.count(func.distinct(count_distinct_col))
    query = select(day_expr, count_expr).where(dt_col.is_not(None), dt_col >= start_dt)
    if filters:
        for cond in filters:
            query = query.where(cond)
    query = query.group_by(day_expr).order_by(day_expr)
    rows = db.execute(query).all()
    counts: dict[datetime.date, int] = {}
    for day_value, count_value in rows:
        day = _day_key(day_value)
        if day is None:
            continue
        counts[day] = int(count_value or 0)
    series: list[dict[str, Any]] = []
    for i in range(max(1, days)):
        day = start_day + timedelta(days=i)
        series.append(
            {
                "label": day.strftime("%m-%d"),
                "full": day.strftime("%Y-%m-%d"),
                "value": int(counts.get(day, 0)),
            }
        )
    return series


def _build_daily_series_sum(
    db: Session,
    dt_col,
    value_col,
    days: int,
    filters: list[Any] | None = None,
) -> list[dict[str, Any]]:
    now = utc_now()
    start_day = (now - timedelta(days=max(1, days) - 1)).date()
    start_dt = datetime.combine(start_day, datetime.min.time())
    day_expr = func.date(dt_col).label("day")
    sum_expr = func.coalesce(func.sum(value_col), 0)
    query = select(day_expr, sum_expr).where(dt_col.is_not(None), dt_col >= start_dt)
    if filters:
        for cond in filters:
            query = query.where(cond)
    query = query.group_by(day_expr).order_by(day_expr)
    rows = db.execute(query).all()
    totals: dict[datetime.date, int] = {}
    for day_value, total_value in rows:
        day = _day_key(day_value)
        if day is None:
            continue
        totals[day] = int(total_value or 0)
    series: list[dict[str, Any]] = []
    for i in range(max(1, days)):
        day = start_day + timedelta(days=i)
        series.append(
            {
                "label": day.strftime("%m-%d"),
                "full": day.strftime("%Y-%m-%d"),
                "value": int(totals.get(day, 0)),
            }
        )
    return series


def _probe_vpn_tcp_latency_ms(host: str, port: int, timeout_seconds: float = 0.8) -> float | None:
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.2, float(timeout_seconds))):
            pass
    except Exception:
        return None
    return max(0.0, (time.monotonic() - start) * 1000.0)


def _check_server_runtime(server: VpnServer) -> dict[str, Any]:
    try:
        protocol = server_protocol(server)
        service_name = "hysteria-server" if protocol == SERVER_PROTOCOL_HYSTERIA2 else "xray"
        version_cmd = "hysteria version 2>/dev/null | head -n 1 || true"
        if protocol != SERVER_PROTOCOL_HYSTERIA2:
            version_cmd = "xray version 2>/dev/null | head -n 1 || true"
        command = (
            f"XRAY_STATE=$(systemctl is-active {shlex.quote(service_name)} 2>/dev/null || true); "
            f"XRAY_VER=$({version_cmd}); "
            "UPTIME=$(uptime -p 2>/dev/null || true); "
            "LOADAVG=$(cat /proc/loadavg 2>/dev/null | awk '{print $1\" \"$2\" \"$3}' || true); "
            "MEM_USED_PCT=$(free -m 2>/dev/null | awk '/Mem:/ {if ($2>0) printf \"%.1f\", ($3/$2)*100; else printf \"0\"}' || true); "
            "NET_IFACE=$(ip route show default 2>/dev/null | awk '{print $5; exit}'); "
            "read_net(){ cat /proc/net/dev 2>/dev/null | awk -v iface=\"$NET_IFACE\" '$1 ~ iface\":\" {gsub(\":\", \"\", $1); print $2\" \"$10; exit}'; }; "
            "NET1=$(read_net); sleep 0.6; NET2=$(read_net); "
            "echo XRAY_STATE:$XRAY_STATE; "
            "echo XRAY_VER:$XRAY_VER; "
            "echo UPTIME:$UPTIME; "
            "echo LOADAVG:$LOADAVG; "
            "echo MEM_USED_PCT:$MEM_USED_PCT; "
            "echo NET_IFACE:$NET_IFACE; "
            "echo NET1:$NET1; "
            "echo NET2:$NET2; "
            "echo PORTS_START; "
            "ss -lnt 2>/dev/null || true; "
            "echo PORTS_END"
        )
        output = _run_ssh(server, command, timeout=8)
        lines = output.splitlines()
        xray_state = ""
        xray_ver = ""
        uptime = ""
        loadavg = "-"
        mem_used_pct = None
        net_iface = ""
        net_rx1 = None
        net_tx1 = None
        net_rx2 = None
        net_tx2 = None
        ports_lines: list[str] = []
        capture_ports = False
        for line in lines:
            if line.startswith("XRAY_STATE:"):
                xray_state = line.split(":", 1)[1].strip()
            elif line.startswith("XRAY_VER:"):
                xray_ver = line.split(":", 1)[1].strip()
            elif line.startswith("UPTIME:"):
                uptime = line.split(":", 1)[1].strip()
            elif line.startswith("LOADAVG:"):
                loadavg = line.split(":", 1)[1].strip() or "-"
            elif line.startswith("MEM_USED_PCT:"):
                mem_raw = line.split(":", 1)[1].strip()
                try:
                    mem_used_pct = float(mem_raw) if mem_raw else None
                except Exception:
                    mem_used_pct = None
            elif line.startswith("NET_IFACE:"):
                net_iface = line.split(":", 1)[1].strip()
            elif line.startswith("NET1:"):
                parts = line.split(":", 1)[1].split()
                if len(parts) >= 2:
                    net_rx1 = _parse_non_negative_int(parts[0])
                    net_tx1 = _parse_non_negative_int(parts[1])
            elif line.startswith("NET2:"):
                parts = line.split(":", 1)[1].split()
                if len(parts) >= 2:
                    net_rx2 = _parse_non_negative_int(parts[0])
                    net_tx2 = _parse_non_negative_int(parts[1])
            elif line.strip() == "PORTS_START":
                capture_ports = True
            elif line.strip() == "PORTS_END":
                capture_ports = False
            elif capture_ports:
                ports_lines.append(line)

        expected_port = f":{server.port}"
        port_open = any(expected_port in line for line in ports_lines)
        established_connections = 0
        try:
            estab_out = _run_ssh(
                server,
                f"ss -Hnt state established '( sport = :{int(server.port)} )' 2>/dev/null | wc -l",
                timeout=2.0,
            )
            established_connections = _parse_non_negative_int(estab_out)
        except Exception:
            established_connections = 0
        latency_ms = None
        if xray_state == "active" and port_open:
            latency_ms = _probe_vpn_tcp_latency_ms(server.host, server.port, timeout_seconds=0.8)
        vpn_reachable = bool(latency_ms is not None and xray_state == "active" and port_open)
        health = "ok" if xray_state == "active" and port_open and vpn_reachable else "degraded"
        latency_text = f"{latency_ms:.0f} ms" if latency_ms is not None else "-"
        net_rx_bps = None
        net_tx_bps = None
        if net_rx1 is not None and net_rx2 is not None and net_tx1 is not None and net_tx2 is not None:
            sample_seconds = 0.6
            net_rx_bps = max(0.0, (net_rx2 - net_rx1) / sample_seconds)
            net_tx_bps = max(0.0, (net_tx2 - net_tx1) / sample_seconds)
        load_parts = str(loadavg).split()
        load1 = float(load_parts[0]) if len(load_parts) > 0 and load_parts[0].replace(".", "", 1).isdigit() else 0.0
        load5 = float(load_parts[1]) if len(load_parts) > 1 and load_parts[1].replace(".", "", 1).isdigit() else 0.0
        load15 = float(load_parts[2]) if len(load_parts) > 2 and load_parts[2].replace(".", "", 1).isdigit() else 0.0
        return {
            "health": health,
            "xray_state": xray_state or "unknown",
            "service_name": service_name,
            "protocol": protocol,
            "port_open": port_open,
            "vpn_reachable": vpn_reachable,
            "vpn_latency_ms": latency_ms,
            "vpn_latency_text": latency_text,
            "established_connections": established_connections,
            "active_devices_estimate": established_connections,
            "load1": load1,
            "load5": load5,
            "load15": load15,
            "mem_used_pct": mem_used_pct,
            "net_iface": net_iface or "-",
            "net_rx_bps": net_rx_bps,
            "net_tx_bps": net_tx_bps,
            "net_rx_text": _format_rate_short(net_rx_bps),
            "net_tx_text": _format_rate_short(net_tx_bps),
            "version": xray_ver or "-",
            "uptime": uptime or "-",
            "loadavg": loadavg,
            "error": "",
        }
    except Exception as exc:
        return {
            "health": "error",
            "xray_state": "unknown",
            "service_name": server_service_name(server),
            "protocol": server_protocol(server),
            "port_open": False,
            "vpn_reachable": False,
            "vpn_latency_ms": None,
            "vpn_latency_text": "-",
            "established_connections": 0,
            "active_devices_estimate": 0,
            "load1": 0.0,
            "load5": 0.0,
            "load15": 0.0,
            "mem_used_pct": None,
            "net_iface": "-",
            "net_rx_bps": None,
            "net_tx_bps": None,
            "net_rx_text": "-",
            "net_tx_text": "-",
            "version": "-",
            "uptime": "-",
            "loadavg": "-",
            "error": str(exc),
        }


def _runtime_checks_budget_seconds(server_count: int, base_seconds: float = 8.0) -> float:
    # Avoid skipping all nodes when there are many servers or slow SSH checks.
    count = max(0, int(server_count))
    base = max(2.0, float(base_seconds))
    return min(45.0, base + max(0, count - 1) * 2.0)


def _build_admin_snapshot(db: Session, include_runtime_checks: bool) -> dict[str, Any]:
    now = utc_now()
    total_users = int(db.scalar(select(func.count(User.id))) or 0)
    active_subscriptions = int(
        db.scalar(select(func.count(User.id)).where(User.subscription_until.is_not(None), User.subscription_until > now)) or 0
    )
    total_servers = int(db.scalar(select(func.count(VpnServer.id))) or 0)
    enabled_servers = int(db.scalar(select(func.count(VpnServer.id)).where(VpnServer.enabled.is_(True))) or 0)
    total_configs = int(db.scalar(select(func.count(ClientConfig.id))) or 0)
    active_configs = int(db.scalar(select(func.count(ClientConfig.id)).where(ClientConfig.is_active.is_(True))) or 0)
    total_invoices = int(db.scalar(select(func.count(PaymentInvoice.id))) or 0)
    paid_invoices = int(
        db.scalar(select(func.count(PaymentInvoice.id)).where(PaymentInvoice.status == "paid")) or 0
    )
    revenue_rub = int(
        db.scalar(select(func.coalesce(func.sum(PaymentInvoice.amount_rub), 0)).where(PaymentInvoice.status == "paid")) or 0
    )
    total_balance_rub = int(db.scalar(select(func.coalesce(func.sum(User.balance_rub), 0))) or 0)
    total_ref_bonus_rub = int(
        db.scalar(select(func.coalesce(func.sum(ReferralReward.bonus_rub), 0))) or 0
    )
    users_new_24h = int(
        db.scalar(select(func.count(User.id)).where(User.created_at >= now - timedelta(hours=24))) or 0
    )
    users_new_7d = int(
        db.scalar(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7))) or 0
    )
    users_new_30d = int(
        db.scalar(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=30))) or 0
    )
    users_blocked = int(db.scalar(select(func.count(User.id)).where(User.is_blocked.is_(True))) or 0)
    users_trial_bonus = int(db.scalar(select(func.count(User.id)).where(User.trial_bonus_granted.is_(True))) or 0)
    users_referred = int(db.scalar(select(func.count(User.id)).where(User.referred_by_user_id.is_not(None))) or 0)
    users_with_subscription_any = int(
        db.scalar(select(func.count(User.id)).where(User.subscription_until.is_not(None))) or 0
    )
    expired_subscriptions = int(
        db.scalar(
            select(func.count(User.id)).where(
                User.subscription_until.is_not(None), User.subscription_until <= now
            )
        )
        or 0
    )
    expiring_3d = int(
        db.scalar(
            select(func.count(User.id)).where(
                User.subscription_until.is_not(None),
                User.subscription_until > now,
                User.subscription_until <= now + timedelta(days=3),
            )
        )
        or 0
    )
    expiring_7d = int(
        db.scalar(
            select(func.count(User.id)).where(
                User.subscription_until.is_not(None),
                User.subscription_until > now,
                User.subscription_until <= now + timedelta(days=7),
            )
        )
        or 0
    )
    users_with_configs = int(
        db.scalar(select(func.count(func.distinct(ClientConfig.user_id)))) or 0
    )
    users_with_active_configs = int(
        db.scalar(
            select(func.count(func.distinct(ClientConfig.user_id))).where(ClientConfig.is_active.is_(True))
        )
        or 0
    )
    active_users_30d = int(
        db.scalar(
            select(func.count(func.distinct(ClientConfig.user_id))).where(
                ClientConfig.created_at >= now - timedelta(days=30)
            )
        )
        or 0
    )
    paid_users_total = int(
        db.scalar(
            select(func.count(func.distinct(PaymentInvoice.user_id))).where(PaymentInvoice.status == "paid")
        )
        or 0
    )
    paid_users_30d = int(
        db.scalar(
            select(func.count(func.distinct(PaymentInvoice.user_id))).where(
                PaymentInvoice.status == "paid", PaymentInvoice.paid_at >= now - timedelta(days=30)
            )
        )
        or 0
    )
    revenue_7d = int(
        db.scalar(
            select(func.coalesce(func.sum(PaymentInvoice.amount_rub), 0)).where(
                PaymentInvoice.status == "paid", PaymentInvoice.paid_at >= now - timedelta(days=7)
            )
        )
        or 0
    )
    revenue_30d = int(
        db.scalar(
            select(func.coalesce(func.sum(PaymentInvoice.amount_rub), 0)).where(
                PaymentInvoice.status == "paid", PaymentInvoice.paid_at >= now - timedelta(days=30)
            )
        )
        or 0
    )

    active_cfg_rows = db.execute(
        select(ClientConfig.server_id, func.count(ClientConfig.id))
        .where(ClientConfig.is_active.is_(True))
        .group_by(ClientConfig.server_id)
    ).all()
    active_by_server = {int(server_id): int(count) for server_id, count in active_cfg_rows}

    servers = db.scalars(select(VpnServer).order_by(VpnServer.id)).all()
    server_rows: list[dict[str, Any]] = []
    touched = False
    runtime_deadline = time.monotonic() + _runtime_checks_budget_seconds(len(servers), base_seconds=10.0)
    for server in servers:
        runtime = {
            "health": "skipped",
            "xray_state": "-",
            "port_open": False,
            "vpn_reachable": False,
            "vpn_latency_ms": None,
            "vpn_latency_text": "-",
            "loadavg": "-",
            "version": "-",
            "uptime": "-",
            "error": "",
        }
        if include_runtime_checks and time.monotonic() <= runtime_deadline:
            runtime = _check_server_runtime(server)
            _record_load_sample(db, server.id, runtime)
            touched = True
        elif include_runtime_checks:
            runtime["error"] = "runtime check skipped by deadline"
        server_rows.append(
            {
                "id": server.id,
                "name": server.name,
                "enabled": server.enabled,
                "protocol": server_protocol(server),
                "host": server.host,
                "port": server.port,
                "sni": server.sni,
                "ssh_host": server.ssh_host,
                "active_clients": active_by_server.get(server.id, 0),
                "runtime": runtime,
            }
        )
    if touched:
        db.commit()
    live_users_now = 0
    live_users_partial = False
    if include_runtime_checks and servers:
        try:
            live_result = _sample_live_users_now(db, servers, max_seconds=8.0, sample_interval_seconds=0.8)
            live_users_now = int(live_result.get("count", 0))
            live_users_partial = bool(live_result.get("partial"))
        except Exception:
            live_users_now = 0
            live_users_partial = False

    recent_configs = db.scalars(
        select(ClientConfig)
        .options(selectinload(ClientConfig.user), selectinload(ClientConfig.server))
        .order_by(ClientConfig.created_at.desc())
        .limit(50)
    ).all()

    users_with_sub = db.scalars(
        select(User)
        .where(User.subscription_until.is_not(None))
        .order_by(User.subscription_until.asc())
        .limit(50)
    ).all()
    recent_payments = db.scalars(
        select(PaymentInvoice)
        .options(selectinload(PaymentInvoice.user))
        .order_by(PaymentInvoice.created_at.desc())
        .limit(50)
    ).all()

    history_since = now - timedelta(hours=24)
    history_rows = db.scalars(
        select(ServerLoadSample)
        .where(ServerLoadSample.created_at >= history_since)
        .order_by(ServerLoadSample.server_id, ServerLoadSample.created_at)
    ).all()
    history_map: dict[int, list[dict[str, Any]]] = {}
    connection_bucket_map: dict[datetime, dict[int, tuple[datetime, int]]] = {}
    for item in history_rows:
        latency_value = float(item.latency_ms or 0.0)
        if latency_value <= 0:
            # Backward compatibility with old samples where load1 stored latency.
            latency_value = float(item.load1 or 0.0)
        history_map.setdefault(item.server_id, []).append(
            {
                "ts": item.created_at.strftime("%H:%M"),
                "latency_ms": latency_value,
            }
        )
        bucket_ts = item.created_at.replace(minute=(item.created_at.minute // 30) * 30, second=0, microsecond=0)
        bucket_servers = connection_bucket_map.setdefault(bucket_ts, {})
        prev = bucket_servers.get(int(item.server_id))
        current_value = int(item.established_connections or 0)
        if not prev or item.created_at > prev[0]:
            bucket_servers[int(item.server_id)] = (item.created_at, current_value)
    for sid in list(history_map.keys()):
        history_map[sid] = history_map[sid][-120:]
    connections_series_24h: list[dict[str, Any]] = []
    if connection_bucket_map:
        bucket_start = (now - timedelta(hours=24)).replace(second=0, microsecond=0)
        bucket_start = bucket_start.replace(minute=(bucket_start.minute // 30) * 30)
        bucket_end = now.replace(second=0, microsecond=0)
        cursor = bucket_start
        while cursor <= bucket_end:
            servers = connection_bucket_map.get(cursor, {})
            total_value = sum(int(value) for _, value in servers.values()) if servers else 0
            connections_series_24h.append(
                {
                    "label": cursor.strftime("%H:%M"),
                    "full": cursor.strftime("%Y-%m-%d %H:%M"),
                    "value": int(total_value),
                }
            )
            cursor += timedelta(minutes=30)

    users_series_14d = _build_daily_series_counts(db, User.created_at, 14)
    configs_series_14d = _build_daily_series_counts(db, ClientConfig.created_at, 14)
    paid_series_14d = _build_daily_series_counts(
        db,
        PaymentInvoice.paid_at,
        14,
        filters=[PaymentInvoice.status == "paid"],
    )
    revenue_series_14d = _build_daily_series_sum(
        db,
        PaymentInvoice.paid_at,
        PaymentInvoice.amount_rub,
        14,
        filters=[PaymentInvoice.status == "paid"],
    )

    top_spenders_rows = db.execute(
        select(
            User.telegram_id,
            User.username,
            func.coalesce(func.sum(PaymentInvoice.amount_rub), 0).label("total_rub"),
        )
        .join(PaymentInvoice, PaymentInvoice.user_id == User.id)
        .where(PaymentInvoice.status == "paid")
        .group_by(User.id)
        .order_by(func.coalesce(func.sum(PaymentInvoice.amount_rub), 0).desc())
        .limit(5)
    ).all()
    top_spenders = [
        {
            "telegram_id": int(row.telegram_id),
            "username": row.username or "-",
            "total_rub": int(row.total_rub or 0),
        }
        for row in top_spenders_rows
    ]

    ref_counts = db.execute(
        select(User.referred_by_user_id, func.count(User.id).label("ref_count"))
        .where(User.referred_by_user_id.is_not(None))
        .group_by(User.referred_by_user_id)
        .order_by(func.count(User.id).desc())
        .limit(5)
    ).all()
    inviter_ids = [int(row.referred_by_user_id) for row in ref_counts if row.referred_by_user_id is not None]
    inviter_map: dict[int, dict[str, Any]] = {}
    bonus_map: dict[int, int] = {}
    if inviter_ids:
        inviter_rows = db.execute(
            select(User.id, User.telegram_id, User.username).where(User.id.in_(inviter_ids))
        ).all()
        inviter_map = {
            int(row.id): {"telegram_id": int(row.telegram_id), "username": row.username or "-"}
            for row in inviter_rows
        }
        bonus_rows = db.execute(
            select(ReferralReward.inviter_user_id, func.coalesce(func.sum(ReferralReward.bonus_rub), 0))
            .where(ReferralReward.inviter_user_id.in_(inviter_ids))
            .group_by(ReferralReward.inviter_user_id)
        ).all()
        bonus_map = {int(row[0]): int(row[1] or 0) for row in bonus_rows}
    top_referrers = []
    for row in ref_counts:
        inviter_id = int(row.referred_by_user_id or 0)
        meta = inviter_map.get(inviter_id, {"telegram_id": 0, "username": "-"})
        top_referrers.append(
            {
                "telegram_id": int(meta.get("telegram_id") or 0),
                "username": meta.get("username") or "-",
                "referrals": int(row.ref_count or 0),
                "bonus_rub": int(bonus_map.get(inviter_id, 0)),
            }
        )

    return {
        "generated_at": _fmt_dt(now),
        "summary": {
            "total_users": total_users,
            "active_subscriptions": active_subscriptions,
            "total_servers": total_servers,
            "enabled_servers": enabled_servers,
            "total_configs": total_configs,
            "active_configs": active_configs,
            "total_invoices": total_invoices,
            "paid_invoices": paid_invoices,
            "revenue_rub": revenue_rub,
            "total_balance_rub": total_balance_rub,
            "total_ref_bonus_rub": total_ref_bonus_rub,
            "connected_now": sum(
                int(s.get("runtime", {}).get("established_connections") or 0) for s in server_rows
            ),
            "live_users_now": live_users_now,
            "live_users_partial": live_users_partial,
        },
        "analytics": {
            "users": {
                "new_24h": users_new_24h,
                "new_7d": users_new_7d,
                "new_30d": users_new_30d,
                "blocked": users_blocked,
                "trial_bonus": users_trial_bonus,
                "referred": users_referred,
                "with_subscription_any": users_with_subscription_any,
                "expired_subscriptions": expired_subscriptions,
                "expiring_3d": expiring_3d,
                "expiring_7d": expiring_7d,
                "with_configs": users_with_configs,
                "with_active_configs": users_with_active_configs,
                "active_users_30d": active_users_30d,
            },
            "monetization": {
                "paid_users_total": paid_users_total,
                "paid_users_30d": paid_users_30d,
                "revenue_7d": revenue_7d,
                "revenue_30d": revenue_30d,
            },
            "series": {
                "users_new_14d": users_series_14d,
                "configs_new_14d": configs_series_14d,
                "paid_invoices_14d": paid_series_14d,
                "revenue_14d": revenue_series_14d,
                "connections_24h": connections_series_24h,
            },
            "top": {
                "spenders": top_spenders,
                "referrers": top_referrers,
            },
        },
        "servers": server_rows,
        "recent_configs": [
            {
                "id": cfg.id,
                "server": cfg.server.name if cfg.server else "-",
                "telegram_id": cfg.user.telegram_id if cfg.user else 0,
                "device_name": cfg.device_name,
                "is_active": cfg.is_active,
                "created_at": _fmt_dt(cfg.created_at),
            }
            for cfg in recent_configs
        ],
        "subscriptions": [
            {
                "telegram_id": user.telegram_id,
                "username": user.username or "-",
                "balance_rub": int(user.balance_rub or 0),
                "subscription_until": _fmt_dt(user.subscription_until),
                "is_active": is_subscription_active(user),
            }
            for user in users_with_sub
        ],
        "recent_payments": [
            {
                "invoice_id": p.invoice_id,
                "telegram_id": p.user.telegram_id if p.user else 0,
                "amount_rub": p.amount_rub,
                "payable_rub": p.payable_rub,
                "kind": p.kind,
                "promo_code": p.promo_code_text,
                "promo_discount_percent": p.promo_discount_percent,
                "credited_rub": p.credited_rub,
                "referral_bonus_rub": p.referral_bonus_rub,
                "status": p.status,
                "created_at": _fmt_dt(p.created_at),
                "paid_at": _fmt_dt(p.paid_at),
            }
            for p in recent_payments
        ],
        "load_history": [
            {
                "server_id": s["id"],
                "server_name": s["name"],
                "points": history_map.get(s["id"], []),
            }
            for s in server_rows
        ],
    }


_ADMIN_SNAPSHOT_CACHE_LOCK = threading.Lock()
_ADMIN_SNAPSHOT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _build_admin_snapshot_cached(
    db: Session,
    include_runtime_checks: bool,
    force_refresh: bool = False,
) -> dict[str, Any]:
    key = "runtime" if include_runtime_checks else "static"
    ttl_seconds = 8.0 if include_runtime_checks else 20.0
    now_mono = time.monotonic()
    if not force_refresh:
        with _ADMIN_SNAPSHOT_CACHE_LOCK:
            cached = _ADMIN_SNAPSHOT_CACHE.get(key)
            if cached and (now_mono - float(cached[0])) <= ttl_seconds:
                return cached[1]

    snapshot = _build_admin_snapshot(db, include_runtime_checks=include_runtime_checks)
    with _ADMIN_SNAPSHOT_CACHE_LOCK:
        _ADMIN_SNAPSHOT_CACHE[key] = (time.monotonic(), snapshot)
    return snapshot


def _admin_generated_snapshot() -> dict[str, Any]:
    return {"generated_at": _fmt_dt(utc_now())}


def _build_admin_users_summary_snapshot(db: Session) -> dict[str, Any]:
    now = utc_now()
    total_users = int(db.scalar(select(func.count(User.id))) or 0)
    active_subscriptions = int(
        db.scalar(select(func.count(User.id)).where(User.subscription_until.is_not(None), User.subscription_until > now)) or 0
    )
    active_configs = int(db.scalar(select(func.count(ClientConfig.id)).where(ClientConfig.is_active.is_(True))) or 0)
    blocked_users = int(db.scalar(select(func.count(User.id)).where(User.is_blocked.is_(True))) or 0)
    users_with_configs = int(db.scalar(select(func.count(func.distinct(ClientConfig.user_id)))) or 0)
    return {
        "generated_at": _fmt_dt(now),
        "summary": {
            "total_users": total_users,
            "active_subscriptions": active_subscriptions,
            "active_configs": active_configs,
        },
        "analytics": {
            "users": {
                "blocked": blocked_users,
                "with_configs": users_with_configs,
            }
        },
    }


def _build_admin_servers_snapshot(db: Session, include_runtime_checks: bool) -> dict[str, Any]:
    now = utc_now()
    active_cfg_rows = db.execute(
        select(ClientConfig.server_id, func.count(ClientConfig.id))
        .where(ClientConfig.is_active.is_(True))
        .group_by(ClientConfig.server_id)
    ).all()
    active_by_server = {int(server_id): int(count) for server_id, count in active_cfg_rows}

    servers = db.scalars(select(VpnServer).order_by(VpnServer.id)).all()
    server_rows: list[dict[str, Any]] = []
    touched = False
    runtime_deadline = time.monotonic() + _runtime_checks_budget_seconds(len(servers), base_seconds=10.0)
    for server in servers:
        runtime = {
            "health": "skipped",
            "xray_state": "-",
            "port_open": False,
            "vpn_reachable": False,
            "vpn_latency_ms": None,
            "vpn_latency_text": "-",
            "loadavg": "-",
            "version": "-",
            "uptime": "-",
            "error": "",
        }
        if include_runtime_checks and time.monotonic() <= runtime_deadline:
            runtime = _check_server_runtime(server)
            _record_load_sample(db, server.id, runtime)
            touched = True
        elif include_runtime_checks:
            runtime["error"] = "runtime check skipped by deadline"
        server_rows.append(
            {
                "id": int(server.id),
                "name": str(server.name),
                "enabled": bool(server.enabled),
                "protocol": server_protocol(server),
                "host": str(server.host),
                "port": int(server.port),
                "sni": str(server.sni),
                "ssh_host": str(server.ssh_host),
                "active_clients": int(active_by_server.get(int(server.id), 0)),
                "runtime": runtime,
            }
        )
    if touched:
        db.commit()

    history_since = now - timedelta(hours=24)
    history_rows = db.scalars(
        select(ServerLoadSample)
        .where(ServerLoadSample.created_at >= history_since)
        .order_by(ServerLoadSample.server_id, ServerLoadSample.created_at)
    ).all()
    history_map: dict[int, list[dict[str, Any]]] = {}
    for item in history_rows:
        latency_value = float(item.latency_ms or 0.0)
        if latency_value <= 0:
            latency_value = float(item.load1 or 0.0)
        history_map.setdefault(int(item.server_id), []).append(
            {
                "ts": item.created_at.strftime("%H:%M"),
                "latency_ms": latency_value,
            }
        )
    for sid in list(history_map.keys()):
        history_map[sid] = history_map[sid][-120:]
    return {
        "generated_at": _fmt_dt(now),
        "servers": server_rows,
        "load_history": [
            {
                "server_id": int(s["id"]),
                "server_name": str(s["name"]),
                "points": history_map.get(int(s["id"]), []),
            }
            for s in server_rows
        ],
    }


_ADMIN_SERVERS_SNAPSHOT_CACHE_LOCK = threading.Lock()
_ADMIN_SERVERS_SNAPSHOT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _build_admin_servers_snapshot_cached(
    db: Session,
    include_runtime_checks: bool,
    force_refresh: bool = False,
) -> dict[str, Any]:
    key = "runtime" if include_runtime_checks else "static"
    ttl_seconds = 8.0 if include_runtime_checks else 20.0
    now_mono = time.monotonic()
    if not force_refresh:
        with _ADMIN_SERVERS_SNAPSHOT_CACHE_LOCK:
            cached = _ADMIN_SERVERS_SNAPSHOT_CACHE.get(key)
            if cached and (now_mono - float(cached[0])) <= ttl_seconds:
                return cached[1]
    snapshot = _build_admin_servers_snapshot(db, include_runtime_checks=include_runtime_checks)
    with _ADMIN_SERVERS_SNAPSHOT_CACHE_LOCK:
        _ADMIN_SERVERS_SNAPSHOT_CACHE[key] = (time.monotonic(), snapshot)
    return snapshot


def _query_admin_configs_page(
    db: Session,
    q: str = "",
    status_filter: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q_norm = str(q or "").strip()
    status_norm = str(status_filter or "all").strip().lower()
    base = (
        select(ClientConfig)
        .join(User, User.id == ClientConfig.user_id)
        .join(VpnServer, VpnServer.id == ClientConfig.server_id, isouter=True)
    )
    count_q = (
        select(func.count(ClientConfig.id))
        .select_from(ClientConfig)
        .join(User, User.id == ClientConfig.user_id)
        .join(VpnServer, VpnServer.id == ClientConfig.server_id, isouter=True)
    )
    conditions = []
    if status_norm == "active":
        conditions.append(ClientConfig.is_active.is_(True))
    elif status_norm == "revoked":
        conditions.append(ClientConfig.is_active.is_(False))
    if q_norm:
        like = f"%{q_norm}%"
        q_tg = int(q_norm) if q_norm.isdigit() else None
        cond = or_(
            ClientConfig.device_name.ilike(like),
            VpnServer.name.ilike(like),
            User.username.ilike(like),
        )
        if q_tg is not None:
            cond = or_(cond, User.telegram_id == q_tg)
        conditions.append(cond)
    for cond in conditions:
        base = base.where(cond)
        count_q = count_q.where(cond)
    total = int(db.scalar(count_q) or 0)
    pagination = _pagination_dict(page, page_size, total)
    rows = db.scalars(
        base.options(selectinload(ClientConfig.user), selectinload(ClientConfig.server))
        .order_by(ClientConfig.created_at.desc())
        .offset(int(pagination["offset"]))
        .limit(int(pagination["page_size"]))
    ).all()
    result = [
        {
            "id": cfg.id,
            "telegram_id": cfg.user.telegram_id if cfg.user else 0,
            "server": cfg.server.name if cfg.server else "-",
            "device_name": cfg.device_name,
            "is_active": bool(cfg.is_active),
            "created_at": _fmt_dt(cfg.created_at),
        }
        for cfg in rows
    ]
    return result, pagination


def _query_admin_subscriptions_page(
    db: Session,
    q: str = "",
    status_filter: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q_norm = str(q or "").strip()
    status_norm = str(status_filter or "all").strip().lower()
    now = utc_now()
    base = select(User).where(User.subscription_until.is_not(None))
    count_q = select(func.count(User.id)).where(User.subscription_until.is_not(None))
    if status_norm == "active":
        cond = User.subscription_until > now
        base = base.where(cond)
        count_q = count_q.where(cond)
    elif status_norm == "expired":
        cond = User.subscription_until <= now
        base = base.where(cond)
        count_q = count_q.where(cond)
    if q_norm:
        like = f"%{q_norm}%"
        if q_norm.isdigit():
            base = base.where(or_(User.telegram_id == int(q_norm), User.username.ilike(like)))
            count_q = count_q.where(or_(User.telegram_id == int(q_norm), User.username.ilike(like)))
        else:
            base = base.where(User.username.ilike(like))
            count_q = count_q.where(User.username.ilike(like))
    total = int(db.scalar(count_q) or 0)
    pagination = _pagination_dict(page, page_size, total)
    rows = db.scalars(
        base.order_by(User.subscription_until.asc(), User.id.asc())
        .offset(int(pagination["offset"]))
        .limit(int(pagination["page_size"]))
    ).all()
    result = [
        {
            "telegram_id": user.telegram_id,
            "username": user.username or "-",
            "balance_rub": int(user.balance_rub or 0),
            "subscription_until": _fmt_dt(user.subscription_until),
            "is_active": is_subscription_active(user),
        }
        for user in rows
    ]
    return result, pagination


def _query_admin_users_page(
    db: Session,
    q: str = "",
    status_filter: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q_norm = str(q or "").strip()
    status_norm = str(status_filter or "all").strip().lower()
    now = utc_now()
    configs_subq = (
        select(
            ClientConfig.user_id.label("user_id"),
            func.count(ClientConfig.id).label("configs_total"),
            func.coalesce(
                func.sum(case((ClientConfig.is_active.is_(True), 1), else_=0)),
                0,
            ).label("configs_active"),
            func.count(
                func.distinct(
                    case((ClientConfig.is_active.is_(True), ClientConfig.device_name), else_=None)
                )
            ).label("devices_active"),
            func.max(ClientConfig.created_at).label("last_config_at"),
        )
        .group_by(ClientConfig.user_id)
        .subquery()
    )
    payments_subq = (
        select(
            PaymentInvoice.user_id.label("user_id"),
            func.count(PaymentInvoice.id).label("paid_count"),
            func.coalesce(func.sum(PaymentInvoice.amount_rub), 0).label("paid_sum"),
            func.max(PaymentInvoice.paid_at).label("last_paid_at"),
        )
        .where(PaymentInvoice.status == "paid")
        .group_by(PaymentInvoice.user_id)
        .subquery()
    )
    base = (
        select(
            User,
            configs_subq.c.configs_total,
            configs_subq.c.configs_active,
            configs_subq.c.devices_active,
            configs_subq.c.last_config_at,
            payments_subq.c.paid_count,
            payments_subq.c.paid_sum,
            payments_subq.c.last_paid_at,
        )
        .outerjoin(configs_subq, configs_subq.c.user_id == User.id)
        .outerjoin(payments_subq, payments_subq.c.user_id == User.id)
    )
    count_q = select(func.count(User.id))
    conditions = []
    if status_norm == "active":
        conditions.append(User.subscription_until.is_not(None))
        conditions.append(User.subscription_until > now)
    elif status_norm == "expired":
        conditions.append(User.subscription_until.is_not(None))
        conditions.append(User.subscription_until <= now)
    elif status_norm == "no_sub":
        conditions.append(User.subscription_until.is_(None))
    elif status_norm == "blocked":
        conditions.append(User.is_blocked.is_(True))
    if q_norm:
        like = f"%{q_norm}%"
        if q_norm.isdigit():
            q_int = int(q_norm)
            conditions.append(or_(User.telegram_id == q_int, User.username.ilike(like)))
        else:
            conditions.append(User.username.ilike(like))
    for cond in conditions:
        base = base.where(cond)
        count_q = count_q.where(cond)
    total = int(db.scalar(count_q) or 0)
    pagination = _pagination_dict(page, page_size, total)
    rows = db.execute(
        base.order_by(User.created_at.desc(), User.id.desc())
        .offset(int(pagination["offset"]))
        .limit(int(pagination["page_size"]))
    ).all()
    result = []
    for row in rows:
        user = row[0]
        mapping = row._mapping
        result.append(
            {
                "telegram_id": int(user.telegram_id),
                "username": user.username or "-",
                "balance_rub": int(user.balance_rub or 0),
                "subscription_until": _fmt_dt(user.subscription_until),
                "subscription_active": is_subscription_active(user),
                "is_blocked": bool(user.is_blocked),
                "created_at": _fmt_dt(user.created_at),
                "configs_total": int(mapping.get("configs_total") or 0),
                "configs_active": int(mapping.get("configs_active") or 0),
                "devices_active": int(mapping.get("devices_active") or 0),
                "last_config_at": _fmt_dt(mapping.get("last_config_at")),
                "paid_count": int(mapping.get("paid_count") or 0),
                "paid_sum": int(mapping.get("paid_sum") or 0),
                "last_paid_at": _fmt_dt(mapping.get("last_paid_at")),
            }
        )
    return result, pagination


def _query_admin_user_devices(
    db: Session,
    telegram_id: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    user = db.scalar(select(User).where(User.telegram_id == int(telegram_id)))
    if not user:
        return None, []

    rows = db.execute(
        select(ClientConfig, VpnServer)
        .join(VpnServer, VpnServer.id == ClientConfig.server_id, isouter=True)
        .where(ClientConfig.user_id == user.id)
        .order_by(ClientConfig.created_at.desc(), ClientConfig.id.desc())
    ).all()
    devices_map: dict[str, dict[str, Any]] = {}
    for cfg, server in rows:
        device_name = str(cfg.device_name or "").strip() or "-"
        entry = devices_map.get(device_name)
        if not entry:
            entry = {
                "device_name": device_name,
                "configs_total": 0,
                "configs_active": 0,
                "servers": set(),
                "last_config_at": cfg.created_at,
            }
            devices_map[device_name] = entry
        entry["configs_total"] = int(entry["configs_total"]) + 1
        if bool(cfg.is_active):
            entry["configs_active"] = int(entry["configs_active"]) + 1
        if server and str(server.name or "").strip():
            entry["servers"].add(str(server.name).strip())
        last_dt = entry.get("last_config_at")
        if cfg.created_at and (not last_dt or cfg.created_at > last_dt):
            entry["last_config_at"] = cfg.created_at

    device_rows: list[dict[str, Any]] = []
    for item in devices_map.values():
        servers = sorted(list(item.get("servers") or []))
        device_rows.append(
            {
                "device_name": str(item.get("device_name") or "-"),
                "configs_total": int(item.get("configs_total") or 0),
                "configs_active": int(item.get("configs_active") or 0),
                "servers": servers,
                "servers_text": ", ".join(servers) if servers else "-",
                "last_config_at": _fmt_dt(item.get("last_config_at")),
            }
        )
    device_rows.sort(key=lambda row: str(row.get("last_config_at") or ""), reverse=True)

    user_row = {
        "telegram_id": int(user.telegram_id),
        "username": user.username or "-",
        "balance_rub": int(user.balance_rub or 0),
        "subscription_until": _fmt_dt(user.subscription_until),
        "subscription_active": is_subscription_active(user),
        "is_blocked": bool(user.is_blocked),
    }
    return user_row, device_rows


def _query_admin_payments_page(
    db: Session,
    q: str = "",
    status_filter: str = "all",
    kind_filter: str = "all",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q_norm = str(q or "").strip()
    status_norm = str(status_filter or "all").strip().lower()
    kind_norm = str(kind_filter or "all").strip().lower()
    base = select(PaymentInvoice).join(User, User.id == PaymentInvoice.user_id, isouter=True)
    count_q = select(func.count(PaymentInvoice.id)).select_from(PaymentInvoice).join(User, User.id == PaymentInvoice.user_id, isouter=True)
    if status_norm != "all":
        base = base.where(PaymentInvoice.status == status_norm)
        count_q = count_q.where(PaymentInvoice.status == status_norm)
    if kind_norm != "all":
        base = base.where(PaymentInvoice.kind == kind_norm)
        count_q = count_q.where(PaymentInvoice.kind == kind_norm)
    if q_norm:
        like = f"%{q_norm}%"
        cond = or_(
            PaymentInvoice.kind.ilike(like),
            PaymentInvoice.invoice_hash.ilike(like),
            PaymentInvoice.promo_code_text.ilike(like),
            User.username.ilike(like),
        )
        if q_norm.isdigit():
            q_int = int(q_norm)
            cond = or_(cond, PaymentInvoice.invoice_id == q_int, User.telegram_id == q_int)
        base = base.where(cond)
        count_q = count_q.where(cond)
    total = int(db.scalar(count_q) or 0)
    pagination = _pagination_dict(page, page_size, total)
    rows = db.scalars(
        base.options(selectinload(PaymentInvoice.user))
        .order_by(PaymentInvoice.created_at.desc())
        .offset(int(pagination["offset"]))
        .limit(int(pagination["page_size"]))
    ).all()
    result = [
        {
            "invoice_id": p.invoice_id,
            "telegram_id": p.user.telegram_id if p.user else 0,
            "amount_rub": p.amount_rub,
            "payable_rub": p.payable_rub,
            "kind": p.kind,
            "promo_code": p.promo_code_text,
            "promo_discount_percent": p.promo_discount_percent,
            "credited_rub": p.credited_rub,
            "referral_bonus_rub": p.referral_bonus_rub,
            "status": p.status,
            "created_at": _fmt_dt(p.created_at),
            "paid_at": _fmt_dt(p.paid_at),
        }
        for p in rows
    ]
    return result, pagination


def _query_admin_promo_uses_page(
    db: Session,
    q: str = "",
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q_norm = str(q or "").strip()
    base = (
        select(PromoRedemption, PromoCode.code, User.telegram_id)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_code_id)
        .join(User, User.id == PromoRedemption.user_id)
    )
    count_q = (
        select(func.count(PromoRedemption.id))
        .select_from(PromoRedemption)
        .join(PromoCode, PromoCode.id == PromoRedemption.promo_code_id)
        .join(User, User.id == PromoRedemption.user_id)
    )
    if q_norm:
        like = f"%{q_norm}%"
        cond = or_(PromoCode.code.ilike(like), PromoRedemption.kind.ilike(like))
        if q_norm.isdigit():
            cond = or_(cond, User.telegram_id == int(q_norm))
        base = base.where(cond)
        count_q = count_q.where(cond)
    total = int(db.scalar(count_q) or 0)
    pagination = _pagination_dict(page, page_size, total)
    rows = db.execute(
        base.order_by(PromoRedemption.created_at.desc())
        .offset(int(pagination["offset"]))
        .limit(int(pagination["page_size"]))
    ).all()
    result = [
        {
            "id": int(red.id),
            "code": str(code),
            "telegram_id": int(telegram_id),
            "kind": str(red.kind),
            "value_int": int(red.value_int or 0),
            "payment_invoice_id": int(red.payment_invoice_id) if red.payment_invoice_id else None,
            "created_at": _fmt_dt(red.created_at),
        }
        for red, code, telegram_id in rows
    ]
    return result, pagination


def _query_admin_giveaways(db: Session) -> list[dict[str, Any]]:
    now = utc_now()
    rows = db.scalars(select(Giveaway).order_by(Giveaway.created_at.desc())).all()
    return [
        {
            "id": int(g.id),
            "title": str(g.title or ""),
            "description": str(g.description or ""),
            "prize": str(g.prize or ""),
            "kind": str(g.kind or ""),
            "kind_title": _giveaway_kind_title(str(g.kind or "")),
            "condition_text": _giveaway_condition_text(str(g.kind or "")),
            "starts_at": _fmt_dt(g.starts_at),
            "ends_at": _fmt_dt(g.ends_at),
            "enabled": bool(g.enabled),
            "active": _is_giveaway_active(g, now),
            "participants": _giveaway_participant_count(db, g.id),
            "winners": _giveaway_winners_summary(db, g.id),
        }
        for g in rows
    ]


def _query_admin_audit_page(
    db: Session,
    q: str = "",
    action_filter: str = "all",
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    q_norm = str(q or "").strip()
    action_norm = str(action_filter or "all").strip().lower()
    base = select(AdminAuditLog)
    count_q = select(func.count(AdminAuditLog.id))
    if action_norm != "all":
        base = base.where(AdminAuditLog.action == action_norm)
        count_q = count_q.where(AdminAuditLog.action == action_norm)
    if q_norm:
        like = f"%{q_norm}%"
        cond = or_(
            AdminAuditLog.action.ilike(like),
            AdminAuditLog.entity_type.ilike(like),
            AdminAuditLog.entity_id.ilike(like),
            AdminAuditLog.request_path.ilike(like),
            AdminAuditLog.details_json.ilike(like),
        )
        if q_norm.isdigit():
            cond = or_(cond, AdminAuditLog.admin_telegram_id == int(q_norm))
        base = base.where(cond)
        count_q = count_q.where(cond)
    total = int(db.scalar(count_q) or 0)
    pagination = _pagination_dict(page, page_size, total)
    rows = db.scalars(
        base.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .offset(int(pagination["offset"]))
        .limit(int(pagination["page_size"]))
    ).all()
    result = [
        {
            "id": int(row.id),
            "admin_telegram_id": int(row.admin_telegram_id or 0),
            "action": str(row.action or ""),
            "entity_type": str(row.entity_type or ""),
            "entity_id": str(row.entity_id or ""),
            "request_path": str(row.request_path or ""),
            "remote_addr": str(row.remote_addr or ""),
            "details_json": str(row.details_json or ""),
            "created_at": _fmt_dt(row.created_at),
        }
        for row in rows
    ]
    return result, pagination


def _sample_health_severity(health: str, xray_state: str) -> str:
    health_value = str(health or "").strip().lower()
    xray_value = str(xray_state or "").strip().lower()
    if health_value == "ok" and xray_value == "active":
        return "green"
    if health_value == "degraded" or xray_value == "active":
        return "yellow"
    return "red"


def _build_server_detail_snapshot(
    db: Session,
    server_id: int,
    include_runtime_checks: bool = True,
) -> dict[str, Any]:
    now = utc_now()
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    runtime = {
        "health": "skipped",
        "xray_state": "-",
        "port_open": False,
        "vpn_reachable": False,
        "vpn_latency_ms": None,
        "vpn_latency_text": "-",
        "loadavg": "-",
        "version": "-",
        "uptime": "-",
        "error": "runtime check skipped",
    }
    if include_runtime_checks:
        runtime = _check_server_runtime(server)
        _record_load_sample(db, server.id, runtime)
        db.commit()

    total_configs = int(
        db.scalar(
            select(func.count(ClientConfig.id)).where(
                ClientConfig.server_id == server.id,
            )
        )
        or 0
    )
    active_configs_count = int(
        db.scalar(
            select(func.count(ClientConfig.id)).where(
                ClientConfig.server_id == server.id,
                ClientConfig.is_active.is_(True),
            )
        )
        or 0
    )
    active_users = int(
        db.scalar(
            select(func.count(func.distinct(ClientConfig.user_id))).where(
                ClientConfig.server_id == server.id,
                ClientConfig.is_active.is_(True),
            )
        )
        or 0
    )
    active_devices = int(
        db.scalar(
            select(func.count(func.distinct(ClientConfig.device_name))).where(
                ClientConfig.server_id == server.id,
                ClientConfig.is_active.is_(True),
            )
        )
        or 0
    )
    since_24h = now - timedelta(hours=24)
    created_24h = int(
        db.scalar(
            select(func.count(ClientConfig.id)).where(
                ClientConfig.server_id == server.id,
                ClientConfig.created_at >= since_24h,
            )
        )
        or 0
    )
    revoked_24h = int(
        db.scalar(
            select(func.count(ClientConfig.id)).where(
                ClientConfig.server_id == server.id,
                ClientConfig.revoked_at.is_not(None),
                ClientConfig.revoked_at >= since_24h,
            )
        )
        or 0
    )

    active_config_rows = db.scalars(
        select(ClientConfig)
        .where(
            ClientConfig.server_id == server.id,
            ClientConfig.is_active.is_(True),
        )
        .options(selectinload(ClientConfig.user))
        .order_by(ClientConfig.created_at.desc())
    ).all()

    history_rows = db.scalars(
        select(ServerLoadSample)
        .where(
            ServerLoadSample.server_id == server.id,
            ServerLoadSample.created_at >= since_24h,
        )
        .order_by(ServerLoadSample.created_at.asc())
    ).all()
    history_tail = list(history_rows)[-180:]
    latency_points: list[dict[str, Any]] = []
    load_points: list[dict[str, Any]] = []
    connection_points: list[dict[str, Any]] = []
    for sample in history_tail:
        latency_value = float(sample.latency_ms or 0.0)
        if latency_value <= 0:
            latency_value = float(sample.load1 or 0.0)
        ts = sample.created_at.strftime("%H:%M")
        severity = _sample_health_severity(sample.health, sample.xray_state)
        latency_points.append(
            {
                "ts": ts,
                "latency_ms": latency_value,
                "severity": severity,
            }
        )
        load_points.append(
            {
                "ts": ts,
                "load1": float(sample.load1 or 0.0),
                "load5": float(sample.load5 or 0.0),
                "load15": float(sample.load15 or 0.0),
                "severity": severity,
            }
        )
        connection_points.append(
            {
                "ts": ts,
                "established_connections": int(sample.established_connections or 0),
                "active_devices_estimate": int(sample.active_devices_estimate or 0),
                "severity": severity,
            }
        )

    live_active_devices: list[dict[str, Any]] = []
    live_error: str | None = None
    if include_runtime_checks:
        live_active_devices, live_error = _live_server_active_devices(
            server,
            active_config_rows,
            sample_interval_seconds=1.1,
            timeout_seconds=6.0,
            top_n=50,
        )
    else:
        live_error = None

    since_14d = now - timedelta(days=13)
    created_rows = db.scalars(
        select(ClientConfig.created_at).where(
            ClientConfig.server_id == server.id,
            ClientConfig.created_at >= since_14d,
        )
    ).all()
    per_day: dict[str, int] = {}
    for created_at in created_rows:
        if not created_at:
            continue
        key = created_at.strftime("%Y-%m-%d")
        per_day[key] = int(per_day.get(key, 0)) + 1
    daily_points: list[dict[str, Any]] = []
    for offset in range(13, -1, -1):
        day = (now - timedelta(days=offset)).date()
        key = day.isoformat()
        daily_points.append({"day": day.strftime("%m-%d"), "count": int(per_day.get(key, 0))})

    recent_configs = db.scalars(
        select(ClientConfig)
        .where(ClientConfig.server_id == server.id)
        .options(selectinload(ClientConfig.user))
        .order_by(ClientConfig.created_at.desc())
        .limit(80)
    ).all()

    return {
        "generated_at": _fmt_dt(now),
        "server": {
            "id": int(server.id),
            "name": str(server.name),
            "protocol": server_protocol(server),
            "host": str(server.host),
            "port": int(server.port),
            "sni": str(server.sni),
            "public_key": str(server.public_key),
            "short_id": str(server.short_id),
            "fingerprint": str(server.fingerprint),
            "hy2_obfs": str(server.hy2_obfs or ""),
            "hy2_obfs_password": str(server.hy2_obfs_password or ""),
            "hy2_alpn": str(server.hy2_alpn or "h3"),
            "hy2_insecure": bool(server.hy2_insecure),
            "enabled": bool(server.enabled),
            "ssh_host": str(server.ssh_host),
            "ssh_port": int(server.ssh_port),
            "ssh_user": str(server.ssh_user),
            "ssh_key_path": str(server.ssh_key_path),
            "remote_add_script": str(server.remote_add_script),
            "remote_remove_script": str(server.remote_remove_script),
        },
        "runtime": runtime,
        "metrics": {
            "total_configs": total_configs,
            "active_configs": active_configs_count,
            "active_users": active_users,
            "active_devices": active_devices,
            "created_24h": created_24h,
            "revoked_24h": revoked_24h,
            "established_connections": int(runtime.get("established_connections") or 0),
            "live_active_devices_count": len(live_active_devices),
        },
        "latency_points": latency_points,
        "load_points": load_points,
        "connection_points": connection_points,
        "daily_points": daily_points,
        "live_active_devices": live_active_devices,
        "live_active_devices_error": live_error,
        "recent_configs": [
            {
                "id": int(cfg.id),
                "telegram_id": int(cfg.user.telegram_id) if cfg.user else 0,
                "device_name": str(cfg.device_name or "-"),
                "is_active": bool(cfg.is_active),
                "created_at": _fmt_dt(cfg.created_at),
                "revoked_at": _fmt_dt(cfg.revoked_at),
            }
            for cfg in recent_configs
        ],
    }


_SERVER_DETAIL_SNAPSHOT_CACHE_LOCK = threading.Lock()
_SERVER_DETAIL_SNAPSHOT_CACHE: dict[tuple[int, bool], tuple[float, dict[str, Any]]] = {}


def _build_server_detail_snapshot_cached(
    db: Session,
    server_id: int,
    include_runtime_checks: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    key = (int(server_id), bool(include_runtime_checks))
    ttl_seconds = 6.0 if include_runtime_checks else 20.0
    now_mono = time.monotonic()
    if not force_refresh:
        with _SERVER_DETAIL_SNAPSHOT_CACHE_LOCK:
            cached = _SERVER_DETAIL_SNAPSHOT_CACHE.get(key)
            if cached and (now_mono - float(cached[0])) <= ttl_seconds:
                return cached[1]
    snapshot = _build_server_detail_snapshot(
        db,
        server_id=int(server_id),
        include_runtime_checks=bool(include_runtime_checks),
    )
    with _SERVER_DETAIL_SNAPSHOT_CACHE_LOCK:
        _SERVER_DETAIL_SNAPSHOT_CACHE[key] = (time.monotonic(), snapshot)
    return snapshot


def _sync_server_with_active_devices(
    db: Session,
    server_id: int,
    max_seconds: float = 30.0,
    per_add_timeout_seconds: float = 4.0,
) -> dict[str, Any]:
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if not server.enabled:
        return {
            "created": 0,
            "existing": 0,
            "skipped_inactive": 0,
            "errors": [],
            "timed_out": False,
        }

    now = utc_now()
    deadline = time.monotonic() + max(3.0, float(max_seconds))
    pairs = db.execute(
        select(
            ClientConfig.user_id,
            ClientConfig.device_name,
            func.max(ClientConfig.created_at).label("last_created"),
        )
        .join(User, User.id == ClientConfig.user_id)
        .where(
            ClientConfig.is_active.is_(True),
            ClientConfig.server_id != server.id,
            User.is_blocked.is_(False),
            User.subscription_until.is_not(None),
            User.subscription_until > now,
        )
        .group_by(ClientConfig.user_id, ClientConfig.device_name)
        .order_by(func.max(ClientConfig.created_at).desc())
    ).all()

    created = 0
    existing = 0
    skipped_inactive = 0
    timed_out = False
    errors: list[str] = []

    for user_id_raw, device_name_raw, _ in pairs:
        if time.monotonic() >= deadline:
            timed_out = True
            break
        user_id = int(user_id_raw or 0)
        device_name = str(device_name_raw or "").strip()
        if user_id <= 0 or not device_name:
            continue

        exists = db.scalar(
            select(ClientConfig.id).where(
                ClientConfig.user_id == user_id,
                ClientConfig.server_id == server.id,
                ClientConfig.device_name == device_name,
                ClientConfig.is_active.is_(True),
            )
        )
        if exists:
            existing += 1
            continue

        user = db.scalar(select(User).where(User.id == user_id))
        if not user or not is_subscription_active(user):
            skipped_inactive += 1
            continue

        client_uuid = str(uuid4())
        email_tag = generate_email_tag(user.telegram_id, device_name)
        vless_label = f"{server.name}-{device_name}"
        vless_url = build_client_url(server, client_uuid, vless_label)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            add_client_on_server(
                server,
                client_uuid,
                email_tag,
                user.subscription_until,
                timeout=max(1.0, min(float(per_add_timeout_seconds), float(remaining))),
            )
        except Exception as exc:
            errors.append(f"user_id={user_id} device={device_name}: {exc}")
            continue
        db.add(
            ClientConfig(
                user_id=user.id,
                server_id=server.id,
                device_name=device_name,
                client_uuid=client_uuid,
                email_tag=email_tag,
                vless_url=vless_url,
                is_active=True,
            )
        )
        created += 1

    db.commit()
    return {
        "created": created,
        "existing": existing,
        "skipped_inactive": skipped_inactive,
        "errors": errors,
        "timed_out": timed_out,
    }


def _render_admin_server_detail_page(snapshot: dict[str, Any], msg_text: str = "", error_text: str = "") -> str:
    server = snapshot["server"]
    runtime = snapshot["runtime"]
    metrics = snapshot["metrics"]
    server_id = int(server["id"])
    runtime_severity = _runtime_severity(runtime)
    health_color = _severity_color(runtime_severity)

    latency_points = list(snapshot.get("latency_points", []))[-120:]
    latency_stats = _series_stats(latency_points, "latency_ms")
    max_latency = max([300.0] + [float(p.get("latency_ms", 0.0)) for p in latency_points])
    latency_bars = ""
    for point in latency_points:
        latency_ms = float(point.get("latency_ms", 0.0))
        bar_height = max(2, int((latency_ms / max_latency) * 72))
        bar_cls = str(point.get("severity") or "yellow")
        latency_bars += (
            f"<div class='hist-bar sev-{escape(bar_cls)}' style='height:{bar_height}px' "
            f"title='{escape(str(point.get('ts', '-')))} | {latency_ms:.0f} ms'></div>"
        )
    if not latency_bars:
        latency_bars = "<div class='muted'>No latency samples yet</div>"
    latency_stats_html = (
        "<div class='meta-list' style='margin-top:8px;'>"
        f"<div class='meta-item'><div class='k'>Min ms</div><div class='v'>{latency_stats['min']:.0f}</div></div>"
        f"<div class='meta-item'><div class='k'>Avg ms</div><div class='v'>{latency_stats['avg']:.0f}</div></div>"
        f"<div class='meta-item'><div class='k'>Max ms</div><div class='v'>{latency_stats['max']:.0f}</div></div>"
        f"<div class='meta-item'><div class='k'>Last ms</div><div class='v'>{latency_stats['last']:.0f}</div></div>"
        "</div>"
    )

    daily_points = list(snapshot.get("daily_points", []))
    daily_stats = _series_stats(daily_points, "count")
    max_day = max([1] + [int(p.get("count", 0)) for p in daily_points])
    daily_bars = ""
    for point in daily_points:
        value = int(point.get("count", 0))
        bar_height = max(2, int((value / max_day) * 72))
        daily_bars += (
            f"<div class='hist-bar' style='height:{bar_height}px;background:#60a5fa;' "
            f"title='{escape(str(point.get('day', '-')))} | created: {value}'></div>"
        )
    if not daily_bars:
        daily_bars = "<div class='muted'>No data</div>"
    daily_stats_html = (
        "<div class='meta-list' style='margin-top:8px;'>"
        f"<div class='meta-item'><div class='k'>Sum</div><div class='v'>{int(daily_stats['sum'])}</div></div>"
        f"<div class='meta-item'><div class='k'>Avg/day</div><div class='v'>{daily_stats['avg']:.1f}</div></div>"
        f"<div class='meta-item'><div class='k'>Max/day</div><div class='v'>{int(daily_stats['max'])}</div></div>"
        f"<div class='meta-item'><div class='k'>Last</div><div class='v'>{int(daily_stats['last'])}</div></div>"
        "</div>"
    )

    load_points = list(snapshot.get("load_points", []))[-120:]
    load_stats = _series_stats(load_points, "load1")
    max_load1 = max([1.0] + [float(p.get("load1", 0.0)) for p in load_points])
    load_bars = ""
    for point in load_points:
        load1 = float(point.get("load1", 0.0))
        bar_height = max(2, int((load1 / max_load1) * 72))
        bar_cls = str(point.get("severity") or "yellow")
        load_bars += (
            f"<div class='hist-bar sev-{escape(bar_cls)}' style='height:{bar_height}px' "
            f"title='{escape(str(point.get('ts', '-')))} | load1: {load1:.2f}'></div>"
        )
    if not load_bars:
        load_bars = "<div class='muted'>No load samples yet</div>"
    load_stats_html = (
        "<div class='meta-list' style='margin-top:8px;'>"
        f"<div class='meta-item'><div class='k'>Min</div><div class='v'>{load_stats['min']:.2f}</div></div>"
        f"<div class='meta-item'><div class='k'>Avg</div><div class='v'>{load_stats['avg']:.2f}</div></div>"
        f"<div class='meta-item'><div class='k'>Max</div><div class='v'>{load_stats['max']:.2f}</div></div>"
        f"<div class='meta-item'><div class='k'>Last</div><div class='v'>{load_stats['last']:.2f}</div></div>"
        "</div>"
    )

    connection_points = list(snapshot.get("connection_points", []))[-120:]
    connection_stats = _series_stats(connection_points, "established_connections")
    max_connections = max([1] + [int(p.get("established_connections", 0)) for p in connection_points])
    conn_bars = ""
    for point in connection_points:
        current_connections = int(point.get("established_connections", 0))
        bar_height = max(2, int((current_connections / max_connections) * 72))
        bar_cls = str(point.get("severity") or "yellow")
        conn_bars += (
            f"<div class='hist-bar sev-{escape(bar_cls)}' style='height:{bar_height}px' "
            f"title='{escape(str(point.get('ts', '-')))} | established: {current_connections}'></div>"
        )
    if not conn_bars:
        conn_bars = "<div class='muted'>No connection samples yet</div>"
    conn_stats_html = (
        "<div class='meta-list' style='margin-top:8px;'>"
        f"<div class='meta-item'><div class='k'>Min</div><div class='v'>{int(connection_stats['min'])}</div></div>"
        f"<div class='meta-item'><div class='k'>Avg</div><div class='v'>{connection_stats['avg']:.1f}</div></div>"
        f"<div class='meta-item'><div class='k'>Max</div><div class='v'>{int(connection_stats['max'])}</div></div>"
        f"<div class='meta-item'><div class='k'>Last</div><div class='v'>{int(connection_stats['last'])}</div></div>"
        "</div>"
    )

    live_rows = ""
    for row in list(snapshot.get("live_active_devices", []))[:100]:
        live_rows += (
            "<tr>"
            f"<td data-label='Device'>{escape(str(row.get('device_name', '-')))}</td>"
            f"<td data-label='Telegram ID'>{escape(str(row.get('telegram_id', 0)))}</td>"
            f"<td data-label='Traffic delta'>{escape(str(row.get('traffic_delta_text', '0 B')))}</td>"
            f"<td data-label='Configs on server'>{int(row.get('server_config_count', 0))}</td>"
            "</tr>"
        )
    if not live_rows:
        live_rows = "<tr><td colspan='4' class='muted'>No active devices detected in last sample window</td></tr>"

    recent_rows = ""
    for cfg in snapshot.get("recent_configs", []):
        recent_rows += (
            "<tr>"
            f"<td data-label='ID'>{cfg['id']}</td>"
            f"<td data-label='Telegram ID'>{escape(str(cfg['telegram_id']))}</td>"
            f"<td data-label='Device'>{escape(cfg['device_name'])}</td>"
            f"<td data-label='Status'>{'active' if cfg['is_active'] else 'revoked'}</td>"
            f"<td data-label='Created'>{escape(cfg['created_at'])}</td>"
            f"<td data-label='Revoked'>{escape(cfg['revoked_at'])}</td>"
            "</tr>"
        )

    toggle_text = "РЎРєСЂС‹С‚СЊ РёР· РІС‹РґР°С‡Рё" if bool(server["enabled"]) else "Р’РµСЂРЅСѓС‚СЊ РІ РІС‹РґР°С‡Сѓ"
    live_error_html = ""
    if snapshot.get("live_active_devices_error"):
        live_error_html = f"<div class='notice err'>{escape(str(snapshot.get('live_active_devices_error')))}</div>"

    action_bar = (
        "<a class='btn ghost' href='/admin/servers' style='text-decoration:none;'>Back to servers</a>"
        f"<form method='post' action='/admin/action/server/{server_id}/sync-devices' class='inline-form'><button class='btn small' type='submit'>Sync devices</button></form>"
    )
    runtime_table = (
        "<div class='table-wrap'><table><tbody>"
        f"<tr><th>Host</th><td>{escape(server['host'])}:{server['port']}</td><th>Protocol</th><td>{escape(str(server.get('protocol') or SERVER_PROTOCOL_VLESS_REALITY))}</td></tr>"
        f"<tr><th>SNI</th><td>{escape(server['sni'])}</td><th>Service state</th><td id='sd-rt-xray'>{escape(str(runtime.get('xray_state', '-')))}</td></tr>"
        f"<tr><th>Reachable</th><td id='sd-rt-reach'>{'yes' if runtime.get('vpn_reachable') else 'no'}</td><th>Service</th><td>{escape(str(runtime.get('service_name') or 'xray'))}</td></tr>"
        f"<tr><th>Version</th><td id='sd-rt-version'>{escape(str(runtime.get('version', '-')))}</td><th>Uptime</th><td id='sd-rt-uptime'>{escape(str(runtime.get('uptime', '-')))}</td></tr>"
        f"<tr><th>Loadavg</th><td id='sd-rt-loadavg'>{escape(str(runtime.get('loadavg', '-')))}</td><th>RAM used</th><td id='sd-rt-mem'>{escape(str(runtime.get('mem_used_pct', '-')))}%</td></tr>"
        f"<tr><th>Net RX</th><td id='sd-rt-netrx'>{escape(str(runtime.get('net_rx_text', '-')))}</td><th>Net TX</th><td id='sd-rt-nettx'>{escape(str(runtime.get('net_tx_text', '-')))}</td></tr>"
        f"<tr><th>Established TCP</th><td id='sd-rt-established'>{int(runtime.get('established_connections') or 0)}</td><th>SSH</th><td>{escape(server['ssh_user'])}@{escape(server['ssh_host'])}:{server['ssh_port']}</td></tr>"
        f"<tr><th>Error</th><td id='sd-rt-error' colspan='3'>{escape(str(runtime.get('error') or '-'))}</td></tr>"
        "</tbody></table></div>"
    )
    edit_form = (
        f"<form method='post' action='/admin/action/server/{server_id}/update' class='server-form'>"
        f"<input type='text' name='name' value='{escape(server['name'])}' required />"
        "<select name='protocol'>"
        f"<option value='{SERVER_PROTOCOL_VLESS_REALITY}' {'selected' if str(server.get('protocol')) == SERVER_PROTOCOL_VLESS_REALITY else ''}>vless_reality</option>"
        f"<option value='{SERVER_PROTOCOL_HYSTERIA2}' {'selected' if str(server.get('protocol')) == SERVER_PROTOCOL_HYSTERIA2 else ''}>hysteria2</option>"
        "</select>"
        f"<input type='text' name='host' value='{escape(server['host'])}' required />"
        f"<input type='text' name='port' value='{server['port']}' required />"
        f"<input type='text' name='sni' value='{escape(server['sni'])}' required />"
        f"<input type='text' name='public_key' value='{escape(server['public_key'])}' placeholder='VLESS REALITY public key' />"
        f"<input type='text' name='short_id' value='{escape(server['short_id'])}' placeholder='VLESS REALITY short id' />"
        f"<input type='text' name='fingerprint' value='{escape(server['fingerprint'])}' placeholder='VLESS fingerprint (chrome)' />"
        f"<input type='text' name='hy2_alpn' value='{escape(str(server.get('hy2_alpn') or 'h3'))}' placeholder='HY2 ALPN (h3)' />"
        f"<input type='text' name='hy2_obfs' value='{escape(str(server.get('hy2_obfs') or ''))}' placeholder='HY2 obfs (optional)' />"
        f"<input type='text' name='hy2_obfs_password' value='{escape(str(server.get('hy2_obfs_password') or ''))}' placeholder='HY2 obfs password (optional)' />"
        f"<label><input type='checkbox' name='hy2_insecure' value='1' {'checked' if bool(server.get('hy2_insecure')) else ''}/> HY2 insecure=1</label>"
        "<div class='sub-form'>"
        f"<input type='text' name='ssh_host' value='{escape(server['ssh_host'])}' required />"
        f"<input type='text' name='ssh_port' value='{server['ssh_port']}' required />"
        f"<input type='text' name='ssh_user' value='{escape(server['ssh_user'])}' required />"
        f"<input type='text' name='ssh_key_path' value='{escape(server['ssh_key_path'])}' required />"
        "</div>"
        f"<input type='text' name='remote_add_script' value='{escape(server['remote_add_script'])}' required />"
        f"<input type='text' name='remote_remove_script' value='{escape(server['remote_remove_script'])}' required />"
        f"<label><input type='checkbox' name='enabled' value='1' {'checked' if server['enabled'] else ''}/> Enabled</label>"
        "<button type='submit' class='btn'>Save Changes</button>"
        "</form>"
    )
    body = (
        _admin_page_header_html(
            f"Server: {server['name']}",
            f"Node details and operational controls (id={server_id}).",
            actions_html=action_bar,
            icon="ND",
        )
        + _admin_section_html(
            "Node Metrics",
            (
                "<div class='cards'>"
                f"<div class='card'><div class='label'>Enabled</div><div class='value'>{'yes' if server['enabled'] else 'no'}</div></div>"
                f"<div class='card'><div class='label'>Health</div><div id='sd-card-health' class='value' style='color:{health_color}'>{escape(str(runtime.get('health', '-')))}</div></div>"
                f"<div class='card'><div class='label'>Latency</div><div id='sd-card-latency' class='value'>{escape(str(runtime.get('vpn_latency_text', '-')))}</div></div>"
                f"<div class='card'><div class='label'>Loadavg</div><div id='sd-card-loadavg' class='value'>{escape(str(runtime.get('loadavg', '-')))}</div></div>"
                f"<div class='card'><div class='label'>RAM used</div><div id='sd-card-mem' class='value'>{escape(str(runtime.get('mem_used_pct', '-')))}%</div></div>"
                f"<div class='card'><div class='label'>Net RX</div><div id='sd-card-netrx' class='value'>{escape(str(runtime.get('net_rx_text', '-')))}</div></div>"
                f"<div class='card'><div class='label'>Net TX</div><div id='sd-card-nettx' class='value'>{escape(str(runtime.get('net_tx_text', '-')))}</div></div>"
                f"<div class='card'><div class='label'>Established now</div><div id='sd-card-established' class='value'>{metrics.get('established_connections', 0)}</div></div>"
                f"<div class='card'><div class='label'>Live devices now</div><div class='value'>{metrics.get('live_active_devices_count', 0)}</div></div>"
                f"<div class='card'><div class='label'>Active configs</div><div class='value'>{metrics['active_configs']}</div></div>"
                f"<div class='card'><div class='label'>Active devices</div><div class='value'>{metrics['active_devices']}</div></div>"
                f"<div class='card'><div class='label'>Active users</div><div class='value'>{metrics['active_users']}</div></div>"
                f"<div class='card'><div class='label'>Configs total</div><div class='value'>{metrics['total_configs']}</div></div>"
                f"<div class='card'><div class='label'>Created 24h</div><div class='value'>{metrics['created_24h']}</div></div>"
                f"<div class='card'><div class='label'>Revoked 24h</div><div class='value'>{metrics['revoked_24h']}</div></div>"
                "</div>"
            ),
        )
        + "<div class='layout-split'>"
        + "<div class='stack'>"
        + _admin_section_html("Runtime Monitor", runtime_table)
        + _admin_section_html(
            "Latency (24h)",
            f"<div class='load-item'><div class='hist-track'>{latency_bars}</div>{latency_stats_html}</div>",
        )
        + _admin_section_html(
            "CPU Load1 (24h)",
            f"<div class='load-item'><div class='hist-track'>{load_bars}</div>{load_stats_html}</div>",
        )
        + _admin_section_html(
            "Established Connections (24h)",
            f"<div class='load-item'><div class='hist-track'>{conn_bars}</div>{conn_stats_html}</div>",
        )
        + _admin_section_html(
            "New Configs Per Day (14d)",
            f"<div class='load-item'><div class='hist-track'>{daily_bars}</div>{daily_stats_html}</div>",
        )
        + _admin_section_html(
            "Live Active Devices (sampled now)",
            (
                f"{live_error_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>Device</th><th>Telegram ID</th><th>Traffic delta</th><th>Configs on server</th></tr></thead>"
                f"<tbody>{live_rows}</tbody></table>"
                "</div>"
            ),
        )
        + _admin_section_html(
            "Recent Configs",
            (
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Telegram ID</th><th>Device</th><th>Status</th><th>Created</th><th>Revoked</th></tr></thead>"
                f"<tbody>{recent_rows}</tbody></table>"
                "</div>"
            ),
        )
        + "</div>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Server Identity",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Host</div><div class='v'>{escape(server['host'])}:{server['port']}</div></div>"
                f"<div class='meta-item'><div class='k'>SNI</div><div class='v'>{escape(server['sni'])}</div></div>"
                f"<div class='meta-item'><div class='k'>Fingerprint</div><div class='v'>{escape(server['fingerprint'])}</div></div>"
                f"<div class='meta-item'><div class='k'>SSH</div><div class='v'>{escape(server['ssh_user'])}@{escape(server['ssh_host'])}:{server['ssh_port']}</div></div>"
                "</div>"
            ),
        )
        + _admin_section_html("Edit Server", edit_form, desc="Р’СЃРµ РїРѕР»СЏ Рё РїРѕРІРµРґРµРЅРёРµ СЃРѕС…СЂР°РЅРµРЅС‹, РёР·РјРµРЅРµРЅР° С‚РѕР»СЊРєРѕ РєРѕРјРїРѕРЅРѕРІРєР°.")
        + _admin_section_html(
            "Danger Zone",
            (
                "<div class='notice err'>РћРїРµСЂР°С†РёРё РЅРёР¶Рµ РјРµРЅСЏСЋС‚ СЃРѕСЃС‚РѕСЏРЅРёРµ РЅРѕРґС‹ РёР»Рё СѓРґР°Р»СЏСЋС‚ РґР°РЅРЅС‹Рµ. РСЃРїРѕР»СЊР·СѓР№С‚Рµ С‚РѕР»СЊРєРѕ РїСЂРё РЅРµРѕР±С…РѕРґРёРјРѕСЃС‚Рё.</div>"
                "<div class='section-actions'>"
        f"<form method='post' action='/admin/action/server/{server_id}/restart' class='inline-form'><button class='btn small' type='submit'>Restart service</button></form>"
                f"<form method='post' action='/admin/action/server/{server_id}/toggle-enabled' class='inline-form'><button class='btn small' type='submit'>{escape(toggle_text)}</button></form>"
                f"<form method='post' action='/admin/action/server/{server_id}/delete' class='inline-form'>"
                "<button class='btn danger small' type='submit' onclick=\"return confirm('РЈРґР°Р»РёС‚СЊ СЃРµСЂРІРµСЂ Рё РµРіРѕ Р»РѕРєР°Р»СЊРЅС‹Рµ Р·Р°РїРёСЃРё?');\">Delete Server</button>"
                "</form>"
                "</div>"
            ),
            desc="Restart/toggle/delete РІС‹РЅРµСЃРµРЅС‹ РѕС‚РґРµР»СЊРЅРѕ РѕС‚ РѕР±С‹С‡РЅРѕРіРѕ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ РїР°СЂР°РјРµС‚СЂРѕРІ СЃРµСЂРІРµСЂР°.",
        )
        + "</div>"
        + "</div>"
    )
    return _render_admin_layout(
        f"VPN Server {server['name']}",
        "servers",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
        extra_js=_admin_server_detail_runtime_refresh_js(server_id),
    )


def _render_admin_login_page(error_text: str = "") -> str:
    return _render_template_to_str(
        "admin_login.html",
        error_text=str(error_text or ""),
        admin_telegram_id=int(settings.admin_telegram_id or 0),
        admin_session_hours=max(1, int(settings.admin_session_hours or 24)),
        admin_cookie=ADMIN_COOKIE,
    )



def _admin_page_header_html(
    title: str,
    subtitle: str = "",
    actions_html: str = "",
    icon: str = "",
) -> str:
    icon_html = f"<span class='page-head-icon'>{escape(icon)}</span>" if icon else ""
    subtitle_html = f"<div class='page-head-sub'>{escape(subtitle)}</div>" if subtitle else ""
    actions_block = f"<div class='page-head-actions'>{actions_html}</div>" if actions_html else ""
    return (
        "<div class='page-head'>"
        "<div class='page-head-main'>"
        f"{icon_html}"
        "<div>"
        f"<h1>{escape(title)}</h1>"
        f"{subtitle_html}"
        "</div>"
        "</div>"
        f"{actions_block}"
        "</div>"
    )


def _admin_section_html(title: str, inner_html: str, desc: str = "", actions_html: str = "") -> str:
    desc_html = f"<div class='section-desc'>{escape(desc)}</div>" if desc else ""
    actions_block = f"<div class='section-actions'>{actions_html}</div>" if actions_html else ""
    return (
        "<section class='panel-section'>"
        "<div class='section-head'>"
        "<div>"
        f"<h2>{escape(title)}</h2>"
        f"{desc_html}"
        "</div>"
        f"{actions_block}"
        "</div>"
        f"{inner_html}"
        "</section>"
    )


def _render_admin_layout(
    title: str,
    current_tab: str,
    generated_at: str,
    body_html: str,
    msg_text: str = "",
    error_text: str = "",
    extra_js: str = "",
) -> str:
    tabs = [
        ("overview", "/admin/overview", "Overview"),
        ("users", "/admin/users", "Users"),
        ("servers", "/admin/servers", "Servers"),
        ("configs", "/admin/configs", "Configs"),
        ("subscriptions", "/admin/subscriptions", "Subscriptions"),
        ("payments", "/admin/payments", "Payments"),
        ("settings", "/admin/settings", "Settings"),
        ("giveaways", "/admin/giveaways", "Giveaways"),
        ("promos", "/admin/promos", "Promos"),
        ("audit", "/admin/audit", "Audit"),
    ]
    tabs_ctx = [{"key": k, "href": h, "label": l, "active": bool(k == current_tab)} for k, h, l in tabs]
    return _render_template_to_str(
        "admin_base.html",
        title=str(title or ""),
        generated_at=str(generated_at or ""),
        tabs=tabs_ctx,
        body_html=str(body_html or ""),
        msg_text=str(msg_text or ""),
        error_text=str(error_text or ""),
        extra_js=str(extra_js or ""),
    )


def _admin_servers_runtime_refresh_js() -> str:
    return """
(function(){
  let busy = false;
  function severity(runtime){
    if (!runtime) return "red";
    const health = String(runtime.health || "error");
    const xray = String(runtime.xray_state || "unknown");
    const portOpen = !!runtime.port_open;
    const reachable = !!runtime.vpn_reachable;
    if (health === "error" || xray !== "active" || !portOpen || !reachable) return "red";
    const latency = Number(runtime.vpn_latency_ms);
    if (!Number.isFinite(latency)) return health === "degraded" ? "yellow" : "green";
    let sev = latency < 120 ? "green" : (latency < 250 ? "yellow" : "red");
    if (health === "degraded" && sev === "green") sev = "yellow";
    return sev;
  }
  function sevColor(sev){
    if (sev === "green") return "#22c55e";
    if (sev === "yellow") return "#f59e0b";
    return "#ef4444";
  }
  function setText(id, value){
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value == null || value === "" ? "-" : String(value);
  }
  function yesNo(v){ return v ? "yes" : "no"; }
  async function tick(){
    if (busy || document.hidden) return;
    busy = true;
    try {
      const res = await fetch("/admin/api/servers/runtime-live", { headers: { "Accept": "application/json" } });
      if (!res.ok) return;
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];
      items.forEach(function(item){
        const id = Number(item.id || 0);
        const runtime = item.runtime || {};
        const color = sevColor(severity(runtime));
        setText(`srv-xray-${id}`, runtime.xray_state || "-");
        setText(`srv-port-${id}`, yesNo(runtime.port_open));
        setText(`srv-reach-${id}`, yesNo(runtime.vpn_reachable));
        setText(`srv-latency-${id}`, runtime.vpn_latency_text || "-");
        setText(`srv-version-${id}`, runtime.version || "-");
        setText(`srv-uptime-${id}`, runtime.uptime || "-");
        setText(`srv-error-${id}`, runtime.error || "-");
        const healthText = document.getElementById(`srv-health-${id}`);
        if (healthText){
          healthText.textContent = String(runtime.health || "-");
          healthText.style.color = color;
        }
        const healthDot = document.getElementById(`srv-health-dot-${id}`);
        if (healthDot) healthDot.style.background = color;
      });
      const meta = document.querySelector(".topbar-meta");
      if (meta && data.generated_at) meta.textContent = "updated: " + String(data.generated_at);
    } catch (_) {
    } finally {
      busy = false;
    }
  }
  tick();
  setInterval(tick, 30000);
})();
""".strip()


def _admin_server_detail_runtime_refresh_js(server_id: int) -> str:
    js = """
(function(){
  let busy = false;
  function severity(runtime){
    if (!runtime) return "red";
    const health = String(runtime.health || "error");
    const xray = String(runtime.xray_state || "unknown");
    const portOpen = !!runtime.port_open;
    const reachable = !!runtime.vpn_reachable;
    if (health === "error" || xray !== "active" || !portOpen || !reachable) return "red";
    const latency = Number(runtime.vpn_latency_ms);
    if (!Number.isFinite(latency)) return health === "degraded" ? "yellow" : "green";
    let sev = latency < 120 ? "green" : (latency < 250 ? "yellow" : "red");
    if (health === "degraded" && sev === "green") sev = "yellow";
    return sev;
  }
  function sevColor(sev){
    if (sev === "green") return "#22c55e";
    if (sev === "yellow") return "#f59e0b";
    return "#ef4444";
  }
  function setText(id, value){
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value == null || value === "" ? "-" : String(value);
  }
  function yesNo(v){ return v ? "yes" : "no"; }
  async function tick(){
    if (busy || document.hidden) return;
    busy = true;
    try{
      const res = await fetch("/admin/api/server/__SERVER_ID__/check", { headers: { "Accept": "application/json" } });
      if (!res.ok) return;
      const r = await res.json();
      const color = sevColor(severity(r));
      setText("sd-card-health", r.health || "-");
      setText("sd-card-latency", r.vpn_latency_text || "-");
      setText("sd-card-loadavg", r.loadavg || "-");
      setText("sd-card-mem", (r.mem_used_pct == null ? "-" : String(r.mem_used_pct) + "%"));
      setText("sd-card-netrx", r.net_rx_text || "-");
      setText("sd-card-nettx", r.net_tx_text || "-");
      setText("sd-card-established", Number(r.established_connections || 0));
      setText("sd-rt-xray", r.xray_state || "-");
      setText("sd-rt-reach", yesNo(r.vpn_reachable));
      setText("sd-rt-version", r.version || "-");
      setText("sd-rt-uptime", r.uptime || "-");
      setText("sd-rt-loadavg", r.loadavg || "-");
      setText("sd-rt-mem", (r.mem_used_pct == null ? "-" : String(r.mem_used_pct) + "%"));
      setText("sd-rt-netrx", r.net_rx_text || "-");
      setText("sd-rt-nettx", r.net_tx_text || "-");
      setText("sd-rt-established", Number(r.established_connections || 0));
      setText("sd-rt-error", r.error || "-");
      const healthCard = document.getElementById("sd-card-health");
      if (healthCard) healthCard.style.color = color;
      const reachCell = document.getElementById("sd-rt-reach");
      if (reachCell) reachCell.style.color = color;
    }catch(_){
    }finally{
      busy = false;
    }
  }
  tick();
  setInterval(tick, 30000);
})();
""".strip()
    return js.replace("__SERVER_ID__", str(int(server_id)))


def _render_admin_overview_page(snapshot: dict[str, Any], msg_text: str = "", error_text: str = "") -> str:
    summary = snapshot["summary"]
    analytics = snapshot.get("analytics", {}) or {}
    user_stats = analytics.get("users", {}) or {}
    monetization = analytics.get("monetization", {}) or {}
    series = analytics.get("series", {}) or {}
    top = analytics.get("top", {}) or {}
    server_rows = list(snapshot.get("servers", []))
    degraded_servers = sum(1 for s in server_rows if str(s.get("runtime", {}).get("health")) in {"degraded", "error"})
    unreachable_servers = sum(1 for s in server_rows if not bool(s.get("runtime", {}).get("vpn_reachable")))
    active_clients_total = sum(int(s.get("active_clients") or 0) for s in server_rows)

    paid_users_total = int(monetization.get("paid_users_total", 0))
    paid_users_30d = int(monetization.get("paid_users_30d", 0))
    revenue_7d = int(monetization.get("revenue_7d", 0))
    revenue_30d = int(monetization.get("revenue_30d", 0))
    conversion_pct = _safe_ratio(paid_users_total, summary.get("total_users", 0)) * 100.0
    arppu_total = _safe_ratio(summary.get("revenue_rub", 0), paid_users_total)
    arppu_30d = _safe_ratio(revenue_30d, paid_users_30d)
    arpu_total = _safe_ratio(summary.get("revenue_rub", 0), summary.get("total_users", 0))
    avg_configs_per_user = _safe_ratio(summary.get("total_configs", 0), summary.get("total_users", 0))
    avg_active_cfg_per_active_user = _safe_ratio(
        summary.get("active_configs", 0), user_stats.get("with_active_configs", 0)
    )
    live_users_value = int(summary.get("live_users_now", 0))
    if summary.get("live_users_partial"):
        live_users_text = f"{live_users_value}+"
    else:
        live_users_text = str(live_users_value)

    def _render_series_bars(points: list[dict[str, Any]], color: str) -> str:
        if not points:
            return "<div class='muted'>No data</div>"
        max_value = max(1, max(int(p.get("value", 0)) for p in points))
        stats = _series_stats(points, "value")
        bars = ""
        for p in points:
            value = int(p.get("value", 0))
            bar_height = max(2, int((value / max_value) * 72))
            bars += (
                f"<div class='hist-bar' style='height:{bar_height}px;background:{color};' "
                f"title='{escape(str(p.get('full', '-')))} | {value}'></div>"
            )
        stats_html = (
            "<div class='meta-list' style='margin-top:8px;'>"
            f"<div class='meta-item'><div class='k'>Sum</div><div class='v'>{int(stats['sum'])}</div></div>"
            f"<div class='meta-item'><div class='k'>Avg</div><div class='v'>{stats['avg']:.1f}</div></div>"
            f"<div class='meta-item'><div class='k'>Min</div><div class='v'>{int(stats['min'])}</div></div>"
            f"<div class='meta-item'><div class='k'>Max</div><div class='v'>{int(stats['max'])}</div></div>"
            f"<div class='meta-item'><div class='k'>Last</div><div class='v'>{int(stats['last'])}</div></div>"
            "</div>"
        )
        return f"<div class='hist-track'>{bars}</div>{stats_html}"
    health_rows = ""
    for s in server_rows[:10]:
        runtime = s.get("runtime", {}) or {}
        severity = _runtime_severity(runtime)
        color = _severity_color(severity)
        health_rows += (
            "<tr>"
            f"<td data-label='Name'><a href='/admin/server/{s['id']}' style='color:#9bc0ff;text-decoration:none;'>{escape(str(s['name']))}</a></td>"
            f"<td data-label='Host'>{escape(str(s['host']))}:{int(s['port'])}</td>"
            f"<td data-label='Health'><span class='status-inline'><span class='status-dot' style='background:{color}'></span><span style='color:{color}'>{escape(str(runtime.get('health', '-')))}</span></span></td>"
            f"<td data-label='Service'>{escape(str(runtime.get('xray_state', '-')))}</td>"
            f"<td data-label='Latency'>{escape(str(runtime.get('vpn_latency_text', '-')))}</td>"
            "</tr>"
        )
    if not health_rows:
        health_rows = "<tr><td colspan='5' class='muted'>No servers</td></tr>"
    quick_actions = (
        "<a class='btn ghost' href='/admin/servers' style='text-decoration:none;'>Open Servers</a>"
        "<a class='btn ghost' href='/admin/payments' style='text-decoration:none;'>Open Payments</a>"
        "<a class='btn ghost' href='/admin/promos' style='text-decoration:none;'>Open Promos</a>"
    )
    top_spenders_html = ""
    for row in list(top.get("spenders", [])):
        top_spenders_html += (
            "<div class='leader-item'>"
            f"<div><div class='name'>{escape(str(row.get('username') or '-'))}</div>"
            f"<div class='meta'>tg {escape(str(row.get('telegram_id', 0)))}</div></div>"
            f"<div class='val'>{int(row.get('total_rub') or 0)} RUB</div>"
            "</div>"
        )
    if not top_spenders_html:
        top_spenders_html = "<div class='muted'>No spenders yet</div>"
    top_referrers_html = ""
    for row in list(top.get("referrers", [])):
        top_referrers_html += (
            "<div class='leader-item'>"
            f"<div><div class='name'>{escape(str(row.get('username') or '-'))}</div>"
            f"<div class='meta'>tg {escape(str(row.get('telegram_id', 0)))}</div></div>"
            f"<div class='val'>{int(row.get('referrals') or 0)} refs В· {int(row.get('bonus_rub') or 0)} RUB</div>"
            "</div>"
        )
    if not top_referrers_html:
        top_referrers_html = "<div class='muted'>No referrals yet</div>"
    body = (
        _admin_page_header_html(
            "Overview",
            "Р“Р»Р°РІРЅР°СЏ РѕРїРµСЂР°С†РёРѕРЅРЅР°СЏ СЃРІРѕРґРєР°: РїРѕР»СЊР·РѕРІР°С‚РµР»Рё, СѓР·Р»С‹, РїР»Р°С‚РµР¶Рё Рё С‚РµРєСѓС‰РёР№ СЃС‚Р°С‚СѓСЃ СЃРёСЃС‚РµРјС‹.",
            actions_html=quick_actions,
            icon="OV",
        )
        + _admin_section_html(
            "Business Metrics",
            (
                "<div class='cards'>"
                f"<div class='card'><div class='label'>Users total</div><div class='value'>{summary['total_users']}</div></div>"
                f"<div class='card'><div class='label'>Subscriptions active</div><div class='value'>{summary['active_subscriptions']}</div></div>"
                f"<div class='card'><div class='label'>Live users now</div><div class='value'>{live_users_text}</div></div>"
                f"<div class='card'><div class='label'>Connections now</div><div class='value'>{int(summary.get('connected_now', 0))}</div></div>"
                f"<div class='card'><div class='label'>Servers total</div><div class='value'>{summary['total_servers']}</div></div>"
                f"<div class='card'><div class='label'>Servers enabled</div><div class='value'>{summary['enabled_servers']}</div></div>"
                f"<div class='card'><div class='label'>Configs total</div><div class='value'>{summary['total_configs']}</div></div>"
                f"<div class='card'><div class='label'>Configs active</div><div class='value'>{summary['active_configs']}</div></div>"
                f"<div class='card'><div class='label'>Invoices total</div><div class='value'>{summary['total_invoices']}</div></div>"
                f"<div class='card'><div class='label'>Invoices paid</div><div class='value'>{summary['paid_invoices']}</div></div>"
                f"<div class='card'><div class='label'>Revenue RUB</div><div class='value'>{summary['revenue_rub']}</div></div>"
                f"<div class='card'><div class='label'>Users balance RUB</div><div class='value'>{summary['total_balance_rub']}</div></div>"
                f"<div class='card'><div class='label'>Referral bonus RUB</div><div class='value'>{summary['total_ref_bonus_rub']}</div></div>"
                "</div>"
            ),
            desc="Р¤РёРЅР°РЅСЃРѕРІС‹Рµ Рё РїСЂРѕРґСѓРєС‚РѕРІС‹Рµ РїРѕРєР°Р·Р°С‚РµР»Рё Р±РµР· РїРµСЂРµС…РѕРґР° РїРѕ РІРєР»Р°РґРєР°Рј.",
        )
        + _admin_section_html(
            "User Analytics",
            (
                "<div class='cards'>"
                f"<div class='card'><div class='label'>New users 24h</div><div class='value'>{int(user_stats.get('new_24h', 0))}</div></div>"
                f"<div class='card'><div class='label'>New users 7d</div><div class='value'>{int(user_stats.get('new_7d', 0))}</div></div>"
                f"<div class='card'><div class='label'>New users 30d</div><div class='value'>{int(user_stats.get('new_30d', 0))}</div></div>"
                f"<div class='card'><div class='label'>Active users 30d</div><div class='value'>{int(user_stats.get('active_users_30d', 0))}</div></div>"
                f"<div class='card'><div class='label'>Users w/ configs</div><div class='value'>{int(user_stats.get('with_configs', 0))}</div></div>"
                f"<div class='card'><div class='label'>Users w/ active configs</div><div class='value'>{int(user_stats.get('with_active_configs', 0))}</div></div>"
                f"<div class='card'><div class='label'>Expiring 7d</div><div class='value'>{int(user_stats.get('expiring_7d', 0))}</div></div>"
                f"<div class='card'><div class='label'>Blocked users</div><div class='value'>{int(user_stats.get('blocked', 0))}</div></div>"
                "</div>"
                "<div class='meta-list' style='margin-top:10px;'>"
                f"<div class='meta-item'><div class='k'>Trial bonus granted</div><div class='v'>{int(user_stats.get('trial_bonus', 0))}</div></div>"
                f"<div class='meta-item'><div class='k'>Referred users</div><div class='v'>{int(user_stats.get('referred', 0))}</div></div>"
                f"<div class='meta-item'><div class='k'>Subscriptions total</div><div class='v'>{int(user_stats.get('with_subscription_any', 0))}</div></div>"
                f"<div class='meta-item'><div class='k'>Expired subscriptions</div><div class='v'>{int(user_stats.get('expired_subscriptions', 0))}</div></div>"
                f"<div class='meta-item'><div class='k'>Configs / user</div><div class='v'>{avg_configs_per_user:.2f}</div></div>"
                f"<div class='meta-item'><div class='k'>Active configs / active user</div><div class='v'>{avg_active_cfg_per_active_user:.2f}</div></div>"
                "</div>"
            ),
            desc="Р РѕСЃС‚ Р±Р°Р·С‹, Р°РєС‚РёРІРЅРѕСЃС‚СЊ Рё СЃС‚Р°С‚СѓСЃС‹ РїРѕРґРїРёСЃРѕРє Р·Р° РїРѕСЃР»РµРґРЅРёРµ РїРµСЂРёРѕРґС‹.",
        )
        + _admin_section_html(
            "Monetization",
            (
                "<div class='cards'>"
                f"<div class='card'><div class='label'>Revenue 7d</div><div class='value'>{revenue_7d}</div></div>"
                f"<div class='card'><div class='label'>Revenue 30d</div><div class='value'>{revenue_30d}</div></div>"
                f"<div class='card'><div class='label'>ARPPU total</div><div class='value'>{arppu_total:.1f}</div></div>"
                f"<div class='card'><div class='label'>ARPPU 30d</div><div class='value'>{arppu_30d:.1f}</div></div>"
                f"<div class='card'><div class='label'>ARPU total</div><div class='value'>{arpu_total:.1f}</div></div>"
                f"<div class='card'><div class='label'>Conversion</div><div class='value'>{conversion_pct:.1f}%</div></div>"
                "</div>"
                "<div class='meta-list' style='margin-top:10px;'>"
                f"<div class='meta-item'><div class='k'>Paid users total</div><div class='v'>{paid_users_total}</div></div>"
                f"<div class='meta-item'><div class='k'>Paid users 30d</div><div class='v'>{paid_users_30d}</div></div>"
                f"<div class='meta-item'><div class='k'>Payment conversion</div><div class='v'>{summary['paid_invoices']}/{summary['total_invoices']}</div></div>"
                f"<div class='meta-item'><div class='k'>Balance outstanding</div><div class='v'>{summary['total_balance_rub']}</div></div>"
                "</div>"
            ),
            desc="Р”РѕС…РѕРґРЅРѕСЃС‚СЊ Рё СЌС„С„РµРєС‚РёРІРЅРѕСЃС‚СЊ РјРѕРЅРµС‚РёР·Р°С†РёРё РїРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏРј Рё РїРµСЂРёРѕРґР°Рј.",
        )
        + _admin_section_html(
            "Growth Trends (14d)",
            (
                "<div class='chart-grid'>"
                "<div class='load-item'>"
                "<div class='chart-title'>New users</div>"
                f"{_render_series_bars(list(series.get('users_new_14d', [])), '#60a5fa')}"
                "</div>"
                "<div class='load-item'>"
                "<div class='chart-title'>New configs</div>"
                f"{_render_series_bars(list(series.get('configs_new_14d', [])), '#34d399')}"
                "</div>"
                "<div class='load-item'>"
                "<div class='chart-title'>Paid invoices</div>"
                f"{_render_series_bars(list(series.get('paid_invoices_14d', [])), '#f59e0b')}"
                "</div>"
                "<div class='load-item'>"
                "<div class='chart-title'>Revenue RUB</div>"
                f"{_render_series_bars(list(series.get('revenue_14d', [])), '#f97316')}"
                "</div>"
                "</div>"
            ),
            desc="Р”РёРЅР°РјРёРєР° СЂРµРіРёСЃС‚СЂР°С†РёРё, РєРѕРЅС„РёРіРѕРІ Рё РїР»Р°С‚РµР¶РµР№ РїРѕ РґРЅСЏРј.",
        )
        + _admin_section_html(
            "Live Connections (24h)",
            f"<div class='load-item'>{_render_series_bars(list(series.get('connections_24h', [])), '#38bdf8')}</div>",
            desc="РЎСѓРјРјР°СЂРЅС‹Рµ TCP РїРѕРґРєР»СЋС‡РµРЅРёСЏ РїРѕ РІСЃРµРј СѓР·Р»Р°Рј (Р°РіСЂРµРіР°С†РёСЏ РєР°Р¶РґС‹Рµ 30 РјРёРЅСѓС‚).",
        )
        + "<div class='layout-split'>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Servers Health Snapshot",
            (
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>Name</th><th>Host</th><th>Health</th><th>Service</th><th>Latency</th></tr></thead>"
                f"<tbody>{health_rows}</tbody></table>"
                "</div>"
            ),
            desc="РџРµСЂРІС‹Рµ 10 СЃРµСЂРІРµСЂРѕРІ РґР»СЏ Р±С‹СЃС‚СЂРѕРіРѕ РєРѕРЅС‚СЂРѕР»СЏ Р±РµР· РѕС‚РєСЂС‹С‚РёСЏ РІРєР»Р°РґРєРё Servers.",
        )
        + "</div>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Operations Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Degraded servers</div><div class='v'>{degraded_servers}</div></div>"
                f"<div class='meta-item'><div class='k'>Unreachable servers</div><div class='v'>{unreachable_servers}</div></div>"
                f"<div class='meta-item'><div class='k'>Active clients on nodes</div><div class='v'>{active_clients_total}</div></div>"
                f"<div class='meta-item'><div class='k'>Live users now</div><div class='v'>{live_users_text}</div></div>"
                f"<div class='meta-item'><div class='k'>Connections now</div><div class='v'>{int(summary.get('connected_now', 0))}</div></div>"
                f"<div class='meta-item'><div class='k'>Payment conversion</div><div class='v'>{summary['paid_invoices']}/{summary['total_invoices']}</div></div>"
                f"<div class='meta-item'><div class='k'>Active/Total configs</div><div class='v'>{summary['active_configs']}/{summary['total_configs']}</div></div>"
                f"<div class='meta-item'><div class='k'>Enabled/Total servers</div><div class='v'>{summary['enabled_servers']}/{summary['total_servers']}</div></div>"
                "</div>"
            ),
            desc="Р‘С‹СЃС‚СЂС‹Рµ РёРЅРґРёРєР°С‚РѕСЂС‹ РґР»СЏ РґРµР¶СѓСЂРЅРѕРіРѕ РїСЂРѕСЃРјРѕС‚СЂР°.",
        )
        + "</div>"
        + "</div>"
        + _admin_section_html(
            "Leaderboards",
            (
                "<div class='layout-split'>"
                "<div class='stack'>"
                "<div class='section-head'><h2>Top spenders</h2></div>"
                f"<div class='leader-list'>{top_spenders_html}</div>"
                "</div>"
                "<div class='stack'>"
                "<div class='section-head'><h2>Top referrers</h2></div>"
                f"<div class='leader-list'>{top_referrers_html}</div>"
                "</div>"
                "</div>"
            ),
            desc="Р›РёРґРµСЂС‹ РїРѕ РІС‹СЂСѓС‡РєРµ Рё СЂРµС„РµСЂР°Р»Р°Рј РґР»СЏ РѕС†РµРЅРєРё Р·РґРѕСЂРѕРІСЊСЏ РєР°РЅР°Р»РѕРІ.",
        )
    )
    return _render_admin_layout(
        "VPN Admin Overview",
        "overview",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_servers_page(snapshot: dict[str, Any], msg_text: str = "", error_text: str = "") -> str:
    load_chart_rows = ""
    for series in snapshot.get("load_history", []):
        points = list(series.get("points", []))[-60:]
        server_name = escape(series.get("server_name", "-"))
        if not points:
            load_chart_rows += (
                "<div class='load-item'>"
                f"<div class='load-head'><span>{server_name}</span><span>-</span></div>"
                "<div class='muted'>No history yet</div>"
                "</div>"
            )
            continue
        max_latency = max(max(float(p.get("latency_ms", 0.0)) for p in points), 300.0)
        start_ts = escape(str(points[0].get("ts", "-")))
        end_ts = escape(str(points[-1].get("ts", "-")))
        bars = ""
        for p in points:
            latency_ms = float(p.get("latency_ms", 0.0))
            bar_h = max(2, int((latency_ms / max_latency) * 72))
            if latency_ms < 120:
                cls = "sev-green"
            elif latency_ms < 250:
                cls = "sev-yellow"
            else:
                cls = "sev-red"
            bars += (
                f"<div class='hist-bar {cls}' style='height:{bar_h}px' "
                f"title='{escape(str(p.get('ts', '-')))} latency={latency_ms:.0f}ms'></div>"
            )
        load_chart_rows += (
            "<div class='load-item'>"
            "<div class='load-head'>"
            f"<span>{server_name}</span>"
            f"<span>{start_ts} - {end_ts}</span>"
            "</div>"
            "<div class='hist-track'>"
            f"{bars}"
            "</div>"
            "</div>"
        )

    if not load_chart_rows:
        load_chart_rows = "<div class='muted'>No servers</div>"

    server_rows = ""
    for server in snapshot["servers"]:
        runtime = server["runtime"]
        severity = _runtime_severity(runtime)
        health_color = _severity_color(severity)
        server_rows += (
            f"<tr data-server-id='{server['id']}'>"
            f"<td data-label='ID'>{server['id']}</td>"
            f"<td data-label='Name'><a href='/admin/server/{server['id']}' style='color:#93c5fd;text-decoration:none;'>{escape(server['name'])}</a></td>"
            f"<td data-label='Protocol'>{escape(str(server.get('protocol') or SERVER_PROTOCOL_VLESS_REALITY))}</td>"
            f"<td data-label='Host'>{escape(server['host'])}:{server['port']}</td>"
            f"<td data-label='SSH'>{escape(server['ssh_host'])}</td>"
            f"<td data-label='Enabled'>{'yes' if server['enabled'] else 'no'}</td>"
            f"<td data-label='Active clients'>{server['active_clients']}</td>"
            f"<td data-label='Health'><span class='status-inline'><span id='srv-health-dot-{server['id']}' class='status-dot' style='background:{health_color}'></span><span id='srv-health-{server['id']}' style='color:{health_color}'>{escape(runtime['health'])}</span></span></td>"
            f"<td data-label='Service' id='srv-xray-{server['id']}'>{escape(runtime['xray_state'])}</td>"
            f"<td data-label='Port' id='srv-port-{server['id']}'>{'yes' if runtime['port_open'] else 'no'}</td>"
            f"<td data-label='Reachable' id='srv-reach-{server['id']}'>{'yes' if runtime.get('vpn_reachable') else 'no'}</td>"
            f"<td data-label='VPN latency' id='srv-latency-{server['id']}'>{escape(str(runtime.get('vpn_latency_text', '-')))}</td>"
            f"<td data-label='Version' id='srv-version-{server['id']}'>{escape(runtime['version'])}</td>"
            f"<td data-label='Uptime' id='srv-uptime-{server['id']}'>{escape(runtime['uptime'])}</td>"
            f"<td data-label='Error' id='srv-error-{server['id']}'>{escape(runtime['error'] or '-')}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<a class='btn small' href='/admin/server/{server['id']}' style='display:inline-block;text-decoration:none;margin-right:6px;'>Details</a>"
            f"<form method='post' action='/admin/action/server/{server['id']}/restart' class='inline-form'>"
            "<button class='btn small' type='submit'>Restart Service</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    total_servers = len(snapshot.get("servers", []))
    enabled_servers = sum(1 for s in snapshot.get("servers", []) if bool(s.get("enabled")))
    degraded_servers = sum(
        1 for s in snapshot.get("servers", []) if str((s.get("runtime") or {}).get("health")) in {"degraded", "error"}
    )
    active_clients_total = sum(int(s.get("active_clients") or 0) for s in snapshot.get("servers", []))
    body = (
        _admin_page_header_html(
            "Servers",
            "РЈРїСЂР°РІР»РµРЅРёРµ СѓР·Р»Р°РјРё VPN, РёРјРїРѕСЂС‚ REALITY-РїР°СЂР°РјРµС‚СЂРѕРІ, РѕРїРµСЂР°С‚РёРІРЅС‹Р№ РјРѕРЅРёС‚РѕСЂРёРЅРі Рё РїРµСЂРµС…РѕРґ Рє РґРµС‚Р°Р»СЏРј СЃРµСЂРІРµСЂР°.",
            actions_html=(
                "<a class='btn ghost' href='/admin/api/overview' style='text-decoration:none;'>JSON snapshot</a>"
                "<a class='btn ghost' href='/admin/overview' style='text-decoration:none;'>Back to overview</a>"
            ),
            icon="SV",
        )
        + "<div class='layout-split'>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Add / Update VPN Server",
            (
                "<form method='post' action='/admin/action/server/add' class='server-form'>"
                "<input type='text' name='name' placeholder='Server name (optional, e.g. NL-1)' />"
                "<input type='text' name='host' placeholder='Server IP/host (e.g. 185.23.19.74)' required />"
                "<textarea name='reality_block' placeholder='PUBLIC_KEY=...&#10;SHORT_ID=...&#10;SNI=www.cloudflare.com&#10;PORT=443' required></textarea>"
                "<div class='sub-form'>"
                "<input type='text' name='ssh_host' placeholder='SSH host (optional, default = IP)' />"
                "<input type='text' name='ssh_port' placeholder='SSH port (optional)' />"
                "<input type='text' name='ssh_user' placeholder='SSH user (optional)' />"
                "<input type='text' name='ssh_key_path' placeholder='SSH key path (optional)' />"
                "</div>"
                "<button type='submit' class='btn'>Add/Update server</button>"
                "</form>"
            ),
            desc="Р’СЃС‚Р°РІСЊС‚Рµ Р±Р»РѕРє REALITY Рё Р±Р°Р·РѕРІС‹Рµ SSH-РїР°СЂР°РјРµС‚СЂС‹. РџРѕСЃР»Рµ СЃРѕС…СЂР°РЅРµРЅРёСЏ Р·Р°РїСѓСЃРєР°РµС‚СЃСЏ sync Р°РєС‚РёРІРЅС‹С… СѓСЃС‚СЂРѕР№СЃС‚РІ.",
        )
        + _admin_section_html(
            "Add Hysteria2 Server",
            (
                "<form method='post' action='/admin/action/server/add-hysteria2' class='server-form'>"
                "<input type='text' name='name' placeholder='Server name (e.g. DE-HY2-1)' required />"
                "<input type='text' name='host' placeholder='Domain/IP (e.g. hy2.example.com)' required />"
                "<div class='sub-form'>"
                "<input type='text' name='sni' placeholder='SNI / TLS server name (e.g. hy2.example.com)' required />"
                "<input type='text' name='port' placeholder='Port (default 443)' value='443' />"
                "<input type='text' name='hy2_alpn' placeholder='ALPN (default h3)' value='h3' />"
                "<input type='text' name='hy2_obfs' placeholder='obfs (optional, e.g. salamander)' value='salamander' />"
                "<input type='text' name='hy2_obfs_password' placeholder='obfs password (optional)' />"
                "</div>"
                "<div class='sub-form'>"
                "<label><input type='checkbox' name='hy2_insecure' value='1' /> insecure=1 in client links</label>"
                "</div>"
                "<div class='sub-form'>"
                "<input type='text' name='ssh_host' placeholder='SSH host (optional, default = host)' />"
                "<input type='text' name='ssh_port' placeholder='SSH port (optional)' />"
                "<input type='text' name='ssh_user' placeholder='SSH user (optional)' />"
                "<input type='text' name='ssh_key_path' placeholder='SSH key path (optional)' />"
                "</div>"
                "<button type='submit' class='btn'>Add HY2 server</button>"
                "</form>"
            ),
            desc="РЎРѕР·РґР°С‘С‚ РЅРѕРґСѓ protocol=hysteria2. РЎРєСЂРёРїС‚С‹ add/remove Р±РµСЂСѓС‚СЃСЏ РєР°Рє /opt/vpn/add_hysteria2_user.sh Рё /opt/vpn/remove_hysteria2_user.sh.",
        )
        + _admin_section_html(
            "Latency Trend (24h)",
            f"<div class='load-grid'>{load_chart_rows}</div>",
            desc="Р‘С‹СЃС‚СЂС‹Р№ РѕР±Р·РѕСЂ Р·Р°РґРµСЂР¶РєРё РїРѕ РІСЃРµРј СЃРµСЂРІРµСЂР°Рј. Р¦РІРµС‚ РїРѕР»РѕСЃС‹ РѕС‚СЂР°Р¶Р°РµС‚ РґРёР°РїР°Р·РѕРЅ latency.",
        )
        + _admin_section_html(
            "Servers Runtime",
            (
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Name</th><th>Protocol</th><th>Host</th><th>SSH</th><th>Enabled</th><th>Active clients</th><th>Health</th><th>Service</th><th>Port</th><th>Reachable</th><th>VPN latency</th><th>Version</th><th>Uptime</th><th>Error</th><th>Actions</th></tr></thead>"
                f"<tbody>{server_rows}</tbody></table>"
                "</div>"
            ),
            desc="РћСЃРЅРѕРІРЅР°СЏ С‚Р°Р±Р»РёС†Р° РѕРїРµСЂР°С†РёР№ РїРѕ РЅРѕРґР°Рј. Р’СЃРµ РґРµР№СЃС‚РІРёСЏ (details/restart) СЃРѕС…СЂР°РЅРµРЅС‹.",
        )
        + "</div>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Nodes Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Total nodes</div><div class='v'>{total_servers}</div></div>"
                f"<div class='meta-item'><div class='k'>Enabled nodes</div><div class='v'>{enabled_servers}</div></div>"
                f"<div class='meta-item'><div class='k'>Degraded / error</div><div class='v'>{degraded_servers}</div></div>"
                f"<div class='meta-item'><div class='k'>Active clients total</div><div class='v'>{active_clients_total}</div></div>"
                "</div>"
            ),
            desc="РћРїРµСЂР°С‚РёРІРЅР°СЏ СЃРІРѕРґРєР° РґР»СЏ РґРёСЃРїРµС‚С‡РµСЂРёР·Р°С†РёРё Рё capacity planning.",
        )
        + _admin_section_html(
            "Ops Notes",
            (
                "<div class='meta-list'>"
                "<div class='meta-item'><div class='k'>Workflow</div><div class='v'>Add server -> sync devices -> verify runtime</div></div>"
                "<div class='meta-item'><div class='k'>Recommended check</div><div class='v'>Open server details after import and verify service state + latency</div></div>"
                "<div class='meta-item'><div class='k'>Failure path</div><div class='v'>Use Restart service, then Sync devices, then check errors in row</div></div>"
                "</div>"
            ),
            desc="РџРѕРґСЃРєР°Р·РєРё РґР»СЏ РµР¶РµРґРЅРµРІРЅРѕР№ СЌРєСЃРїР»СѓР°С‚Р°С†РёРё Р±РµР· РѕС‚РґРµР»СЊРЅРѕР№ РґРѕРєСѓРјРµРЅС‚Р°С†РёРё.",
        )
        + "</div>"
        + "</div>"
    )
    return _render_admin_layout(
        "VPN Admin Servers",
        "servers",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
        extra_js=_admin_servers_runtime_refresh_js(),
    )


def _render_admin_configs_page(
    snapshot: dict[str, Any],
    msg_text: str = "",
    error_text: str = "",
    table_rows: list[dict[str, Any]] | None = None,
    pagination: dict[str, Any] | None = None,
    q: str = "",
    status_filter: str = "all",
) -> str:
    rows_source = list(table_rows if table_rows is not None else snapshot.get("recent_configs", []))
    config_rows = ""
    for cfg in rows_source:
        config_rows += (
            "<tr>"
            f"<td data-label='ID'>{cfg['id']}</td>"
            f"<td data-label='Telegram ID'>{escape(str(cfg['telegram_id']))}</td>"
            f"<td data-label='Server'>{escape(cfg['server'])}</td>"
            f"<td data-label='Device'>{escape(cfg['device_name'])}</td>"
            f"<td data-label='Status'>{'active' if cfg['is_active'] else 'revoked'}</td>"
            f"<td data-label='Created'>{escape(cfg['created_at'])}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<form method='post' action='/admin/action/config/{cfg['id']}/delete' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Delete</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    rows_count = len(rows_source)
    active_count = sum(1 for cfg in rows_source if bool(cfg.get("is_active")))
    filters_html = (
        "<form method='get' action='/admin/configs' class='sub-form'>"
        f"<input type='text' name='q' placeholder='Search: tg id / username / server / device' value='{escape(str(q or ''))}' />"
        "<select name='status'>"
        f"<option value='all' {'selected' if status_filter=='all' else ''}>All</option>"
        f"<option value='active' {'selected' if status_filter=='active' else ''}>Active</option>"
        f"<option value='revoked' {'selected' if status_filter=='revoked' else ''}>Revoked</option>"
        "</select>"
        "<button type='submit' class='btn'>Apply</button>"
        "<a class='btn ghost' href='/admin/configs' style='text-decoration:none;'>Reset</a>"
        "</form>"
    )
    pager_html = _admin_pagination_bar(
        "/admin/configs",
        pagination or {"total_pages": 1, "page": 1, "total": rows_count},
        {"q": q, "status": status_filter},
    )
    body = (
        _admin_page_header_html(
            "Configs",
            "РџРѕСЃР»РµРґРЅРёРµ РІС‹РґР°РЅРЅС‹Рµ Рё РѕС‚РѕР·РІР°РЅРЅС‹Рµ РєРѕРЅС„РёРіРё. РЈРґР°Р»РµРЅРёРµ Р»РѕРєР°Р»СЊРЅРѕР№ Р·Р°РїРёСЃРё Рё СѓРґР°Р»РµРЅРёРµ РЅР° СЃРµСЂРІРµСЂРµ РґРѕСЃС‚СѓРїРЅС‹ РёР· С‚Р°Р±Р»РёС†С‹.",
            actions_html="<a class='btn ghost' href='/admin/servers' style='text-decoration:none;'>Open servers</a>",
            icon="CF",
        )
        + _admin_section_html(
            "Configs Snapshot",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Rows shown</div><div class='v'>{rows_count}</div></div>"
                f"<div class='meta-item'><div class='k'>Active in list</div><div class='v'>{active_count}</div></div>"
                f"<div class='meta-item'><div class='k'>Revoked in list</div><div class='v'>{max(0, rows_count - active_count)}</div></div>"
                "</div>"
            ),
            desc="Р‘С‹СЃС‚СЂС‹Р№ РєРѕРЅС‚СЂРѕР»СЊ РїРѕСЃР»РµРґРЅРµР№ Р°РєС‚РёРІРЅРѕСЃС‚Рё РїРѕ СѓСЃС‚СЂРѕР№СЃС‚РІР°Рј.",
        )
        + _admin_section_html(
            "Recent Configs",
            (
                f"{filters_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Telegram ID</th><th>Server</th><th>Device</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>"
                f"<tbody>{config_rows}</tbody></table>"
                "</div>"
                f"{pager_html}"
            ),
        )
    )
    return _render_admin_layout(
        "VPN Admin Configs",
        "configs",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_subscriptions_page(
    snapshot: dict[str, Any],
    msg_text: str = "",
    error_text: str = "",
    table_rows: list[dict[str, Any]] | None = None,
    pagination: dict[str, Any] | None = None,
    q: str = "",
    status_filter: str = "all",
) -> str:
    rows_source = list(table_rows if table_rows is not None else snapshot.get("subscriptions", []))
    sub_rows = ""
    for sub in rows_source:
        sub_rows += (
            "<tr>"
            f"<td data-label='Telegram ID'>{escape(str(sub['telegram_id']))}</td>"
            f"<td data-label='Username'>{escape(sub['username'])}</td>"
            f"<td data-label='Balance RUB'>{sub['balance_rub']}</td>"
            f"<td data-label='Subscription until'>{escape(sub['subscription_until'])}</td>"
            f"<td data-label='Status'>{'active' if sub['is_active'] else 'expired'}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<form method='post' action='/admin/action/subscription/remove/{sub['telegram_id']}' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Remove</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    subs = rows_source
    active_subs = sum(1 for s in subs if bool(s.get("is_active")))
    filters_html = (
        "<form method='get' action='/admin/subscriptions' class='sub-form'>"
        f"<input type='text' name='q' placeholder='Search: tg id / username' value='{escape(str(q or ''))}' />"
        "<select name='status'>"
        f"<option value='all' {'selected' if status_filter=='all' else ''}>All</option>"
        f"<option value='active' {'selected' if status_filter=='active' else ''}>Active</option>"
        f"<option value='expired' {'selected' if status_filter=='expired' else ''}>Expired</option>"
        "</select>"
        "<button type='submit' class='btn'>Apply</button>"
        "<a class='btn ghost' href='/admin/subscriptions' style='text-decoration:none;'>Reset</a>"
        "</form>"
    )
    pager_html = _admin_pagination_bar(
        "/admin/subscriptions",
        pagination or {"total_pages": 1, "page": 1, "total": len(subs)},
        {"q": q, "status": status_filter},
    )
    body = (
        _admin_page_header_html(
            "Subscriptions",
            "РџСЂРѕРґР»РµРЅРёРµ РІСЂСѓС‡РЅСѓСЋ, СѓРґР°Р»РµРЅРёРµ РїРѕРґРїРёСЃРєРё Рё РєРѕРЅС‚СЂРѕР»СЊ СЃС‚Р°С‚СѓСЃР° РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ РІ РѕРґРЅРѕРј РјРµСЃС‚Рµ.",
            actions_html="<a class='btn ghost' href='/admin/payments' style='text-decoration:none;'>Open payments</a>",
            icon="SB",
        )
        + "<div class='layout-split'>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Add / Extend Subscription",
            (
                "<form method='post' action='/admin/action/subscription/add' class='sub-form'>"
                "<input type='text' name='telegram_id' placeholder='Telegram ID' required />"
                "<input type='text' name='days' placeholder='Days (e.g. 30)' required />"
                "<button type='submit' class='btn'>Add/Extend</button>"
                "</form>"
            ),
            desc="Р СѓС‡РЅРѕР№ РѕРІРµСЂСЂР°Р№Рґ РїРѕРґРїРёСЃРєРё РґР»СЏ СЃР°РїРїРѕСЂС‚Р°/РєРѕРјРїРµРЅСЃР°С†РёР№/С‚РµСЃС‚РѕРІ.",
        )
        + _admin_section_html(
            "Subscriptions List",
            (
                f"{filters_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>Telegram ID</th><th>Username</th><th>Balance RUB</th><th>Subscription until</th><th>Status</th><th>Actions</th></tr></thead>"
                f"<tbody>{sub_rows}</tbody></table>"
                "</div>"
                f"{pager_html}"
            ),
        )
        + "</div>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Subscriptions Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Rows shown</div><div class='v'>{len(subs)}</div></div>"
                f"<div class='meta-item'><div class='k'>Active in list</div><div class='v'>{active_subs}</div></div>"
                f"<div class='meta-item'><div class='k'>Expired in list</div><div class='v'>{max(0, len(subs)-active_subs)}</div></div>"
                "</div>"
            ),
            desc="РЎРїРёСЃРѕРє РѕС‚СЃРѕСЂС‚РёСЂРѕРІР°РЅ РїРѕ Р±Р»РёР¶Р°Р№С€РµРјСѓ РѕРєРѕРЅС‡Р°РЅРёСЋ РїРѕРґРїРёСЃРєРё.",
        )
        + "</div>"
        + "</div>"
    )
    return _render_admin_layout(
        "VPN Admin Subscriptions",
        "subscriptions",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_users_page(
    snapshot: dict[str, Any],
    msg_text: str = "",
    error_text: str = "",
    table_rows: list[dict[str, Any]] | None = None,
    pagination: dict[str, Any] | None = None,
    q: str = "",
    status_filter: str = "all",
) -> str:
    rows_source = list(table_rows if table_rows is not None else [])
    user_rows = ""
    for user in rows_source:
        has_sub = str(user.get("subscription_until") or "").strip() not in {"", "-"}
        if user.get("subscription_active"):
            sub_status = "active"
        elif has_sub:
            sub_status = "expired"
        else:
            sub_status = "none"
        if user.get("is_blocked"):
            status_text = f"blocked В· {sub_status}"
        else:
            status_text = sub_status
        tg_id = int(user.get("telegram_id") or 0)
        configs_text = f"{int(user.get('configs_active') or 0)}/{int(user.get('configs_total') or 0)}"
        paid_text = f"{int(user.get('paid_sum') or 0)} RUB"
        block_btn_cls = "btn danger small" if not user.get("is_blocked") else "btn ghost small"
        block_btn_label = "Block" if not user.get("is_blocked") else "Unblock"
        user_rows += (
            "<tr>"
            f"<td data-label='Telegram ID'>{tg_id}</td>"
            f"<td data-label='Username'>{escape(str(user.get('username') or '-'))}</td>"
            f"<td data-label='Balance'>{int(user.get('balance_rub') or 0)} RUB</td>"
            f"<td data-label='Subscription until'>{escape(str(user.get('subscription_until') or '-'))}</td>"
            f"<td data-label='Status'>{escape(status_text)}</td>"
            f"<td data-label='Configs active/total'>{escape(configs_text)}</td>"
            f"<td data-label='Devices active'>{int(user.get('devices_active') or 0)}</td>"
            f"<td data-label='Last config'>{escape(str(user.get('last_config_at') or '-'))}</td>"
            f"<td data-label='Paid total'>{escape(paid_text)}</td>"
            f"<td data-label='Last paid'>{escape(str(user.get('last_paid_at') or '-'))}</td>"
            f"<td data-label='Created'>{escape(str(user.get('created_at') or '-'))}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<a class='btn ghost small' href='/admin/configs?q={tg_id}' style='display:inline-block;text-decoration:none;'>Configs</a>"
            f"<a class='btn ghost small' href='/admin/payments?q={tg_id}' style='display:inline-block;text-decoration:none;margin-right:6px;'>Payments</a>"
            f"<a class='btn ghost small' href='/admin/user/{tg_id}/devices' style='display:inline-block;text-decoration:none;margin-right:6px;'>Devices</a>"
            f"<form method='post' action='/admin/action/subscription/add' class='inline-form'>"
            f"<input type='hidden' name='telegram_id' value='{tg_id}' />"
            "<input type='hidden' name='days' value='30' />"
            "<button class='btn small' type='submit'>+30d</button>"
            "</form>"
            f"<form method='post' action='/admin/action/subscription/remove/{tg_id}' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Remove sub</button>"
            "</form>"
            f"<form method='post' action='/admin/action/user/{tg_id}/toggle-block' class='inline-form'>"
            f"<button class='{block_btn_cls}' type='submit'>{block_btn_label}</button>"
            "</form>"
            f"<form method='post' action='/admin/action/user/{tg_id}/revoke-configs' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Revoke configs</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    rows_count = len(rows_source)
    active_subs = sum(1 for u in rows_source if bool(u.get("subscription_active")))
    blocked_count = sum(1 for u in rows_source if bool(u.get("is_blocked")))
    configs_active_total = sum(int(u.get("configs_active") or 0) for u in rows_source)
    configs_total = sum(int(u.get("configs_total") or 0) for u in rows_source)
    paid_total = sum(int(u.get("paid_sum") or 0) for u in rows_source)
    filters_html = (
        "<form method='get' action='/admin/users' class='sub-form'>"
        f"<input type='text' name='q' placeholder='Search: tg id / username' value='{escape(str(q or ''))}' />"
        "<select name='status'>"
        f"<option value='all' {'selected' if status_filter=='all' else ''}>All</option>"
        f"<option value='active' {'selected' if status_filter=='active' else ''}>Active sub</option>"
        f"<option value='expired' {'selected' if status_filter=='expired' else ''}>Expired sub</option>"
        f"<option value='no_sub' {'selected' if status_filter=='no_sub' else ''}>No sub</option>"
        f"<option value='blocked' {'selected' if status_filter=='blocked' else ''}>Blocked</option>"
        "</select>"
        "<button type='submit' class='btn'>Apply</button>"
        "<a class='btn ghost' href='/admin/users' style='text-decoration:none;'>Reset</a>"
        "</form>"
    )
    pager_html = _admin_pagination_bar(
        "/admin/users",
        pagination or {"total_pages": 1, "page": 1, "total": rows_count},
        {"q": q, "status": status_filter},
    )
    summary = snapshot.get("summary", {})
    analytics_users = snapshot.get("analytics", {}).get("users", {})
    body = (
        _admin_page_header_html(
            "Users",
            "РџСЂРѕС„РёР»Рё РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ СЃ Р±С‹СЃС‚СЂС‹РјРё РґРµР№СЃС‚РІРёСЏРјРё РїРѕ РїРѕРґРїРёСЃРєРµ, Р±Р»РѕРєРёСЂРѕРІРєРµ Рё РєРѕРЅС„РёРіР°Рј.",
            actions_html="<a class='btn ghost' href='/admin/configs' style='text-decoration:none;'>Open configs</a>",
            icon="US",
        )
        + _admin_section_html(
            "Users Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Total users</div><div class='v'>{int(summary.get('total_users') or 0)}</div></div>"
                f"<div class='meta-item'><div class='k'>Active subs</div><div class='v'>{int(summary.get('active_subscriptions') or 0)}</div></div>"
                f"<div class='meta-item'><div class='k'>Blocked users</div><div class='v'>{int(analytics_users.get('blocked') or 0)}</div></div>"
                f"<div class='meta-item'><div class='k'>Users w/ configs</div><div class='v'>{int(analytics_users.get('with_configs') or 0)}</div></div>"
                f"<div class='meta-item'><div class='k'>Active configs</div><div class='v'>{int(summary.get('active_configs') or 0)}</div></div>"
                "</div>"
            ),
            desc="РЎРІРѕРґРЅС‹Рµ РјРµС‚СЂРёРєРё РїРѕ РІСЃРµР№ Р±Р°Р·Рµ.",
        )
        + _admin_section_html(
            "Quick Actions",
            (
                "<form method='post' action='/admin/action/subscription/add' class='sub-form'>"
                "<input type='text' name='telegram_id' placeholder='Telegram ID' required />"
                "<input type='text' name='days' placeholder='Days (e.g. 30)' required />"
                "<button type='submit' class='btn'>Add/Extend</button>"
                "</form>"
                "<form method='post' action='/admin/action/user/revoke-configs' class='sub-form'>"
                "<input type='text' name='telegram_id' placeholder='Telegram ID for revoke' required />"
                "<button type='submit' class='btn danger'>Revoke all configs</button>"
                "</form>"
            ),
            desc="Р‘С‹СЃС‚СЂС‹Рµ РѕРїРµСЂР°С†РёРё РїРѕРґРґРµСЂР¶РєРё Р±РµР· РїРѕРёСЃРєР° РїРѕ СЃРїРёСЃРєСѓ.",
        )
        + _admin_section_html(
            "Users List",
            (
                f"{filters_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr>"
                "<th>Telegram ID</th><th>Username</th><th>Balance</th><th>Subscription until</th><th>Status</th>"
                "<th>Configs</th><th>Devices</th><th>Last config</th><th>Paid total</th><th>Last paid</th><th>Created</th><th>Actions</th>"
                "</tr></thead>"
                f"<tbody>{user_rows}</tbody></table>"
                "</div>"
                f"{pager_html}"
                "<div style='margin-top:10px;'>"
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Rows shown</div><div class='v'>{rows_count}</div></div>"
                f"<div class='meta-item'><div class='k'>Active subs in list</div><div class='v'>{active_subs}</div></div>"
                f"<div class='meta-item'><div class='k'>Blocked in list</div><div class='v'>{blocked_count}</div></div>"
                f"<div class='meta-item'><div class='k'>Configs active/total</div><div class='v'>{configs_active_total}/{configs_total}</div></div>"
                f"<div class='meta-item'><div class='k'>Paid total in list</div><div class='v'>{paid_total} RUB</div></div>"
                "</div>"
                "</div>"
            ),
            desc="РЎРїРёСЃРѕРє РїРѕР»СЊР·РѕРІР°С‚РµР»РµР№ СЃ РґРµР№СЃС‚РІРёСЏРјРё РґР»СЏ РїРѕРґРґРµСЂР¶РєРё.",
        )
    )
    return _render_admin_layout(
        "VPN Admin Users",
        "users",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_user_devices_page(
    snapshot: dict[str, Any],
    user_row: dict[str, Any],
    device_rows: list[dict[str, Any]],
    msg_text: str = "",
    error_text: str = "",
) -> str:
    tg_id = int(user_row.get("telegram_id") or 0)
    rows_html = ""
    for row in device_rows:
        device_name = str(row.get("device_name") or "-")
        rows_html += (
            "<tr>"
            f"<td data-label='Device'>{escape(device_name)}</td>"
            f"<td data-label='Configs active/total'>{int(row.get('configs_active') or 0)}/{int(row.get('configs_total') or 0)}</td>"
            f"<td data-label='Servers'>{escape(str(row.get('servers_text') or '-'))}</td>"
            f"<td data-label='Last config'>{escape(str(row.get('last_config_at') or '-'))}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<form method='post' action='/admin/action/user/{tg_id}/device/delete' class='inline-form'>"
            f"<input type='hidden' name='device_name' value='{escape(device_name)}' />"
            "<button class='btn danger small' type='submit'>Delete device</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html = "<tr><td colspan='5' class='muted'>No devices</td></tr>"

    device_count = len(device_rows)
    active_devices = sum(1 for row in device_rows if int(row.get("configs_active") or 0) > 0)
    total_configs = sum(int(row.get("configs_total") or 0) for row in device_rows)
    body = (
        _admin_page_header_html(
            "User Devices",
            "РЈРїСЂР°РІР»РµРЅРёРµ СѓСЃС‚СЂРѕР№СЃС‚РІР°РјРё РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ. РЈРґР°Р»РµРЅРёРµ СѓСЃС‚СЂРѕР№СЃС‚РІР° СѓРґР°Р»СЏРµС‚ РІСЃРµ СЃРІСЏР·Р°РЅРЅС‹Рµ РєРѕРЅС„РёРіРё.",
            actions_html="<a class='btn ghost' href='/admin/users' style='text-decoration:none;'>Back to users</a>",
            icon="UD",
        )
        + _admin_section_html(
            "User Snapshot",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Telegram ID</div><div class='v'>{tg_id}</div></div>"
                f"<div class='meta-item'><div class='k'>Username</div><div class='v'>{escape(str(user_row.get('username') or '-'))}</div></div>"
                f"<div class='meta-item'><div class='k'>Balance</div><div class='v'>{int(user_row.get('balance_rub') or 0)} RUB</div></div>"
                f"<div class='meta-item'><div class='k'>Subscription</div><div class='v'>{escape(str(user_row.get('subscription_until') or '-'))}</div></div>"
                f"<div class='meta-item'><div class='k'>Blocked</div><div class='v'>{'yes' if user_row.get('is_blocked') else 'no'}</div></div>"
                "</div>"
            ),
        )
        + _admin_section_html(
            "Devices",
            (
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>Device</th><th>Configs</th><th>Servers</th><th>Last config</th><th>Actions</th></tr></thead>"
                f"<tbody>{rows_html}</tbody></table>"
                "</div>"
                "<div style='margin-top:10px;'>"
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Devices total</div><div class='v'>{device_count}</div></div>"
                f"<div class='meta-item'><div class='k'>Active devices</div><div class='v'>{active_devices}</div></div>"
                f"<div class='meta-item'><div class='k'>Configs total</div><div class='v'>{total_configs}</div></div>"
                "</div>"
                "</div>"
            ),
        )
    )
    return _render_admin_layout(
        f"VPN Admin Devices В· {tg_id}",
        "users",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_payments_page(
    snapshot: dict[str, Any],
    msg_text: str = "",
    error_text: str = "",
    table_rows: list[dict[str, Any]] | None = None,
    pagination: dict[str, Any] | None = None,
    q: str = "",
    status_filter: str = "all",
    kind_filter: str = "all",
) -> str:
    rows_source = list(table_rows if table_rows is not None else snapshot.get("recent_payments", []))
    payment_rows = ""
    for p in rows_source:
        payment_rows += (
            "<tr>"
            f"<td data-label='Invoice'>{p['invoice_id']}</td>"
            f"<td data-label='Telegram ID'>{escape(str(p['telegram_id']))}</td>"
            f"<td data-label='Face RUB'>{p['amount_rub']}</td>"
            f"<td data-label='Payable RUB'>{p.get('payable_rub', p['amount_rub'])}</td>"
            f"<td data-label='Promo'>{escape(p.get('promo_code') or '-')}</td>"
            f"<td data-label='Discount'>{p.get('promo_discount_percent', 0)}%</td>"
            f"<td data-label='Kind'>{escape(p['kind'])}</td>"
            f"<td data-label='Credited'>{p['credited_rub']}</td>"
            f"<td data-label='Ref bonus'>{p['referral_bonus_rub']}</td>"
            f"<td data-label='Status'>{escape(p['status'])}</td>"
            f"<td data-label='Created'>{escape(p['created_at'])}</td>"
            f"<td data-label='Paid'>{escape(p['paid_at'])}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<form method='post' action='/admin/action/payment/{p['invoice_id']}/approve' class='inline-form'>"
            "<button class='btn small' type='submit'>Approve</button>"
            "</form>"
            f"<form method='post' action='/admin/action/payment/{p['invoice_id']}/reject' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Reject</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    payments = rows_source
    paid_rows = sum(1 for p in payments if str(p.get("status")) == "paid")
    pending_rows = sum(1 for p in payments if str(p.get("status")) == "active")
    filters_html = (
        "<form method='get' action='/admin/payments' class='sub-form'>"
        f"<input type='text' name='q' placeholder='Search: invoice / tg id / kind / promo' value='{escape(str(q or ''))}' />"
        "<select name='status'>"
        f"<option value='all' {'selected' if status_filter=='all' else ''}>All statuses</option>"
        f"<option value='active' {'selected' if status_filter=='active' else ''}>Active</option>"
        f"<option value='paid' {'selected' if status_filter=='paid' else ''}>Paid</option>"
        f"<option value='rejected' {'selected' if status_filter=='rejected' else ''}>Rejected</option>"
        "</select>"
        f"<input type='text' name='kind' placeholder='Kind filter (e.g. topup_platega)' value='{escape('' if kind_filter=='all' else kind_filter)}' />"
        "<button type='submit' class='btn'>Apply</button>"
        "<a class='btn ghost' href='/admin/payments' style='text-decoration:none;'>Reset</a>"
        "</form>"
    )
    pager_html = _admin_pagination_bar(
        "/admin/payments",
        pagination or {"total_pages": 1, "page": 1, "total": len(payments)},
        {"q": q, "status": status_filter, "kind": "" if kind_filter == "all" else kind_filter},
    )
    body = (
        _admin_page_header_html(
            "Payments",
            "РџСЂРѕРІРµСЂРєР° РїРѕСЃР»РµРґРЅРёС… РёРЅРІРѕР№СЃРѕРІ, СЂСѓС‡РЅРѕРµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ/РѕС‚РєР»РѕРЅРµРЅРёРµ, РєРѕРЅС‚СЂРѕР»СЊ РїСЂРѕРјРѕ Рё СЂРµС„РµСЂР°Р»СЊРЅС‹С… РЅР°С‡РёСЃР»РµРЅРёР№.",
            actions_html="<a class='btn ghost' href='/admin/overview' style='text-decoration:none;'>Open overview</a>",
            icon="PY",
        )
        + _admin_section_html(
            "Payments Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Rows shown</div><div class='v'>{len(payments)}</div></div>"
                f"<div class='meta-item'><div class='k'>Paid</div><div class='v'>{paid_rows}</div></div>"
                f"<div class='meta-item'><div class='k'>Active / pending</div><div class='v'>{pending_rows}</div></div>"
                f"<div class='meta-item'><div class='k'>Other statuses</div><div class='v'>{max(0, len(payments)-paid_rows-pending_rows)}</div></div>"
                "</div>"
            ),
            desc="РЎСЂРµР· РїРѕ РїРѕСЃР»РµРґРЅРёРј 50 РїР»Р°С‚РµР¶Р°Рј РёР· snapshot.",
        )
        + _admin_section_html(
            "Recent Payments",
            (
                f"{filters_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>Invoice</th><th>Telegram ID</th><th>Face RUB</th><th>Payable RUB</th><th>Promo</th><th>Discount</th><th>Kind</th><th>Credited</th><th>Ref bonus</th><th>Status</th><th>Created</th><th>Paid</th><th>Actions</th></tr></thead>"
                f"<tbody>{payment_rows}</tbody></table>"
                "</div>"
                f"{pager_html}"
            ),
        )
    )
    return _render_admin_layout(
        "VPN Admin Payments",
        "payments",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _mask_secret(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}...{raw[-2:]} (len={len(raw)})"


def _settings_table_html(items: list[tuple[str, Any]]) -> str:
    rows_html = ""
    for key, value in items:
        rows_html += f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
    if not rows_html:
        rows_html = "<tr><td colspan='2' class='muted'>No settings</td></tr>"
    return "<div class='table-wrap'><table><tbody>" + rows_html + "</tbody></table></div>"


def _settings_input_row(
    label: str,
    name: str,
    value: Any,
    input_type: str = "text",
    placeholder: str = "",
    note: str = "",
) -> str:
    value_attr = escape(str(value if value is not None else ""))
    placeholder_attr = escape(str(placeholder or ""))
    note_html = f"<div class='muted' style='margin-top:4px;'>{escape(note)}</div>" if note else ""
    return (
        "<div class='stack'>"
        f"<label class='muted' style='font-size:12px;'>{escape(label)}</label>"
        f"<input type='{escape(input_type)}' name='{escape(name)}' value='{value_attr}' placeholder='{placeholder_attr}' />"
        f"{note_html}"
        "</div>"
    )


def _env_quote(value: str) -> str:
    if value == "":
        return ""
    needs_quote = any(ch in value for ch in (" ", "#", "\""))
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
    return f"\"{escaped}\""


def _read_env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _upsert_env_lines(lines: list[str], key: str, value: str) -> list[str]:
    key_eq = f"{key}="
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key_eq}{_env_quote(value)}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key_eq}{_env_quote(value)}")
    return out


def _save_env_updates(updates: dict[str, str]) -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    lines = _read_env_lines(env_path)
    for key, value in updates.items():
        lines = _upsert_env_lines(lines, key, value)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_admin_settings_page(snapshot: dict[str, Any], msg_text: str = "", error_text: str = "") -> str:
    core_items = [
        ("API host", settings.api_host),
        ("API port", settings.api_port),
        ("API base URL", settings.api_base_url),
        ("Public API base URL", settings.public_api_base_url or "-"),
        ("Database URL", settings.database_url),
    ]
    admin_items = [
        ("Admin Telegram ID", settings.admin_telegram_id),
        ("Giveaway admin ID", settings.giveaway_admin_telegram_id),
        ("Admin session hours", settings.admin_session_hours),
        ("Admin panel password", _mask_secret(settings.admin_panel_password)),
        ("Admin session secret", _mask_secret(settings.admin_session_secret)),
        ("Internal API token", _mask_secret(settings.internal_api_token)),
    ]
    subscription_items = [
        ("Subscription price (RUB)", settings.subscription_price_rub),
        ("Days per month", settings.subscription_days_per_month),
        ("Welcome bonus days", settings.welcome_bonus_days),
        ("Referral bonus (%)", settings.referral_bonus_percent),
        ("Max active configs per user", MAX_ACTIVE_CONFIGS_PER_USER),
    ]
    payment_items = [
        ("Payment gateway", settings.payment_gateway),
        ("Min topup (RUB)", settings.min_topup_rub),
        ("Max topup (RUB)", settings.max_topup_rub),
        ("Payments notify chat", settings.payments_notify_chat_id),
    ]
    crypto_items = [
        ("CryptoPay base URL", settings.crypto_pay_base_url),
        ("CryptoPay API token", _mask_secret(settings.crypto_pay_api_token)),
        ("Accepted assets", settings.crypto_pay_accepted_assets),
        ("Invoice expires (sec)", settings.crypto_pay_invoice_expires_in),
    ]
    yoomoney_items = [
        ("YooMoney receiver", settings.yoomoney_receiver or "-"),
        ("YooMoney secret", _mask_secret(settings.yoomoney_notification_secret)),
        ("YooMoney quickpay form", settings.yoomoney_quickpay_form),
        ("YooMoney payment type", settings.yoomoney_payment_type),
        ("YooMoney success URL", settings.yoomoney_success_url or "-"),
    ]
    platega_items = [
        ("Platega base URL", settings.platega_base_url),
        ("Platega merchant ID", _mask_secret(settings.platega_merchant_id)),
        ("Platega API key", _mask_secret(settings.platega_api_key)),
        ("Platega payment method (default)", settings.platega_payment_method),
        ("Platega payment method card", settings.platega_payment_method_card),
        ("Platega payment method SBP", settings.platega_payment_method_sbp),
        ("Platega payment method crypto", settings.platega_payment_method_crypto),
        ("Platega return URL", settings.platega_return_url or "-"),
        ("Platega failed URL", settings.platega_failed_url or "-"),
    ]
    channel_items = [
        ("Welcome channel URL", settings.welcome_channel_url),
        ("Welcome channel chat", settings.welcome_channel_chat),
        ("HApp import URL template", settings.happ_import_url_template),
        ("HApp download URL", settings.happ_download_url),
    ]

    edit_form = (
        "<form method='post' action='/admin/settings/update' class='server-form'>"
        "<div class='sub-form'>"
        f"{_settings_input_row('Database URL', 'database_url', settings.database_url, note='РР·РјРµРЅРµРЅРёРµ С‚СЂРµР±СѓРµС‚ СЂРµСЃС‚Р°СЂС‚Р° РїСЂРёР»РѕР¶РµРЅРёСЏ.')}"
        f"{_settings_input_row('API host', 'api_host', settings.api_host)}"
        f"{_settings_input_row('API port', 'api_port', settings.api_port, input_type='number')}"
        f"{_settings_input_row('API base URL', 'api_base_url', settings.api_base_url)}"
        f"{_settings_input_row('Public API base URL', 'public_api_base_url', settings.public_api_base_url)}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('Admin Telegram ID', 'admin_telegram_id', settings.admin_telegram_id, input_type='number')}"
        f"{_settings_input_row('Giveaway admin ID', 'giveaway_admin_telegram_id', settings.giveaway_admin_telegram_id, input_type='number')}"
        f"{_settings_input_row('Admin session hours', 'admin_session_hours', settings.admin_session_hours, input_type='number')}"
        f"{_settings_input_row('Admin panel password', 'admin_panel_password', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.admin_panel_password)}')}"
        f"{_settings_input_row('Admin session secret', 'admin_session_secret', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.admin_session_secret)}')}"
        f"{_settings_input_row('Internal API token', 'internal_api_token', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.internal_api_token)}')}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('Subscription price (RUB)', 'subscription_price_rub', settings.subscription_price_rub, input_type='number')}"
        f"{_settings_input_row('Days per month', 'subscription_days_per_month', settings.subscription_days_per_month, input_type='number')}"
        f"{_settings_input_row('Welcome bonus days', 'welcome_bonus_days', settings.welcome_bonus_days, input_type='number')}"
        f"{_settings_input_row('Referral bonus (%)', 'referral_bonus_percent', settings.referral_bonus_percent, input_type='number')}"
        f"{_settings_input_row('Max active configs per user', 'MAX_ACTIVE_CONFIGS_PER_USER', MAX_ACTIVE_CONFIGS_PER_USER, input_type='number')}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('Payment gateway', 'payment_gateway', settings.payment_gateway)}"
        f"{_settings_input_row('Min topup (RUB)', 'min_topup_rub', settings.min_topup_rub, input_type='number')}"
        f"{_settings_input_row('Max topup (RUB)', 'max_topup_rub', settings.max_topup_rub, input_type='number')}"
        f"{_settings_input_row('Payments notify chat', 'payments_notify_chat_id', settings.payments_notify_chat_id, input_type='number')}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('CryptoPay base URL', 'crypto_pay_base_url', settings.crypto_pay_base_url)}"
        f"{_settings_input_row('CryptoPay API token', 'crypto_pay_api_token', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.crypto_pay_api_token)}')}"
        f"{_settings_input_row('Accepted assets', 'crypto_pay_accepted_assets', settings.crypto_pay_accepted_assets)}"
        f"{_settings_input_row('Invoice expires (sec)', 'crypto_pay_invoice_expires_in', settings.crypto_pay_invoice_expires_in, input_type='number')}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('YooMoney receiver', 'yoomoney_receiver', settings.yoomoney_receiver)}"
        f"{_settings_input_row('YooMoney secret', 'yoomoney_notification_secret', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.yoomoney_notification_secret)}')}"
        f"{_settings_input_row('YooMoney quickpay form', 'yoomoney_quickpay_form', settings.yoomoney_quickpay_form)}"
        f"{_settings_input_row('YooMoney payment type', 'yoomoney_payment_type', settings.yoomoney_payment_type)}"
        f"{_settings_input_row('YooMoney success URL', 'yoomoney_success_url', settings.yoomoney_success_url)}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('Platega base URL', 'platega_base_url', settings.platega_base_url)}"
        f"{_settings_input_row('Platega merchant ID', 'platega_merchant_id', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.platega_merchant_id)}')}"
        f"{_settings_input_row('Platega API key', 'platega_api_key', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.platega_api_key)}')}"
        f"{_settings_input_row('Platega payment method (default)', 'platega_payment_method', settings.platega_payment_method, input_type='number')}"
        f"{_settings_input_row('Platega payment method card', 'platega_payment_method_card', settings.platega_payment_method_card, input_type='number')}"
        f"{_settings_input_row('Platega payment method SBP', 'platega_payment_method_sbp', settings.platega_payment_method_sbp, input_type='number')}"
        f"{_settings_input_row('Platega payment method crypto', 'platega_payment_method_crypto', settings.platega_payment_method_crypto, input_type='number')}"
        f"{_settings_input_row('Platega return URL', 'platega_return_url', settings.platega_return_url)}"
        f"{_settings_input_row('Platega failed URL', 'platega_failed_url', settings.platega_failed_url)}"
        "</div>"
        "<div class='sub-form'>"
        f"{_settings_input_row('Welcome channel URL', 'welcome_channel_url', settings.welcome_channel_url)}"
        f"{_settings_input_row('Welcome channel chat', 'welcome_channel_chat', settings.welcome_channel_chat)}"
        f"{_settings_input_row('HApp import URL template', 'happ_import_url_template', settings.happ_import_url_template)}"
        f"{_settings_input_row('HApp download URL', 'happ_download_url', settings.happ_download_url)}"
        f"{_settings_input_row('Bot token', 'bot_token', '', input_type='password', placeholder='(unchanged)', note=f'Current: {_mask_secret(settings.bot_token)}')}"
        "</div>"
        "<button type='submit' class='btn'>Save Settings</button>"
        "</form>"
    )

    body = (
        _admin_page_header_html(
            "Settings",
            "Application configuration. Secrets are masked in read-only views.",
            actions_html="<a class='btn ghost' href='/admin/overview' style='text-decoration:none;'>Back to overview</a>",
            icon="ST",
        )
        + _admin_section_html("Core", _settings_table_html(core_items))
        + _admin_section_html("Admin & Security", _settings_table_html(admin_items))
        + _admin_section_html("Subscription & Referral", _settings_table_html(subscription_items))
        + _admin_section_html("Payments", _settings_table_html(payment_items))
        + _admin_section_html("CryptoPay", _settings_table_html(crypto_items))
        + _admin_section_html("YooMoney", _settings_table_html(yoomoney_items))
        + _admin_section_html("Platega", _settings_table_html(platega_items))
        + _admin_section_html("Channels & Apps", _settings_table_html(channel_items))
        + _admin_section_html("Edit Settings", edit_form, desc="РџСѓСЃС‚С‹Рµ Р·РЅР°С‡РµРЅРёСЏ РґР»СЏ СЃРµРєСЂРµС‚РѕРІ РѕСЃС‚Р°РІР»СЏСЋС‚ РёС… Р±РµР· РёР·РјРµРЅРµРЅРёР№.")
    )
    return _render_admin_layout(
        "Settings",
        "settings",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _promo_kind_title(kind: str) -> str:
    if kind == PROMO_KIND_BALANCE:
        return "Balance RUB"
    if kind == PROMO_KIND_TOPUP_DISCOUNT:
        return "Topup Discount %"
    if kind == PROMO_KIND_SUBSCRIPTION_DAYS:
        return "Subscription Days"
    return kind


def _render_admin_promos_page(
    snapshot: dict[str, Any],
    promos: list[dict[str, Any]],
    recent_uses: list[dict[str, Any]],
    msg_text: str = "",
    error_text: str = "",
    uses_q: str = "",
    uses_pagination: dict[str, Any] | None = None,
) -> str:
    promo_rows = ""
    for p in promos:
        promo_rows += (
            "<tr>"
            f"<td data-label='ID'>{p['id']}</td>"
            f"<td data-label='Code'>{escape(p['code'])}</td>"
            f"<td data-label='Type'>{escape(_promo_kind_title(p['kind']))}</td>"
            f"<td data-label='Value'>{p['value_int']}</td>"
            f"<td data-label='Uses'>{p['uses_total']}</td>"
            f"<td data-label='Max total'>{p['max_uses_total'] or '-'}</td>"
            f"<td data-label='Max per user'>{p['max_uses_per_user'] or '-'}</td>"
            f"<td data-label='Starts'>{escape(p['starts_at'])}</td>"
            f"<td data-label='Ends'>{escape(p['ends_at'])}</td>"
            f"<td data-label='Enabled'>{'yes' if p['enabled'] else 'no'}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<form method='post' action='/admin/action/promo/{p['id']}/toggle' class='inline-form'>"
            f"<button class='btn small' type='submit'>{'Disable' if p['enabled'] else 'Enable'}</button>"
            "</form>"
            f"<form method='post' action='/admin/action/promo/{p['id']}/delete' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Archive</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    uses_rows = ""
    for u in recent_uses:
        uses_rows += (
            "<tr>"
            f"<td data-label='ID'>{u['id']}</td>"
            f"<td data-label='Code'>{escape(u['code'])}</td>"
            f"<td data-label='Telegram ID'>{escape(str(u['telegram_id']))}</td>"
            f"<td data-label='Kind'>{escape(u['kind'])}</td>"
            f"<td data-label='Value'>{u['value_int']}</td>"
            f"<td data-label='Invoice'>{escape(str(u['payment_invoice_id']) if u['payment_invoice_id'] else '-')}</td>"
            f"<td data-label='Created'>{escape(u['created_at'])}</td>"
            "</tr>"
        )
    enabled_promos = sum(1 for p in promos if bool(p.get("enabled")))
    uses_filters_html = (
        "<form method='get' action='/admin/promos' class='sub-form'>"
        f"<input type='text' name='uses_q' placeholder='Search uses: code / tg id / kind' value='{escape(str(uses_q or ''))}' />"
        "<button type='submit' class='btn'>Apply</button>"
        "<a class='btn ghost' href='/admin/promos' style='text-decoration:none;'>Reset</a>"
        "</form>"
    )
    uses_pager_html = _admin_pagination_bar(
        "/admin/promos",
        uses_pagination or {"total_pages": 1, "page": 1, "total": len(recent_uses)},
        {"uses_q": uses_q},
        page_param="uses_page",
    )
    body = (
        _admin_page_header_html(
            "Promos",
            "РЎРѕР·РґР°РЅРёРµ Рё СѓРїСЂР°РІР»РµРЅРёРµ РїСЂРѕРјРѕРєРѕРґР°РјРё РґР»СЏ РїРѕРїРѕР»РЅРµРЅРёР№, Р±Р°Р»Р°РЅСЃР° Рё РґРЅРµР№ РїРѕРґРїРёСЃРєРё. Р’СЃРµ РґРµР№СЃС‚РІРёСЏ СЃРѕС…СЂР°РЅРµРЅС‹.",
            actions_html="<a class='btn ghost' href='/admin/payments' style='text-decoration:none;'>Open payments</a>",
            icon="PR",
        )
        + "<div class='layout-split'>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Create / Update Promo",
            (
                "<form method='post' action='/admin/action/promo/save' class='server-form'>"
                "<div class='sub-form'>"
                "<input type='text' name='code' placeholder='PROMO2026' required />"
                "<select name='kind'>"
                f"<option value='{PROMO_KIND_BALANCE}'>Balance RUB</option>"
                f"<option value='{PROMO_KIND_TOPUP_DISCOUNT}'>Topup Discount %</option>"
                f"<option value='{PROMO_KIND_SUBSCRIPTION_DAYS}'>Subscription Days</option>"
                "</select>"
                "<input type='text' name='value_int' placeholder='Value' required />"
                "<input type='text' name='max_uses_total' placeholder='Max total uses (0=inf)' />"
                "<input type='text' name='max_uses_per_user' placeholder='Max per user (0=inf)' />"
                "<input type='text' name='starts_at' placeholder='Start UTC YYYY-MM-DDTHH:MM' />"
                "<input type='text' name='ends_at' placeholder='End UTC YYYY-MM-DDTHH:MM' />"
                "</div>"
                "<label><input type='checkbox' name='enabled' value='1' checked /> Enabled</label>"
                "<button type='submit' class='btn'>Save Promo</button>"
                "</form>"
            ),
            desc="Р•СЃР»Рё РєРѕРґ СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓРµС‚, Р·Р°РїРёСЃСЊ Р±СѓРґРµС‚ РѕР±РЅРѕРІР»РµРЅР°.",
        )
        + _admin_section_html(
            "Promocodes",
            (
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Code</th><th>Type</th><th>Value</th><th>Uses</th><th>Max total</th><th>Max per user</th><th>Starts</th><th>Ends</th><th>Enabled</th><th>Actions</th></tr></thead>"
                f"<tbody>{promo_rows}</tbody></table>"
                "</div>"
            ),
        )
        + "</div>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Promo Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Total promos</div><div class='v'>{len(promos)}</div></div>"
                f"<div class='meta-item'><div class='k'>Enabled promos</div><div class='v'>{enabled_promos}</div></div>"
                f"<div class='meta-item'><div class='k'>Recent uses shown</div><div class='v'>{len(recent_uses)}</div></div>"
                "</div>"
            ),
        )
        + _admin_section_html(
            "Recent Promo Uses",
            (
                f"{uses_filters_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Code</th><th>Telegram ID</th><th>Kind</th><th>Value</th><th>Invoice</th><th>Created</th></tr></thead>"
                f"<tbody>{uses_rows}</tbody></table>"
                "</div>"
                f"{uses_pager_html}"
            ),
        )
        + "</div>"
        + "</div>"
    )
    return _render_admin_layout(
        "VPN Admin Promos",
        "promos",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_giveaways_page(
    snapshot: dict[str, Any],
    giveaways: list[dict[str, Any]],
    msg_text: str = "",
    error_text: str = "",
) -> str:
    rows = ""
    for g in giveaways:
        title_html = escape(g["title"]) or f"Giveaway #{g['id']}"
        if g.get("description"):
            title_html = f"{title_html}<div class='muted'>{escape(g['description'])}</div>"
        winners = g.get("winners") or []
        winners_html = "-"
        if winners:
            chunks = []
            for w in winners:
                username = w.get("username") or "-"
                handle = f"@{username}" if username != "-" else "-"
                chunks.append(f"{w.get('telegram_id', 0)} {handle}")
            winners_html = "<br/>".join(escape(x) for x in chunks)
        rows += (
            "<tr>"
            f"<td data-label='ID'>{g['id']}</td>"
            f"<td data-label='Title'>{title_html}</td>"
            f"<td data-label='Type'>{escape(g['kind_title'])}</td>"
            f"<td data-label='Condition'>{escape(g['condition_text'])}</td>"
            f"<td data-label='Prize'>{escape(g['prize'] or '-')}</td>"
            f"<td data-label='Starts'>{escape(g['starts_at'])}</td>"
            f"<td data-label='Ends'>{escape(g['ends_at'])}</td>"
            f"<td data-label='Enabled'>{'yes' if g['enabled'] else 'no'}</td>"
            f"<td data-label='Active'>{'yes' if g['active'] else 'no'}</td>"
            f"<td data-label='Participants'>{int(g.get('participants') or 0)}</td>"
            f"<td data-label='Winners'>{winners_html}</td>"
            "<td data-label='Actions' class='actions-cell'>"
            f"<form method='post' action='/admin/action/giveaway/{g['id']}/toggle' class='inline-form'>"
            f"<button class='btn small' type='submit'>{'Disable' if g['enabled'] else 'Enable'}</button>"
            "</form>"
            f"<form method='post' action='/admin/action/giveaway/{g['id']}/draw' class='inline-form'>"
            "<button class='btn small' type='submit'>Draw</button>"
            "</form>"
            f"<form method='post' action='/admin/action/giveaway/{g['id']}/end' class='inline-form'>"
            "<button class='btn small' type='submit'>End</button>"
            "</form>"
            f"<form method='post' action='/admin/action/giveaway/{g['id']}/reroll' class='inline-form'>"
            "<button class='btn small' type='submit'>Reroll</button>"
            "</form>"
            f"<form method='post' action='/admin/action/giveaway/{g['id']}/delete' class='inline-form'>"
            "<button class='btn danger small' type='submit'>Delete</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    if not rows:
        rows = "<tr><td colspan='12' class='muted'>No giveaways yet</td></tr>"
    active_now = sum(1 for g in giveaways if g.get("active"))
    body = (
        _admin_page_header_html(
            "Giveaways",
            "РЎРѕР·РґР°РЅРёРµ СЂРѕР·С‹РіСЂС‹С€РµР№ Рё СѓРїСЂР°РІР»РµРЅРёРµ СѓСЃР»РѕРІРёСЏРјРё СѓС‡Р°СЃС‚РёСЏ.",
            actions_html="<a class='btn ghost' href='/admin/overview' style='text-decoration:none;'>Open overview</a>",
            icon="GW",
        )
        + "<div class='layout-split'>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Create Giveaway",
            (
                "<form method='post' action='/admin/action/giveaway/save' class='server-form'>"
                "<div class='sub-form'>"
                "<input type='text' name='title' placeholder='РќР°Р·РІР°РЅРёРµ' required />"
                "<select name='kind'>"
                f"<option value='{GIVEAWAY_KIND_CHANNEL_SUB}'>РџРѕРґРїРёСЃРєР° РЅР° РіСЂСѓРїРїСѓ</option>"
                f"<option value='{GIVEAWAY_KIND_ACTIVE_SUB_MIN_DEPOSIT}'>РђРєС‚РёРІРЅР°СЏ РїРѕРґРїРёСЃРєР° + РґРµРїРѕР·РёС‚</option>"
                f"<option value='{GIVEAWAY_KIND_REFERRAL_LEADER}'>Р›РёРґРµСЂ РїРѕ СЂРµС„РµСЂР°Р»Р°Рј</option>"
                "</select>"
                "<input type='text' name='prize' placeholder='РџСЂРёР· (РЅР°РїСЂРёРјРµСЂ, 30 РґРЅРµР№ РїРѕРґРїРёСЃРєРё)' />"
                "<input type='text' name='starts_at' placeholder='Start UTC YYYY-MM-DDTHH:MM' />"
                "<input type='text' name='duration' placeholder='Р”Р»РёС‚РµР»СЊРЅРѕСЃС‚СЊ (РЅР°РїСЂРёРјРµСЂ, 1m, 1h, 1d)' />"
                "</div>"
                "<textarea name='description' placeholder='РћРїРёСЃР°РЅРёРµ (РѕРїС†РёРѕРЅР°Р»СЊРЅРѕ)' rows='3'></textarea>"
                "<label><input type='checkbox' name='enabled' value='1' checked /> Enabled</label>"
                "<button type='submit' class='btn'>Create Giveaway</button>"
                "</form>"
            ),
            desc=f"РћРґРЅРѕРІСЂРµРјРµРЅРЅРѕ Р°РєС‚РёРІРЅРѕ РЅРµ Р±РѕР»РµРµ {GIVEAWAY_MAX_ACTIVE} СЂРѕР·С‹РіСЂС‹С€РµР№.",
        )
        + _admin_section_html(
            "Giveaways",
            (
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Title</th><th>Type</th><th>Condition</th><th>Prize</th><th>Starts</th><th>Ends</th><th>Enabled</th><th>Active</th><th>Participants</th><th>Winners</th><th>Actions</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>"
                "</div>"
            ),
        )
        + "</div>"
        + "<div class='stack'>"
        + _admin_section_html(
            "Giveaway Summary",
            (
                "<div class='meta-list'>"
                f"<div class='meta-item'><div class='k'>Total giveaways</div><div class='v'>{len(giveaways)}</div></div>"
                f"<div class='meta-item'><div class='k'>Active now</div><div class='v'>{active_now}</div></div>"
                "</div>"
            ),
        )
        + "</div>"
        + "</div>"
    )
    return _render_admin_layout(
        "VPN Admin Giveaways",
        "giveaways",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _render_admin_audit_page(
    snapshot: dict[str, Any],
    rows: list[dict[str, Any]],
    pagination: dict[str, Any] | None = None,
    q: str = "",
    action_filter: str = "all",
    msg_text: str = "",
    error_text: str = "",
) -> str:
    table_rows = ""
    for row in rows:
        details = str(row.get("details_json") or "")
        if len(details) > 240:
            details = details[:240] + "..."
        table_rows += (
            "<tr>"
            f"<td data-label='ID'>{row['id']}</td>"
            f"<td data-label='Created'>{escape(str(row.get('created_at', '-')))}</td>"
            f"<td data-label='Admin ID'>{escape(str(row.get('admin_telegram_id', 0)))}</td>"
            f"<td data-label='Action'>{escape(str(row.get('action', '')))}</td>"
            f"<td data-label='Entity'>{escape(str(row.get('entity_type', '')))}</td>"
            f"<td data-label='Entity ID'>{escape(str(row.get('entity_id', '')))}</td>"
            f"<td data-label='Path'>{escape(str(row.get('request_path', '')))}</td>"
            f"<td data-label='IP'>{escape(str(row.get('remote_addr', '')))}</td>"
            f"<td data-label='Details'><code>{escape(details)}</code></td>"
            "</tr>"
        )
    if not table_rows:
        table_rows = "<tr><td colspan='9' class='muted'>No audit rows</td></tr>"
    filters_html = (
        "<form method='get' action='/admin/audit' class='sub-form'>"
        f"<input type='text' name='q' placeholder='Search: action / entity / id / path / details / admin id' value='{escape(str(q or ''))}' />"
        "<select name='action'>"
        f"<option value='all' {'selected' if action_filter=='all' else ''}>All actions</option>"
        f"<option value='payment_approve' {'selected' if action_filter=='payment_approve' else ''}>payment_approve</option>"
        f"<option value='payment_reject' {'selected' if action_filter=='payment_reject' else ''}>payment_reject</option>"
        f"<option value='server_restart' {'selected' if action_filter=='server_restart' else ''}>server_restart</option>"
        f"<option value='server_delete' {'selected' if action_filter=='server_delete' else ''}>server_delete</option>"
        f"<option value='server_toggle_enabled' {'selected' if action_filter=='server_toggle_enabled' else ''}>server_toggle_enabled</option>"
        f"<option value='server_sync_devices' {'selected' if action_filter=='server_sync_devices' else ''}>server_sync_devices</option>"
        f"<option value='user_device_delete' {'selected' if action_filter=='user_device_delete' else ''}>user_device_delete</option>"
        "</select>"
        "<button type='submit' class='btn'>Apply</button>"
        "<a class='btn ghost' href='/admin/audit' style='text-decoration:none;'>Reset</a>"
        "</form>"
    )
    pager_html = _admin_pagination_bar(
        "/admin/audit",
        pagination or {"total_pages": 1, "page": 1, "total": len(rows)},
        {"q": q, "action": action_filter},
    )
    body = (
        _admin_page_header_html(
            "Audit Log",
            "Р–СѓСЂРЅР°Р» РґРµР№СЃС‚РІРёР№ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР° РїРѕ РєСЂРёС‚РёС‡РЅС‹Рј РѕРїРµСЂР°С†РёСЏРј: approve/reject/restart/delete Рё СЃРІСЏР·Р°РЅРЅС‹Рµ СЃРµСЂРІРµСЂРЅС‹Рµ РґРµР№СЃС‚РІРёСЏ.",
            actions_html="<a class='btn ghost' href='/admin/overview' style='text-decoration:none;'>Open overview</a>",
            icon="AL",
        )
        + _admin_section_html(
            "Audit Entries",
            (
                f"{filters_html}"
                "<div class='table-wrap stack'>"
                "<table><thead><tr><th>ID</th><th>Created</th><th>Admin ID</th><th>Action</th><th>Entity</th><th>Entity ID</th><th>Path</th><th>IP</th><th>Details</th></tr></thead>"
                f"<tbody>{table_rows}</tbody></table>"
                "</div>"
                f"{pager_html}"
            ),
            desc="РџРѕСЃС‚СЂР°РЅРёС‡РЅС‹Р№ SSR-СЃРїРёСЃРѕРє. Р”РµС‚Р°Р»Рё РѕР±СЂРµР·Р°СЋС‚СЃСЏ РІ С‚Р°Р±Р»РёС†Рµ, РїРѕР»РЅС‹Р№ JSON С…СЂР°РЅРёС‚СЃСЏ РІ Р‘Р”.",
        )
    )
    return _render_admin_layout(
        "VPN Admin Audit",
        "audit",
        snapshot["generated_at"],
        body,
        msg_text=msg_text,
        error_text=error_text,
    )


def _active_giveaway_count(db: Session, now: datetime | None = None, exclude_id: int | None = None) -> int:
    now = now or utc_now()
    base = select(Giveaway).where(Giveaway.enabled.is_(True))
    if exclude_id:
        base = base.where(Giveaway.id != int(exclude_id))
    rows = db.scalars(base).all()
    return sum(1 for g in rows if _is_giveaway_active(g, now))


def _parse_admin_dt(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        raise ValueError("Invalid datetime format, expected YYYY-MM-DDTHH:MM")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_duration(value: str) -> timedelta | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    match = re.fullmatch(r"(\d+)\s*([smhd])", raw)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    if amount <= 0:
        return None
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    return None


@app.get("/admin")
def admin_entry(request: Request):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    return RedirectResponse("/admin/overview", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if require_admin_session(request):
        return RedirectResponse("/admin/overview", status_code=303)
    return HTMLResponse(_render_admin_login_page())


@app.post("/admin/login")
async def admin_login_submit(request: Request):
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    admin_id_raw = form.get("admin_id", [""])[0].strip()
    password = form.get("password", [""])[0]
    if admin_id_raw != str(settings.admin_telegram_id) or password != settings.admin_panel_password:
        return HTMLResponse(_render_admin_login_page("РќРµРІРµСЂРЅС‹Р№ admin_id РёР»Рё РїР°СЂРѕР»СЊ"), status_code=401)

    response = RedirectResponse("/admin/overview", status_code=303)
    response.set_cookie(
        key=ADMIN_COOKIE,
        value=make_admin_session_token(settings.admin_telegram_id),
        httponly=True,
        samesite="lax",
        max_age=max(1, settings.admin_session_hours) * 3600,
    )
    return response


@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard_legacy_redirect(request: Request):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    return RedirectResponse("/admin/overview", status_code=303)


@app.get("/admin/overview", response_class=HTMLResponse)
def admin_overview_page(
    request: Request,
    msg: str = "",
    error: str = "",
    fresh: int = 0,
    db: Session = Depends(get_db),
):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    snapshot = _build_admin_snapshot_cached(
        db,
        include_runtime_checks=True,
        force_refresh=bool(int(fresh or 0)),
    )
    return HTMLResponse(_render_admin_overview_page(snapshot, msg_text=msg, error_text=error))


@app.get("/admin/servers", response_class=HTMLResponse)
def admin_servers_page(
    request: Request,
    msg: str = "",
    error: str = "",
    live: int = 1,
    fresh: int = 0,
    db: Session = Depends(get_db),
):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    snapshot = _build_admin_servers_snapshot_cached(
        db,
        include_runtime_checks=bool(int(live or 0)),
        force_refresh=bool(int(fresh or 0)),
    )
    return HTMLResponse(_render_admin_servers_page(snapshot, msg_text=msg, error_text=error))


@app.get("/admin/server/{server_id}", response_class=HTMLResponse)
def admin_server_detail_page(
    server_id: int,
    request: Request,
    msg: str = "",
    error: str = "",
    live: int = 1,
    fresh: int = 0,
    db: Session = Depends(get_db),
):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    snapshot = _build_server_detail_snapshot_cached(
        db,
        server_id=server_id,
        include_runtime_checks=bool(int(live or 0)),
        force_refresh=bool(int(fresh or 0)),
    )
    return HTMLResponse(_render_admin_server_detail_page(snapshot, msg_text=msg, error_text=error))


@app.get("/admin/configs", response_class=HTMLResponse)
def admin_configs_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower()
    if status_filter not in {"all", "active", "revoked"}:
        status_filter = "all"
    page = _parse_page(request.query_params.get("page"), 1)
    table_rows, pagination = _query_admin_configs_page(db, q=q, status_filter=status_filter, page=page, page_size=50)
    snapshot = _admin_generated_snapshot()
    return HTMLResponse(
        _render_admin_configs_page(
            snapshot,
            msg_text=msg,
            error_text=error,
            table_rows=table_rows,
            pagination=pagination,
            q=q,
            status_filter=status_filter,
        )
    )


@app.get("/admin/subscriptions", response_class=HTMLResponse)
def admin_subscriptions_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower()
    if status_filter not in {"all", "active", "expired"}:
        status_filter = "all"
    page = _parse_page(request.query_params.get("page"), 1)
    table_rows, pagination = _query_admin_subscriptions_page(db, q=q, status_filter=status_filter, page=page, page_size=50)
    snapshot = _admin_generated_snapshot()
    return HTMLResponse(
        _render_admin_subscriptions_page(
            snapshot,
            msg_text=msg,
            error_text=error,
            table_rows=table_rows,
            pagination=pagination,
            q=q,
            status_filter=status_filter,
        )
    )


@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower()
    if status_filter not in {"all", "active", "expired", "no_sub", "blocked"}:
        status_filter = "all"
    page = _parse_page(request.query_params.get("page"), 1)
    table_rows, pagination = _query_admin_users_page(db, q=q, status_filter=status_filter, page=page, page_size=50)
    snapshot = _build_admin_users_summary_snapshot(db)
    return HTMLResponse(
        _render_admin_users_page(
            snapshot,
            msg_text=msg,
            error_text=error,
            table_rows=table_rows,
            pagination=pagination,
            q=q,
            status_filter=status_filter,
        )
    )


@app.get("/admin/user/{telegram_id}/devices", response_class=HTMLResponse)
def admin_user_devices_page(
    telegram_id: int,
    request: Request,
    msg: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    user_row, device_rows = _query_admin_user_devices(db, telegram_id)
    if not user_row:
        return _admin_redirect(error="User not found", target="/admin/users")
    snapshot = _admin_generated_snapshot()
    return HTMLResponse(
        _render_admin_user_devices_page(
            snapshot,
            user_row,
            device_rows,
            msg_text=msg,
            error_text=error,
        )
    )


@app.get("/admin/payments", response_class=HTMLResponse)
def admin_payments_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower()
    if status_filter not in {"all", "active", "paid", "rejected"}:
        status_filter = "all"
    kind_filter = str(request.query_params.get("kind") or "all").strip() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    table_rows, pagination = _query_admin_payments_page(
        db,
        q=q,
        status_filter=status_filter,
        kind_filter=kind_filter,
        page=page,
        page_size=50,
    )
    snapshot = _admin_generated_snapshot()
    return HTMLResponse(
        _render_admin_payments_page(
            snapshot,
            msg_text=msg,
            error_text=error,
            table_rows=table_rows,
            pagination=pagination,
            q=q,
            status_filter=status_filter,
            kind_filter=kind_filter,
        )
    )


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    snapshot = _admin_generated_snapshot()
    return HTMLResponse(_render_admin_settings_page(snapshot, msg_text=msg, error_text=error))


@app.post("/admin/settings/update")
async def admin_settings_update(request: Request):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    form = await request.form()

    int_fields = {
        "api_port",
        "admin_telegram_id",
        "giveaway_admin_telegram_id",
        "admin_session_hours",
        "subscription_price_rub",
        "subscription_days_per_month",
        "min_topup_rub",
        "max_topup_rub",
        "welcome_bonus_days",
        "referral_bonus_percent",
        "payments_notify_chat_id",
        "crypto_pay_invoice_expires_in",
        "platega_payment_method",
        "platega_payment_method_crypto",
        "platega_payment_method_card",
        "platega_payment_method_sbp",
        "MAX_ACTIVE_CONFIGS_PER_USER",
    }
    secret_fields = {
        "bot_token",
        "internal_api_token",
        "admin_panel_password",
        "admin_session_secret",
        "crypto_pay_api_token",
        "yoomoney_notification_secret",
        "platega_merchant_id",
        "platega_api_key",
    }
    allowed_fields = {
        "database_url",
        "api_host",
        "api_port",
        "api_base_url",
        "public_api_base_url",
        "admin_telegram_id",
        "giveaway_admin_telegram_id",
        "admin_session_hours",
        "admin_panel_password",
        "admin_session_secret",
        "internal_api_token",
        "subscription_price_rub",
        "subscription_days_per_month",
        "payment_gateway",
        "min_topup_rub",
        "max_topup_rub",
        "welcome_bonus_days",
        "referral_bonus_percent",
        "payments_notify_chat_id",
        "crypto_pay_api_token",
        "crypto_pay_base_url",
        "crypto_pay_accepted_assets",
        "crypto_pay_invoice_expires_in",
        "yoomoney_receiver",
        "yoomoney_notification_secret",
        "yoomoney_quickpay_form",
        "yoomoney_payment_type",
        "yoomoney_success_url",
        "platega_merchant_id",
        "platega_api_key",
        "platega_base_url",
        "platega_payment_method",
        "platega_payment_method_crypto",
        "platega_payment_method_card",
        "platega_payment_method_sbp",
        "platega_return_url",
        "platega_failed_url",
        "welcome_channel_url",
        "welcome_channel_chat",
        "happ_import_url_template",
        "happ_download_url",
        "bot_token",
        "MAX_ACTIVE_CONFIGS_PER_USER",
    }

    updates_env: dict[str, str] = {}
    try:
        for key in allowed_fields:
            if key not in form:
                continue
            raw = str(form.get(key) or "")
            if key in secret_fields and raw.strip() == "":
                continue
            if key in int_fields:
                try:
                    val = int(str(raw).strip())
                except Exception as exc:
                    raise ValueError(f"{key} must be numeric") from exc
                if key == "MAX_ACTIVE_CONFIGS_PER_USER":
                    global MAX_ACTIVE_CONFIGS_PER_USER
                    MAX_ACTIVE_CONFIGS_PER_USER = max(1, val)
                else:
                    setattr(settings, key, val)
                updates_env[key.upper()] = str(val)
            else:
                setattr(settings, key, raw)
                updates_env[key.upper()] = str(raw)
    except Exception as exc:
        return _admin_redirect(error=str(exc), target="/admin/settings")

    if updates_env:
        _save_env_updates(updates_env)
    return _admin_redirect(msg="Settings updated", target="/admin/settings")


@app.get("/admin/promos", response_class=HTMLResponse)
def admin_promos_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    uses_q = str(request.query_params.get("uses_q") or "").strip()
    uses_page = _parse_page(request.query_params.get("uses_page"), 1)
    snapshot = _admin_generated_snapshot()
    promos_raw = db.scalars(select(PromoCode).order_by(PromoCode.created_at.desc(), PromoCode.id.desc())).all()
    usage_map: dict[int, int] = {}
    promo_ids = [int(p.id) for p in promos_raw if int(p.id or 0) > 0]
    if promo_ids:
        usage_rows = db.execute(
            select(PromoRedemption.promo_code_id, func.count(PromoRedemption.id))
            .where(PromoRedemption.promo_code_id.in_(promo_ids))
            .group_by(PromoRedemption.promo_code_id)
        ).all()
        usage_map = {int(pid): int(count or 0) for pid, count in usage_rows}
    promo_rows: list[dict[str, Any]] = []
    for promo in promos_raw:
        promo_rows.append(
            {
                "id": promo.id,
                "code": promo.code,
                "kind": promo.kind,
                "value_int": int(promo.value_int or 0),
                "max_uses_total": int(promo.max_uses_total or 0),
                "max_uses_per_user": int(promo.max_uses_per_user or 0),
                "starts_at": _fmt_dt(promo.starts_at),
                "ends_at": _fmt_dt(promo.ends_at),
                "enabled": bool(promo.enabled),
                "uses_total": int(usage_map.get(int(promo.id), 0)),
            }
        )
    recent_rows, uses_pagination = _query_admin_promo_uses_page(db, q=uses_q, page=uses_page, page_size=100)
    return HTMLResponse(
        _render_admin_promos_page(
            snapshot,
            promo_rows,
            recent_rows,
            msg_text=msg,
            error_text=error,
            uses_q=uses_q,
            uses_pagination=uses_pagination,
        )
    )


@app.get("/admin/giveaways", response_class=HTMLResponse)
def admin_giveaways_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    snapshot = _admin_generated_snapshot()
    giveaways = _query_admin_giveaways(db)
    return HTMLResponse(_render_admin_giveaways_page(snapshot, giveaways, msg_text=msg, error_text=error))


@app.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_page(request: Request, msg: str = "", error: str = "", db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    q = str(request.query_params.get("q") or "").strip()
    action_filter = str(request.query_params.get("action") or "all").strip().lower() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    rows, pagination = _query_admin_audit_page(db, q=q, action_filter=action_filter, page=page, page_size=100)
    snapshot = {"generated_at": _fmt_dt(utc_now())}
    return HTMLResponse(
        _render_admin_audit_page(
            snapshot,
            rows,
            pagination=pagination,
            q=q,
            action_filter=action_filter,
            msg_text=msg,
            error_text=error,
        )
    )


@app.get("/admin/api/overview")
def admin_overview_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    live = int(request.query_params.get("live") or 0)
    fresh = int(request.query_params.get("fresh") or 0)
    return _build_admin_snapshot_cached(
        db,
        include_runtime_checks=bool(live),
        force_refresh=bool(fresh),
    )


@app.get("/admin/api/server/{server_id}/check")
def admin_server_check(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    runtime = _check_server_runtime(server)
    _record_load_sample(db, server.id, runtime)
    db.commit()
    return runtime


@app.get("/admin/api/servers/runtime-live")
def admin_servers_runtime_live(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    fresh = int(request.query_params.get("fresh") or 0)
    snapshot = _build_admin_servers_snapshot_cached(
        db,
        include_runtime_checks=True,
        force_refresh=bool(fresh),
    )
    legacy_items = [
        {
            "id": int(server.get("id", 0)),
            "enabled": bool(server.get("enabled", False)),
            "runtime": dict(server.get("runtime") or {}),
        }
        for server in list(snapshot.get("servers") or [])
    ]
    # Keep legacy "items" key for backward compatibility with old admin scripts.
    snapshot["items"] = legacy_items
    return snapshot


def _admin_api_page_size(raw: Any, default: int = 50, max_value: int = 200) -> int:
    try:
        value = int(str(raw or "").strip())
    except Exception:
        value = int(default)
    return max(1, min(int(max_value), value))


@app.get("/admin/api/servers")
def admin_servers_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    live = int(request.query_params.get("live") or 0)
    fresh = int(request.query_params.get("fresh") or 0)
    snapshot = _build_admin_servers_snapshot_cached(
        db,
        include_runtime_checks=bool(live),
        force_refresh=bool(fresh),
    )
    snapshot["defaults"] = _admin_server_defaults(db)
    return snapshot


@app.get("/admin/api/servers/{server_id}")
def admin_server_detail_api(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    live = int(request.query_params.get("live") or 1)
    fresh = int(request.query_params.get("fresh") or 0)
    return _build_server_detail_snapshot_cached(
        db,
        server_id=server_id,
        include_runtime_checks=bool(live),
        force_refresh=bool(fresh),
    )


@app.get("/admin/api/users")
def admin_users_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    page_size = _admin_api_page_size(request.query_params.get("page_size"), default=50, max_value=200)
    rows, pagination = _query_admin_users_page(
        db,
        q=q,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": rows,
        "pagination": pagination,
        "filters": {
            "q": q,
            "status": status_filter,
        },
    }


@app.get("/admin/api/users/{telegram_id}/devices")
def admin_user_devices_api(telegram_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_row, devices = _query_admin_user_devices(db, telegram_id)
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "generated_at": _fmt_dt(utc_now()),
        "user": user_row,
        "items": devices,
    }


@app.get("/admin/api/configs")
def admin_configs_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    page_size = _admin_api_page_size(request.query_params.get("page_size"), default=50, max_value=200)
    rows, pagination = _query_admin_configs_page(
        db,
        q=q,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": rows,
        "pagination": pagination,
        "filters": {
            "q": q,
            "status": status_filter,
        },
    }


@app.get("/admin/api/subscriptions")
def admin_subscriptions_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    page_size = _admin_api_page_size(request.query_params.get("page_size"), default=50, max_value=200)
    rows, pagination = _query_admin_subscriptions_page(
        db,
        q=q,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": rows,
        "pagination": pagination,
        "filters": {
            "q": q,
            "status": status_filter,
        },
    }


@app.get("/admin/api/payments")
def admin_payments_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    q = str(request.query_params.get("q") or "").strip()
    status_filter = str(request.query_params.get("status") or "all").strip().lower() or "all"
    kind_filter = str(request.query_params.get("kind") or "all").strip().lower() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    page_size = _admin_api_page_size(request.query_params.get("page_size"), default=50, max_value=200)
    rows, pagination = _query_admin_payments_page(
        db,
        q=q,
        status_filter=status_filter,
        kind_filter=kind_filter,
        page=page,
        page_size=page_size,
    )
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": rows,
        "pagination": pagination,
        "filters": {
            "q": q,
            "status": status_filter,
            "kind": kind_filter,
        },
    }


@app.get("/admin/api/promos")
def admin_promos_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    uses_q = str(request.query_params.get("uses_q") or "").strip()
    uses_page = _parse_page(request.query_params.get("uses_page"), 1)
    uses_page_size = _admin_api_page_size(request.query_params.get("uses_page_size"), default=100, max_value=300)

    promos_raw = db.scalars(select(PromoCode).order_by(PromoCode.created_at.desc(), PromoCode.id.desc())).all()
    usage_map: dict[int, int] = {}
    promo_ids = [int(p.id) for p in promos_raw if int(p.id or 0) > 0]
    if promo_ids:
        usage_rows = db.execute(
            select(PromoRedemption.promo_code_id, func.count(PromoRedemption.id))
            .where(PromoRedemption.promo_code_id.in_(promo_ids))
            .group_by(PromoRedemption.promo_code_id)
        ).all()
        usage_map = {int(pid): int(count or 0) for pid, count in usage_rows}
    promo_rows: list[dict[str, Any]] = []
    for promo in promos_raw:
        promo_rows.append(
            {
                "id": int(promo.id),
                "code": str(promo.code or ""),
                "kind": str(promo.kind or ""),
                "value_int": int(promo.value_int or 0),
                "max_uses_total": int(promo.max_uses_total or 0),
                "max_uses_per_user": int(promo.max_uses_per_user or 0),
                "starts_at": _fmt_dt(promo.starts_at),
                "ends_at": _fmt_dt(promo.ends_at),
                "enabled": bool(promo.enabled),
                "uses_total": int(usage_map.get(int(promo.id), 0)),
            }
        )

    uses_rows, uses_pagination = _query_admin_promo_uses_page(
        db,
        q=uses_q,
        page=uses_page,
        page_size=uses_page_size,
    )
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": promo_rows,
        "uses": {
            "items": uses_rows,
            "pagination": uses_pagination,
            "filters": {"q": uses_q},
        },
    }


@app.get("/admin/api/giveaways")
def admin_giveaways_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": _query_admin_giveaways(db),
    }


@app.get("/admin/api/audit")
def admin_audit_api(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    q = str(request.query_params.get("q") or "").strip()
    action_filter = str(request.query_params.get("action") or "all").strip().lower() or "all"
    page = _parse_page(request.query_params.get("page"), 1)
    page_size = _admin_api_page_size(request.query_params.get("page_size"), default=100, max_value=300)
    rows, pagination = _query_admin_audit_page(
        db,
        q=q,
        action_filter=action_filter,
        page=page,
        page_size=page_size,
    )
    actions = db.scalars(select(AdminAuditLog.action).distinct().order_by(AdminAuditLog.action.asc())).all()
    return {
        "generated_at": _fmt_dt(utc_now()),
        "items": rows,
        "pagination": pagination,
        "filters": {
            "q": q,
            "action": action_filter,
            "available_actions": [str(item or "") for item in actions if str(item or "").strip()],
        },
    }


@app.get("/admin/api/settings")
def admin_settings_api(request: Request, db: Session = Depends(get_db)):
    _ = db
    if not require_admin_session(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "generated_at": _fmt_dt(utc_now()),
        "values": {
            "database_url": settings.database_url,
            "api_host": settings.api_host,
            "api_port": int(settings.api_port),
            "api_base_url": settings.api_base_url,
            "public_api_base_url": settings.public_api_base_url,
            "admin_telegram_id": int(settings.admin_telegram_id),
            "giveaway_admin_telegram_id": int(settings.giveaway_admin_telegram_id or 0),
            "admin_session_hours": int(settings.admin_session_hours),
            "subscription_price_rub": int(settings.subscription_price_rub),
            "subscription_days_per_month": int(settings.subscription_days_per_month),
            "welcome_bonus_days": int(settings.welcome_bonus_days),
            "referral_bonus_percent": int(settings.referral_bonus_percent),
            "max_active_configs_per_user": int(MAX_ACTIVE_CONFIGS_PER_USER),
            "payment_gateway": settings.payment_gateway,
            "min_topup_rub": int(settings.min_topup_rub),
            "max_topup_rub": int(settings.max_topup_rub),
            "payments_notify_chat_id": int(settings.payments_notify_chat_id),
            "crypto_pay_base_url": settings.crypto_pay_base_url,
            "crypto_pay_accepted_assets": settings.crypto_pay_accepted_assets,
            "crypto_pay_invoice_expires_in": int(settings.crypto_pay_invoice_expires_in),
            "yoomoney_receiver": settings.yoomoney_receiver,
            "yoomoney_quickpay_form": settings.yoomoney_quickpay_form,
            "yoomoney_payment_type": settings.yoomoney_payment_type,
            "yoomoney_success_url": settings.yoomoney_success_url,
            "platega_base_url": settings.platega_base_url,
            "platega_payment_method": int(settings.platega_payment_method),
            "platega_payment_method_card": int(settings.platega_payment_method_card),
            "platega_payment_method_sbp": int(settings.platega_payment_method_sbp),
            "platega_payment_method_crypto": int(settings.platega_payment_method_crypto),
            "platega_return_url": settings.platega_return_url,
            "platega_failed_url": settings.platega_failed_url,
            "welcome_channel_url": settings.welcome_channel_url,
            "welcome_channel_chat": settings.welcome_channel_chat,
            "happ_import_url_template": settings.happ_import_url_template,
            "happ_download_url": settings.happ_download_url,
        },
        "masked": {
            "admin_panel_password": _mask_secret(settings.admin_panel_password),
            "admin_session_secret": _mask_secret(settings.admin_session_secret),
            "internal_api_token": _mask_secret(settings.internal_api_token),
            "crypto_pay_api_token": _mask_secret(settings.crypto_pay_api_token),
            "yoomoney_notification_secret": _mask_secret(settings.yoomoney_notification_secret),
            "platega_merchant_id": _mask_secret(settings.platega_merchant_id),
            "platega_api_key": _mask_secret(settings.platega_api_key),
            "bot_token": _mask_secret(settings.bot_token),
        },
    }


@app.post("/admin/action/promo/save")
async def admin_save_promo(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    code = _normalize_promo_code(form.get("code", [""])[0])
    kind = str(form.get("kind", [""])[0]).strip()
    value_raw = str(form.get("value_int", [""])[0]).strip()
    if len(code) < 2:
        return _admin_redirect(error="Promo code is required", target="/admin/promos")
    if kind not in PROMO_KINDS:
        return _admin_redirect(error="Invalid promo kind", target="/admin/promos")
    if not value_raw.lstrip("-").isdigit():
        return _admin_redirect(error="Value must be numeric", target="/admin/promos")
    value_int = int(value_raw)
    if kind == PROMO_KIND_TOPUP_DISCOUNT:
        value_int = max(1, min(95, value_int))
    elif kind in (PROMO_KIND_BALANCE, PROMO_KIND_SUBSCRIPTION_DAYS):
        value_int = max(1, value_int)

    max_total_raw = str(form.get("max_uses_total", [""])[0]).strip() or "0"
    max_per_user_raw = str(form.get("max_uses_per_user", [""])[0]).strip() or "1"
    if not max_total_raw.lstrip("-").isdigit() or not max_per_user_raw.lstrip("-").isdigit():
        return _admin_redirect(error="Usage limits must be numeric", target="/admin/promos")
    max_total = max(0, int(max_total_raw))
    max_per_user = max(0, int(max_per_user_raw))

    try:
        starts_at = _parse_admin_dt(form.get("starts_at", [""])[0])
        ends_at = _parse_admin_dt(form.get("ends_at", [""])[0])
    except ValueError as exc:
        return _admin_redirect(error=str(exc), target="/admin/promos")
    if starts_at and ends_at and starts_at >= ends_at:
        return _admin_redirect(error="starts_at must be less than ends_at", target="/admin/promos")

    enabled = form.get("enabled", [""])[0] == "1"
    promo = db.scalar(select(PromoCode).where(PromoCode.code == code))
    created = False
    if not promo:
        promo = PromoCode(code=code)
        db.add(promo)
        created = True
    promo.kind = kind
    promo.value_int = value_int
    promo.max_uses_total = max_total
    promo.max_uses_per_user = max_per_user
    promo.starts_at = starts_at
    promo.ends_at = ends_at
    promo.enabled = enabled
    db.commit()
    action = "created" if created else "updated"
    return _admin_redirect(msg=f"Promo {code} {action}", target="/admin/promos")


@app.post("/admin/action/promo/{promo_id}/toggle")
def admin_toggle_promo(promo_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    promo = db.scalar(select(PromoCode).where(PromoCode.id == promo_id))
    if not promo:
        return _admin_redirect(error="Promo not found", target="/admin/promos")
    promo.enabled = not bool(promo.enabled)
    db.commit()
    return _admin_redirect(msg=f"Promo {promo.code} {'enabled' if promo.enabled else 'disabled'}", target="/admin/promos")


@app.post("/admin/action/promo/{promo_id}/delete")
def admin_archive_promo(promo_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    promo = db.scalar(select(PromoCode).where(PromoCode.id == promo_id))
    if not promo:
        _audit_log(db, request, "promo_delete", "promo", promo_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Promo not found", target="/admin/promos")
    promo.enabled = False
    _audit_log(db, request, "promo_delete", "promo", promo_id, outcome="ok", code=promo.code)
    db.commit()
    return _admin_redirect(msg=f"Promo {promo.code} archived", target="/admin/promos")


@app.post("/admin/action/giveaway/save")
async def admin_save_giveaway(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    title = str(form.get("title", [""])[0]).strip()
    description = str(form.get("description", [""])[0]).strip()
    prize = str(form.get("prize", [""])[0]).strip()
    kind = str(form.get("kind", [""])[0]).strip()
    duration_raw = str(form.get("duration", [""])[0]).strip()
    if len(title) < 2:
        return _admin_redirect(error="Title is required", target="/admin/giveaways")
    if kind not in GIVEAWAY_KINDS:
        return _admin_redirect(error="Invalid giveaway kind", target="/admin/giveaways")
    try:
        starts_at = _parse_admin_dt(form.get("starts_at", [""])[0])
    except ValueError as exc:
        return _admin_redirect(error=str(exc), target="/admin/giveaways")
    duration = _parse_duration(duration_raw)
    if duration_raw and not duration:
        return _admin_redirect(error="Invalid duration, use 1m/1h/1d", target="/admin/giveaways")
    if not starts_at:
        starts_at = utc_now()
    ends_at = starts_at + duration if duration else None
    enabled = form.get("enabled", [""])[0] == "1"
    now = utc_now()
    active_candidate = _is_giveaway_active(
        Giveaway(title=title, kind=kind, enabled=enabled, starts_at=starts_at, ends_at=ends_at),
        now,
    )
    if active_candidate and _active_giveaway_count(db, now) >= GIVEAWAY_MAX_ACTIVE:
        return _admin_redirect(
            error=f"Active giveaways limit reached ({GIVEAWAY_MAX_ACTIVE}). Disable or end one first.",
            target="/admin/giveaways",
        )
    giveaway = Giveaway(
        title=title,
        description=description or None,
        prize=prize or None,
        kind=kind,
        starts_at=starts_at,
        ends_at=ends_at,
        enabled=enabled,
    )
    db.add(giveaway)
    _audit_log(db, request, "giveaway_create", "giveaway", "", outcome="ok", title=title, kind=kind)
    db.commit()
    return _admin_redirect(msg="Giveaway created", target="/admin/giveaways")


@app.post("/admin/action/giveaway/{giveaway_id}/toggle")
def admin_toggle_giveaway(giveaway_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    giveaway = db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id))
    if not giveaway:
        _audit_log(db, request, "giveaway_toggle", "giveaway", giveaway_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Giveaway not found", target="/admin/giveaways")
    now = utc_now()
    if not giveaway.enabled:
        candidate_active = _is_giveaway_active(
            Giveaway(
                title=giveaway.title,
                kind=giveaway.kind,
                enabled=True,
                starts_at=giveaway.starts_at,
                ends_at=giveaway.ends_at,
            ),
            now,
        )
        if candidate_active and _active_giveaway_count(db, now, exclude_id=giveaway.id) >= GIVEAWAY_MAX_ACTIVE:
            return _admin_redirect(
                error=f"Active giveaways limit reached ({GIVEAWAY_MAX_ACTIVE}).",
                target="/admin/giveaways",
            )
        giveaway.enabled = True
    else:
        giveaway.enabled = False
    _audit_log(
        db,
        request,
        "giveaway_toggle",
        "giveaway",
        giveaway_id,
        outcome="ok",
        enabled=bool(giveaway.enabled),
    )
    db.commit()
    return _admin_redirect(
        msg=f"Giveaway {'enabled' if giveaway.enabled else 'disabled'}",
        target="/admin/giveaways",
    )


def _draw_giveaway(
    db: Session,
    giveaway: Giveaway,
    reason: str,
    exclude_existing: bool = True,
) -> tuple[list[dict[str, Any]], str | None]:
    now = utc_now()
    if giveaway.ends_at and now < giveaway.ends_at:
        return [], "Giveaway is not ended yet"
    exclude_ids: set[int] = set()
    if exclude_existing:
        existing = db.scalars(
            select(GiveawayWinner.user_id).where(
                GiveawayWinner.giveaway_id == giveaway.id,
            )
        ).all()
        exclude_ids = {int(x) for x in existing if x}
    winner = _pick_giveaway_winner(db, giveaway, exclude_user_ids=exclude_ids)
    if not winner:
        _notify_giveaway_winners(giveaway, [], SUPPORT_URL)
        return [], None
    db.add(
        GiveawayWinner(
            giveaway_id=giveaway.id,
            user_id=winner.id,
            reason=reason,
            is_active=True,
        )
    )
    db.commit()
    winners = _giveaway_winners_summary(db, giveaway.id)
    _notify_giveaway_winners(giveaway, winners, SUPPORT_URL)
    return winners, None


@app.post("/admin/action/giveaway/{giveaway_id}/draw")
def admin_draw_giveaway(giveaway_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    giveaway = db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id))
    if not giveaway:
        _audit_log(db, request, "giveaway_draw", "giveaway", giveaway_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Giveaway not found", target="/admin/giveaways")
    winners, error = _draw_giveaway(db, giveaway, reason="draw", exclude_existing=False)
    if error:
        _audit_log(db, request, "giveaway_draw", "giveaway", giveaway_id, outcome="error", error=error)
        db.commit()
        return _admin_redirect(error=error, target="/admin/giveaways")
    _audit_log(db, request, "giveaway_draw", "giveaway", giveaway_id, outcome="ok", winners=len(winners))
    db.commit()
    if not winners:
        return _admin_redirect(msg="No winners found (no participants). Admin notified.", target="/admin/giveaways")
    return _admin_redirect(msg="Winners notified", target="/admin/giveaways")


@app.post("/admin/action/giveaway/{giveaway_id}/end")
def admin_end_giveaway(giveaway_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    giveaway = db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id))
    if not giveaway:
        _audit_log(db, request, "giveaway_end", "giveaway", giveaway_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Giveaway not found", target="/admin/giveaways")
    giveaway.ends_at = utc_now()
    giveaway.enabled = False
    db.commit()
    winners, error = _draw_giveaway(db, giveaway, reason="end", exclude_existing=False)
    if error:
        _audit_log(db, request, "giveaway_end", "giveaway", giveaway_id, outcome="error", error=error)
        db.commit()
        return _admin_redirect(error=error, target="/admin/giveaways")
    _audit_log(db, request, "giveaway_end", "giveaway", giveaway_id, outcome="ok", winners=len(winners))
    db.commit()
    if not winners:
        return _admin_redirect(msg="Giveaway ended. No winners (no participants). Admin notified.", target="/admin/giveaways")
    return _admin_redirect(msg="Giveaway ended and winners notified", target="/admin/giveaways")


@app.post("/admin/action/giveaway/{giveaway_id}/reroll")
def admin_reroll_giveaway(giveaway_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    giveaway = db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id))
    if not giveaway:
        _audit_log(db, request, "giveaway_reroll", "giveaway", giveaway_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Giveaway not found", target="/admin/giveaways")
    # deactivate current winners
    for winner in db.scalars(
        select(GiveawayWinner).where(GiveawayWinner.giveaway_id == giveaway.id, GiveawayWinner.is_active.is_(True))
    ).all():
        winner.is_active = False
    db.commit()
    winners, error = _draw_giveaway(db, giveaway, reason="reroll", exclude_existing=True)
    if error:
        _audit_log(db, request, "giveaway_reroll", "giveaway", giveaway_id, outcome="error", error=error)
        db.commit()
        return _admin_redirect(error=error, target="/admin/giveaways")
    _audit_log(db, request, "giveaway_reroll", "giveaway", giveaway_id, outcome="ok", winners=len(winners))
    db.commit()
    if not winners:
        return _admin_redirect(msg="Reroll complete. No eligible winners.", target="/admin/giveaways")
    return _admin_redirect(msg="Reroll complete", target="/admin/giveaways")


@app.post("/admin/action/giveaway/{giveaway_id}/delete")
def admin_delete_giveaway(giveaway_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    giveaway = db.scalar(select(Giveaway).where(Giveaway.id == giveaway_id))
    if not giveaway:
        _audit_log(db, request, "giveaway_delete", "giveaway", giveaway_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Giveaway not found", target="/admin/giveaways")
    _audit_log(db, request, "giveaway_delete", "giveaway", giveaway_id, outcome="ok", title=giveaway.title)
    db.delete(giveaway)
    db.commit()
    return _admin_redirect(msg="Giveaway deleted", target="/admin/giveaways")


@app.post("/admin/action/server/{server_id}/update")
async def admin_update_server(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        return _admin_redirect(error="Server not found", target="/admin/servers")

    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    name = str(form.get("name", [""])[0]).strip()
    protocol_raw = str(form.get("protocol", [server.protocol])[0]).strip().lower()
    host = str(form.get("host", [""])[0]).strip()
    port_raw = str(form.get("port", [""])[0]).strip()
    sni = str(form.get("sni", [""])[0]).strip()
    public_key = str(form.get("public_key", [""])[0]).strip()
    short_id = str(form.get("short_id", [""])[0]).strip()
    fingerprint = str(form.get("fingerprint", [""])[0]).strip() or "chrome"
    hy2_alpn = str(form.get("hy2_alpn", [server.hy2_alpn or "h3"])[0]).strip() or "h3"
    hy2_obfs = str(form.get("hy2_obfs", [server.hy2_obfs or ""])[0]).strip()
    hy2_obfs_password = str(form.get("hy2_obfs_password", [server.hy2_obfs_password or ""])[0]).strip()
    hy2_insecure = form.get("hy2_insecure", [""])[0] == "1"
    ssh_host = str(form.get("ssh_host", [""])[0]).strip()
    ssh_port_raw = str(form.get("ssh_port", [""])[0]).strip()
    ssh_user = str(form.get("ssh_user", [""])[0]).strip()
    ssh_key_path = str(form.get("ssh_key_path", [""])[0]).strip()
    remote_add_script = str(form.get("remote_add_script", [""])[0]).strip()
    remote_remove_script = str(form.get("remote_remove_script", [""])[0]).strip()
    enabled = form.get("enabled", [""])[0] == "1"

    target = f"/admin/server/{server_id}"
    protocol = protocol_raw if protocol_raw in SERVER_PROTOCOLS else SERVER_PROTOCOL_VLESS_REALITY
    old_protocol = server_protocol(server)
    if old_protocol != protocol:
        active_on_server = _active_configs_count_for_server(db, server_id)
        if active_on_server > 0:
            return _admin_redirect(
                error=(
                    "Cannot change protocol while server has active configs "
                    f"({active_on_server}). Revoke configs or create a new server."
                ),
                target=target,
            )
    if not name or not host or not sni:
        return _admin_redirect(error="name/host/sni are required", target=target)
    if protocol == SERVER_PROTOCOL_VLESS_REALITY and (not public_key or not short_id):
        return _admin_redirect(error="public_key/short_id are required for vless_reality", target=target)
    if not port_raw.isdigit() or not ssh_port_raw.isdigit():
        return _admin_redirect(error="port and ssh_port must be numeric", target=target)
    port = int(port_raw)
    ssh_port = int(ssh_port_raw)
    if port <= 0 or port > 65535 or ssh_port <= 0 or ssh_port > 65535:
        return _admin_redirect(error="port and ssh_port must be in range 1..65535", target=target)
    if not ssh_host or not ssh_user or not ssh_key_path:
        return _admin_redirect(error="ssh_host/ssh_user/ssh_key_path are required", target=target)
    if protocol == SERVER_PROTOCOL_HYSTERIA2:
        if not remote_add_script or remote_add_script == DEFAULT_VLESS_ADD_SCRIPT:
            remote_add_script = DEFAULT_HYSTERIA2_ADD_SCRIPT
        if not remote_remove_script or remote_remove_script == DEFAULT_VLESS_REMOVE_SCRIPT:
            remote_remove_script = DEFAULT_HYSTERIA2_REMOVE_SCRIPT
    else:
        if not remote_add_script or remote_add_script == DEFAULT_HYSTERIA2_ADD_SCRIPT:
            remote_add_script = DEFAULT_VLESS_ADD_SCRIPT
        if not remote_remove_script or remote_remove_script == DEFAULT_HYSTERIA2_REMOVE_SCRIPT:
            remote_remove_script = DEFAULT_VLESS_REMOVE_SCRIPT
    if not remote_add_script or not remote_remove_script:
        return _admin_redirect(error="remote scripts are required", target=target)

    duplicate = db.scalar(select(VpnServer).where(VpnServer.name == name, VpnServer.id != server_id))
    if duplicate:
        return _admin_redirect(error=f"Server name '{name}' is already used", target=target)

    server.name = name
    server.protocol = protocol
    server.host = host
    server.port = port
    server.sni = sni
    server.public_key = public_key if protocol == SERVER_PROTOCOL_VLESS_REALITY else (public_key or "-")
    server.short_id = short_id if protocol == SERVER_PROTOCOL_VLESS_REALITY else (short_id or "-")
    server.fingerprint = fingerprint
    server.hy2_alpn = hy2_alpn
    server.hy2_obfs = hy2_obfs or None
    server.hy2_obfs_password = hy2_obfs_password or None
    server.hy2_insecure = bool(hy2_insecure)
    server.enabled = enabled
    server.ssh_host = ssh_host
    server.ssh_port = ssh_port
    server.ssh_user = ssh_user
    server.ssh_key_path = ssh_key_path
    server.remote_add_script = remote_add_script
    server.remote_remove_script = remote_remove_script
    db.commit()
    return _admin_redirect(msg=f"Server {server.name} updated", target=target)


@app.post("/admin/action/server/{server_id}/sync-devices")
def admin_sync_server_devices(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        _audit_log(db, request, "server_sync_devices", "server", server_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Server not found", target="/admin/servers")
    result = _sync_server_with_active_devices(
        db,
        server_id=server_id,
        max_seconds=30.0,
        per_add_timeout_seconds=4.0,
    )
    msg = (
        f"Sync done: created={result['created']}, existing={result['existing']}, "
        f"skipped_inactive={result['skipped_inactive']}, errors={len(result['errors'])}"
    )
    if result.get("timed_out"):
        msg += ", timeout reached"
    if result.get("errors"):
        _audit_log(
            db,
            request,
            "server_sync_devices",
            "server",
            server_id,
            outcome="partial_error",
            created=result["created"],
            existing=result["existing"],
            skipped_inactive=result["skipped_inactive"],
            errors_count=len(result["errors"]),
            timed_out=bool(result.get("timed_out")),
        )
        db.commit()
        return _admin_redirect(
            msg=msg,
            error=f"First error: {result['errors'][0]}",
            target=f"/admin/server/{server_id}",
        )
    _audit_log(
        db,
        request,
        "server_sync_devices",
        "server",
        server_id,
        outcome="ok",
        created=result["created"],
        existing=result["existing"],
        skipped_inactive=result["skipped_inactive"],
        errors_count=len(result["errors"]),
        timed_out=bool(result.get("timed_out")),
    )
    db.commit()
    return _admin_redirect(msg=msg, target=f"/admin/server/{server_id}")


@app.post("/admin/action/server/{server_id}/toggle-enabled")
def admin_toggle_server_enabled(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        _audit_log(db, request, "server_toggle_enabled", "server", server_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Server not found", target="/admin/servers")
    server.enabled = not bool(server.enabled)
    db.commit()
    if server.enabled:
        sync_result = _sync_server_with_active_devices(
            db,
            server_id=server.id,
            max_seconds=20.0,
            per_add_timeout_seconds=4.0,
        )
        msg = (
            f"Server {server.name} enabled. "
            f"Sync: created={sync_result['created']}, existing={sync_result['existing']}, "
            f"inactive={sync_result['skipped_inactive']}, errors={len(sync_result['errors'])}"
        )
        if sync_result.get("timed_out"):
            msg += ", timeout reached"
        if sync_result.get("errors"):
            _audit_log(
                db,
                request,
                "server_toggle_enabled",
                "server",
                server_id,
                outcome="enabled_sync_partial_error",
                enabled=bool(server.enabled),
                created=sync_result["created"],
                existing=sync_result["existing"],
                inactive=sync_result["skipped_inactive"],
                errors_count=len(sync_result["errors"]),
            )
            db.commit()
            return _admin_redirect(msg=msg, error=f"First sync error: {sync_result['errors'][0]}", target=f"/admin/server/{server_id}")
        _audit_log(
            db,
            request,
            "server_toggle_enabled",
            "server",
            server_id,
            outcome="ok",
            enabled=bool(server.enabled),
            created=sync_result["created"],
            existing=sync_result["existing"],
            inactive=sync_result["skipped_inactive"],
            errors_count=len(sync_result["errors"]),
        )
        db.commit()
        return _admin_redirect(msg=msg, target=f"/admin/server/{server_id}")
    _audit_log(db, request, "server_toggle_enabled", "server", server_id, outcome="ok", enabled=bool(server.enabled))
    db.commit()
    return _admin_redirect(
        msg=f"Server {server.name} {'enabled' if server.enabled else 'disabled'}",
        target=f"/admin/server/{server_id}",
    )


@app.post("/admin/action/server/{server_id}/delete")
def admin_delete_server(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        _audit_log(db, request, "server_delete", "server", server_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Server not found", target="/admin/servers")

    rows = db.scalars(select(ClientConfig).where(ClientConfig.server_id == server.id)).all()
    active_rows = [cfg for cfg in rows if bool(cfg.is_active)]
    removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
        db,
        active_rows,
        remove_timeout=90.0,
        restart_timeout=90.0,
    )
    active_failed = max(0, len(active_rows) - len(removed_ids))
    if active_failed > 0:
        first_error = errors[0] if errors else f"{active_failed} active configs were not removed"
        _audit_log(
            db,
            request,
            "server_delete",
            "server",
            server_id,
            outcome="blocked",
            server_name=server.name,
            errors_count=len(errors),
            first_error=first_error,
        )
        db.commit()
        return _admin_redirect(
            error=f"Delete blocked: failed to remove active users on node: {first_error}",
            target=f"/admin/server/{server_id}",
        )

    for cfg in rows:
        db.delete(cfg)
    samples = db.scalars(select(ServerLoadSample).where(ServerLoadSample.server_id == server.id)).all()
    for sample in samples:
        db.delete(sample)
    _audit_log(
        db,
        request,
        "server_delete",
        "server",
        server_id,
        outcome="ok",
        server_name=server.name,
        configs_deleted=len(rows),
        samples_deleted=len(samples),
        warnings_count=len(warnings),
        first_warning=warnings[0] if warnings else "",
    )
    db.delete(server)
    db.commit()
    if warnings:
        return _admin_redirect(
            msg=f"Server {server.name} deleted",
            error=f"Warning: {warnings[0]}",
            target="/admin/servers",
        )
    return _admin_redirect(msg=f"Server {server.name} deleted", target="/admin/servers")


@app.post("/admin/action/server/{server_id}/restart")
def admin_restart_server(server_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    server = db.scalar(select(VpnServer).where(VpnServer.id == server_id))
    if not server:
        _audit_log(db, request, "server_restart", "server", server_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Server not found", target="/admin/servers")
    referer = str(request.headers.get("referer", "") or "")
    target = f"/admin/server/{server_id}" if f"/admin/server/{server_id}" in referer else "/admin/servers"
    try:
        out = restart_server_service(server, timeout=45.0, no_block=False)
    except Exception as exc:
        _audit_log(
            db,
            request,
            "server_restart",
            "server",
            server_id,
            outcome="error",
            server_name=server.name,
            error=str(exc),
        )
        db.commit()
        return _admin_redirect(error=f"Restart failed on {server.name}: {exc}", target=target)
    _audit_log(
        db,
        request,
        "server_restart",
        "server",
        server_id,
        outcome="ok",
        server_name=server.name,
        ssh_output=str(out or "ok"),
    )
    db.commit()
    return _admin_redirect(msg=f"Server {server.name} restarted ({out or 'ok'})", target=target)


@app.post("/admin/action/server/add")
async def admin_add_server_from_reality(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)

    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    name_raw = form.get("name", [""])[0].strip()
    host = form.get("host", [""])[0].strip()
    reality_block = form.get("reality_block", [""])[0]
    if not host:
        return _admin_redirect(error="Server host/IP is required", target="/admin/servers")

    try:
        public_key, short_id, sni, port = _parse_reality_block(reality_block)
    except ValueError as exc:
        return _admin_redirect(error=f"Invalid reality block: {exc}", target="/admin/servers")

    defaults = _admin_server_defaults(db)
    ssh_host = form.get("ssh_host", [""])[0].strip() or host
    ssh_user = form.get("ssh_user", [""])[0].strip() or str(defaults["ssh_user"])
    ssh_key_path = form.get("ssh_key_path", [""])[0].strip() or str(defaults["ssh_key_path"])
    ssh_port_raw = form.get("ssh_port", [""])[0].strip()
    if ssh_port_raw:
        if not ssh_port_raw.isdigit():
            return _admin_redirect(error="SSH port must be numeric", target="/admin/servers")
        ssh_port = int(ssh_port_raw)
    else:
        ssh_port = int(defaults["ssh_port"])
    if ssh_port <= 0 or ssh_port > 65535:
        return _admin_redirect(error="SSH port must be in range 1..65535", target="/admin/servers")
    if not ssh_key_path:
        return _admin_redirect(error="SSH key path is required", target="/admin/servers")

    server_name = name_raw or f"VPN-{host}"
    server = db.scalar(select(VpnServer).where(VpnServer.name == server_name))
    created = False
    if not server:
        server = VpnServer(name=server_name)
        db.add(server)
        created = True
    elif server_protocol(server) != SERVER_PROTOCOL_VLESS_REALITY:
        active_on_server = _active_configs_count_for_server(db, int(server.id))
        if active_on_server > 0:
            return _admin_redirect(
                error=(
                    f"Server '{server_name}' already exists as {server_protocol(server)} "
                    f"with {active_on_server} active configs. "
                    "Create another server name or revoke configs first."
                ),
                target="/admin/servers",
            )

    server.host = host
    server.port = port
    server.sni = sni
    server.public_key = public_key
    server.short_id = short_id
    server.fingerprint = str(defaults["fingerprint"] or "chrome")
    server.protocol = SERVER_PROTOCOL_VLESS_REALITY
    server.hy2_obfs = None
    server.hy2_obfs_password = None
    server.hy2_alpn = "h3"
    server.hy2_insecure = False
    server.enabled = True
    server.ssh_host = ssh_host
    server.ssh_port = ssh_port
    server.ssh_user = ssh_user
    server.ssh_key_path = ssh_key_path
    server.remote_add_script = DEFAULT_VLESS_ADD_SCRIPT
    server.remote_remove_script = DEFAULT_VLESS_REMOVE_SCRIPT

    db.commit()
    db.refresh(server)
    action = "created" if created else "updated"
    sync_result = _sync_server_with_active_devices(
        db,
        server_id=server.id,
        max_seconds=20.0,
        per_add_timeout_seconds=4.0,
    )
    msg = (
        f"Server {server.name} {action} (id={server.id}). "
        f"Sync: created={sync_result['created']}, existing={sync_result['existing']}, "
        f"inactive={sync_result['skipped_inactive']}, errors={len(sync_result['errors'])}"
    )
    if sync_result.get("timed_out"):
        msg += ", timeout reached"
    if sync_result.get("errors"):
        return _admin_redirect(msg=msg, error=f"First sync error: {sync_result['errors'][0]}", target="/admin/servers")
    return _admin_redirect(msg=msg, target="/admin/servers")


@app.post("/admin/action/server/add-hysteria2")
async def admin_add_hysteria2_server(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)

    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    name = str(form.get("name", [""])[0]).strip()
    host = str(form.get("host", [""])[0]).strip()
    sni = str(form.get("sni", [""])[0]).strip()
    port_raw = str(form.get("port", ["443"])[0]).strip() or "443"
    hy2_alpn = str(form.get("hy2_alpn", ["h3"])[0]).strip() or "h3"
    hy2_obfs = str(form.get("hy2_obfs", [""])[0]).strip()
    hy2_obfs_password = str(form.get("hy2_obfs_password", [""])[0]).strip()
    hy2_insecure = form.get("hy2_insecure", [""])[0] == "1"
    if not name or not host or not sni:
        return _admin_redirect(error="name/host/sni are required", target="/admin/servers")
    if not port_raw.isdigit():
        return _admin_redirect(error="port must be numeric", target="/admin/servers")
    port = int(port_raw)
    if port <= 0 or port > 65535:
        return _admin_redirect(error="port must be in range 1..65535", target="/admin/servers")

    defaults = _admin_server_defaults(db)
    ssh_host = str(form.get("ssh_host", [""])[0]).strip() or host
    ssh_user = str(form.get("ssh_user", [""])[0]).strip() or str(defaults["ssh_user"])
    ssh_key_path = str(form.get("ssh_key_path", [""])[0]).strip() or str(defaults["ssh_key_path"])
    ssh_port_raw = str(form.get("ssh_port", [""])[0]).strip()
    if ssh_port_raw:
        if not ssh_port_raw.isdigit():
            return _admin_redirect(error="ssh_port must be numeric", target="/admin/servers")
        ssh_port = int(ssh_port_raw)
    else:
        ssh_port = int(defaults["ssh_port"])
    if ssh_port <= 0 or ssh_port > 65535:
        return _admin_redirect(error="ssh_port must be in range 1..65535", target="/admin/servers")
    if not ssh_key_path:
        return _admin_redirect(error="ssh_key_path is required", target="/admin/servers")

    server = db.scalar(select(VpnServer).where(VpnServer.name == name))
    created = False
    if not server:
        server = VpnServer(name=name)
        db.add(server)
        created = True
    elif server_protocol(server) != SERVER_PROTOCOL_HYSTERIA2:
        active_on_server = _active_configs_count_for_server(db, int(server.id))
        if active_on_server > 0:
            return _admin_redirect(
                error=(
                    f"Server '{name}' already exists as {server_protocol(server)} "
                    f"with {active_on_server} active configs. "
                    "Create another server name or revoke configs first."
                ),
                target="/admin/servers",
            )
    server.name = name
    server.protocol = SERVER_PROTOCOL_HYSTERIA2
    server.host = host
    server.port = port
    server.sni = sni
    server.public_key = server.public_key or "-"
    server.short_id = server.short_id or "-"
    server.fingerprint = server.fingerprint or "chrome"
    server.hy2_alpn = hy2_alpn
    server.hy2_obfs = hy2_obfs or None
    server.hy2_obfs_password = hy2_obfs_password or None
    server.hy2_insecure = bool(hy2_insecure)
    server.enabled = True
    server.ssh_host = ssh_host
    server.ssh_port = ssh_port
    server.ssh_user = ssh_user
    server.ssh_key_path = ssh_key_path
    server.remote_add_script = DEFAULT_HYSTERIA2_ADD_SCRIPT
    server.remote_remove_script = DEFAULT_HYSTERIA2_REMOVE_SCRIPT
    db.commit()
    db.refresh(server)

    action = "created" if created else "updated"
    sync_result = _sync_server_with_active_devices(
        db,
        server_id=server.id,
        max_seconds=20.0,
        per_add_timeout_seconds=4.0,
    )
    msg = (
        f"Hysteria2 server {server.name} {action} (id={server.id}). "
        f"Sync: created={sync_result['created']}, existing={sync_result['existing']}, "
        f"inactive={sync_result['skipped_inactive']}, errors={len(sync_result['errors'])}"
    )
    if sync_result.get("timed_out"):
        msg += ", timeout reached"
    if sync_result.get("errors"):
        return _admin_redirect(msg=msg, error=f"First sync error: {sync_result['errors'][0]}", target="/admin/servers")
    return _admin_redirect(msg=msg, target="/admin/servers")


@app.post("/admin/action/config/{config_id}/delete")
def admin_delete_config(config_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    cfg = db.scalar(select(ClientConfig).where(ClientConfig.id == config_id))
    if not cfg:
        _audit_log(db, request, "config_delete", "config", config_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Config not found", target="/admin/configs")
    warnings: list[str] = []
    if cfg.is_active:
        removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
            db,
            [cfg],
            remove_timeout=90.0,
            restart_timeout=90.0,
        )
        if int(cfg.id) not in removed_ids:
            first_error = errors[0] if errors else "remote remove failed"
            _audit_log(
                db,
                request,
                "config_delete",
                "config",
                config_id,
                outcome="error",
                server_id=int(cfg.server_id or 0),
                client_uuid=str(cfg.client_uuid or ""),
                error=str(first_error),
            )
            db.commit()
            return _admin_redirect(error=f"Failed to remove config on server: {first_error}", target="/admin/configs")
    _audit_log(
        db,
        request,
        "config_delete",
        "config",
        config_id,
        outcome="ok",
        server_id=int(cfg.server_id or 0),
        telegram_id=int(cfg.user.telegram_id) if getattr(cfg, "user", None) else None,
        device_name=str(cfg.device_name or ""),
        was_active=bool(cfg.is_active),
        warnings_count=len(warnings),
        first_warning=warnings[0] if warnings else "",
    )
    db.delete(cfg)
    db.commit()
    if warnings:
        return _admin_redirect(
            msg=f"Config #{config_id} deleted",
            error=f"Warning: {warnings[0]}",
            target="/admin/configs",
        )
    return _admin_redirect(msg=f"Config #{config_id} deleted", target="/admin/configs")


@app.post("/admin/action/subscription/add")
async def admin_add_subscription(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    referer = str(request.headers.get("referer") or "")
    target = "/admin/users" if "/admin/users" in referer else "/admin/subscriptions"

    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    telegram_id_raw = form.get("telegram_id", [""])[0].strip()
    days_raw = form.get("days", [""])[0].strip()
    if not telegram_id_raw.isdigit() or not days_raw.isdigit():
        _audit_log(db, request, "subscription_add", "user", telegram_id_raw or "", outcome="invalid_input")
        db.commit()
        return _admin_redirect(error="telegram_id and days must be numeric", target=target)

    telegram_id = int(telegram_id_raw)
    days = int(days_raw)
    if telegram_id <= 0 or days <= 0 or days > 3650:
        _audit_log(
            db,
            request,
            "subscription_add",
            "user",
            telegram_id_raw or "",
            outcome="invalid_range",
            days=days_raw,
        )
        db.commit()
        return _admin_redirect(error="Invalid telegram_id or days", target=target)

    user = get_or_create_user(db, telegram_id=telegram_id)
    extend_subscription(db, user, days)
    _audit_log(
        db,
        request,
        "subscription_add",
        "user",
        telegram_id,
        outcome="ok",
        days=days,
        target=target,
    )
    db.commit()
    return _admin_redirect(msg=f"Subscription added: {telegram_id}, +{days} days", target=target)


@app.post("/admin/action/subscription/remove/{telegram_id}")
def admin_remove_subscription(telegram_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    referer = str(request.headers.get("referer") or "")
    target = "/admin/users" if "/admin/users" in referer else "/admin/subscriptions"
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        _audit_log(db, request, "subscription_remove", "user", telegram_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="User not found", target=target)

    active_configs = db.scalars(
        select(ClientConfig).where(ClientConfig.user_id == user.id, ClientConfig.is_active.is_(True))
    ).all()
    removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
        db,
        active_configs,
        remove_timeout=90.0,
        restart_timeout=90.0,
    )
    revoked = 0
    now = utc_now()
    for cfg in active_configs:
        if int(cfg.id) not in removed_ids:
            continue
        cfg.is_active = False
        cfg.revoked_at = now
        revoked += 1

    user.subscription_until = utc_now() - timedelta(seconds=1)
    db.commit()
    if errors:
        _audit_log(
            db,
            request,
            "subscription_remove",
            "user",
            telegram_id,
            outcome="partial_error",
            revoked_count=revoked,
            errors_count=len(errors),
            first_error=errors[0],
        )
        db.commit()
        return _admin_redirect(
            error=f"Subscription removed with errors: {'; '.join(errors[:3])}",
            target=target,
        )
    if warnings:
        _audit_log(
            db,
            request,
            "subscription_remove",
            "user",
            telegram_id,
            outcome="warning",
            revoked_count=revoked,
            warnings_count=len(warnings),
            first_warning=warnings[0],
        )
        db.commit()
        return _admin_redirect(
            msg=f"Subscription removed for {telegram_id}",
            error=f"Warning: {warnings[0]}",
            target=target,
        )
    _audit_log(
        db,
        request,
        "subscription_remove",
        "user",
        telegram_id,
        outcome="ok",
        revoked_count=revoked,
    )
    db.commit()
    return _admin_redirect(msg=f"Subscription removed for {telegram_id}", target=target)


def _revoke_user_active_configs(db: Session, user: User) -> tuple[int, list[str]]:
    active_configs = db.scalars(
        select(ClientConfig).where(ClientConfig.user_id == user.id, ClientConfig.is_active.is_(True))
    ).all()
    if not active_configs:
        return 0, []
    removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
        db,
        active_configs,
        remove_timeout=90.0,
        restart_timeout=90.0,
    )
    now = utc_now()
    revoked = 0
    for cfg in active_configs:
        if int(cfg.id) not in removed_ids:
            continue
        cfg.is_active = False
        cfg.revoked_at = now
        revoked += 1
    db.commit()
    return revoked, list(errors) + list(warnings)


@app.post("/admin/action/user/{telegram_id}/toggle-block")
def admin_toggle_user_block(telegram_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        _audit_log(db, request, "user_toggle_block", "user", telegram_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="User not found", target="/admin/users")
    user.is_blocked = not bool(user.is_blocked)
    action = "blocked" if user.is_blocked else "unblocked"
    _audit_log(
        db,
        request,
        "user_toggle_block",
        "user",
        telegram_id,
        outcome="ok",
        blocked=bool(user.is_blocked),
    )
    db.commit()
    return _admin_redirect(msg=f"User {telegram_id} {action}", target="/admin/users")


@app.post("/admin/action/user/{telegram_id}/revoke-configs")
def admin_revoke_user_configs(telegram_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if not user:
        _audit_log(db, request, "user_revoke_configs", "user", telegram_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="User not found", target="/admin/users")
    revoked, errors = _revoke_user_active_configs(db, user)
    if errors and revoked == 0:
        _audit_log(
            db,
            request,
            "user_revoke_configs",
            "user",
            telegram_id,
            outcome="error",
            revoked_count=revoked,
            errors_count=len(errors),
            first_error=errors[0],
        )
        db.commit()
        return _admin_redirect(error=f"Revoke failed: {errors[0]}", target="/admin/users")
    if errors:
        _audit_log(
            db,
            request,
            "user_revoke_configs",
            "user",
            telegram_id,
            outcome="partial_error",
            revoked_count=revoked,
            errors_count=len(errors),
            first_error=errors[0],
        )
        db.commit()
        return _admin_redirect(
            msg=f"Configs revoked: {revoked}",
            error=f"First error: {errors[0]}",
            target="/admin/users",
        )
    _audit_log(
        db,
        request,
        "user_revoke_configs",
        "user",
        telegram_id,
        outcome="ok",
        revoked_count=revoked,
    )
    db.commit()
    return _admin_redirect(msg=f"Configs revoked: {revoked}", target="/admin/users")


@app.post("/admin/action/user/{telegram_id}/device/delete")
async def admin_delete_user_device(telegram_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    target = f"/admin/user/{telegram_id}/devices"
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    device_name = str(form.get("device_name", [""])[0] or "").strip()
    if not device_name:
        _audit_log(db, request, "user_device_delete", "user", telegram_id, outcome="invalid_input")
        db.commit()
        return _admin_redirect(error="Device name is required", target=target)

    user = db.scalar(select(User).where(User.telegram_id == int(telegram_id)))
    if not user:
        _audit_log(db, request, "user_device_delete", "user", telegram_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="User not found", target="/admin/users")

    rows = db.scalars(
        select(ClientConfig)
        .where(ClientConfig.user_id == user.id, ClientConfig.device_name == device_name)
        .order_by(ClientConfig.created_at.desc(), ClientConfig.id.desc())
    ).all()
    if not rows:
        _audit_log(
            db,
            request,
            "user_device_delete",
            "user",
            telegram_id,
            outcome="device_not_found",
            device_name=device_name,
        )
        db.commit()
        return _admin_redirect(error="Device not found", target=target)

    deleted = 0
    active_rows = [cfg for cfg in rows if bool(cfg.is_active)]
    removed_ids, errors, warnings = _remove_active_configs_remotely_grouped(
        db,
        active_rows,
        remove_timeout=90.0,
        restart_timeout=90.0,
    )
    for cfg in rows:
        if bool(cfg.is_active) and int(cfg.id) not in removed_ids:
            continue
        db.delete(cfg)
        deleted += 1

    db.commit()
    if errors and deleted == 0:
        _audit_log(
            db,
            request,
            "user_device_delete",
            "user",
            telegram_id,
            outcome="error",
            device_name=device_name,
            deleted_count=deleted,
            rows_total=len(rows),
            errors_count=len(errors),
            first_error=errors[0],
        )
        db.commit()
        return _admin_redirect(error=f"Delete failed: {errors[0]}", target=target)
    if errors:
        _audit_log(
            db,
            request,
            "user_device_delete",
            "user",
            telegram_id,
            outcome="partial_error",
            device_name=device_name,
            deleted_count=deleted,
            rows_total=len(rows),
            errors_count=len(errors),
            first_error=errors[0],
        )
        db.commit()
        return _admin_redirect(
            msg=f"Device deleted partially: {deleted}/{len(rows)}",
            error=f"First error: {errors[0]}",
            target=target,
        )
    if warnings:
        _audit_log(
            db,
            request,
            "user_device_delete",
            "user",
            telegram_id,
            outcome="warning",
            device_name=device_name,
            deleted_count=deleted,
            rows_total=len(rows),
            warnings_count=len(warnings),
            first_warning=warnings[0],
        )
        db.commit()
        return _admin_redirect(
            msg=f"Device {device_name} deleted ({deleted} configs)",
            error=f"Warning: {warnings[0]}",
            target=target,
        )
    _audit_log(
        db,
        request,
        "user_device_delete",
        "user",
        telegram_id,
        outcome="ok",
        device_name=device_name,
        deleted_count=deleted,
    )
    db.commit()
    return _admin_redirect(msg=f"Device {device_name} deleted ({deleted} configs)", target=target)


@app.post("/admin/action/user/revoke-configs")
async def admin_revoke_user_configs_form(request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    raw_body = (await request.body()).decode("utf-8", errors="ignore")
    form = parse_qs(raw_body)
    telegram_id_raw = form.get("telegram_id", [""])[0].strip()
    if not telegram_id_raw.isdigit():
        return _admin_redirect(error="telegram_id must be numeric", target="/admin/users")
    return admin_revoke_user_configs(int(telegram_id_raw), request, db)


@app.post("/admin/action/payment/{invoice_id}/approve")
def admin_approve_payment(invoice_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    payment = db.scalar(
        select(PaymentInvoice)
        .where(PaymentInvoice.invoice_id == invoice_id)
        .options(selectinload(PaymentInvoice.user))
    )
    if not payment or not payment.user:
        _audit_log(db, request, "payment_approve", "payment", invoice_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Payment not found", target="/admin/payments")

    was_paid = payment.status == "paid"
    payment.status = "paid"
    if not payment.paid_at:
        payment.paid_at = utc_now()
    if int(payment.credited_rub or 0) <= 0:
        credit = int(payment.amount_rub or 0)
        payment.user.balance_rub = int(payment.user.balance_rub or 0) + credit
        payment.credited_rub = credit
    apply_referral_bonus(db, payment.user, payment)
    _audit_log(
        db,
        request,
        "payment_approve",
        "payment",
        invoice_id,
        outcome="ok",
        telegram_id=int(payment.user.telegram_id or 0),
        was_paid=bool(was_paid),
        amount_rub=int(payment.amount_rub or 0),
        credited_rub=int(payment.credited_rub or 0),
        status=str(payment.status or ""),
    )
    db.commit()
    if not was_paid:
        notify_payment_paid(payment.user, payment, source="admin")
    return _admin_redirect(msg=f"Payment {invoice_id} approved", target="/admin/payments")


@app.post("/admin/action/payment/{invoice_id}/reject")
def admin_reject_payment(invoice_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin_session(request):
        return RedirectResponse("/admin/login", status_code=303)
    payment = db.scalar(
        select(PaymentInvoice)
        .where(PaymentInvoice.invoice_id == invoice_id)
        .options(selectinload(PaymentInvoice.user))
    )
    if not payment or not payment.user:
        _audit_log(db, request, "payment_reject", "payment", invoice_id, outcome="not_found")
        db.commit()
        return _admin_redirect(error="Payment not found", target="/admin/payments")

    reward = db.scalar(select(ReferralReward).where(ReferralReward.payment_invoice_id == payment.id))
    if reward:
        inviter = db.scalar(select(User).where(User.id == reward.inviter_user_id))
        if inviter:
            inviter.balance_rub = max(0, int(inviter.balance_rub or 0) - int(reward.bonus_rub or 0))
        db.delete(reward)
        payment.referral_bonus_rub = 0

    credited = int(payment.credited_rub or 0)
    if credited > 0:
        payment.user.balance_rub = max(0, int(payment.user.balance_rub or 0) - credited)
        payment.credited_rub = 0

    payment.status = "rejected"
    payment.paid_at = None
    _audit_log(
        db,
        request,
        "payment_reject",
        "payment",
        invoice_id,
        outcome="ok",
        telegram_id=int(payment.user.telegram_id or 0),
        credited_rolled_back=int(credited),
        status=str(payment.status or ""),
    )
    db.commit()
    return _admin_redirect(msg=f"Payment {invoice_id} rejected", target="/admin/payments")


app.include_router(api_users)
app.include_router(api_servers)
app.include_router(api_configs)
app.include_router(api_admin)
app.include_router(api_maintenance)
app.include_router(api_payments)
app.include_router(api_promos)
app.include_router(api_giveaways)


@dataclass
class APIClient:
    base_url: str
    internal_token: str

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None):
        headers = {"x-internal-token": self.internal_token}
        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout) as client:
            resp = await client.request(method, path, json=payload)
            if resp.status_code >= 400:
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                raise RuntimeError(f"API error {resp.status_code}: {detail}")
            return resp.json()

    async def register(self, telegram_id: int, username: str | None, referrer_telegram_id: int | None = None):
        payload = {"telegram_id": telegram_id, "username": username}
        if referrer_telegram_id:
            payload["referrer_telegram_id"] = referrer_telegram_id
        return await self._request("POST", "/api/users/register", payload)

    async def get_user(self, telegram_id: int, with_stats: bool = False):
        suffix = "?with_stats=1" if with_stats else ""
        return await self._request("GET", f"/api/users/{telegram_id}{suffix}")

    async def extend(self, telegram_id: int, days: int):
        return await self._request("POST", "/api/users/extend", {"telegram_id": telegram_id, "days": days})

    async def renew_from_balance(self, telegram_id: int):
        return await self._request("POST", "/api/users/renew-from-balance", {"telegram_id": telegram_id})

    async def purchase_plan(self, telegram_id: int, plan_id: str):
        return await self._request(
            "POST",
            "/api/users/purchase-plan",
            {"telegram_id": telegram_id, "plan_id": plan_id},
        )

    async def claim_welcome_bonus(self, telegram_id: int):
        return await self._request("POST", "/api/users/claim-welcome-bonus", {"telegram_id": telegram_id})

    async def servers(self):
        return await self._request("GET", "/api/servers")

    async def servers_runtime(self):
        return await self._request("GET", "/api/servers/runtime")

    async def issue(self, telegram_id: int, server_id: int, device_name: str):
        return await self._request(
            "POST",
            "/api/configs/issue",
            {"telegram_id": telegram_id, "server_id": server_id, "device_name": device_name},
        )

    async def revoke(self, telegram_id: int, config_id: int):
        return await self._request("POST", "/api/configs/revoke", {"telegram_id": telegram_id, "config_id": config_id})

    async def create_payment(self, telegram_id: int, amount_rub: int, gateway: str | None = None):
        payload: dict[str, Any] = {"telegram_id": telegram_id, "amount_rub": amount_rub}
        if gateway:
            payload["gateway"] = gateway
        return await self._request("POST", "/api/payments/create", payload)

    async def check_payment(self, telegram_id: int, invoice_id: int):
        return await self._request("POST", "/api/payments/check", {"telegram_id": telegram_id, "invoice_id": invoice_id})

    async def list_payments(self, telegram_id: int):
        return await self._request("GET", f"/api/payments/{telegram_id}")

    async def apply_promo(self, telegram_id: int, code: str):
        return await self._request("POST", "/api/promos/apply", {"telegram_id": telegram_id, "code": code})

    async def active_giveaways(self, telegram_id: int):
        return await self._request("GET", f"/api/giveaways/active?telegram_id={int(telegram_id)}")

    async def join_giveaway(self, telegram_id: int, giveaway_id: int):
        return await self._request("POST", "/api/giveaways/join", {"telegram_id": telegram_id, "giveaway_id": giveaway_id})


class IssueConfigState(StatesGroup):
    waiting_for_device_name = State()


class PaymentCheckState(StatesGroup):
    waiting_for_invoice_id = State()


class PaymentAmountState(StatesGroup):
    waiting_for_amount_rub = State()


router = Router()
bot_api_client = APIClient(base_url=settings.api_base_url, internal_token=settings.internal_api_token)
BOT_USERNAME = ""

BTN_PROFILE = "👤 Профиль"
BTN_CONNECT = "⚡ Подключить"
BTN_SERVERS = "🗂 Серверы"
BTN_BALANCE = "💳 Баланс"
BTN_TOPUP = "💰 Пополнить"
BTN_GIVEAWAY = "🎁 Розыгрыш"
BTN_HELP = "❓ Помощь"
SUPPORT_URL = "https://t.me/trumpvpnhelp"
PRIVACY_POLICY_URL = "https://telegra.ph/Politika-konfidencialnosti-08-15-17"
TERMS_OF_USE_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10"


def _runtime_latency_text(runtime: dict[str, Any] | None) -> str:
    latency_ms = _parse_latency_ms((runtime or {}).get("vpn_latency_ms"))
    if latency_ms is None:
        return "-"
    return f"{int(round(latency_ms))} ms"


def _runtime_availability_text(runtime: dict[str, Any] | None) -> str:
    return "РґРѕСЃС‚СѓРїРµРЅ" if bool((runtime or {}).get("vpn_reachable", False)) else "РЅРµРґРѕСЃС‚СѓРїРµРЅ"



def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BTN_CONNECT, callback_data="menu:connect"),
                InlineKeyboardButton(text=BTN_BALANCE, callback_data="menu:balance"),
            ],
            [
                InlineKeyboardButton(text=BTN_PROFILE, callback_data="menu:profile"),
                InlineKeyboardButton(text=BTN_GIVEAWAY, callback_data="menu:giveaways"),
            ],
            [
                InlineKeyboardButton(text=BTN_HELP, callback_data="menu:help"),
            ],
        ]
    )


def _welcome_channel_chat_id() -> str:
    explicit_chat = str(settings.welcome_channel_chat or "").strip()
    if explicit_chat:
        if explicit_chat.startswith("@"):
            return explicit_chat
        return f"@{explicit_chat}"
    raw_url = str(settings.welcome_channel_url or "").strip()
    if "t.me/" in raw_url:
        slug = raw_url.rstrip("/").split("/")[-1].split("?")[0].strip()
        if slug:
            return f"@{slug.lstrip('@')}"
    return "@trumpxvpn"


def welcome_bonus_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџ“ў РџРѕРґРїРёСЃР°С‚СЊСЃСЏ", url=settings.welcome_channel_url)],
            [InlineKeyboardButton(text=f"вњ… РџРѕР»СѓС‡РёС‚СЊ +{settings.welcome_bonus_days} РґРЅСЏ", callback_data="welcome:check")],
            [InlineKeyboardButton(text="РџРѕР·Р¶Рµ", callback_data="welcome:skip")],
        ]
    )


async def _is_user_subscribed_to_welcome_channel(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=_welcome_channel_chat_id(), user_id=user_id)
    except Exception:
        return False
    status_value = str(getattr(member, "status", "")).strip().lower()
    return status_value not in {"left", "kicked"}


def payment_kb(pay_url: str, invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџ’і РћРїР»Р°С‚РёС‚СЊ", url=pay_url)],
            [InlineKeyboardButton(text="рџ”„ РџСЂРѕРІРµСЂРёС‚СЊ РѕРїР»Р°С‚Сѓ", callback_data=f"paycheck:{invoice_id}")],
        ]
    )


def _payment_gateways_available() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if settings.crypto_pay_api_token.strip():
        rows.append(("cryptopay", "рџ’Ћ Crypto Bot"))
    if settings.platega_merchant_id.strip() and settings.platega_api_key.strip():
        rows.append(("platega_crypto", "рџ”’Crypto"))
        rows.append(("platega_card", "рџ‡·рџ‡єРљР°СЂС‚Р°"))
        rows.append(("platega_sbp", "рџ‡·рџ‡єРЎР‘Рџ"))
    if not rows:
        # Fallback to current default; API will return clear error if not configured.
        rows.append(((settings.payment_gateway or "cryptopay").strip().lower(), "рџ’і РћРїР»Р°С‚Р°"))
    return rows


def choose_gateway_kb(amount_rub: int) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for code, title in _payment_gateways_available():
        buttons.append([InlineKeyboardButton(text=title, callback_data=f"topup:gateway:{code}:{amount_rub}")])
    buttons.append([InlineKeyboardButton(text="вќЊ РћС‚РјРµРЅРёС‚СЊ", callback_data="topup:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def balance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџ’і РџРѕРїРѕР»РЅРёС‚СЊ Р±Р°Р»Р°РЅСЃ", callback_data="topup:start")],
            [InlineKeyboardButton(text="вњ… РџСЂРѕРґР»РёС‚СЊ РїРѕРґРїРёСЃРєСѓ", callback_data="balance:renew")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def _plan_months_label(plan: dict[str, Any]) -> str:
    return str(plan.get("label") or "").strip() or "РџР»Р°РЅ"


def _plan_price_rub(plan: dict[str, Any]) -> int:
    return int(plan.get("price_rub") or 0)


def _plan_savings_rub(plan: dict[str, Any]) -> int:
    months = int(plan.get("months") or 0)
    if months <= 1:
        return 0
    base = max(1, int(settings.subscription_price_rub)) * months
    return max(0, base - _plan_price_rub(plan))


def renew_menu_kb() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for plan in SUBSCRIPTION_PLANS:
        label = _plan_months_label(plan)
        price = _plan_price_rub(plan)
        emoji = "рџ—“пёЏ"
        if str(plan.get("id")) == "m1":
            emoji = "1пёЏвѓЈ"
        elif str(plan.get("id")) == "m3":
            emoji = "3пёЏвѓЈ"
        elif str(plan.get("id")) == "m6":
            emoji = "6пёЏвѓЈ"
        elif str(plan.get("id")) == "y1":
            emoji = "рџ—“пёЏ"
        text = f"{emoji} {label} вЂ” {price} RUB"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"renew:plan:{plan['id']}")])
    rows.append([InlineKeyboardButton(text="в†©пёЏ РќР°Р·Р°Рґ Рє Р±Р°Р»Р°РЅСЃСѓ", callback_data="menu:balance")])
    rows.append([InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџЋЃ Р РµС„РµСЂР°Р»СЊРЅР°СЏ СЃРёСЃС‚РµРјР°", callback_data="profile:ref")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def topup_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="вќЊ РћС‚РјРµРЅРёС‚СЊ РїРѕРїРѕР»РЅРµРЅРёРµ", callback_data="topup:cancel")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def connect_inactive_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="рџ’і РџРµСЂРµР№С‚Рё Рє РѕРїР»Р°С‚Рµ",
                    callback_data="menu:balance",
                )
            ],
            [InlineKeyboardButton(text="рџ’і РџРѕРїРѕР»РЅРёС‚СЊ РЅР° РґСЂСѓРіСѓСЋ СЃСѓРјРјСѓ", callback_data="topup:start")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def connect_active_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџ”‘ РљР»СЋС‡ РїРѕРґРєР»СЋС‡РµРЅРёСЏ", callback_data="connect:sub")],
            [InlineKeyboardButton(text="рџ’» РЈСЃС‚СЂРѕР№СЃС‚РІР°", callback_data="connect:devices")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def connect_devices_kb(active_configs: list[dict[str, Any]], can_add_device: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for cfg in active_configs:
        cfg_id = int(cfg.get("id", 0))
        if cfg_id <= 0:
            continue
        device_name = str(cfg.get("device_name") or f"device-{cfg_id}")
        if len(device_name) > 18:
            device_name = device_name[:17] + "вЂ¦"
        rows.append(
            [
                InlineKeyboardButton(text=f"рџ’» {device_name}", callback_data=f"connect:devshow:{cfg_id}"),
                InlineKeyboardButton(text="вќЊ РћС‚РєР»СЋС‡РёС‚СЊ", callback_data=f"connect:devdel:{cfg_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="рџ”„ РћР±РЅРѕРІРёС‚СЊ", callback_data="connect:devices")])
    rows.append([InlineKeyboardButton(text="в¬…пёЏ РќР°Р·Р°Рґ Рє РїРѕРґРєР»СЋС‡РµРЅРёСЋ", callback_data="menu:connect")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def servers_overview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BTN_CONNECT, callback_data="menu:connect")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="рџ† РџРѕРґРґРµСЂР¶РєР°", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def giveaways_kb(giveaways: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for g in giveaways:
        gid = int(g.get("id") or 0)
        joined = bool(g.get("joined"))
        if gid <= 0:
            continue
        if joined:
            rows.append([InlineKeyboardButton(text="вњ… РЈС‡Р°СЃС‚РІСѓСЋ", callback_data="giveaway:joined")])
        else:
            rows.append([InlineKeyboardButton(text="вњ… РЈС‡Р°СЃС‚РІРѕРІР°С‚СЊ", callback_data=f"giveaway:join:{gid}")])
    rows.append([InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def subscription_link_kb(telegram_id: int) -> InlineKeyboardMarkup:
    happ_sub_url = build_user_subscription_url(telegram_id)
    happ_sub_url = f"{happ_sub_url}{'&' if '?' in happ_sub_url else '?'}fmt=b64&preview=0&pool=all"
    sub_url = build_user_subscription_url(telegram_id)
    encoded_happ_sub_url = quote(happ_sub_url, safe="")
    try:
        happ_url = str(settings.happ_import_url_template).format(url=encoded_happ_sub_url, raw_url=happ_sub_url)
    except Exception:
        happ_url = f"happ://add?url={encoded_happ_sub_url}"
    happ_download_url = str(settings.happ_download_url or "").strip()
    if not happ_download_url.startswith(("https://", "http://")):
        happ_download_url = SUPPORT_URL
    happ_is_safe_button_url = happ_url.startswith(("https://", "http://", "tg://"))
    happ_button = (
        InlineKeyboardButton(text="вћ• Р”РѕР±Р°РІРёС‚СЊ РІ HApp", url=happ_url)
        if happ_is_safe_button_url
        else InlineKeyboardButton(text="вћ• Р”РѕР±Р°РІРёС‚СЊ РІ HApp", callback_data="sub:happ")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [happ_button],
            [InlineKeyboardButton(text="в¬‡пёЏ РЎРєР°С‡Р°С‚СЊ HApp", url=happ_download_url)],
            [InlineKeyboardButton(text="рџ“ РљР°Рє СѓСЃС‚Р°РЅРѕРІРёС‚СЊ", callback_data="sub:howto")],
            [InlineKeyboardButton(text="в¬…пёЏ Рљ РїСЂРѕС„РёР»СЋ", callback_data="profile:open")],
            [InlineKeyboardButton(text="в¬…пёЏ Р’ РјРµРЅСЋ", callback_data="menu:main")],
        ]
    )


def profile_configs_kb(active_configs: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for cfg in active_configs[:15]:
        cfg_id = int(cfg["id"])
        rows.append(
            [
                InlineKeyboardButton(text=f"рџ”— #{cfg_id} РєРѕРїРёСЂРѕРІР°С‚СЊ", callback_data=f"profile:cfgcopy:{cfg_id}"),
                InlineKeyboardButton(text=f"рџ—‘ #{cfg_id} СѓРґР°Р»РёС‚СЊ", callback_data=f"profile:cfgdel:{cfg_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="в¬…пёЏ РџСЂРѕС„РёР»СЊ", callback_data="profile:open")])
    return InlineKeyboardMarkup(
        inline_keyboard=rows
    )


def _active_devices_from_user_payload(user: dict[str, Any]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cfg in list(user.get("configs") or []):
        if not cfg.get("is_active"):
            continue
        name = str(cfg.get("device_name") or "").strip()
        key = name.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        devices.append(cfg)
    return devices


def _extract_referrer_from_start(message: Message) -> int | None:
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if payload.startswith("ref_") and payload[4:].isdigit():
        return int(payload[4:])
    if payload.isdigit():
        return int(payload)
    return None


def _user_ref_link(telegram_id: int) -> str:
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start=ref_{telegram_id}"
    return f"ref_{telegram_id}"


def _is_message_not_modified_error(exc: Exception) -> bool:
    return "message is not modified" in str(exc).lower()


def _fix_mojibake_text(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return text
    if all(ord(ch) < 128 for ch in text):
        return text

    payload = bytearray()
    for ch in text:
        try:
            encoded = ch.encode("cp1251")
            if len(encoded) != 1:
                return text
            payload.append(encoded[0])
            continue
        except Exception:
            pass
        code = ord(ch)
        if code <= 255:
            payload.append(code)
        else:
            return text

    try:
        fixed = payload.decode("utf-8")
    except Exception:
        return text
    return fixed or text


def _normalize_reply_markup(markup: Any) -> Any:
    if not markup:
        return markup
    try:
        if isinstance(markup, InlineKeyboardMarkup):
            rows: list[list[InlineKeyboardButton]] = []
            for row in list(markup.inline_keyboard or []):
                new_row: list[InlineKeyboardButton] = []
                for btn in row:
                    if isinstance(btn, InlineKeyboardButton):
                        payload = btn.model_dump(exclude_none=True)
                        payload["text"] = _fix_mojibake_text(str(payload.get("text") or ""))
                        new_row.append(InlineKeyboardButton(**payload))
                    else:
                        new_row.append(btn)
                rows.append(new_row)
            return InlineKeyboardMarkup(inline_keyboard=rows)
    except Exception:
        return markup
    return markup


if not getattr(Bot, "_tvpn_mojibake_patch", False):
    _orig_bot_send_message = Bot.send_message
    _orig_bot_edit_message_text = Bot.edit_message_text
    _orig_bot_send_photo = Bot.send_photo

    async def _patched_bot_send_message(self, chat_id, text, *args, **kwargs):
        kwargs["reply_markup"] = _normalize_reply_markup(kwargs.get("reply_markup"))
        return await _orig_bot_send_message(self, chat_id, _fix_mojibake_text(text), *args, **kwargs)

    async def _patched_bot_edit_message_text(self, text, *args, **kwargs):
        kwargs["reply_markup"] = _normalize_reply_markup(kwargs.get("reply_markup"))
        return await _orig_bot_edit_message_text(self, _fix_mojibake_text(text), *args, **kwargs)

    async def _patched_bot_send_photo(self, chat_id, photo, *args, **kwargs):
        kwargs["reply_markup"] = _normalize_reply_markup(kwargs.get("reply_markup"))
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = _fix_mojibake_text(caption)
        return await _orig_bot_send_photo(self, chat_id, photo, *args, **kwargs)

    Bot.send_message = _patched_bot_send_message
    Bot.edit_message_text = _patched_bot_edit_message_text
    Bot.send_photo = _patched_bot_send_photo
    Bot._tvpn_mojibake_patch = True


if not getattr(Message, "_tvpn_mojibake_patch", False):
    _orig_message_answer = Message.answer
    _orig_message_edit_text = Message.edit_text
    _orig_message_answer_photo = Message.answer_photo

    async def _patched_message_answer(self, text: str, *args, **kwargs):
        kwargs["reply_markup"] = _normalize_reply_markup(kwargs.get("reply_markup"))
        return await _orig_message_answer(self, _fix_mojibake_text(text), *args, **kwargs)

    async def _patched_message_edit_text(self, text: str, *args, **kwargs):
        kwargs["reply_markup"] = _normalize_reply_markup(kwargs.get("reply_markup"))
        return await _orig_message_edit_text(self, _fix_mojibake_text(text), *args, **kwargs)

    async def _patched_message_answer_photo(self, photo, *args, **kwargs):
        kwargs["reply_markup"] = _normalize_reply_markup(kwargs.get("reply_markup"))
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = _fix_mojibake_text(caption)
        return await _orig_message_answer_photo(self, photo, *args, **kwargs)

    Message.answer = _patched_message_answer
    Message.edit_text = _patched_message_edit_text
    Message.answer_photo = _patched_message_answer_photo
    Message._tvpn_mojibake_patch = True


async def _remove_legacy_keyboard(message: Message) -> None:
    try:
        cleanup_message = await message.answer(" ", reply_markup=ReplyKeyboardRemove())
        await cleanup_message.delete()
    except Exception:
        pass


async def _upsert_message(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = True,
) -> Message:
    kwargs: dict[str, Any] = {
        "reply_markup": reply_markup,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        kwargs["parse_mode"] = parse_mode
    try:
        return await message.edit_text(text, **kwargs)
    except Exception as exc:
        if _is_message_not_modified_error(exc):
            return message
        try:
            if message.from_user and bool(message.from_user.is_bot):
                await message.delete()
        except Exception:
            pass
        return await message.answer(text, **kwargs)


async def show_main_menu(message: Message) -> None:
    await _upsert_message(
        message,
        (
            "TrumpVPN\n"
            "вњЁ Р‘С‹СЃС‚СЂС‹Р№ Рё СЃС‚Р°Р±РёР»СЊРЅС‹Р№ VPN\n\n"
            f"рџ’і Р‘Р°Р·РѕРІС‹Р№ С‚Р°СЂРёС„: {settings.subscription_price_rub} RUB / {settings.subscription_days_per_month} РґРЅРµР№\n"
            "рџ”— РќР°Р¶РјРёС‚Рµ В«РџРѕРґРєР»СЋС‡РёС‚СЊВ», С‡С‚РѕР±С‹ РїРѕР»СѓС‡РёС‚СЊ СЃСЃС‹Р»РєСѓ"
        ),
        reply_markup=main_menu_kb(),
    )


async def show_help_screen(message: Message) -> None:
    await _upsert_message(
        message,
        (
            "РџРѕРјРѕС‰СЊ\n\n"
            "1. РќР°Р¶РјРёС‚Рµ В«РџРѕРґРєР»СЋС‡РёС‚СЊВ» Рё РїРѕР»СѓС‡РёС‚Рµ СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё.\n"
            "2. Р”РѕР±Р°РІСЊС‚Рµ СЃСЃС‹Р»РєСѓ РІ VPN-РєР»РёРµРЅС‚ (HApp, Hiddify, v2rayNG).\n"
            "3. РќР°Р¶РјРёС‚Рµ Update/Import Рё РІРєР»СЋС‡РёС‚Рµ VPN.\n\n"
            f"рџ”’ РџРѕР»РёС‚РёРєР° РєРѕРЅС„РёРґРµРЅС†РёР°Р»СЊРЅРѕСЃС‚Рё: <a href=\"{PRIVACY_POLICY_URL}\">С‡РёС‚Р°С‚СЊ</a>\n"
            f"рџ“њ РџРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРµ СЃРѕРіР»Р°С€РµРЅРёРµ: <a href=\"{TERMS_OF_USE_URL}\">С‡РёС‚Р°С‚СЊ</a>\n\n"
            f"РџРѕРґРґРµСЂР¶РєР°: {SUPPORT_URL}"
        ),
        reply_markup=help_kb(),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


async def show_giveaways_screen(message: Message) -> None:
    try:
        giveaways = await bot_api_client.active_giveaways(message.from_user.id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=main_menu_kb())
        return
    if not giveaways:
        await _upsert_message(message, "РђРєС‚РёРІРЅС‹С… СЂРѕР·С‹РіСЂС‹С€РµР№ РїРѕРєР° РЅРµС‚.", reply_markup=giveaways_kb([]))
        return
    lines: list[str] = ["рџЋЃ РђРєС‚РёРІРЅС‹Рµ СЂРѕР·С‹РіСЂС‹С€Рё:"]
    for idx, g in enumerate(giveaways, start=1):
        title = str(g.get("title") or f"Р РѕР·С‹РіСЂС‹С€ #{g.get('id')}").strip()
        lines.append(f"{idx}. {title}")
        if g.get("description"):
            lines.append(str(g.get("description")).strip())
        if g.get("prize"):
            lines.append(f"РџСЂРёР·: {g.get('prize')}")
        lines.append(f"РџРµСЂРёРѕРґ: {_format_giveaway_period(g.get('starts_at'), g.get('ends_at'))}")
        kind = str(g.get("kind") or "")
        lines.append(f"РЈСЃР»РѕРІРёРµ: {_giveaway_condition_text(kind)}")
        participants = int(g.get("participants") or 0)
        lines.append(f"РЈС‡Р°СЃС‚РЅРёРєРё: {participants}")
        if kind == GIVEAWAY_KIND_CHANNEL_SUB:
            lines.append(f"Р“СЂСѓРїРїР°: {settings.welcome_channel_url}")
        lines.append("")
    await _upsert_message(message, "\n".join(lines).rstrip(), reply_markup=giveaways_kb(giveaways))


async def show_servers_screen(message: Message) -> None:
    rows = await bot_api_client.servers_runtime()
    if not rows:
        await _upsert_message(message, "РЎРµСЂРІРµСЂРѕРІ РїРѕРєР° РЅРµС‚.", reply_markup=main_menu_kb())
        return
    lines = ["РЎРµСЂРІРµСЂС‹ (СЃС‚Р°С‚СѓСЃ Рё Р·Р°РґРµСЂР¶РєР°):"]
    for s in rows:
        runtime = s.get("runtime", {})
        circle = _runtime_circle(runtime)
        status = str(runtime.get("health", "-"))
        avail_text = _runtime_availability_text(runtime)
        latency_text = _runtime_latency_text(runtime)
        lines.append(f"{circle} {s['name']} | {status} | {avail_text} | {latency_text}")
    lines.append("")
    lines.append("РџРѕРґРєР»СЋС‡РµРЅРёРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ С‡РµСЂРµР· РєРЅРѕРїРєСѓ В«РџРѕРґРєР»СЋС‡РёС‚СЊВ».")
    await _upsert_message(message, "\n".join(lines), reply_markup=servers_overview_kb())


async def show_connect_screen(message: Message, telegram_id: int) -> None:
    try:
        user = await bot_api_client.get_user(telegram_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=main_menu_kb())
        return
    active_devices = _active_devices_from_user_payload(user)
    if user.get("subscription_active"):
        days_left = _subscription_days_left(user.get("subscription_until"))
        await _upsert_message(
            message,
            (
                "РџРѕРґРєР»СЋС‡РµРЅРёРµ\n\n"
                "РџРѕРґРїРёСЃРєР° Р°РєС‚РёРІРЅР°.\n"
                f"РћСЃС‚Р°Р»РѕСЃСЊ РґРЅРµР№: {days_left}\n"
                f"РЈСЃС‚СЂРѕР№СЃС‚РІ РїРѕРґРєР»СЋС‡РµРЅРѕ: {len(active_devices)} РёР· {MAX_ACTIVE_CONFIGS_PER_USER}.\n\n"
                "РћС‚РєСЂРѕР№С‚Рµ СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё Рё РґРѕР±Р°РІСЊС‚Рµ РµРµ РІ РєР»РёРµРЅС‚."
            ),
            reply_markup=connect_active_kb(),
        )
        return
    await _upsert_message(
        message,
        (
            "РџРѕРґРєР»СЋС‡РµРЅРёРµ\n\n"
            "РџРѕРґРїРёСЃРєР° РЅРµР°РєС‚РёРІРЅР°.\n"
            f"Р‘Р°Р»Р°РЅСЃ: {int(user.get('balance_rub', 0))} RUB\n\n"
            "РџРµСЂРµР№РґРёС‚Рµ РІ В«Р‘Р°Р»Р°РЅСЃ Рё РїСЂРѕРґР»РµРЅРёРµВ» Рё РІС‹Р±РµСЂРёС‚Рµ СѓРґРѕР±РЅС‹Р№ РїРµСЂРёРѕРґ.\n"
            "Р§РµРј РґРѕР»СЊС€Рµ РїРµСЂРёРѕРґ вЂ” С‚РµРј РІС‹РіРѕРґРЅРµРµ."
        ),
        reply_markup=connect_inactive_kb(),
    )


async def show_connect_devices_screen(message: Message, telegram_id: int) -> None:
    try:
        user = await bot_api_client.get_user(telegram_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=main_menu_kb())
        return
    active_devices = _active_devices_from_user_payload(user)
    can_add_device = bool(user.get("subscription_active"))
    lines = [
        "РџРѕРґРєР»СЋС‡РµРЅРЅС‹Рµ СѓСЃС‚СЂРѕР№СЃС‚РІР°",
        "",
        f"Р’СЃРµРіРѕ: {len(active_devices)} РёР· {MAX_ACTIVE_CONFIGS_PER_USER} РґРѕСЃС‚СѓРїРЅС‹С…",
        "",
    ]
    if not active_devices:
        lines.append("РџРѕРєР° РЅРµС‚ РїРѕРґРєР»СЋС‡РµРЅРЅС‹С… СѓСЃС‚СЂРѕР№СЃС‚РІ.")
    else:
        for idx, cfg in enumerate(active_devices[:MAX_ACTIVE_CONFIGS_PER_USER], start=1):
            lines.append(f"{idx}. {cfg.get('device_name', '-')}")
    lines.extend(
        [
            "",
            "РќР°Р¶РјРёС‚Рµ В«РћС‚РєР»СЋС‡РёС‚СЊВ», С‡С‚РѕР±С‹ СѓРґР°Р»РёС‚СЊ СѓСЃС‚СЂРѕР№СЃС‚РІРѕ РёР· СЃРїРёСЃРєР°.",
            "Р”РѕР±Р°РІР»РµРЅРёРµ СѓСЃС‚СЂРѕР№СЃС‚РІ РІСЂСѓС‡РЅСѓСЋ РѕС‚РєР»СЋС‡РµРЅРѕ вЂ” РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РѕР±С‰СѓСЋ СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё.",
        ]
    )
    await _upsert_message(
        message,
        "\n".join(lines),
        reply_markup=connect_devices_kb(active_devices, can_add_device=can_add_device),
    )


async def send_payment_created(message: Message, invoice: dict[str, Any]) -> None:
    gateway_map = {
        "cryptopay": "Crypto Bot",
        "platega": "Platega",
        "platega_crypto": "crypto",
        "platega_card": "рџ‡·рџ‡єРљР°СЂС‚Р°",
        "platega_sbp": "рџ‡·рџ‡єРЎР‘Рџ",
        "yoomoney": "Р®Money",
    }
    gw = str(invoice.get("gateway", "")).lower()
    gw_title = gateway_map.get(gw, gw or "unknown")
    amount_face = int(invoice.get("amount_rub", 0))
    payable = int(invoice.get("payable_rub", amount_face))
    discount_percent = int(invoice.get("promo_discount_percent", 0) or 0)
    promo_code = str(invoice.get("promo_code") or "").strip()
    amount_line = f"РЎСѓРјРјР° Рє РѕРїР»Р°С‚Рµ: {payable} RUB"
    if discount_percent > 0 and payable < amount_face:
        amount_line = (
            f"РЎСѓРјРјР°: {amount_face} RUB\n"
            f"РЎРєРёРґРєР°: {discount_percent}% ({promo_code or 'promo'})\n"
            f"Рљ РѕРїР»Р°С‚Рµ: {payable} RUB"
        )
    await _upsert_message(
        message,
        (
            "РЎС‡РµС‚ СЃРѕР·РґР°РЅ.\n\n"
            f"РЎРїРѕСЃРѕР± РѕРїР»Р°С‚С‹: {gw_title}\n"
            f"{amount_line}\n"
            f"Invoice ID: {invoice['invoice_id']}\n\n"
            "РџРѕСЃР»Рµ РѕРїР»Р°С‚С‹ РЅР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ РїСЂРѕРІРµСЂРєРё."
        ),
        reply_markup=payment_kb(invoice["pay_url"], invoice["invoice_id"]),
    )


async def send_copyable_vless(message: Message, vless_url: str) -> None:
    await message.answer(
        f"<pre>{escape(vless_url)}</pre>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def send_device_subscription_link(message: Message, telegram_id: int, device_name: str) -> None:
    sub_url = build_user_subscription_url_for_device(telegram_id, device_name=device_name)
    await message.answer(
        (
            f"Subscription URL РґР»СЏ СѓСЃС‚СЂРѕР№СЃС‚РІР° В«{device_name}В»:\n"
            f"<code>{escape(sub_url)}</code>\n\n"
            "Р”РѕР±Р°РІСЊС‚Рµ СЌС‚РѕС‚ URL РІ РєР»РёРµРЅС‚, С‡С‚РѕР±С‹ РїРѕР»СѓС‡РёС‚СЊ РІСЃРµ РґРѕСЃС‚СѓРїРЅС‹Рµ СЃРµСЂРІРµСЂС‹ РґР»СЏ СѓСЃС‚СЂРѕР№СЃС‚РІР°."
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def _parse_api_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _subscription_days_left(subscription_until: str | None) -> int:
    dt = _parse_api_datetime(subscription_until)
    if not dt:
        return 0
    delta_seconds = (dt - utc_now()).total_seconds()
    if delta_seconds <= 0:
        return 0
    return max(1, int((delta_seconds + 86399) // 86400))


def _format_subscription_until(subscription_until: str | None) -> str:
    dt = _parse_api_datetime(subscription_until)
    if not dt:
        return "-"
    msk_tz = timezone(timedelta(hours=3))
    dt_msk = dt.replace(tzinfo=timezone.utc).astimezone(msk_tz)
    return dt_msk.strftime("%d.%m.%Y %H:%M MSK")


def _subscription_status_summary(user: dict[str, Any]) -> dict[str, Any]:
    until_raw = user.get("subscription_until")
    until_dt = _parse_api_datetime(until_raw)
    now = utc_now()
    if not until_dt:
        return {"status": "РЅРµР°РєС‚РёРІРЅР°", "days_left": 0, "until_text": "-", "is_active": False}
    is_active = until_dt > now
    status = "Р°РєС‚РёРІРЅР°" if is_active else "РёСЃС‚РµРєР»Р°"
    return {
        "status": status,
        "days_left": _subscription_days_left(until_raw) if is_active else 0,
        "until_text": _format_subscription_until(until_raw),
        "is_active": is_active,
    }


def _format_giveaway_period(starts_at: str | None, ends_at: str | None) -> str:
    start_dt = _parse_api_datetime(starts_at)
    end_dt = _parse_api_datetime(ends_at)
    msk_tz = timezone(timedelta(hours=3))

    def fmt(dt: datetime) -> str:
        return dt.replace(tzinfo=timezone.utc).astimezone(msk_tz).strftime("%d.%m.%Y %H:%M MSK")

    if start_dt and end_dt:
        return f"{fmt(start_dt)} вЂ” {fmt(end_dt)}"
    if start_dt:
        return f"СЃ {fmt(start_dt)}"
    if end_dt:
        return f"РґРѕ {fmt(end_dt)}"
    return "Р±РµР· РѕРіСЂР°РЅРёС‡РµРЅРёР№"


def _build_profile_text(user: dict[str, Any]) -> str:
    summary = _subscription_status_summary(user)
    status_emoji = "рџџў" if summary["is_active"] else "рџ”ґ"
    lines = [
        "Р›РёС‡РЅС‹Р№ РєР°Р±РёРЅРµС‚",
        f"рџ’і Р‘Р°Р»Р°РЅСЃ: {user.get('balance_rub', 0)} RUB",
        f"{status_emoji} РџРѕРґРїРёСЃРєР°: {summary['status']}",
    ]
    if summary["is_active"]:
        lines.append(f"рџ“† РћСЃС‚Р°Р»РѕСЃСЊ РґРЅРµР№: {summary['days_left']}")
        lines.append(f"вЏі Р”Рѕ: {summary['until_text']}")
    else:
        lines.append("вЏі Р”Рѕ: -")
    lines.extend(
        [
            "",
            "РџСЂРѕРґР»РёС‚Рµ Р·Р°СЂР°РЅРµРµ, С‡С‚РѕР±С‹ РґРѕСЃС‚СѓРї РЅРµ РїСЂРµСЂС‹РІР°Р»СЃСЏ.",
        ]
    )
    return "\n".join(lines)


def _build_configs_text(user: dict[str, Any]) -> str:
    configs = list(user.get("configs") or [])
    active = [cfg for cfg in configs if cfg.get("is_active")]
    lines = [
        "РљРѕРЅС„РёРіРё",
        "",
        f"РђРєС‚РёРІРЅС‹Рµ СЃРµСЂРІРµСЂС‹: {len(active)}",
    ]
    if not active:
        lines.append("РђРєС‚РёРІРЅС‹С… РєРѕРЅС„РёРіРѕРІ РЅРµС‚.")
        return "\n".join(lines)
    for cfg in active[:15]:
        lines.append(f"#{cfg['id']} {cfg['server_name']} / {cfg['device_name']} [ACTIVE]")
    if len(active) > 15:
        lines.append(f"... Рё РµС‰Рµ {len(active) - 15}")
    return "\n".join(lines)


def _build_referral_text(user: dict[str, Any]) -> str:
    percent = referral_topup_bonus_percent()
    return "\n".join(
        [
            "Р РµС„РµСЂР°Р»СЊРЅР°СЏ СЃРёСЃС‚РµРјР°",
            "",
            "Р‘РѕРЅСѓСЃС‹:",
            "вЂў +3 РґРЅСЏ РІР°Рј Рё РґСЂСѓРіСѓ Р·Р° РїСЂРёРіР»Р°С€РµРЅРёРµ",
            "вЂў +7 РґРЅРµР№ РІР°Рј, РµСЃР»Рё РґСЂСѓРі РѕРїР»Р°С‚РёС‚ РІ С‚РµС‡РµРЅРёРµ 7 РґРЅРµР№",
            f"вЂў +{percent}% СЃ РїРѕРїРѕР»РЅРµРЅРёР№ РїСЂРёРіР»Р°С€С‘РЅРЅС‹С…",
            "",
            f"РџСЂРёРіР»Р°С€РµРЅРѕ: {user.get('invited_count', 0)}",
            f"Р—Р°СЂР°Р±РѕС‚Р°РЅРѕ Р±РѕРЅСѓСЃРѕРІ: {user.get('referral_bonus_rub', 0)} RUB",
            f"РЎСЃС‹Р»РєР°: {_user_ref_link(user['telegram_id'])}",
        ]
    )


async def show_profile_screen(message: Message, telegram_id: int) -> None:
    try:
        user = await bot_api_client.get_user(telegram_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=main_menu_kb())
        return
    await _upsert_message(
        message,
        _build_profile_text(user),
        reply_markup=profile_kb(),
        disable_web_page_preview=True,
    )


async def show_configs_screen(message: Message, telegram_id: int) -> None:
    try:
        user = await bot_api_client.get_user(telegram_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=main_menu_kb())
        return
    active_configs = [cfg for cfg in list(user.get("configs") or []) if cfg.get("is_active")]
    await _upsert_message(
        message,
        _build_configs_text(user),
        reply_markup=profile_configs_kb(active_configs),
        disable_web_page_preview=True,
    )


def _resolve_message_telegram_id(message: Message, fallback: int | None = None) -> int:
    if message and message.from_user and not bool(getattr(message.from_user, "is_bot", False)):
        return int(message.from_user.id)
    if message and message.chat and message.chat.id:
        return int(message.chat.id)
    return int(fallback or 0)


async def show_balance(message: Message, telegram_id: int | None = None) -> None:
    effective_id = _resolve_message_telegram_id(message, telegram_id)
    if effective_id <= 0:
        await _upsert_message(message, "РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ.", reply_markup=main_menu_kb())
        return
    try:
        user = await bot_api_client.get_user(effective_id, with_stats=True)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=main_menu_kb())
        return

    summary = _subscription_status_summary(user)
    status_emoji = "рџџў" if summary["is_active"] else "рџ”ґ"
    traffic_total = int(user.get("traffic_total", 0) or 0)
    traffic_up = int(user.get("traffic_upload", 0) or 0)
    traffic_down = int(user.get("traffic_download", 0) or 0)
    lines = [
        "Р‘Р°Р»Р°РЅСЃ",
        f"рџ’і Р‘Р°Р»Р°РЅСЃ: {user.get('balance_rub', 0)} RUB",
        f"{status_emoji} РџРѕРґРїРёСЃРєР°: {summary['status']}",
    ]
    if summary["is_active"]:
        lines.append(f"рџ“† РћСЃС‚Р°Р»РѕСЃСЊ РґРЅРµР№: {summary['days_left']}")
        lines.append(f"вЏі Р”Рѕ: {summary['until_text']}")
    else:
        lines.append("вЏі Р”Рѕ: -")
        lines.append("рџ“† РћСЃС‚Р°Р»РѕСЃСЊ РґРЅРµР№: 0")
    if traffic_total > 0:
        lines.append(f"рџ“¶ РўСЂР°С„РёРє: {_format_bytes_short(traffic_total)}")
        lines.append(f"рџ“Ґ РџРѕР»СѓС‡РµРЅРѕ: {_format_bytes_short(traffic_down)}")
        lines.append(f"рџ“¤ РћС‚РїСЂР°РІР»РµРЅРѕ: {_format_bytes_short(traffic_up)}")
    else:
        lines.append("рџ“¶ РўСЂР°С„РёРє: -")
    lines.extend(
        [
            "",
            "Р РµС„РµСЂР°Р»С‹",
            f"рџ‘Ґ РџСЂРёРіР»Р°С€РµРЅРѕ: {user.get('invited_count', 0)}",
            f"рџЋЃ Р‘РѕРЅСѓСЃ: {user.get('referral_bonus_rub', 0)} RUB",
        ]
    )
    await _upsert_message(message, "\n".join(lines), reply_markup=balance_kb(), disable_web_page_preview=True)


def _build_renew_menu_text(user: dict[str, Any]) -> str:
    balance = int(user.get("balance_rub", 0))
    lines = [
        "РџСЂРѕРґР»РµРЅРёРµ РїРѕРґРїРёСЃРєРё",
        "",
        "Р’С‹Р±РµСЂРёС‚Рµ РїРµСЂРёРѕРґ вЂ” С‡РµРј РґРѕР»СЊС€Рµ, С‚РµРј РІС‹РіРѕРґРЅРµРµ.",
        "",
    ]
    for plan in SUBSCRIPTION_PLANS:
        label = _plan_months_label(plan)
        price = _plan_price_rub(plan)
        savings = _plan_savings_rub(plan)
        suffix = f" В· СЌРєРѕРЅРѕРјРёСЏ {savings} RUB" if savings > 0 else ""
        lines.append(f"{label}: {price} RUB{suffix}")
    lines.extend(
        [
            "",
            f"Р’Р°С€ Р±Р°Р»Р°РЅСЃ: {balance} RUB",
            "РџСЂРѕРґР»РµРЅРёРµ Р±СѓРґРµС‚ Р°РєС‚РёРІРёСЂРѕРІР°РЅРѕ СЃСЂР°Р·Сѓ РїРѕСЃР»Рµ СЃРїРёСЃР°РЅРёСЏ.",
        ]
    )
    return "\n".join(lines)


def _build_insufficient_balance_text(plan: dict[str, Any], balance: int) -> str:
    label = _plan_months_label(plan)
    price = _plan_price_rub(plan)
    missing = max(0, price - int(balance))
    suggested_topup = max(missing, int(settings.min_topup_rub))
    note = ""
    if suggested_topup > missing:
        note = f"РњРёРЅРёРјР°Р»СЊРЅРѕРµ РїРѕРїРѕР»РЅРµРЅРёРµ: {suggested_topup} RUB"
    return "\n".join(
        [
            "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ СЃСЂРµРґСЃС‚РІ РґР»СЏ РїСЂРѕРґР»РµРЅРёСЏ.",
            "",
            f"РџР»Р°РЅ: {label}",
            f"РЎС‚РѕРёРјРѕСЃС‚СЊ: {price} RUB",
            f"Р‘Р°Р»Р°РЅСЃ: {balance} RUB",
            f"РќРµ С…РІР°С‚Р°РµС‚: {missing} RUB",
            note,
            "",
            "РџРѕРїРѕР»РЅРёС‚Рµ Р±Р°Р»Р°РЅСЃ РЅР° РЅСѓР¶РЅСѓСЋ СЃСѓРјРјСѓ вЂ” Рё РїРѕРґРїРёСЃРєР° РїСЂРѕРґР»РёС‚СЃСЏ СЃСЂР°Р·Сѓ.",
        ]
    )


async def show_renew_menu(message: Message, telegram_id: int) -> None:
    try:
        user = await bot_api_client.get_user(telegram_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=balance_kb())
        return
    await _upsert_message(message, _build_renew_menu_text(user), reply_markup=renew_menu_kb())


async def send_subscription_link(message: Message, telegram_id: int) -> None:
    try:
        user = await bot_api_client.get_user(telegram_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc), reply_markup=profile_kb())
        return
    days_left = _subscription_days_left(user.get("subscription_until"))
    sub_url = build_user_subscription_url(telegram_id)
    warning = ""
    if "127.0.0.1" in sub_url or "localhost" in sub_url:
        warning = (
            "\n\nР’РЅРёРјР°РЅРёРµ: СЃСЃС‹Р»РєР° СЃРµР№С‡Р°СЃ СѓРєР°Р·С‹РІР°РµС‚ РЅР° localhost. "
            "Р—Р°РґР°Р№ PUBLIC_API_BASE_URL РІ .env (РЅР°РїСЂРёРјРµСЂ, https://vpn.example.com)."
        )
    await _upsert_message(
        message,
        (
            "РЎСЃС‹Р»РєР° РїРѕРґРєР»СЋС‡РµРЅРёСЏ (Subscription URL):\n"
            f"<code>{escape(sub_url)}</code>\n\n"
            f"РћСЃС‚Р°Р»РѕСЃСЊ РґРЅРµР№: {days_left}\n"
            "Р”РѕР±Р°РІСЊС‚Рµ СЌС‚Сѓ СЃСЃС‹Р»РєСѓ РІ VPN-РєР»РёРµРЅС‚ РІ СЂР°Р·РґРµР»Рµ РїРѕРґРїРёСЃРѕРє.\n"
            "Р”Р»СЏ HApp РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ В«Р”РѕР±Р°РІРёС‚СЊ РІ HAppВ» вЂ” СѓСЃС‚СЂРѕР№СЃС‚РІРѕ РґРѕР±Р°РІРёС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё."
            f"{warning}"
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=subscription_link_kb(telegram_id),
    )


@router.message(Command("start"))
async def start_handler(message: Message):
    referrer_id = _extract_referrer_from_start(message)
    user = await bot_api_client.register(
        message.from_user.id,
        message.from_user.username if message.from_user else None,
        referrer_telegram_id=referrer_id,
    )
    await _remove_legacy_keyboard(message)
    start_caption = (
        "рџ’њ TRUMP VPN - РЎР°РјС‹Р№ СЃС‚Р°Р±РёР»СЊРЅС‹Р№ VPN\n\n"
        "вљЎ РџСЂРµРёРјСѓС‰РµСЃС‚РІР°:\n"
        "в””в”Ђ рџ‡·рџ‡єР Р°Р±РѕС‡РёР№ РјРѕР±РёР»СЊРЅС‹Р№ РёРЅС‚РµСЂРЅРµС‚\n"
        "в””в”Ђ рџ’¶РќРёР·РєРёРµ С†РµРЅС‹\n"
        "в””в”Ђ рџљЂРќРёР·РєР°СЏ Р·Р°РґРµСЂР¶РєР°\n"
        "в””в”Ђ вњ…Р‘С‹СЃС‚СЂРѕРµ РїРѕРґРєР»СЋС‡РµРЅРёРµ/СЃС‚Р°Р±РёР»СЊРЅРѕСЃС‚СЊ\n\n"
        "рџЊђ Р›РѕРєР°С†РёРё:\n"
        "рџ‡ірџ‡±В·рџ‡©рџ‡ЄВ·рџ‡ёрџ‡Є 1Gb/s\n"
        "рџ‡ірџ‡±В·рџ‡єрџ‡ёВ·рџ‡«рџ‡·В·рџ‡µрџ‡±10Gb/s\n"
        "рџ‡єрџ‡ё 25Gb/s\n\n"
        "РџР°РЅРµР»СЊ СѓРїСЂР°РІР»РµРЅРёСЏ в¬‡пёЏ"
    )
    if START_PROMO_IMAGE_PATH.exists():
        try:
            await message.answer_photo(
                FSInputFile(str(START_PROMO_IMAGE_PATH)),
                caption=start_caption,
                reply_markup=main_menu_kb(),
            )
        except Exception:
            await message.answer(start_caption, reply_markup=main_menu_kb())
    else:
        await message.answer(start_caption, reply_markup=main_menu_kb())
    if user.get("is_new") and not user.get("trial_bonus_granted"):
        await message.answer(
            (
                "РџРѕРґРїРёС€РёСЃСЊ РЅР° РєР°РЅР°Р» Рё РїРѕР»СѓС‡Рё Р±РµСЃРїР»Р°С‚РЅС‹Рµ РґРЅРё РїРѕРґРїРёСЃРєРё.\n\n"
                f"РљР°РЅР°Р»: {settings.welcome_channel_url}\n"
                f"Р‘РѕРЅСѓСЃ: +{max(1, int(settings.welcome_bonus_days))} РґРЅСЏ"
            ),
            reply_markup=welcome_bonus_kb(),
            disable_web_page_preview=True,
        )


@router.message(Command("menu"))
async def menu_handler(message: Message):
    await _remove_legacy_keyboard(message)
    await show_main_menu(message)


@router.message(Command("balance"))
async def balance_handler(message: Message):
    await show_balance(message)


@router.message(Command("help"))
async def help_handler(message: Message):
    await show_help_screen(message)


@router.message(Command("topup"))
async def topup_handler(message: Message, state: FSMContext):
    parts = (message.text or "").split()
    if len(parts) == 2 and parts[1].isdigit():
        amount_rub = int(parts[1])
        await _upsert_message(
            message,
            f"Р’С‹Р±РµСЂРё СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹ РґР»СЏ {amount_rub} RUB:",
            reply_markup=choose_gateway_kb(amount_rub),
        )
        return
    await state.set_state(PaymentAmountState.waiting_for_amount_rub)
    await _upsert_message(
        message,
        (
            f"Р’РІРµРґРёС‚Рµ СЃСѓРјРјСѓ РїРѕРїРѕР»РЅРµРЅРёСЏ РІ RUB (РѕС‚ {settings.min_topup_rub} РґРѕ {settings.max_topup_rub}).\n"
            "РџСЂРёРјРµСЂ: 500\n"
            "Р”Р»СЏ РѕС‚РјРµРЅС‹ РЅР°Р¶РјРёС‚Рµ РєРЅРѕРїРєСѓ РЅРёР¶Рµ."
        ),
        reply_markup=topup_cancel_kb(),
    )


@router.message(Command("promo"))
async def promo_handler(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ: /promo <РїСЂРѕРјРѕРєРѕРґ>")
        return
    code = parts[1].strip()
    try:
        result = await bot_api_client.apply_promo(message.from_user.id, code)
    except RuntimeError as exc:
        await message.answer(str(exc))
        return

    applied = str(result.get("applied", ""))
    user = result.get("user", {}) if isinstance(result.get("user"), dict) else {}
    if applied == "pending_topup_discount":
        await message.answer(
            (
                f"РџСЂРѕРјРѕРєРѕРґ {result.get('promo_code', code)} РїСЂРёРЅСЏС‚.\n"
                f"РЎРєРёРґРєР° {result.get('discount_percent', 0)}% РїСЂРёРјРµРЅРёС‚СЃСЏ Рє СЃР»РµРґСѓСЋС‰РµРјСѓ РїРѕРїРѕР»РЅРµРЅРёСЋ."
            )
        )
        return

    if applied == PROMO_KIND_BALANCE:
        await message.answer(
            (
                f"РџСЂРѕРјРѕРєРѕРґ {result.get('promo_code', code)} РїСЂРёРјРµРЅРµРЅ.\n"
                f"РќР°С‡РёСЃР»РµРЅРѕ: {max(1, int(result.get('value_int', 0)))} RUB\n"
                f"Р‘Р°Р»Р°РЅСЃ: {int(user.get('balance_rub', 0))} RUB"
            )
        )
        return

    if applied == PROMO_KIND_SUBSCRIPTION_DAYS:
        await message.answer(
            (
                f"РџСЂРѕРјРѕРєРѕРґ {result.get('promo_code', code)} РїСЂРёРјРµРЅРµРЅ.\n"
                f"Р”РѕР±Р°РІР»РµРЅРѕ РґРЅРµР№: {max(1, int(result.get('value_int', 0)))}\n"
                f"РџРѕРґРїРёСЃРєР° РґРѕ: {_format_subscription_until(user.get('subscription_until'))}"
            )
        )
        return

    await message.answer("РџСЂРѕРјРѕРєРѕРґ РїСЂРёРјРµРЅРµРЅ.")


@router.message(Command("payments"))
async def payments_handler(message: Message):
    try:
        items = await bot_api_client.list_payments(message.from_user.id)
    except RuntimeError as exc:
        await message.answer(str(exc))
        return
    if not items:
        await message.answer("РџР»Р°С‚РµР¶РµР№ РїРѕРєР° РЅРµС‚.")
        return
    lines = ["РџРѕСЃР»РµРґРЅРёРµ РїР»Р°С‚РµР¶Рё:"]
    for p in items[:10]:
        lines.append(
            f"Invoice {p['invoice_id']} | {p['status']} | {p['amount_rub']} RUB | "
            f"credited={p.get('credited_rub', 0)} | {p['created_at']}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("check"))
async def check_command_handler(message: Message, state: FSMContext):
    parts = (message.text or "").split()
    if len(parts) == 2 and parts[1].isdigit():
        await perform_payment_check(message, int(parts[1]))
        return
    await state.set_state(PaymentCheckState.waiting_for_invoice_id)
    await message.answer("Р’РІРµРґРёС‚Рµ ID СЃС‡РµС‚Р° РґР»СЏ РїСЂРѕРІРµСЂРєРё. РџСЂРёРјРµСЂ: /check 123456")


@router.message(Command("renew"))
async def renew_handler(message: Message):
    await show_renew_menu(message, message.from_user.id)


@router.message(Command("profile"))
async def profile_handler(message: Message):
    await show_profile_screen(message, message.from_user.id)


@router.message(Command("sub"))
async def subscription_handler(message: Message):
    await show_connect_screen(message, message.from_user.id)


async def perform_payment_check(message: Message, invoice_id: int, telegram_id: int | None = None):
    effective_telegram_id = telegram_id
    if effective_telegram_id is None:
        if not message.from_user:
            await _upsert_message(message, "РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РґР»СЏ РїСЂРѕРІРµСЂРєРё РїР»Р°С‚РµР¶Р°.")
            return
        effective_telegram_id = message.from_user.id
    try:
        result = await bot_api_client.check_payment(effective_telegram_id, invoice_id)
    except RuntimeError as exc:
        await _upsert_message(message, str(exc))
        return
    if str(result.get("status", "")).lower() == "paid":
        await _upsert_message(message, "Р‘Р°Р»Р°РЅСЃ СѓСЃРїРµС€РЅРѕ РїРѕРїРѕР»РЅРµРЅ.", reply_markup=main_menu_kb())
        return
    lines = [
        f"Invoice {result['invoice_id']}: {result['status']}",
        f"РЎСѓРјРјР°: {result['amount_rub']} RUB",
        f"Рљ РѕРїР»Р°С‚Рµ: {result.get('payable_rub', result['amount_rub'])} RUB",
        f"РџСЂРѕРјРѕ: {result.get('promo_code') or '-'} ({result.get('promo_discount_percent', 0)}%)",
        f"Р—Р°С‡РёСЃР»РµРЅРѕ: {result.get('credited_rub', 0)} RUB",
        f"Р РµС„. Р±РѕРЅСѓСЃ: {result.get('referral_bonus_rub', 0)} RUB",
        f"Р‘Р°Р»Р°РЅСЃ: {result.get('balance_rub', 0)} RUB",
        f"РџРѕРґРїРёСЃРєР° РґРѕ: {_format_subscription_until(result.get('subscription_until'))}",
    ]
    await _upsert_message(message, "\n".join(lines), reply_markup=main_menu_kb())


@router.message(Command("servers"))
async def servers_handler(message: Message):
    await show_servers_screen(message)


@router.message(Command("load"))
async def load_handler(message: Message):
    await show_servers_screen(message)


@router.message(Command("config"))
async def config_handler(message: Message, state: FSMContext):
    await state.clear()
    await show_connect_screen(message, message.from_user.id)


@router.callback_query(F.data == "welcome:skip")
async def welcome_skip_callback(callback: CallbackQuery):
    await callback.answer("РћРєРµР№, РјРѕР¶РЅРѕ Р°РєС‚РёРІРёСЂРѕРІР°С‚СЊ Р±РѕРЅСѓСЃ С‡РµСЂРµР· СЌС‚Рѕ СЃРѕРѕР±С‰РµРЅРёРµ.", show_alert=True)


@router.callback_query(F.data == "welcome:check")
async def welcome_check_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    subscribed = await _is_user_subscribed_to_welcome_channel(callback.bot, callback.from_user.id)
    if not subscribed:
        await callback.answer("РџРѕРґРїРёСЃРєР° РЅРµ РЅР°Р№РґРµРЅР°. РџРѕРґРїРёС€РёСЃСЊ РЅР° РєР°РЅР°Р» Рё РЅР°Р¶РјРё СЃРЅРѕРІР°.", show_alert=True)
        return
    try:
        result = await bot_api_client.claim_welcome_bonus(callback.from_user.id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=welcome_bonus_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    if result.get("claimed"):
        await _upsert_message(
            callback.message,
            (
                f"Р“РѕС‚РѕРІРѕ. РќР°С‡РёСЃР»РµРЅРѕ +{result.get('days_added', 0)} РґРЅСЏ.\n"
                f"РџРѕРґРїРёСЃРєР° РґРѕ: {_format_subscription_until(result.get('subscription_until'))}"
            ),
            reply_markup=main_menu_kb(),
        )
    else:
        await _upsert_message(callback.message, "Р‘РѕРЅСѓСЃ СѓР¶Рµ Р±С‹Р» Р°РєС‚РёРІРёСЂРѕРІР°РЅ СЂР°РЅРµРµ.", reply_markup=main_menu_kb())
    await callback.answer("РЎС‚Р°С‚СѓСЃ РїСЂРѕРІРµСЂРµРЅ")


@router.callback_query(F.data == "menu:main")
async def menu_main_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_main_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu:profile")
async def menu_profile_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_profile_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "menu:balance")
async def menu_balance_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_balance(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "menu:servers")
async def menu_servers_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_servers_screen(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu:topup")
async def menu_topup_callback(callback: CallbackQuery, state: FSMContext):
    await topup_start_callback(callback, state)


@router.callback_query(F.data == "menu:connect")
async def menu_connect_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_connect_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def menu_help_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_help_screen(callback.message)
    await callback.answer()


@router.callback_query(F.data == "menu:giveaways")
async def menu_giveaways_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_giveaways_screen(callback.message)
    await callback.answer()


@router.callback_query(F.data == "giveaway:joined")
async def giveaway_joined_callback(callback: CallbackQuery):
    await callback.answer("Р’С‹ СѓР¶Рµ СѓС‡Р°СЃС‚РІСѓРµС‚Рµ")


@router.callback_query(F.data.startswith("giveaway:join:"))
async def giveaway_join_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    raw = str(callback.data or "")
    parts = raw.split(":")
    giveaway_id = int(parts[-1]) if parts and parts[-1].isdigit() else 0
    if giveaway_id <= 0:
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ СЂРѕР·С‹РіСЂС‹С€", show_alert=True)
        return
    try:
        await bot_api_client.join_giveaway(callback.from_user.id, giveaway_id)
    except RuntimeError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await show_giveaways_screen(callback.message)
    await callback.answer("Р’С‹ СѓС‡Р°СЃС‚РІСѓРµС‚Рµ")


@router.callback_query(F.data == "profile:open")
async def profile_open_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_profile_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "profile:configs")
async def profile_configs_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_connect_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "profile:ref")
async def profile_ref_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    try:
        user = await bot_api_client.get_user(callback.from_user.id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=profile_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    await _upsert_message(
        callback.message,
        _build_referral_text(user),
        reply_markup=profile_kb(),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data == "profile:sub")
async def profile_subscription_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_connect_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "profile:limit")
async def profile_limit_callback(callback: CallbackQuery):
    await callback.answer(
        f"Р›РёРјРёС‚ РїРѕРґРїРёСЃРєРё: РґРѕ {MAX_ACTIVE_CONFIGS_PER_USER} СѓСЃС‚СЂРѕР№СЃС‚РІ.",
        show_alert=True,
    )


@router.callback_query(F.data == "profile:create_config")
async def profile_create_config_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await state.clear()
    await show_connect_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("profile:cfgcopy:"))
async def profile_copy_config_callback(callback: CallbackQuery):
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ID", show_alert=True)
        return
    config_id = int(parts[2])
    try:
        user = await bot_api_client.get_user(callback.from_user.id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=profile_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    cfg = next((item for item in list(user.get("configs") or []) if int(item.get("id", 0)) == config_id), None)
    if not cfg:
        await callback.answer("РљРѕРЅС„РёРі РЅРµ РЅР°Р№РґРµРЅ", show_alert=True)
        return
    if not cfg.get("is_active"):
        await callback.answer("РљРѕРЅС„РёРі РЅРµР°РєС‚РёРІРµРЅ", show_alert=True)
        return
    await send_copyable_vless(callback.message, str(cfg.get("vless_url", "")))
    await callback.answer("РЎСЃС‹Р»РєР° РѕС‚РїСЂР°РІР»РµРЅР°")


@router.callback_query(F.data.startswith("profile:cfgdel:"))
async def profile_delete_config_callback(callback: CallbackQuery):
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ID", show_alert=True)
        return
    config_id = int(parts[2])
    try:
        result = await bot_api_client.revoke(callback.from_user.id, config_id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=profile_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    await show_configs_screen(callback.message, callback.from_user.id)
    await callback.answer(f"РљРѕРЅС„РёРі #{result['config_id']} СѓРґР°Р»РµРЅ")


@router.callback_query(F.data == "topup:start")
async def topup_start_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PaymentAmountState.waiting_for_amount_rub)
    if callback.message:
        await _upsert_message(
            callback.message,
            f"Р’РІРµРґРёС‚Рµ СЃСѓРјРјСѓ РїРѕРїРѕР»РЅРµРЅРёСЏ РІ RUB (РѕС‚ {settings.min_topup_rub} РґРѕ {settings.max_topup_rub}). "
            "Р”Р°Р»РµРµ РІС‹Р±РµСЂРµС€СЊ СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹.",
            reply_markup=topup_cancel_kb(),
        )
    await callback.answer()


@router.callback_query(F.data == "topup:cancel")
async def topup_cancel_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message:
        await _upsert_message(
            callback.message,
            "РџРѕРїРѕР»РЅРµРЅРёРµ РѕС‚РјРµРЅРµРЅРѕ.",
            reply_markup=main_menu_kb(),
        )
    await callback.answer("РћС‚РјРµРЅРµРЅРѕ")


@router.callback_query(F.data.startswith("topup:gateway:"))
async def topup_gateway_callback(callback: CallbackQuery):
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("РќРµРІРµСЂРЅС‹Р№ С„РѕСЂРјР°С‚", show_alert=True)
        return
    _, _, gateway, amount_raw = parts
    if not amount_raw.isdigit():
        await callback.answer("РќРµРІРµСЂРЅР°СЏ СЃСѓРјРјР°", show_alert=True)
        return
    amount_rub = int(amount_raw)
    try:
        invoice = await bot_api_client.create_payment(callback.from_user.id, amount_rub, gateway=gateway)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=topup_cancel_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    await send_payment_created(callback.message, invoice)
    await callback.answer("РЎС‡РµС‚ СЃРѕР·РґР°РЅ")


@router.callback_query(F.data == "balance:renew")
async def renew_from_balance_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await show_renew_menu(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("renew:plan:"))
async def renew_plan_callback(callback: CallbackQuery):
    if not callback.message or not callback.data:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    parts = callback.data.split(":")
    plan_id = parts[-1] if parts else ""
    plan = subscription_plan_by_id(plan_id)
    if not plan:
        await callback.answer("РџР»Р°РЅ РЅРµ РЅР°Р№РґРµРЅ", show_alert=True)
        return
    try:
        user = await bot_api_client.get_user(callback.from_user.id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=balance_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    balance = int(user.get("balance_rub", 0))
    price = _plan_price_rub(plan)
    if balance < price:
        missing = max(0, price - balance)
        suggested_topup = max(missing, int(settings.min_topup_rub))
        await _upsert_message(
            callback.message,
            _build_insufficient_balance_text(plan, balance),
            reply_markup=choose_gateway_kb(suggested_topup),
        )
        await callback.answer("РќРµ С…РІР°С‚Р°РµС‚ СЃСЂРµРґСЃС‚РІ", show_alert=True)
        return
    try:
        result = await bot_api_client.purchase_plan(callback.from_user.id, str(plan.get("id", "")))
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=renew_menu_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    await _upsert_message(
        callback.message,
        "\n".join(
            [
                "вњ… РџРѕРґРїРёСЃРєР° РїСЂРѕРґР»РµРЅР°!",
                f"РџР»Р°РЅ: {_plan_months_label(plan)}",
                f"РЎРїРёСЃР°РЅРѕ: {int(result.get('charged_rub', price))} RUB",
                f"РћСЃС‚Р°С‚РѕРє Р±Р°Р»Р°РЅСЃР°: {int(result.get('balance_rub', 0))} RUB",
                f"РќРѕРІР°СЏ РґР°С‚Р°: {_format_subscription_until(result.get('subscription_until'))}",
            ]
        ),
        reply_markup=balance_kb(),
    )
    await callback.answer("Р“РѕС‚РѕРІРѕ")


@router.callback_query(F.data.startswith("paycheck:"))
async def payment_check_callback(callback: CallbackQuery):
    if not callback.data:
        return
    invoice_id = int(callback.data.split(":")[1])
    fake_message = callback.message
    if fake_message is None:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await perform_payment_check(fake_message, invoice_id, telegram_id=callback.from_user.id)
    await callback.answer("РЎС‚Р°С‚СѓСЃ РѕР±РЅРѕРІР»РµРЅ")


@router.callback_query(F.data == "sub:howto")
async def sub_howto_callback(callback: CallbackQuery):
    happ_download_url = str(settings.happ_download_url or "").strip()
    if not happ_download_url.startswith(("https://", "http://")):
        happ_download_url = SUPPORT_URL
    if callback.message:
        await _upsert_message(
            callback.message,
            "\n".join(
                [
                    "РљР°Рє РїРѕРґРєР»СЋС‡РёС‚СЊСЃСЏ Рє VPN:",
                    "",
                    "1. РќР°Р¶РјРёС‚Рµ В«РџРѕРґРєР»СЋС‡РёС‚СЊВ» Рё РїРѕР»СѓС‡РёС‚Рµ СЃСЃС‹Р»РєСѓ Subscription URL.",
                    "2. РћС‚РєСЂРѕР№С‚Рµ VPN-РєР»РёРµРЅС‚ СЃ РїРѕРґРґРµСЂР¶РєРѕР№ РїРѕРґРїРёСЃРѕРє (HApp, Hiddify, v2rayNG Рё Р°РЅР°Р»РѕРіРё).",
                    "3. Р”РѕР±Р°РІСЊС‚Рµ URL РІ СЂР°Р·РґРµР»Рµ Profiles/Subscriptions.",
                    "4. РќР°Р¶РјРёС‚Рµ Update/Import Рё РІРєР»СЋС‡РёС‚Рµ VPN.",
                    "",
                    f"Р›РёРјРёС‚: РґРѕ {MAX_ACTIVE_CONFIGS_PER_USER} СѓСЃС‚СЂРѕР№СЃС‚РІ РЅР° РїРѕРґРїРёСЃРєСѓ.",
                    "Р”Р»СЏ HApp РјРѕР¶РЅРѕ РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РєРЅРѕРїРєСѓ В«Р”РѕР±Р°РІРёС‚СЊ РІ HAppВ».",
                    f"РЎРєР°С‡Р°С‚СЊ HApp: {happ_download_url}",
                ]
            ),
            reply_markup=subscription_link_kb(callback.from_user.id),
        )
    await callback.answer()


@router.callback_query(F.data == "sub:happ")
async def sub_happ_callback(callback: CallbackQuery):
    sub_url = build_user_subscription_url(callback.from_user.id)
    happ_sub_url = f"{sub_url}{'&' if '?' in sub_url else '?'}fmt=b64&preview=0&pool=all"
    encoded_happ_sub_url = quote(happ_sub_url, safe="")
    try:
        happ_url = str(settings.happ_import_url_template).format(url=encoded_happ_sub_url, raw_url=happ_sub_url)
    except Exception:
        happ_url = f"happ://add?url={encoded_happ_sub_url}"
    happ_download_url = str(settings.happ_download_url or "").strip()
    if not happ_download_url.startswith(("https://", "http://")):
        happ_download_url = SUPPORT_URL

    if callback.message:
        await _upsert_message(
            callback.message,
            (
                "РћС‚РєСЂС‹С‚РёРµ HApp РёР· Telegram-РєРЅРѕРїРєРё РѕРіСЂР°РЅРёС‡РµРЅРѕ РЅР° РЅРµРєРѕС‚РѕСЂС‹С… РєР»РёРµРЅС‚Р°С….\n\n"
                "РЎРєРѕРїРёСЂСѓР№С‚Рµ СЃСЃС‹Р»РєСѓ РЅРёР¶Рµ Рё РѕС‚РєСЂРѕР№С‚Рµ РІ СЃРёСЃС‚РµРјРµ/Р±СЂР°СѓР·РµСЂРµ:\n"
                f"<code>{escape(happ_url)}</code>\n\n"
                "Р•СЃР»Рё РЅРµ СЃСЂР°Р±РѕС‚Р°РµС‚, РѕС‚РєСЂРѕР№С‚Рµ HApp РІСЂСѓС‡РЅСѓСЋ Рё РІСЃС‚Р°РІСЊС‚Рµ СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё РґР»СЏ Р°РІС‚Рѕ-РґРѕР±Р°РІР»РµРЅРёСЏ СѓСЃС‚СЂРѕР№СЃС‚РІР°:\n"
                f"<code>{escape(happ_sub_url)}</code>\n\n"
                "РћР±С‹С‡РЅР°СЏ СЃСЃС‹Р»РєР° РїРѕРґРїРёСЃРєРё (Р±РµР· Р°РІС‚Рѕ-РјРµС‚РєРё СѓСЃС‚СЂРѕР№СЃС‚РІР°):\n"
                f"<code>{escape(sub_url)}</code>\n\n"
                f"РЎРєР°С‡Р°С‚СЊ HApp: {escape(happ_download_url)}"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=subscription_link_kb(callback.from_user.id),
        )
    await callback.answer("РРЅСЃС‚СЂСѓРєС†РёСЏ РѕС‚РїСЂР°РІР»РµРЅР°")


@router.callback_query(F.data.startswith("issue:"))
async def choose_server_handler(callback: CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await state.clear()
    await _upsert_message(
        callback.message,
        "Р СѓС‡РЅР°СЏ РІС‹РґР°С‡Р° РєРѕРЅС„РёРіРѕРІ РѕС‚РєР»СЋС‡РµРЅР°. РСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ В«РџРѕРґРєР»СЋС‡РёС‚СЊВ».",
        reply_markup=servers_overview_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "connect:buy")
async def connect_buy_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    amount_rub = max(1, int(settings.subscription_price_rub))
    await _upsert_message(
        callback.message,
        f"Р’С‹Р±РµСЂРёС‚Рµ СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹ РґР»СЏ РїРѕРґРєР»СЋС‡РµРЅРёСЏ: {amount_rub} RUB.",
        reply_markup=choose_gateway_kb(amount_rub),
    )
    await callback.answer("РЎРїРѕСЃРѕР±С‹ РѕРїР»Р°С‚С‹ РѕС‚РєСЂС‹С‚С‹")


@router.callback_query(F.data == "connect:sub")
async def connect_subscription_link_callback(callback: CallbackQuery):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await send_subscription_link(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "connect:devices")
async def connect_devices_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await state.clear()
    await show_connect_devices_screen(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("connect:devshow:"))
async def connect_device_show_callback(callback: CallbackQuery):
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ID", show_alert=True)
        return
    config_id = int(parts[2])
    try:
        user = await bot_api_client.get_user(callback.from_user.id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=connect_active_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    cfg = next((item for item in list(user.get("configs") or []) if int(item.get("id", 0)) == config_id), None)
    if not cfg or not cfg.get("is_active"):
        await callback.answer("РЈСЃС‚СЂРѕР№СЃС‚РІРѕ РЅРµ РЅР°Р№РґРµРЅРѕ", show_alert=True)
        return
    device_name = str(cfg.get("device_name") or "").strip() or "device"
    await send_device_subscription_link(callback.message, callback.from_user.id, device_name)
    await callback.answer("Subscription URL РѕС‚РїСЂР°РІР»РµРЅ")


@router.callback_query(F.data.startswith("connect:devdel:"))
async def connect_device_delete_callback(callback: CallbackQuery):
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await callback.answer("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ID", show_alert=True)
        return
    config_id = int(parts[2])
    try:
        result = await bot_api_client.revoke(callback.from_user.id, config_id)
    except RuntimeError as exc:
        await _upsert_message(callback.message, str(exc), reply_markup=main_menu_kb())
        await callback.answer("РћС€РёР±РєР°", show_alert=True)
        return
    await show_connect_devices_screen(callback.message, callback.from_user.id)
    await callback.answer(f"РЈСЃС‚СЂРѕР№СЃС‚РІРѕ #{result['config_id']} РѕС‚РєР»СЋС‡РµРЅРѕ")


@router.callback_query(F.data == "connect:devadd")
async def connect_device_add_callback(callback: CallbackQuery, state: FSMContext):
    if not callback.message:
        await callback.answer("РќРµС‚ РєРѕРЅС‚РµРєСЃС‚Р° СЃРѕРѕР±С‰РµРЅРёСЏ", show_alert=True)
        return
    await state.clear()
    await _upsert_message(
        callback.message,
        "Р”РѕР±Р°РІР»РµРЅРёРµ СѓСЃС‚СЂРѕР№СЃС‚РІ РІСЂСѓС‡РЅСѓСЋ РѕС‚РєР»СЋС‡РµРЅРѕ. РСЃРїРѕР»СЊР·СѓР№С‚Рµ РѕР±С‰СѓСЋ СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё.",
        reply_markup=connect_active_kb(),
    )
    await callback.answer("Р”РѕР±Р°РІР»РµРЅРёРµ РѕС‚РєР»СЋС‡РµРЅРѕ", show_alert=True)


@router.message(IssueConfigState.waiting_for_device_name)
async def issue_with_device(message: Message, state: FSMContext):
    if not message.from_user:
        await state.clear()
        await _upsert_message(message, "РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ.", reply_markup=main_menu_kb())
        return
    await state.clear()
    await _upsert_message(
        message,
        "Р”РѕР±Р°РІР»РµРЅРёРµ СѓСЃС‚СЂРѕР№СЃС‚РІ РІСЂСѓС‡РЅСѓСЋ РѕС‚РєР»СЋС‡РµРЅРѕ. РСЃРїРѕР»СЊР·СѓР№С‚Рµ РѕР±С‰СѓСЋ СЃСЃС‹Р»РєСѓ РїРѕРґРїРёСЃРєРё.",
        reply_markup=connect_active_kb(),
    )
    return


@router.message(PaymentCheckState.waiting_for_invoice_id)
async def payment_check_state_handler(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("РќСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ С‡РёСЃР»РѕРІРѕР№ ID СЃС‡РµС‚Р°.")
        return
    await state.clear()
    await perform_payment_check(message, int(text))


@router.message(PaymentAmountState.waiting_for_amount_rub)
async def payment_amount_state_handler(message: Message, state: FSMContext):
    raw_text = (message.text or "").strip()
    if raw_text.lower() in {"РѕС‚РјРµРЅР°", "cancel", "/cancel"}:
        await state.clear()
        await message.answer("РџРѕРїРѕР»РЅРµРЅРёРµ РѕС‚РјРµРЅРµРЅРѕ.")
        return
    text = raw_text.replace(",", ".")
    if not text.isdigit():
        await message.answer(
            "РќСѓР¶РЅРѕ РІРІРµСЃС‚Рё С†РµР»СѓСЋ СЃСѓРјРјСѓ РІ RUB РёР»Рё РЅР°РїРёСЃР°С‚СЊ 'РѕС‚РјРµРЅР°'.",
            reply_markup=topup_cancel_kb(),
        )
        return
    amount_rub = int(text)
    await state.clear()
    await message.answer(
        f"Р’С‹Р±РµСЂРё СЃРїРѕСЃРѕР± РѕРїР»Р°С‚С‹ РґР»СЏ {amount_rub} RUB:",
        reply_markup=choose_gateway_kb(amount_rub),
    )


@router.message(Command("revoke"))
async def revoke_handler(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("РСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ: /revoke <config_id>")
        return
    try:
        result = await bot_api_client.revoke(message.from_user.id, int(parts[1]))
    except RuntimeError as exc:
        await message.answer(str(exc))
        return
    await message.answer(f"РљРѕРЅС„РёРі #{result['config_id']} РѕС‚РѕР·РІР°РЅ.")


async def run_bot():
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty in .env")
    global BOT_USERNAME
    bot = Bot(token=settings.bot_token)
    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username or ""
    except Exception:
        BOT_USERNAME = ""
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


async def run_all():
    config = uvicorn.Config(app=app, host=settings.api_host, port=settings.api_port, log_level="info")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    while not server.started:
        await asyncio.sleep(0.1)

    bot_task = asyncio.create_task(run_bot())
    done, pending = await asyncio.wait({api_task, bot_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        if exc := task.exception():
            raise exc


def parse_args():
    parser = argparse.ArgumentParser(description="VPN bot+api in one file (VLESS Reality + Hysteria2)")
    parser.add_argument("mode", choices=["all", "api", "bot", "sweep"], nargs="?", default="all")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    run_sqlite_migrations()
    Base.metadata.create_all(bind=engine)

    if args.mode == "api":
        uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level="info")
        return
    if args.mode == "bot":
        asyncio.run(run_bot())
        return
    if args.mode == "sweep":
        print(sweep_expired_local())
        return
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
