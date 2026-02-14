# News Feed Application

A generic, automated news feed application that fetches news from RSS feeds, analyzes them using an LLM, and publishes relevant summaries to Telegram channels.

## Features
- **RSS Feed Aggregation**: Fetches news from multiple sources.
- **Provider-Agnostic LLM**: Supports local providers like LM Studio and Ollama (OpenAI-compatible) for cost-effective analysis.
- **Smart Analysis**: Scores news for relevance, importance, and urgency using your preferred model.
- **Telegram Integration**: Posts a main summary with an image and a detailed follow-up comment.
- **Theme-Based**: Configurable themes (e.g., "Science", "Breaking News") with dedicated feeds and channels.
- **Dockerized**: Easy to deploy and run 24/7.

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
   - `themes`: Define your channels and their RSS feeds.
   
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
