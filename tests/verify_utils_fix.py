import json
import sys
import os

# Set up path to include src/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

try:
    from utils import extract_json
except ImportError:
    # If project structure is different
    from src.utils import extract_json

# Ensure UTF-8 output
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

bad_json = """
{
  "is_valid_news": true,
  "rejection_reason": null,
  "short_summary": "text...",
  "long_summary": "📢 Text1."
  "💡 Text2."
  "⚠️ Text3."
}
"""

print("Running verification with actual utils.py extract_json...")
fixed_json = extract_json(bad_json)
print("Extracted/Fixed JSON:")
print(fixed_json)

try:
    data = json.loads(fixed_json)
    print("\nSUCCESS: JSON is valid.")
    print(f"Long Summary:\n{data['long_summary']}")

    # Check if merged with 2 line breaks
    if "\n\n💡 Text2." in data['long_summary'] and "\n\n⚠️ Text3." in data['long_summary']:
        print("\nSUCCESS: Merged with double line breaks correctly.")
    else:
        print("\nFAILURE: Double line breaks were not found as expected.")

except Exception as e:
    print(f"\nFAILURE: JSON is still invalid: {e}")
