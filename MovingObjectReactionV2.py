"""Moving-object timing test for ProSelectTester."""

from datetime import datetime, timezone
from math import cos, radians, sin
from random import Random
from statistics import mean
from time import monotonic
import tkinter as tk
from tkinter import messagebox, ttk
from uuid import uuid4

from ProSelect import atomic_json, results_dir


class MovingObjectReactionV2:
    TITLE = "Реакция на движущийся объект v2"
    TOLERANCE_MS = 100
    RESPONSE_GRACE_SECONDS = 0.75
    TRIALS = tuple(zip(
        (90, 120, 150, 180, 210, 240) * 2,
        (135, 180, 225, 180, 225, 270, 225, 270, 135, 270, 135, 180),
    ))
    CENTER = (280, 180)
    RADIUS = 128
    MARK_ANGLE = 0
    FRAME_MS = 16

    def __init__(self, parent, candidate):
        self.candidate = candidate
        self.started_at = datetime.now(timezone.utc)
        self.session_id = uuid4().hex
        self.trials = list(self.TRIALS)
        Random(1).shuffle(self.trials)
        self.attempts = []
        self.trial_started = None
        self.frame = None

        self.window = tk.Toplevel(parent)
        self.window.title(self.TITLE)
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        panel = ttk.Frame(self.window, padding=16)
        panel.pack()
        ttk.Label(panel, text="Стрелка вращается по часовой стрелке.\n"
                  "Нажмите пробел, когда её кончик совпадёт с красной меткой.",
                  justify="left").pack(anchor="w")
        self.canvas = tk.Canvas(panel, width=560, height=360, bg="#111827", highlightthickness=0)
        self.canvas.pack(pady=12)
        x, y = self.CENTER
        radius = self.RADIUS
        self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                outline="#94a3b8", width=2)
        self.arrow = self.canvas.create_line(x, y, x, y, fill="#f8fafc",
                                             width=3, arrow=tk.LAST, state="hidden")
        self.canvas.create_line(*self.point(self.MARK_ANGLE, radius - 7),
                                *self.point(self.MARK_ANGLE, radius + 9),
                                fill="#f87171", width=4)
        self.status = ttk.Label(panel, text=f"Всего попыток: {len(self.trials)}")
        self.status.pack(anchor="w")
        self.button = ttk.Button(panel, text="Начать попытку", command=self.start_trial)
        self.button.pack(anchor="w", pady=(8, 0))
        self.canvas.bind("<KeyPress-space>", self.respond)
        self.window.grab_set()

    def point(self, angle, radius):
        x, y = self.CENTER
        angle = radians(angle)
        return x + radius * sin(angle), y - radius * cos(angle)

    def draw_arrow(self, elapsed):
        angle = self.MARK_ANGLE - self.distance + self.speed * elapsed
        self.canvas.coords(self.arrow, *self.CENTER, *self.point(angle, self.RADIUS - 7))

    def start_trial(self):
        self.button.state(["disabled"])
        self.canvas.focus_set()
        self.speed, self.distance = self.trials[len(self.attempts)]
        self.target_time = self.distance / self.speed
        self.status.configure(text=f"Попытка {len(self.attempts) + 1} из {len(self.trials)}")
        self.canvas.itemconfigure(self.arrow, state="normal")
        self.trial_started = monotonic()
        self.animate()

    def animate(self):
        self.frame = None
        elapsed = monotonic() - self.trial_started
        if elapsed >= self.target_time + self.RESPONSE_GRACE_SECONDS:
            self.finish_trial(None)
            return
        self.draw_arrow(elapsed)
        self.frame = self.window.after(self.FRAME_MS, self.animate)

    def respond(self, _event):
        if self.trial_started is not None:
            elapsed = monotonic() - self.trial_started
            self.finish_trial(elapsed if elapsed < self.target_time + self.RESPONSE_GRACE_SECONDS else None)
        return "break"

    def finish_trial(self, elapsed):
        self.trial_started = None
        self.cancel_frame()
        deviation = None if elapsed is None else round((elapsed - self.target_time) * 1000, 1)
        if deviation is None:
            self.canvas.itemconfigure(self.arrow, state="hidden")
            outcome, feedback = "missed", "Пропуск"
        else:
            self.draw_arrow(elapsed)
            if abs(deviation) <= self.TOLERANCE_MS:
                outcome, feedback = "accurate", f"Точно ({deviation:+.1f} мс)"
            elif deviation < 0:
                outcome, feedback = "early", f"Раньше на {-deviation:.1f} мс"
            else:
                outcome, feedback = "late", f"Позже на {deviation:.1f} мс"
        self.attempts.append({
            "attempt": len(self.attempts) + 1,
            "speed_deg_per_second": self.speed,
            "distance_to_mark_deg": self.distance,
            "target_time_ms": round(self.target_time * 1000, 1),
            "response_time_ms": None if elapsed is None else round(elapsed * 1000, 1),
            "deviation_ms": deviation,
            "outcome": outcome,
        })
        self.button.state(["!disabled"])
        if len(self.attempts) == len(self.trials):
            self.save()
        else:
            self.status.configure(text=feedback)
            self.button.configure(text="Следующая попытка")

    def save(self):
        summary = {kind: sum(row["outcome"] == kind for row in self.attempts)
                   for kind in ("accurate", "early", "late", "missed")}
        deviations = [row["deviation_ms"] for row in self.attempts if row["deviation_ms"] is not None]
        summary["mean_deviation_ms"] = round(mean(deviations), 1) if deviations else None
        summary["mean_absolute_deviation_ms"] = round(mean(map(abs, deviations)), 1) if deviations else None
        result = {
            "test": "moving_object_reaction_v2",
            "protocol_version": 1,
            "session_id": self.session_id,
            "candidate": self.candidate,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "input": "space",
            "tolerance_ms": self.TOLERANCE_MS,
            "response_grace_seconds": self.RESPONSE_GRACE_SECONDS,
            "summary": summary,
            "attempts": self.attempts,
        }
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        try:
            output = results_dir("exports/moving-object-reaction-v2-results") / f"{stamp}_{self.session_id[:8]}.json"
            atomic_json(output, result)
        except OSError as error:
            self.button.configure(text="Повторить сохранение", command=self.save)
            messagebox.showerror("Ошибка сохранения", str(error), parent=self.window)
            return
        self.status.configure(text=f"Сохранено · точно {summary['accurate']} · рано {summary['early']} · "
                                   f"поздно {summary['late']} · пропущено {summary['missed']}")
        self.button.configure(text="Закрыть", command=self.close)

    def cancel_frame(self):
        if self.frame is not None:
            self.window.after_cancel(self.frame)
            self.frame = None

    def close(self):
        self.cancel_frame()
        self.window.destroy()
