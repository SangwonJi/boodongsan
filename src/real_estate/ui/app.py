"""Streamlit web UI for Korean real estate data (부동산)."""

from __future__ import annotations

import asyncio
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Environment / secrets bootstrap
# ---------------------------------------------------------------------------

def _load_secrets() -> None:
    """Push Streamlit Cloud secrets into os.environ for the existing helpers."""
    try:
        for key in (
            "DATA_GO_KR_API_KEY",
            "ONBID_API_KEY",
            "ODCLOUD_API_KEY",
            "ODCLOUD_SERVICE_KEY",
        ):
            if key in st.secrets:
                os.environ[key] = st.secrets[key]
    except Exception:
        pass

_load_secrets()

from real_estate.mcp_server._helpers import (  # noqa: E402
    _APT_RENT_URL,
    _APT_TRADE_URL,
    _APPLYHOME_STAT_BASE_URL,
    _APT_SUBSCRIPTION_INFO_PATH,
    _COMMERCIAL_TRADE_URL,
    _ODCLOUD_BASE_URL,
    _OFFI_RENT_URL,
    _OFFI_TRADE_URL,
    _ONBID_BID_RESULT_LIST_URL,
    _SINGLE_RENT_URL,
    _SINGLE_TRADE_URL,
    _VILLA_RENT_URL,
    _VILLA_TRADE_URL,
    _build_url_with_service_key,
    _check_odcloud_key,
    _check_onbid_api_key,
    _fetch_json,
    _get_data_go_kr_key_for_onbid,
    _get_odcloud_key,
    _run_rent_tool,
    _run_trade_tool,
)
from real_estate.mcp_server._region import search_region_code  # noqa: E402
from real_estate.mcp_server.parsers.onbid import _onbid_extract_items  # noqa: E402
from real_estate.mcp_server.parsers.rent import (  # noqa: E402
    _parse_apt_rent,
    _parse_officetel_rent,
    _parse_single_house_rent,
    _parse_villa_rent,
)
from real_estate.mcp_server.parsers.trade import (  # noqa: E402
    _parse_apt_trades,
    _parse_commercial_trade,
    _parse_officetel_trades,
    _parse_single_house_trades,
    _parse_villa_trades,
)

# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------

def _run_async(coro: Any) -> Any:
    """Run an async coroutine from Streamlit's synchronous context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _current_ym() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m")


def _recent_months(n: int = 24) -> list[str]:
    """Return last *n* year-month strings (YYYYMM), newest first."""
    now = datetime.now(tz=timezone.utc)
    months: list[str] = []
    y, m = now.year, now.month
    for _ in range(n):
        months.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return months


def _fmt_price(val: int | float) -> str:
    """Format a price in 만원 to a readable Korean string."""
    if val >= 10000:
        return f"{val / 10000:.1f}억"
    return f"{val:,.0f}만"


# ---------------------------------------------------------------------------
# Housing-type registry (maps UI label → URLs + parsers)
# ---------------------------------------------------------------------------

HOUSING_TYPES: dict[str, dict[str, Any]] = {
    "아파트": {
        "trade_url": _APT_TRADE_URL,
        "trade_parser": _parse_apt_trades,
        "rent_url": _APT_RENT_URL,
        "rent_parser": _parse_apt_rent,
    },
    "오피스텔": {
        "trade_url": _OFFI_TRADE_URL,
        "trade_parser": _parse_officetel_trades,
        "rent_url": _OFFI_RENT_URL,
        "rent_parser": _parse_officetel_rent,
    },
    "연립다세대 (빌라)": {
        "trade_url": _VILLA_TRADE_URL,
        "trade_parser": _parse_villa_trades,
        "rent_url": _VILLA_RENT_URL,
        "rent_parser": _parse_villa_rent,
    },
    "단독/다가구": {
        "trade_url": _SINGLE_TRADE_URL,
        "trade_parser": _parse_single_house_trades,
        "rent_url": _SINGLE_RENT_URL,
        "rent_parser": _parse_single_house_rent,
    },
    "상업/업무용": {
        "trade_url": _COMMERCIAL_TRADE_URL,
        "trade_parser": _parse_commercial_trade,
        "rent_url": None,
        "rent_parser": None,
    },
}

# ---------------------------------------------------------------------------
# Subscription async helpers (standalone — avoids importing MCP-decorated modules)
# ---------------------------------------------------------------------------

async def _fetch_subscription_info(
    page: int = 1, per_page: int = 100,
) -> dict[str, Any]:
    err = _check_odcloud_key()
    if err:
        return err

    mode, key = _get_odcloud_key()
    headers: dict[str, str] | None = None
    params: dict[str, Any] = {
        "page": page, "perPage": per_page, "returnType": "JSON",
    }
    if mode == "authorization":
        headers = {"Authorization": key}
    elif mode == "serviceKey":
        params["serviceKey"] = key

    url = (
        f"{_ODCLOUD_BASE_URL}{_APT_SUBSCRIPTION_INFO_PATH}"
        f"?{urllib.parse.urlencode(params)}"
    )
    payload, fetch_err = await _fetch_json(url, headers=headers)
    if fetch_err:
        return fetch_err
    if not isinstance(payload, dict):
        return {"error": "parse_error", "message": "Unexpected response type"}
    return {
        "total_count": int(payload.get("totalCount") or 0),
        "items": payload.get("data") or [],
        "page": int(payload.get("page") or page),
        "per_page": int(payload.get("perPage") or per_page),
    }


async def _fetch_subscription_results(
    stat_kind: str,
    stat_year_month: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict[str, Any]:
    endpoint_map = {
        "cmpetrt_area": "getAPTCmpetrtAreaStat",
        "reqst_area": "getAPTReqstAreaStat",
        "przwner_area": "getAPTPrzwnerAreaStat",
        "aps_przwner": "getAPTApsPrzwnerStat",
    }
    endpoint = endpoint_map.get(stat_kind)
    if not endpoint:
        return {
            "error": "validation_error",
            "message": f"Invalid stat_kind: {stat_kind}",
        }
    err = _check_odcloud_key()
    if err:
        return err

    mode, key = _get_odcloud_key()
    headers: dict[str, str] | None = None
    params: dict[str, Any] = {
        "page": page, "perPage": per_page, "returnType": "JSON",
    }
    if mode == "authorization":
        headers = {"Authorization": key}
    elif mode == "serviceKey":
        params["serviceKey"] = key
    if stat_year_month:
        params["cond[STAT_DE::EQ]"] = stat_year_month

    url = (
        f"{_APPLYHOME_STAT_BASE_URL}/{endpoint}"
        f"?{urllib.parse.urlencode(params)}"
    )
    payload, fetch_err = await _fetch_json(url, headers=headers)
    if fetch_err:
        return fetch_err
    if not isinstance(payload, dict):
        return {"error": "parse_error", "message": "Unexpected response type"}
    return {
        "stat_kind": stat_kind,
        "total_count": int(payload.get("totalCount") or 0),
        "items": payload.get("data") or [],
    }


# ---------------------------------------------------------------------------
# Onbid async helper
# ---------------------------------------------------------------------------

async def _fetch_onbid_items(
    page_no: int = 1,
    num_of_rows: int = 20,
    lctn_sdnm: str | None = None,
    lctn_sggnm: str | None = None,
    opbd_dt_start: str | None = None,
    opbd_dt_end: str | None = None,
    onbid_cltr_nm: str | None = None,
) -> dict[str, Any]:
    err = _check_onbid_api_key()
    if err:
        return err

    service_key = _get_data_go_kr_key_for_onbid()
    params: dict[str, Any] = {
        "pageNo": page_no,
        "numOfRows": num_of_rows,
        "resultType": "json",
    }
    if lctn_sdnm:
        params["lctnSdnm"] = lctn_sdnm
    if lctn_sggnm:
        params["lctnSggnm"] = lctn_sggnm
    if opbd_dt_start:
        params["opbdDtStart"] = opbd_dt_start
    if opbd_dt_end:
        params["opbdDtEnd"] = opbd_dt_end
    if onbid_cltr_nm:
        params["onbidCltrNm"] = onbid_cltr_nm

    url = _build_url_with_service_key(
        _ONBID_BID_RESULT_LIST_URL, service_key, params,
    )
    payload, fetch_err = await _fetch_json(url)
    if fetch_err:
        return fetch_err
    if not isinstance(payload, dict):
        return {"error": "parse_error", "message": "Unexpected response type"}

    result_code, body, items = _onbid_extract_items(payload)
    if result_code and result_code not in {"00", "000"}:
        return {
            "error": "api_error",
            "code": result_code,
            "message": "Onbid API error",
        }
    try:
        total_count = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total_count = 0
    return {"total_count": total_count, "items": items}


# ---------------------------------------------------------------------------
# Finance calculators (pure math — no MCP import needed)
# ---------------------------------------------------------------------------

def _calc_loan(
    principal_10k: int, annual_rate_pct: float, years: int,
) -> dict[str, float]:
    r = annual_rate_pct / 100 / 12
    n = years * 12
    if r == 0:
        monthly = principal_10k / n
    else:
        g = (1 + r) ** n
        monthly = principal_10k * r * g / (g - 1)
    total = monthly * n
    return {
        "monthly_payment_10k": round(monthly, 2),
        "total_payment_10k": round(total, 2),
        "total_interest_10k": round(total - principal_10k, 2),
    }


def _calc_compound(
    initial_10k: int,
    monthly_10k: float,
    annual_rate_pct: float,
    years: int,
) -> dict[str, float]:
    r = annual_rate_pct / 100 / 12
    n = years * 12
    if r == 0:
        final = initial_10k + monthly_10k * n
    else:
        g = (1 + r) ** n
        final = initial_10k * g + monthly_10k * (g - 1) / r
    contributed = initial_10k + monthly_10k * n
    return {
        "final_value_10k": round(final, 2),
        "total_contributed_10k": round(contributed, 2),
        "total_gain_10k": round(final - contributed, 2),
    }


def _calc_cashflow(
    income_10k: float,
    loan_10k: float,
    living_10k: float,
    other_10k: float,
) -> dict[str, Any]:
    auto = living_10k == 0
    living_used = income_10k * 0.4 if auto else living_10k
    cashflow = income_10k - loan_10k - living_used - other_10k
    return {
        "cashflow_10k": round(cashflow, 2),
        "living_cost_10k": round(living_used, 2),
        "auto_applied": auto,
    }


# ===========================================================================
# Column rename map (API field → Korean display name)
# ===========================================================================

_COL_MAP: dict[str, str] = {
    "apt_name": "단지명",
    "unit_name": "단지명",
    "building_type": "건물유형",
    "building_use": "건물용도",
    "dong": "동",
    "area_sqm": "면적(㎡)",
    "floor": "층",
    "price_10k": "가격(만원)",
    "trade_date": "거래일",
    "build_year": "건축년도",
    "deal_type": "거래유형",
    "house_type": "주택유형",
    "land_use": "용도지역",
    "building_ar": "건물면적",
    "share_dealing": "지분거래",
    "deposit_10k": "보증금(만원)",
    "monthly_rent_10k": "월세(만원)",
    "contract_type": "계약유형",
}


def _to_display_df(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert API items to a display-friendly DataFrame with Korean columns."""
    df = pd.DataFrame(items)
    df = df.rename(columns={k: v for k, v in _COL_MAP.items() if k in df.columns})
    return df


# ===========================================================================
# Page configuration
# ===========================================================================

st.set_page_config(
    page_title="부동산 - 실거래가·청약·공매",
    page_icon="\U0001f3e0",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("\U0001f3e0 부동산")
st.caption("한국 부동산 실거래가 · 청약 · 공매 · 금융 계산기")

if not os.getenv("DATA_GO_KR_API_KEY"):
    st.error(
        "API 키가 설정되지 않았습니다. "
        "`.env` 파일 또는 Streamlit Secrets에 `DATA_GO_KR_API_KEY`를 설정하세요."
    )
    st.stop()

tab_trade, tab_sub, tab_onbid, tab_finance = st.tabs(
    [
        "\U0001f4ca 실거래가 조회",
        "\U0001f3d7\ufe0f 청약 정보",
        "\u2696\ufe0f 온비드 공매",
        "\U0001f9ee 금융 계산기",
    ]
)

# ===========================================================================
# Tab 1 — 실거래가 조회
# ===========================================================================

with tab_trade:
    col_input, col_result = st.columns([1, 2])

    with col_input:
        st.subheader("조회 조건")

        region_query = st.text_input(
            "지역명", placeholder="예: 마포구, 서울 강남구", key="region_q",
        )

        selected_code: str | None = None
        selected_name: str | None = None

        if region_query:
            region_result = search_region_code(region_query)
            if "error" in region_result:
                st.warning(f"지역을 찾을 수 없습니다: {region_query}")
            else:
                matches = region_result.get("matches", [])
                gu_matches = [
                    m for m in matches if m["code"][5:] == "00000"
                ]
                display_matches = gu_matches if gu_matches else matches

                if len(display_matches) > 1:
                    options = {
                        f"{m['name']} ({m['code'][:5]})": m
                        for m in display_matches
                    }
                    choice = st.selectbox("지역 선택", list(options.keys()))
                    if choice:
                        selected_code = options[choice]["code"][:5]
                        selected_name = options[choice]["name"]
                else:
                    selected_code = region_result["region_code"]
                    selected_name = region_result["full_name"]
                    st.success(f"{selected_name} ({selected_code})")

        months = _recent_months(24)
        month_labels = [f"{m[:4]}년 {int(m[4:])}월" for m in months]
        selected_month_idx = st.selectbox(
            "조회 년월",
            range(len(months)),
            format_func=lambda i: month_labels[i],
            key="ym",
        )
        selected_ym = months[selected_month_idx]

        housing_type = st.selectbox(
            "주택 유형", list(HOUSING_TYPES.keys()), key="htype",
        )
        hcfg = HOUSING_TYPES[housing_type]

        trade_options = ["매매"]
        if hcfg["rent_url"] is not None:
            trade_options.append("전월세")
        trade_type = st.radio(
            "거래 유형", trade_options, horizontal=True, key="ttype",
        )

        num_rows = st.slider("최대 건수", 10, 1000, 100, step=10, key="nrows")
        search_clicked = st.button(
            "\U0001f50d 조회", type="primary", use_container_width=True,
        )

    with col_result:
        if search_clicked:
            if not selected_code:
                st.warning("지역을 먼저 입력하세요.")
            else:
                with st.spinner("데이터를 불러오는 중..."):
                    if trade_type == "매매":
                        result = _run_async(
                            _run_trade_tool(
                                hcfg["trade_url"],
                                hcfg["trade_parser"],
                                selected_code,
                                selected_ym,
                                num_rows,
                            )
                        )
                    else:
                        result = _run_async(
                            _run_rent_tool(
                                hcfg["rent_url"],
                                hcfg["rent_parser"],
                                selected_code,
                                selected_ym,
                                num_rows,
                            )
                        )

                if "error" in result:
                    st.error(
                        f"오류: {result.get('message', result.get('error'))}"
                    )
                else:
                    header = (
                        f"{selected_name} · "
                        f"{selected_ym[:4]}년 {int(selected_ym[4:])}월 · "
                        f"{housing_type} {trade_type}"
                    )
                    st.subheader(header)

                    summary = result.get("summary", {})
                    total = result.get("total_count", 0)
                    items = result.get("items", [])

                    if trade_type == "매매":
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("전체 건수", f"{total:,}건")
                        m2.metric(
                            "중위가",
                            _fmt_price(summary.get("median_price_10k", 0)),
                        )
                        m3.metric(
                            "최저가",
                            _fmt_price(summary.get("min_price_10k", 0)),
                        )
                        m4.metric(
                            "최고가",
                            _fmt_price(summary.get("max_price_10k", 0)),
                        )
                    else:
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("전체 건수", f"{total:,}건")
                        m2.metric(
                            "보증금 중위값",
                            _fmt_price(
                                summary.get("median_deposit_10k", 0),
                            ),
                        )
                        m3.metric(
                            "보증금 최저",
                            _fmt_price(
                                summary.get("min_deposit_10k", 0),
                            ),
                        )
                        m4.metric(
                            "평균 월세",
                            _fmt_price(
                                summary.get("monthly_rent_avg_10k", 0),
                            ),
                        )

                    if items:
                        st.dataframe(
                            _to_display_df(items),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info("해당 조건에 맞는 거래 데이터가 없습니다.")

# ===========================================================================
# Tab 2 — 청약 정보
# ===========================================================================

with tab_sub:
    sub_tab1, sub_tab2 = st.tabs(["\U0001f4cb 분양 공고", "\U0001f4c8 청약 통계"])

    with sub_tab1:
        sub_page = st.number_input(
            "페이지", min_value=1, value=1, key="sub_page",
        )
        if st.button("공고 조회", key="sub_fetch"):
            with st.spinner("청약 공고를 불러오는 중..."):
                sub_result = _run_async(
                    _fetch_subscription_info(page=sub_page),
                )
            if "error" in sub_result:
                st.error(
                    f"오류: {sub_result.get('message', sub_result.get('error'))}"
                )
            else:
                st.metric(
                    "전체 공고 수",
                    f"{sub_result.get('total_count', 0):,}건",
                )
                sub_items = sub_result.get("items", [])
                if sub_items:
                    st.dataframe(
                        pd.DataFrame(sub_items),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("공고 데이터가 없습니다.")

    with sub_tab2:
        stat_options = {
            "지역별 경쟁률": "cmpetrt_area",
            "지역별 신청자": "reqst_area",
            "지역별 당첨자": "przwner_area",
            "가점제 당첨자": "aps_przwner",
        }
        stat_choice = st.selectbox(
            "통계 유형", list(stat_options.keys()), key="stat_kind",
        )
        stat_ym = st.text_input(
            "조회 년월 (YYYYMM, 선택사항)",
            placeholder="예: 202601",
            key="stat_ym",
        )
        if st.button("통계 조회", key="stat_fetch"):
            with st.spinner("통계를 불러오는 중..."):
                stat_result = _run_async(
                    _fetch_subscription_results(
                        stat_kind=stat_options[stat_choice],
                        stat_year_month=stat_ym or None,
                    ),
                )
            if "error" in stat_result:
                st.error(
                    f"오류: {stat_result.get('message', stat_result.get('error'))}"
                )
            else:
                st.metric(
                    "전체 건수",
                    f"{stat_result.get('total_count', 0):,}건",
                )
                stat_items = stat_result.get("items", [])
                if stat_items:
                    st.dataframe(
                        pd.DataFrame(stat_items),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("통계 데이터가 없습니다.")

# ===========================================================================
# Tab 3 — 온비드 공매
# ===========================================================================

with tab_onbid:
    st.subheader("공매 물건 검색")
    oc1, oc2 = st.columns(2)
    with oc1:
        onbid_sido = st.text_input(
            "시/도", placeholder="예: 서울특별시", key="ob_sido",
        )
        onbid_sgg = st.text_input(
            "시/군/구", placeholder="예: 강남구", key="ob_sgg",
        )
        onbid_keyword = st.text_input(
            "물건명 검색어", placeholder="예: 아파트", key="ob_kw",
        )
    with oc2:
        onbid_dt_start = st.text_input(
            "개찰일 시작 (yyyyMMdd)",
            placeholder="예: 20260101",
            key="ob_ds",
        )
        onbid_dt_end = st.text_input(
            "개찰일 종료 (yyyyMMdd)",
            placeholder="예: 20261231",
            key="ob_de",
        )
        onbid_rows = st.slider("최대 건수", 5, 100, 20, key="ob_rows")

    if st.button(
        "\U0001f50d 공매 조회", type="primary", key="ob_fetch",
    ):
        with st.spinner("온비드 데이터를 불러오는 중..."):
            ob_result = _run_async(
                _fetch_onbid_items(
                    num_of_rows=onbid_rows,
                    lctn_sdnm=onbid_sido or None,
                    lctn_sggnm=onbid_sgg or None,
                    opbd_dt_start=onbid_dt_start or None,
                    opbd_dt_end=onbid_dt_end or None,
                    onbid_cltr_nm=onbid_keyword or None,
                ),
            )
        if "error" in ob_result:
            st.error(
                f"오류: {ob_result.get('message', ob_result.get('error'))}"
            )
        else:
            st.metric(
                "전체 건수",
                f"{ob_result.get('total_count', 0):,}건",
            )
            ob_items = ob_result.get("items", [])
            if ob_items:
                st.dataframe(
                    pd.DataFrame(ob_items),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("조건에 맞는 공매 물건이 없습니다.")

# ===========================================================================
# Tab 4 — 금융 계산기
# ===========================================================================

with tab_finance:
    fc1, fc2, fc3 = st.tabs(
        ["\U0001f4b0 대출 상환", "\U0001f4c8 복리 성장", "\U0001f4b5 월 현금흐름"],
    )

    # ----- 대출 상환 -----
    with fc1:
        st.subheader("원리금균등상환 계산기")
        lc1, lc2, lc3 = st.columns(3)
        loan_principal = lc1.number_input(
            "대출 원금 (만원)", min_value=1, value=30000, step=1000, key="lp",
        )
        loan_rate = lc2.number_input(
            "연이율 (%)", min_value=0.0, value=3.5, step=0.1, key="lr",
        )
        loan_years = lc3.number_input(
            "대출 기간 (년)", min_value=1, value=30, step=1, key="ly",
        )
        if st.button("계산", key="loan_calc"):
            lr = _calc_loan(loan_principal, loan_rate, loan_years)
            r1, r2, r3 = st.columns(3)
            r1.metric("월 상환액", _fmt_price(lr["monthly_payment_10k"]))
            r2.metric("총 상환액", _fmt_price(lr["total_payment_10k"]))
            r3.metric("총 이자", _fmt_price(lr["total_interest_10k"]))

    # ----- 복리 성장 -----
    with fc2:
        st.subheader("복리 자산 성장 계산기")
        gc1, gc2, gc3, gc4 = st.columns(4)
        g_init = gc1.number_input(
            "초기 자본 (만원)", min_value=0, value=5000, step=500, key="gi",
        )
        g_monthly = gc2.number_input(
            "월 적립 (만원)", min_value=0.0, value=100.0, step=10.0, key="gm",
        )
        g_rate = gc3.number_input(
            "연수익률 (%)", min_value=0.0, value=7.0, step=0.5, key="gr",
        )
        g_years = gc4.number_input(
            "기간 (년)", min_value=1, value=20, step=1, key="gy",
        )
        if st.button("계산", key="growth_calc"):
            gr = _calc_compound(g_init, g_monthly, g_rate, g_years)
            r1, r2, r3 = st.columns(3)
            r1.metric("최종 자산", _fmt_price(gr["final_value_10k"]))
            r2.metric("총 납입액", _fmt_price(gr["total_contributed_10k"]))
            r3.metric("총 수익", _fmt_price(gr["total_gain_10k"]))

    # ----- 월 현금흐름 -----
    with fc3:
        st.subheader("월 현금흐름 계산기")
        cc1, cc2 = st.columns(2)
        with cc1:
            c_income = st.number_input(
                "월 소득 (만원)",
                min_value=1.0, value=400.0, step=10.0, key="ci",
            )
            c_loan = st.number_input(
                "월 대출 상환 (만원)",
                min_value=0.0, value=80.0, step=10.0, key="cl",
            )
        with cc2:
            c_living = st.number_input(
                "월 생활비 (만원, 0=소득의 40%)",
                min_value=0.0, value=0.0, step=10.0, key="cv",
            )
            c_other = st.number_input(
                "기타 지출 (만원)",
                min_value=0.0, value=0.0, step=10.0, key="co",
            )
        if st.button("계산", key="cf_calc"):
            cf = _calc_cashflow(c_income, c_loan, c_living, c_other)
            auto_note = " (소득의 40% 자동)" if cf["auto_applied"] else ""
            r1, r2 = st.columns(2)
            r1.metric("월 여유 자금", _fmt_price(cf["cashflow_10k"]))
            r2.metric(f"생활비{auto_note}", _fmt_price(cf["living_cost_10k"]))

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    "데이터 출처: "
    "[공공데이터포털](https://data.go.kr) · "
    "[온비드](https://onbid.co.kr) · "
    "[청약홈](https://applyhome.co.kr)"
)
