import click
from zero.dependencies import DependencyManager

@click.group()
def cli():
    """Zero CLI commands"""
    pass

@cli.command()
def outdated():
    """List outdated packages"""
    manager = DependencyManager()
    outdated = manager.get_outdated_packages()
    
    if not outdated:
        click.echo("All dependencies are up to date!")
        return
        
    click.echo("Outdated packages:")
    for package in outdated:
        click.echo(f"{package['name']}: {package['installed']} -> {package['expected']}")

@cli.command()
@click.argument('package_name')
@click.argument('version')
def update(package_name: str, version: str):
    """Update a package to a new version"""
    manager = DependencyManager()
    success = manager.update_package(package_name, version)
    
    if success:
        click.echo(f"Successfully updated {package_name} to {version}")
    else:
        click.echo(f"Failed to update {package_name}")