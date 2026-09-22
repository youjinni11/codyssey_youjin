#!/usr/bin/env python3
"""AI 브랜드 아이덴티티 생성기 (CLI)

브랜드 브리프(JSON)를 입력받아
  1) 브랜드 네이밍(한글+영문, 의미 포함)  2) 슬로건 3개  3) 브랜드 스토리
  4) 컬러 팔레트(+PNG 시각화)            5) 로고 시안 PNG
  (보너스) 경쟁사 분석/차별화 포인트
를 AI API로 생성해 폴더에 저장한다. 기본값은 텍스트/이미지 모두 OpenAI(GPT/gpt-image, DALL-E 후속).
BRAND_TEXT_PROVIDER=gemini / BRAND_IMAGE_PROVIDER=gemini|huggingface 로 다른 서비스로 바꿀 수 있다.

사용법:  python brand_generator.py
필요:    Python 3.10+, requests, matplotlib  /  환경변수 OPENAI_API_KEY (기본값 기준)
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import requests


def load_env_file(path: str = ".env") -> None:
    """.env 파일이 있으면 KEY=VALUE 형태를 읽어 환경변수에 등록한다(이미 있는 값은 유지).

    아래 "설정" 블록이 os.environ 을 읽어 OPENAI_BASE 등 상수를 만들기 *전에* 실행되어야 한다.
    (예전에는 main() 안에서만 호출했는데, 그 시점엔 이미 설정 상수들이 기본값으로 굳어버린 뒤라
    .env 에 OPENAI_BASE_URL 을 적어도 반영되지 않는 버그가 있었다.)
    """
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()  # 아래 설정 상수들이 .env 값을 읽을 수 있도록 가장 먼저 실행한다.

# ----------------------------------------------------------------------------
# 설정 (모델 이름은 환경변수로 바꿀 수 있다)
# ----------------------------------------------------------------------------
API_BASE = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
# 텍스트 생성 서비스: "openai"(기본) 또는 "gemini"
TEXT_PROVIDER = os.environ.get("BRAND_TEXT_PROVIDER", "openai").lower()
_TEXT_MODEL_DEFAULTS = {"openai": "gpt-4o-mini", "gemini": "gemini-3.6-flash"}
TEXT_MODEL = os.environ.get("BRAND_TEXT_MODEL", _TEXT_MODEL_DEFAULTS.get(TEXT_PROVIDER, "gpt-4o-mini"))
# 이미지 모델은 무료 티어가 없을 수 있고 모델 ID 가 바뀔 수 있어 환경변수로 교체 가능하게 둔다.
IMAGE_MODEL = os.environ.get("BRAND_IMAGE_MODEL", "gemini-3.1-flash-image")
# 로고(이미지) 생성 서비스: "openai"(기본), "huggingface"(무료 크레딧), "gemini"(유료 티어 필요)
IMAGE_PROVIDER = os.environ.get("BRAND_IMAGE_PROVIDER", "openai").lower()
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
# DALL-E 2/3 는 2026-05-12 에 API 에서 제거되어, 후속 이미지 모델(gpt-image 계열)을 쓴다.
OPENAI_IMAGE_MODEL = os.environ.get("BRAND_OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
OPENAI_IMAGE_QUALITY = os.environ.get("BRAND_OPENAI_IMAGE_QUALITY", "low")  # low / medium / high
HF_IMAGE_MODEL = os.environ.get("BRAND_HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell")
TIMEOUT_TEXT = 60
TIMEOUT_IMAGE = 180
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

REQUIRED_FIELDS = ("industry", "target", "keywords")
OPTIONAL_FIELDS = ("tone", "competitors", "notes")


class ApiError(Exception):
    """API 호출 실패를 사용자에게 보여줄 한국어 메시지로 감싼 예외.

    retryable=True 는 서버가 일시적으로 바쁜 경우(5xx, 타임아웃)라 잠시 뒤 다시 시도할 만하다는 표시.
    """

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


RETRY_DELAYS = (3, 8, 15)  # 일시 오류(503 등)일 때 기다렸다 다시 시도하는 간격(초)


# ----------------------------------------------------------------------------
# API 키 관리 (코드에 키를 쓰지 않고 환경변수 / .env 파일에서만 읽는다)
# ----------------------------------------------------------------------------
def get_api_key(provider: str = TEXT_PROVIDER) -> str | None:
    """텍스트 생성에 쓸 API 키를 확인한다. provider 에 따라 필요한 키 이름이 다르다."""
    if provider == "gemini":
        env_name, url, key = "GEMINI_API_KEY", "https://aistudio.google.com/apikey", (
            os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        ).strip()
    else:
        env_name, url, key = "OPENAI_API_KEY", "https://platform.openai.com/api-keys", os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        print(f"\n❌ {env_name} 가 설정되어 있지 않습니다.")
        print("   해결 방법(둘 중 하나):")
        print(f"   1) 터미널에서  export {env_name}=키값   (Windows: set {env_name}=키값)")
        print(f"   2) 이 폴더에 .env 파일을 만들고  {env_name}=키값  한 줄 저장 (.env.example 참고)")
        print(f"   키 발급: {url}")
        return None
    return key


# ----------------------------------------------------------------------------
# 브리프 입력/검증
# ----------------------------------------------------------------------------
def load_brief(path: str) -> dict:
    """브리프 JSON을 읽고 필수 필드를 검증한다. 문제가 있으면 ValueError."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"브리프 파일을 찾을 수 없습니다: {p}")
    try:
        brief = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"브리프 파일이 올바른 JSON이 아닙니다 ({e.msg}, {e.lineno}행)") from e
    if not isinstance(brief, dict):
        raise ValueError("브리프 JSON의 최상위는 { ... } 객체여야 합니다.")

    missing = [f for f in REQUIRED_FIELDS if not brief.get(f)]
    if missing:
        raise ValueError(f"필수 필드가 없거나 비어 있습니다: {', '.join(missing)}")
    if isinstance(brief["keywords"], str):  # "자연, 순수" 처럼 문자열이어도 허용
        brief["keywords"] = [k.strip() for k in brief["keywords"].split(",") if k.strip()]
    if not isinstance(brief["keywords"], list) or not brief["keywords"]:
        raise ValueError("keywords 는 비어있지 않은 리스트여야 합니다. 예: [\"자연\", \"순수\"]")
    if isinstance(brief.get("competitors"), str):
        brief["competitors"] = [c.strip() for c in brief["competitors"].split(",") if c.strip()]
    return brief


def brief_to_text(brief: dict) -> str:
    lines = [
        f"- 업종: {brief['industry']}",
        f"- 타겟: {brief['target']}",
        f"- 키워드: {', '.join(map(str, brief['keywords']))}",
    ]
    if brief.get("tone"):
        lines.append(f"- 톤앤매너: {brief['tone']}")
    if brief.get("competitors"):
        lines.append(f"- 경쟁사: {', '.join(map(str, brief['competitors']))}")
    if brief.get("notes"):
        lines.append(f"- 추가 요청사항: {brief['notes']}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# API 호출 (오류 종류별로 명확한 메시지)
# ----------------------------------------------------------------------------
def _raise_for_response(resp: requests.Response) -> None:
    if resp.ok:
        return
    try:
        detail = resp.json().get("error", {}).get("message", resp.text[:200])
    except ValueError:
        detail = resp.text[:200]
    code = resp.status_code
    # Gemini 는 잘못된 키도 400(API key not valid)으로 돌려주므로 메시지로 함께 판별한다.
    if code == 401 or "api key not valid" in detail.lower() or "api_key_invalid" in detail.lower():
        raise ApiError("API 키가 잘못되었거나 만료되었습니다. 키를 다시 확인하세요.")
    if code == 403:
        raise ApiError(f"이 키에는 해당 모델/기능 사용 권한이 없습니다(403): {detail}")
    if code == 404:
        raise ApiError(f"모델을 찾을 수 없습니다(404). BRAND_TEXT_MODEL/BRAND_IMAGE_MODEL 이름 확인: {detail}")
    if code == 429:
        raise ApiError(
            "요청 한도 초과입니다(429). 무료 티어에서 이미지 모델은 한도가 0일 수 있어요(유료 전환 필요). "
            f"상세: {detail[:200]}"
        )
    if code == 400:
        raise ApiError(f"요청이 거부되었습니다(400, 콘텐츠 정책/파라미터 문제 가능): {detail[:200]}")
    if code >= 500:
        raise ApiError(f"Gemini 서버 오류입니다({code}). 잠시 후 다시 시도하세요.", retryable=True)
    raise ApiError(f"API 오류({code}): {detail[:200]}")


def _post(api_key: str, model: str, payload: dict, timeout: int) -> dict:
    """_post_once 를 호출하되, 일시적인 서버 오류는 간격을 두고 자동 재시도한다."""
    for delay in (*RETRY_DELAYS, None):
        try:
            return _post_once(api_key, model, payload, timeout)
        except ApiError as e:
            if delay is None or not e.retryable:
                raise
            print(f"     … 서버가 일시적으로 바빠요. {delay}초 뒤 다시 시도합니다.")
            time.sleep(delay)
    raise ApiError("재시도에 실패했습니다.")  # 도달하지 않는 안전장치


def _post_once(api_key: str, model: str, payload: dict, timeout: int) -> dict:
    try:
        resp = requests.post(
            f"{API_BASE}/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as e:
        raise ApiError("응답 시간이 초과되었습니다(타임아웃).", retryable=True) from e
    except requests.exceptions.ConnectionError as e:
        raise ApiError("네트워크에 연결할 수 없습니다. 인터넷 연결을 확인하세요.") from e
    except requests.exceptions.RequestException as e:
        raise ApiError(f"요청 중 오류: {e}") from e
    _raise_for_response(resp)
    try:
        return resp.json()
    except ValueError as e:
        raise ApiError("API 응답을 해석할 수 없습니다(JSON 아님).") from e


def _text_gemini(api_key: str, instruction: str, brief_text: str, retries: int = 1) -> dict:
    """Gemini generateContent 로 JSON 브랜드 요소를 생성한다."""
    payload = {
        "systemInstruction": {
            "parts": [{"text": "당신은 전문 브랜드 디자이너입니다. 반드시 유효한 JSON 객체 하나만 출력하세요. 한국어로 작성합니다."}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": f"[브랜드 브리프]\n{brief_text}\n\n[요청]\n{instruction}"}]}
        ],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
    }
    last_err: Exception | None = None
    for _ in range(retries + 1):
        data = _post(api_key, TEXT_MODEL, payload, TIMEOUT_TEXT)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            return json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            last_err = e  # 형식이 깨졌거나 안전 필터로 비었으면 한 번 더 시도
    raise ApiError(f"AI 응답이 올바른 JSON 형식이 아닙니다: {last_err}")


def _parse_json_loose(text: str) -> dict:
    """모델이 ```json ... ``` 코드블록으로 감싸 보내는 경우에도 JSON 을 파싱한다."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
        text = text.strip()
    return json.loads(text)


def _text_openai(api_key: str, instruction: str, brief_text: str, retries: int = 1) -> dict:
    """OpenAI(호환) Chat Completions 로 JSON 브랜드 요소를 생성한다."""
    payload = {
        "model": TEXT_MODEL,
        "temperature": 0.8,
        "messages": [
            {
                "role": "system",
                "content": (
                    "당신은 전문 브랜드 디자이너입니다. 반드시 유효한 JSON 객체 하나만 출력하세요. "
                    "코드블록(```)이나 설명 문구 없이 JSON 텍스트만 출력합니다. 한국어로 작성합니다."
                ),
            },
            {"role": "user", "content": f"[브랜드 브리프]\n{brief_text}\n\n[요청]\n{instruction}"},
        ],
    }
    # 코디세이 공개 API는 response_format(JSON 강제) 파라미터를 지원하지 않는다(400 unsupported_feature).
    # 진짜 OpenAI 서버일 때만 켜서, 형식이 깨질 확률을 더 낮춘다.
    if not _is_codyssey_base():
        payload["response_format"] = {"type": "json_object"}
    last_err: Exception | None = None
    for _ in range(retries + 1):
        data = _post_openai("chat/completions", api_key, payload, TIMEOUT_TEXT)
        try:
            return _parse_json_loose(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            last_err = e
    raise ApiError(f"AI 응답이 올바른 JSON 형식이 아닙니다: {last_err}")


def _post_openai(path: str, api_key: str, payload: dict, timeout: int, base_url: str | None = None) -> dict:
    """OpenAI(호환) REST 엔드포인트를 호출한다. 일시 오류(5xx/타임아웃)는 간격을 두고 자동 재시도한다.

    base_url 을 지정하면 OPENAI_BASE 대신 그 주소를 쓴다(코디세이 공개 API처럼 이미지 엔드포인트가
    텍스트와 다른 주소 구조를 쓰는 경우에 사용).
    """
    base = (base_url or OPENAI_BASE).rstrip("/")
    for delay in (*RETRY_DELAYS, None):
        err: ApiError | None = None
        try:
            resp = requests.post(
                f"{base}/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as e:
            err = ApiError("응답 시간이 초과되었습니다(타임아웃).", retryable=True)
        except requests.exceptions.ConnectionError as e:
            raise ApiError("네트워크에 연결할 수 없습니다. 인터넷 연결을 확인하세요.") from e
        except requests.exceptions.RequestException as e:
            raise ApiError(f"요청 중 오류: {e}") from e
        else:
            if resp.ok:
                try:
                    return resp.json()
                except ValueError as e:
                    raise ApiError("API 응답을 해석할 수 없습니다(JSON 아님).") from e
            error_code = ""
            try:
                error_obj = resp.json().get("error", {})
                detail = error_obj.get("message", resp.text[:200])
                error_code = str(error_obj.get("code") or "")
            except ValueError:
                detail = resp.text[:200]
            code = resp.status_code
            if code == 401:
                raise ApiError("OpenAI API 키가 잘못되었거나 만료되었습니다(401). 키를 다시 확인하세요.")
            if code == 403:
                raise ApiError(f"이 OpenAI 계정에는 해당 기능 사용 권한이 없습니다(403): {detail[:150]}")
            if code == 404:
                raise ApiError(f"OpenAI 에서 모델을 찾을 수 없습니다(404). BRAND_TEXT_MODEL/BRAND_OPENAI_IMAGE_MODEL 이름을 확인하세요: {detail[:150]}")
            if code == 429:
                raise ApiError(f"OpenAI 크레딧 부족 또는 요청 한도 초과입니다(429). 결제 설정/잔액을 확인하세요: {detail[:150]}")
            if code == 400 and error_code == "unsupported_feature" and base_url is None and _is_codyssey_base():
                # 코디세이 공개 API(QA 환경)에서 요청이 몰릴 때 가끔 이 오류를 잘못 돌려주는 경우가
                # 있어(우리는 response_format 등 미지원 파라미터를 이미 빼고 보낸다), 한 번은 재시도해본다.
                err = ApiError(f"일시적인 오류로 보입니다(400 unsupported_feature): {detail[:150]}", retryable=True)
            elif code == 400:
                raise ApiError(f"요청이 거부되었습니다(400, 콘텐츠 정책/파라미터 문제 가능): {detail[:150]}")
            elif code >= 500:
                err = ApiError(f"OpenAI 서버 오류입니다({code}). 잠시 후 다시 시도하세요.", retryable=True)
            else:
                raise ApiError(f"OpenAI API 오류({code}): {detail[:150]}")
        if delay is None or not err.retryable:
            raise err
        print(f"     … 서버가 일시적으로 바빠요. {delay}초 뒤 다시 시도합니다.")
        time.sleep(delay)
    raise ApiError("재시도에 실패했습니다.")  # 도달하지 않는 안전장치


def ask_llm_json(api_key: str, instruction: str, brief_text: str, retries: int = 1) -> dict:
    """설정된 텍스트 서비스(TEXT_PROVIDER)로 JSON 브랜드 요소를 생성한다."""
    if TEXT_PROVIDER == "gemini":
        return _text_gemini(api_key, instruction, brief_text, retries)
    return _text_openai(api_key, instruction, brief_text, retries)


# ----------------------------------------------------------------------------
# 1~4단계: 텍스트 요소 생성
# ----------------------------------------------------------------------------
def generate_names(api_key: str, brief_text: str) -> list[dict]:
    """브랜드명 후보 3~5개 + 의미. (보너스) 한글/영문 네이밍 동시 생성."""
    data = ask_llm_json(
        api_key,
        "브랜드명 후보를 4개 만들어 주세요. 각 후보는 한글 이름(name_ko)과 영문 이름(name_en)을 "
        "모두 가지며, 의미/유래(meaning)를 한국어 한 문장으로 설명합니다.\n"
        '형식: {"names": [{"name_ko": "...", "name_en": "...", "meaning": "..."}]}',
        brief_text,
    )
    names = [n for n in data.get("names", []) if isinstance(n, dict) and n.get("name_ko")]
    if not 3 <= len(names) <= 5:
        names = names[:5]
        if len(names) < 3:
            raise ApiError(f"네이밍이 3개 미만으로 생성되었습니다({len(names)}개).")
    for n in names:
        n.setdefault("name_en", "")
        n.setdefault("meaning", "")
    return names


def generate_slogans(api_key: str, brief_text: str) -> list[str]:
    data = ask_llm_json(
        api_key,
        "브랜드 톤앤매너에 맞는 슬로건/태그라인 3개를 만들어 주세요. 짧고 기억에 남게 작성합니다.\n"
        '형식: {"slogans": ["...", "...", "..."]}',
        brief_text,
    )
    slogans = [s.strip() for s in data.get("slogans", []) if isinstance(s, str) and s.strip()][:3]
    if len(slogans) < 3:
        raise ApiError(f"슬로건이 3개 미만으로 생성되었습니다({len(slogans)}개).")
    return slogans


STORY_LEN_MIN, STORY_LEN_MAX = 270, 330


def generate_story(api_key: str, brief_text: str, length_retries: int = 4) -> str:
    """브랜드 스토리를 270~330자로 생성한다.

    "처음부터 다시 써줘" 식 재시도는 매번 새로 생성하다 보니 글자 수를 잘 못 맞춘다.
    대신 방금 나온 초안을 그대로 주고 "이어서 늘리거나/줄여서" 고치게 하면 훨씬 잘 맞는다.
    """
    base_instruction = (
        "브랜드 스토리를 공백 포함 300자 내외(반드시 270~330자 사이)로 써 주세요. "
        "탄생 배경, 철학, 비전을 모두 포함하고 하나의 자연스러운 글로 작성합니다.\n"
        '형식: {"story": "..."}'
    )
    data = ask_llm_json(api_key, base_instruction, brief_text)
    story = str(data.get("story", "")).strip()
    if not story:
        raise ApiError("브랜드 스토리가 비어 있습니다.")

    for _ in range(length_retries):
        length = len(story)
        if STORY_LEN_MIN <= length <= STORY_LEN_MAX:
            return story
        if length < STORY_LEN_MIN:
            fix_instruction = (
                f"다음은 브랜드 스토리 초안입니다(현재 {length}자, 공백 포함). 내용을 자연스럽게 이어가며 "
                "탄생 배경/철학/비전 중 아직 부족한 부분을 한두 문장 더 보강해서, 공백 포함 정확히 "
                "270~330자 사이가 되도록 다시 써 주세요. 완전히 새로 쓰지 말고 아래 초안을 확장하세요.\n\n"
                f"[초안]\n{story}\n\n"
                '형식: {"story": "..."}'
            )
        else:
            fix_instruction = (
                f"다음은 브랜드 스토리 초안입니다(현재 {length}자, 공백 포함). 핵심 의미는 유지하되 "
                "군더더기 문구를 다듬어서, 공백 포함 정확히 270~330자 사이가 되도록 간결하게 줄여 "
                "다시 써 주세요.\n\n"
                f"[초안]\n{story}\n\n"
                '형식: {"story": "..."}'
            )
        data = ask_llm_json(api_key, fix_instruction, brief_text)
        new_story = str(data.get("story", "")).strip()
        if new_story:
            story = new_story

    if not (STORY_LEN_MIN <= len(story) <= STORY_LEN_MAX):
        # 여러 번 시도해도 270~330자를 못 맞추면, 마지막 결과라도 안내 문구와 함께 반환한다
        # (완전 실패 처리보다는 낫지만, 길이 요구사항은 벗어난 상태이니 최종 결과물을 검수할 때 확인이 필요하다).
        print(f"     … 요청한 글자 수 범위(270~330자)를 못 맞췄습니다(최종 {len(story)}자). 결과는 저장하되 확인이 필요해요.")
    return story


def generate_palette(api_key: str, brief_text: str) -> dict:
    """메인 1개 + 서브 2~3개 HEX. 형식이 틀린 HEX 는 걸러낸다."""
    data = ask_llm_json(
        api_key,
        "브랜드에 어울리는 컬러 팔레트를 제안해 주세요. 메인 컬러 1개, 서브 컬러 3개. "
        "색상은 반드시 #RRGGBB 형식의 HEX 코드, name 은 영어 색상 이름, reason 은 한국어 한 문장.\n"
        '형식: {"main": {"hex": "#000000", "name": "...", "reason": "..."}, '
        '"sub": [{"hex": "#000000", "name": "...", "reason": "..."}]}',
        brief_text,
    )
    main = data.get("main")
    if not isinstance(main, dict) or not HEX_RE.match(str(main.get("hex", ""))):
        raise ApiError("메인 컬러의 HEX 코드가 올바르지 않습니다.")
    subs = [
        s for s in data.get("sub", [])
        if isinstance(s, dict) and HEX_RE.match(str(s.get("hex", "")))
    ][:3]
    if len(subs) < 2:
        raise ApiError("유효한 서브 컬러가 2개 미만입니다.")
    for c in [main, *subs]:
        c["hex"] = c["hex"].upper()
        c.setdefault("name", "")
        c.setdefault("reason", "")
    return {"main": main, "sub": subs}


def analyze_competitors(api_key: str, brief_text: str) -> dict:
    """(보너스) 경쟁사 분석 + 차별화 포인트."""
    data = ask_llm_json(
        api_key,
        "브리프의 경쟁사 브랜드를 분석해 주세요. 각 경쟁사의 특징(strength)과 약점/빈틈(gap)을 정리하고, "
        "우리 브랜드의 차별화 포인트 3가지를 제안합니다. 확실하지 않은 정보는 일반적 인상 수준으로만 쓰고 "
        "단정하지 마세요.\n"
        '형식: {"competitors": [{"name": "...", "strength": "...", "gap": "..."}], '
        '"differentiation_points": ["...", "...", "..."]}',
        brief_text,
    )
    if not data.get("differentiation_points"):
        raise ApiError("차별화 포인트가 비어 있습니다.")
    return data


# ----------------------------------------------------------------------------
# 컬러 팔레트 시각화 (matplotlib)
# ----------------------------------------------------------------------------
def _text_color_for(hex_code: str) -> str:
    """배경색 밝기에 따라 글자색(검정/흰색)을 골라 가독성 확보."""
    r, g, b = (int(hex_code[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


def save_palette_png(palette: dict, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")  # 화면 없이 파일로만 저장
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    colors = [("MAIN", palette["main"])] + [(f"SUB {i}", c) for i, c in enumerate(palette["sub"], 1)]
    fig, ax = plt.subplots(figsize=(3 * len(colors), 3.6))
    for i, (role, c) in enumerate(colors):
        ax.add_patch(Rectangle((i, 0.25), 0.95, 0.75, facecolor=c["hex"], edgecolor="#CCCCCC", linewidth=1))
        fg = _text_color_for(c["hex"])
        ax.text(i + 0.475, 0.72, role, ha="center", va="center", color=fg, fontsize=12, fontweight="bold")
        ax.text(i + 0.475, 0.55, c["hex"], ha="center", va="center", color=fg, fontsize=14)
        ax.text(i + 0.475, 0.12, c.get("name", ""), ha="center", va="center", color="#333333", fontsize=11)
    ax.set_xlim(-0.05, len(colors))
    ax.set_ylim(0, 1.05)
    ax.axis("off")
    ax.set_title("Brand Color Palette", fontsize=16, fontweight="bold")
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ----------------------------------------------------------------------------
# 로고 시안 생성 (이미지 API)
# ----------------------------------------------------------------------------
LOGO_STYLES = [
    "minimal geometric symbol logo, flat vector style, simple shapes",
    "modern emblem logo with a clean abstract icon, subtle gradient-free flat design",
    "elegant line-art icon logo, thin consistent strokes, balanced composition",
]


def build_logo_prompt(brief: dict, name_en: str, main_hex: str, style: str) -> str:
    return (
        f"A {style} for a brand named '{name_en}' in the {brief['industry']} industry, "
        f"for {brief['target']}. Brand keywords: {', '.join(map(str, brief['keywords']))}. "
        f"Tone: {brief.get('tone', 'clean and professional')}. Primary color {main_hex}. "
        "Centered on a plain white background, no text, no letters, no mockup, professional logo design."
    )


def _logo_gemini(api_key: str, prompt: str, out_path: Path) -> None:
    """Gemini 이미지 모델로 로고를 생성해 PNG 로 저장한다."""
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    data = _post(api_key, IMAGE_MODEL, payload, TIMEOUT_IMAGE)
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as e:
        raise ApiError("이미지 응답이 비어 있습니다(안전 필터에 걸렸을 수 있어요).") from e
    for part in parts:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline and inline.get("data"):
            raw = base64.b64decode(inline["data"])
            try:  # 응답이 JPEG 여도 확실히 PNG 로 저장
                from PIL import Image
                import io
                Image.open(io.BytesIO(raw)).convert("RGBA").save(out_path, "PNG")
            except Exception as e:
                raise ApiError(f"이미지를 PNG 로 저장하지 못했습니다: {e}") from e
            return
    text = " ".join(p.get("text", "") for p in parts).strip()[:150]
    raise ApiError(f"응답에 이미지가 없습니다. 모델이 텍스트만 돌려줬어요: {text}")


def _is_codyssey_base() -> bool:
    """OPENAI_BASE_URL 이 코디세이 공개 API(copa.codyssey.kr) 를 가리키는지 판별한다.

    코디세이 공개 API는 텍스트(/v1/chat/completions)는 OpenAI 와 동일한 경로를 쓰지만,
    이미지 엔드포인트는 경로(/api/v1/images)와 응답 구조(result.images[].b64_json)가 다르다.
    """
    return "codyssey" in OPENAI_BASE.lower()


def _logo_openai(prompt: str, out_path: Path) -> None:
    """OpenAI(또는 코디세이 공개 API) 이미지 엔드포인트로 로고를 생성해 PNG 로 저장한다."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ApiError(
            "OpenAI API 키(OPENAI_API_KEY)가 없습니다. https://platform.openai.com/api-keys 에서 발급해 "
            ".env 에 OPENAI_API_KEY=키값 을 추가하세요. (이미지 생성은 유료 크레딧이 필요합니다)"
        )
    if _is_codyssey_base():
        # 코디세이 공개 API: Base URL 이 https://copa.codyssey.kr/v1 이어도
        # 이미지는 /v1 이 아니라 /api/v1/images 경로를 쓴다(문서 탭 '이미지' 예제 기준).
        origin = OPENAI_BASE[: -len("/v1")] if OPENAI_BASE.lower().endswith("/v1") else OPENAI_BASE
        payload = {
            "model": OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": "1024x1024",
            "response_format": "b64_json",
        }
        data = _post_openai("api/v1/images", key, payload, TIMEOUT_IMAGE, base_url=origin)
        try:
            out_path.write_bytes(base64.b64decode(data["result"]["images"][0]["b64_json"]))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ApiError(f"이미지 응답을 해석할 수 없습니다: {e}") from e
        return
    payload = {
        "model": OPENAI_IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "quality": OPENAI_IMAGE_QUALITY,
    }
    data = _post_openai("images/generations", key, payload, TIMEOUT_IMAGE)
    try:
        out_path.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ApiError(f"이미지 응답을 해석할 수 없습니다: {e}") from e


def _logo_huggingface(prompt: str, out_path: Path) -> None:
    """Hugging Face Inference Providers(FLUX 등)로 로고를 생성해 PNG 로 저장한다."""
    token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or "").strip()
    if not token:
        raise ApiError(
            "HF_TOKEN(Hugging Face 토큰)이 없습니다. https://huggingface.co/settings/tokens 에서 발급해 "
            ".env 에 HF_TOKEN=토큰값 을 추가하세요."
        )
    try:
        from huggingface_hub import InferenceClient
    except ImportError as e:
        raise ApiError("huggingface_hub 가 설치되지 않았습니다. `pip3 install huggingface_hub` 를 실행하세요.") from e
    try:
        client = InferenceClient(provider="auto", api_key=token, timeout=TIMEOUT_IMAGE)
        image = client.text_to_image(prompt, model=HF_IMAGE_MODEL)
        image.save(out_path, "PNG")
    except Exception as e:  # 라이브러리 예외 종류가 다양해 상태 코드로 분류한다
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (401, 403):
            raise ApiError(f"Hugging Face 토큰이 잘못되었거나 권한이 없습니다({status}). 토큰의 Inference Providers 권한을 확인하세요.") from e
        if status in (402, 429):
            raise ApiError(f"Hugging Face 무료 크레딧/요청 한도를 모두 썼습니다({status}). 다음 달 갱신을 기다리거나 결제 설정이 필요합니다.") from e
        if status == 404:
            raise ApiError(f"Hugging Face 에서 모델을 찾을 수 없습니다(404). BRAND_HF_IMAGE_MODEL 이름을 확인하세요: {HF_IMAGE_MODEL}") from e
        if status is not None and status >= 500:
            raise ApiError(f"Hugging Face 서버 오류입니다({status}). 잠시 후 다시 시도하세요.") from e
        raise ApiError(f"Hugging Face 이미지 생성 실패: {type(e).__name__}: {str(e)[:150]}") from e


def generate_logo(api_key: str, prompt: str, out_path: Path) -> None:
    """설정된 이미지 서비스(IMAGE_PROVIDER)로 로고 1장을 생성한다."""
    if IMAGE_PROVIDER == "gemini":
        _logo_gemini(api_key, prompt, out_path)
    elif IMAGE_PROVIDER == "huggingface":
        _logo_huggingface(prompt, out_path)
    else:
        _logo_openai(prompt, out_path)


# ----------------------------------------------------------------------------
# 메인 흐름
# ----------------------------------------------------------------------------
def run_step(label: str, func, errors: dict, key: str):
    """한 단계를 실행. 실패하면 메시지를 출력하고 None 을 돌려 다음 단계로 계속 진행."""
    try:
        return func()
    except ApiError as e:
        print(f"  ⚠️  {label} 실패: {e}")
        errors[key] = str(e)
    except Exception as e:  # 예상 못한 오류도 전체 중단은 막는다
        print(f"  ⚠️  {label} 중 예상치 못한 오류: {type(e).__name__}: {e}")
        errors[key] = f"{type(e).__name__}: {e}"
    return None


def main() -> int:
    # (.env 로딩은 모듈 맨 위에서 이미 끝났다 — 설정 상수들이 .env 값을 읽어야 하기 때문)
    print("\n🎨 AI 브랜드 아이덴티티 생성기\n")

    brief_path = input("브리프 파일 경로를 입력하세요: ").strip().strip('"').strip("'")
    if not brief_path:
        print("❌ 브리프 파일 경로는 필수입니다.")
        return 1
    out_input = input("출력 폴더 경로를 입력하세요 (엔터 시 ./output): ").strip()
    out_dir = Path(out_input or "./output").expanduser()

    try:
        brief = load_brief(brief_path)
    except ValueError as e:
        print(f"\n❌ {e}")
        return 1

    api_key = get_api_key()
    if not api_key:
        return 1

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"\n❌ 출력 폴더를 만들 수 없습니다: {e}")
        return 1

    brief_text = brief_to_text(brief)
    result: dict = {"brief": brief}
    errors: dict = {}
    total = 5 + (1 if brief.get("competitors") else 0)

    # [1/5] 네이밍
    print(f"\n[1/{total}] 브랜드 네이밍 생성 중...")
    names = run_step("네이밍 생성", lambda: generate_names(api_key, brief_text), errors, "names")
    if names:
        result["names"] = names
        for n in names:
            en = f" ({n['name_en']})" if n["name_en"] else ""
            print(f"  - {n['name_ko']}{en}: {n['meaning']}")

    time.sleep(1.5)  # 요청이 너무 몰리지 않도록 살짝 간격을 둔다(일부 서버에서 순간 과부하로 오류가 날 수 있어서)
    # [2/5] 슬로건
    print(f"[2/{total}] 슬로건 생성 중...")
    slogans = run_step("슬로건 생성", lambda: generate_slogans(api_key, brief_text), errors, "slogans")
    if slogans:
        result["slogans"] = slogans
        for s in slogans:
            print(f'  - "{s}"')

    time.sleep(1.5)
    # [3/5] 스토리
    print(f"[3/{total}] 브랜드 스토리 생성 중...")
    story = run_step("스토리 생성", lambda: generate_story(api_key, brief_text), errors, "story")
    if story:
        result["story"] = story
        warn = "" if STORY_LEN_MIN <= len(story) <= STORY_LEN_MAX else "  ⚠️ 270~330자 범위를 벗어났어요, 확인해주세요."
        print(f"  - 스토리 생성 완료 ({len(story)}자){warn}")

    time.sleep(1.5)
    # [4/5] 컬러 팔레트
    print(f"[4/{total}] 컬러 팔레트 생성 중...")
    palette = run_step("팔레트 생성", lambda: generate_palette(api_key, brief_text), errors, "palette")
    if palette:
        result["palette"] = palette
        print(f"  - 메인: {palette['main']['hex']} ({palette['main']['name']})")
        print(f"  - 서브: {', '.join(c['hex'] for c in palette['sub'])}")
        pal_path = out_dir / "color_palette.png"
        if run_step("팔레트 이미지 저장", lambda: save_palette_png(palette, pal_path) or True, errors, "palette_png"):
            print(f"  - 저장: {pal_path}")

    # [5/5] 로고 (네이밍/팔레트가 실패해도 브리프 기반으로 계속 진행)
    print(f"[5/{total}] 로고 시안 생성 중... (이미지 생성은 시간이 걸릴 수 있어요)")
    logo_name = (names[0]["name_en"] or names[0]["name_ko"]) if names else str(brief["keywords"][0])
    main_hex = palette["main"]["hex"] if palette else "a color that fits the brand"
    saved_logos: list[str] = []
    for i, style in enumerate(LOGO_STYLES[:3], 1):
        logo_path = out_dir / f"logo_{i:02d}.png"
        prompt = build_logo_prompt(brief, logo_name, main_hex, style)
        ok = run_step(
            f"로고 {i} 생성",
            lambda p=prompt, lp=logo_path: generate_logo(api_key, p, lp) or True,
            errors,
            f"logo_{i:02d}",
        )
        if ok:
            saved_logos.append(logo_path.name)
            print(f"  - 저장: {logo_path}")
        if f"logo_{i:02d}" in errors and any(k in errors[f"logo_{i:02d}"] for k in ("API 키", "토큰", "429", "402", "403", "설치되지")):
            break  # 키/한도(429) 문제는 반복해도 같으므로 나머지 시안은 건너뜀
    result["logos"] = saved_logos

    # [보너스] 경쟁사 분석
    if brief.get("competitors"):
        time.sleep(1.5)
        print(f"[6/{total}] (보너스) 경쟁사 분석 중...")
        comp = run_step("경쟁사 분석", lambda: analyze_competitors(api_key, brief_text), errors, "competitor_analysis")
        if comp:
            result["competitor_analysis"] = comp
            for c in comp.get("competitors", []):
                print(f"  - [{c.get('name', '')}] 강점: {c.get('strength', '')}")
                print(f"    약점/빈틈: {c.get('gap', '')}")
            for p in comp["differentiation_points"]:
                print(f"  - 차별화: {p}")

    # 결과 저장
    if errors:
        result["errors"] = errors
    json_path = out_dir / "brand_result.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        print(f"\n⚠️  일부 단계가 실패했습니다({len(errors)}건). 성공한 결과는 {out_dir}/ 에 저장했습니다.")
    else:
        print(f"\n✅ 완료! {out_dir}/ 폴더를 확인하세요.")
    print(f"   - 텍스트 결과: {json_path}")
    return 0 if len(errors) < total else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\n중단되었습니다.")
        sys.exit(130)
