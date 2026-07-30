import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo


# =========================================================
# 1. 페이지 설정
# =========================================================
st.set_page_config(
    page_title="박스오피스 대시보드",
    page_icon="🎬",
    layout="wide",
)

st.title("🎬 일별 박스오피스 대시보드")
st.caption("원하는 날짜를 선택하여 영화별 순위와 관객 수를 확인할 수 있습니다.")


# =========================================================
# 2. KOBIS 인증키 불러오기
# =========================================================
try:
    KOBIS_KEY = st.secrets["KOBIS_KEY"]

except KeyError:
    st.error(
        "KOBIS 인증키가 등록되지 않았습니다. "
        "Streamlit Secrets에 KOBIS_KEY를 등록해 주세요."
    )
    st.stop()


# =========================================================
# 3. 날짜 선택
# =========================================================
korea_today = datetime.now(ZoneInfo("Asia/Seoul")).date()
yesterday = korea_today - timedelta(days=1)

st.sidebar.header("🔍 조회 조건")

selected_date = st.sidebar.date_input(
    "박스오피스 조회 날짜",
    value=yesterday,
    max_value=yesterday,
)

target_dt = selected_date.strftime("%Y%m%d")

st.sidebar.caption(
    "일별 박스오피스 자료는 보통 당일 자료가 아닌 "
    "전날까지의 자료를 조회할 수 있습니다."
)

st.caption(
    f"조회 기준일: **{selected_date.strftime('%Y년 %m월 %d일')}**"
)


# =========================================================
# 4. KOBIS API 요청 함수
# =========================================================
@st.cache_data(ttl=3600)
def get_boxoffice(api_key, target_date):
    url = (
        "https://www.kobis.or.kr/kobisopenapi/webservice/rest/"
        "boxoffice/searchDailyBoxOfficeList.json"
    )

    params = {
        "key": api_key,
        "targetDt": target_date,
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    return response


try:
    res = get_boxoffice(
        KOBIS_KEY,
        target_dt,
    )

except requests.exceptions.Timeout:
    st.error("영화진흥위원회 서버의 응답 시간이 초과되었습니다.")
    st.stop()

except requests.exceptions.RequestException as error:
    st.error("박스오피스 자료를 요청하는 과정에서 오류가 발생했습니다.")
    st.exception(error)
    st.stop()


# =========================================================
# 5. 응답 상태 확인
# =========================================================
if res.status_code != 200:
    st.error(
        f"요청이 실패했습니다. 상태코드: {res.status_code}"
    )
    st.stop()


try:
    data = res.json()

except ValueError:
    st.error("서버 응답을 JSON 형식으로 변환하지 못했습니다.")
    st.stop()


# KOBIS는 키가 잘못되어도 상태코드 200을 줄 수 있음
if "faultInfo" in data:
    fault_message = data.get(
        "faultInfo",
        {},
    ).get(
        "message",
        "인증키가 올바르지 않습니다.",
    )

    st.error(
        f"API 요청 오류: {fault_message}"
    )
    st.stop()


# =========================================================
# 6. 박스오피스 자료 정리
# =========================================================
box_list = (
    data.get("boxOfficeResult", {})
    .get("dailyBoxOfficeList", [])
)

if not box_list:
    st.warning(
        "선택한 날짜의 박스오피스 자료가 없습니다. "
        "다른 날짜를 선택해 주세요."
    )
    st.stop()


df = pd.DataFrame(box_list)


# 숫자형 열 변환
number_columns = [
    "rank",
    "rankInten",
    "audiCnt",
    "audiAcc",
    "scrnCnt",
    "showCnt",
]

for col in number_columns:
    if col in df.columns:
        df[col] = pd.to_numeric(
            df[col],
            errors="coerce",
        ).fillna(0).astype(int)


df = df.sort_values("rank").reset_index(drop=True)


# =========================================================
# 7. 순위 변동 표시 함수
# =========================================================
def make_rank_change(row):
    rank_old_and_new = str(row.get("rankOldAndNew", "OLD"))
    rank_change = int(row.get("rankInten", 0))

    if rank_old_and_new == "NEW":
        return "🆕 신규 진입"

    if rank_change > 0:
        return f"▲ {rank_change}계단 상승"

    if rank_change < 0:
        return f"▼ {abs(rank_change)}계단 하락"

    return "― 순위 유지"


# =========================================================
# 8. TOP 3 카드
# =========================================================
st.subheader("🏆 박스오피스 TOP 3")

top3 = df.head(3)

top_columns = st.columns(3)

medals = [
    "🥇",
    "🥈",
    "🥉",
]

for index, (_, movie) in enumerate(top3.iterrows()):
    with top_columns[index]:
        st.markdown(
            f"### {medals[index]} {int(movie['rank'])}위"
        )

        st.markdown(
            f"#### {movie['movieNm']}"
        )

        st.metric(
            "당일 관객 수",
            f"{int(movie['audiCnt']):,}명",
        )

        st.write(
            f"**누적 관객:** "
            f"{int(movie['audiAcc']):,}명"
        )

        st.write(
            f"**스크린 수:** "
            f"{int(movie['scrnCnt']):,}개"
        )

        st.write(
            f"**순위 변동:** "
            f"{make_rank_change(movie)}"
        )

        open_date = movie.get("openDt", "")

        if open_date:
            st.caption(
                f"개봉일: {open_date}"
            )


# =========================================================
# 9. 주요 지표
# =========================================================
st.divider()
st.subheader("📊 주요 지표")

total_audience = df["audiCnt"].sum()
total_screen = df["scrnCnt"].sum()
total_show = df["showCnt"].sum()

metric1, metric2, metric3, metric4 = st.columns(4)

metric1.metric(
    "1위 영화",
    df.iloc[0]["movieNm"],
)

metric2.metric(
    "TOP 10 전체 관객",
    f"{total_audience:,}명",
)

metric3.metric(
    "TOP 10 스크린",
    f"{total_screen:,}개",
)

metric4.metric(
    "TOP 10 상영 횟수",
    f"{total_show:,}회",
)


# =========================================================
# 10. TOP 10 표
# =========================================================
st.subheader("📋 박스오피스 TOP 10")

table_columns = [
    "rank",
    "movieNm",
    "openDt",
    "audiCnt",
    "audiAcc",
    "scrnCnt",
    "showCnt",
]

table = df[table_columns].copy()

table["순위 변동"] = df.apply(
    make_rank_change,
    axis=1,
)

table.columns = [
    "순위",
    "영화명",
    "개봉일",
    "관객수",
    "누적관객",
    "스크린수",
    "상영횟수",
    "순위 변동",
]

table = table[
    [
        "순위",
        "영화명",
        "순위 변동",
        "개봉일",
        "관객수",
        "누적관객",
        "스크린수",
        "상영횟수",
    ]
]

st.dataframe(
    table,
    hide_index=True,
    use_container_width=True,
    column_config={
        "순위": st.column_config.NumberColumn(
            width="small",
            format="%d위",
        ),
        "영화명": st.column_config.TextColumn(
            width="large",
        ),
        "관객수": st.column_config.NumberColumn(
            format="%d명",
        ),
        "누적관객": st.column_config.NumberColumn(
            format="%d명",
        ),
        "스크린수": st.column_config.NumberColumn(
            format="%d개",
        ),
        "상영횟수": st.column_config.NumberColumn(
            format="%d회",
        ),
    },
)


# =========================================================
# 11. 관객수 상위 5편 그래프
# =========================================================
st.subheader("📈 관객수 상위 5편")

top5 = (
    table.sort_values(
        "관객수",
        ascending=False,
    )
    .head(5)
    .set_index("영화명")
)

st.bar_chart(
    top5["관객수"],
    horizontal=True,
)


# =========================================================
# 12. 영화별 상세 정보
# =========================================================
st.subheader("🔎 영화별 상세 조회")

selected_movie = st.selectbox(
    "영화를 선택하세요.",
    df["movieNm"].tolist(),
)

movie_detail = df[
    df["movieNm"] == selected_movie
].iloc[0]

detail1, detail2, detail3, detail4 = st.columns(4)

detail1.metric(
    "순위",
    f"{int(movie_detail['rank'])}위",
)

detail2.metric(
    "당일 관객",
    f"{int(movie_detail['audiCnt']):,}명",
)

detail3.metric(
    "누적 관객",
    f"{int(movie_detail['audiAcc']):,}명",
)

detail4.metric(
    "상영 횟수",
    f"{int(movie_detail['showCnt']):,}회",
)

st.write(
    f"**순위 변동:** {make_rank_change(movie_detail)}"
)

st.write(
    f"**개봉일:** {movie_detail['openDt']}"
)

st.write(
    f"**스크린 수:** {int(movie_detail['scrnCnt']):,}개"
)
