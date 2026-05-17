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


def get_models(provider: str, api_key: str):
    """
    Returns (chat_model, embedding_model, embedding_dims) for the given provider.
    Imports are lazy — only the chosen provider's package is imported.
    """
    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
        chat  = ChatMistralAI(api_key=api_key)
        embed = MistralAIEmbeddings(api_key=api_key)
        dims  = 1024
        return chat, embed, dims

    elif provider == "openai":
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        chat  = ChatOpenAI(api_key=api_key, model="gpt-4o")
        embed = OpenAIEmbeddings(api_key=api_key, model="text-embedding-3-small")
        dims  = 1536
        return chat, embed, dims

    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
        chat  = ChatGoogleGenerativeAI(google_api_key=api_key, model="gemini-1.5-flash")
        embed = GoogleGenerativeAIEmbeddings(google_api_key=api_key, model="models/embedding-001")
        dims  = 768
        return chat, embed, dims

    else:
        raise ValueError(
            f"Unsupported provider: '{provider}'. "
            f"Choose from: {list(SUPPORTED_PROVIDERS.keys())}"
        )