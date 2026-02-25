import sys
import os
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

# Robust mock for relative imports
import types
from unittest.mock import MagicMock

# Create mock utils module
utils_mock = types.ModuleType('utils')
utils_mock.setup_logger = MagicMock(return_value=MagicMock())
utils_mock.extract_json = MagicMock(side_effect=lambda x: x)

# Inject into sys.modules
sys.modules['utils'] = utils_mock
sys.modules['src.utils'] = utils_mock

# Now we can import because we've handled the external dependency
# But we still have relative imports in the files themselves.
# Let's mock the entire modules to verify the class logic
sys.modules['.utils'] = utils_mock

from config import LLMConfig
from analyzer_llm import NewsAnalyzer

def test_config_initialization():
    print("Testing NewsAnalyzer initialization...")
    config = LLMConfig(
        primary_api_key="p-key",
        primary_base_url="http://primary/v1",
        primary_model="p-model",
        secondary_api_key="s-key",
        secondary_base_url="http://secondary/v1",
        secondary_model="s-model"
    )

    with patch('analyzer_llm.OpenAI') as mock_openai:
        analyzer = NewsAnalyzer(config)

        # Verify two clients created
        assert mock_openai.call_count == 2

        # Check primary client params (first call)
        args, kwargs = mock_openai.call_args_list[0]
        assert kwargs['api_key'] == "p-key"
        assert kwargs['base_url'] == "http://primary/v1"

        # Check secondary client params (second call)
        args, kwargs = mock_openai.call_args_list[1]
        assert kwargs['api_key'] == "s-key"
        assert kwargs['base_url'] == "http://secondary/v1"

        assert analyzer.primary_model == "p-model"
        assert analyzer.secondary_model == "s-model"
        print("✅ Initialization test passed")

def test_client_usage():
    print("Testing NewsAnalyzer client usage...")
    config = LLMConfig(
        primary_api_key="p-key", primary_base_url="http://p", primary_model="p-m",
        secondary_api_key="s-key", secondary_base_url="http://s", secondary_model="s-m"
    )

    with patch('analyzer_llm.OpenAI') as mock_openai:
        analyzer = NewsAnalyzer(config)

        # Mock completions.create for both clients
        analyzer.primary_client.chat.completions.create = MagicMock()
        analyzer.secondary_client.chat.completions.create = MagicMock()

        # Test analyze_scores (should use primary)
        analyzer.analyze_scores("Title", "Content", "Focus")
        analyzer.primary_client.chat.completions.create.assert_called()
        print("✅ analyze_scores uses primary client")

        # Test analyze_summaries (should use primary)
        analyzer.analyze_summaries("Title", "Content")
        assert analyzer.primary_client.chat.completions.create.call_count == 2
        print("✅ analyze_summaries uses primary client")

        # Test check_for_duplicate (should use secondary)
        article_mock = MagicMock()
        article_mock.title = "New Title"
        article_mock.rss_summary = "New Summary"
        analyzer.check_for_duplicate(article_mock, [("Old Title", "Old Summary")])
        analyzer.secondary_client.chat.completions.create.assert_called()
        print("✅ check_for_duplicate uses secondary client")

if __name__ == "__main__":
    try:
        test_config_initialization()
        test_client_usage()
        print("\nAll verification tests passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
