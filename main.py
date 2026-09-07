"""
나만의 프롬프트 관리 프로그램
Python & Git 기초 미션 - 콘솔 기반 프롬프트 관리 프로그램
"""

CATEGORIES = ["텍스트 생성", "이미지 생성", "영상 생성", "페르소나", "자동화", "기타"]


def get_default_prompts():
    """이전 미션에서 작성한 프롬프트를 기본 데이터로 등록한다."""
    return [
        {
            "title": "블로그 글 작성 도우미",
            "content": "당신은 10년 경력의 전문 블로거입니다. 주어진 주제에 대해 SEO에 최적화된 블로그 글을 작성해주세요.",
            "category": "텍스트 생성",
            "favorite": True,
        },
        {
            "title": "제품 썸네일 생성",
            "content": "다음 제품의 매력적인 썸네일 이미지를 생성해주세요. 밝고 화사한 배경에 제품이 중앙에 위치하도록 해주세요.",
            "category": "이미지 생성",
            "favorite": False,
        },
        {
            "title": "IT 컨설턴트 페르소나",
            "content": "당신은 스타트업 전문 IT 컨설턴트입니다. 비전공자도 이해할 수 있도록 쉬운 용어로 설명해주세요.",
            "category": "페르소나",
            "favorite": False,
        },
    ]


def show_menu():
    print("\n=== 나만의 프롬프트 관리 ===")
    print("1. 프롬프트 추가")
    print("2. 프롬프트 목록")
    print("3. 카테고리별 조회")
    print("4. 프롬프트 검색")
    print("5. 프롬프트 상세 보기")
    print("6. 즐겨찾기 관리")
    print("7. 즐겨찾기 목록")
    print("0. 종료")


def main():
    prompts = get_default_prompts()
    while True:
        show_menu()
        choice = input("선택: ").strip()
        if choice == "0":
            print("\n프로그램을 종료합니다. 이용해주셔서 감사합니다!")
            break
        else:
            print("\n(아직 구현되지 않은 기능입니다)")


if __name__ == "__main__":
    main()
