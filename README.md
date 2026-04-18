# News Feed Application

A generic, automated news feed application that fetches news from RSS feeds, analyzes them using an LLM, and publishes relevant summaries to Telegram channels.

## Features
- **RSS Feed Aggregation**: Fetches news from multiple sources. Custom source names and content download fallbacks (Requests, Cloudscraper) ensure reliable parsing.
- **Resilient Multi-LLM Setup**: Supports local/remote providers (LM Studio, Ollama, OpenAI-compatible). Configure primary, secondary, and embedding models, each with backup/fallback models to ensure continuous processing during API failures.
- **Phased Article Processing**: Article processing is split into discrete stages saved in the database, allowing the workflow to safely pause and resume without losing progress.
- **Smart Analysis**: Scores news for relevance, importance, and urgency. Rejects short or irrelevant articles early to save time and processing resources.
- **Advanced Duplicate Detection**: Uses embeddings for fuzzy matching to detect if a similar article was already published, with a configurable historical search window (in days).
- **Hashtags Generation**: Automatically generates relevant hashtags for articles.
- **Telegram Integration**: Posts a short summary with an image and reliably forwards a detailed follow-up to discussion groups.
- **Automated Maintenance**: Auto-deletes old log/stats files daily, creates daily database backups, and runs SQLite database optimizations/auto-vacuum.
- **Flexible Paths & Statistics**: Specify custom directories for logs, stats, and backups. Daily export of statistics categorized by theme.
- **Dockerized & Resilient**: Easy to deploy 24/7 with auto-restart, auto-heal healthchecks, LLM timeouts, and retry delays.
- **Dev Mode**: Run the entire processing pipeline without publishing to Telegram, perfect for testing new features and prompts safely.

## Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd NewsFeed
   ```

2. **Configuration**:
   Copy `config/config.example.yaml` to `config/config.yaml` and fill in your details:
   - `telegram_bot_token`: Your Telegram Bot Token (from @BotFather).
   - `llm`: Configure your local/remote provider endpoints and models, including backups for primary, secondary, and embedding tasks.
   - `logs_folder` / `stats_folder` / `backup_folder`: Customize paths for operational files.
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
