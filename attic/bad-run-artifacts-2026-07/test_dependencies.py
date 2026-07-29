import os
import pytest
from zero.dependencies import PackageManager
from zero.core.exceptions import PackageManagerError

def test_get_outdated_packages():
    pm = PackageManager()
    packages = pm.get_outdated_packages()
    assert isinstance(packages, list)
    for package in packages:
        assert 'name' in package
        assert 'current_version' in package
        assert 'latest_version' in package
        assert 'location' in package

def test_update_package():
    pm = PackageManager()
    success = pm.update_package("requests")
    assert isinstance(success, bool)

def test_update_all_packages():
    pm = PackageManager()
    updates = pm.update_all_packages()
    assert isinstance(updates, dict)
    for package, success in updates.items():
        assert isinstance(package, str)
        assert isinstance(success, bool)

def test_error_handling():
    pm = PackageManager()
    with pytest.raises(PackageManagerError):
        # Test error handling by trying to update a non-existent package
        # This might not raise an error on all systems, but the method should handle it gracefully
        pm.update_package("non-existent-package-1234567890")