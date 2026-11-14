"""Offline Windows viewer and HTML exporter for ProSelect results."""

import json
import tkinter as tk
from collections import Counter, defaultdict
from html import escape
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


ORGANIZATION = "АНО Де-Фриз"


version_file = Path(__file__).with_name("build_version.json")
APP_VERSION = (
    json.loads(version_file.read_text(encoding="utf-8"))["version"]
    if version_file.is_file() else "dev"
)


def validate(result):
    if not isinstance(result, dict):
        raise ValueError("Ожидался объект результата")
    for key in ("session_id", "candidate"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise ValueError(f"Отсутствует поле {key}")
    if result.get("status") not in ("completed", "in_progress"):
        raise ValueError("Неизвестный статус результата")
    for key in ("topics", "answers", "topic_results"):
        if not isinstance(result.get(key), list):
            raise ValueError(f"Отсутствует список {key}")
    if not all(isinstance(topic, str) for topic in result["topics"]):
        raise ValueError("Некорректный список тем")
    for item in result["topic_results"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("topic"), str)
            or type(item.get("last_passed_level")) is not int
            or not 0 <= item["last_passed_level"] <= 5
            or not isinstance(item.get("stop_reason"), str)
        ):
            raise ValueError("Некорректный итог по теме")
    for answer in result["answers"]:
        if (
            not isinstance(answer, dict)
            or not all(isinstance(answer.get(key), str) for key in ("topic", "code", "question"))
            or type(answer.get("level")) is not int
            or not 1 <= answer["level"] <= 5
            or type(answer.get("is_correct")) is not bool
            or type(answer.get("timed_out")) is not bool
        ):
            raise ValueError("Некорректная запись ответа")
        options = answer.get("options")
        correct = answer.get("correct_index")
        selected = answer.get("selected_index")
        if (
            not isinstance(options, list)
            or not all(isinstance(option, str) for option in options)
            or type(correct) is not int
            or not 0 <= correct < len(options)
            or (selected is not None and (type(selected) is not int or not 0 <= selected < len(options)))
            or answer["timed_out"] != (selected is None)
            or answer["is_correct"] != (selected == correct)
        ):
            raise ValueError("Некорректные варианты или отметка ответа")


def score(result):
    return sum(answer["is_correct"] for answer in result["answers"])


def load_group(folder):
    attempts = {}
    warnings = []
    for path in sorted(folder.rglob("*.json")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(folder)
        try:
            result = json.loads(path.read_text(encoding="utf-8-sig"))
            validate(result)
        except (OSError, ValueError) as error:
            warnings.append(f"{relative_path} — {error}")
            continue
        key = result["session_id"]
        if key in attempts:
            warnings.append(f"{relative_path} — повторная копия попытки")
            previous = attempts[key]
            if (result["status"] == "completed", len(result["answers"])) <= (
                previous["status"] == "completed", len(previous["answers"])
            ):
                continue
        attempts[key] = result
    return sorted(attempts.values(), key=lambda result: (-score(result), result["candidate"].casefold())), warnings


def percentage(count, total):
    return f"{count / total:.0%}" if total else "—"


def outcome(answer):
    if answer["timed_out"]:
        return "Тайм-аут"
    return "Верно" if answer["is_correct"] else "Ошибка"


def topic_summary(result, topic):
    answers = [answer for answer in result["answers"] if answer["topic"] == topic]
    saved = next((item for item in result["topic_results"] if item["topic"] == topic), None)
    if saved:
        passed = saved["last_passed_level"]
    elif answers:
        blocks = defaultdict(list)
        for answer in answers:
            blocks[answer["level"]].append(answer["is_correct"])
        passed = max((level for level, block in blocks.items() if len(block) == 3 and sum(block) >= 2), default=0)
    else:
        return "—", "Тема не начата"
    label = str(passed) if passed else "0"
    if saved:
        reason = saved["stop_reason"]
    else:
        reason = "Итог темы не сохранён"
        label = f"{label} · прервано" if passed else "Прервано"
    return label, reason


STUDENT_COLUMNS = ("Место", "Студент", "Баллы", "Вопросов", "Тайм-ауты", "Статус")
LEVEL_COLUMNS = ("Тема", "Уровень", "Дошли", "Ответили на все 3", "Прошли", "% от полных")
QUESTION_COLUMNS = ("Код", "Тема", "Уровень", "Вопрос", "Показов¹", "Верно", "% верных",
                    "Ошибки", "Тайм-ауты", "Частый неверный ответ")
ANSWER_COLUMNS = ("Тема", "Уровень", "Код", "Вопрос", "Ответ студента", "Правильный ответ", "Итог")
QUESTION_NOTE = "¹ Учитываются вопросы, по которым записан ответ или тайм-аут."

COLUMN_HINTS = {
    "Место": "Место по числу баллов. При равных баллах место одинаковое.",
    "Студент": "ФИО из файла результата.",
    "Баллы": "Число правильных ответов. Один правильный ответ даёт один балл.",
    "Вопросов": "Число вопросов с записанным ответом или тайм-аутом.",
    "Тайм-ауты": "Число вопросов, на которые не успели ответить.",
    "Статус": "Завершена ли попытка.",
    "Тема": "Тема вопроса или проверяемого уровня.",
    "Уровень": "Уровень сложности от 1 до 5.",
    "Дошли": "Число попыток с хотя бы одной записью на этом уровне.",
    "Ответили на все 3": "Число попыток со всеми тремя записями уровня, включая тайм-ауты.",
    "Прошли": "Число попыток с двумя или тремя верными ответами из трёх.",
    "% от полных": "Доля прошедших среди попыток со всеми тремя записями уровня.",
    "Код": "Идентификатор вопроса в банке.",
    "Вопрос": "Текст задания.",
    "Показов¹": "Число показов с записанным ответом или тайм-аутом.",
    "Верно": "Число правильных ответов.",
    "% верных": "Доля правильных ответов от всех учтённых показов, включая тайм-ауты.",
    "Ошибки": "Число выбранных неверных ответов.",
    "Частый неверный ответ": "Наиболее часто выбранные неверные варианты и число выборов.",
    "Пройденный уровень": "Последний пройденный уровень. Ноль означает, что первый уровень не пройден.",
    "Результат": "Причина завершения или состояние прохождения темы.",
    "Ответ студента": "Выбранный вариант. Прочерк означает, что время истекло.",
    "Правильный ответ": "Правильный вариант по банку вопросов.",
    "Итог": "Верный ответ, ошибка или тайм-аут.",
}


def column_hint(heading, is_topic=False):
    if is_topic:
        return (f"{heading}. Последний пройденный уровень. "
                "0 — первый уровень не пройден. «—» — тема не начата.")
    return COLUMN_HINTS[heading]


def group_tables(results):
    topics = list(dict.fromkeys(
        topic for result in results for topic in (
            result["topics"] + [item["topic"] for item in result["topic_results"]]
            + [answer["topic"] for answer in result["answers"]]
        )
    ))
    students = []
    levels = defaultdict(Counter)
    questions = defaultdict(Counter)
    previous_score = None
    for index, result in enumerate(results, 1):
        points = score(result)
        if points != previous_score:
            rank = index
            previous_score = points
        students.append((
            rank, result["candidate"], points, len(result["answers"]),
            sum(answer["timed_out"] for answer in result["answers"]),
            "Завершён" if result["status"] == "completed" else "Не завершён",
            *(topic_summary(result, topic)[0] for topic in topics),
        ))
        blocks = defaultdict(list)
        for answer in result["answers"]:
            blocks[answer["topic"], answer["level"]].append(answer["is_correct"])
            key = (answer["topic"], answer["level"], answer["code"], answer["question"],
                   tuple(answer["options"]), answer["correct_index"])
            questions[key][answer["selected_index"]] += 1
        for key, block in blocks.items():
            levels[key]["reached"] += 1
            if len(block) == 3:
                levels[key]["complete"] += 1
                levels[key]["passed"] += int(sum(block) >= 2)
    level_rows = [
        (topic, level, counts["reached"], counts["complete"], counts["passed"],
         percentage(counts["passed"], counts["complete"]))
        for (topic, level), counts in sorted(levels.items())
    ]
    question_rows = []
    for (topic, level, code, question, options, correct), counts in sorted(questions.items()):
        total = sum(counts.values())
        wrong = [(count, options[index]) for index, count in counts.items() if index not in (None, correct)]
        most_common = "—"
        if wrong:
            highest = max(count for count, _ in wrong)
            choices = ", ".join(sorted(text for count, text in wrong if count == highest))
            most_common = f"{choices} ({highest})"
        question_rows.append((
            code, topic, level, question, total, counts[correct], percentage(counts[correct], total),
            total - counts[correct] - counts[None], counts[None], most_common,
        ))
    return [(STUDENT_COLUMNS + tuple(topics), students),
            (LEVEL_COLUMNS, level_rows), (QUESTION_COLUMNS, question_rows)]


def student_details(result):
    topics = list(dict.fromkeys(result["topics"] + [answer["topic"] for answer in result["answers"]]
                               + [item["topic"] for item in result["topic_results"]]))
    summaries = [(topic, *topic_summary(result, topic)) for topic in topics]
    answers = [
        (answer["topic"], answer["level"], answer["code"], answer["question"],
         "—" if answer["timed_out"] else answer["options"][answer["selected_index"]],
         answer["options"][answer["correct_index"]], outcome(answer))
        for answer in result["answers"]
    ]
    return [(("Тема", "Пройденный уровень", "Результат"), summaries), (ANSWER_COLUMNS, answers)]


def html_table(columns, rows, student_links=False):
    headings = "".join(
        f'<th scope="col" title="{escape(column_hint(title, student_links and index >= len(STUDENT_COLUMNS)))}">'
        f"{escape(title)}</th>"
        for index, title in enumerate(columns)
    )
    body = []
    for index, row in enumerate(rows):
        cells = [escape(str(value)) for value in row]
        if student_links:
            cells[1] = f'<a href="#student-{index}">{cells[1]}</a>'
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    return f'<div class="table"><table><thead><tr>{headings}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def group_summary(results):
    completed = sum(result["status"] == "completed" for result in results)
    return f"Попыток: {len(results)} · завершено: {completed} · не завершено: {len(results) - completed}"


def make_report(folder, results, warnings):
    parts = [
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>ProSelect — отчёт по группе</title>',
        """<style>
        body { font: 15px/1.5 "Segoe UI", sans-serif; color: #19293a; margin: 2rem auto;
               max-width: 96rem; padding: 0 1.5rem; }
        h1, h2 { line-height: 1.2; } h2 { margin-top: 2rem; }
        a { color: #075c80; } .table { overflow-x: auto; margin-bottom: 1rem; }
        table { border-collapse: collapse; width: 100%; }
        th, td { text-align: left; vertical-align: top; padding: .5rem .7rem; border: 1px solid #ccd7df; }
        th { background: #e8f1f5; } tbody tr:nth-child(even) { background: #f5f8fa; }
        details { padding: .65rem 0; border-bottom: 1px solid #ccd7df; }
        summary { cursor: pointer; font-weight: 600; } details:target { background: #eef6fa; }
        @media print { body { margin: 0; padding: 0; } tr { break-inside: avoid; } }
        </style></head><body>""",
        f"<h1>Отчёт по группе · {escape(folder.name)}</h1>",
        f"<p>{escape(ORGANIZATION)}</p>",
        f"<p>{group_summary(results)}</p>",
        "<p>Балл — один правильный ответ. Отдельные попытки отображаются отдельными строками.</p>",
    ]
    for index, (title, table) in enumerate(zip(("Студенты", "Уровни", "Вопросы"), group_tables(results))):
        parts.append(f"<h2>{title}</h2>")
        if index == 2:
            parts.append(f"<p>{QUESTION_NOTE}</p>")
        parts.append(html_table(*table, student_links=index == 0))
    parts.append("<h2>Подробности по студентам</h2>")
    for index, result in enumerate(results):
        parts.append(f'<details id="student-{index}"><summary>{escape(result["candidate"])}'
                     f' · {score(result)} из {len(result["answers"])}</summary>')
        parts.extend(html_table(*table) for table in student_details(result))
        parts.append("</details>")
    if warnings:
        parts.append("<h2>Замечания при импорте</h2><ul>")
        parts.extend(f"<li>{escape(warning)}</li>" for warning in warnings)
        parts.append("</ul>")
    parts.append("""<script>
    function revealStudent() {
      const target = document.getElementById(location.hash.slice(1));
      if (target?.tagName === 'DETAILS') target.open = true;
    }
    addEventListener('hashchange', revealStudent);
    revealStudent();
    </script></body></html>""")
    return "\n".join(parts)


WIDE_COLUMNS = {
    "Студент": 220, "Тема": 240, "Вопрос": 420, "Ответ студента": 220,
    "Правильный ответ": 220, "Частый неверный ответ": 240, "Результат": 300,
    "Статус": 120, "Пройденный уровень": 145, "Ответили на все 3": 135,
}


def column_sort_key(value, heading, is_topic):
    if isinstance(value, int):
        return value
    if is_topic or heading == "Пройденный уровень":
        level = value.partition(" ")[0]
        return int(level) if level.isdecimal() else None
    if heading in ("% от полных", "% верных"):
        return int(value[:-1]) if value.endswith("%") and value[:-1].isdecimal() else None
    return None if value == "—" else value.casefold()


class Table(ttk.Frame):
    def __init__(self, parent, height=12):
        super().__init__(parent)
        self.tree = ttk.Treeview(self, show="headings", selectmode="browse", height=height)
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.hints = ()
        self.hovered_column = ""
        self.hint_timer = None
        self.tooltip = None
        self.tree.bind("<Motion>", self.track_pointer)
        self.tree.bind("<Leave>", self.clear_tooltip)
        self.tree.bind("<ButtonPress>", self.clear_tooltip)
        self.tree.bind("<MouseWheel>", self.clear_tooltip)
        self.tree.bind("<Destroy>", self.clear_tooltip)

    def clear_tooltip(self, _event=None):
        self.hovered_column = ""
        if self.hint_timer is not None:
            self.after_cancel(self.hint_timer)
            self.hint_timer = None
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None

    def track_pointer(self, event):
        region = self.tree.identify_region(event.x, event.y)
        column = self.tree.identify_column(event.x) if region in ("heading", "cell") else ""
        if column == self.hovered_column:
            return
        self.clear_tooltip()
        if column:
            self.hovered_column = column
            self.hint_timer = self.after(600, self.show_tooltip)

    def show_tooltip(self):
        self.hint_timer = None
        index = int(self.hovered_column[1:]) - 1
        x, y = self.tree.winfo_pointerxy()
        self.tooltip = tk.Toplevel(self)
        self.tooltip.wm_overrideredirect(True)
        label = tk.Label(self.tooltip, text=self.hints[index], wraplength=340, justify="left",
                         background="#fff8d8", foreground="#19293a", padx=9, pady=6, relief="solid",
                         borderwidth=1, font=("Segoe UI", 9))
        label.pack()
        self.tooltip.update_idletasks()
        width, height = label.winfo_reqwidth(), label.winfo_reqheight()
        left = min(x + 14, self.tree.winfo_screenwidth() - width)
        top = y + 20 if y + 20 + height <= self.tree.winfo_screenheight() else y - height - 8
        self.tooltip.wm_geometry(f"+{max(0, left)}+{max(0, top)}")

    def fill(self, headings, rows, topic_columns=False):
        self.clear_tooltip()
        self.headings = headings
        self.rows = rows
        self.topic_columns = topic_columns
        self.sort_index = 2 if topic_columns else None
        self.descending = topic_columns
        self.hints = tuple(
            column_hint(heading, topic_columns and index >= len(STUDENT_COLUMNS))
            for index, heading in enumerate(headings)
        )
        self.tree.delete(*self.tree.get_children())
        columns = tuple(str(index) for index in range(len(headings)))
        self.tree.configure(columns=columns)
        for index, (column, heading) in enumerate(zip(columns, headings)):
            width = WIDE_COLUMNS.get(heading, 100)
            is_topic = topic_columns and index >= len(STUDENT_COLUMNS)
            if is_topic:
                width = max(150, len(heading) * 8)
            title = f"{heading} ▼" if index == self.sort_index else heading
            self.tree.heading(column, text=title, command=lambda index=index: self.sort_by(index))
            self.tree.column(column, width=width, minwidth=60, stretch=False,
                             anchor="center" if is_topic or width < 180 else "w")
        for index, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(index), values=row, tags=("alternate",) if index % 2 else ())
        self.tree.tag_configure("alternate", background="#edf4f8")
        self.tree.xview_moveto(0)
        self.tree.yview_moveto(0)

    def sort_by(self, index):
        self.clear_tooltip()
        if self.sort_index is not None:
            self.tree.heading(str(self.sort_index), text=self.headings[self.sort_index])
        self.descending = not self.descending if index == self.sort_index else False
        self.sort_index = index
        is_topic = self.topic_columns and index >= len(STUDENT_COLUMNS)
        keys = {
            str(i): column_sort_key(row[index], self.headings[index], is_topic)
            for i, row in enumerate(self.rows)
        }
        ordered = sorted((row for row, key in keys.items() if key is not None),
                         key=keys.__getitem__, reverse=self.descending)
        ordered.extend(row for row, key in keys.items() if key is None)
        self.tree.set_children("", *ordered)
        for position, row in enumerate(ordered):
            self.tree.item(row, tags=("alternate",) if position % 2 else ())
        arrow = "▼" if self.descending else "▲"
        self.tree.heading(str(index), text=f"{self.headings[index]} {arrow}")
        self.tree.yview_moveto(0)


def add_row_preview(parent, table, headings, rows):
    frame = ttk.Frame(parent)
    frame.pack(fill="x", pady=(8, 0))
    preview = tk.Text(frame, height=5, wrap="word", font=("Segoe UI", 10),
                      background="#edf4f8", foreground="#19293a", relief="flat", padx=10, pady=8)
    scroll = ttk.Scrollbar(frame, orient="vertical", command=preview.yview)
    preview.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    preview.pack(side="left", fill="x", expand=True)

    def show_selected(_event=None):
        selected = table.tree.selection()
        content = "Выберите строку, чтобы прочитать её целиком."
        if selected:
            row = rows[int(selected[0])]
            content = "\n".join(f"{title} · {value}" for title, value in zip(headings, row))
        preview.configure(state="normal")
        preview.delete("1.0", "end")
        preview.insert("1.0", content)
        preview.configure(state="disabled")

    table.tree.bind("<<TreeviewSelect>>", show_selected)
    show_selected()


class Analyzer:
    def __init__(self, root):
        self.root = root
        self.folder = None
        self.results = []
        self.warnings = []
        root.title("ProSelect — анализ результатов")
        root.geometry("1350x730")
        root.minsize(780, 500)
        style = ttk.Style(root)
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        main = ttk.Frame(root, padding=20)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Анализ результатов ProSelect", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(main, text=ORGANIZATION).pack(anchor="w")
        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=(12, 8))
        ttk.Button(actions, text="Выбрать папку…", command=self.choose_folder).pack(side="left")
        self.export_button = ttk.Button(actions, text="Сохранить HTML…", command=self.export, state="disabled")
        self.export_button.pack(side="left", padx=8)
        self.warning_button = ttk.Button(actions, command=self.show_warnings)
        self.summary = ttk.Label(main, text="Выберите папку с JSON-файлами одной группы.")
        self.summary.pack(anchor="w", pady=(0, 10))
        ttk.Label(main, text=APP_VERSION).pack(side="bottom", anchor="e", pady=(8, 0))
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)

    def choose_folder(self):
        path = filedialog.askdirectory(parent=self.root, title="Папка с результатами ProSelect",
                                       initialdir=str(self.folder) if self.folder else None)
        if path:
            self.open_folder(Path(path))

    def open_folder(self, folder):
        try:
            results, warnings = load_group(folder)
        except OSError as error:
            messagebox.showerror("Ошибка импорта", str(error), parent=self.root)
            return
        self.folder, self.results, self.warnings = folder, results, warnings
        self.summary.configure(text=f"{folder.name} · {group_summary(results)}" if results
                               else f"{folder.name} · Нет результатов ProSelect для отображения")
        self.export_button.configure(state="normal" if results else "disabled")
        self.warning_button.pack_forget()
        if warnings:
            self.warning_button.configure(text=f"Замечания при импорте ({len(warnings)})")
            self.warning_button.pack(side="left")
        for tab in self.tabs.tabs():
            self.root.nametowidget(tab).destroy()
        for index, (title, (headings, rows)) in enumerate(zip(
            ("Студенты", "Уровни", "Вопросы"), group_tables(results)
        )):
            page = ttk.Frame(self.tabs, padding=10)
            self.tabs.add(page, text=title)
            if index == 0:
                tools = ttk.Frame(page)
                tools.pack(fill="x", pady=(0, 8))
                button = ttk.Button(tools, text="Открыть детали", command=self.open_student, state="disabled")
                button.pack(side="left")
                ttk.Label(tools, text="Балл — один правильный ответ. По темам указан пройденный уровень.").pack(
                    side="left", padx=10
                )
            elif index == 2:
                ttk.Label(page, text=QUESTION_NOTE).pack(anchor="w", pady=(0, 8))
            table = Table(page)
            table.pack(fill="both", expand=True)
            table.fill(headings, rows, topic_columns=index == 0)
            if index == 0:
                self.students = table.tree
                self.students.bind("<<TreeviewSelect>>", lambda _event: button.configure(
                    state="normal" if self.students.selection() else "disabled"
                ))
                self.students.bind("<Double-1>", self.open_student)
                self.students.bind("<Return>", self.open_student)
            elif index == 2:
                add_row_preview(page, table, headings, rows)

    def open_student(self, event=None):
        selected = self.students.selection()
        if event and event.type == tk.EventType.ButtonPress:
            row = self.students.identify_row(event.y)
            selected = (row,) if row else ()
        if not selected:
            return
        result = self.results[int(selected[0])]
        dialog = tk.Toplevel(self.root)
        dialog.title(result["candidate"])
        dialog.geometry("1120x650")
        dialog.minsize(650, 460)
        dialog.transient(self.root)
        main = ttk.Frame(dialog, padding=15)
        main.pack(fill="both", expand=True)
        status = "Завершён" if result["status"] == "completed" else "Не завершён"
        ttk.Label(main, text=f'{result["candidate"]} · {score(result)} из {len(result["answers"])} · {status}',
                  font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 10))
        version = result.get("app_version")
        version_text = version.strip() if isinstance(version, str) and version.strip() else "Не указана"
        ttk.Label(main, text=f"Версия ProSelect: {version_text}").pack(anchor="w", pady=(0, 10))
        for index, (headings, rows) in enumerate(student_details(result)):
            table = Table(main, height=min(5, max(2, len(rows))) if index == 0 else 6)
            table.pack(fill="both" if index else "x", expand=bool(index), pady=(0, 8))
            table.fill(headings, rows)
            if index == 1:
                add_row_preview(main, table, headings, rows)

    def show_warnings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Замечания при импорте")
        dialog.geometry("720x360")
        dialog.transient(self.root)
        view = tk.Text(dialog, wrap="word", padx=12, pady=12)
        scroll = ttk.Scrollbar(dialog, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        view.pack(fill="both", expand=True)
        view.insert("1.0", "\n\n".join(self.warnings))
        view.configure(state="disabled")

    def export(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Сохранить отчёт по группе",
                                            initialfile="ProSelect-отчёт.html", defaultextension=".html",
                                            filetypes=[("HTML-отчёт", "*.html")])
        if not path:
            return
        try:
            Path(path).write_text(make_report(self.folder, self.results, self.warnings), encoding="utf-8")
        except OSError as error:
            messagebox.showerror("Не удалось сохранить отчёт", str(error), parent=self.root)
        else:
            messagebox.showinfo("Отчёт сохранён", path, parent=self.root)


if __name__ == "__main__":
    root = tk.Tk()
    Analyzer(root)
    root.mainloop()
