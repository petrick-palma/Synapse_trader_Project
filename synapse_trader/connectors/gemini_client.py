# --- synapse_trader/connectors/gemini_client.py ---

import logging
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from synapse_trader.utils.config import settings

logger = logging.getLogger(__name__)

class GeminiClient:
    """
    Cliente para interagir com a API Google Gemini (Generative AI).
    Usado pelo AnalystBot para análise de mercado e tendências.
    """

    def __init__(self):
        self.api_key: str = settings.GEMINI_API_KEY
        if not self.api_key or "SUA_API_KEY" in self.api_key:
            logger.error("API Key do Gemini não configurada. GeminiClient ficará inativo.")
            self.model = None
            return
            
        try:
            # Configura a API
            genai.configure(api_key=self.api_key)
            
            # Configurações do modelo
            generation_config = GenerationConfig(
                temperature=0.7,
                top_p=1.0,
                top_k=1,
                max_output_tokens=2048,
            )
            
            # TODO: Considerar o modelo "gemini-1.5-flash" (mais rápido e barato)
            self.model = genai.GenerativeModel(
                model_name="gemini-pro",
                generation_config=generation_config
            )
            logger.info("Cliente Google Gemini inicializado com sucesso (modelo: gemini-pro).")
            
        except Exception as e:
            logger.error(f"Falha ao inicializar o cliente Gemini: {e}", exc_info=True)
            self.model = None

    async def prompt_async(self, text_prompt: str) -> str | None:
        """
        Envia um prompt para o modelo Gemini de forma assíncrona e retorna a resposta.
        """
        if not self.model:
            logger.warning("GeminiClient não está inicializado. A ignorar prompt.")
            return None
            
        logger.debug(f"A enviar prompt para o Gemini: '{text_prompt[:50]}...'")
        
        try:
            # Usa generate_content_async para não bloquear o loop asyncio
            response = await self.model.generate_content_async(text_prompt)
            
            if response.candidates:
                # Retorna o texto da primeira candidata
                text_response = response.candidates[0].content.parts[0].text
                logger.debug(f"Resposta recebida do Gemini: '{text_response[:50]}...'")
                return text_response
            else:
                logger.warning(f"Resposta do Gemini não contém candidatos. Prompt: {text_prompt}")
                return None
                
        except Exception as e:
            logger.error(f"Erro ao comunicar com a API Gemini: {e}", exc_info=True)
            return None