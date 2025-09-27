from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable

from pydantic import BaseModel, Field, ValidationError, field_validator


class FiltersModel(BaseModel):
    subject_ids: list[str] = Field(default_factory=list)
    type_ids: list[str] = Field(default_factory=list)
    min_budget: int = 0
    max_budget: int = 200_000

    @field_validator("min_budget", "max_budget")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("budget must be non-negative")
        return value


class MessagesModel(BaseModel):
    initial: str = "Здравствуйте! Готов выполнить заказ {order_title}."
    followup: str = "Напоминаю о своём предложении по заказу {order_title}."


class BidModel(BaseModel):
    strategy: str = Field(default="recommended")
    min_bid: int = 0
    max_bid: int = 200_000
    multiplier: float = 1.0

    @field_validator("multiplier")
    @classmethod
    def validate_multiplier(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("multiplier must be positive")
        return value

    @field_validator("min_bid", "max_bid")
    @classmethod
    def validate_bid_bounds(cls, value: int) -> int:
        if value < 0:
            raise ValueError("bid bounds must be non-negative")
        return value


class AuthModel(BaseModel):
    cookie: str
    user_agent: str


class BrowserModel(BaseModel):
    headless: bool = True
    slow_mo: int = 0
    navigation_timeout_ms: int = 15000

    @field_validator("navigation_timeout_ms")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("navigation timeout must be positive")
        return value

    @field_validator("slow_mo")
    @classmethod
    def validate_slow_mo(cls, value: int) -> int:
        if value < 0:
            raise ValueError("slow_mo must be non-negative")
        return value


class AccountConfigModel(BaseModel):
    login: str
    base_url: str
    poll_interval_seconds: float = 2.0
    min_seconds_between_bids: float = 3.0
    followup_delay_seconds: float = 300.0
    filters: FiltersModel = Field(default_factory=FiltersModel)
    messages: MessagesModel = Field(default_factory=MessagesModel)
    bid: BidModel = Field(default_factory=BidModel)
    auth: AuthModel
    browser: BrowserModel = Field(default_factory=BrowserModel)

    @field_validator("poll_interval_seconds", "min_seconds_between_bids", "followup_delay_seconds")
    @classmethod
    def positive_interval(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("interval must be positive")
        return value


@dataclass(slots=True)
class AccountConfig:
    path: Path
    data: AccountConfigModel

    @property
    def login(self) -> str:  # pragma: no cover - trivial forwarding
        return self.data.login

    def to_dict(self) -> Dict[str, Any]:
        return self.data.model_dump()


@dataclass(slots=True)
class ConfigRepository:
    root: Path
    _cache: Dict[Path, AccountConfig] = field(default_factory=dict)

    def list_configs(self) -> Iterable[AccountConfig]:
        for file in sorted(self.root.glob("*.json")):
            try:
                config = self.load(file)
            except ValidationError as exc:
                raise RuntimeError(f"Invalid config {file}: {exc}") from exc
            else:
                yield config

    def load(self, path: Path) -> AccountConfig:
        if path in self._cache:
            return self._cache[path]
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        model = AccountConfigModel.model_validate(raw)
        config = AccountConfig(path=path, data=model)
        self._cache[path] = config
        return config

    def save(self, config: AccountConfig) -> None:
        with config.path.open("w", encoding="utf-8") as fh:
            json.dump(config.to_dict(), fh, ensure_ascii=False, indent=2)
        self._cache[config.path] = config


def load_account_config(path: Path) -> AccountConfig:
    repo = ConfigRepository(path.parent)
    return repo.load(path)
