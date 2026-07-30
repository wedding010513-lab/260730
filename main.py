import io
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


# ---------------------------------------------------------
# 1. 스트림릿 화면 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="광주광역시 고령화 지도",
    page_icon="🗺️",
    layout="wide",
)

# 인구 데이터 주소
POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/population_yearly.csv.gz"
)

# 전국 시군구 경계 데이터 주소
GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/boundaries/sigungu_kr.geojson"
)

# 지도에 표시할 지역
TARGET_CITY = "광주광역시"


# ---------------------------------------------------------
# 2. 행정구역 코드 정리 함수
# ---------------------------------------------------------
def clean_code(value, length):
    """
    행정구역 코드를 문자열로 정리합니다.

    행정구역 코드는 계산할 숫자가 아니라 지역을 구분하는 이름표입니다.
    따라서 숫자가 아닌 문자열로 사용해야 합니다.
    """
    if pd.isna(value):
        return ""

    code = str(value).strip()

    # 숫자로 잘못 읽히면서 붙을 수 있는 .0을 제거합니다.
    if code.endswith(".0"):
        code = code[:-2]

    # 숫자가 아닌 문자는 제거합니다.
    code = re.sub(r"[^0-9]", "", code)

    if not code:
        return ""

    # 필요한 길이보다 짧으면 앞에 0을 채웁니다.
    code = code.zfill(length)

    # 필요한 길이만 사용합니다.
    return code[:length]


# ---------------------------------------------------------
# 3. 인구 데이터 불러오기
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_population_data():
    """
    압축된 CSV 인구 데이터를 인터넷에서 불러옵니다.

    코드 열은 반드시 문자열로 읽습니다.
    """
    response = requests.get(POPULATION_URL, timeout=120)
    response.raise_for_status()

    try:
        population = pd.read_csv(
            io.BytesIO(response.content),
            compression="gzip",
            dtype={"코드": "string"},
            encoding="utf-8-sig",
            low_memory=False,
        )

    except UnicodeDecodeError:
        # UTF-8로 읽히지 않을 경우 한글 인코딩으로 다시 시도합니다.
        population = pd.read_csv(
            io.BytesIO(response.content),
            compression="gzip",
            dtype={"코드": "string"},
            encoding="cp949",
            low_memory=False,
        )

    return population


# ---------------------------------------------------------
# 4. 지도 경계 데이터 불러오기
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_gwangju_geojson():
    """
    전국 시군구 GeoJSON에서 광주광역시의 5개 구만 추출합니다.
    """
    response = requests.get(GEOJSON_URL, timeout=120)
    response.raise_for_status()

    nationwide_geojson = response.json()

    gwangju_features = []

    for feature in nationwide_geojson.get("features", []):
        properties = feature.get("properties", {})

        sido_name = str(properties.get("시도", "")).strip()

        # 광주광역시 경계만 선택합니다.
        if sido_name == TARGET_CITY:
            properties["코드"] = clean_code(
                properties.get("코드"),
                5,
            )

            gwangju_features.append(feature)

    if not gwangju_features:
        raise ValueError(
            "GeoJSON에서 광주광역시 경계를 찾지 못했습니다."
        )

    return {
        "type": "FeatureCollection",
        "features": gwangju_features,
    }


# ---------------------------------------------------------
# 5. 인구 숫자 정리 함수
# ---------------------------------------------------------
def convert_population_number(series):
    """
    인구 자료에 쉼표, 공백, 하이픈 등이 있어도 숫자로 바꿉니다.
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
# 6. 광주광역시 5개 구의 고령화율 계산
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def calculate_gwangju_aging_rate(population):
    """
    가장 최신 연도의 광주광역시 읍·면·동 인구를 구별로 합칩니다.

    고령화율 계산 방법:
    65세 이상 인구 ÷ 전체 인구 × 100
    """
    required_columns = {
        "연도",
        "시도",
        "시군구",
        "코드",
    }

    missing_columns = required_columns - set(population.columns)

    if missing_columns:
        raise ValueError(
            "인구 데이터에 필요한 열이 없습니다: "
            + ", ".join(sorted(missing_columns))
        )

    data = population.copy()

    # 연도 열에 2026년처럼 글자가 포함되어 있어도
    # 숫자 네 자리만 추출합니다.
    data["연도_숫자"] = pd.to_numeric(
        data["연도"]
        .astype("string")
        .str.extract(r"(\d{4})")[0],
        errors="coerce",
    )

    # 데이터에 들어 있는 가장 최신 연도를 찾습니다.
    latest_year = int(data["연도_숫자"].max())

    # 최신 연도 자료만 선택합니다.
    data = data[
        data["연도_숫자"] == latest_year
    ].copy()

    # 광주광역시 자료만 선택합니다.
    data["시도"] = data["시도"].astype("string").str.strip()

    data = data[
        data["시도"] == TARGET_CITY
    ].copy()

    if data.empty:
        raise ValueError(
            f"{latest_year}년 인구 자료에서 "
            "광주광역시 자료를 찾지 못했습니다."
        )

    # 10자리 행정동 코드를 문자열로 정리합니다.
    data["행정동코드"] = data["코드"].apply(
        lambda value: clean_code(value, 10)
    )

    # 행정동 코드 앞 5자리가 시군구 코드입니다.
    data["시군구코드"] = data["행정동코드"].str[:5]

    # 계_0세, 계_1세와 같은 전체 인구 열을 찾습니다.
    total_age_columns = []

    # 65세 이상 인구 열을 찾습니다.
    elderly_age_columns = []

    for column in data.columns:
        column_name = str(column).strip()

        # 계_0세부터 계_99세까지 찾습니다.
        age_match = re.fullmatch(r"계_(\d+)세", column_name)

        if age_match:
            age = int(age_match.group(1))

            total_age_columns.append(column)

            if age >= 65:
                elderly_age_columns.append(column)

        # 계_100세 이상 열을 포함합니다.
        elif column_name == "계_100세 이상":
            total_age_columns.append(column)
            elderly_age_columns.append(column)

    if not total_age_columns:
        raise ValueError(
            "'계_0세', '계_1세' 형식의 "
            "연령별 인구 열을 찾지 못했습니다."
        )

    # 인구 열을 숫자 형식으로 바꿉니다.
    for column in total_age_columns:
        data[column] = convert_population_number(data[column])

    # 각 읍·면·동의 전체 인구를 계산합니다.
    data["총인구"] = data[total_age_columns].sum(axis=1)

    # 각 읍·면·동의 65세 이상 인구를 계산합니다.
    data["65세이상인구"] = data[elderly_age_columns].sum(axis=1)

    # 정상적인 5자리 시군구 코드가 있는 자료만 사용합니다.
    data = data[
        data["시군구코드"].str.len() == 5
    ].copy()

    # 읍·면·동 자료를 구 단위로 합칩니다.
    district_data = (
        data.groupby(
            "시군구코드",
            as_index=False,
        )
        .agg(
            총인구=("총인구", "sum"),
            고령인구=("65세이상인구", "sum"),
        )
    )

    # 전체 인구가 0인 지역은 제외합니다.
    district_data = district_data[
        district_data["총인구"] > 0
    ].copy()

    # 고령화율을 계산합니다.
    district_data["고령화율"] = (
        district_data["고령인구"]
        / district_data["총인구"]
        * 100
    )

    return latest_year, district_data


# ---------------------------------------------------------
# 7. GeoJSON의 지역 정보를 표로 만들기
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def make_boundary_table(gwangju_geojson):
    """
    GeoJSON 속성의 코드, 시도, 시군구 정보를 표로 만듭니다.
    """
    records = []

    for feature in gwangju_geojson.get("features", []):
        properties = feature.get("properties", {})

        records.append(
            {
                "시군구코드": clean_code(
                    properties.get("코드"),
                    5,
                ),
                "시도": str(
                    properties.get("시도", "")
                ).strip(),
                "시군구": str(
                    properties.get("시군구", "")
                ).strip(),
            }
        )

    boundary_table = pd.DataFrame(records)

    boundary_table = boundary_table.drop_duplicates(
        subset="시군구코드"
    )

    return boundary_table


# ---------------------------------------------------------
# 8. 고령화율을 다섯 단계로 분류
# ---------------------------------------------------------
def classify_aging_rate(rate):
    """
    고령화율을 기존 기준에 따라 다섯 단계로 나눕니다.

    1단계: 19% 미만
    2단계: 19% 이상 23% 미만
    3단계: 23% 이상 28% 미만
    4단계: 28% 이상 38% 미만
    5단계: 38% 이상
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
# 9. 광주광역시 단계구분도 만들기
# ---------------------------------------------------------
def make_gwangju_map(map_data, gwangju_geojson):
    """
    광주광역시 5개 구의 고령화율을 블루 계열로 표현합니다.
    """
    map_data = map_data.copy()

    map_data["단계"] = map_data["고령화율"].apply(
        classify_aging_rate
    )

    # 밝은 하늘색에서 진한 파란색으로 이어지는 5단계 색상입니다.
    blue_colors = [
        "#E8F4FD",  # 19% 미만
        "#B9DDF4",  # 19% 이상~23% 미만
        "#74B9E6",  # 23% 이상~28% 미만
        "#3182BD",  # 28% 이상~38% 미만
        "#08519C",  # 38% 이상
    ]

    # Plotly의 연속형 색상표를 다섯 단계 색상으로 끊어 줍니다.
    discrete_colorscale = [
        [0.00, blue_colors[0]],
        [0.20, blue_colors[0]],

        [0.20, blue_colors[1]],
        [0.40, blue_colors[1]],

        [0.40, blue_colors[2]],
        [0.60, blue_colors[2]],

        [0.60, blue_colors[3]],
        [0.80, blue_colors[3]],

        [0.80, blue_colors[4]],
        [1.00, blue_colors[4]],
    ]

    # 마우스를 지도에 올렸을 때 보여 줄 정보입니다.
    custom_data = np.column_stack(
        (
            map_data["시군구"].fillna(""),
            map_data["시도"].fillna(""),
            map_data["고령화율"].fillna(0),
            map_data["총인구"].fillna(0),
            map_data["고령인구"].fillna(0),
        )
    )

    figure = go.Figure(
        go.Choropleth(
            geojson=gwangju_geojson,

            # GeoJSON의 코드 속성과 데이터의 시군구 코드를 연결합니다.
            featureidkey="properties.코드",
            locations=map_data["시군구코드"],

            # 각 구의 고령화율 단계를 색상 값으로 사용합니다.
            z=map_data["단계"],
            zmin=-0.5,
            zmax=4.5,

            colorscale=discrete_colorscale,

            # 다섯 구를 명확히 구분할 수 있도록 흰색 경계선을 표시합니다.
            marker_line_color="#FFFFFF",
            marker_line_width=2,

            customdata=custom_data,

            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "지역: %{customdata[1]}<br>"
                "고령화율: %{customdata[2]:.1f}%<br>"
                "총인구: %{customdata[3]:,.0f}명<br>"
                "65세 이상: %{customdata[4]:,.0f}명"
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
                "len": 0.75,
                "thickness": 24,
                "x": 1.01,
                "y": 0.5,
                "outlinewidth": 0,
            },
        )
    )

    figure.update_geos(
        # 광주광역시 5개 구의 경계에 맞게 자동 확대합니다.
        fitbounds="locations",

        # 배경 지도 타일과 위도·경도 축을 표시하지 않습니다.
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
        margin={
            "r": 190,
            "t": 20,
            "l": 20,
            "b": 20,
        },
        height=650,
        paper_bgcolor="white",
        plot_bgcolor="white",

        hoverlabel={
            "bgcolor": "white",
            "font_size": 14,
            "font_family": "Arial",
        },
    )

    return figure


# ---------------------------------------------------------
# 10. 구별 고령화율 막대그래프 만들기
# ---------------------------------------------------------
def make_bar_chart(ranking_data):
    """
    광주광역시 5개 구의 고령화율을 막대그래프로 비교합니다.
    """
    chart_data = ranking_data.sort_values(
        "고령화율",
        ascending=True,
    ).copy()

    figure = go.Figure(
        go.Bar(
            x=chart_data["고령화율"],
            y=chart_data["시군구"],
            orientation="h",

            marker={
                "color": chart_data["고령화율"],
                "colorscale": [
                    [0.0, "#B9DDF4"],
                    [0.5, "#4292C6"],
                    [1.0, "#08519C"],
                ],
                "line": {
                    "color": "white",
                    "width": 1,
                },
            },

            text=chart_data["고령화율"].apply(
                lambda value: f"{value:.1f}%"
            ),

            textposition="outside",

            hovertemplate=(
                "<b>%{y}</b><br>"
                "고령화율: %{x:.1f}%"
                "<extra></extra>"
            ),
        )
    )

    # 각 단계의 기준선을 표시합니다.
    for boundary in [19, 23, 28, 38]:
        figure.add_vline(
            x=boundary,
            line_width=1,
            line_dash="dot",
            line_color="#9E9E9E",
        )

    figure.update_layout(
        title={
            "text": "5개 구 고령화율 비교",
            "x": 0.02,
            "xanchor": "left",
        },
        xaxis_title="65세 이상 인구 비율(%)",
        yaxis_title="",
        height=420,
        margin={
            "l": 20,
            "r": 70,
            "t": 60,
            "b": 50,
        },
        showlegend=False,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    figure.update_xaxes(
        showgrid=True,
        gridcolor="#E5E7EB",
        zeroline=False,
    )

    figure.update_yaxes(
        showgrid=False,
    )

    return figure


# ---------------------------------------------------------
# 11. 스트림릿 화면에 결과 출력
# ---------------------------------------------------------
st.title("🗺️ 광주광역시 5개 구 고령화 지도")

st.caption(
    "광주광역시 동구·서구·남구·북구·광산구의 "
    "전체 인구 중 65세 이상 인구 비율을 비교합니다."
)

try:
    with st.spinner(
        "최신 인구 자료와 광주광역시 지도 경계를 불러오는 중입니다."
    ):
        population_data = load_population_data()

        gwangju_geojson = load_gwangju_geojson()

        latest_year, aging_data = calculate_gwangju_aging_rate(
            population_data
        )

        boundary_table = make_boundary_table(
            gwangju_geojson
        )

        # 지역명이 아니라 5자리 시군구 코드로 연결합니다.
        map_data = boundary_table.merge(
            aging_data,
            on="시군구코드",
            how="left",
        )

    # 인구 자료가 정상적으로 연결된 지역만 사용합니다.
    ranking_data = map_data.dropna(
        subset=["고령화율"]
    ).copy()

    if ranking_data.empty:
        raise ValueError(
            "광주광역시 지도 경계와 인구 자료가 연결되지 않았습니다."
        )

    # 순위 계산
    ranking_data = ranking_data.sort_values(
        "고령화율",
        ascending=False,
    ).reset_index(drop=True)

    ranking_data["순위"] = (
        ranking_data.index + 1
    )

    # 가장 높은 구와 낮은 구를 찾습니다.
    highest_district = ranking_data.iloc[0]
    lowest_district = ranking_data.iloc[-1]

    # 광주광역시 전체 고령화율도 계산합니다.
    gwangju_total_population = ranking_data["총인구"].sum()
    gwangju_elderly_population = ranking_data["고령인구"].sum()

    gwangju_aging_rate = (
        gwangju_elderly_population
        / gwangju_total_population
        * 100
    )

    st.subheader(
        f"{latest_year}년 광주광역시 구별 고령화율"
    )

    # 핵심 수치를 위쪽에 표시합니다.
    metric_column1, metric_column2, metric_column3 = st.columns(3)

    with metric_column1:
        st.metric(
            label="광주광역시 전체 고령화율",
            value=f"{gwangju_aging_rate:.1f}%",
        )

    with metric_column2:
        st.metric(
            label="고령화율이 가장 높은 구",
            value=highest_district["시군구"],
            delta=f'{highest_district["고령화율"]:.1f}%',
            delta_color="off",
        )

    with metric_column3:
        st.metric(
            label="고령화율이 가장 낮은 구",
            value=lowest_district["시군구"],
            delta=f'{lowest_district["고령화율"]:.1f}%',
            delta_color="off",
        )

    # 광주광역시 단계구분도
    map_figure = make_gwangju_map(
        map_data,
        gwangju_geojson,
    )

    st.plotly_chart(
        map_figure,
        use_container_width=True,
        config={
            "displayModeBar": False,
            "scrollZoom": False,
        },
    )

    st.divider()

    # 표와 막대그래프를 나란히 보여 줍니다.
    left_column, right_column = st.columns(
        [1, 1.25]
    )

    # 표에 표시할 값을 정리합니다.
    display_table = ranking_data.copy()

    display_table["고령화율(%)"] = (
        display_table["고령화율"].round(1)
    )

    display_table["총인구(명)"] = (
        display_table["총인구"]
        .round()
        .astype(int)
    )

    display_table["65세 이상(명)"] = (
        display_table["고령인구"]
        .round()
        .astype(int)
    )

    with left_column:
        st.subheader("5개 구 고령화율 순위")

        st.dataframe(
            display_table[
                [
                    "순위",
                    "시군구",
                    "고령화율(%)",
                    "총인구(명)",
                    "65세 이상(명)",
                ]
            ],
            use_container_width=True,
            hide_index=True,

            column_config={
                "순위": st.column_config.NumberColumn(
                    "순위",
                    format="%d위",
                ),
                "시군구": st.column_config.TextColumn(
                    "구",
                ),
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
        bar_figure = make_bar_chart(
            ranking_data
        )

        st.plotly_chart(
            bar_figure,
            use_container_width=True,
            config={
                "displayModeBar": False,
            },
        )

    st.caption(
        "고령화율 = 각 구의 65세 이상 인구 ÷ 각 구의 총인구 × 100"
    )

    # 경계와 인구 자료가 연결되지 않은 지역이 있을 때만 표시합니다.
    unmatched_data = map_data[
        map_data["고령화율"].isna()
    ]

    if not unmatched_data.empty:
        with st.expander(
            "인구 자료와 연결되지 않은 지역 확인"
        ):
            st.warning(
                f"{len(unmatched_data)}개 지역의 코드가 "
                "인구 자료와 연결되지 않았습니다."
            )

            st.dataframe(
                unmatched_data[
                    [
                        "시군구코드",
                        "시도",
                        "시군구",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

except requests.RequestException as error:
    st.error(
        "인터넷에서 인구 자료 또는 지도 경계를 내려받지 못했습니다."
    )
    st.exception(error)

except Exception as error:
    st.error(
        "자료를 처리하거나 지도를 만드는 과정에서 오류가 발생했습니다."
    )
    st.exception(error)
