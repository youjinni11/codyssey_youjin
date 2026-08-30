# 노코드 자동화 기초: 워크플로우 설계

Make와 Zapier를 활용해 동일한 이메일 자동 분류/알림 워크플로우를 구현하고 비교 분석한 과제입니다.

## 📁 폴더 구조

```
├── project1-도구비교/
│   ├── 비교분석보고서.md
│   └── screenshots/
│       ├── make-01-구조.png
│       ├── make-02-router조건.png
│       ├── make-03-실행로그.png
│       ├── make-04-discord-일정.png
│       ├── make-05-discord-업무.png
│       ├── zapier-06-자동화1-구조.png
│       ├── zapier-07-자동화1-filter.png
│       ├── zapier-08-자동화1-discord.png
│       ├── zapier-09-자동화2-구조.png
│       ├── zapier-10-자동화2-filter.png
│       └── zapier-11-자동화2-discord.png
└── project2-자유주제/
    ├── 워크플로우설계문서.md
    └── screenshots/
        ├── 구현화면.png
        └── 실행결과.png
```

## 🎯 워크플로우 개요

Gmail에 새 메일이 도착하면 제목/본문 키워드에 따라 조건 분기하여 Discord로 알림을 전송하는 자동화입니다.

```
Gmail (신규 메일 감지)
        │
        ▼
     조건 분기
     ├─ "일정", "미팅", "회의" 포함 → Discord DM: 일정 관련 알림
     └─ "업무", "공지", "요청", "안내" 포함 → Discord DM: 업무 확인 알림
```

## [프로젝트 1] 자동화 도구 비교 구현
동일한 워크플로우를 **Make**와 **Zapier**로 각각 구현하고 비교했습니다.

- 상세 내용: [비교분석보고서.md](./project1-도구비교/비교분석보고서.md)

## [프로젝트 2] 자유 주제 자동화 설계 및 구현
반복되는 이메일 확인 업무를 자동화했습니다. (Make로 구현)

- 상세 내용: [워크플로우설계문서.md](./project2-자유주제/워크플로우설계문서.md)

## 🛠 사용 도구
- Make (Integromat)
- Zapier
- Gmail
- Discord
