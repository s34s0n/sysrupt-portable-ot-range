"""PID controller with anti-windup."""


class PIDController:
    """Standard discrete PID controller with integral anti-windup."""

    def __init__(self, config: dict):
        self.kp = config.get("kp", 1.0)
        self.ki = config.get("ki", 0.1)
        self.kd = config.get("kd", 0.05)
        self.setpoint = config.get("setpoint", 0.0)
        self.output_min = config.get("output_min", 0.0)
        self.output_max = config.get("output_max", 100.0)
        self.integral_limit = config.get("integral_limit", 100.0)

        self._integral = 0.0
        self._last_error = 0.0
        self._first_call = True

    def update(self, dt: float, measurement: float, setpoint: float = None) -> dict:
        """Compute PID output. dt in seconds."""
        if setpoint is not None:
            self.setpoint = setpoint

        error = self.setpoint - measurement

        # Proportional
        p_term = self.kp * error

        # Integral with anti-windup
        self._integral += error * dt
        self._integral = max(-self.integral_limit, min(self.integral_limit, self._integral))
        i_term = self.ki * self._integral

        # Derivative
        if self._first_call:
            d_term = 0.0
            self._first_call = False
        else:
            d_term = self.kd * (error - self._last_error) / dt if dt > 0 else 0.0

        self._last_error = error

        # Output
        output = p_term + i_term + d_term
        output = max(self.output_min, min(self.output_max, output))

        return {
            "output": round(output, 4),
            "error": round(error, 4),
            "p_term": round(p_term, 4),
            "i_term": round(i_term, 4),
            "d_term": round(d_term, 4),
        }

    def reset(self):
        """Reset controller state."""
        self._integral = 0.0
        self._last_error = 0.0
        self._first_call = True
