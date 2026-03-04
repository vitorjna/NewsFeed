import os
import sys
import io

# Force UTF-8 encoding for output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add current directory to path so we can import src as a package
sys.path.append(os.getcwd())

from src.analyzer_llm import NewsAnalyzer
from src.config import load_config
from src.article import Article

def test_llm_instructions():
    config_obj = load_config()
    analyzer = NewsAnalyzer(config_obj.llm, config_obj.embeddings)

    test_articles = [
        {
            "title": "German Chancellor visits the US",
            "content": """In a major diplomatic move, the German Chancellor arrived in Washington today for high-level talks with top US officials regarding international trade agreements and mutual security concerns. The visit highlights the strong and enduring ties between the two nations, emphasizing a shared commitment to democratic values and economic stability. During the press conference, the Chancellor discussed the importance of multilateralism in solving global challenges such as climate change, energy security, and the future of regional alliances. Both delegations expressed optimism about the outcomes of the meetings, which are expected to lead to new frameworks for cooperation in technology and defense. The Chancellor is scheduled to meet with several business leaders tomorrow to discuss potential investments in sustainable energy projects, further cementing the economic partnership. This visit comes at a critical time for global diplomacy, as both countries seek to navigate a complex international landscape marked by shifting power dynamics and economic uncertainties. The Chancellor's agenda remains packed with meetings focused on improving bilateral relations and addressing the most pressing issues of the day.""",
            "test_desc": "Test Case 1: Outdated Name (Should not add 'Olaf Scholz')",
            "negative_checks": ["Olaf Scholz", "Scholz"]
        },
        {
            "title": "Donald Trump makes a speech in Florida",
            "content": """Donald Trump addressed a large and enthusiastic crowd in Florida today, discussing a wide range of economic policies and laying out his future plans for the country's development. He spoke at length about the critical importance of domestic manufacturing, job creation, and the need to protect national industries from foreign competition. The speech, which lasted over an hour, touched upon topics such as infrastructure revitalisation, education reform, and energy independence. Trump's supporters cheered as he reiterated his commitment to the principles that have defined his political career, focusing on American workers and the middle class. He also addressed recent developments in international trade and highlighted what he described as the successes of his previous initiatives. The event was held at a prominent venue in Palm Beach and attracted significant media attention, with many analysts noting the potential impact of his remarks on the upcoming political cycle. As the event concluded, Trump promised to continue his advocacy for the issues he believes are most vital to the nation's prosperity and security.""",
            "test_desc": "Test Case 2: Outdated Title (Should not add 'former President' or 'President' if not in text)",
            "negative_checks": ["former President", "President Trump"]
        },
        {
            "title": "Chancellor Friedrich Merz announces new policy",
            "content": """Chancellor Friedrich Merz announced a comprehensive new economic policy today aimed at significantly reducing inflation and stimulating long-term growth. Merz stated that the measures, which include targeted tax cuts and increased investment in digital infrastructure, would take effect immediately and are designed to provide relief to households and businesses alike. The announcement was made during a televised address from the Chancellery, where Merz emphasized the need for fiscal responsibility and structural reforms to ensure the country's competitiveness in a rapidly changing global economy. He also spoke about the importance of fostering innovation and supporting small and medium-sized enterprises, which he called the backbone of the national economy. Public reaction to the news has been mixed, with some economists praising the Chancellor's bold approach while others express concern about the potential impact on the national budget. Merz concluded his remarks by reaffirming his government's dedication to building a prosperous and resilient future for all citizens, calling for national unity in the face of economic challenges.""",
            "test_desc": "Test Case 3: Correct Usage (Should preserve 'Chancellor Friedrich Merz')",
            "positive_checks": ["Chancellor Friedrich Merz", "Merz"]
        },
        {
            "title": "Trump orders federal agencies to drop Anthropic’s AI",
            "content": """On Friday afternoon, Donald Trump posted on Truth Social, accusing Anthropic, the AI company behind Claude, of attempting to “STRONG-ARM” the Pentagon and directing federal agencies to “IMMEDIATELY CEASE” use of its products. At issue is Anthropic CEO Dario Amodei’s refusal of an updated agreement with the US military agreeing to “any lawful use” of Anthropic’s technology, as Defense Secretary Pete Hegseth mandated in a January memo, to the frustration of many tech workers across the industry.
Anthropic has refused to agree to the Pentagon’s demand to allow ‘any lawful use’ of its AI.
As we explained earlier this week, that agreement would give the US military access to use the company’s services for mass domestic surveillance and lethal autonomous weapons, or AI that has full power to track and kill targets with no humans involved in the decision-making process. OpenAI and xAI have reportedly already agreed to the new terms, though OpenAI is reportedly looking to negotiate with the Pentagon to adopt the same red lines as Anthropic.
For weeks, Anthropic and the Pentagon have been locked in a stalemate regarding the acceptable use of Anthropic’s AI technology. But negotiations with Anthropic had stalled after a dramatic exchange of public statements and social media posts.
In a statement Thursday, Amodei wrote that the Pentagon’s “threats do not change our position: we cannot in good conscience accede to their request.” He added that Anthropic has “never raised objections to particular military operations nor attempted to limit use of our technology in an ad hoc manner” but that in a “narrow set of cases, we believe AI can undermine, rather than defend, democratic values.”
Amodei went on to say that “should the Department choose to offboard Anthropic, we will work to enable a smooth transition to another provider, avoiding any disruption to ongoing military planning, operations, or other critical missions. Our models will be available on the expansive terms we have proposed for as long as required.”
Now we have Trump’s response:
THE UNITED STATES OF AMERICA WILL NEVER ALLOW A RADICAL LEFT, WOKE COMPANY TO DICTATE HOW OUR GREAT MILITARY FIGHTS AND WINS WARS! That decision belongs to YOUR COMMANDER-IN-CHIEF, and the tremendous leaders I appoint to run our Military.
The Leftwing nut jobs at Anthropic have made a DISASTROUS MISTAKE trying to STRONG-ARM the Department of War, and force them to obey their Terms of Service instead of our Constitution. Their selfishness is putting AMERICAN LIVES at risk, our Troops in danger, and our National Security in JEOPARDY.
Therefore, I am directing EVERY Federal Agency in the United States Government to IMMEDIATELY CEASE all use of Anthropic’s technology. We don’t need it, we don’t want it, and will not do business with them again! There will be a Six Month phase out period for Agencies like the Department of War who are using Anthropic’s products, at various levels. Anthropic better get their act together, and be helpful during this phase out period, or I will use the Full Power of the Presidency to make them comply, with major civil and criminal consequences to follow.
WE will decide the fate of our Country — NOT some out-of-control, Radical Left AI company run by people who have no idea what the real World is all about. Thank you for your attention to this matter. MAKE AMERICA GREAT AGAIN!""",
            "test_desc": "Test Case 4: Correct Usage (Should preserve 'Donald Trump'. Should not add 'former President' or 'President' if not in text)",
            "positive_checks": ["Donald Trump", "Trump"],
            "negative_checks": ["former", "President"]
        }
    ]

    for test in test_articles:
        if "Chancellor" in test["title"]:
            continue

        print(f"\n--- {test['test_desc']} ---")
        # Create a mock article object
        article_inst = Article(
            title=test['title'],
            link="http://example.com",
            rss_summary=test['content'],
            rss_date="2026-03-04",
            source_feed="Test",
            source_name="Test",
            theme="World"
        )
        article_inst.full_content = test['content']

        result = analyzer.generate_summaries(article_inst.title, article_inst.full_content, language="English")

        short_s = result.get('short_summary', '')
        long_s = result.get('long_summary', '')

        print(f"Short Summary: {short_s}")
        print(f"Long Summary: {long_s}")

        if 'negative_checks' in test:
            for check in test['negative_checks']:
                if check.lower() in long_s.lower() or check.lower() in short_s.lower():
                    print(f"FAILED: Found '{check}' in summary.")
                else:
                    print(f"PASSED: '{check}' not found.")

        if 'positive_checks' in test:
            for check in test['positive_checks']:
                if check.lower() in long_s.lower() or check.lower() in short_s.lower():
                    print(f"PASSED: Found '{check}' in summary.")
                else:
                    print(f"FAILED: '{check}' not found.")

if __name__ == "__main__":
    test_llm_instructions()
