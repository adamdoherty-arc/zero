import asyncio
from datetime import datetime, timedelta
from typing import Optional

class AgenticLoopMonitor:
    def __init__(self):
        self.last_activity_time: Optional[datetime] = None
        self.inactivity_threshold = timedelta(minutes=30)
        self.heartbeat_interval = timedelta(minutes=5)

    async def monitor_loop(self):
        while True:
            if self.last_activity_time and datetime.now() - self.last_activity_time > self.inactivity_threshold:
                raise Exception("Agentic loop inactivity detected")
            await asyncio.sleep(self.heartbeat_interval.seconds)

    def record_activity(self):
        self.last_activity_time = datetime.now()

agentic_loop_monitor = AgenticLoopMonitor()
