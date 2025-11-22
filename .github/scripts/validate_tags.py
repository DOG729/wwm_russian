#!/usr/bin/env python3
"""
Валидатор игровых тегов для файла translation_ru.tsv

Проверяет:
1. Корректность тегов цветового оформления (#G...#E)
2. Отсутствие русских букв после символа #
3. Корректность тегов-ссылок (<...|...|...|...>)
4. Корректность переменных ({...})
"""

import sys
import re
from pathlib import Path


def validate_tags(file_path: str) -> tuple[bool, list[str]]:
    """
    Валидирует игровые теги в TSV файле.
    
    Returns:
        tuple: (is_valid, list_of_errors)
    """
    errors = []
    file_path_obj = Path(file_path)
    
    if not file_path_obj.exists():
        errors.append(f"❌ Файл {file_path} не найден")
        return False, errors
    
    try:
        with open(file_path_obj, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        errors.append(f"❌ Ошибка при чтении файла: {e}")
        return False, errors
    
    if len(lines) == 0:
        errors.append("❌ Файл пуст")
        return False, errors
    
    # Пропускаем заголовок
    if len(lines) < 1:
        return False, errors
    
    # Паттерны для проверки
    # После # должна быть английская буква или hex символ (0-9, A-F, a-f)
    # Русские буквы после # - это ошибка
    russian_after_hash_pattern = re.compile(r'#[\u0400-\u04FF]')
    
    # Паттерн для hex кода цвета (#000, #FFF и т.д.)
    hex_color_pattern = re.compile(r'#[0-9A-Fa-f]{3,6}')
    
    # Паттерн для тегов вида #G...#E
    color_tag_pattern = re.compile(r'#([A-Za-z0-9]+)([^#]*?)#E')
    
    # Паттерн для тегов-ссылок <...|...|...|...>
    link_tag_pattern = re.compile(r'<([^>]*)\|([^>]*)\|([^>]*)\|([^>]*)>')
    
    # Паттерн для переменных {...}
    variable_pattern = re.compile(r'\{[^}]*\}')
    
    # ID должен быть 16 символов hex
    id_pattern = re.compile(r'^[0-9a-fA-F]{16}$')
    
    # Проверка каждой строки
    current_entry_lines = []
    entry_start_line = None
    current_id = None
    
    for line_num, line in enumerate(lines[1:], start=2):
        original_line = line
        line = line.rstrip('\n\r')
        
        # Пропускаем пустые строки
        if not line.strip():
            continue
        
        # Проверяем, начинается ли строка с ID
        is_new_entry = re.match(r'^[0-9a-fA-F]{16}\t', line)
        
        if is_new_entry:
            # Если это новая запись, обрабатываем предыдущую
            if current_entry_lines:
                full_text = ''.join(current_entry_lines)
                if entry_start_line:
                    _validate_entry_tags(
                        errors, entry_start_line, full_text, id_pattern,
                        russian_after_hash_pattern, hex_color_pattern,
                        color_tag_pattern, link_tag_pattern, variable_pattern,
                        current_id
                    )
            
            # Начинаем новую запись
            current_entry_lines = [original_line]
            entry_start_line = line_num
            
            parts = line.split('\t', 1)
            if len(parts) == 2:
                current_id = parts[0]
        else:
            # Продолжение предыдущей записи
            if current_entry_lines:
                current_entry_lines.append(original_line)
    
    # Обрабатываем последнюю запись
    if current_entry_lines:
        full_text = ''.join(current_entry_lines)
        if entry_start_line:
            _validate_entry_tags(
                errors, entry_start_line, full_text, id_pattern,
                russian_after_hash_pattern, hex_color_pattern,
                color_tag_pattern, link_tag_pattern, variable_pattern,
                current_id
            )
    
    is_valid = len(errors) == 0
    return is_valid, errors


def _validate_entry_tags(
    errors: list, start_line: int, full_text: str, id_pattern: re.Pattern,
    russian_after_hash_pattern: re.Pattern, hex_color_pattern: re.Pattern,
    color_tag_pattern: re.Pattern, link_tag_pattern: re.Pattern,
    variable_pattern: re.Pattern, current_id: str = None
):
    """Валидирует теги в одной записи TSV."""
    full_text = full_text.rstrip('\n\r')
    
    # Разделяем на ID и текст
    parts = full_text.split('\t', 1)
    if len(parts) != 2:
        return
    
    id_value, text = parts
    display_id = current_id if current_id else id_value
    
    # 1. Проверка тегов цветового оформления #G...#E и русских букв после #
    # Сначала находим все теги-ссылки, чтобы пропустить теги внутри них
    link_ranges = []
    for link_match in re.finditer(r'<([^>]*)>', text):
        link_ranges.append((link_match.start(), link_match.end()))
    
    def is_inside_link_tag(pos):
        """Проверяет, находится ли позиция внутри тега-ссылки."""
        for start, end in link_ranges:
            if start <= pos < end:
                return True
        return False
    
    # Проходим по тексту и проверяем парность тегов
    tag_stack = []
    i = 0
    while i < len(text):
        # Пропускаем теги внутри тегов-ссылок
        if is_inside_link_tag(i):
            i += 1
            continue
        
        # Проверяем, не начинается ли здесь открывающий тег
        if text[i] == '#' and i + 1 < len(text):
            # Сначала проверяем закрывающий тег #E
            if text[i:i+2] == '#E':
                if tag_stack:
                    tag_stack.pop()
                else:
                    errors.append(
                        f"❌ Строка {start_line}, ID: {display_id}: "
                        f"Найден закрывающий тег #E без соответствующего открывающего тега. "
                        f"Контекст: '{_get_context(text, '#E', 30, i)}'"
                    )
                i += 2
                continue
            
            # Проверяем hex код цвета (#000, #FFFFFF, #ffc89c10 и т.д.)
            # Hex коды могут быть 3, 6 или больше символов
            # Они содержат только цифры и буквы A-F (в любом порядке)
            # Проверяем, что после # идет последовательность hex символов длиной 3+
            # и она заканчивается на не-hex символ или конец строки
            hex_match = re.match(r'#([0-9A-Fa-f]{3,})(?![0-9A-Fa-f])', text[i:])
            if hex_match:
                hex_code = hex_match.group(0)
                hex_code_len = len(hex_code)
                
                # Проверяем, используется ли hex код как открывающий тег с закрывающим #E
                # Формат: #ffc89cтекст#E - это валидная конструкция
                # Ищем следующий #E после hex кода (но не сразу после, а после текста)
                # Если сразу после hex кода идет #E, то это просто hex код без закрывающего
                if i + hex_code_len < len(text) and text[i + hex_code_len:i + hex_code_len + 2] != '#E':
                    # После hex кода идет текст - это может быть открывающий тег с закрывающим #E
                    # Добавляем в стек как открывающий тег
                    tag_stack.append((i, hex_code))
                
                # Hex код цвета может использоваться с закрывающим #E или без него
                i += hex_code_len
                continue
            
            # Проверяем буквенный тег (#G, #R, #Y и т.д.)
            # НЕ включаем #E, так как это закрывающий тег
            letter_match = re.match(r'#([A-Za-z][A-Za-z0-9]*)', text[i:])
            if letter_match:
                tag = letter_match.group(0)
                # #E - это закрывающий тег, не открывающий
                if tag != '#E':
                    tag_stack.append((i, tag))
                i += len(tag)
                continue
            
            # Проверяем на русскую букву после #
            if i + 1 < len(text) and '\u0400' <= text[i+1] <= '\u04FF':
                errors.append(
                    f"❌ Строка {start_line}, ID: {display_id}: "
                    f"Найдена русская буква после символа #: '#{text[i+1]}'. "
                    f"После # должны быть только английские буквы или hex символы (0-9, A-F). "
                    f"Контекст: '{_get_context(text, f'#{text[i+1]}', 30, i)}'"
                )
                i += 1
                continue
        
        i += 1
    
    # Проверяем незакрытые открывающие теги
    for pos, tag in tag_stack:
        errors.append(
            f"❌ Строка {start_line}, ID: {display_id}: "
            f"Открывающий тег '{tag}' не имеет закрывающего тега #E. "
            f"Контекст: '{_get_context(text, tag, 30, pos)}'"
        )
    
    # 3. Проверка тегов-ссылок <...|...|...|...>
    # Теги-ссылки могут иметь 4 или 5 частей (некоторые содержат дополнительный ID)
    for link_match in re.finditer(r'<([^>]*)>', text):
        link_content = link_match.group(1)
        parts = link_content.split('|')
        # Игнорируем HTML-подобные теги (например, <TEXT>, </TEXT>, <IMAGE>)
        if not re.match(r'^[A-Z/]', link_content.strip()):
            if len(parts) != 4 and len(parts) != 5:
                errors.append(
                    f"❌ Строка {start_line}, ID: {display_id}: "
                    f"Тег-ссылка '<{link_content}>' должен содержать 4 или 5 частей, разделённых символом |. "
                    f"Найдено частей: {len(parts)}. "
                    f"Контекст: '{_get_context(text, link_match.group(0), 30)}'"
                )
    
    # 4. Проверка переменных {...}
    # Ищем незакрытые фигурные скобки
    open_braces = text.count('{')
    close_braces = text.count('}')
    if open_braces != close_braces:
        errors.append(
            f"❌ Строка {start_line}, ID: {display_id}: "
            f"Несбалансированные фигурные скобки в переменных. "
            f"Открывающих {{: {open_braces}, закрывающих }}: {close_braces}. "
            f"Контекст: '{text[:100]}'"
        )
    
    # Проверяем, что все переменные правильно закрыты
    brace_stack = []
    for i, char in enumerate(text):
        if char == '{':
            brace_stack.append(i)
        elif char == '}':
            if not brace_stack:
                errors.append(
                    f"❌ Строка {start_line}, ID: {display_id}: "
                    f"Найдена закрывающая скобка }} без соответствующей открывающей {{. "
                    f"Позиция: {i}. "
                    f"Контекст: '{_get_context(text, '}', 30, i)}'"
                )
            else:
                brace_stack.pop()
    
    # Проверяем незакрытые переменные
    for pos in brace_stack:
        errors.append(
            f"❌ Строка {start_line}, ID: {display_id}: "
            f"Найдена открывающая скобка {{ без соответствующей закрывающей }}. "
            f"Позиция: {pos}. "
            f"Контекст: '{_get_context(text, '{', 30, pos)}'"
        )


def _get_context(text: str, search_str: str, context_len: int = 30, pos: int = None) -> str:
    """Получает контекст вокруг найденной строки."""
    if pos is None:
        pos = text.find(search_str)
        if pos == -1:
            return text[:context_len]
    
    start = max(0, pos - context_len)
    end = min(len(text), pos + len(search_str) + context_len)
    context = text[start:end]
    
    # Заменяем переносы строк для читаемости
    context = context.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    
    return context


def main():
    # Настройка кодировки для Windows
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    
    if len(sys.argv) != 2:
        print("Использование: python validate_tags.py <путь_к_tsv_файлу>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    is_valid, errors = validate_tags(file_path)
    
    if errors:
        print(f"\n🔍 Валидация тегов в файле {file_path}:\n")
        # Заменяем ❌ на ⚠️ для предупреждений
        for error in errors:
            warning = error.replace("❌", "⚠️")
            print(warning)
        print(f"\n⚠️  Найдено предупреждений: {len(errors)}")
        print("ℹ️  Это предупреждения, а не критичные ошибки. Коммит не будет заблокирован.")
        # Всегда возвращаем 0, чтобы не блокировать коммиты
        sys.exit(0)
    else:
        print(f"✅ Все теги в файле {file_path} валидны!")
        sys.exit(0)


if __name__ == '__main__':
    main()

