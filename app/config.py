import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Dict, Any, Optional

class FilterConfig(BaseSettings):
    """Configuration for security filters"""
    enabled: bool = True
    max_tokens: int = 8192
    allowed_models: List[str] = [
        "gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "gpt-4.1",  "gpt-4o", "gpt-4o-mini", "text-embedding-ada-002",
        "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307",
        "claude-3-5-sonnet-20240620", "claude-3-7-sonnet-20250219"
    ]
    blocked_prompts: List[str] = []
    rate_limit: int = 100  # requests per minute

class LoggingConfig(BaseSettings):
    """Configuration for logging"""
    level: str = "INFO"
    log_requests: bool = True
    log_responses: bool = True
    log_tokens: bool = False  # Don't log tokens by default for privacy
    log_file: Optional[str] = None

class Settings(BaseSettings):
    """Main application settings"""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_org_id: str = ""  # Add organization ID field
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_version: str = "2023-06-01"
    filters: FilterConfig = FilterConfig()
    logging: LoggingConfig = LoggingConfig()
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore"
    )
    
    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_openai_api_key(cls, v):
        """Validate OpenAI API key from environment"""
        if not v:
            return os.environ.get("OPENAI_API_KEY", "")
        return v
    
    @field_validator("openai_org_id", mode="before")
    @classmethod
    def validate_openai_org_id(cls, v):
        """Validate OpenAI organization ID from environment"""
        if not v:
            return os.environ.get("OPENAI_ORG_ID", "")
        return v
    
    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def validate_anthropic_api_key(cls, v):
        """Validate Anthropic API key from environment"""
        if not v:
            return os.environ.get("ANTHROPIC_API_KEY", "")
        return v
    
    def get_openai_headers(self) -> Dict[str, str]:
        """Get headers for OpenAI API requests"""
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }
        # Add organization header if present
        if self.openai_org_id:
            headers["OpenAI-Organization"] = self.openai_org_id
        return headers
    
    def get_anthropic_headers(self) -> Dict[str, str]:
        """Get headers for Anthropic API requests"""
        headers = {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": self.anthropic_version,
            "Content-Type": "application/json",
        }
        return headers 