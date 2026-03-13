import os
import redis
import time
from duckclaw import DuckClaw

class SingletonWriterBridge:
    def __init__(self, db_path, redis_url="redis://localhost:6379"):
        self.db = DuckClaw(db_path)
        self.r = redis.from_url(redis_url)
        self.queue_key = "duckdb_write_queue"

    def run(self):
        print(f"SingletonWriterBridge started. Listening on {self.queue_key}...")
        while True:
            # BLPOP blocks until an item is available
            _, sql = self.r.blpop(self.queue_key)
            sql_str = sql.decode("utf-8")
            try:
                print(f"Executing: {sql_str}")
                self.db.execute(sql_str)
            except Exception as e:
                print(f"Error executing SQL: {e}")

if __name__ == "__main__":
    db_path = os.environ.get("DUCKCLAW_DB_PATH", "duckclaw.duckdb")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    bridge = SingletonWriterBridge(db_path, redis_url)
    bridge.run()
