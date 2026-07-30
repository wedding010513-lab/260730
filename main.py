import io
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


# ---------------------------------------------------------
# 1. 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="전국 시군구 고령화 지도",
    page_icon="🗺️",
    layout="wide",
)

POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/population_yearly.csv.gz"
)

GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/boundaries/sigungu_kr.geojson"
)


# ---------------------------------------------------------
# 2. 행정구역 코드 정리 함수
# ---------------------------------------------------------
def clean_code(value, length):
    """
    행정구역 코드를 글자로 정리하는 함수입니다.

    엑셀이나 판다스가 코드를 숫자로 인식하면 끝에 '.0'이 붙을 수 있어
    이를 제거하고 필요한 길이만큼 앞에 0을 채웁니다.
    """
    if pd.isna(value):
        return ""

    code = str(value).strip()
    code = code.replace(".0", "")
    code = re.sub(r"[^0-9]", "", code)

    if not code:
        return ""

    return code.zfill(length)[:length]


# ---------------------------------------------------------
# 3. 인구 데이터 불러오기
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_population_data():
    """
    압축된 CSV 파일을 내려받아 판다스 데이터프레임으로 읽습니다.

    코드 열은 계산할 숫자가 아니므로 반드시 문자열로 읽습니다.
    """
    response = requests.get(POPULATION_URL, timeout=120)
    response.raise_for_status()

    # 일반적으로 UTF-8이지만 혹시 다른 인코딩일 경우를 대비합니다.
    try:
        population = pd.read_csv(
            io.BytesIO(response.content),
            compression="gzip",
            dtype={"코드": "string"},
            encoding="utf-8-sig",
            low_memory=False,
        )
    except UnicodeDecodeError:
        population = pd.read_csv(
            io.BytesIO(response.content),
            compression="gzip",
            dtype={"코드": "string"},
            encoding="cp949",
            low_memory=False,
        )

    return population


# ---------------------------------------------------------
# 4. 시군구 경계 데이터 불러오기
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_geojson():
    """
    전국 시군구 경계가 들어 있는 GeoJSON 파일을 내려받습니다.
    """
    response = requests.get(GEOJSON_URL, timeout=120)
    response.raise_for_status()

    geojson = response.json()

    # GeoJSON의 코드도 반드시 5자리 문자열로 통일합니다.
    for feature in geojson.get("features", []):
        properties = feature.get("properties", {})
        properties["코드"] = clean_code(properties.get("코드"), 5)

    return geojson


# ---------------------------------------------------------
# 5. 숫자 형식 정리 함수
# ---------------------------------------------------------
def convert_population_number(series):
    """
    인구 열에 쉼표나 빈칸이 들어 있어도 숫자로 바꾸어 줍니다.
    숫자로 바꿀 수 없는 값은 0으로 처리합니다.
    """
    return pd.to_numeric(
        series.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("-", "0", regex=False),
        errors="coerce",
    ).fillna(0)


# ---------------------------------------------------------
# 6. 시군구별 고령화율 계산
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def calculate_aging_rate(population):
    """
    가장 최신 연도의 읍·면·동 인구를 시군구 단위로 합칩니다.

    총인구:
        계_0세부터 계_100세 이상까지의 합

    65세 이상 인구:
        계_65세부터 계_100세 이상까지의 합
    """
    required_columns = {"연도", "시도", "시군구", "코드"}

    missing_columns = required_columns - set(population.columns)
    if missing_columns:
        raise ValueError(
            "인구 데이터에 필요한 열이 없습니다: "
            + ", ".join(sorted(missing_columns))
        )

    data = population.copy()

    # 연도에 '2026년'처럼 글자가 들어가도 숫자 네 자리만 추출합니다.
    data["연도_숫자"] = pd.to_numeric(
        data["연도"].astype("string").str.extract(r"(\d{4})")[0],
        errors="coerce",
    )

    latest_year = int(data["연도_숫자"].max())
    data = data[data["연도_숫자"] == latest_year].copy()

    # 10자리 행정동 코드를 문자열로 정리합니다.
    data["행정동코드"] = data["코드"].apply(
        lambda value: clean_code(value, 10)
    )

    # 행정동 코드 앞 5자리가 시군구 코드입니다.
    data["시군구코드"] = data["행정동코드"].str[:5]

    # 계_0세, 계_1세 등의 연령별 전체 인구 열을 찾습니다.
    age_columns = []
    age_65_columns = []

    for column in data.columns:
        normal_age_match = re.fullmatch(r"계_(\d+)세", str(column))

        if normal_age_match:
            age = int(normal_age_match.group(1))
            age_columns.append(column)

            if age >= 65:
                age_65_columns.append(column)

        elif str(column) == "계_100세 이상":
            age_columns.append(column)
            age_65_columns.append(column)

    if not age_columns:
        raise ValueError(
            "'계_0세', '계_1세' 형식의 연령별 인구 열을 찾지 못했습니다."
        )

    # 인구 열에 들어 있는 쉼표 등을 제거하고 숫자로 바꿉니다.
    for column in age_columns:
        data[column] = convert_population_number(data[column])

    # 각 읍·면·동의 총인구와 65세 이상 인구를 계산합니다.
    data["총인구"] = data[age_columns].sum(axis=1)
    data["65세이상인구"] = data[age_65_columns].sum(axis=1)

    # 시군구 코드가 없는 행은 제외합니다.
    data = data[data["시군구코드"].str.len() == 5].copy()

    # 행정동 자료를 시군구 단위로 합칩니다.
    sigungu = (
        data.groupby("시군구코드", as_index=False)
        .agg(
            총인구=("총인구", "sum"),
            고령인구=("65세이상인구", "sum"),
        )
    )

    # 총인구가 0인 지역은 계산에서 제외합니다.
    sigungu = sigungu[sigungu["총인구"] > 0].copy()

    sigungu["고령화율"] = (
        sigungu["고령인구"] / sigungu["총인구"] * 100
    )

    return latest_year, sigungu


# ---------------------------------------------------------
# 7. GeoJSON 속성을 표로 변환
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def make_boundary_table(geojson):
    """
    GeoJSON 안의 코드·시도·시군구 정보를 표 형태로 만듭니다.
    """
    records = []

    for feature in geojson.get("features", []):
        properties = feature.get("properties", {})

        records.append(
            {
                "시군구코드": clean_code(properties.get("코드"), 5),
                "시도": properties.get("시도", ""),
                "시군구": properties.get("시군구", ""),
            }
        )

    boundary_table = pd.DataFrame(records)
    boundary_table = boundary_table.drop_duplicates("시군구코드")

    return boundary_table


# ---------------------------------------------------------
# 8. 고령화율을 다섯 단계로 분류
# ---------------------------------------------------------
def classify_aging_rate(rate):
    """
    고령화율을 지정된 경계값에 따라 다섯 단계로 분류합니다.
    """
    if pd.isna(rate):
        return np.nan

    if rate < 19:
        return 0
    if rate < 23:
        return 1
    if rate < 28:
        return 2
    if rate < 38:
        return 3

    return 4


# ---------------------------------------------------------
# 9. 단계구분도 만들기
# ---------------------------------------------------------
def make_choropleth_map(map_data, geojson):
    """
    배경 지도 타일 없이 시군구 경계와 색만 표시하는 지도입니다.
    """
    map_data = map_data.copy()
    map_data["단계"] = map_data["고령화율"].apply(classify_aging_rate)

    # 낮은 고령화율은 옅게, 높은 고령화율은 진하게 표현합니다.
    colors = [
        "#FFF7BC",  # 19% 미만: 밝은 노랑
        "#FEE391",  # 19% 이상~23% 미만: 노랑
        "#FEC44F",  # 23% 이상~28% 미만: 밝은 주황
        "#FE9929",  # 28% 이상~38% 미만: 선명한 주황
        "#E31A1C",  # 38% 이상: 선명한 빨강
    ]

    # Plotly 연속형 색상표를 계단식으로 만들어
    # 실제 지도에서는 다섯 가지 색만 나타나게 합니다.
    discrete_colorscale = [
        [0.00, colors[0]],
        [0.20, colors[0]],
        [0.20, colors[1]],
        [0.40, colors[1]],
        [0.40, colors[2]],
        [0.60, colors[2]],
        [0.60, colors[3]],
        [0.80, colors[3]],
        [0.80, colors[4]],
        [1.00, colors[4]],
    ]

    # 마우스를 올렸을 때 보여 줄 추가 정보입니다.
    custom_data = np.column_stack(
        (
            map_data["시군구"].fillna(""),
            map_data["시도"].fillna(""),
            map_data["고령화율"].fillna(0),
        )
    )

    figure = go.Figure(
        go.Choropleth(
            geojson=geojson,
            featureidkey="properties.코드",
            locations=map_data["시군구코드"],
            z=map_data["단계"],
            zmin=-0.5,
            zmax=4.5,
            colorscale=discrete_colorscale,
            marker_line_color="#666666",
            marker_line_width=0.45,
            customdata=custom_data,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "시도: %{customdata[1]}<br>"
                "고령화율: %{customdata[2]:.1f}%"
                "<extra></extra>"
            ),
            colorbar={
                "title": {
                    "text": "65세 이상<br>인구 비율",
                    "side": "right",
                },
                "tickmode": "array",
                "tickvals": [0, 1, 2, 3, 4],
                "ticktext": [
                    "19% 미만",
                    "19% 이상~23% 미만",
                    "23% 이상~28% 미만",
                    "28% 이상~38% 미만",
                    "38% 이상",
                ],
                "len": 0.72,
                "thickness": 22,
                "x": 0.99,
                "y": 0.5,
            },
        )
    )

    figure.update_geos(
        # 대한민국 전체 경계에 맞게 자동 확대합니다.
        fitbounds="locations",

        # 바다·대륙·축 등 배경 요소를 숨깁니다.
        visible=False,
        showcoastlines=False,
        showcountries=False,
        showland=False,
        showocean=False,
        showlakes=False,
        showrivers=False,
        bgcolor="rgba(0,0,0,0)",
    )

    figure.update_layout(
        margin={"r": 170, "t": 10, "l": 10, "b": 10},
        height=760,
        paper_bgcolor="white",
        plot_bgcolor="white",
        hoverlabel={
            "bgcolor": "white",
            "font_size": 14,
        },
    )

    return figure


# ---------------------------------------------------------
# 10. 화면 출력
# ---------------------------------------------------------
st.title("🗺️ 전국 시군구 고령화 지도")
st.caption("시군구별 전체 인구 중 65세 이상 인구가 차지하는 비율")

try:
    with st.spinner("최신 인구 자료와 지도 경계를 불러오는 중입니다."):
        population_data = load_population_data()
        boundary_geojson = load_geojson()

        latest_year, aging_data = calculate_aging_rate(population_data)
        boundary_table = make_boundary_table(boundary_geojson)

        # 이름이 아니라 시군구 코드로 인구와 경계 자료를 연결합니다.
        map_data = boundary_table.merge(
            aging_data,
            on="시군구코드",
            how="left",
        )

    st.subheader(f"{latest_year}년 시군구별 고령화율")

    map_figure = make_choropleth_map(map_data, boundary_geojson)

    st.plotly_chart(
        map_figure,
        use_container_width=True,
        config={
            "displayModeBar": False,
            "scrollZoom": False,
        },
    )

    # 인구 데이터와 정상적으로 연결된 지역만 순위 표에 사용합니다.
    ranking_data = map_data.dropna(subset=["고령화율"]).copy()

    ranking_data["지역"] = (
        ranking_data["시도"].astype(str)
        + " "
        + ranking_data["시군구"].astype(str)
    )

    ranking_data["고령화율(%)"] = ranking_data["고령화율"].round(1)
    ranking_data["총인구(명)"] = ranking_data["총인구"].round().astype(int)
    ranking_data["65세 이상(명)"] = (
        ranking_data["고령인구"].round().astype(int)
    )

    high_10 = (
        ranking_data.sort_values(
            "고령화율",
            ascending=False,
        )
        .head(10)
        .reset_index(drop=True)
    )

    low_10 = (
        ranking_data.sort_values(
            "고령화율",
            ascending=True,
        )
        .head(10)
        .reset_index(drop=True)
    )

    high_10.index = high_10.index + 1
    low_10.index = low_10.index + 1

    table_columns = [
        "지역",
        "고령화율(%)",
        "총인구(명)",
        "65세 이상(명)",
    ]

    st.divider()
    st.subheader("시군구 고령화율 순위")

    left_column, right_column = st.columns(2)

    with left_column:
        st.markdown("#### 고령화율 높은 곳 10개")
        st.dataframe(
            high_10[table_columns],
            use_container_width=True,
            column_config={
                "지역": st.column_config.TextColumn("지역"),
                "고령화율(%)": st.column_config.NumberColumn(
                    "고령화율",
                    format="%.1f%%",
                ),
                "총인구(명)": st.column_config.NumberColumn(
                    "총인구",
                    format="%d명",
                ),
                "65세 이상(명)": st.column_config.NumberColumn(
                    "65세 이상",
                    format="%d명",
                ),
            },
        )

    with right_column:
        st.markdown("#### 고령화율 낮은 곳 10개")
        st.dataframe(
            low_10[table_columns],
            use_container_width=True,
            column_config={
                "지역": st.column_config.TextColumn("지역"),
                "고령화율(%)": st.column_config.NumberColumn(
                    "고령화율",
                    format="%.1f%%",
                ),
                "총인구(명)": st.column_config.NumberColumn(
                    "총인구",
                    format="%d명",
                ),
                "65세 이상(명)": st.column_config.NumberColumn(
                    "65세 이상",
                    format="%d명",
                ),
            },
        )

    # 경계에는 있지만 최신 인구 자료와 연결되지 않은 코드가 있는지 알립니다.
    unmatched = map_data[map_data["고령화율"].isna()]

    if not unmatched.empty:
        with st.expander("인구 자료와 연결되지 않은 지역 확인"):
            st.warning(
                f"경계 자료 중 {len(unmatched)}개 지역은 "
                "최신 인구 자료와 코드가 연결되지 않았습니다."
            )
            st.dataframe(
                unmatched[["시군구코드", "시도", "시군구"]],
                use_container_width=True,
                hide_index=True,
            )

    st.caption(
        "고령화율 = 시군구의 65세 이상 인구 ÷ 시군구 총인구 × 100"
    )

except requests.RequestException as error:
    st.error("인터넷에서 자료를 내려받지 못했습니다.")
    st.exception(error)

except Exception as error:
    st.error("자료를 처리하는 과정에서 오류가 발생했습니다.")
    st.exception(error)
