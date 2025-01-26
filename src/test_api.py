import requests
import logging
from requests.exceptions import RequestException

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Update deze URL met je Railway URL
BASE_URL = "https://lss-training-assistant-production.up.railway.app"

def test_api():
    try:
        # Test health endpoint
        logger.info("Testing health endpoint...")
        response = requests.get(f"{BASE_URL}/health")
        response.raise_for_status()
        print("Health check response:", response.json())

        # Test vraag endpoint
        logger.info("Testing vraag endpoint...")
        test_vraag = "Wat is de totale omzet deze maand?"
        response = requests.post(
            f"{BASE_URL}/vraag",
            json={"vraag": test_vraag}
        )
        response.raise_for_status()
        print("\nVraag:", test_vraag)
        print("Response:", response.json())

    except RequestException as e:
        logger.error(f"Network error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    test_api() 