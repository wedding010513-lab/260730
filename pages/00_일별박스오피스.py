import html
import json
import re

import pandas as pd
import requests
import streamlit as st
from openai import OpenAI


# =========================================================
# 1. 페이지 기본 설정
# =========================================================
st.set_page_config(
    page_title="우리나라 여행 도우미",
    page_icon="🧳",
    layout="wide",
)

st.title("🧳 우리나라 여행 도우미")
st.caption(
    "가고 싶은 국내 지역을 입력하면 "
    "가볼 만한 곳 TOP 3와 대표 사진을 안내합니다."
)


# =========================================================
# 2. Upstage Solar API 연결
# =========================================================
try:
    client = OpenAI(
        api_key=st.secrets["SOLAR_API_KEY"],
        base_url="https://api.upstage.ai/v1",
    )

except KeyError:
    st.error(
        "Solar API 키가 등록되지 않았습니다. "
        "Streamlit의 Secrets에 SOLAR_API_KEY를 등록해 주세요."
    )
    st.stop()


# =========================================================
# 3. 기본 설정
# =========================================================
MODEL_NAME = "solar-open2"

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"

HEADERS = {
    "User-Agent": (
        "KoreaTravelTeacherBot/1.0 "
        "(educational Streamlit application)"
    )
}


# =========================================================
# 4. AI에게 전달할 역할
# =========================================================
SYSTEM_PROMPT = """
너는 국내 여행지를 소개하는 친절한 여행 정보 선생님이야.

사용자가 대한민국의 지역명을 입력하면 해당 지역에서 가볼 만한 장소
TOP 3를 선정해 소개해야 해.

반드시 다음 규칙을 지켜.

1. 대한민국 안에 있는 여행지만 추천해.
2. 장소는 실제로 존재하는 대표적인 관광지로 선정해.
3. 같은 성격의 장소만 반복하지 말고 자연, 역사, 문화, 체험 등을 적절히 섞어.
4. 학생과 가족 여행객도 이해할 수 있는 쉬운 한국어로 작성해.
5. 운영시간, 입장료처럼 자주 바뀌는 정보는 확실하지 않으면 단정하지 마.
6. 여행지마다 선정 이유와 활동 내용을 구체적으로 설명해.
7. 답변은 설명문이 아니라 반드시 아래 JSON 형식으로만 작성해.
8. JSON 바깥에는 아무 글도 작성하지 마.
9. 마크다운 코드 블록 기호를 사용하지 마.

JSON 형식:

{
  "region": "지역명",
  "title": "추천 제목",
  "summary": "지역 전체의 여행 특징을 두 문장으로 설명",
  "places": [
    {
      "rank": 1,
      "name": "장소명",
      "category": "자연 또는 역사 또는 문화 또는 체험",
      "address_hint": "시군구와 읍면동 정도의 위치",
      "reason": "이 장소를 추천한 이유",
      "activities": ["활동 1", "활동 2", "활동 3"],
      "visit_tip": "방문할 때 알아두면 좋은 점",
      "image_keyword": "위키미디어에서 사진을 찾기 좋은 장소 공식 명칭"
    },
    {
      "rank": 2,
      "name": "장소명",
      "category": "분류",
      "address_hint": "위치",
      "reason": "추천 이유",
      "activities": ["활동 1", "활동 2", "활동 3"],
      "visit_tip": "방문 도움말",
      "image_keyword": "사진 검색어"
    },
    {
      "rank": 3,
      "name": "장소명",
      "category": "분류",
      "address_hint": "위치",
      "reason": "추천 이유",
      "activities": ["활동 1", "활동 2", "활동 3"],
      "visit_tip": "방문 도움말",
      "image_keyword": "사진 검색어"
    }
  ],
  "course_tip": "세 장소를 둘러볼 때의 간단한 동선 또는 일정 조언",
  "caution": "날씨나 휴관일 등 방문 전 확인할 사항"
}

사용자가 지역이 아닌 질문을 하면 region에는 빈 문자열을 넣고
title에는 '지역명을 입력해 주세요'라고 작성해.
"""


# =========================================================
# 5. 세션 상태 만들기
# =========================================================
if "travel_history" not in st.session_state:
    st.session_state.travel_history = []

if "last_result" not in st.session_state:
    st.session_state.last_result = None


# =========================================================
# 6. AI 응답에서 JSON 추출
# =========================================================
def extract_json(text):
    """
    AI가 JSON 앞뒤에 불필요한 글자를 붙여도
    가능한 범위에서 JSON 부분만 추출합니다.
    """
    if not text:
        raise ValueError("AI 응답이 비어 있습니다.")

    cleaned = text.strip()

    # 마크다운 코드 블록 제거
    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    try:
        return json.loads(cleaned)

    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end == -1 or start >= end:
            raise ValueError("AI 응답에서 JSON을 찾지 못했습니다.")

        return json.loads(cleaned[start:end + 1])


# =========================================================
# 7. AI 여행 추천 요청
# =========================================================
@st.cache_data(ttl=60 * 60, show_spinner=False)
def request_travel_recommendation(region_query):
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"사용자가 입력한 국내 여행 지역은 "
                    f"'{region_query}'이야. "
                    f"이 지역의 대표 여행지 TOP 3를 선정해 줘."
                ),
            },
        ],
        reasoning_effort="none",
        temperature=0.4,
    )

    answer = response.choices[0].message.content

    return extract_json(answer)


# =========================================================
# 8. 위키미디어 사진 검색
# =========================================================
@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def search_wikimedia_image(place_name, region_name):
    """
    위키미디어 공용에서 장소 사진을 검색합니다.

    반환값:
    {
        "image_url": 이미지 주소,
        "description_url": 원본 자료 페이지,
        "artist": 촬영자,
        "license": 이용 허가,
        "title": 파일 제목
    }
    """

    search_queries = [
        f"{place_name} {region_name}",
        place_name,
    ]

    for search_query in search_queries:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": search_query,
            "gsrlimit": 8,
            "prop": "imageinfo",
            "iiprop": "url|mime|extmetadata",
            "iiurlwidth": 1000,
            "origin": "*",
        }

        try:
            response = requests.get(
                WIKIMEDIA_API_URL,
                params=params,
                headers=HEADERS,
                timeout=12,
            )
            response.raise_for_status()
            data = response.json()

        except requests.RequestException:
            continue

        pages = data.get("query", {}).get("pages", {})

        if not pages:
            continue

        candidates = []

        for page in pages.values():
            image_info_list = page.get("imageinfo", [])

            if not image_info_list:
                continue

            image_info = image_info_list[0]
            mime_type = image_info.get("mime", "")

            # 일반 사진 파일만 사용
            if mime_type not in [
                "image/jpeg",
                "image/png",
                "image/webp",
            ]:
                continue

            image_url = (
                image_info.get("thumburl")
                or image_info.get("url")
            )

            if not image_url:
                continue

            metadata = image_info.get("extmetadata", {})

            description = strip_html(
                metadata.get(
                    "ImageDescription",
                    {},
                ).get("value", "")
            )

            title = page.get("title", "")

            score = calculate_image_score(
                title=title,
                description=description,
                place_name=place_name,
                region_name=region_name,
            )

            candidates.append(
                {
                    "score": score,
                    "image_url": image_url,
                    "description_url": (
                        image_info.get("descriptionurl", "")
                    ),
                    "artist": strip_html(
                        metadata.get(
                            "Artist",
                            {},
                        ).get("value", "정보 없음")
                    ),
                    "license": strip_html(
                        metadata.get(
                            "LicenseShortName",
                            {},
                        ).get("value", "정보 없음")
                    ),
                    "title": title.replace("File:", ""),
                }
            )

        if candidates:
            candidates.sort(
                key=lambda item: item["score"],
                reverse=True,
            )
            return candidates[0]

    return None


# =========================================================
# 9. HTML 태그 정리
# =========================================================
def strip_html(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", "", str(text))
    return html.unescape(text).strip()


# =========================================================
# 10. 이미지 검색 결과 점수 계산
# =========================================================
def calculate_image_score(
    title,
    description,
    place_name,
    region_name,
):
    """
    검색된 파일 중 장소명과 관련성이 높은 이미지를 우선합니다.
    """
    combined_text = f"{title} {description}".lower()
    score = 0

    place_words = [
        word.strip().lower()
        for word in re.split(r"\s+", place_name)
        if len(word.strip()) >= 2
    ]

    region_words = [
        word.strip().lower()
        for word in re.split(r"\s+", region_name)
        if len(word.strip()) >= 2
    ]

    for word in place_words:
        if word in combined_text:
            score += 5

    for word in region_words:
        if word in combined_text:
            score += 2

    # 지도, 로고, 도표보다 실제 사진을 우선
    undesirable_words = [
        "map",
        "지도",
        "logo",
        "로고",
        "icon",
        "아이콘",
        "diagram",
        "도표",
        "symbol",
        "기호",
    ]

    for word in undesirable_words:
        if word in combined_text:
            score -= 5

    return score


# =========================================================
# 11. 카테고리 표시
# =========================================================
def category_icon(category):
    category = str(category)

    if "자연" in category:
        return "🌿"

    if "역사" in category:
        return "🏛️"

    if "문화" in category:
        return "🎨"

    if "체험" in category:
        return "🎯"

    if "먹거리" in category:
        return "🍽️"

    return "📍"


# =========================================================
# 12. 여행지 카드 출력
# =========================================================
def display_place_card(place, region):
    rank = place.get("rank", "")
    name = place.get("name", "장소명 없음")
    category = place.get("category", "여행지")
    address_hint = place.get("address_hint", "")
    reason = place.get("reason", "")
    activities = place.get("activities", [])
    visit_tip = place.get("visit_tip", "")
    image_keyword = place.get("image_keyword", name)

    medal = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
        "1": "🥇",
        "2": "🥈",
        "3": "🥉",
    }.get(rank, "📌")

    st.markdown(
        f"### {medal} TOP {rank}. {name}"
    )

    st.caption(
        f"{category_icon(category)} {category}"
        + (
            f" · 📍 {address_hint}"
            if address_hint
            else ""
        )
    )

    image_data = search_wikimedia_image(
        place_name=image_keyword,
        region_name=region,
    )

    if image_data:
        st.image(
            image_data["image_url"],
            caption=(
                f"{name} 관련 이미지 · "
                f"촬영자: {image_data['artist']} · "
                f"이용 허가: {image_data['license']}"
            ),
            use_container_width=True,
        )

        if image_data["description_url"]:
            st.link_button(
                "사진 원본과 이용 조건 확인",
                image_data["description_url"],
                use_container_width=True,
            )

    else:
        st.info(
            "이 장소의 대표 사진을 찾지 못했습니다. "
            "여행지 설명은 정상적으로 확인할 수 있습니다."
        )

    st.markdown(f"**추천 이유**  \n{reason}")

    if activities:
        st.markdown("**이곳에서 해볼 활동**")

        for activity in activities:
            st.markdown(f"- {activity}")

    if visit_tip:
        st.markdown(
            f"**방문 도움말**  \n{visit_tip}"
        )


# =========================================================
# 13. 전체 여행 결과 출력
# =========================================================
def display_travel_result(result):
    region = result.get("region", "")
    title = result.get(
        "title",
        f"{region} 여행지 TOP 3",
    )
    summary = result.get("summary", "")
    places = result.get("places", [])
    course_tip = result.get("course_tip", "")
    caution = result.get("caution", "")

    if not region or not places:
        st.warning(
            "국내 지역명을 입력해 주세요. "
            "예: 공주, 여수, 경주, 속초, 전주"
        )
        return

    st.markdown(f"## 📍 {title}")

    if summary:
        st.info(summary)

    valid_places = places[:3]

    if len(valid_places) < 3:
        st.warning(
            "추천 결과가 3개보다 적습니다. "
            "지역명을 조금 더 구체적으로 입력해 보세요."
        )

    columns = st.columns(len(valid_places))

    for column, place in zip(
        columns,
        valid_places,
    ):
        with column:
            with st.container(border=True):
                display_place_card(
                    place=place,
                    region=region,
                )

    if course_tip:
        st.markdown("### 🚗 추천 동선")
        st.success(course_tip)

    if caution:
        st.markdown("### ✅ 방문 전 확인")
        st.warning(caution)

    st.caption(
        "AI 추천 내용과 관광지 운영 정보는 달라질 수 있습니다. "
        "출발 전 공식 관광 안내 페이지에서 휴관일과 이용시간을 확인하세요."
    )


# =========================================================
# 14. 빠른 지역 선택
# =========================================================
st.subheader("어디로 떠나 볼까요?")

quick_regions = [
    "서울",
    "부산",
    "경주",
    "전주",
    "공주",
    "여수",
    "강릉",
    "속초",
    "제주",
]

quick_columns = st.columns(3)

selected_quick_region = None

for index, region in enumerate(quick_regions):
    with quick_columns[index % 3]:
        if st.button(
            region,
            key=f"quick_{region}",
            use_container_width=True,
        ):
            selected_quick_region = region


# =========================================================
# 15. 지역 검색 입력
# =========================================================
user_input = st.chat_input(
    "국내 지역을 입력하세요. 예: 공주, 경주, 여수"
)

search_region = selected_quick_region or user_input


# =========================================================
# 16. 새 검색 처리
# =========================================================
if search_region:
    search_region = search_region.strip()

    st.session_state.travel_history.append(search_region)

    with st.chat_message("user"):
        st.markdown(
            f"**{search_region}**에서 가볼 만한 곳 "
            f"TOP 3를 알려 주세요."
        )

    with st.chat_message("assistant"):
        try:
            with st.spinner(
                f"{search_region}의 대표 여행지를 찾고 있습니다."
            ):
                result = request_travel_recommendation(
                    search_region
                )

            st.session_state.last_result = result
            display_travel_result(result)

        except json.JSONDecodeError:
            st.error(
                "AI의 답변 형식을 읽지 못했습니다. "
                "같은 지역을 다시 검색해 주세요."
            )

        except requests.RequestException:
            st.error(
                "사진 자료를 가져오지 못했습니다. "
                "인터넷 연결을 확인해 주세요."
            )

        except Exception as error:
            st.error(
                "여행 정보를 가져오지 못했습니다. "
                "잠시 후 다시 검색해 주세요."
            )

            with st.expander("오류 내용 확인"):
                st.code(str(error))


# =========================================================
# 17. 직전 검색 결과 유지
# =========================================================
elif st.session_state.last_result is not None:
    display_travel_result(
        st.session_state.last_result
    )


# =========================================================
# 18. 최근 검색 지역
# =========================================================
if st.session_state.travel_history:
    st.divider()
    st.subheader("🕘 최근 검색 지역")

    recent_regions = list(
        dict.fromkeys(
            reversed(
                st.session_state.travel_history
            )
        )
    )[:5]

    history_columns = st.columns(
        len(recent_regions)
    )

    for column, region in zip(
        history_columns,
        recent_regions,
    ):
        with column:
            st.write(f"📍 {region}")


# =========================================================
# 19. 대화 초기화
# =========================================================
st.sidebar.header("여행 도우미")

st.sidebar.markdown(
    """
**이용 방법**

1. 국내 지역명을 입력합니다.
2. 추천 여행지 TOP 3를 확인합니다.
3. 대표 사진과 활동 내용을 살펴봅니다.
4. 방문 전 최신 운영 정보를 확인합니다.
    """
)

if st.sidebar.button(
    "검색 기록 초기화",
    use_container_width=True,
):
    st.session_state.travel_history = []
    st.session_state.last_result = None
    st.cache_data.clear()
    st.rerun()


st.sidebar.caption(
    "사진 자료: 위키미디어 공용"
)
