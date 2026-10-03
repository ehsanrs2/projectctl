from __future__ import annotations

from projectctl.core.enums import (
    ModelProfile,
    QuotaMode,
    ReasoningLevel,
    RecommendationReason,
    ResourceClass,
    RiskLevel,
    TaskType,
)
from projectctl.scheduler.resource import effective_resource_class
from projectctl.schemas.config import ProjectConfig
from projectctl.schemas.scheduler import ModelRecommendation
from projectctl.schemas.task import NormalizedTask


_ORDER = [ModelProfile.ECONOMICAL, ModelProfile.BALANCED, ModelProfile.STRONG, ModelProfile.DEEP]


def _base_profile(resource: ResourceClass) -> ModelProfile:
    return {
        ResourceClass.TRIVIAL: ModelProfile.ECONOMICAL,
        ResourceClass.SMALL: ModelProfile.ECONOMICAL,
        ResourceClass.MEDIUM: ModelProfile.BALANCED,
        ResourceClass.LARGE: ModelProfile.STRONG,
        ResourceClass.DEEP: ModelProfile.DEEP,
        ResourceClass.UNKNOWN: ModelProfile.BALANCED,
    }[resource]


def _shift(profile: ModelProfile, delta: int) -> ModelProfile:
    index = min(max(_ORDER.index(profile) + delta, 0), len(_ORDER) - 1)
    return _ORDER[index]


def _enabled_profile(desired: ModelProfile, config: ProjectConfig) -> ModelProfile:
    enabled = [p for p in _ORDER if config.model_profiles[p].enabled]
    if not enabled:
        raise ValueError("At least one model profile must be enabled.")
    if desired in enabled:
        return desired
    desired_index = _ORDER.index(desired)
    return min(enabled, key=lambda p: (abs(_ORDER.index(p) - desired_index), _ORDER.index(p)))


def recommend_model(task: NormalizedTask, *, quota_mode: QuotaMode, config: ProjectConfig) -> ModelRecommendation:
    resource = effective_resource_class(task)
    profile = _base_profile(resource)
    reasons = [RecommendationReason.TASK_COMPLEXITY]

    if task.type == TaskType.ARCHITECTURE:
        profile = max(profile, ModelProfile.STRONG, key=_ORDER.index)
        reasons.append(RecommendationReason.ARCHITECTURE_TASK)
    elif task.type in {TaskType.RESEARCH, TaskType.EXPERIMENT}:
        profile = max(profile, ModelProfile.STRONG, key=_ORDER.index)
        reasons.append(RecommendationReason.RESEARCH_TASK)

    if task.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        profile = _shift(profile, 1)
        reasons.append(RecommendationReason.HIGH_RISK)

    if quota_mode in {QuotaMode.CONSERVATION, QuotaMode.CRITICAL, QuotaMode.UNKNOWN} and task.risk not in {
        RiskLevel.HIGH, RiskLevel.CRITICAL
    }:
        profile = _shift(profile, -1)
        reasons.append(RecommendationReason.LOW_QUOTA)

    profile = _enabled_profile(profile, config)

    if task.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL} or task.type in {
        TaskType.ARCHITECTURE, TaskType.SECURITY, TaskType.RESEARCH, TaskType.EXPERIMENT
    } or resource in {ResourceClass.LARGE, ResourceClass.DEEP}:
        reasoning = ReasoningLevel.HIGH
    elif resource == ResourceClass.MEDIUM or task.type == TaskType.BUG:
        reasoning = ReasoningLevel.MEDIUM
    else:
        reasoning = ReasoningLevel.LOW

    # The configured profile may deliberately override the default reasoning floor/ceiling.
    configured = config.model_profiles[profile].reasoning
    levels = [ReasoningLevel.LOW, ReasoningLevel.MEDIUM, ReasoningLevel.HIGH]
    reasoning = levels[max(levels.index(reasoning), levels.index(configured))]

    return ModelRecommendation(profile=profile, reasoning=reasoning, reasons=list(dict.fromkeys(reasons)), quota_mode=quota_mode)
