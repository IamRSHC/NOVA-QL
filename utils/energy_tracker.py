# energy_tracker.py
import codecarbon

class EnergyTracker:
    def __init__(self):
        self.energy_usage = codecarbon.get_energy_usage()

    def track_energy_usage(self):
        energy_usage = codecarbon.get_energy_usage()
        print(f"Energy usage: {energy_usage} Joules")
