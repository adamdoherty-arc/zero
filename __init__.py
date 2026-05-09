from flask import Flask
from .v1.endpoints import v1_bp
from .auth.endpoints import auth_bp
from .errors.endpoints import errors_bp

app = Flask(__name__)
app.register_blueprint(v1_bp, url_prefix='/v1')
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(errors_bp)

if __name__ == '__main__':
    app.run()