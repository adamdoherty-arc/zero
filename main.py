def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Initialize database
    db.init_app(app)
    
    # Initialize Prometheus metrics
    prometheus_client = PrometheusClient()
    
    # Initialize and start learning aggregator service
    learning_aggregator_service = LearningAggregatorService(db.session, prometheus_client)
    
    # Register blueprints
    from .api import api_bp
    app.register_blueprint(api_bp)
    
    return app