# settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # ND OAuth
    ND_CLIENT_ID: str = Field(..., description="NetDocuments Client ID")
    ND_CLIENT_SECRET: str = Field(..., description="NetDocuments Client Secret")
    ND_REDIRECT_URI: str = Field(..., description="Registered redirect URI (e.g., your Replit /oauth/callback)")
    ND_OAUTH_SCOPE: str = Field("read", description="OAuth scope; 'read' for view-only")

    ND_AUTH_AUTHORIZE_URL: str = Field("https://vault.netvoyage.com/neWeb2/OAuth.aspx")
    ND_AUTH_TOKEN_URL: str = Field("https://api.vault.netvoyage.com/v1/OAuth")
    ND_API_BASE: str = Field("https://api.vault.netvoyage.com/v1")

    # Server
    SERVER_HOST: str = Field("0.0.0.0")
    SERVER_PORT: int = Field(8000)

    # Internal SSE port for FastMCP
    INTERNAL_SSE_PORT: int = Field(9000)

    # Behavior
    SEARCH_DEFAULT_TOP: int = Field(50)
    SEARCH_DEFAULT_ORDER: str = Field("relevance")  # or 'lastMod'
    MAX_FETCH_CHARS: int = Field(150_000)
    ENABLE_DOCX: bool = Field(True)

    # pydantic-settings v2 style config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

settings = Settings()
