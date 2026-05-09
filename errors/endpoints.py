from flask import Blueprint

errors_bp = Blueprint('errors', __name__)

@errors_bp.app_errorhandler(404)
def not_found(error):
    return {"error": "Not found"}, 404