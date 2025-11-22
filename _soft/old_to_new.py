#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для переноса русских текстов из old_translation_ru.tsv в translation_ru.tsv
с соблюдением правил фильтрации.
GUI версия с выбором файлов.
"""

import re
import os
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from threading import Thread

def has_cyrillic(text):
    """Проверяет наличие кириллицы в тексте"""
    return bool(re.search(r'[А-Яа-я]', text))

def has_tags(text):
    """Проверяет наличие тегов { или }"""
    return '{' in text or '}' in text

def has_digits(text):
    """Проверяет наличие цифр в тексте"""
    return bool(re.search(r'\d', text))

def is_valid_length(text):
    """Проверяет, что длина текста больше 3 символов"""
    return len(text.strip()) > 3

def load_old_translations(old_file, log_callback=None):
    """Загружает переводы из old_translation_ru.tsv в словарь"""
    translations = {}
    if log_callback:
        log_callback(f"Загрузка переводов из {os.path.basename(old_file)}...")
    
    with open(old_file, 'r', encoding='utf-8') as f:
        # Пропускаем заголовок
        next(f)
        
        for line_num, line in enumerate(f, start=2):
            line = line.rstrip('\n\r')
            if not line:
                continue
            
            parts = line.split('\t', 1)
            if len(parts) != 2:
                continue
            
            id_val, text = parts
            translations[id_val] = text
    
    if log_callback:
        log_callback(f"Загружено {len(translations)} переводов из старого файла")
    return translations

def process_translations(old_file, new_file, enable_sort=True, 
                        filter_tags=True, filter_digits=True, filter_length=True,
                        log_callback=None, progress_callback=None):
    """Обрабатывает translation_ru.tsv и переносит тексты из old_translation_ru.tsv"""
    updated_count = 0
    skipped_cyrillic = 0
    skipped_not_found = 0
    skipped_tags = 0
    skipped_digits = 0
    skipped_length = 0
    
    temp_file = new_file + '.tmp'
    
    if log_callback:
        log_callback(f"Обработка файла {os.path.basename(new_file)}...")
        if enable_sort:
            log_callback("Сортировка включена: RU → в начало, EN → в конец")
        else:
            log_callback("Сортировка отключена: порядок строк сохраняется")
        log_callback(f"Фильтры: теги={filter_tags}, цифры={filter_digits}, длина={filter_length}")
    
    # Загружаем старые переводы
    old_translations = load_old_translations(old_file, log_callback)
    
    # Собираем все строки в список
    if enable_sort:
        lines_with_cyrillic = []  # Строки с кириллицей (в начале)
        lines_without_cyrillic = []  # Строки без кириллицы (в конце)
    else:
        all_lines_ordered = []  # Все строки в исходном порядке
    
    # Подсчитываем общее количество строк для прогресса
    total_lines = 0
    with open(new_file, 'r', encoding='utf-8') as f:
        total_lines = sum(1 for _ in f) - 1  # -1 для заголовка
    
    with open(new_file, 'r', encoding='utf-8') as f_in:
        # Пропускаем заголовок
        header = f_in.readline()
        
        for line_num, line in enumerate(f_in, start=2):
            line = line.rstrip('\n\r')
            original_line = line
            
            if not line:
                if enable_sort:
                    lines_without_cyrillic.append('')
                else:
                    all_lines_ordered.append('')
                continue
            
            parts = line.split('\t', 1)
            if len(parts) != 2:
                if enable_sort:
                    lines_without_cyrillic.append(line)
                else:
                    all_lines_ordered.append(line)
                continue
            
            id_val, current_text = parts
            final_text = current_text
            
            # Проверяем, есть ли уже кириллица в текущем тексте
            if has_cyrillic(current_text):
                skipped_cyrillic += 1
                if enable_sort:
                    lines_with_cyrillic.append(line)
                else:
                    all_lines_ordered.append(line)
                continue
            
            # Проверяем, есть ли этот ID в старом файле
            if id_val not in old_translations:
                skipped_not_found += 1
                if enable_sort:
                    lines_without_cyrillic.append(line)
                else:
                    all_lines_ordered.append(line)
                continue
            
            old_text = old_translations[id_val]
            
            # Проверяем условия для переноса (только если фильтры включены)
            if filter_tags and has_tags(old_text):
                skipped_tags += 1
                if enable_sort:
                    lines_without_cyrillic.append(line)
                else:
                    all_lines_ordered.append(line)
                continue
            
            if filter_digits and has_digits(old_text):
                skipped_digits += 1
                if enable_sort:
                    lines_without_cyrillic.append(line)
                else:
                    all_lines_ordered.append(line)
                continue
            
            if filter_length and not is_valid_length(old_text):
                skipped_length += 1
                if enable_sort:
                    lines_without_cyrillic.append(line)
                else:
                    all_lines_ordered.append(line)
                continue
            
            # Все условия выполнены - переносим текст
            final_text = old_text
            updated_count += 1
            new_line = f"{id_val}\t{final_text}"
            
            # Добавляем строку в соответствующий список
            if enable_sort:
                # Проверяем, есть ли кириллица в перенесенном тексте
                if has_cyrillic(final_text):
                    lines_with_cyrillic.append(new_line)
                else:
                    lines_without_cyrillic.append(new_line)
            else:
                all_lines_ordered.append(new_line)
            
            # Обновляем прогресс
            if progress_callback and line_num % 1000 == 0:
                progress = int((line_num / total_lines) * 100)
                progress_callback(progress)
                if log_callback:
                    log_callback(f"Обработано {line_num}/{total_lines} строк, обновлено {updated_count}...")
    
    # Объединяем строки в зависимости от режима сортировки
    if enable_sort:
        if log_callback:
            log_callback("Сортировка строк...")
        all_lines = lines_with_cyrillic + lines_without_cyrillic
    else:
        all_lines = all_lines_ordered
    
    # Записываем результат
    with open(temp_file, 'w', encoding='utf-8') as f_out:
        f_out.write(header)
        for line in all_lines:
            f_out.write(line + '\n')
    
    if progress_callback:
        progress_callback(100)
    
    # Подсчитываем статистику
    if enable_sort:
        lines_with_cyrillic_count = len(lines_with_cyrillic)
        lines_without_cyrillic_count = len(lines_without_cyrillic)
        total_lines_count = lines_with_cyrillic_count + lines_without_cyrillic_count
    else:
        # Если сортировка отключена, подсчитываем статистику из всех строк
        total_lines_count = len(all_lines)
        lines_with_cyrillic_count = sum(1 for line in all_lines if line and '\t' in line and has_cyrillic(line.split('\t', 1)[1] if len(line.split('\t', 1)) > 1 else ''))
        lines_without_cyrillic_count = total_lines_count - lines_with_cyrillic_count
    
    result = {
        'updated_count': updated_count,
        'skipped_cyrillic': skipped_cyrillic,
        'skipped_not_found': skipped_not_found,
        'skipped_tags': skipped_tags,
        'skipped_digits': skipped_digits,
        'skipped_length': skipped_length,
        'lines_with_cyrillic': lines_with_cyrillic_count,
        'lines_without_cyrillic': lines_without_cyrillic_count,
        'temp_file': temp_file,
        'enable_sort': enable_sort
    }
    
    if log_callback:
        log_callback(f"\nОбработка завершена!")
        log_callback(f"Обновлено записей: {updated_count}")
        if enable_sort:
            log_callback(f"Строк с кириллицей (в начале): {lines_with_cyrillic_count}")
            log_callback(f"Строк без кириллицы (в конце): {lines_without_cyrillic_count}")
        else:
            log_callback(f"Всего строк обработано: {total_lines_count}")
            log_callback(f"Строк с кириллицей: {lines_with_cyrillic_count}")
            log_callback(f"Строк без кириллицы: {lines_without_cyrillic_count}")
        log_callback(f"Пропущено (уже есть кириллица): {skipped_cyrillic}")
        log_callback(f"Пропущено (ID не найден в старом файле): {skipped_not_found}")
        if filter_tags:
            log_callback(f"Пропущено (есть теги): {skipped_tags}")
        if filter_digits:
            log_callback(f"Пропущено (есть цифры): {skipped_digits}")
        if filter_length:
            log_callback(f"Пропущено (длина <= 3): {skipped_length}")
    
    return result

class TranslationMergerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Перенос переводов: old_translation_ru.tsv → translation_ru.tsv")
        self.root.geometry("800x700")
        
        self.old_file = None
        self.new_file = None
        
        self.create_widgets()
    
    def create_widgets(self):
        # Фрейм для выбора файлов
        file_frame = ttk.LabelFrame(self.root, text="Выбор файлов", padding=10)
        file_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Источник переводов (old_translation_ru.tsv)
        source_label = ttk.Label(file_frame, text="ИСТОЧНИК (old_translation_ru.tsv):\nоткуда берем русские тексты", 
                                  font=('Arial', 9, 'bold'))
        source_label.grid(row=0, column=0, sticky=tk.W, pady=5)
        self.old_file_label = ttk.Label(file_frame, text="Не выбран", foreground="gray")
        self.old_file_label.grid(row=0, column=1, sticky=tk.W, padx=10, pady=5)
        ttk.Button(file_frame, text="Выбрать...", command=self.select_old_file).grid(row=0, column=2, padx=5, pady=5)
        
        # Целевой файл (translation_ru.tsv) - главный
        target_label = ttk.Label(file_frame, text="ЦЕЛЕВОЙ (translation_ru.tsv):\nглавный файл, куда переносим", 
                                 font=('Arial', 9, 'bold'))
        target_label.grid(row=1, column=0, sticky=tk.W, pady=5)
        self.new_file_label = ttk.Label(file_frame, text="Не выбран", foreground="gray")
        self.new_file_label.grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)
        ttk.Button(file_frame, text="Выбрать...", command=self.select_new_file).grid(row=1, column=2, padx=5, pady=5)
        
        # Опции
        options_frame = ttk.LabelFrame(self.root, text="Опции", padding=10)
        options_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.sort_enabled = tk.BooleanVar(value=True)
        sort_checkbox = ttk.Checkbutton(
            options_frame, 
            text="Сортировать: строки с кириллицей (RU) → в начало, без кириллицы (EN) → в конец",
            variable=self.sort_enabled
        )
        sort_checkbox.pack(anchor=tk.W, pady=2)
        
        # Разделитель
        ttk.Separator(options_frame, orient='horizontal').pack(fill=tk.X, pady=5)
        
        # Фильтры
        filters_label = ttk.Label(options_frame, text="Фильтры (пропускать строки с):", font=('Arial', 9, 'bold'))
        filters_label.pack(anchor=tk.W, pady=(5, 2))
        
        self.filter_tags = tk.BooleanVar(value=True)
        filter_tags_checkbox = ttk.Checkbutton(
            options_frame,
            text="Теги { }",
            variable=self.filter_tags
        )
        filter_tags_checkbox.pack(anchor=tk.W, pady=2)
        
        self.filter_digits = tk.BooleanVar(value=True)
        filter_digits_checkbox = ttk.Checkbutton(
            options_frame,
            text="Цифры",
            variable=self.filter_digits
        )
        filter_digits_checkbox.pack(anchor=tk.W, pady=2)
        
        self.filter_length = tk.BooleanVar(value=True)
        filter_length_checkbox = ttk.Checkbutton(
            options_frame,
            text="Длина <= 3 символов",
            variable=self.filter_length
        )
        filter_length_checkbox.pack(anchor=tk.W, pady=2)
        
        # Кнопка запуска
        self.start_button = ttk.Button(self.root, text="Начать обработку", command=self.start_processing, state=tk.DISABLED)
        self.start_button.pack(pady=10)
        
        # Прогресс-бар
        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.pack(fill=tk.X, padx=10, pady=5)
        
        # Лог-область
        log_frame = ttk.LabelFrame(self.root, text="Лог обработки", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
    
    def select_old_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите ИСТОЧНИК переводов (old_translation_ru.tsv)",
            filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")]
        )
        if filename:
            self.old_file = filename
            self.old_file_label.config(text=os.path.basename(filename), foreground="black")
            self.check_files_selected()
    
    def select_new_file(self):
        filename = filedialog.askopenfilename(
            title="Выберите ЦЕЛЕВОЙ файл (translation_ru.tsv) - главный файл",
            filetypes=[("TSV files", "*.tsv"), ("All files", "*.*")]
        )
        if filename:
            self.new_file = filename
            self.new_file_label.config(text=os.path.basename(filename), foreground="black")
            self.check_files_selected()
    
    def check_files_selected(self):
        if self.old_file and self.new_file:
            self.start_button.config(state=tk.NORMAL)
        else:
            self.start_button.config(state=tk.DISABLED)
    
    def log(self, message):
        """Добавляет сообщение в лог"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def update_progress(self, value):
        """Обновляет прогресс-бар"""
        self.progress['value'] = value
        self.root.update_idletasks()
    
    def start_processing(self):
        """Запускает обработку в отдельном потоке"""
        if not self.old_file or not self.new_file:
            messagebox.showerror("Ошибка", "Пожалуйста, выберите оба файла!")
            return
        
        # Блокируем кнопку
        self.start_button.config(state=tk.DISABLED)
        self.progress['value'] = 0
        self.log_text.delete(1.0, tk.END)
        
        # Запускаем обработку в отдельном потоке
        thread = Thread(target=self.process_files, daemon=True)
        thread.start()
    
    def process_files(self):
        """Обрабатывает файлы"""
        try:
            enable_sort = self.sort_enabled.get()
            filter_tags = self.filter_tags.get()
            filter_digits = self.filter_digits.get()
            filter_length = self.filter_length.get()
            
            result = process_translations(
                self.old_file,
                self.new_file,
                enable_sort=enable_sort,
                filter_tags=filter_tags,
                filter_digits=filter_digits,
                filter_length=filter_length,
                log_callback=self.log,
                progress_callback=self.update_progress
            )
            
            # Заменяем оригинальный файл временным
            if os.path.exists(result['temp_file']):
                os.replace(result['temp_file'], self.new_file)
                sort_msg = "отсортирован" if enable_sort else "обновлен"
                self.log(f"\n✓ Файл {os.path.basename(self.new_file)} успешно {sort_msg}!")
                
                message_text = f"Обработка завершена!\n\nОбновлено записей: {result['updated_count']}"
                if enable_sort:
                    message_text += f"\nСтрок с кириллицей: {result['lines_with_cyrillic']}\nСтрок без кириллицы: {result['lines_without_cyrillic']}"
                messagebox.showinfo("Успех", message_text)
            else:
                self.log("Ошибка: временный файл не создан!")
                messagebox.showerror("Ошибка", "Временный файл не был создан!")
        
        except Exception as e:
            error_msg = f"Ошибка при обработке: {str(e)}"
            self.log(error_msg)
            messagebox.showerror("Ошибка", error_msg)
        
        finally:
            # Разблокируем кнопку
            self.start_button.config(state=tk.NORMAL)

def main():
    """Основная функция"""
    root = tk.Tk()
    app = TranslationMergerGUI(root)
    root.mainloop()

if __name__ == '__main__':
    main()
