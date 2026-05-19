class LearningAggregatorService:
    def __init__(self, db_session, prometheus_client):
        self.db_session = db_session
        self.prometheus_client = prometheus_client
        self.scheduler = BackgroundScheduler()
        self.learning_writes_total = prometheus_client.Counter('learning_writes_total', 'Total learning writes')
        self.start()  # Previously missing - service wasn't being started

    def start(self):
        """Start the aggregation service"""
        self.scheduler.add_job(self.aggregate_and_write, 'interval', minutes=5)
        self.scheduler.start()
        logger.info("LearningAggregatorService started")

    def aggregate_and_write(self):
        """Aggregate learning data and write to database"""
        try:
            # Simulate data aggregation logic
            learning_data = self._aggregate_data()
            
            if learning_data:
                self.db_session.add(learning_data)
                self.db_session.commit()
                self.learning_writes_total.inc()
                logger.info(f"Written {len(learning_data)} learning records")
        except Exception as e:
            logger.error(f"Failed to aggregate and write learning data: {str(e)}")
            self.db_session.rollback()
            raise

    def _aggregate_data(self):
        """Simulated data aggregation logic"""
        # In a real implementation, this would aggregate data from various sources
        return SprintLearning(
            project_id="test_project",
            sprint_id="sprint_123",
            learning_type="aggregation",
            content={"test": "data"},
            created_at=datetime.utcnow()
        )