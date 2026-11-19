"""Mouse-controlled compensation tracker for ProSelectTester."""

from datetime import datetime, timezone
from math import hypot, pi, sin
from time import monotonic
import tkinter as tk
from tkinter import messagebox, ttk
from uuid import uuid4

from ProSelect import atomic_json, results_dir


class CompensationTracker:
    ATTEMPTS = 4
    DURATION = 20
    TARGET_RADIUS = 0.065
    FRAME_MS = 16

    def __init__(self, parent, candidate):
        self.candidate = candidate
        self.session_id = uuid4().hex
        self.started_at = datetime.now(timezone.utc)
        self.attempts = []
        self.pending_frame = None

        self.window = tk.Toplevel(parent)
        self.window.title("Компенсационный трекер")
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.grab_set()

        panel = ttk.Frame(self.window, padding=16)
        panel.pack(fill="both", expand=True)
        ttk.Label(
            panel,
            text="Мышью удерживайте оранжевый шар в центре кольца. Шар будет сносить в стороны.\n"
                 f"Наводите шар обратно плавно. Всего {self.ATTEMPTS} попытки по {self.DURATION} секунд.",
            justify="left",
        ).pack(anchor="w")
        self.canvas = tk.Canvas(panel, width=680, height=360, bg="#111827", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=12)
        self.target = self.canvas.create_oval(0, 0, 0, 0, outline="#7dd3fc", width=2)
        self.ball = self.canvas.create_oval(0, 0, 0, 0, fill="#fb923c", outline="")
        self.canvas.bind("<Configure>", lambda _event: self.draw(0))

        self.status = ttk.Label(panel, text="Перед стартом наведите мышь на центр кольца.")
        self.status.pack(anchor="w")
        self.button = ttk.Button(panel, text="Начать попытку", command=self.prepare)
        self.button.pack(anchor="w", pady=(8, 0))

    def draw(self, elapsed):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = min(width, height)
        center_x, center_y = width / 2, height / 2
        radius = self.TARGET_RADIUS * scale
        self.canvas.coords(self.target, center_x - radius, center_y - radius,
                           center_x + radius, center_y + radius)
        pointer_x, pointer_y = self.canvas.winfo_pointerxy()
        x = pointer_x - self.canvas.winfo_rootx()
        y = pointer_y - self.canvas.winfo_rooty()
        # Each attempt starts with zero drift and follows a reproducible path.
        direction = (-1) ** len(self.attempts)
        x += scale * direction * (0.13 * sin(2 * pi * elapsed / 5) + 0.05 * sin(2 * pi * elapsed / 2.3))
        y += scale * (0.12 * sin(2 * pi * elapsed / 4.1) + 0.05 * sin(2 * pi * elapsed / 2.9))
        visible = 0 <= x < width and 0 <= y < height
        self.canvas.itemconfigure(self.ball, state="normal" if visible else "hidden")
        self.canvas.coords(self.ball, x - 7, y - 7, x + 7, y + 7)
        return hypot(x - center_x, y - center_y) / scale

    def prepare(self):
        self.button.state(["disabled"])
        self.countdown(3)

    def countdown(self, seconds):
        if seconds:
            self.draw(0)
            self.status.configure(text=f"Попытка {len(self.attempts) + 1}/{self.ATTEMPTS} · старт через {seconds} с")
            self.pending_frame = self.window.after(1000, self.countdown, seconds - 1)
            return
        self.canvas.configure(cursor="none")
        self.attempt_started = monotonic()
        self.previous_elapsed = 0
        self.previous_error = self.draw(0)
        self.error_integral = 0
        self.time_in_zone = 0
        self.tick()

    def tick(self):
        self.pending_frame = None
        elapsed = min(monotonic() - self.attempt_started, self.DURATION)
        dt = elapsed - self.previous_elapsed
        self.error_integral += self.previous_error * dt
        if self.previous_error <= self.TARGET_RADIUS:
            self.time_in_zone += dt
        if elapsed >= self.DURATION:
            self.finish_attempt()
            return
        self.previous_elapsed = elapsed
        self.previous_error = self.draw(elapsed)
        self.status.configure(text=f"Попытка {len(self.attempts) + 1}/{self.ATTEMPTS} · осталось {self.DURATION - elapsed:.1f} с")
        self.pending_frame = self.window.after(self.FRAME_MS, self.tick)

    def finish_attempt(self):
        self.canvas.configure(cursor="")
        self.canvas.itemconfigure(self.ball, state="hidden")
        attempt = {
            "attempt": len(self.attempts) + 1,
            "mean_error_pct": round(100 * self.error_integral / self.DURATION, 2),
            "time_in_zone_pct": round(100 * self.time_in_zone / self.DURATION, 2),
        }
        self.attempts.append(attempt)
        self.status.configure(text=f"Попытка {attempt['attempt']} · в зоне цели {attempt['time_in_zone_pct']:.1f}% времени")
        self.button.state(["!disabled"])
        if len(self.attempts) == self.ATTEMPTS:
            self.save()
        else:
            self.button.configure(text="Следующая попытка")

    def save(self):
        result = {
            "test": "compensation_tracker",
            "protocol_version": 1,
            "session_id": self.session_id,
            "candidate": self.candidate,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "input": "mouse",
            "attempt_duration_seconds": self.DURATION,
            "target_radius_pct": self.TARGET_RADIUS * 100,
            "attempts": self.attempts,
        }
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        try:
            output = results_dir("exports/tracker-results") / f"{stamp}_{self.session_id[:8]}.json"
            atomic_json(output, result)
        except OSError as error:
            self.button.configure(text="Повторить сохранение", command=self.save)
            messagebox.showerror("Ошибка сохранения", str(error), parent=self.window)
            return
        mean_error = sum(attempt["mean_error_pct"] for attempt in self.attempts) / len(self.attempts)
        mean_in_zone = sum(attempt["time_in_zone_pct"] for attempt in self.attempts) / len(self.attempts)
        self.status.configure(text=f"Сохранено · средняя ошибка {mean_error:.1f}% поля · в зоне {mean_in_zone:.1f}% времени")
        self.button.configure(text="Закрыть", command=self.close)

    def close(self):
        if self.pending_frame is not None:
            self.window.after_cancel(self.pending_frame)
        self.window.destroy()
