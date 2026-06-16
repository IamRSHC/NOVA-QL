import numpy as np
import re


class DifferentialPrivacy:
    """
    Research-level Differential Privacy Engine
    - Aggregate-only DP
    - Sensitivity-based scaling
    - Per-user privacy budgets
    - Modes: private | raw | audit
    """

    def __init__(self, epsilon=1.0):
        self.epsilon = float(epsilon)
        self.mode = "private"  # private | raw | audit

        # Per-user budgets: {username: remaining_budget}
        self.user_budgets = {}

        # Store last noise for audit mode
        self.last_noise = []

    # -------------------------------------------------
    # USER REGISTRATION / BUDGET MANAGEMENT
    # -------------------------------------------------
    def register_user(self, username, total_budget=10.0):
        self.user_budgets[username] = float(total_budget)

    def get_remaining_budget(self, username):
        return self.user_budgets.get(username, 0.0)

    def deduct_budget(self, username):
        if username not in self.user_budgets:
            raise Exception("User not registered in DP system.")

        if self.user_budgets[username] < self.epsilon:
            raise Exception("Privacy budget exhausted.")

        self.user_budgets[username] -= self.epsilon

    # -------------------------------------------------
    # EPSILON CONTROL
    # -------------------------------------------------
    def set_epsilon(self, new_epsilon):
        new_epsilon = float(new_epsilon)
        if new_epsilon <= 0:
            raise ValueError("Epsilon must be greater than 0.")
        self.epsilon = new_epsilon

    # -------------------------------------------------
    # MODE CONTROL
    # -------------------------------------------------
    def set_mode(self, mode):
        if mode not in ["private", "raw", "audit"]:
            raise ValueError("Mode must be 'private', 'raw', or 'audit'")
        self.mode = mode

    # -------------------------------------------------
    # QUERY TYPE DETECTION
    # -------------------------------------------------
    def is_aggregate_query(self, query):
        query = query.lower()
        return any(func in query for func in ["count(", "sum(", "avg("])

    def detect_aggregate_type(self, query):
        query = query.lower()

        if "count(" in query:
            return "count"

        if "sum(" in query:
            return "sum"

        if "avg(" in query:
            return "avg"

        return None

    # -------------------------------------------------
    # SENSITIVITY ESTIMATION
    # -------------------------------------------------
    def get_sensitivity(self, aggregate_type):
        """
        Research-level:
        COUNT -> sensitivity = 1
        SUM   -> assume bounded column in range [0, 100]
                 (You can later make this dynamic)
        AVG   -> bounded / dataset_size approximation
                 Here we use 1 for simplicity
        """

        if aggregate_type == "count":
            return 1

        if aggregate_type == "sum":
            return 100  # assumed max contribution

        if aggregate_type == "avg":
            return 1

        return 1

    # -------------------------------------------------
    # LAPLACE MECHANISM (Sensitivity-aware)
    # -------------------------------------------------
    def apply_laplace(self, value, sensitivity):
        scale = sensitivity / self.epsilon
        noise = np.random.laplace(0, scale)
        self.last_noise.append(noise)
        return value + noise

    # -------------------------------------------------
    # MAIN PROCESSOR
    # -------------------------------------------------
    def process_result(self, username, query, result):

        if result is None:
            return None

        # RAW MODE (no DP, no budget deduction)
        if self.mode == "raw":
            return {
                "raw": result,
                "private": result,
                "noise": None
            }

        # Only apply DP if aggregate query
        if not self.is_aggregate_query(query):
            # Non-aggregate queries are returned as raw
            return {
                "raw": result if self.mode == "audit" else None,
                "private": result,
                "noise": None
            }

        # Budget enforcement
        self.deduct_budget(username)
        self.last_noise = []

        aggregate_type = self.detect_aggregate_type(query)
        sensitivity = self.get_sensitivity(aggregate_type)

        privatized = []

        for row in result:
            new_row = []
            for item in row:
                if isinstance(item, (int, float)):
                    new_row.append(self.apply_laplace(item, sensitivity))
                else:
                    new_row.append(item)
            privatized.append(tuple(new_row))

        # PRIVATE MODE
        if self.mode == "private":
            return {
                "raw": None,
                "private": privatized,
                "noise": None
            }

        # AUDIT MODE
        if self.mode == "audit":
            return {
                "raw": result,
                "private": privatized,
                "noise": self.last_noise
            }

    # -------------------------------------------------
    # METRICS
    # -------------------------------------------------
    def get_metrics(self, username):
        return {
            "epsilon": self.epsilon,
            "remaining_budget": self.get_remaining_budget(username),
            "mode": self.mode
        }