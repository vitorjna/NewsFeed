import sys
import json
import trafilatura
from datetime import datetime

# ANSI escape codes for colored output
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

def print_header(text):
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE} {text.center(58)} {RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}\n")

def test_trafilatura(url):
    """
    Independent script to test trafilatura extraction capabilities.
    Fetches a URL, extracts metadata and full content, and displays it.
    """
    # Ensure UTF-8 output on Windows terminals
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    try:
        print(f"{YELLOW}>>> Fetching content from:{RESET} {BOLD}{url}{RESET}")
        
        start_time = datetime.now()
        downloaded = trafilatura.fetch_url(url)
        
        if not downloaded:
            print(f"{YELLOW}[WARNING] Trafilatura fetch failed. Trying fallback with requests...{RESET}")
            import requests
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.google.com/',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-User': '?1'
            }
            try:
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                downloaded = response.text
                print(f"{GREEN}[SUCCESS] Requests fallback downloaded content successfully.{RESET}")
            except Exception as req_e:
                print(f"{YELLOW}[WARNING] Requests fallback failed ({req_e}). Trying 2nd fallback with cloudscraper...{RESET}")
                try:
                    import cloudscraper
                    scraper = cloudscraper.create_scraper()
                    response = scraper.get(url, timeout=15)
                    response.raise_for_status()
                    downloaded = response.text
                    print(f"{GREEN}[SUCCESS] Cloudscraper fallback downloaded content successfully.{RESET}")
                except ImportError:
                    print(f"{RED}[ERROR] cloudscraper is not installed. Please run: pip install cloudscraper{RESET}")
                    return
                except Exception as cs_e:
                    print(f"{RED}[ERROR] Could not download content even with cloudscraper: {cs_e}{RESET}")
                    return

        # Extract as JSON to get both content and metadata easily
        result_json_str = trafilatura.extract(
            downloaded, 
            output_format='json',
            include_comments=False,
            include_tables=True,
            no_fallback=False
        )
        
        if not result_json_str:
            print(f"{RED}[ERROR] Trafilatura failed to extract any meaningful content.{RESET}")
            return

        data = json.loads(result_json_str)
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print_header("METADATA")
        
        fields = [
            ("Title", "title"),
            ("Author", "author"),
            ("Date", "date"),
            ("Site", "sitename"),
            ("Language", "language"),
            ("Description", "description")
        ]
        
        for label, key in fields:
            value = data.get(key)
            print(f"{BOLD}{GREEN}{label+':':<12}{RESET} {value if value else 'N/A'}")
        
        print(f"{BOLD}{GREEN}Extraction:{RESET} Took {duration:.2f} seconds")

        print_header("FULL CONTENT")
        
        content = data.get("text", "")
        if content:
            print(content)
        else:
            print(f"{RED}No text content extracted.{RESET}")
            
        print_header("EXTRACTION FINISHED")

    except Exception as e:
        print(f"{RED}[CRITICAL ERROR] An unexpected error occurred: {e}{RESET}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"\n{BOLD}{YELLOW}Usage:{RESET} python test_trafilatura.py <URL>")
        print(f"{DIM}Example: python test_trafilatura.py https://example.com/article{RESET}\n")
    else:
        # Check if the URL has a protocol
        url = sys.argv[1]
        if not url.startswith(('http://', 'https://')):
            print(f"{YELLOW}[WARNING] URL doesn't start with http:// or https://. Adding https://{RESET}")
            url = 'https://' + url
            
        test_trafilatura(url)
