"""Time Wall timing task for ProSelectTester."""

from datetime import datetime, timezone
from random import Random
from statistics import mean
from time import monotonic
import tkinter as tk
from tkinter import messagebox, ttk
from uuid import uuid4

from ProSelect import atomic_json, results_dir


class TimeWall:
    TOLERANCE_MS = 100
    RESPONSE_GRACE_SECONDS = 1.5
    SPEEDS = (120, 150, 180, 210, 240, 270) * 2
    START_Y = 40
    MARK_Y = 305

    def __init__(self, parent, candidate):
        self.candidate = candidate
        self.started_at = datetime.now(timezone.utc)
        self.session_id = uuid4().hex
        self.speeds = list(self.SPEEDS)
        Random(1).shuffle(self.speeds)
        self.attempts = []
        self.trial_started = None
        self.frame = None

        self.window = tk.Toplevel(parent)
        self.window.title("Time Wall")
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        panel = ttk.Frame(self.window, padding=16)
        panel.pack()
        ttk.Label(panel, text="Квадрат движется вниз и скрывается за стеной.\n"
                  "Нажмите пробел, когда центр квадрата, по вашей оценке, достигнет белой метки.",
                  justify="left").pack(anchor="w")
        self.canvas = tk.Canvas(panel, width=560, height=360, bg="#111827", highlightthickness=0)
        self.canvas.pack(pady=12)
        self.square = self.canvas.create_rectangle(269, 29, 291, 51, fill="#fb923c", outline="")
        self.canvas.create_rectangle(0, 205, 560, 360, fill="#334155", outline="")
        self.canvas.create_line(250, self.MARK_Y, 310, self.MARK_Y, fill="white", width=3)
        self.status = ttk.Label(panel, text=f"Всего попыток: {len(self.speeds)}")
        self.status.pack(anchor="w")
        self.button = ttk.Button(panel, text="Начать попытку", command=self.start_trial)
        self.button.pack(anchor="w", pady=(8, 0))
        self.window.bind("<space>", self.respond)
        self.window.grab_set()

    def start_trial(self):
        self.button.state(["disabled"])
        self.canvas.focus_set()
        self.speed = self.speeds[len(self.attempts)]
        self.target_time = (self.MARK_Y - self.START_Y) / self.speed
        self.status.configure(text=f"Попытка {len(self.attempts) + 1} из {len(self.speeds)}")
        self.trial_started = monotonic()
        self.animate()

    def animate(self):
        self.frame = None
        elapsed = monotonic() - self.trial_started
        if elapsed >= self.target_time + self.RESPONSE_GRACE_SECONDS:
            self.finish_trial(None)
            return
        y = self.START_Y + self.speed * elapsed
        self.canvas.coords(self.square, 269, y - 11, 291, y + 11)
        self.frame = self.window.after(16, self.animate)

    def respond(self, _event):
        if self.trial_started is not None:
            elapsed = monotonic() - self.trial_started
            if elapsed >= self.target_time + self.RESPONSE_GRACE_SECONDS:
                self.finish_trial(None)
            else:
                self.finish_trial(elapsed)
        return "break"

    def finish_trial(self, elapsed):
        self.trial_started = None
        self.cancel_frame()
        self.canvas.coords(self.square, 269, 29, 291, 51)
        deviation = None if elapsed is None else round((elapsed - self.target_time) * 1000, 1)
        if deviation is None:
            kind, feedback = "missed", "Пропуск"
        elif abs(deviation) <= self.TOLERANCE_MS:
            kind, feedback = "accurate", f"Точно ({deviation:+.1f} мс)"
        elif deviation < 0:
            kind, feedback = "early", f"Раньше на {-deviation:.1f} мс"
        else:
            kind, feedback = "late", f"Позже на {deviation:.1f} мс"
        self.attempts.append({
            "attempt": len(self.attempts) + 1,
            "speed_px_per_second": self.speed,
            "target_time_ms": round(self.target_time * 1000, 1),
            "response_time_ms": None if elapsed is None else round(elapsed * 1000, 1),
            "deviation_ms": deviation,
            "outcome": kind,
        })
        self.button.state(["!disabled"])
        if len(self.attempts) == len(self.speeds):
            self.save()
        else:
            self.status.configure(text=feedback)
            self.button.configure(text="Следующая попытка")

    def save(self):
        summary = {kind: sum(row["outcome"] == kind for row in self.attempts)
                   for kind in ("accurate", "early", "late", "missed")}
        deviations = [row["deviation_ms"] for row in self.attempts if row["deviation_ms"] is not None]
        summary["mean_absolute_deviation_ms"] = round(mean(map(abs, deviations)), 1) if deviations else None
        result = {
            "test": "time_wall",
            "protocol_version": 1,
            "session_id": self.session_id,
            "candidate": self.candidate,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "input": "space",
            "tolerance_ms": self.TOLERANCE_MS,
            "summary": summary,
            "attempts": self.attempts,
        }
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        try:
            output = results_dir("exports/time-wall-results") / f"{stamp}_{self.session_id[:8]}.json"
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
