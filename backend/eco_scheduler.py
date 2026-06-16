from codecarbon import EmissionsTracker

class EcoScheduler:
    def __init__(self, query_buffer_size=5):
        self.query_buffer_size = query_buffer_size
        self.tracker = None
        self.last_emissions = 0.0

    def start_tracking(self):
        self.tracker = EmissionsTracker(log_level="error", save_to_file=False)
        self.tracker.start()

    def stop_tracking(self):
        if self.tracker:
            self.last_emissions = self.tracker.stop()
            return self.last_emissions
        return 0.0