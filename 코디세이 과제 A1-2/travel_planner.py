"""
국내 여행지 추천 프로그램
Python 응용: API 활용 미션 (LLM API + 지도/장소 검색 API 연동)

사용된 API:
    - LLM: OpenAI Chat Completions API (gpt-4o-mini)
    - 지도/장소 검색: Kakao Local API (키워드 검색)

실행 방법:
    python3 travel_planner.py --date "2026-03-15"

필요한 환경변수 (.env 파일 또는 시스템 환경변수):
    OPENAI_API_KEY       - OpenAI API 키
    KAKAO_REST_API_KEY   - Kakao REST API 키
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    # python-dotenv가 없어도 시스템 환경변수만으로 동작하도록 허용한다.
    pass


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
KAKAO_API_KEY = os.environ.get("KAKAO_REST_API_KEY")

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
KAKAO_LOCAL_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

RESULTS_DIR = Path("results")


# ---------------------------------------------------------------------------
# 0. CLI / 환경 설정
# ---------------------------------------------------------------------------

def parse_args():
    """--date 인자를 받아 형식을 검증하고 반환한다."""
    parser = argparse.ArgumentParser(
        prog="travel_planner.py",
        description="국내 여행지 추천 프로그램 (LLM + 지도 API 연동)",
    )
    parser.add_argument(
        "--date",
        required=True,
        help='여행 날짜, YYYY-MM-DD 형식 (예: "2026-03-15")',
    )
    args = parser.parse_args()

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        parser.print_usage()
        print('오류: --date는 "YYYY-MM-DD" 형식이어야 합니다. 예) --date "2026-03-15"')
        sys.exit(1)

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        parser.print_usage()
        print("오류: 유효하지 않은 날짜입니다.")
        sys.exit(1)

    return args.date


def check_api_keys():
    """필수 API 키가 설정되어 있는지 확인하고, 없으면 안내 후 종료한다."""
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not KAKAO_API_KEY:
        missing.append("KAKAO_REST_API_KEY")

    if missing:
        print("오류: 다음 API 키가 설정되지 않았습니다 -> " + ", ".join(missing))
        print()
        print("설정 방법 (프로젝트 루트에 .env 파일을 만들고 아래처럼 입력):")
        print('  OPENAI_API_KEY="sk-..."')
        print('  KAKAO_REST_API_KEY="..."')
        print()
        print("또는 터미널에서 환경변수로 직접 설정할 수도 있습니다:")
        print('  export OPENAI_API_KEY="sk-..."')
        print('  export KAKAO_REST_API_KEY="..."')
        sys.exit(1)


# ---------------------------------------------------------------------------
# 1. LLM 호출 공통 함수
# ---------------------------------------------------------------------------

def call_openai_chat(prompt, errors, system_prompt=None):
    """OpenAI Chat Completions API를 호출하고 응답 텍스트를 반환한다.

    실패 시 None을 반환하고 errors 리스트에 오류를 기록한다.
    """
    body = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
                or "당신은 한국 국내 여행 전문가입니다. 요청받은 형식을 정확히 지켜 답변하세요.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }

    req = urllib.request.Request(
        OPENAI_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            errors.append(
                {"step": "llm_call", "type": "AUTH_ERROR", "message": f"HTTP {e.code} - OpenAI API 키를 확인하세요."}
            )
        elif e.code == 429:
            errors.append(
                {"step": "llm_call", "type": "QUOTA_ERROR", "message": "HTTP 429 - 요청 한도를 초과했습니다."}
            )
        else:
            errors.append({"step": "llm_call", "type": "HTTP_ERROR", "message": f"HTTP {e.code}"})
        return None
    except urllib.error.URLError as e:
        errors.append({"step": "llm_call", "type": "NETWORK_ERROR", "message": str(e.reason)})
        return None
    except Exception as e:  # noqa: BLE001 - 예상 못한 오류도 리포트에 남기고 계속 진행한다.
        errors.append({"step": "llm_call", "type": "UNKNOWN_ERROR", "message": str(e)})
        return None


def extract_json(text):
    """LLM 응답 텍스트에서 JSON 객체만 추출해 파싱한다. 실패 시 None."""
    if not text:
        return None

    cleaned = text.strip()
    # ```json ... ``` 코드블록 표시 제거
    cleaned = re.sub(r"^```(json)?\s*|```$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 텍스트 중간에 JSON 객체가 섞여 있는 경우, { ... } 블록만 추출 시도
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# 2. 1차 추천 (날씨 / 행사 정보) - LLM
# ---------------------------------------------------------------------------

def build_recommendation_prompt(date):
    return f"""여행 날짜: {date}

이 시기에 한국 국내에서 여행하기 좋은 도시 1곳을 추천해주세요.
다른 설명 없이 아래 JSON 형식으로만 답변하세요:

{{
  "recommended_city": "도시명",
  "weather": "해당 시기 일반적인 날씨 요약 (1~2문장)",
  "events": ["행사/축제 후보1", "행사/축제 후보2"],
  "reason": "추천 근거 2~4문장"
}}"""


def get_recommendation(date, errors):
    """1차 추천 JSON을 받는다. 파싱 실패 시 1회 재시도한다."""
    prompt = build_recommendation_prompt(date)
    text = call_openai_chat(prompt, errors)
    result = extract_json(text)

    if result is None:
        # 재시도 1회: "필수 키만 다시 JSON으로 출력"하도록 프롬프트를 강화한다.
        retry_prompt = (
            prompt
            + "\n\n중요: JSON 객체 하나만 출력하세요. 설명 문장, 코드블록 표시를 포함하지 마세요."
        )
        text = call_openai_chat(retry_prompt, errors)
        result = extract_json(text)

    if result is None:
        errors.append(
            {
                "step": "llm_recommendation",
                "type": "PARSE_ERROR",
                "message": "1차 추천 JSON 파싱 실패 (재시도 1회 포함)",
            }
        )
        result = {}

    # 필수 키 보정 (스키마를 항상 만족하도록)
    result.setdefault("recommended_city", "제주")
    result.setdefault("weather", "정보 없음")
    result.setdefault("events", [])
    result.setdefault("reason", "추천 정보를 가져오지 못했습니다.")

    if not isinstance(result.get("events"), list):
        result["events"] = [str(result["events"])] if result.get("events") else []

    return result


# ---------------------------------------------------------------------------
# 3. 맛집 검색 - Kakao Local API
# ---------------------------------------------------------------------------

def search_restaurants(city, errors, size=5):
    """Kakao Local API로 '{city} 맛집' 키워드 검색을 수행한다.

    실패하거나 결과가 0건이어도 프로그램을 중단하지 않고 빈 리스트를 반환한다.
    """
    query = f"{city} 맛집"
    params = urllib.parse.urlencode({"query": query, "size": size})
    req = urllib.request.Request(
        f"{KAKAO_LOCAL_URL}?{params}",
        headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            errors.append(
                {"step": "place_search", "type": "AUTH_ERROR", "message": f"HTTP {e.code}"}
            )
        else:
            errors.append({"step": "place_search", "type": "HTTP_ERROR", "message": f"HTTP {e.code}"})
        return []
    except urllib.error.URLError as e:
        errors.append({"step": "place_search", "type": "NETWORK_ERROR", "message": str(e.reason)})
        return []
    except Exception as e:  # noqa: BLE001
        errors.append({"step": "place_search", "type": "UNKNOWN_ERROR", "message": str(e)})
        return []

    documents = data.get("documents", [])
    if not documents:
        errors.append(
            {"step": "place_search", "type": "EMPTY_RESULT", "message": f"0 results for query={query}"}
        )
        return []

    restaurants = []
    for doc in documents[:size]:
        restaurants.append(
            {
                "name": doc.get("place_name", ""),
                "address": doc.get("road_address_name") or doc.get("address_name", ""),
                "category": doc.get("category_name", ""),
                "url": doc.get("place_url", ""),
                "x": doc.get("x"),
                "y": doc.get("y"),
            }
        )
    return restaurants


# ---------------------------------------------------------------------------
# 4. 최종 리포트 생성 - LLM
# ---------------------------------------------------------------------------

def format_restaurants_for_prompt(restaurants):
    if not restaurants:
        return "데이터 없음 (장소 검색 결과 0건)"
    return "\n".join(
        f"- {r['name']} ({r.get('category', '') or '분류 정보 없음'}) - {r.get('address', '')}"
        for r in restaurants
    )


def build_report_prompt(date, recommendation, restaurants):
    return f"""아래 정보를 바탕으로 국내 여행 추천 리포트를 마크다운으로 작성하세요.

날짜: {date}
추천 도시: {recommendation['recommended_city']}
날씨: {recommendation['weather']}
행사/축제: {', '.join(recommendation['events']) if recommendation['events'] else '없음'}
추천 이유: {recommendation['reason']}
맛집 목록:
{format_restaurants_for_prompt(restaurants)}

반드시 아래 마크다운 형식(헤더 구조)을 그대로 지켜서 작성하세요:

# {date} 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 맛집 추천
## 1일 일정 제안

맛집 목록이 "데이터 없음"이면 맛집 추천 섹션에도 "데이터 없음"이라고 표기하세요.
'오류 요약(errors)' 섹션은 작성하지 마세요 (프로그램이 별도로 추가합니다)."""


def build_fallback_report(date, recommendation, restaurants):
    """LLM 호출이 끝내 실패했을 때 직접 조립하는 대체 리포트."""
    events_text = (
        "\n".join(f"- {e}" for e in recommendation["events"])
        if recommendation["events"]
        else "- 없음"
    )
    if restaurants:
        restaurants_md = "\n".join(
            f"- **{r['name']}** ({r.get('category', '') or '분류 정보 없음'}) - {r.get('address', '')}"
            for r in restaurants
        )
    else:
        restaurants_md = "- 데이터 없음 (장소 검색 결과 0건)"

    return f"""# {date} 국내 여행 추천 리포트

## 추천 지역
{recommendation['recommended_city']}

## 추천 이유
{recommendation['reason']}

## 날씨 요약
{recommendation['weather']}

## 행사/축제
{events_text}

## 맛집 추천
{restaurants_md}

## 1일 일정 제안
- 오전: {recommendation['recommended_city']} 대표 명소 관광
- 오후: 인근 자연/문화 명소 방문
- 저녁: 추천 맛집에서 현지 음식 즐기기
"""


def generate_report(date, recommendation, restaurants, errors):
    """최종 여행 리포트를 마크다운 텍스트로 생성한다. LLM 실패 시 템플릿으로 대체."""
    prompt = build_report_prompt(date, recommendation, restaurants)
    text = call_openai_chat(
        prompt,
        errors,
        system_prompt="당신은 여행 리포트를 작성하는 어시스턴트입니다. 요청받은 마크다운 형식을 정확히 따르세요.",
    )

    if text:
        text = re.sub(r"^```markdown\s*|^```\s*|```$", "", text.strip(), flags=re.MULTILINE).strip()
    else:
        errors.append(
            {
                "step": "report_generation",
                "type": "LLM_FALLBACK",
                "message": "리포트 생성 LLM 호출 실패, 템플릿으로 대체 생성",
            }
        )
        text = build_fallback_report(date, recommendation, restaurants)

    # 오류 요약 섹션은 항상 프로그램이 직접 덧붙인다 (LLM이 빠뜨리거나 잘못 쓸 수 있으므로).
    if errors:
        error_lines = "\n".join(
            f"- [{e['step']}] {e['type']}: {e['message']}" for e in errors
        )
    else:
        error_lines = "- 없음"
    text = text.rstrip() + f"\n\n## 오류 요약(errors)\n{error_lines}\n"

    return text


# ---------------------------------------------------------------------------
# 5. 결과 저장 (보너스: 캐싱)
# ---------------------------------------------------------------------------

def load_cached_raw_data(date):
    """같은 날짜로 이미 저장된 원본 JSON이 있으면 불러온다 (보너스: 캐싱)."""
    json_path = RESULTS_DIR / f"{date}_raw_data.json"
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_results(date, recommendation, restaurants, errors, report_text):
    RESULTS_DIR.mkdir(exist_ok=True)

    raw_data = {
        "date": date,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors,
    }

    json_path = RESULTS_DIR / f"{date}_raw_data.json"
    md_path = RESULTS_DIR / f"{date}_travel_plan.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return json_path, md_path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    date = parse_args()
    check_api_keys()

    errors = []

    cached = load_cached_raw_data(date)
    if cached:
        print(f"[캐시] {date} 에 대한 기존 결과를 발견했습니다. API 호출을 건너뛰고 리포트를 재생성합니다.")
        recommendation = cached.get("recommendation", {})
        restaurants = cached.get("restaurants", [])
        errors = cached.get("errors", [])
    else:
        print("[1/3] 1차 추천 생성 중(LLM)...")
        recommendation = get_recommendation(date, errors)
        print(f'  - recommended_city: "{recommendation["recommended_city"]}"')

        print("[2/3] 맛집 검색 중(지도/장소 API)...")
        restaurants = search_restaurants(recommendation["recommended_city"], errors)
        if restaurants:
            print(f"  - 맛집 {len(restaurants)}곳 검색 완료")
        else:
            print("  - 검색 결과 0건 또는 오류 발생 (데이터 없음으로 진행)")

    print("[3/3] 최종 리포트 생성 중(LLM)...")
    report = generate_report(date, recommendation, restaurants, errors)
    print("  - 리포트 생성 완료")

    json_path, md_path = save_results(date, recommendation, restaurants, errors, report)

    print(f"\n완료! {md_path} 를 확인하세요.")
    print(f"(원본 데이터: {json_path})")


if __name__ == "__main__":
    main()
