"""!
@file deploy/healthcheck.py
@brief Controllo di salute del container della prova Docker.

Interroga l'endpoint di salute del servizio locale, senza proxy, e termina con
codice 0 solo se il servizio è in modalità solo locale con OCR e NER pronti e
un solo worker.
"""

import json
import sys
from urllib.request import ProxyHandler, build_opener


def main():
    """!
    @brief Esegue il controllo di salute.
    @return 0 se il servizio è pronto, 1 in ogni altro caso, errori compresi.
    """
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open("http://127.0.0.1:18765/api/health", timeout=3) as response:
            state = json.loads(response.read(16_384))
        ready = (
            state.get("mode") == "local_only"
            and state.get("ocr") == "ready"
            and state.get("ner") == "ready"
            and state.get("workers") == 1
        )
        return 0 if ready else 1
    except (OSError, ValueError, TypeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
