import time
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("AutoExtractorSeNaSA")

def obtener_token_fresco():
    logger.info("🌐 Abriendo navegador headless e interactuando con SeNaSA para obtener el JWT...")
    token = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        page = context.new_page()

        def handle_request(request):
            nonlocal token
            headers = request.headers
            if "authorization" in headers and "Bearer" in headers["authorization"]:
                val = headers["authorization"].replace("Bearer ", "").strip()
                if val and val != "null" and len(val) > 20:
                    token = val

        page.on("request", handle_request)

        try:
            page.goto("https://ova.arssenasa.gob.do/", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # Intenta hacer clic en elementos comunes o enviar un formulario de consulta para forzar la petición API
            button = page.locator("button, a, input[type='button'], input[type='submit']").first
            if button.is_visible():
                button.click()
                time.sleep(3)
        except Exception as e:
            logger.warning(f"⚠️ Evento de interacción: {e}")

        browser.close()

    if token:
        logger.info("🔑 Token Bearer válido capturado exitosamente.")
    else:
        logger.error("❌ No se pudo interceptar el token automáticamente.")
    return token

if __name__ == "__main__":
    token = obtener_token_fresco()
    if token:
        print(f"\nTOKEN_BEARER = \"{token}\"\n")