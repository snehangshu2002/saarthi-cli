# Chatbot CLI

Terminal chatbot with LangGraph memory, multiple model providers, streaming output, session resume, and a prompt-toolkit UI.

## Run

```bash
uv run python main.py
```

After installation, the package entry point is:

```bash
uv run chatbot-cli
```

## Layout

```text
src/chatbot_cli/   Application package
data/              Local SQLite runtime data
notebooks/         Experiments and scratch notebooks
tests/             Automated tests
main.py            Local development launcher
```
