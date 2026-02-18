import os
import yaml
from openai import OpenAI

def test():
    with open("config/config.yaml", "r") as f:
        config = yaml.safe_load(f)

    llm_config = config['llm']
    print(f"Testing with model: {llm_config['model']}")
    print(f"Base URL: {llm_config['base_url']}")

    client = OpenAI(
        api_key=llm_config['api_key'],
        base_url=llm_config['base_url']
    )

    try:
        response = client.chat.completions.create(
            model=llm_config['model'],
            messages=[
                {"role": "user", "content": f"SYSTEM INSTRUCTION: You are a helpful assistant. Output JSON.\n\nUSER REQUEST: Say hello in JSON format."}
            ]
        )
        print("Response received:")
        print(response.choices[0].message.content)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
