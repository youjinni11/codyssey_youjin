# AI 브랜드 아이덴티티 생성기 (Project A)

브랜드 브리프(JSON) 하나로 **네이밍 · 슬로건 · 스토리 · 컬러 팔레트 · 로고 시안**을 자동 생성하는 Python CLI 프로그램입니다. (보너스: 경쟁사 분석, 한글+영문 네이밍 포함)

## 1. 설치

```bash
# Python 3.10 이상 필요
pip install -r requirements.txt      # requests, matplotlib
```

## 2. API 키 설정 (코드에 키를 쓰지 않음)

기본값은 텍스트(네이밍·슬로건·스토리·팔레트)와 로고 이미지 모두 **OpenAI 키 1개**로 동작합니다. (https://platform.openai.com/api-keys, 이미지 생성은 유료 크레딧이 필요합니다)

```bash
export OPENAI_API_KEY=키값            # macOS/Linux   (Windows: set OPENAI_API_KEY=키값)
```
또는 `.env.example` 을 `.env` 로 복사해 키를 넣습니다. (`.env` 는 `.gitignore` 에 등록되어 GitHub 에 올라가지 않습니다.)

텍스트를 Gemini로, 로고를 Hugging Face 등 다른 서비스로 바꾸고 싶다면 `.env.example`의 아래쪽 "다른 서비스로 바꾸고 싶을 때만" 항목을 참고하세요(`BRAND_TEXT_PROVIDER`, `BRAND_IMAGE_PROVIDER` 환경변수로 전환).

소속 기관(코디세이)이 제공하는 **공개 API**(`/public-api-console`에서 발급하는 `sk-cody-live-...` 키, 비용은 기관 부담)를 쓸 때는 `OPENAI_API_KEY`에 그 키를, `OPENAI_BASE_URL=https://copa.codyssey.kr/v1`, `BRAND_TEXT_MODEL=gpt-5.4-mini`(콘솔의 사용 가능 모델 목록 기준)를 `.env`에 추가하세요(`.env.example`에 예시 포함).

## 3. 실행

```bash
python brand_generator.py
```
```
브리프 파일 경로를 입력하세요: brief.json
출력 폴더 경로를 입력하세요 (엔터 시 ./output):
```

### 브리프 JSON 형식 (`brief.json` 예시 포함)

| 필드 | 필수 | 설명 |
|---|---|---|
| industry | 필수 | 업종 |
| target | 필수 | 타겟 고객 |
| keywords | 필수 | 키워드 리스트 |
| tone | 선택 | 톤앤매너 |
| competitors | 선택 | 경쟁사 리스트 (있으면 보너스 경쟁사 분석 실행) |
| notes | 선택 | 추가 요청사항 |

## 4. 출력물 (`./output/`)

| 파일 | 내용 |
|---|---|
| `brand_result.json` | 네이밍(한글/영문/의미), 슬로건 3개, 스토리, 팔레트 HEX, 경쟁사 분석, 실패한 단계(errors) |
| `color_palette.png` | 메인/서브 컬러 시각화 (matplotlib) |
| `logo_01.png` ~ `logo_03.png` | 로고 시안 3개 |

## 5. 동작 구조 (파이프라인)

```
brief.json → 검증 → [LLM] 네이밍 → [LLM] 슬로건 → [LLM] 스토리 → [LLM] 팔레트 → matplotlib PNG
                                                         ↓ (1순위 브랜드명 + 메인 컬러를 프롬프트에 반영)
                                              [이미지 API] 로고 3장 → PNG → brand_result.json 저장
```

- **텍스트**: OpenAI Chat Completions(`gpt-4o-mini`), `response_format=json_object` 로 JSON 응답 강제. `BRAND_TEXT_PROVIDER=gemini` 로 바꾸면 Gemini `generateContent` 사용.
- **이미지**: OpenAI Images API(`gpt-image-1-mini`, quality=low)로 로고를 생성해 PNG 저장. DALL-E 2/3 은 2026-05-12 에 OpenAI API 에서 제거되어, 후속 모델인 gpt-image 계열을 사용합니다. `BRAND_IMAGE_PROVIDER=huggingface`(무료 크레딧, `pip install huggingface_hub`, HF_TOKEN 필요) 또는 `gemini`(유료 티어 필요)로 바꿀 수도 있습니다. 로고마다 스타일 문구를 달리해 시안을 다양화. 이미지 속 글자 깨짐을 막기 위해 "no text" 로 심볼 중심 생성.
- 모델은 환경변수 `BRAND_TEXT_MODEL`, `BRAND_OPENAI_IMAGE_MODEL`(HF/Gemini용은 `BRAND_HF_IMAGE_MODEL`/`BRAND_IMAGE_MODEL`) 로 교체 가능.
- **코디세이 공개 API**: `OPENAI_BASE_URL`에 `codyssey`가 포함되어 있으면(`https://copa.codyssey.kr/v1`) 텍스트는 OpenAI 와 동일한 `/v1/chat/completions` 로, 이미지는 경로(`/api/v1/images`)와 응답 구조(`result.images[].b64_json`, OpenAI 는 `data[].b64_json`)가 달라 코드가 자동으로 이 방식으로 전환해 호출합니다. 이 API는 `response_format`(JSON 강제 응답) 파라미터를 지원하지 않아(400 unsupported_feature) 이때는 자동으로 빼고, 대신 프롬프트로 JSON만 출력하도록 지시하고 응답이 ```코드블록으로 감싸져 와도 파싱하도록 처리합니다.

## 6. 에러 처리

| 상황 | 대응 |
|---|---|
| API 키 없음 | 설정 방법을 안내하고 종료 (OpenAI 키가 없으면 로고 단계만 안내 후 건너뜀) |
| 키 오류 / 한도 초과(429) / 권한(403) / 정책 거부(400) / 서버 오류(5xx) / 타임아웃 / 네트워크 끊김 | 원인별 한국어 메시지 출력 후 **다음 단계 계속 진행** |
| LLM 응답이 JSON 이 아님 | 1회 자동 재시도 후 실패 처리 |
| 서버 일시 오류(503)·타임아웃 | 3초/8초/15초 간격으로 최대 3회 자동 재시도 |
| HEX 형식 오류 | 정규식(`#RRGGBB`) 검증, 잘못된 색은 제외 |
| 네이밍/팔레트가 실패 | 로고는 키워드·기본 문구로 계속 생성 |
| 브리프 파일 없음/JSON 오류/필수 필드 누락 | 무엇이 문제인지 알려주고 종료 |

실패한 단계는 `brand_result.json` 의 `errors` 에 기록됩니다.
