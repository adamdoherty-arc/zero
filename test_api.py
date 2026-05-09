import pytest
from zero import app

@pytest.fixture
def client():
    return app.test_client()

def test_v1_index(client):
    response = client.get('/v1/')
    assert response.status_code == 200
    assert response.data == b'V1 Hello'

def test_auth_login(client):
    response = client.get('/auth/login')
    assert response.status_code == 200
    assert response.data == b'Login'

def test_404(client):
    response = client.get('/invalid')
    assert response.status_code == 404
    assert response.json == {'error': 'Not found'}