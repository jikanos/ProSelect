# -*- coding: utf-8 -*-
"""ProSelect — автономное пробное тестирование.
Запуск: python ProSelect.py (Python 3.9+, стандартная библиотека).
Банк вопросов хранится в локальном файле questions.json.
"""
import ctypes
from hashlib import sha256
from math import ceil
from time import monotonic
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime, timezone
import json, random, uuid, sys, os

BANK_SOURCE = "Реестр Профотбор, выгрузка 2026-11-12"
with Path(__file__).with_name("questions.json").open(encoding="utf-8") as bank_file:
    QUESTIONS = json.load(bank_file)

BANK_SHA256 = sha256(
    json.dumps(QUESTIONS, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

version_file = Path(__file__).with_name("build_version.json")
APP_VERSION = (
    json.loads(version_file.read_text(encoding="utf-8"))["version"]
    if version_file.is_file() else "dev"
)

LETTERS = "АБВГ"


def is_online():
    if sys.platform != "win32":
        return False

    # Windows Network List Manager reports Internet connectivity without an app-level probe.
    guid_type = ctypes.c_ubyte * 16
    class_id = guid_type.from_buffer_copy(uuid.UUID("DCB00C01-570F-4A9B-8D69-199FDBA5723B").bytes_le)
    interface_id = guid_type.from_buffer_copy(uuid.UUID("DCB00000-570F-4A9B-8D69-199FDBA5723B").bytes_le)
    ole = ctypes.windll.ole32
    if ole.CoInitialize(None) < 0:
        return False

    try:
        manager = ctypes.c_void_p()
        if ole.CoCreateInstance(ctypes.byref(class_id), None, 1, ctypes.byref(interface_id),
                                ctypes.byref(manager)) < 0:
            return False
        methods = ctypes.cast(manager, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(methods[2])
        try:
            # INetworkListManager::get_IsConnectedToInternet follows the four network accessors.
            connected = ctypes.c_short()
            get_connected = ctypes.WINFUNCTYPE(
                ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_short)
            )(methods[11])
            return get_connected(manager, ctypes.byref(connected)) == 0 and bool(connected.value)
        finally:
            release(manager)
    finally:
        ole.CoUninitialize()


def results_dir():
    # Portable: рядом со скриптом/EXE. Если нет прав — в домашней папке.
    location = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    locations = [location / "results", Path.home() / "ProSelect" / "results"]
    for candidate in locations:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / (".write_test_" + uuid.uuid4().hex)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    raise OSError("Не удалось создать папку для результатов")


def atomic_json(path, obj):
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


class ProSelectApp:
    BG = "#111827"
    PANEL = "#1f2937"
    TEXT = "#f3f4f6"
    MUTED = "#9ca3af"
    ACCENT = "#60a5fa"

    def __init__(self, root):
        self.root = root
        self.root.title("ProSelect — пробная версия")
        self.root.geometry("960x720")
        self.root.minsize(760, 580)
        self.root.configure(bg=self.BG)
        logo_path = Path(__file__).with_name("de-friz_logo.png")
        self.logo = tk.PhotoImage(master=root, file=logo_path)
        self.out = results_dir()
        self.session = None
        self.current = None
        self.question_timer = None
        self.question_deadline = None
        self.selected = tk.IntVar(value=-1)
        self.name = tk.StringVar()
        self.adaptive_topic_idx = 0
        self.adaptive_level = 1
        self.adaptive_chunk = []
        self.adaptive_chunk_index = 0
        self.topics = sorted(set(q["topic"] for q in QUESTIONS))
        self.make_start()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def clear(self):
        self.stop_question_timer()
        for child in self.root.winfo_children():
            child.destroy()

    def label(self, parent, text, size=12, color=None, bold=False, wrap=None):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or self.TEXT,
                        font=("Segoe UI", size, "bold" if bold else "normal"),
                        anchor="w", justify="left", wraplength=wrap)

    def button(self, parent, text, command, primary=True):
        return tk.Button(parent, text=text, command=command,
                         bg=self.ACCENT if primary else self.PANEL,
                         fg="#0b1220" if primary else self.TEXT,
                         activebackground="#93c5fd", activeforeground="#0b1220",
                         font=("Segoe UI", 11, "bold"), borderwidth=0,
                         padx=18, pady=11, cursor="hand2")

    def page_header(self, parent):
        header = tk.Frame(parent, bg=self.BG)
        header.pack(fill="x")
        tk.Label(header, image=self.logo, bg=self.BG, borderwidth=0).pack(side="right", anchor="n")
        footer = tk.Frame(parent, bg=self.BG)
        footer.pack(side="bottom", fill="x")
        status = self.label(footer, "", 11, bold=True)
        status.pack(side="left")
        self.label(footer, APP_VERSION, 10, self.MUTED).pack(side="right")
        self.refresh_connection_status(status)
        return header

    def make_start(self):
        self.clear()
        outer = tk.Frame(self.root, bg=self.BG, padx=45, pady=42)
        outer.pack(fill="both", expand=True)
        header = self.page_header(outer)
        self.label(header, "ProSelect / ПРОФОТБОР", 13, self.ACCENT, True).pack(side="left")
        self.label(outer, "Система проверки знаний", 28, bold=True).pack(anchor="w", pady=(12, 5))
        self.label(outer, "Тест разработан командой АНО «Де-Фриз».",
                   11, self.MUTED).pack(anchor="w", pady=(0, 32))
        self.label(outer, "ФИО", 12, bold=True).pack(anchor="w")
        name_entry = tk.Entry(outer, textvariable=self.name, font=("Segoe UI", 14), bg="#374151", fg="white",
                              insertbackground="white", relief="flat")
        name_entry.pack(fill="x", ipady=9, pady=(8, 23))
        name_entry.focus_set()
        self.label(outer, "У каждого вопроса только один правильный вариант ответа.",
                   11, self.MUTED).pack(anchor="w", pady=(0, 6))
        self.label(outer, "Время на каждый вопрос ограничено. Выберите вариант и нажмите «Ответить» до истечения времени. Когда время закончится, тест автоматически перейдёт к следующему вопросу.",
                   11, self.MUTED, wrap=620).pack(anchor="w", pady=(0, 16))
        self.button(outer, "Начать тестирование", self.start).pack(anchor="w")

    def refresh_connection_status(self, label):
        online = is_online()
        label.configure(text="● Online" if online else "● Offline",
                        fg="#86efac" if online else self.MUTED)
        refresh = label.after(5000, self.refresh_connection_status, label)
        label.bind("<Destroy>", lambda event: label.after_cancel(refresh))

    def start(self):
        candidate = self.name.get().strip()
        if not candidate:
            messagebox.showwarning("Введите ФИО", "Укажите ФИО кандидата")
            return
        self.session = {"session_id":str(uuid.uuid4()), "candidate":candidate,
                        "started_at":datetime.now(timezone.utc).isoformat(), "finished_at":None,
                        "status":"in_progress", "mode":"Адаптивный (3 вопроса на уровень)", "topics":self.topics,
                        "app_version":APP_VERSION, "bank_sha256":BANK_SHA256,
                        "bank_source":BANK_SOURCE, "answers":[], "topic_results":[], "timeout_count":0}
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filebase = self.out / (stamp + "_" + self.session["session_id"][:8])
        self.save()
        self.adaptive_topic_idx = 0
        self.adaptive_level = 1
        self.next_adaptive_chunk()
        if self.current is None:
            self.finish()
        else:
            self.show_question()

    def next_adaptive_chunk(self):
        chosen=self.session["topics"]
        while self.adaptive_topic_idx < len(chosen):
            topic=chosen[self.adaptive_topic_idx]
            pool=[q for q in QUESTIONS if q["topic"]==topic and q["level"]==self.adaptive_level and q["id"] not in [a["code"] for a in self.session["answers"]]]
            if len(pool)>=3:
                self.adaptive_chunk=random.sample(pool,3)
                self.adaptive_chunk_index=0
                self.current=self.adaptive_chunk[0]
                return
            self.session["topic_results"].append({"topic":topic, "last_passed_level":self.adaptive_level-1, "stop_reason":"Недостаточно вопросов на уровне " + str(self.adaptive_level)})
            self.adaptive_topic_idx+=1
            self.adaptive_level=1
        self.current=None

    def show_question(self):
        self.clear()
        self.selected.set(-1)
        q=self.current
        self.display_order=list(range(4))
        random.shuffle(self.display_order)
        main=tk.Frame(self.root,bg=self.BG,padx=45,pady=35)
        main.pack(fill="both",expand=True)
        header = self.page_header(main)
        details = tk.Frame(header, bg=self.BG)
        details.pack(side="left", anchor="n")
        self.label(details, "ProSelect / ПРОФОТБОР", 12, self.ACCENT, True).pack(anchor="w")
        progress = tk.Frame(details, bg=self.BG)
        progress.pack(anchor="w", pady=(22, 8))
        self.label(progress, q['id'], 11, self.MUTED).pack(side="left")
        self.label(progress, str(self.adaptive_level), 11, self.ACCENT, bold=True).pack(side="left", padx=(12, 0))
        timer = self.label(header, self.format_time(q["time_limit_seconds"]), 16, bold=True)
        timer.pack(side="right", anchor="n", padx=(0, 16))
        bottom=tk.Frame(main,bg=self.BG)
        bottom.pack(side="bottom",fill="x",pady=(20,0))
        self.button(bottom,"Ответить →",self.submit).pack(side="right")
        self.answer_hint = self.label(bottom, "Ответ сохраняется после нажатия кнопки", 10, self.MUTED)
        self.answer_hint.pack(side="left")
        question=tk.Message(main,text=q["text"],width=820,bg=self.BG,fg=self.TEXT,font=("Segoe UI",18,"bold"))
        question.pack(anchor="w",fill="x",pady=(18,22))
        choices=tk.Frame(main,bg=self.BG)
        choices.pack(fill="x")
        for i, original_index in enumerate(self.display_order):
            option=q["options"][original_index]
            row=tk.Radiobutton(choices,text=option,variable=self.selected,value=i,
                               font=("Segoe UI",12),bg=self.PANEL,fg=self.TEXT,selectcolor="#374151",
                               activebackground=self.PANEL,activeforeground=self.TEXT,
                               indicatoron=True,justify="left",anchor="w",wraplength=730,padx=17,pady=12)
            row.pack(fill="x",pady=4)

        self.question_timer = self.root.after_idle(self.start_question_timer, timer, q["time_limit_seconds"])

    @staticmethod
    def format_time(seconds):
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def start_question_timer(self, label, limit):
        self.question_deadline = monotonic() + limit
        self.tick_question_timer(label)

    def tick_question_timer(self, label):
        self.question_timer = None
        remaining = self.question_deadline - monotonic()
        if remaining <= 0:
            self.record_answer(None)
            return

        seconds = ceil(remaining)
        label.configure(text=self.format_time(seconds), fg="#fca5a5" if seconds <= 10 else self.TEXT)
        self.question_timer = self.root.after(
            max(1, ceil((remaining - seconds + 1) * 1000)), self.tick_question_timer, label
        )

    def stop_question_timer(self):
        if self.question_timer is not None:
            self.root.after_cancel(self.question_timer)
            self.question_timer = None
        self.question_deadline = None

    def submit(self):
        if self.question_deadline is None:
            return
        if monotonic() >= self.question_deadline:
            self.record_answer(None)
            return
        value = self.selected.get()
        if value < 0:
            self.answer_hint.configure(text="Сначала выберите один из вариантов")
            return
        self.record_answer(value)

    def record_answer(self, value):
        self.stop_question_timer()
        q = self.current
        timed_out = value is None
        original_index = None if timed_out else self.display_order[value]
        answer = {
            "code": q["id"], "topic": q["topic"], "level": q["level"], "question": q["text"],
            "options": q["options"], "selected_index": original_index,
            "selected_letter": None if timed_out else LETTERS[value],
            "selected_text": None if timed_out else q["options"][original_index],
            "correct_index": q["correct"], "correct_letter": LETTERS[self.display_order.index(q["correct"])],
            "is_correct": original_index == q["correct"], "timed_out": timed_out,
            "time_limit_seconds": q["time_limit_seconds"], "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.session["timeout_count"] += int(timed_out)
        self.session["answers"].append(answer)
        self.save()
        self.adaptive_chunk_index+=1
        if self.adaptive_chunk_index<3:
            self.current=self.adaptive_chunk[self.adaptive_chunk_index]
        else:
            recent=self.session["answers"][-3:]
            score=sum(a["is_correct"] for a in recent)
            if score>=2:
                self.adaptive_level+=1
                if self.adaptive_level>5:
                    self.session["topic_results"].append({"topic":recent[0]["topic"],"last_passed_level":5,"stop_reason":"Пройден уровень 5"})
                    self.adaptive_topic_idx+=1
                    self.adaptive_level=1
            else:
                self.session["topic_results"].append({"topic":recent[0]["topic"],"last_passed_level":self.adaptive_level-1,"stop_reason":f"На уровне {self.adaptive_level}: {score}/3"})
                self.adaptive_topic_idx+=1
                self.adaptive_level=1
            self.next_adaptive_chunk()
        if self.current is None:self.finish()
        else:self.show_question()

    def save(self):
        atomic_json(self.filebase.with_suffix(".json"),self.session)

    def finish(self):
        self.session["status"]="completed"
        self.session["finished_at"]=datetime.now(timezone.utc).isoformat()
        self.save()
        self.clear()
        main=tk.Frame(self.root,bg=self.BG,padx=45,pady=55)
        main.pack(fill="both",expand=True)
        header = self.page_header(main)
        self.label(header, "Тестирование завершено", 27, bold=True).pack(side="left", anchor="n")
        answers=self.session["answers"]
        correct=sum(a["is_correct"] for a in answers)
        self.label(main,f"Итоговый балл: {correct}",20,self.ACCENT,True).pack(anchor="w",pady=(24,18))
        self.label(main, f"Время истекло: {self.session['timeout_count']}", 11, self.MUTED).pack(anchor="w")
        by_topic={}
        for a in answers:
            by_topic.setdefault(a["topic"],[0,0])
            by_topic[a["topic"]][0]+=int(a["is_correct"])
            by_topic[a["topic"]][1]+=1
        for t,(ok,total) in by_topic.items():
            self.label(main,f"{t}: {ok}/{total}",12).pack(anchor="w",pady=4)
        if self.session["topic_results"]:
            self.label(main,"Результат адаптивного прохождения:",12,bold=True).pack(anchor="w",pady=(16,6))
            for item in self.session["topic_results"]:
                self.label(main,f"{item['topic']}: пройден уровень {item['last_passed_level']} · {item['stop_reason']}",10,self.MUTED).pack(anchor="w")
        self.button(main,"Новое тестирование",self.make_start).pack(anchor="w")

    def close(self):
        if self.session and self.session["status"]=="in_progress":
            if not messagebox.askyesno("Завершить работу?","Тест не завершён. Уже данные ответы сохранены. Закрыть программу?"):
                return
        self.stop_question_timer()
        self.root.destroy()


if __name__=="__main__":
    root=tk.Tk()
    ProSelectApp(root)
    root.mainloop()
