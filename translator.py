# translator.py

import logging
from typing import Optional, Tuple

import deepl
import requests

logger = logging.getLogger(__name__)


class TranslatorCascade:
    def __init__(self, deepl_api_key: Optional[str] = None):
        self.deepl_client = deepl.Translator(deepl_api_key) if deepl_api_key else None
        self.libretranslate_url = "https://libretranslate.com/translate"
        self.mymemory_url = "https://api.mymemory.translated.net/get"

        if self.deepl_client:
            logger.info("DeepL client initialized")
        else:
            logger.info("DeepL client not initialized (no API key)")

    def translate(self, text: str, target_lang: str) -> Tuple[Optional[str], str]:
        """
        Attempts translation through cascade of free APIs.
        Returns (translated_text, service_used) or (None, error_message)
        """
        logger.info(f"Translation request: '{text[:50]}...' to {target_lang}")

        # Try DeepL
        if self.deepl_client:
            result = self._try_deepl(text, target_lang)
            if result:
                logger.info(f"DeepL translation successful")
                return result, "DeepL"
            logger.warning("DeepL translation failed, trying LibreTranslate")

        # Try LibreTranslate
        result = self._try_libretranslate(text, target_lang)
        if result:
            logger.info(f"LibreTranslate translation successful")
            return result, "LibreTranslate"
        logger.warning("LibreTranslate translation failed, trying MyMemory")

        # Try MyMemory
        result = self._try_mymemory(text, target_lang)
        if result:
            logger.info(f"MyMemory translation successful")
            return result, "MyMemory"

        logger.error("All translation services failed")
        return None, "Translation failed, all services exhausted."

    def _try_deepl(self, text: str, target_lang: str) -> Optional[str]:
        try:
            logger.info(f"Attempting DeepL translation to {target_lang}")
            # DeepL uses uppercase codes (EN, ES, FR, etc.)
            # Some languages need specific variants (EN-US, EN-GB, PT-BR, PT-PT)
            target = target_lang.upper()

            # Handle special cases
            if target == "EN":
                target = "EN-US"
            elif target == "PT":
                target = "PT-PT"

            result = self.deepl_client.translate_text(
                    text,
                    target_lang=target
            )
            logger.info(f"DeepL returned: {result.text[:50]}...")
            return result.text
        except deepl.exceptions.QuotaExceededException as e:
            logger.warning(f"DeepL quota exceeded: {e}")
            return None
        except deepl.exceptions.AuthorizationException as e:
            logger.error(f"DeepL auth failed: {e}")
            return None
        except Exception as e:
            logger.error(f"DeepL error: {type(e).__name__}: {e}")
            return None

    def _try_libretranslate(self, text: str, target_lang: str) -> Optional[str]:
        try:
            logger.info(f"Attempting LibreTranslate translation to {target_lang}")
            response = requests.post(
                    self.libretranslate_url,
                    json={
                        "q": text,
                        "target": target_lang,
                        "source": "auto",
                        "format": "text"
                    },
                    timeout=10
            )
            logger.info(f"LibreTranslate status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                translated = data.get("translatedText")
                if translated:
                    logger.info(f"LibreTranslate returned: {translated[:50]}...")
                    return translated
                else:
                    logger.warning(f"LibreTranslate response missing translatedText: {data}")
            else:
                logger.warning(f"LibreTranslate failed: {response.status_code} - {response.text}")
        except requests.exceptions.Timeout as e:
            logger.error(f"LibreTranslate timeout: {e}")
        except Exception as e:
            logger.error(f"LibreTranslate error: {type(e).__name__}: {e}")
        return None

    def _try_mymemory(self, text: str, target_lang: str) -> Optional[str]:
        try:
            logger.info(f"Attempting MyMemory translation to {target_lang}")
            response = requests.get(
                    self.mymemory_url,
                    params={
                        "q": text,
                        "langpair": f"auto|{target_lang}"
                    },
                    timeout=10
            )
            logger.info(f"MyMemory status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                logger.info(f"MyMemory response: {data}")

                if data.get("responseStatus") == 200:
                    translated = data["responseData"]["translatedText"]
                    logger.info(f"MyMemory returned: {translated[:50]}...")
                    return translated
                else:
                    logger.warning(f"MyMemory responseStatus: {data.get('responseStatus')}")
            else:
                logger.warning(f"MyMemory failed: {response.status_code} - {response.text}")
        except requests.exceptions.Timeout as e:
            logger.error(f"MyMemory timeout: {e}")
        except Exception as e:
            logger.error(f"MyMemory error: {type(e).__name__}: {e}")
        return None
