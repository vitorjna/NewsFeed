# News Feed Application

A generic, automated news feed application that fetches news from RSS feeds, analyzes them using an LLM, and publishes relevant summaries to Telegram channels.

## Features
- **RSS Feed Aggregation**: Fetches news from multiple sources. Custom source names and content download fallbacks (Requests, Cloudscraper) ensure reliable parsing.
- **Provider-Agnostic Dual LLM**: Supports local providers like LM Studio and Ollama (OpenAI-compatible). Can use a primary LLM for deep analysis/summarization and a faster secondary LLM for lighter tasks.
- **Smart Analysis**: Scores news for relevance, importance, and urgency using your preferred model. Rejects short or irrelevant articles (content size checks) before unnecessary processing to save time.
- **Advanced Duplicate Detection**: Uses embeddings to detect and reject similar articles even if they come from different feeds or were published previously.
- **Hashtags Generation**: Automatically generates relevant hashtags for articles.
- **Telegram Integration**: Posts a main summary with an image and a detailed follow-up comment.
- **Automated Maintenance**: Auto deletes old log/stats files daily and runs SQLite DB optimizations/auto-vacuum.
- **Statistics & Logging**: Daily export of statistics categorized by theme. Verbose error logs are kept for debug/analysis.
- **Dockerized & Resilient**: Easy to deploy 24/7 with auto-restart, auto-heal healthchecks, LLM timeouts, and retry delays.
- **Dev Mode**: Run the entire processing, logging, and DB storage pipeline without actually publishing to Telegram, perfect for testing new features and prompts.

## Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd NewsFeed
   ```

2. **Configuration**:
   Copy `config/config.example.yaml` to `config/config.yaml` and fill in your details:
   - `telegram_bot_token`: Your Telegram Bot Token (from @BotFather).
   - `llm`: Configure your local provider endpoint (e.g., LM Studio: `http://localhost:1234/v1` or Ollama: `http://localhost:11434/v1`) and the loaded model name.
   - `min_relevance_score` / `min_importance_score` / `min_urgency_score`: Set thresholds (0-10) for posting. An article is published if any score meets its threshold.
   - `themes`: Define your channels, RSS feeds, and `prompt_focus` for specialized filtering.

   *Note: Ensure your bot is an admin in the target channels.*

3. **Install Dependencies (Local)**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run**:
   ```bash
   python src/main.py
   ```

## Docker Deployment

1. **Build and Run**:
   ```bash
   docker-compose up -d --build
   ```

2. **Logs**:
   ```bash
   docker-compose logs -f
   ```

## Project Structure
- `src/`: Source code.
- `config/`: Configuration files.
- `data/`: SQLite database storage (persisted in Docker volume).
