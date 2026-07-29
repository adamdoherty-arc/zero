from zero import db

class Package(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    current_version = db.Column(db.String(50), nullable=False)
    latest_version = db.Column(db.String(50), nullable=False)
    days_since_update = db.Column(db.Integer, nullable=False)