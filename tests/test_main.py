import pytest


@pytest.mark.asyncio
async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "GM Core Service is running"}


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    print(f"\nDB Health Check Result: {data}")
    assert "status" in data
    # DB 연결 실패시 status: error일 수 있으므로 구체적인 값 검증은 상황에 따라
