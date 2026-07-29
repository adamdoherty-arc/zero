import pytest
from zero import create_app, db
from zero.models import Package

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            # Add test data
            test_packages = [
                Package(name='package1', current_version='1.0.0', latest_version='1.2.0', days_since_update=60),
                Package(name='package2', current_version='2.1.0', latest_version='2.1.3', days_since_update=10),
                Package(name='package3', current_version='3.0.0', latest_version='3.0.0', days_since_update=0)
            ]
            db.session.add_all(test_packages)
            db.session.commit()
        yield client
        with app.app_context():
            db.session.remove()
            db.drop_all()

def test_get_outdated_packages(client):
    response = client.get('/outdated_packages')
    data = response.get_json()
    
    assert response.status_code == 200
    assert len(data) == 3
    assert data[0]['name'] == 'package1'
    assert data[0]['current_version'] == '1.0.0'
    assert data[0]['latest_version'] == '1.2.0'
    assert data[0]['days_since_update'] == 60

def test_update_package(client):
    # Test updating a package
    response = client.post('/update_package/package1')
    assert response.status_code == 200
    
    # Verify the package was updated
    package = Package.query.filter_by(name='package1').first()
    assert package.current_version == '1.2.0'
    
    # Test updating a non-existent package
    response = client.post('/update_package/nonexistent')
    assert response.status_code == 404
    assert response.get_json()['error'] == 'Package not found'