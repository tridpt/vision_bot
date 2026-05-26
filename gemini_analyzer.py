from PIL import Image
from google import genai


_client = None


def configure_gemini_analyzer(api_key):
    global _client
    _client = genai.Client(api_key=api_key)


def ask_ai(image_path, user_question):
    if _client is None:
        raise RuntimeError("Gemini analyzer has not been configured.")

    img = Image.open(image_path)
    try:
        prompt = (
            f"Bạn là bộ não an ninh. Chủ vừa yêu cầu: '{user_question}'. \n "
            "Hãy quan sát tỷ mỉ ảnh camera trực tiếp này và trả lời cực kỳ ngắn gọn, khách quan."
        )
        response = _client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, img]
        )
        return response.text
    finally:
        img.close()
