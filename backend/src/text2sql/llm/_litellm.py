"""Single import point for LiteLLM, configured for a server process.

Import ``litellm`` and its exceptions from here, never directly, so the settings below always
apply first.
"""

import os

# Use the price map bundled with the installed version instead of fetching it from GitHub at
# import time: no network on start-up, and costs are reproducible for a given lockfile.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
# In its default "DEV" mode LiteLLM calls load_dotenv() on import, copying backend/.env (API keys
# included) into os.environ for the whole process. Configuration comes only from Settings.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

import litellm
from litellm.exceptions import RateLimitError, Timeout

litellm.suppress_debug_info = True
litellm.telemetry = False

__all__ = ["RateLimitError", "Timeout", "litellm"]
