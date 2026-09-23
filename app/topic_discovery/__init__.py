"""Topic discovery facade for the owner application."""

from app.web.service import (
    TopicAnalysisService,
    TopicSuggestionService,
    dashboard_counts,
    save_topic,
    topic_detail_view,
    validate_youtube_url,
)

__all__ = [
    "TopicAnalysisService",
    "TopicSuggestionService",
    "dashboard_counts",
    "save_topic",
    "topic_detail_view",
    "validate_youtube_url",
]
