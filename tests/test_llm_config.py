import sys
import os
from unittest.mock import MagicMock, patch

# Add the project root to sys.path so we can import src as a package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import types

# Mock utils module properly as a submodule of src
utils_mock = types.ModuleType('src.utils')
utils_mock.setup_logger = MagicMock(return_value=MagicMock())
utils_mock.extract_json = MagicMock(side_effect=lambda x: x)
utils_mock.extract_retry_delay = MagicMock(return_value=1)
sys.modules['src.utils'] = utils_mock

from src.config import LLMConfig, EmbeddingConfig
from src.analyzer_llm import NewsAnalyzer

def test_config_initialization():
    print("Testing NewsAnalyzer initialization...")
    llm_config = LLMConfig(
        primary_api_key="p-key",
        primary_base_url="http://primary/v1",
        primary_model="p-model",
        primary_timeout=120,
        primary_backup_api_key="pb-key",
        primary_backup_base_url="http://pb/v1",
        primary_backup_model="pb-model",
        primary_backup_timeout=120,
        secondary_api_key="s-key",
        secondary_base_url="http://secondary/v1",
        secondary_model="s-model",
        secondary_timeout=60,
        secondary_backup_api_key="sb-key",
        secondary_backup_base_url="http://sb/v1",
        secondary_backup_model="sb-model",
        secondary_backup_timeout=60
    )

    embedding_config = EmbeddingConfig(
        embedding_api_key="e-key",
        embedding_base_url="http://e/v1",
        embedding_model="e-model",
        embedding_timeout=60,
        embedding_backup_api_key="eb-key",
        embedding_backup_base_url="http://eb/v1",
        embedding_backup_model="eb-model",
        embedding_backup_timeout=60
    )

    with patch('src.analyzer_llm.OpenAI') as mock_openai:
        analyzer = NewsAnalyzer(llm_config, embedding_config)

        # Verify 6 clients created
        assert mock_openai.call_count == 6

        assert analyzer.primary_model == "p-model"
        assert analyzer.primary_backup_model == "pb-model"
        assert analyzer.secondary_model == "s-model"
        assert analyzer.secondary_backup_model == "sb-model"
        assert analyzer.embedding_model == "e-model"
        assert analyzer.embedding_backup_model == "eb-model"
        print("[PASS] Initialization test passed")

def test_client_usage():
    print("Testing NewsAnalyzer client usage...")
    llm_config = LLMConfig(
        primary_api_key="p-key", primary_base_url="http://p", primary_model="p-m", primary_timeout=120,
        secondary_api_key="s-key", secondary_base_url="http://s", secondary_model="s-m", secondary_timeout=120
    )
    embedding_config = EmbeddingConfig(
        embedding_api_key="e-key", embedding_base_url="http://e", embedding_model="e-m", embedding_timeout=60
    )

    with patch('src.analyzer_llm.OpenAI') as mock_openai:
        analyzer = NewsAnalyzer(llm_config, embedding_config)

        # Mock completions.create for both clients
        analyzer.primary_client.chat.completions.create = MagicMock()
        analyzer.secondary_client.chat.completions.create = MagicMock()

        # Test analyze_scores (should use primary)
        analyzer.analyze_scores("Title", "Content", "Focus")
        analyzer.primary_client.chat.completions.create.assert_called()
        print("[PASS] analyze_scores uses primary client")

        # Test generate_summaries (should use primary)
        analyzer.generate_summaries("Title", "Content")
        assert analyzer.primary_client.chat.completions.create.call_count == 2
        print("[PASS] generate_summaries uses primary client")

        # Test generate_hashtags (should use secondary)
        analyzer.generate_hashtags("Title", "Content")
        analyzer.secondary_client.chat.completions.create.assert_called()
        print("[PASS] generate_hashtags uses secondary client")
        print("[PASS] Client usage test passed")

def test_fallback_logic():
    print("Testing NewsAnalyzer fallback logic...")
    llm_config = LLMConfig(
        primary_api_key="p-key", primary_base_url="http://p", primary_model="p-m", primary_timeout=120,
        primary_backup_api_key="pb-key", primary_backup_base_url="http://pb", primary_backup_model="pb-m", primary_backup_timeout=120,
        secondary_api_key="s-key", secondary_base_url="http://s", secondary_model="s-m", secondary_timeout=60
    )
    embedding_config = EmbeddingConfig(
        embedding_api_key="e-key", embedding_base_url="http://e", embedding_model="e-m", embedding_timeout=60
    )

    with patch('src.analyzer_llm.OpenAI') as mock_openai, patch('time.sleep') as mock_sleep:
        # Create separate mocks for each call to OpenAI()
        m1, m2, m3, m4 = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        mock_openai.side_effect = [m1, m2, m3, m4]
        
        # m1: primary_client
        # m2: primary_backup_client
        # m3: secondary_client
        # m4: embedding_client
        
        analyzer = NewsAnalyzer(llm_config, embedding_config)
        
        # Verify separate mocks were assigned
        assert analyzer.primary_client == m1
        assert analyzer.primary_backup_client == m2
        
        # Mock the primary client to fail
        m1.chat.completions.create.side_effect = Exception("Primary failed")
        
        # Mock response for backup to succeed
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevance_score": 9, "importance_score": 8, "urgency_score": 7, "reasoning": "Backup worked"}'
        m2.chat.completions.create.return_value = mock_response

        # Call analyze_scores
        result = analyzer.analyze_scores("Test Title", "Test Content", "Test Focus")
        
        print(f"Result scores: R={result.relevance_score}, I={result.importance_score}, U={result.urgency_score}")
        print(f"Reasoning: {result.reasoning}")
        
        # Verify fallback
        assert result.relevance_score == 9, f"Expected 9, got {result.relevance_score}"
        assert m1.chat.completions.create.call_count >= 1
        assert m2.chat.completions.create.called
        print("[PASS] Fallback logic test passed")

def test_quota_error_no_wait():
    print("Testing NewsAnalyzer quota error logic (no wait)...")
    llm_config = LLMConfig(
        primary_api_key="p-key", primary_base_url="http://p", primary_model="p-m", primary_timeout=120,
        primary_backup_api_key="pb-key", primary_backup_base_url="http://pb", primary_backup_model="pb-m", primary_backup_timeout=120,
        secondary_api_key="s-key", secondary_base_url="http://s", secondary_model="s-m", secondary_timeout=60
    )
    embedding_config = EmbeddingConfig(
        embedding_api_key="e-key", embedding_base_url="http://e", embedding_model="e-m", embedding_timeout=60
    )

    with patch('src.analyzer_llm.OpenAI') as mock_openai, patch('time.sleep') as mock_sleep:
        m1, m2, m3, m4 = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        mock_openai.side_effect = [m1, m2, m3, m4]

        analyzer = NewsAnalyzer(llm_config, embedding_config)

        # Mock primary client to fail with a quota limit error
        m1.chat.completions.create.side_effect = Exception("429 Resource exhausted: User quota exceeded for project")

        # Mock backup client to succeed
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevance_score": 5, "importance_score": 5, "urgency_score": 5, "reasoning": "Fallback worked after quota"}'
        m2.chat.completions.create.return_value = mock_response

        # Call analyze_scores
        result = analyzer.analyze_scores("Quota Title", "Quota Content", "Test Focus")

        # Verify fallback succeeded and mock_sleep was NOT called
        assert result.relevance_score == 5, f"Expected 5, got {result.relevance_score}"
        assert m1.chat.completions.create.call_count == 1, f"Expected 1 call (no retries), got {m1.chat.completions.create.call_count}"
        assert m2.chat.completions.create.called
        assert mock_sleep.call_count == 0, f"Expected 0 calls to sleep, got {mock_sleep.call_count}"
        print("[PASS] Quota error logic test passed (no sleep, no retries on primary)")

if __name__ == "__main__":
    try:
        test_config_initialization()
        test_client_usage()
        test_fallback_logic()
        test_quota_error_no_wait()
        print("\nAll verification tests passed!")
    except Exception as e:
        print(f"\n[FAIL] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
