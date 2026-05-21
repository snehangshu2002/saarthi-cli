"""
providers.py
All LangChain provider imports are isolated here.
main.py never imports any provider directly.
"""

SUPPORTED_PROVIDERS = {
    "mistral": "Mistral AI",
    "openai":  "OpenAI",
    "google":  "Google Gemini",
    "anthropic": "Anthropic Claude",
    "ollama": "Ollama (Local)",
}

_PROVIDER_PACKAGES = {
    "mistral": "langchain-mistralai",
    "openai":  "langchain-openai",
    "google":  "langchain-google-genai",
    "anthropic": "langchain-anthropic",
    "ollama": "langchain-ollama",
}

DEFAULT_MODELS = {
    "mistral": "mistral-large-latest",
    "openai": "gpt-4o",
    "google": "gemini-2.0-flash",
    "anthropic": "claude-sonnet-4-5",
    "ollama": "llama3.2",
}

PROVIDER_MODELS = {
    "mistral": [
        "mistral-large-latest",
        "mistral-medium-latest",
        "mistral-small-latest",
        "codestral-latest",
        "open-mixtral-8x22b",
        "open-mistral-nemo",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "o1",
        "o1-mini",
        "o1-preview",
        "o3-mini",
    ],
    "google": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-pro-preview-05-06",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ],
    "anthropic": [
        "claude-sonnet-4-5",
        "claude-opus-4-5",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest",
        "claude-3-haiku-20240307",
    ],
    "ollama": [
        "llama3.2",
        "llama3.1",
        "llama3",
        "mistral",
        "mistral-nemo",
        "phi4",
        "phi3",
        "gemma2",
        "gemma2:2b",
        "codegemma",
        "deepseek-r1",
        "qwen2.5",
        "qwen2.5-coder",
        "nomic-embed-text",
    ],
}


from langchain_core.embeddings import Embeddings
import hashlib
import math

ACTIVE_CHAT_MODEL = None

class DeterministicFakeEmbeddings(Embeddings):
    """
    A pure-python deterministic fake embedding model.
    Generates consistent vectors based on string content hashing.
    """
    def __init__(self, dimensionality: int = 768):
        self.dimensionality = dimensionality

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = []
        for i in range(self.dimensionality):
            val = hashlib.sha256(h + i.to_bytes(4, "big")).digest()
            vec.append(float(val[0]) / 255.0 - 0.5)
        # Normalize vector to unit length
        sq_sum = sum(x * x for x in vec)
        norm = math.sqrt(sq_sum)
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


def get_models(
    provider: str,
    api_key: str,
    model_name: str = None,
    embedding_provider: str = None,
    embedding_model: str = None,
    api_keys: dict = None,
):
    """
    Returns (chat_model, embedding_model, embedding_dims) for the given provider and configuration.
    Imports are lazy — only required provider packages are imported.
    """
    if not provider or provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider: '{provider}'. "
            f"Choose from: {list(SUPPORTED_PROVIDERS.keys())}"
        )

    # For Ollama, api key is not required. For others, it's checked either from api_key or api_keys dict.
    active_key = api_key
    if api_keys and provider in api_keys and api_keys[provider]:
        active_key = api_keys[provider]

    if provider != "ollama" and (not active_key or not active_key.strip()):
        raise ValueError(
            f"API key for '{provider}' is empty. "
            f"Run /settings edit or edit settings.json to add your key."
        )

    # Resolve model name
    active_model = model_name or DEFAULT_MODELS.get(provider)

    # 1. Instantiate Chat Model
    if provider == "mistral":
        try:
            from langchain_mistralai import ChatMistralAI
        except ImportError:
            raise ImportError(
                "The 'langchain-mistralai' package is not installed. "
                "Run: pip install langchain-mistralai"
            )
        chat = ChatMistralAI(api_key=active_key, model=active_model)

    elif provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError(
                "The 'langchain-openai' package is not installed. "
                "Run: pip install langchain-openai"
            )
        chat = ChatOpenAI(api_key=active_key, model=active_model)

    elif provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError(
                "The 'langchain-google-genai' package is not installed. "
                "Run: pip install langchain-google-genai"
            )
        chat = ChatGoogleGenerativeAI(google_api_key=active_key, model=active_model)

    elif provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError(
                "The 'langchain-anthropic' package is not installed. "
                "Run: pip install langchain-anthropic"
            )
        chat = ChatAnthropic(api_key=active_key, model=active_model)

    elif provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "The 'langchain-ollama' package is required for Ollama. "
                "Run: pip install langchain-ollama"
            )
        chat = ChatOllama(model=active_model)

    # 2. Instantiate Embedding Model
    # Default embedding provider to chat provider if not specified, except anthropic which defaults to local
    active_embed_provider = embedding_provider
    if not active_embed_provider or active_embed_provider == "anthropic":
        if provider == "anthropic":
            active_embed_provider = "local"
        else:
            active_embed_provider = provider

    # Helper to get the correct API key for embedding provider
    def get_embed_key(p):
        if api_keys and p in api_keys and api_keys[p]:
            return api_keys[p]
        return active_key if p == provider else ""

    if active_embed_provider == "mistral":
        try:
            from langchain_mistralai import MistralAIEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-mistralai' package is not installed for embeddings. "
                "Run: pip install langchain-mistralai"
            )
        embed_key = get_embed_key("mistral")
        if not embed_key:
            raise ValueError("API key for Mistral embeddings is missing.")
        embed = MistralAIEmbeddings(api_key=embed_key)
        dims = 1024

    elif active_embed_provider == "openai":
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-openai' package is not installed for embeddings. "
                "Run: pip install langchain-openai"
            )
        embed_key = get_embed_key("openai")
        if not embed_key:
            raise ValueError("API key for OpenAI embeddings is missing.")
        active_embed_model = embedding_model or "text-embedding-3-small"
        embed = OpenAIEmbeddings(api_key=embed_key, model=active_embed_model)
        dims = 3072 if active_embed_model == "text-embedding-3-large" else 1536

    elif active_embed_provider == "google":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-google-genai' package is not installed for embeddings. "
                "Run: pip install langchain-google-genai"
            )
        embed_key = get_embed_key("google")
        if not embed_key:
            raise ValueError("API key for Google embeddings is missing.")
        embed = GoogleGenerativeAIEmbeddings(google_api_key=embed_key, model=embedding_model or "models/embedding-001")
        dims = 768

    elif active_embed_provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-ollama' package is not installed for Ollama embeddings. "
                "Run: pip install langchain-ollama"
            )
        embed = OllamaEmbeddings(model=embedding_model or "nomic-embed-text")
        dims = 768

    else:
        # local / fallback
        embed = DeterministicFakeEmbeddings()
        dims = 768

    return chat, embed, dims