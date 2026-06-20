import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    API_BASE_URL = os.getenv("API_BASE_URL", "https://api.deepseek.com/v1")
    AGENT_MODEL = os.getenv("AGENT_MODEL", "deepseek-chat")
    AGENT_TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.7"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
    CODE_EXEC_TIMEOUT = int(os.getenv("CODE_EXEC_TIMEOUT", "30"))
    MAX_ITERATIONS = 10
    MAX_TOKENS = 4096
    MEMORY_SUMMARY_THRESHOLD = 20
    REQUEST_TIMEOUT = 120

    def update(self, api_key=None, base_url=None, model=None):
        if api_key is not None: self.OPENAI_API_KEY = api_key
        if base_url is not None: self.API_BASE_URL = base_url
        if model is not None: self.AGENT_MODEL = model

config = Config()
