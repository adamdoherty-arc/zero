import os
import pytest
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from zero.dependencies import DependencyManager, PackageManagerError

class TestDependencyManager:
    """Test cases for the DependencyManager class"""
    
    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory for testing"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            
            # Create basic project structure
            (project_path / "pyproject.toml").touch()
            (project_path / "package-lock.json").touch()
            (project_path / "poetry.lock").touch()
            
            yield project_path
            
    def test_get_outdated_packages_pip(self, temp_project_dir):
        """Test getting outdated pip packages"""
        dm = DependencyManager(temp_project_dir)
        
        # Mock pip list --outdated output
        mock_output = """Package    Version  Latest
-----------------------------  -------  ------
flask      2.0.1    2.3.2
requests   2.26.0   2.31.0"""
        
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                stdout=mock_output,
                stderr="",
                returncode=0
            )
            
            packages = dm.get_outdated_packages("pip")
            assert len(packages) == 2
            assert packages[0]["name"] == "flask"
            assert packages[0]["current_version"] == "2.0.1"
            assert packages[0]["latest_version"] == "2.3.2"
            assert packages[1]["name"] == "requests"
            assert packages[1]["current_version"] == "2.26.0"
            assert packages[1]["latest_version"] == "2.31.0"

    def test_get_outdated_packages_npm(self, temp_project_dir):
        """Test getting outdated npm packages"""
        dm = DependencyManager(temp_project_dir)
        
        # Mock npm outdated --json output
        mock_output = '{"outdated": {"lodash": {"current": "4.17.12", "wanted": "4.17.21", "latest": "4.17.21", "type": "dependencies"}}}'
        
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                stdout=mock_output,
                stderr="",
                returncode=0
            )
            
            packages = dm.get_outdated_packages("npm")
            assert len(packages) == 1
            assert packages[0]["name"] == "lodash"
            assert packages[0]["current_version"] == "4.17.12"
            assert packages[0]["wanted_version"] == "4.17.21"
            assert packages[0]["latest_version"] == "4.17.21"
            assert packages[0]["type"] == "dependencies"

    def test_get_outdated_packages_poetry(self, temp_project_dir):
        """Test getting outdated Poetry packages"""
        dm = DependencyManager(temp_project_dir)
        
        # Mock poetry show --outdated --format=json output
        mock_output = '{"outdated": [{"name": "toml", "current": "0.10.2", "latest": "0.11.7", "type": "dependencies"}]}'
        
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                stdout=mock_output,
                stderr="",
                returncode=0
            )
            
            packages = dm.get_outdated_packages("poetry")
            assert len(packages) == 1
            assert packages[0]["name"] == "toml"
            assert packages[0]["current_version"] == "0.10.2"
            assert packages[0]["latest_version"] == "0.11.7"
            assert packages[0]["type"] == "dependencies"

    def test_get_outdated_packages_unsupported_manager(self, temp_project_dir):
        """Test getting outdated packages with unsupported manager"""
        dm = DependencyManager(temp_project_dir)
        
        with pytest.raises(PackageManagerError) as exc_info:
            dm.get_outdated_packages("invalid-manager")
            
        assert "Unsupported package manager: invalid-manager" in str(exc_info.value)

    def test_update_package_pip(self, temp_project_dir):
        """Test updating a pip package"""
        dm = DependencyManager(temp_project_dir)
        
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            
            success = dm.update_package("flask", "pip")
            assert success is True
            mock_run.assert_called_once_with(["pip", "install", "--upgrade", "flask"], check=True)

    def test_update_package_npm(self, temp_project_dir):
        """Test updating an npm package"""
        dm = DependencyManager(temp_project_dir)
        
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            
            success = dm.update_package("lodash", "npm")
            assert success is True
            mock_run.assert_called_once_with(
                ["npm", "update", "lodash"],
                cwd=str(temp_project_dir),
                check=True
            )

    def test_update_package_poetry(self, temp_project_dir):
        """Test updating a Poetry package"""
        dm = DependencyManager(temp_project_dir)
        
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            
            success = dm.update_package("toml", "poetry")
            assert success is True
            mock_run.assert_called_once_with(
                ["poetry", "add", "--dev", "--update", "toml"],
                cwd=str(temp_project_dir),
                check=True
            )

    def test_update_all_packages_pip(self, temp_project_dir):
        """Test updating all pip packages"""
        dm = DependencyManager(temp_project_dir)
        
        # Mock pip list --outdated output
        mock_list_output = """Package    Version  Latest
-----------------------------  -------  ------
flask      2.0.1    2.3.2
requests   2.26.0   2.31.0"""
        
        with mock.patch("subprocess.run") as mock_run:
            # First call for listing outdated
            mock_run.side_effect = [
                mock.Mock(
                    stdout=mock_list_output,
                    stderr="",
                    returncode=0
                ),
                # Second call for actual upgrade
                mock.Mock(
                    stdout="",
                    stderr="",
                    returncode=0
                )
            ]
            
            result = dm.update_all_packages("pip")
            assert result["success"] is True
            assert len(result["updated"]) == 2
            assert "flask" in result["updated"]
            assert "requests" in result["updated"]

    def test_update_all_packages_npm(self, temp_project_dir):
        """Test updating all npm packages"""
        dm = DependencyManager(temp_project_dir)
        
        # Mock npm outdated --json output
        mock_output = '{"outdated": {"lodash": {"current": "4.17.12", "wanted": "4.17.21", "latest": "4.17.21", "type": "dependencies"}}}'
        
        with mock.patch("subprocess.run") as mock_run:
            # First call for listing outdated
            mock_run.side_effect = [
                mock.Mock(
                    stdout=mock_output,
                    stderr="",
                    returncode=0
                ),
                # Second call for actual update
                mock.Mock(
                    stdout="",
                    stderr="",
                    returncode=0
                )
            ]
            
            result = dm.update_all_packages("npm")
            assert result["success"] is True
            assert len(result["updated"]) == 1
            assert "lodash" in result["updated"]

    def test_update_all_packages_poetry(self, temp_project_dir):
        """Test updating all Poetry packages"""
        dm = DependencyManager(temp_project_dir)
        
        # Mock poetry show --outdated --format=json output
        mock_output = '{"outdated": [{"name": "toml", "current": "0.10.2", "latest": "0.11.7", "type": "dependencies"}]}'
        
        with mock.patch("subprocess.run") as mock_run:
            # First call for listing outdated
            mock_run.side_effect = [
                mock.Mock(
                    stdout=mock_output,
                    stderr="",
                    returncode=0
                ),
                # Second call for actual update
                mock.Mock(
                    stdout="",
                    stderr="",
                    returncode=0
                )
            ]
            
            result = dm.update_all_packages("poetry")
            assert result["success"] is True
            assert len(result["updated"]) == 1
            assert "toml" in result["updated"]