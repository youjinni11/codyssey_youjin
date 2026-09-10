# 국내 여행지 추천 프로그램

여행 날짜를 입력하면 LLM이 그 시기에 가기 좋은 국내 도시를 추천하고,
지도/장소 검색 API로 그 도시의 맛집을 찾은 뒤, 두 결과를 합쳐
최종 여행 리포트(Markdown)를 생성하는 CLI 프로그램입니다.

Python 응용: API 활용 미션 — 여러 API(LLM + 지도)를 조합해 하나의
결과물을 만들어내는 흐름을 익히기 위해 제작되었습니다.

## 사용한 API

| 용도 | 제공자 | 비고 |
| --- | --- | --- |
| LLM (1차 추천 / 최종 리포트 생성) | OpenAI Chat Completions API (`gpt-4o-mini`) | 유료(과금) — 호출 비용 발생 |
| 지도/장소 검색 (맛집 검색) | Kakao Local API (키워드 검색) | 무료 |

## 실행 방법

### 1) 필요한 패키지 설치

```bash
pip install -r requirements.txt
```

(`python-dotenv`가 없어도 동작은 하지만, `.env` 파일을 자동으로 읽으려면 설치를 권장합니다.)

### 2) API 키 설정

이 프로그램은 **API 키를 코드에 직접 작성하지 않고**, `.env` 파일 또는
시스템 환경변수에서 읽어옵니다.

1. `.env.example` 파일을 복사해서 `.env` 파일을 만듭니다.

   ```bash
   cp .env.example .env
   ```

2. `.env` 파일을 열어 아래 두 값을 본인의 키로 채워 넣습니다.

   ```
   OPENAI_API_KEY="sk-..."
   KAKAO_REST_API_KEY="..."
   ```

   - OpenAI API 키 발급: https://platform.openai.com/api-keys
   - Kakao REST API 키 발급: https://developers.kakao.com (애플리케이션 추가 후 "REST API 키" 확인)

   `.env` 대신 터미널에서 직접 환경변수로 설정해도 됩니다.

   ```bash
   # macOS/Linux (현재 터미널 세션에만 적용)
   export OPENAI_API_KEY="sk-..."
   export KAKAO_REST_API_KEY="..."
   ```

   ```powershell
   # Windows PowerShell (현재 세션에만 적용)
   $env:OPENAI_API_KEY="sk-..."
   $env:KAKAO_REST_API_KEY="..."
   ```

3. 두 키 중 하나라도 설정되어 있지 않으면 프로그램은 즉시 종료되며,
   위와 같은 설정 방법을 화면에 안내합니다.

### 3) 프로그램 실행

```bash
python3 travel_planner.py --date "2026-03-15"
```

- `--date`는 필수 옵션이며 `YYYY-MM-DD` 형식이어야 합니다.
- 형식이 올바르지 않으면 사용법을 출력하고 종료합니다.

실행하면 아래와 같은 진행 로그가 출력됩니다.

```
[1/3] 1차 추천 생성 중(LLM)...
  - recommended_city: "제주"
[2/3] 맛집 검색 중(지도/장소 API)...
  - 맛집 5곳 검색 완료
[3/3] 최종 리포트 생성 중(LLM)...
  - 리포트 생성 완료

완료! results/2026-03-15_travel_plan.md 를 확인하세요.
(원본 데이터: results/2026-03-15_raw_data.json)
```

## 결과물 확인 방법

실행이 끝나면 `results/` 폴더에 아래 두 파일이 생성됩니다 (파일명은 입력한 날짜 기준).

- `results/{date}_raw_data.json` — 1차 추천 결과(JSON) + 맛집 검색 결과 + 오류 요약을 담은 원본 데이터
- `results/{date}_travel_plan.md` — 추천 지역/이유, 날씨, 행사, 맛집, 1일 일정, 오류 요약이 포함된 최종 리포트

같은 날짜로 다시 실행하면, 이미 저장된 원본 JSON이 있을 경우 API를 다시
호출하지 않고 그 데이터를 재사용해 리포트만 다시 생성합니다(캐싱).

## 기능 요약

1. `argparse` 기반 CLI, `--date "YYYY-MM-DD"` 필수 옵션과 형식 검증
2. LLM(OpenAI)에게 날짜를 주고 `recommended_city / weather / events / reason` 구조의 JSON을 요청 (파싱 실패 시 1회 재시도)
3. 추천된 도시로 Kakao Local API를 호출해 맛집 최대 5곳 검색 (검색 결과 0건이어도 중단되지 않음)
4. 1차 추천 + 맛집 목록을 다시 LLM에 전달해 최종 Markdown 리포트 생성 (실패 시 템플릿으로 대체 생성)
5. 모든 단계의 오류(인증/쿼터/네트워크/파싱)는 `errors` 리스트로 수집되어 원본 JSON과 리포트 하단에 함께 기록됨
6. 결과는 `results/` 폴더에 JSON + Markdown으로 저장

## API 키 보안 주의 사항 (중요)

- API 키는 **코드, README, 커밋, 로그, 결과 파일 어디에도 직접 작성하지 않습니다.**
- 실제 키 값은 `.env` 파일에만 두고, `.env`는 `.gitignore`에 등록되어
  Git 저장소에 올라가지 않습니다. (`.env.example`에는 값이 아닌 안내 문구만 있습니다.)
- 이렇게 `.env`/환경변수로 키를 관리하는 이유:
  - 실수로 키가 공개 저장소에 노출되는 사고를 막을 수 있습니다.
  - 키를 교체하더라도 코드를 수정할 필요가 없습니다.
  - 과금/쿼터가 걸린 서비스에서 키 유출로 인한 비용 사고를 예방할 수 있습니다.
- 만약 실수로 키를 커밋했다면, 즉시 해당 서비스(OpenAI/Kakao)에서 키를
  폐기(revoke)하고 새 키를 발급받아야 합니다. `git log`에서 지워도
  과거 커밋 기록에는 남아있을 수 있기 때문입니다.

## 에러 처리 정책

- API 키 미설정 → 즉시 종료 + 설정 방법 안내
- 지도/장소 API 실패(네트워크/인증/쿼터) → 맛집 섹션을 "데이터 없음"으로 처리하고 리포트 생성은 계속 진행
- LLM JSON 파싱 실패 → 1회 재시도, 그래도 실패하면 기본값으로 보정 후 계속 진행 (무한 재시도 없음)
- 모든 오류는 내부 `errors` 리스트에 `{step, type, message}` 형태로 기록되어 원본 JSON과 리포트에 남습니다.
