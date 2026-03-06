import sys
import os
import csv
import re
import subprocess
import random
from collections import Counter

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtGui import QTextCursor

# Увеличиваем лимит размера поля CSV для обработки больших текстовых полей
# Устанавливаем большое значение (100MB) для поддержки очень больших полей
# Если sys.maxsize слишком большой, используем фиксированное значение
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    # Если sys.maxsize слишком большой, используем 100MB
    csv.field_size_limit(100 * 1024 * 1024)


class ValidatorThread(QtCore.QThread):
    """Фоновый поток для запуска внешних валидаторов без подвисания GUI."""

    log_signal = QtCore.pyqtSignal(str)
    finished_signal = QtCore.pyqtSignal(int, str, str)  # returncode, description, output

    def __init__(self, script_path: str, args: list[str] | None, description: str):
        super().__init__()
        self.script_path = script_path
        self.args = args or []
        self.description = description

    def run(self):
        output_lines = []
        try:
            cmd = [sys.executable, self.script_path] + self.args
            self.log_signal.emit(f"=== {self.description} ===")
            self.log_signal.emit("Запуск: " + " ".join(cmd))

            proc = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(self.script_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            if proc.stdout is not None:
                for line in proc.stdout:
                    line_stripped = line.rstrip("\n\r")
                    self.log_signal.emit(line_stripped)
                    output_lines.append(line_stripped)

            proc.wait()
            returncode = proc.returncode
        except Exception as e:
            error_msg = f"Ошибка запуска валидатора {self.description}: {e}"
            self.log_signal.emit(error_msg)
            output_lines.append(error_msg)
            returncode = -1

        output = "\n".join(output_lines)
        self.finished_signal.emit(returncode, self.description, output)


class LengthCheckThread(QtCore.QThread):
    """Фоновый поток для проверки различий в длине текста."""

    log_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(int, int)  # current, total
    finished_signal = QtCore.pyqtSignal(list)  # problems

    def __init__(self, path_a: str, path_b: str, threshold: int):
        super().__init__()
        self.path_a = path_a
        self.path_b = path_b
        self.threshold = threshold

    def run(self):
        try:
            self.log_signal.emit(f"Загрузка файла A: {self.path_a}")
            header_a, rows_a = load_tsv(self.path_a)
            
            self.log_signal.emit(f"Загрузка файла B: {self.path_b}")
            header_b, rows_b = load_tsv(self.path_b)

            id_idx_a = find_column_index(header_a, 'ID', 0)
            id_idx_b = find_column_index(header_b, 'ID', 0)
            text_idx_a = find_column_index(header_a, 'OriginalText', 1 if len(header_a) > 1 else 0)
            text_idx_b = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

            # Создаем словарь ID -> текст для файла A
            self.log_signal.emit(f"Индексация файла A ({len(rows_a)} строк)...")
            map_a = {}
            for row in rows_a:
                if len(row) > max(id_idx_a, text_idx_a):
                    row_id = row[id_idx_a]
                    text_a = row[text_idx_a] if len(row) > text_idx_a else ''
                    if row_id:
                        map_a[row_id] = text_a

            problems = []
            total = len(rows_b)
            skipped_chinese = 0
            
            self.log_signal.emit(f"Проверка различий в длине ({total} строк)...")

            for idx, row in enumerate(rows_b):
                # Обновляем прогресс каждые 1000 строк
                if idx % 1000 == 0:
                    self.progress_signal.emit(idx, total)
                
                if len(row) <= max(id_idx_b, text_idx_b):
                    continue
                
                row_id = row[id_idx_b]
                text_b = row[text_idx_b] if len(row) > text_idx_b else ''
                
                if not row_id or row_id not in map_a:
                    continue
                
                text_a = map_a[row_id]
                
                # Пропускаем пустые тексты
                if not text_a.strip() or not text_b.strip():
                    continue
                
                # Пропускаем строки с китайскими символами
                if has_chinese(text_a) or has_chinese(text_b):
                    skipped_chinese += 1
                    continue
                
                len_a = len(text_a)
                len_b = len(text_b)
                
                # Вычисляем процент различия относительно большей длины
                max_len = max(len_a, len_b)
                if max_len == 0:
                    continue
                    
                diff_percent = abs(len_a - len_b) / max_len * 100
                
                # Если различие больше порога
                if diff_percent > self.threshold:
                    problems.append({
                        'id': row_id,
                        'text_a': text_a,
                        'text_b': text_b,
                        'len_a': len_a,
                        'len_b': len_b,
                        'diff_percent': diff_percent
                    })

            self.progress_signal.emit(total, total)
            self.log_signal.emit(f"Проверка завершена. Найдено проблем: {len(problems)}")
            if skipped_chinese > 0:
                self.log_signal.emit(f"Пропущено строк с китайскими символами: {skipped_chinese}")
            self.finished_signal.emit(problems)
        except Exception as e:
            self.log_signal.emit(f"Ошибка: {e}")
            self.finished_signal.emit([])


def load_tsv(path):
    """Загрузка TSV-файла: возвращает (header, rows[list[list[str]]])."""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        # Используем стандартные настройки CSV (QUOTE_MINIMAL по умолчанию)
        # Это позволяет корректно обрабатывать кавычки и специальные символы
        reader = csv.reader(f, delimiter='\t')
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        rows = [row for row in reader]
    return header, rows


def save_tsv(path, header, rows):
    """Сохранение TSV-файла."""
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        # Используем стандартные настройки CSV (QUOTE_MINIMAL по умолчанию)
        # Это позволяет корректно обрабатывать кавычки и специальные символы
        writer = csv.writer(f, delimiter='\t')
        if header:
            writer.writerow(header)
        writer.writerows(rows)


def find_column_index(header, name, default_index=0):
    """Найти индекс колонки по имени, либо вернуть default_index."""
    try:
        return header.index(name)
    except ValueError:
        return default_index if len(header) > default_index else 0


def has_cyrillic(text):
    """Проверка, содержит ли текст кириллицу."""
    return bool(re.search(r'[А-Яа-яЁё]', text or ""))


def has_chinese(text):
    """Проверка, содержит ли текст китайские иероглифы (базовый диапазон CJK)."""
    return bool(re.search(r'[\u4e00-\u9fff]', text or ""))


def has_broken_param_ru_underscore(text):
    """
    Сломанный параметр вида: русские буквы_русские буквы,
    например: 'А_Б', 'ру_тест' и т.п.
    """
    return bool(re.search(r'[А-Яа-яЁё]+_[А-Яа-яЁё]+', text or ""))


def extract_tags(text):
    """
    Извлекает теги из текста: %s, $s, T(, #E, $link, %d, $N
    Игнорирует теги #Y (цвет), но учитывает #E как тег.
    Возвращает список найденных тегов.
    """
    if not text:
        return []
    
    tags = []
    
    # Удаляем только #Y (цвет) перед подсчетом, но оставляем #E
    text_clean = text
    
    # Ищем все теги
    # %s, %d
    tags.extend(re.findall(r'%[sd]', text_clean))
    # #h добавь так же
    tags.extend(re.findall(r'#h', text_clean))
    
    # $link (отдельный тег, ищем первым, чтобы исключить его из $s)
    link_matches = re.findall(r'\$link', text_clean)
    tags.extend(link_matches)
    
    # $s (но не те, что уже в $link)
    # Удаляем $link из текста перед поиском $s
    text_for_s = re.sub(r'\$link', '', text_clean)
    s_matches = re.findall(r'\$s', text_for_s)
    tags.extend(s_matches)
    
    # $N
    tags.extend(re.findall(r'\$N', text_clean))
    
    # T(
    tags.extend(re.findall(r'\$T\(', text_clean))
    # #E (ищем как тег)
    # tags.extend(re.findall(r'#E', text_clean))
    
    return tags


def count_braces(text):
    """
    Подсчитывает количество открывающих { и закрывающих } скобок.
    Возвращает (count_open, count_close).
    """
    if not text:
        return (0, 0)
    count_open = text.count('{')
    count_close = text.count('}')
    return (count_open, count_close)


def find_length_differences(path_a, path_b, threshold_percent=20):
    """
    Находит строки, где длина текста в B отличается от A более чем на threshold_percent процентов.
    
    Args:
        path_a: путь к файлу A (обычно английский)
        path_b: путь к файлу B (обычно русский)
        threshold_percent: порог различия в процентах (по умолчанию 20%)
    
    Returns:
        список словарей с проблемными записями
    """
    if not os.path.isfile(path_a):
        raise FileNotFoundError(f"Файл A не найден: {path_a}")
    if not os.path.isfile(path_b):
        raise FileNotFoundError(f"Файл B не найден: {path_b}")

    header_a, rows_a = load_tsv(path_a)
    header_b, rows_b = load_tsv(path_b)

    id_idx_a = find_column_index(header_a, 'ID', 0)
    id_idx_b = find_column_index(header_b, 'ID', 0)
    text_idx_a = find_column_index(header_a, 'OriginalText', 1 if len(header_a) > 1 else 0)
    text_idx_b = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

    # Создаем словарь ID -> текст для файла A
    map_a = {}
    for row in rows_a:
        if len(row) > max(id_idx_a, text_idx_a):
            row_id = row[id_idx_a]
            text_a = row[text_idx_a] if len(row) > text_idx_a else ''
            if row_id:
                map_a[row_id] = text_a

    problems = []

    for row in rows_b:
        if len(row) <= max(id_idx_b, text_idx_b):
            continue
        
        row_id = row[id_idx_b]
        text_b = row[text_idx_b] if len(row) > text_idx_b else ''
        
        if not row_id or row_id not in map_a:
            continue
        
        text_a = map_a[row_id]
        
        # Пропускаем пустые тексты
        if not text_a.strip() or not text_b.strip():
            continue
        
        len_a = len(text_a)
        len_b = len(text_b)
        
        # Вычисляем процент различия относительно большей длины
        max_len = max(len_a, len_b)
        if max_len == 0:
            continue
            
        diff_percent = abs(len_a - len_b) / max_len * 100
        
        # Если различие больше порога
        if diff_percent > threshold_percent:
            problems.append({
                'id': row_id,
                'text_a': text_a,
                'text_b': text_b,
                'len_a': len_a,
                'len_b': len_b,
                'diff_percent': diff_percent
            })
    
    return problems


def find_tag_differences(path_a, path_b):
    """
    Находит различия в тегах между файлами A и B.
    Проверяет наличие тегов: %s, $s, T(, #E, $link, %d
    Проверяет количество фигурных скобок { и }.
    Возвращает список строк (ID, текст_A, текст_B, проблема) с проблемными записями.
    """
    if not os.path.isfile(path_a):
        raise FileNotFoundError(f"Файл A не найден: {path_a}")
    if not os.path.isfile(path_b):
        raise FileNotFoundError(f"Файл B не найден: {path_b}")

    header_a, rows_a = load_tsv(path_a)
    header_b, rows_b = load_tsv(path_b)

    id_idx_a = find_column_index(header_a, 'ID', 0)
    id_idx_b = find_column_index(header_b, 'ID', 0)
    text_idx_a = find_column_index(header_a, 'OriginalText', 1 if len(header_a) > 1 else 0)
    text_idx_b = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

    # Создаем словарь ID -> текст для файла A
    map_a = {}
    for row in rows_a:
        if len(row) > max(id_idx_a, text_idx_a):
            row_id = row[id_idx_a]
            text_a = row[text_idx_a] if len(row) > text_idx_a else ''
            if row_id:
                map_a[row_id] = text_a

    problems = []

    for row in rows_b:
        if len(row) <= max(id_idx_b, text_idx_b):
            continue
        
        row_id = row[id_idx_b]
        text_b = row[text_idx_b] if len(row) > text_idx_b else ''
        
        if not row_id or row_id not in map_a:
            continue
        
        text_a = map_a[row_id]
        
        # Извлекаем теги из обоих текстов
        tags_a = extract_tags(text_a)
        tags_b = extract_tags(text_b)
        
        # Подсчитываем теги
        tags_count_a = Counter(tags_a)
        tags_count_b = Counter(tags_b)
        
        # Проверяем различия в тегах
        issues = []
        
        # Проверяем каждый тип тега
        for tag in tags_count_a:
            count_a = tags_count_a[tag]
            count_b = tags_count_b.get(tag, 0)
            if count_b < count_a:
                issues.append(f"Не хватает тега '{tag}': в A={count_a}, в B={count_b}")
        
        # Проверяем фигурные скобки
        braces_a = count_braces(text_a)
        braces_b = count_braces(text_b)
        
        if braces_a[0] != braces_b[0] or braces_a[1] != braces_b[1]:
            issues.append(
                f"Несоответствие фигурных скобок: "
                f"в A {{={braces_a[0]}, }}={braces_a[1]}, "
                f"в B {{={braces_b[0]}, }}={braces_b[1]}"
            )
        
        if issues:
            problems.append({
                'id': row_id,
                'text_a': text_a,
                'text_b': text_b,
                'issues': issues
            })
    
    return problems


def create_fixed_tsv(path_b, problems, output_path):
    """
    Создает файл _fixed.tsv из файла B с проблемными строками.
    """
    if not os.path.isfile(path_b):
        raise FileNotFoundError(f"Файл B не найден: {path_b}")
    
    header_b, rows_b = load_tsv(path_b)
    id_idx_b = find_column_index(header_b, 'ID', 0)
    
    # Создаем множество ID с проблемами
    problem_ids = {p['id'] for p in problems}
    
    # Фильтруем строки с проблемными ID
    fixed_rows = []
    for row in rows_b:
        if len(row) > id_idx_b:
            row_id = row[id_idx_b]
            if row_id in problem_ids:
                fixed_rows.append(row)
    
    # Сохраняем в файл
    save_tsv(output_path, header_b, fixed_rows)
    return len(fixed_rows)


def transfer_new_ids(path_a, path_b):
    """
    Переносит строки с новыми ID из A в B.
    Возвращает количество добавленных строк.
    """
    if not os.path.isfile(path_a):
        raise FileNotFoundError(f"Файл A не найден: {path_a}")
    if not os.path.isfile(path_b):
        raise FileNotFoundError(f"Файл B не найден: {path_b}")

    header_a, rows_a = load_tsv(path_a)
    header_b, rows_b = load_tsv(path_b)

    # Определяем индексы ID
    id_idx_a = find_column_index(header_a, 'ID', 0)
    id_idx_b = find_column_index(header_b, 'ID', 0)

    # Множество ID из B
    ids_b = set()
    for row in rows_b:
        if len(row) > id_idx_b:
            ids_b.add(row[id_idx_b])

    added = 0
    # Используем header B, если он есть, иначе header A
    target_header = header_b if header_b else header_a

    # Выравниваем количество колонок в строках к длине target_header
    def normalize_row(row, size):
        if len(row) < size:
            return row + [''] * (size - len(row))
        elif len(row) > size:
            return row[:size]
        return row

    size = len(target_header)

    # Перебираем строки из A, добавляем, если ID новый
    for row in rows_a:
        if len(row) <= id_idx_a:
            continue
        row_id = row[id_idx_a]
        if row_id not in ids_b:
            normalized = normalize_row(row, size)
            rows_b.append(normalized)
            ids_b.add(row_id)
            added += 1

    # Сохраняем обратно в B
    save_tsv(path_b, target_header, rows_b)
    return added


def remove_duplicates_in_b(path_b):
    """
    Удаляет дубли по ID в файле B.
    Приоритет: оставить строку С КИРИЛЛИЦЕЙ (русский), удалить без кириллицы (английский).
    Если все с кириллицей или все без — оставить первую, остальные удалить.

    Возвращает количество удалённых строк.
    """
    if not os.path.isfile(path_b):
        raise FileNotFoundError(f"Файл B не найден: {path_b}")

    header_b, rows_b = load_tsv(path_b)
    if not rows_b:
        return 0

    id_idx = find_column_index(header_b, 'ID', 0)
    text_idx = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

    seen = {}  # ID -> (best_row, has_cyrillic_best)
    original_count = len(rows_b)

    for row in rows_b:
        if len(row) <= id_idx:
            # Строка без ID — можно либо пропустить, либо считать отдельной.
            # Считаем "ID" пустой строкой.
            row_id = ''
        else:
            row_id = row[id_idx]

        text = row[text_idx] if len(row) > text_idx else ''
        cyr = has_cyrillic(text)

        if row_id not in seen:
            seen[row_id] = (row, cyr)
        else:
            best_row, best_cyr = seen[row_id]
            # Если текущий с кириллицей, а лучший без кириллицы — заменяем
            if (not best_cyr) and cyr:
                seen[row_id] = (row, cyr)
            # Иначе оставляем как есть (приоритета нет)

    # Результирующие строки в порядке первого появления ID
    result_rows = [value[0] for value in seen.values()]
    removed = original_count - len(result_rows)

    save_tsv(path_b, header_b, result_rows)
    return removed


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("TSV мультитул v0.0.2")
        self.resize(700, 300)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        layout = QtWidgets.QVBoxLayout(central)

        # Блок выбора файлов A и B
        file_layout = QtWidgets.QGridLayout()

        self.edit_a = QtWidgets.QLineEdit()
        self.btn_browse_a = QtWidgets.QPushButton("Обзор A...")
        self.btn_browse_a.clicked.connect(self.browse_a)

        self.edit_b = QtWidgets.QLineEdit()
        self.btn_browse_b = QtWidgets.QPushButton("Обзор B...")
        self.btn_browse_b.clicked.connect(self.browse_b)

        file_layout.addWidget(QtWidgets.QLabel("Файл A (источник):"), 0, 0)
        file_layout.addWidget(self.edit_a, 0, 1)
        file_layout.addWidget(self.btn_browse_a, 0, 2)

        file_layout.addWidget(QtWidgets.QLabel("Файл B (приёмник):"), 1, 0)
        file_layout.addWidget(self.edit_b, 1, 1)
        file_layout.addWidget(self.btn_browse_b, 1, 2)

        layout.addLayout(file_layout)

        # Кнопки действий
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_transfer = QtWidgets.QPushButton("1. Перенести новые ID из A в B")
        self.btn_transfer.clicked.connect(self.handle_transfer)

        self.btn_replace_fields = QtWidgets.QPushButton("1a. Заменить поля с A в B")
        self.btn_replace_fields.clicked.connect(self.handle_replace_fields)

        self.btn_remove_dups = QtWidgets.QPushButton("2. Удалить дубли по ID в B")
        self.btn_remove_dups.clicked.connect(self.handle_remove_dups)

        btn_layout.addWidget(self.btn_transfer)
        btn_layout.addWidget(self.btn_replace_fields)
        btn_layout.addWidget(self.btn_remove_dups)

        layout.addLayout(btn_layout)

        # Дополнительные кнопки: валидация TSV, поиск китайских символов и теги для файла B
        validate_layout = QtWidgets.QHBoxLayout()
        self.btn_validate_tsv = QtWidgets.QPushButton("3. Проверить TSV B (формат)")
        self.btn_validate_tsv.clicked.connect(self.handle_validate_tsv)

        self.btn_find_cn = QtWidgets.QPushButton("4. Найти китайские ID в B")
        self.btn_find_cn.clicked.connect(self.handle_find_chinese_in_b)

        self.btn_validate_tags = QtWidgets.QPushButton("5. Проверить теги в B")
        self.btn_validate_tags.clicked.connect(self.handle_validate_tags)

        self.btn_find_broken_params = QtWidgets.QPushButton("6. Сломанные параметры (RU_RU с _)")
        self.btn_find_broken_params.clicked.connect(self.handle_find_broken_params)

        self.btn_find_tag_differences = QtWidgets.QPushButton("7. Поиск различий тегов (A vs B)")
        self.btn_find_tag_differences.clicked.connect(self.handle_find_tag_differences)

        self.btn_find_length_differences = QtWidgets.QPushButton("8. Поиск различий в длине текста (A vs B)")
        self.btn_find_length_differences.clicked.connect(self.handle_find_length_differences)

        validate_layout.addWidget(self.btn_validate_tsv)
        validate_layout.addWidget(self.btn_find_cn)
        validate_layout.addWidget(self.btn_validate_tags)
        validate_layout.addWidget(self.btn_find_broken_params)
        validate_layout.addWidget(self.btn_find_tag_differences)
        validate_layout.addWidget(self.btn_find_length_differences)

        layout.addLayout(validate_layout)

        # Небольшой разделитель
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout.addWidget(separator)

        # Блок операций по тексту в файле B
        text_ops_layout = QtWidgets.QVBoxLayout()

        text_filter_layout = QtWidgets.QHBoxLayout()
        text_filter_layout.addWidget(QtWidgets.QLabel("Фрагмент текста для поиска в B (OriginalText):"))
        self.edit_text_filter = QtWidgets.QLineEdit()
        text_filter_layout.addWidget(self.edit_text_filter)
        text_ops_layout.addLayout(text_filter_layout)

        text_btns_layout = QtWidgets.QHBoxLayout()
        self.btn_find_ids_by_text = QtWidgets.QPushButton("Найти ID по тексту (B)")
        self.btn_find_ids_by_text.clicked.connect(self.handle_find_ids_by_text)

        self.btn_delete_by_text = QtWidgets.QPushButton("Удалить строки по тексту (B)")
        self.btn_delete_by_text.clicked.connect(self.handle_delete_by_text)

        self.btn_replace_by_text = QtWidgets.QPushButton("Заменить из A строки по тексту (B)")
        self.btn_replace_by_text.clicked.connect(self.handle_replace_by_text)

        self.btn_cut_by_text = QtWidgets.QPushButton("Вырезать строки по тексту в select_*.tsv")
        self.btn_cut_by_text.clicked.connect(self.handle_cut_by_text)

        text_btns_layout.addWidget(self.btn_find_ids_by_text)
        text_btns_layout.addWidget(self.btn_delete_by_text)
        text_btns_layout.addWidget(self.btn_replace_by_text)
        text_btns_layout.addWidget(self.btn_cut_by_text)

        text_ops_layout.addLayout(text_btns_layout)

        # Кнопка создания debug_*.tsv с UUID-тегами в начале текста
        debug_btn_layout = QtWidgets.QHBoxLayout()
        self.btn_create_debug_tsv = QtWidgets.QPushButton("Создать debug_*.tsv с [UUID] в тексте (B)")
        self.btn_create_debug_tsv.clicked.connect(self.handle_create_debug_tsv)
        debug_btn_layout.addWidget(self.btn_create_debug_tsv)
        debug_btn_layout.addStretch(1)
        text_ops_layout.addLayout(debug_btn_layout)

        layout.addLayout(text_ops_layout)

        # Лог
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)

        # Кнопка очистки лога
        clear_layout = QtWidgets.QHBoxLayout()
        self.btn_clear_log = QtWidgets.QPushButton("Очистить лог")
        self.btn_clear_log.clicked.connect(self.handle_clear_log)
        clear_layout.addStretch(1)
        clear_layout.addWidget(self.btn_clear_log)

        layout.addWidget(self.log)
        layout.addLayout(clear_layout)

        # Текущий поток-валидатор (чтобы не собрать GC)
        self.validator_thread: ValidatorThread | None = None
        self.length_check_thread: LengthCheckThread | None = None
        
        # Прогресс-бар для длительных операций
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

    def browse_a(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выберите TSV-файл A (источник)",
            "",
            "TSV files (*.tsv);;All files (*.*)"
        )
        if path:
            self.edit_a.setText(path)

    def browse_b(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выберите TSV-файл B (приёмник)",
            "",
            "TSV files (*.tsv);;All files (*.*)"
        )
        if path:
            self.edit_b.setText(path)

    def append_log(self, text):
        self.log.append(text)
        self.log.moveCursor(QTextCursor.End)

    def handle_transfer(self):
        path_a = self.edit_a.text().strip()
        path_b = self.edit_b.text().strip()

        if not path_a or not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите пути к файлам A и B.")
            return

        try:
            added = transfer_new_ids(path_a, path_b)
            msg = f"Перенос завершён. Добавлено строк: {added}."
            QtWidgets.QMessageBox.information(self, "Готово", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка переноса: {e}")

    def handle_remove_dups(self):
        """
        Поиск дублей по ID в B с последующим предложением удалить их.
        1) Сначала ищет все ID, у которых больше одной строки, и выводит их в лог.
        2) Затем предлагает автоматически удалить лишние дубликаты
           (оставляя по одной строке на ID, с приоритетом строк с кириллицей —
            логика та же, что и в remove_duplicates_in_b).
        """
        path_b = self.edit_b.text().strip()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            header_b, rows_b = load_tsv(path_b)
            if not rows_b:
                msg = "Файл B пуст или без данных. Дубликатов нет."
                QtWidgets.QMessageBox.information(self, "Дубликаты", msg)
                self.append_log(msg)
                return

            id_idx = find_column_index(header_b, 'ID', 0)

            # Подсчитываем количество строк на каждый ID
            id_counts: dict[str, int] = {}
            for row in rows_b:
                if len(row) <= id_idx:
                    row_id = ''
                else:
                    row_id = row[id_idx]
                id_counts[row_id] = id_counts.get(row_id, 0) + 1

            # ID, у которых больше одной строки
            duplicate_ids = [rid for rid, cnt in id_counts.items() if cnt > 1]
            total_dup_ids = len(duplicate_ids)
            total_dup_rows = sum(cnt - 1 for cnt in id_counts.values() if cnt > 1)

            if total_dup_ids == 0:
                msg = "Дубликаты по ID в файле B не найдены."
                QtWidgets.QMessageBox.information(self, "Дубликаты", msg)
                self.append_log(msg)
                return

            msg_header = (
                f"Найдено ID с дубликатами: {total_dup_ids}. "
                f"Всего лишних строк (кроме первой на каждый ID): {total_dup_rows}."
            )
            self.append_log(msg_header)

            # Выводим в лог список всех дублей
            for rid in sorted(duplicate_ids):
                self.append_log(f"ID (DUP): {rid!r} — всего строк: {id_counts[rid]}")

            # Спрашиваем, нужно ли удалить лишние дубликаты автоматически
            reply = QtWidgets.QMessageBox.question(
                self,
                "Дубликаты",
                (
                    f"{msg_header}\n\n"
                    f"Удалить автоматически лишние дубликаты по ID?\n"
                    f"Будет оставлена по одной строке на каждый ID, "
                    f"с приоритетом строк с кириллицей (как в remove_duplicates_in_b)."
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )

            if reply != QtWidgets.QMessageBox.Yes:
                cancel_msg = "Удаление дублей отменено пользователем. Ничего не изменено."
                QtWidgets.QMessageBox.information(self, "Дубликаты", cancel_msg)
                self.append_log(cancel_msg)
                return

            # Выполняем фактическое удаление дублей с использованием существующей логики
            removed = remove_duplicates_in_b(path_b)
            msg = f"Удаление дублей завершено. Удалено строк: {removed}."
            QtWidgets.QMessageBox.information(self, "Готово", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка поиска/удаления дублей: {e}")

    def handle_replace_fields(self):
        """
        Полная замена строк в B данными из A по совпадению ID.
        Перед выполнением спрашивает подтверждение.
        """
        path_a = self.edit_a.text().strip()
        path_b = self.edit_b.text().strip()

        if not path_a or not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите пути к файлам A и B.")
            return
        if not os.path.isfile(path_a):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл A не найден: {path_a}")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            header_a, rows_a = load_tsv(path_a)
            header_b, rows_b = load_tsv(path_b)

            if not rows_b:
                msg = "Файл B пуст или без данных. Замена не требуется."
                QtWidgets.QMessageBox.information(self, "Замена полей", msg)
                self.append_log(msg)
                return

            id_idx_a = find_column_index(header_a, 'ID', 0)
            id_idx_b = find_column_index(header_b, 'ID', 0)
            size_b = len(header_b)

            def normalize_row(row):
                """Подгоняем строку под длину header B."""
                if len(row) < size_b:
                    return row + [''] * (size_b - len(row))
                elif len(row) > size_b:
                    return row[:size_b]
                return row

            map_a = {}
            for row in rows_a:
                if len(row) > id_idx_a:
                    rid = row[id_idx_a]
                    if rid:
                        map_a[rid] = row

            new_rows = []
            replaced = 0
            changed_indices = []  # Индексы строк, которые действительно изменились

            for idx, row in enumerate(rows_b):
                if len(row) > id_idx_b:
                    rid = row[id_idx_b]
                    if rid in map_a:
                        old_row_normalized = normalize_row(row)
                        new_row_normalized = normalize_row(map_a[rid])
                        
                        # Сравниваем старую и новую строки
                        if old_row_normalized != new_row_normalized:
                            # Строка действительно изменилась
                            changed_indices.append(idx)
                        
                        new_rows.append(new_row_normalized)
                        replaced += 1
                        continue
                new_rows.append(row)

            if replaced == 0:
                msg = "В B нет ID, которые присутствуют в A. Замена не выполнена."
                QtWidgets.QMessageBox.information(self, "Замена полей", msg)
                self.append_log(msg)
                return

            confirm_msg = (
                f"Найдено совпадающих ID: {replaced}.\n"
                f"Заменить соответствующие строки в B данными из A?"
            )
            reply = QtWidgets.QMessageBox.question(
                self,
                "Подтверждение замены",
                confirm_msg,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )

            if reply != QtWidgets.QMessageBox.Yes:
                self.append_log("Замена полей отменена пользователем.")
                return

            # Предлагаем переместить только те строки, которые действительно изменились
            if changed_indices:
                changed_count = len(changed_indices)
                unchanged_count = replaced - changed_count
                
                move_msg = (
                    f"Заменено строк: {replaced}.\n"
                    f"Из них изменились: {changed_count}.\n"
                    f"Не изменились: {unchanged_count}.\n\n"
                    f"Хотите переместить измененные строки ({changed_count}) в конец файла?\n"
                    f"Если нет, они останутся на своих местах."
                )
                
                move_reply = QtWidgets.QMessageBox.question(
                    self,
                    "Перемещение измененных строк",
                    move_msg,
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )

                if move_reply == QtWidgets.QMessageBox.Yes:
                    # Разделяем на две группы: не измененные и измененные
                    changed_set = set(changed_indices)
                    kept_rows = []
                    changed_rows = []
                    
                    for idx, row in enumerate(new_rows):
                        if idx in changed_set:
                            changed_rows.append(row)
                        else:
                            kept_rows.append(row)
                    
                    # Собираем: сначала не измененные, потом измененные
                    new_rows = kept_rows + changed_rows
                    move_msg = f"Измененные строки ({changed_count}) перемещены в конец файла."
                    self.append_log(move_msg)
            else:
                # Все замененные строки остались такими же
                self.append_log(f"Все замененные строки ({replaced}) остались без изменений. Перемещение не требуется.")

            save_tsv(path_b, header_b, new_rows)
            msg = f"Замена завершена. Обновлено строк: {replaced}."
            QtWidgets.QMessageBox.information(self, "Замена полей", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка замены полей: {e}")

    def handle_clear_log(self):
        """Очистка окна лога."""
        self.log.clear()

    # Запуск внешних валидаторов (из репозитория wwm_russian/.github/scripts) в фоне
    def run_validator_script(self, script_relative_path, args=None, description=""):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            repo_root = os.path.abspath(os.path.join(base_dir, "..", ".."))

            # Если передан абсолютный путь — используем его, иначе собираем из .github/scripts
            if os.path.isabs(script_relative_path):
                script_path = script_relative_path
            else:
                script_path = os.path.join(repo_root, ".github", "scripts", script_relative_path)

            if not os.path.isfile(script_path):
                raise FileNotFoundError(f"Скрипт валидатора не найден: {script_path}")

            name = description or os.path.basename(script_path)

            # Если предыдущий поток ещё жив – можно либо дождаться, либо просто запустить новый.
            # Проще: не даём запускать второй валидатор параллельно.
            if self.validator_thread is not None and self.validator_thread.isRunning():
                QtWidgets.QMessageBox.warning(
                    self,
                    "Валидатор",
                    "Другой валидатор ещё выполняется. Дождитесь завершения.",
                )
                return

            self.validator_thread = ValidatorThread(script_path, args, name)
            self.validator_thread.log_signal.connect(self.append_log)
            self.validator_thread.finished_signal.connect(self.on_validator_finished)
            self.validator_thread.start()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка валидатора", str(e))
            self.append_log(f"Ошибка запуска валидатора {description or script_relative_path}: {e}")

    def on_validator_finished(self, returncode: int, description: str, output: str):
        if returncode == 0:
            QtWidgets.QMessageBox.information(
                self,
                "Валидатор",
                f"{description} завершился успешно (код 0).",
            )
        else:
            # Парсим вывод для извлечения ID сломанных строк (только для validate_tsv.py)
            broken_ids = []
            is_tsv_validator = "validate_tsv.py" in description or "Проверка TSV" in description
            
            if is_tsv_validator:
                broken_ids = self._parse_broken_ids_from_output(output)
            
            if broken_ids:
                # Предлагаем удалить сломанные строки
                ids_preview = "\n".join(sorted(broken_ids)[:10])
                if len(broken_ids) > 10:
                    ids_preview += f"\n... и ещё {len(broken_ids) - 10}"
                
                reply = QtWidgets.QMessageBox.question(
                    self,
                    "Сломанные строки",
                    (
                        f"Найдено {len(broken_ids)} сломанных строк с ошибками.\n\n"
                        f"Удалить эти строки из файла B?\n\n"
                        f"ID сломанных строк:\n{ids_preview}"
                    ),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No,
                )
                
                if reply == QtWidgets.QMessageBox.Yes:
                    self._remove_broken_lines_by_ids(broken_ids)
                else:
                    # Показываем стандартное предупреждение, если пользователь отказался
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Валидатор",
                        f"{description} завершился с кодом {returncode}. Подробности см. в логе.",
                    )
            else:
                # Нет сломанных строк для удаления, показываем стандартное предупреждение
                QtWidgets.QMessageBox.warning(
                    self,
                    "Валидатор",
                    f"{description} завершился с кодом {returncode}. Подробности см. в логе.",
                )
    
    def _parse_broken_ids_from_output(self, output: str) -> list[str]:
        """Извлекает ID сломанных строк из вывода валидатора."""
        broken_ids = []
        lines = output.split('\n')
        in_broken_section = False
        
        for line in lines:
            line = line.strip()
            if line == "🔧 BROKEN_IDS_START":
                in_broken_section = True
                continue
            elif line == "🔧 BROKEN_IDS_END":
                break
            elif in_broken_section and line:
                # Проверяем, что это валидный ID (16 hex символов)
                if len(line) == 16 and all(c in '0123456789abcdefABCDEF' for c in line):
                    broken_ids.append(line)
        
        return broken_ids
    
    def _remove_broken_lines_by_ids(self, broken_ids: list[str]):
        """Удаляет строки с указанными ID из файла B."""
        path_b = self.edit_b.text().strip()
        
        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return
        
        try:
            header_b, rows_b = load_tsv(path_b)
            if not rows_b:
                QtWidgets.QMessageBox.information(self, "Результат", "Файл B пуст или без данных.")
                return
            
            id_idx = find_column_index(header_b, 'ID', 0)
            broken_set = set(broken_ids)
            
            original_count = len(rows_b)
            kept_rows = []
            removed_count = 0
            
            for row in rows_b:
                if len(row) > id_idx:
                    row_id = row[id_idx]
                    if row_id in broken_set:
                        removed_count += 1
                        continue
                kept_rows.append(row)
            
            if removed_count == 0:
                QtWidgets.QMessageBox.information(
                    self, 
                    "Удаление", 
                    "Не найдено строк с указанными ID для удаления."
                )
                return
            
            save_tsv(path_b, header_b, kept_rows)
            msg = (
                f"Удаление сломанных строк завершено.\n"
                f"Удалено строк: {removed_count} из {original_count}.\n"
                f"Осталось строк: {len(kept_rows)}."
            )
            QtWidgets.QMessageBox.information(self, "Удаление строк", msg)
            self.append_log(f"Удалено сломанных строк: {removed_count}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка удаления сломанных строк: {e}")

    def handle_validate_tsv(self):
        path_b = self.edit_b.text().strip()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return

        # validate_tsv.py принимает путь к файлу как аргумент
        self.run_validator_script(
            "validate_tsv.py",
            args=[path_b],
            description="Проверка TSV B (validate_tsv.py)",
        )

    def handle_validate_tags(self):
        """
        Запуск validate_tags.py.
        Скрипт сам берёт translation_ru.tsv / translation_en.tsv из папки wwm_russian,
        так что имеет смысл использовать его, когда файл B — это translation_ru.tsv.
        """
        self.run_validator_script(
            "validate_tags.py",
            description="Проверка тегов (validate_tags.py)",
        )

    def handle_find_chinese_in_b(self):
        """
        Поиск строк с китайскими иероглифами в файле B.
        Выводит в лог ID (и при желании можно расширить до текста).
        После нахождения предлагает переместить их в конец файла.
        """
        path_b = self.edit_b.text().strip()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            header_b, rows_b = load_tsv(path_b)
            if not rows_b:
                QtWidgets.QMessageBox.information(self, "Результат", "Файл B пуст или без данных.")
                return

            id_idx = find_column_index(header_b, 'ID', 0)
            text_idx = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

            total = 0
            ids = []
            chinese_indices = []

            for idx, row in enumerate(rows_b):
                if len(row) <= max(id_idx, text_idx):
                    continue
                text = row[text_idx]
                if has_chinese(text):
                    total += 1
                    row_id = row[id_idx] if len(row) > id_idx else ''
                    ids.append((row_id, text))
                    chinese_indices.append(idx)

            if total == 0:
                msg = "Китайские символы в файле B не найдены."
                QtWidgets.QMessageBox.information(self, "Поиск китайских символов", msg)
                self.append_log(msg)
                return

            msg = (
                f"Найдено строк с китайскими символами: {total}. "
                f"ID выведены ниже."
            )

            self.append_log(msg)
            for rid, text in ids:
                # Показываем небольшой фрагмент текста для наглядности
                snippet = text
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                self.append_log(f"ID (CN): {rid} — {snippet}")

            # Спрашиваем, нужно ли переместить все такие строки в конец файла B
            reply = QtWidgets.QMessageBox.question(
                self,
                "Китайские символы",
                (
                    f"{msg}\n\n"
                    f"Переместить все эти строки (кол-во: {total}) в конец файла B?\n"
                    f"Порядок внутри группы будет сохранён."
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )

            if reply == QtWidgets.QMessageBox.Yes:
                # Сохраняем порядок: сначала все нормальные строки, потом с китайскими символами
                chinese_set = set(chinese_indices)
                kept_rows = [row for i, row in enumerate(rows_b) if i not in chinese_set]
                chinese_rows = [rows_b[i] for i in chinese_indices]
                new_rows = kept_rows + chinese_rows

                save_tsv(path_b, header_b, new_rows)
                move_msg = (
                    f"Строки с китайскими символами перемещены в конец файла B. "
                    f"Всего перемещено: {total}."
                )
                self.append_log(move_msg)
                QtWidgets.QMessageBox.information(self, "Китайские символы", move_msg)
            else:
                QtWidgets.QMessageBox.information(self, "Китайские символы", msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка поиска китайских символов: {e}")

    def handle_find_broken_params(self):
        """
        Поиск "сломанных параметров" в файле B:
        русские_русские (буквы с обеих сторон от подчёркивания).
        Выводит ID таких строк.
        """
        path_b = self.edit_b.text().strip()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            header_b, rows_b = load_tsv(path_b)
            if not rows_b:
                QtWidgets.QMessageBox.information(self, "Результат", "Файл B пуст или без данных.")
                return

            id_idx = find_column_index(header_b, 'ID', 0)
            text_idx = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

            total = 0
            ids = []
            broken_indices = []

            for idx, row in enumerate(rows_b):
                if len(row) <= max(id_idx, text_idx):
                    continue
                text = row[text_idx]
                if has_broken_param_ru_underscore(text):
                    total += 1
                    row_id = row[id_idx] if len(row) > id_idx else ''
                    ids.append((row_id, text))
                    broken_indices.append(idx)

            if total == 0:
                msg = "Сломанные параметры (РУ_РУ) в файле B не найдены."
                QtWidgets.QMessageBox.information(self, "Сломанные параметры", msg)
                self.append_log(msg)
                return

            msg = (
                f"Найдено строк со сломанными параметрами (РУ_РУ с подчёркиванием): {total}. "
                f"ID выведены ниже."
            )

            self.append_log(msg)
            for rid, text in ids:
                # Показываем небольшой фрагмент текста для наглядности
                snippet = text
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                self.append_log(f"ID (BROKEN_PARAM): {rid} — {snippet}")

            # Спрашиваем, нужно ли переместить все такие строки в конец файла B
            reply = QtWidgets.QMessageBox.question(
                self,
                "Сломанные параметры",
                (
                    f"{msg}\n\n"
                    f"Переместить все эти строки (кол-во: {total}) в конец файла B?\n"
                    f"Порядок внутри группы будет сохранён."
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )

            if reply == QtWidgets.QMessageBox.Yes:
                # Сохраняем порядок: сначала все нормальные строки, потом сломанные
                broken_set = set(broken_indices)
                kept_rows = [row for i, row in enumerate(rows_b) if i not in broken_set]
                broken_rows = [rows_b[i] for i in broken_indices]
                new_rows = kept_rows + broken_rows

                save_tsv(path_b, header_b, new_rows)
                move_msg = (
                    f"Строки со сломанными параметрами перемещены в конец файла B. "
                    f"Всего перемещено: {total}."
                )
                self.append_log(move_msg)
                QtWidgets.QMessageBox.information(self, "Сломанные параметры", move_msg)
            else:
                QtWidgets.QMessageBox.information(self, "Сломанные параметры", msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка поиска сломанных параметров: {e}")

    def handle_find_tag_differences(self):
        """
        Поиск различий тегов между файлами A и B.
        Проверяет наличие тегов: %s, $s, T(, #E, $link, %d
        Проверяет количество фигурных скобок { и }.
        Создает файл _fixed.tsv с проблемными строками.
        """
        path_a = self.edit_a.text().strip()
        path_b = self.edit_b.text().strip()

        if not path_a or not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите пути к файлам A и B.")
            return
        if not os.path.isfile(path_a):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл A не найден: {path_a}")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            self.append_log("=== Поиск различий тегов между A и B ===")
            problems = find_tag_differences(path_a, path_b)

            if not problems:
                msg = "Различий в тегах между файлами A и B не найдено."
                QtWidgets.QMessageBox.information(self, "Различия тегов", msg)
                self.append_log(msg)
                return

            msg = (
                f"Найдено строк с различиями в тегах: {len(problems)}. "
                f"Детали выведены ниже."
            )
            self.append_log(msg)

            # Выводим детали проблем
            for p in problems:
                self.append_log(f"\nID: {p['id']}")
                self.append_log(f"  A: {p['text_a'][:100]}{'...' if len(p['text_a']) > 100 else ''}")
                self.append_log(f"  B: {p['text_b'][:100]}{'...' if len(p['text_b']) > 100 else ''}")
                for issue in p['issues']:
                    self.append_log(f"  ⚠ {issue}")

            # Создаем файл _fixed.tsv
            b_dir = os.path.dirname(path_b)
            b_name = os.path.basename(path_b)
            b_name_no_ext = os.path.splitext(b_name)[0]
            output_path = os.path.join(b_dir, f"{b_name_no_ext}_fixed.tsv")

            fixed_count = create_fixed_tsv(path_b, problems, output_path)

            result_msg = (
                f"Найдено проблемных строк: {len(problems)}.\n"
                f"Создан файл: {output_path}\n"
                f"Строк в файле: {fixed_count}."
            )

            QtWidgets.QMessageBox.information(self, "Различия тегов", result_msg)
            self.append_log(f"\n{result_msg}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка поиска различий тегов: {e}")

    def handle_find_length_differences(self):
        """
        Поиск строк с большим различием в длине текста между файлами A и B.
        Помогает найти случаи, когда перевод явно некорректный (например, длинный текст заменён на короткое слово).
        """
        path_a = self.edit_a.text().strip()
        path_b = self.edit_b.text().strip()

        if not path_a or not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите пути к файлам A и B.")
            return
        if not os.path.isfile(path_a):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл A не найден: {path_a}")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        # Проверяем, не запущен ли уже другой поток
        if self.length_check_thread is not None and self.length_check_thread.isRunning():
            QtWidgets.QMessageBox.warning(
                self,
                "Проверка",
                "Проверка уже выполняется. Дождитесь завершения.",
            )
            return

        # Спрашиваем порог различия
        threshold, ok = QtWidgets.QInputDialog.getInt(
            self,
            "Порог различия",
            "Введите порог различия в процентах (рекомендуется 20-30%):",
            value=20,
            min=1,
            max=100,
            step=5
        )
        
        if not ok:
            return

        # Запускаем проверку в фоновом потоке
        self.append_log(f"=== Поиск различий в длине текста (порог: {threshold}%) ===")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Отключаем кнопки на время проверки
        self.btn_find_length_differences.setEnabled(False)
        
        self.length_check_thread = LengthCheckThread(path_a, path_b, threshold)
        self.length_check_thread.log_signal.connect(self.append_log)
        self.length_check_thread.progress_signal.connect(self.on_length_check_progress)
        self.length_check_thread.finished_signal.connect(self.on_length_check_finished)
        self.length_check_thread.start()

    def on_length_check_progress(self, current: int, total: int):
        """Обновление прогресс-бара."""
        if total > 0:
            percent = int(current * 100 / total)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"Обработано: {current}/{total} ({percent}%)")

    def on_length_check_finished(self, problems: list):
        """Обработка результатов проверки длины."""
        self.progress_bar.setVisible(False)
        self.btn_find_length_differences.setEnabled(True)
        
        path_b = self.edit_b.text().strip()
        threshold = self.length_check_thread.threshold if self.length_check_thread else 20

        if not problems:
            msg = f"Строк с различием в длине более {threshold}% не найдено."
            QtWidgets.QMessageBox.information(self, "Различия в длине", msg)
            self.append_log(msg)
            return

        try:
            # Сортируем по проценту различия (от большего к меньшему)
            problems.sort(key=lambda x: x['diff_percent'], reverse=True)

            msg = (
                f"Найдено строк с различием в длине более {threshold}%: {len(problems)}. "
                f"Детали выведены ниже."
            )
            self.append_log(msg)

            # Выводим детали проблем (ограничиваем вывод первыми 100 для производительности)
            for i, p in enumerate(problems[:100]):
                self.append_log(f"\nID: {p['id']}")
                self.append_log(f"  Длина A: {p['len_a']}, Длина B: {p['len_b']}, Различие: {p['diff_percent']:.1f}%")
                self.append_log(f"  A: {p['text_a'][:100]}{'...' if len(p['text_a']) > 100 else ''}")
                self.append_log(f"  B: {p['text_b'][:100]}{'...' if len(p['text_b']) > 100 else ''}")
            
            if len(problems) > 100:
                self.append_log(f"\n... и ещё {len(problems) - 100} строк (не выведены для экономии места)")

            # Создаем файл _length_diff.tsv
            b_dir = os.path.dirname(path_b)
            b_name = os.path.basename(path_b)
            b_name_no_ext = os.path.splitext(b_name)[0]
            output_path = os.path.join(b_dir, f"{b_name_no_ext}_length_diff.tsv")

            # Создаём TSV с проблемными строками
            header_b, rows_b = load_tsv(path_b)
            id_idx_b = find_column_index(header_b, 'ID', 0)
            
            problem_ids = {p['id'] for p in problems}
            fixed_rows = []
            for row in rows_b:
                if len(row) > id_idx_b:
                    row_id = row[id_idx_b]
                    if row_id in problem_ids:
                        fixed_rows.append(row)
            
            save_tsv(output_path, header_b, fixed_rows)

            result_msg = (
                f"Найдено проблемных строк: {len(problems)}.\n"
                f"Создан файл: {output_path}\n"
                f"Строк в файле: {len(fixed_rows)}."
            )

            # Спрашиваем, нужно ли переместить проблемные строки в конец файла B
            reply = QtWidgets.QMessageBox.question(
                self,
                "Различия в длине",
                (
                    f"{result_msg}\n\n"
                    f"Переместить все эти строки (кол-во: {len(problems)}) в конец файла B?\n"
                    f"Порядок внутри группы будет сохранён."
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )

            if reply == QtWidgets.QMessageBox.Yes:
                # Перемещаем проблемные строки в конец
                problem_indices = []
                for idx, row in enumerate(rows_b):
                    if len(row) > id_idx_b:
                        row_id = row[id_idx_b]
                        if row_id in problem_ids:
                            problem_indices.append(idx)
                
                problem_set = set(problem_indices)
                kept_rows = [row for i, row in enumerate(rows_b) if i not in problem_set]
                problem_rows = [rows_b[i] for i in problem_indices]
                new_rows = kept_rows + problem_rows

                save_tsv(path_b, header_b, new_rows)
                move_msg = (
                    f"Строки с различием в длине перемещены в конец файла B. "
                    f"Всего перемещено: {len(problems)}."
                )
                self.append_log(move_msg)
                QtWidgets.QMessageBox.information(self, "Различия в длине", result_msg + "\n\n" + move_msg)
            else:
                QtWidgets.QMessageBox.information(self, "Различия в длине", result_msg)
                self.append_log(f"\n{result_msg}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка обработки результатов: {e}")

    # --- Операции по фрагменту текста в файле B ---

    def _get_text_filter(self) -> str:
        return self.edit_text_filter.text().strip()

    def _load_b_with_indices(self, path_b):
        header_b, rows_b = load_tsv(path_b)
        if not rows_b:
            raise ValueError("Файл B пуст или без данных.")
        id_idx = find_column_index(header_b, 'ID', 0)
        text_idx = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)
        return header_b, rows_b, id_idx, text_idx

    def handle_find_ids_by_text(self):
        """Поиск всех ID в B, где OriginalText содержит заданный фрагмент."""
        path_b = self.edit_b.text().strip()
        fragment = self._get_text_filter()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not fragment:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Введите фрагмент текста для поиска.")
            return

        try:
            header_b, rows_b, id_idx, text_idx = self._load_b_with_indices(path_b)

            total = 0
            ids = []

            for row in rows_b:
                if len(row) <= max(id_idx, text_idx):
                    continue
                text = row[text_idx]
                if fragment in text:
                    total += 1
                    row_id = row[id_idx] if len(row) > id_idx else ''
                    ids.append(row_id)

            if total == 0:
                msg = f"Строк с фрагментом текста '{fragment}' в файле B не найдено."
            else:
                msg = f"Найдено строк с фрагментом '{fragment}' в B: {total}. ID выведены ниже."

            self.append_log(msg)
            for rid in ids:
                self.append_log(f"ID (TEXT='{fragment}'): {rid}")

            QtWidgets.QMessageBox.information(self, "Поиск по тексту", msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка поиска по тексту: {e}")

    def handle_delete_by_text(self):
        """Удалить из B все строки, где OriginalText содержит фрагмент."""
        path_b = self.edit_b.text().strip()
        fragment = self._get_text_filter()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not fragment:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Введите фрагмент текста для удаления.")
            return

        try:
            header_b, rows_b, id_idx, text_idx = self._load_b_with_indices(path_b)

            original_count = len(rows_b)
            kept_rows = []
            removed = 0

            for row in rows_b:
                if len(row) <= max(id_idx, text_idx):
                    kept_rows.append(row)
                    continue
                text = row[text_idx]
                if fragment in text:
                    removed += 1
                else:
                    kept_rows.append(row)

            if removed == 0:
                msg = f"В файле B нет строк с фрагментом '{fragment}'. Ничего не удалено."
                QtWidgets.QMessageBox.information(self, "Удаление по тексту", msg)
                self.append_log(msg)
                return

            save_tsv(path_b, header_b, kept_rows)
            msg = (
                f"Удаление по тексту завершено. Удалено строк: {removed} "
                f"из {original_count} (фрагмент: '{fragment}')."
            )
            QtWidgets.QMessageBox.information(self, "Удаление по тексту", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка удаления по тексту: {e}")

    def handle_replace_by_text(self):
        """
        Заменить в B все строки, где OriginalText содержит фрагмент,
        на строки из A с теми же ID.
        """
        path_a = self.edit_a.text().strip()
        path_b = self.edit_b.text().strip()
        fragment = self._get_text_filter()

        if not path_a or not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите пути к файлам A и B.")
            return
        if not fragment:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Введите фрагмент текста для замены.")
            return
        if not os.path.isfile(path_a):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл A не найден: {path_a}")
            return

        try:
            # Загружаем A и строим словарь ID -> row
            header_a, rows_a = load_tsv(path_a)
            id_idx_a = find_column_index(header_a, 'ID', 0)
            map_a = {}
            for row in rows_a:
                if len(row) > id_idx_a:
                    map_a[row[id_idx_a]] = row

            header_b, rows_b, id_idx_b, text_idx_b = self._load_b_with_indices(path_b)

            size_b = len(header_b)

            def normalize_row(row, size):
                if len(row) < size:
                    return row + [''] * (size - len(row))
                elif len(row) > size:
                    return row[:size]
                return row

            replaced = 0
            affected = 0

            new_rows = []
            for row in rows_b:
                if len(row) <= max(id_idx_b, text_idx_b):
                    new_rows.append(row)
                    continue

                text = row[text_idx_b]
                if fragment in text:
                    affected += 1
                    row_id = row[id_idx_b]
                    if row_id in map_a:
                        # Берём строку из A и приводим к размеру header B
                            # Берём строку из A и приводим к размеру header B
                        a_row = normalize_row(map_a[row_id], size_b)
                        new_rows.append(a_row)
                        replaced += 1
                    else:
                        # В A нет такого ID — оставляем как есть
                        new_rows.append(row)
                else:
                    new_rows.append(row)

            if affected == 0:
                msg = (
                    f"В файле B нет строк с фрагментом '{fragment}'. "
                    f"Замена не выполнялась."
                )
                QtWidgets.QMessageBox.information(self, "Замена по тексту", msg)
                self.append_log(msg)
                return

            save_tsv(path_b, header_b, new_rows)
            msg = (
                f"Замена по тексту завершена. "
                f"Строк с фрагментом в B: {affected}, "
                f"заменено по ID из A: {replaced} (фрагмент: '{fragment}')."
            )
            QtWidgets.QMessageBox.information(self, "Замена по тексту", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка замены по тексту: {e}")

    def handle_cut_by_text(self):
        """
        Вырезать в отдельный файл select_*.tsv все строки из B,
        где OriginalText содержит фрагмент. B при этом не меняем.
        """
        path_b = self.edit_b.text().strip()
        fragment = self._get_text_filter()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not fragment:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Введите фрагмент текста для вырезки.")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            header_b, rows_b, id_idx, text_idx = self._load_b_with_indices(path_b)

            selected = []
            for row in rows_b:
                if len(row) <= max(id_idx, text_idx):
                    continue
                text = row[text_idx]
                if fragment in text:
                    row_id = row[id_idx]
                    selected.append((row_id, text))

            if not selected:
                msg = f"Строк с фрагментом '{fragment}' в файле B не найдено. Нечего вырезать."
                QtWidgets.QMessageBox.information(self, "Вырезка по тексту", msg)
                self.append_log(msg)
                return

            b_dir = os.path.dirname(path_b)
            b_name = os.path.basename(path_b)
            out_name = f"select_{b_name}"
            out_path = os.path.join(b_dir, out_name)

            # Создаём TSV только с колонками ID и OriginalText
            with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f, delimiter='\t')
                writer.writerow(['ID', 'OriginalText'])
                for rid, txt in selected:
                    writer.writerow([rid, txt])

            msg = (
                f"Вырезка по тексту завершена. Строк: {len(selected)}. "
                f"Файл: {out_path} (ID\\tOriginalText)."
            )
            QtWidgets.QMessageBox.information(self, "Вырезка по тексту", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка вырезки по тексту: {e}")

    def handle_create_debug_tsv(self):
        """
        Создать debug версию файла B с UUID-тегами.
        
        Логика:
        1. Создаёт или загружает файл {name}_uuid.tsv с ID и UUID
        2. Проверяет, есть ли новые ID в файле B, которых нет в UUID файле
        3. Добавляет новые UUID для новых ID
        4. Создаёт debug_*.tsv, используя UUID из файла {name}_uuid.tsv
        """
        path_b = self.edit_b.text().strip()

        if not path_b:
            QtWidgets.QMessageBox.warning(self, "Ошибка", "Укажите путь к файлу B.")
            return
        if not os.path.isfile(path_b):
            QtWidgets.QMessageBox.warning(self, "Ошибка", f"Файл B не найден: {path_b}")
            return

        try:
            header_b, rows_b = load_tsv(path_b)
            if not rows_b:
                QtWidgets.QMessageBox.information(self, "Результат", "Файл B пуст или без данных.")
                return

            id_idx = find_column_index(header_b, 'ID', 0)
            text_idx = find_column_index(header_b, 'OriginalText', 1 if len(header_b) > 1 else 0)

            # Определяем пути к файлам
            b_dir = os.path.dirname(path_b)
            b_name = os.path.basename(path_b)
            b_name_no_ext = os.path.splitext(b_name)[0]
            uuid_file_path = os.path.join(b_dir, f"{b_name_no_ext}_uuid.tsv")
            debug_file_path = os.path.join(b_dir, f"debug_{b_name}")

            # Загружаем существующий UUID файл или создаём пустой словарь
            uuid_map: dict[str, str] = {}  # ID -> UUID
            used_uuids: set[str] = set()

            if os.path.isfile(uuid_file_path):
                # Загружаем существующие UUID
                try:
                    uuid_header, uuid_rows = load_tsv(uuid_file_path)
                    uuid_id_idx = find_column_index(uuid_header, 'ID', 0)
                    uuid_uuid_idx = find_column_index(uuid_header, 'UUID', 1 if len(uuid_header) > 1 else 0)
                    
                    for row in uuid_rows:
                        if len(row) > max(uuid_id_idx, uuid_uuid_idx):
                            row_id = row[uuid_id_idx]
                            row_uuid = row[uuid_uuid_idx]
                            uuid_map[row_id] = row_uuid
                            used_uuids.add(row_uuid)
                    
                    self.append_log(f"Загружено UUID из файла: {uuid_file_path} (строк: {len(uuid_map)})")
                except Exception as e:
                    self.append_log(f"Предупреждение: не удалось загрузить UUID файл: {e}")

            # Генератор UUID (4 символа из [A-Z, a-z, 1-9])
            allowed_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz123456789"
            
            def gen_uuid() -> str:
                """Генерирует уникальный UUID из 4 символов."""
                while True:
                    uuid = "".join(random.choice(allowed_chars) for _ in range(4))
                    if uuid not in used_uuids:
                        used_uuids.add(uuid)
                        return uuid

            # Собираем все ID из файла B
            ids_in_b = set()
            for row in rows_b:
                if len(row) > id_idx:
                    row_id = row[id_idx]
                    if row_id:
                        ids_in_b.add(row_id)

            # Добавляем UUID для новых ID
            new_uuids_count = 0
            for row_id in ids_in_b:
                if row_id not in uuid_map:
                    uuid_map[row_id] = gen_uuid()
                    new_uuids_count += 1

            # Сохраняем UUID файл
            uuid_rows = [[row_id, uuid_map[row_id]] for row_id in sorted(uuid_map.keys())]
            save_tsv(uuid_file_path, ['ID', 'UUID'], uuid_rows)
            
            if new_uuids_count > 0:
                self.append_log(f"Добавлено новых UUID: {new_uuids_count}")

            # Создаём debug версию с UUID-тегами
            new_rows = []
            tagged_count = 0

            for row in rows_b:
                if len(row) > max(id_idx, text_idx):
                    row_id = row[id_idx]
                    text = row[text_idx]
                    
                    if row_id and row_id in uuid_map and text and text.strip():
                        uuid_tag = uuid_map[row_id]
                        row = list(row)
                        row[text_idx] = f"[{uuid_tag}]{text}"
                        tagged_count += 1
                new_rows.append(row)

            save_tsv(debug_file_path, header_b, new_rows)

            msg = (
                f"Создан файл {debug_file_path} с UUID-тегами.\n"
                f"UUID файл: {uuid_file_path}\n"
                f"Строк с тегами: {tagged_count}.\n"
                f"Всего UUID в файле: {len(uuid_map)}."
            )
            QtWidgets.QMessageBox.information(self, "Debug TSV", msg)
            self.append_log(msg)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Ошибка", str(e))
            self.append_log(f"Ошибка создания debug TSV: {e}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()