"""Application configuration model loaded from ``config.yaml``."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class WorkingGroupConfig(BaseModel):
    name: str
    archive_url: str


class TopicConfig(BaseModel):
    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    model_summarization: str
    model_categorization: str
    use_batch_api: bool = True


class ProcessingConfig(BaseModel):
    active_threshold_days: int = 90
    reprocess_on_new_messages: bool = True
    pre_filter_admin_messages: bool = True
    draft_metadata_refresh_days: int = 30


class DraftsConfig(BaseModel):
    datatracker_api_base: str = "https://datatracker.ietf.org/api/v1/"
    fetch_metadata_on_first_reference: bool = True
    weekly_refresh_active_drafts: bool = True


class AppConfig(BaseModel):
    working_groups: list[WorkingGroupConfig] = Field(default_factory=list)
    topics: list[TopicConfig] = Field(default_factory=list)
    llm: LLMConfig
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    drafts: DraftsConfig = Field(default_factory=DraftsConfig)

    def working_group(self, name: str) -> WorkingGroupConfig | None:
        return next((wg for wg in self.working_groups if wg.name == name), None)


def load_config(path: str | Path) -> AppConfig:
    """Parse and validate the YAML config at ``path``."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(data)
