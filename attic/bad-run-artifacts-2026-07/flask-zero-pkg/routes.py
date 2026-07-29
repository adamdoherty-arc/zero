from flask import Blueprint, jsonify, request
from zero import db
from zero.models import Package

main = Blueprint('main', __name__)

@main.route('/outdated_packages', methods=['GET'])
def get_outdated_packages():
    packages = Package.query.all()
    return jsonify([{
        'name': package.name,
        'current_version': package.current_version,
        'latest_version': package.latest_version,
        'days_since_update': package.days_since_update
    } for package in packages])

@main.route('/update_package/<package_name>', methods=['POST'])
def update_package(package_name):
    package = Package.query.filter_by(name=package_name).first()
    if not package:
        return jsonify({'error': 'Package not found'}), 404
        
    package.current_version = package.latest_version
    db.session.commit()
    return jsonify({'message': f'{package_name} updated successfully'})