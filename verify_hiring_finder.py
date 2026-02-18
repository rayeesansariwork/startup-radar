import asyncio
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

# Load environment variables
load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)

from services.hiring_page_finder import HiringPageFinderService

async def test_finder():
    print("🚀 Starting HiringPageFinder Service Test")
    
    # Check keys
    if not os.getenv("SERPER_API_KEY"):
        print("❌ SERPER_API_KEY not found")
        return
    if not os.getenv("MISTRAL_API_KEY"):
        print("❌ MISTRAL_API_KEY not found")
        return

    finder = HiringPageFinderService()
    
    # Test with a known company
    test_company = "https://linear.app"
    print(f"\n🔍 Testing with: {test_company}")
    
    try:
        # Run sync method in executor to simulate async behavior in main.py
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, finder.find_hiring_page, test_company)
        
        print("\n✅ Result:")
        print(f"Career URL: {result.get('career_page_url')}")
        
        jobs = result.get('jobs', [])
        print(f"Jobs Found: {len(jobs)}")
        
        if jobs:
            print("\nFirst 3 jobs:")
            for job in jobs[:3]:
                print(f"- {job.get('title', 'No Title')} ({job.get('location', 'No Location')})")
        else:
            print("⚠️ No jobs found or extraction failed.")
            if "error" in result:
                print(f"Error: {result['error']}")

    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_finder())
