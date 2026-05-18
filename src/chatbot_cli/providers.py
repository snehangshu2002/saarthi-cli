"""
providers.py
All LangChain provider imports are isolated here.
main.py never imports any provider directly.
"""

SUPPORTED_PROVIDERS = {
    "mistral": "Mistral AI  (mistral-large-latest)",
    "openai":  "OpenAI      (gpt-4o)",
    "google":  "Google      (gemini-1.5-flash)",
}

_PROVIDER_PACKAGES = {
    "mistral": "langchain-mistralai",
    "openai":  "langchain-openai",
    "google":  "langchain-google-genai",
}


def get_models(provider: str, api_key: str):
    """
    Returns (chat_model, embedding_model, embedding_dims) for the given provider.
    Imports are lazy — only the chosen provider's package is imported.

    Raises:
        ValueError: If the provider is not supported or api_key is empty.
        ImportError: If the required provider package is not installed.
        Exception: Propagated from the provider SDK on auth/init failure.
    """
    if not provider or provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider: '{provider}'. "
            f"Choose from: {list(SUPPORTED_PROVIDERS.keys())}"
        )

    if not api_key or not api_key.strip():
        raise ValueError(
            f"API key for '{provider}' is empty. "
            f"Run /settings or edit settings.json to add your key."
        )

    if provider == "mistral":
        try:
            from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-mistralai' package is not installed. "
                "Run: pip install langchain-mistralai"
            )
        chat  = ChatMistralAI(api_key=api_key)
        embed = MistralAIEmbeddings(api_key=api_key)
        dims  = 1024
        return chat, embed, dims

    elif provider == "openai":
        try:
            from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-openai' package is not installed. "
                "Run: pip install langchain-openai"
            )
        chat  = ChatOpenAI(api_key=api_key, model="gpt-4o")
        embed = OpenAIEmbeddings(api_key=api_key, model="text-embedding-3-small")
        dims  = 1536
        return chat, embed, dims

    elif provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
        except ImportError:
            raise ImportError(
                "The 'langchain-google-genai' package is not installed. "
                "Run: pip install langchain-google-genai"
            )
        chat  = ChatGoogleGenerativeAI(google_api_key=api_key, model="gemini-1.5-flash")
        embed = GoogleGenerativeAIEmbeddings(google_api_key=api_key, model="models/embedding-001")
        dims  = 768
        return chat, embed, dims