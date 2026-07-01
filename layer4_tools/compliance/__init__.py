"""
第4层 · 合规防线
"""
from .prompt_rules import (
    check_text,
    get_all_forbidden_words,
    get_prompt_rules_text,
    ABSOLUTE_TERMS,
    MEDICAL_TERMS,
    SNACK_SENSITIVE,
    CHILD_INDUCEMENT,
    PRICE_FRAUD,
)
from .auto_checker import ComplianceAutoChecker, ComplianceReport, ChannelResult
from .review_router import ReviewRouter, RouteResult, ReviewDecision, run_compliance_pipeline

__all__ = [
    "check_text",
    "get_all_forbidden_words",
    "get_prompt_rules_text",
    "ABSOLUTE_TERMS",
    "MEDICAL_TERMS",
    "SNACK_SENSITIVE",
    "CHILD_INDUCEMENT",
    "PRICE_FRAUD",
    "ComplianceAutoChecker",
    "ComplianceReport",
    "ChannelResult",
    "ReviewRouter",
    "RouteResult",
    "ReviewDecision",
    "run_compliance_pipeline",
]
