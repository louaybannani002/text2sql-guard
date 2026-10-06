"""Single import point for LiteLLM, configured for a server process.

Import ``litellm`` and its exceptions from here, never directly, so the settings below always
apply first.
"""

import os

# Use the price map bundled with the installed version instead of fetching it from GitHub at
# import time: no network on start-up, and costs are reproducible for a given lockfile.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from litellm.exceptions import RateLimitError, Timeout

litellm.suppress_debug_info = True
litellm.telemetry = False

__all__ = ["RateLimitError", "Timeout", "litellm"]
