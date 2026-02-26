# boodongsan (부동산 MCP)

한국 부동산 실거래가를 Claude에게 질문할 수 있는 MCP 서버입니다.

> 이 프로젝트는 [tae0y/real-estate-mcp](https://github.com/tae0y/real-estate-mcp) 기반으로 만들어졌습니다 (MIT License).

## 제공 도구 (14개+)

- 아파트 매매/전월세 (`get_apartment_trades`, `get_apartment_rent`)
- 오피스텔 매매/전월세 (`get_officetel_trades`, `get_officetel_rent`)
- 빌라/연립다세대 매매/전월세 (`get_villa_trades`, `get_villa_rent`)
- 단독/다가구 매매/전월세 (`get_single_house_trades`, `get_single_house_rent`)
- 상업용 건물 매매 (`get_commercial_trade`)
- 청약 공고/결과 (`get_apt_subscription_info`, `get_apt_subscription_results`)
- 온비드 공매 입찰 결과 (`get_public_auction_items`)
- 온비드 물건 조회 (`get_onbid_thing_info_list`)
- 온비드 코드/주소 조회 (`get_onbid_*_code_info`, `get_onbid_addr*_info`)
- 지역코드 조회 (`get_region_code`)
- 금융 계산 (`calculate_loan_payment`, `calculate_compound_growth`, `calculate_monthly_cashflow`)

## 사전 준비

1. **uv** 설치
2. **공공데이터포털** (https://www.data.go.kr) API 키 발급

## 빠른 시작 (Claude Desktop - stdio)

```bash
# 1. 클론
git clone https://github.com/SangwonJi/boodongsan.git
cd boodongsan

# 2. .env 파일 생성
cp .env.example .env
# .env 파일에 DATA_GO_KR_API_KEY 값 입력

# 3. Claude Desktop 설정
```

Claude Desktop 설정 파일에 아래 추가:

```json
{
  "mcpServers": {
    "real-estate": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/boodongsan",
        "python", "src/real_estate/mcp_server/server.py"
      ],
      "env": {
        "DATA_GO_KR_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## 라이선스

MIT License - 원 저작자: [tae0y](https://github.com/tae0y/real-estate-mcp)
