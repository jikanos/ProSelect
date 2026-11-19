"""Run ProSelect with test-only controls for choosing topics and questions."""

import random
import tkinter as tk
from tkinter import messagebox, ttk

from ProSelect import QUESTIONS, ProSelectApp
from CompensationTracker import CompensationTracker
from MovingObjectReactionV2 import MovingObjectReactionV2
from TimeWall import TimeWall


class ProSelectTester(ProSelectApp):
    ALL_TOPICS = "Все темы"
    ANY_QUESTION = "По выбранному режиму"
    ADAPTIVE = "Адаптивный (3 вопроса на уровень)"
    ALL_QUESTIONS = "Все вопросы"
    SINGLE_QUESTION = "Один вопрос"

    def __init__(self, root):
        self.test_topic = tk.StringVar(root, value=self.ALL_TOPICS)
        self.test_mode = tk.StringVar(root, value=self.ADAPTIVE)
        self.test_question = tk.StringVar(root, value=self.ANY_QUESTION)
        self.calculator_only = tk.BooleanVar(root, value=False)
        super().__init__(root, result_folder="exports/tester-results")
        self.name.set("Тестовый участник")
        root.title("ProSelect — проверка опросника")

    def make_start(self):
        self.clear()
        page = tk.Frame(self.root, bg=self.BG, padx=45, pady=32)
        page.pack(fill="both", expand=True)
        header = self.page_header(page)
        self.label(header, "Проверка опросника", 24, bold=True).pack(side="left")

        self.label(page, "ФИО", 11, bold=True).pack(anchor="w", pady=(8, 3))
        tk.Entry(page, textvariable=self.name, font=("Segoe UI", 12)).pack(fill="x", ipady=4)
        self.label(page, "Тема", 11, bold=True).pack(anchor="w", pady=(12, 3))
        topic = ttk.Combobox(page, textvariable=self.test_topic, state="readonly",
                             values=(self.ALL_TOPICS, *self.topics))
        topic.pack(fill="x")
        topic.bind("<<ComboboxSelected>>", self.update_questions)
        ttk.Checkbutton(page, text="Только вопросы с калькулятором",
                        variable=self.calculator_only, command=self.update_questions).pack(
                            anchor="w", pady=(6, 0)
                        )

        self.label(page, "Вопрос по коду", 11, bold=True).pack(anchor="w", pady=(12, 3))
        self.question_picker = ttk.Combobox(page, textvariable=self.test_question, state="readonly")
        self.question_picker.pack(fill="x")
        self.question_picker.bind("<<ComboboxSelected>>", self.update_mode)
        self.preview = self.label(page, "", 10, self.MUTED, wrap=600)
        self.preview.pack(anchor="w")

        self.label(page, "Режим", 11, bold=True).pack(anchor="w", pady=(12, 3))
        self.mode_picker = ttk.Combobox(page, textvariable=self.test_mode, state="readonly",
                                        values=(self.ADAPTIVE, self.ALL_QUESTIONS))
        self.mode_picker.pack(fill="x")
        actions = tk.Frame(page, bg=self.BG)
        actions.pack(anchor="w", pady=(16, 0))
        self.start_button = self.button(actions, "Начать проверку", self.start)
        self.start_button.pack(side="left")
        self.button(actions, "Компенсационный трекер", lambda: self.start_sensorimotor(CompensationTracker),
                    primary=False).pack(side="left", padx=(12, 0))
        self.button(actions, "Time Wall", lambda: self.start_sensorimotor(TimeWall),
                    primary=False).pack(side="left", padx=(12, 0))
        self.button(page, "Реакция на движущийся объект v2",
                    lambda: self.start_sensorimotor(MovingObjectReactionV2),
                    primary=False).pack(anchor="w", pady=(8, 0))
        self.update_questions()

    def start_sensorimotor(self, test):
        candidate = self.name.get().strip()
        if not candidate:
            messagebox.showwarning("Введите ФИО", "Укажите имя тестового участника", parent=self.root)
            return
        test(self.root, candidate)

    def update_questions(self, _event=None):
        topic = self.test_topic.get()
        calculator_only = self.calculator_only.get()
        self.available = {
            q["id"]: q for q in QUESTIONS
            if topic in (self.ALL_TOPICS, q["topic"]) and (not calculator_only or q.get("calculator"))
        }
        self.question_picker.configure(values=(self.ANY_QUESTION, *sorted(self.available)),
                                       state="readonly" if self.available else "disabled")
        if self.test_question.get() not in self.available:
            self.test_question.set(self.ANY_QUESTION)
        self.update_mode()

    def update_mode(self, _event=None):
        question = self.available.get(self.test_question.get())
        calculator_only = self.calculator_only.get()
        if calculator_only:
            self.test_mode.set(self.ALL_QUESTIONS)
        self.mode_picker.configure(state="disabled" if question or calculator_only else "readonly")
        self.start_button.configure(state="normal" if self.available else "disabled")
        if question:
            preview = question["text"].splitlines()[0]
        elif not self.available:
            preview = "В этой теме нет вопросов с калькулятором."
        else:
            preview = ""
        self.preview.configure(text=preview if len(preview) <= 95 else preview[:94] + "…")

    def start(self):
        if not self.available:
            return
        candidate = self.name.get().strip()
        if not candidate:
            messagebox.showwarning("Введите ФИО", "Укажите имя тестового участника", parent=self.root)
            return
        question = self.available.get(self.test_question.get())
        topics = sorted({item["topic"] for item in self.available.values()})
        mode = self.SINGLE_QUESTION if question else self.test_mode.get()
        self.begin_session(candidate, [question["topic"]] if question else topics, mode)

        if mode == self.ADAPTIVE:
            self.adaptive_topic_idx = 0
            self.adaptive_level = 1
            self.next_adaptive_chunk()
        else:
            questions = [question] if question else list(self.available.values())
            random.shuffle(questions)
            self.question_queue = iter(questions)
            self.advance_question()
        self.show_current_question()

    def handle_timeout(self):
        self.record_answer(None, advance=False)
        self.timer_label.configure(text="00:00", fg="#fca5a5")
        self.answer_hint.configure(text="Время истекло. Продолжите, когда будете готовы.")
        self.skip_button.configure(state="disabled")
        self.answer_button.configure(text="Продолжить →", command=self.continue_after_answer)

    def advance_question(self):
        if self.session["mode"] == self.ADAPTIVE:
            super().advance_question()
        else:
            self.current = next(self.question_queue, None)
            if self.current:
                self.adaptive_level = self.current["level"]


if __name__ == "__main__":
    root = tk.Tk()
    ProSelectTester(root)
    root.mainloop()
