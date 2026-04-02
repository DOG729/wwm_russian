import re
import os
import struct
import pyzstd
import sys
import csv
import configparser
import random
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout, QFileDialog, QLabel, QGroupBox, QGridLayout, QMessageBox, QComboBox
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# "JSON-подобный" словарь текстов интерфейса для разных языков
LANG_UI = {
    "en": {
        "ui_lang_label": "Interface language:",
        "group_extract_files": "📦 Extract files",
        "group_pack_files": "📦 Pack files",
        "group_extract_texts": "📦 Extract text",
        "group_pack_texts": "📦 Pack text",
        "group_translate": "📑 Translation by ID",
        "group_full_extract": "📦 Full extract (file → data + text)",
        "group_full_pack": "📦 Full pack (data + text → file)",
        "btn_select_file": "📄 Select file",
        "btn_select_folder": "📂 Select folder",
        "btn_output_folder": "📂 Output folder",
        "btn_run_extract_file": "Extract",
        "btn_run_pack_file": "Pack",
        "btn_full_output_folder": "📂 Output folder (data and text will be created)",
        "btn_full_run": "Extract file and text",
        "btn_extract_texts_run": "Extract",
        "btn_pack_text_run": "Pack",
        "btn_tr_select_file": "📄 Select TextExtractor.csv",
        "label_tr_format": "Translation file format",
        "label_text_path": "Unpack/pack method (1.0 / 2.0)",
        "btn_tr_export": "Create CSV/TSV: ID,OriginalText",
        "btn_tr_apply": "Apply translations from CSV/TSV",
        "btn_tr_debug": "Create debug TextExtractor.csv (tags)",
        "btn_tr_validate": "Validate TextExtractor.csv",
        "btn_full_pack_base_folder": "📂 Folder with data and text",
        "btn_full_pack_trans_file": "📄 Translation CSV/TSV (ID,OriginalText)",
        "btn_full_pack_output_file": "📂 Output game file",
        "btn_full_pack_run": "Pack data + text",
    },
    "ru": {
        "ui_lang_label": "Язык интерфейса:",
        "group_extract_files": "📦 Распаковка файлов",
        "group_pack_files": "📦 Запаковка файлов",
        "group_extract_texts": "📦 Распаковка текста",
        "group_pack_texts": "📦 Запаковка текста",
        "group_translate": "📑 Перевод по ID",
        "group_full_extract": "📦 Полная распаковка (файл → data + text)",
        "group_full_pack": "📦 Полная запаковка (data + text → файл)",
        "btn_select_file": "📄 Выберите файл",
        "btn_select_folder": "📂 Выберите папку",
        "btn_output_folder": "📂 Папка сохранения",
        "btn_run_extract_file": "Распаковать",
        "btn_run_pack_file": "Запаковать",
        "btn_full_output_folder": "📂 Папка сохранения (будут созданы data и text)",
        "btn_full_run": "Распаковать файл и текст",
        "btn_extract_texts_run": "Распаковать",
        "btn_pack_text_run": "Запаковать",
        "btn_tr_select_file": "📄 Выберите TextExtractor.csv",
        "label_tr_format": "Формат файла перевода",
        "label_text_path": "Метод распаковки/запаковки текста",
        "btn_tr_export": "Создать CSV/TSV: ID,OriginalText",
        "btn_tr_apply": "Применить переводы из CSV/TSV",
        "btn_tr_debug": "Создать debug TextExtractor.csv (теги)",
        "btn_tr_validate": "Проверить TextExtractor.csv",
        "btn_full_pack_base_folder": "📂 Папка с data и text",
        "btn_full_pack_trans_file": "📄 Файл перевода CSV/TSV (ID,OriginalText)",
        "btn_full_pack_output_file": "📂 Итоговый файл игры",
        "btn_full_pack_run": "Запаковать data + text",
    },
}

# Коды путей формата текста
TEXT_FORMAT_PATH_1 = "path_1"  # версия 1.0 
TEXT_FORMAT_PATH_2 = "path_2"  # версия 2.0 

# Текущий выбранный путь (по умолчанию 2.0)
CURRENT_TEXT_PATH = TEXT_FORMAT_PATH_1

def extract_file(input_file, output_dir, log_callback):
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]

        with open(input_file, 'rb') as f:
            if f.read(4) != b'\xEF\xBE\xAD\xDE':
                return False

            f.read(4)
            offset_count_bytes = f.read(4)
            offset_count = struct.unpack('<I', offset_count_bytes)[0] + 1

            if offset_count == 1:
                comp_block_len = struct.unpack('<I', f.read(4))[0]
                comp_block = f.read(comp_block_len)

                if len(comp_block) < comp_block_len:
                    return False

                header = comp_block[:9]
                comp_data_part = comp_block[9:]

                if len(header) < 9:
                    return False
                    
                comp_type, comp_size, decomp_size = struct.unpack('<BII', header)

                if comp_type == 0x04:
                    try:
                        decomp_data = pyzstd.decompress(comp_data_part)
                        output_path = os.path.join(output_subdir, f"{base_name}_0.dat")
                        with open(output_path, 'wb') as out_f:
                            out_f.write(decomp_data)
                        log_callback(f"{base_name}_0.dat {comp_block_len} {decomp_size}")
                    except Exception:
                        pass
            else:
                offsets = [struct.unpack('<I', f.read(4))[0] for _ in range(offset_count)]
                data_start = f.tell()
                for i in range(offset_count):
                    current_offset = offsets[i]
                    if i == (offset_count - 1):
                       continue
                    else:
                        next_offset = offsets[i + 1]
                    block_len = next_offset - current_offset

                    f.seek(data_start + current_offset)
                    comp_block = f.read(block_len)

                    if len(comp_block) < block_len:
                        continue

                    if len(comp_block) < 9:
                        continue

                    header = comp_block[:9]
                    comp_data_part = comp_block[9:]
                    comp_type, comp_size, decomp_size = struct.unpack('<BII', header)
                    if comp_type == 0x04:
                        try:
                            decomp_data = pyzstd.decompress(comp_data_part)
                            output_path = os.path.join(output_dir, f"{base_name}_{i}.dat")
                            with open(output_path, 'wb') as out_f:
                                out_f.write(decomp_data)
                            log_callback(f"{os.path.basename(output_path)} {current_offset} {decomp_size}")
                        except Exception:
                            pass

            return True

    except Exception:
        return False

def pak_file(input_file, output_dir, log_callback):
    try:
        files = [f for f in os.listdir(input_file) if f.endswith('.dat')]
    
        def extract_number(filename):
            match = re.search(r'(\d+)\.dat$', filename)
            return int(match.group(1)) if match else float('inf')
        files.sort(key=extract_number)
    
        output_file = os.path.join(output_dir, "output_file_for_game.bin")
        with open(output_file, 'wb') as outfile:
            outfile.write(b'\xEF\xBE\xAD\xDE\x01\x00\x00\x00')
            count_files = struct.pack('<I', len(files))
            outfile.write(count_files)
            archive = b''
            for filename in files:
                file_path = os.path.join(input_file, filename)
                file_size = os.path.getsize(file_path)
                with open(file_path, 'rb') as infile:
                    comp_data = pyzstd.compress(infile.read())
                    header = struct.pack('<BII', 4, len(comp_data), file_size)
                    len_arch = struct.pack('<I', len(archive))
                    outfile.write(len_arch)
                    archive += header + comp_data
                log_callback(f"Обработан: {filename}")
                
            len_arch = struct.pack('<I', len(archive))
            outfile.write(len_arch)
            outfile.write(archive)
    
        log_callback(f"✅ Сборка завершена. Файл сохранен как: {output_file}")
    except Exception as e:
        log_callback(f"❌ Ошибка сборки файла: {str(e)}")


def extract_text_v1_0(input_path, output_dir, log_callback):
    """
    Версия 1.0 (path_1) распаковки текста.
    CSV формат: Number;File;All Blocks;Work Blocks;Current Block;Unknown;ID;OriginalText
    """
    try:
        if os.path.isdir(input_path):
            y = 0
            k = 0
            for filename in os.listdir(input_path):
                if filename.endswith('.dat'):
                    full_path = os.path.join(input_path, filename)
                    if os.path.isfile(full_path):
                        base_name = os.path.splitext(os.path.basename(full_path))[0]
                        # Для версии 1.0 тоже ограничиваем размер читаемого текста,
                        # чтобы не уходить в бесконечную перепаковку на битых offset/length.
                        file_size = os.path.getsize(full_path)
                        file_size_limit = file_size * 10
                        with open(full_path, 'rb') as f:
                            f.seek(16)
                            code = b''
                            if f.read(4) == b'\xDC\x96\x58\x59':
                                y += 1
                                form = 'w' if y == 1 else 'a'
                                output_path = os.path.join(output_dir, "TextExtractor.csv")
                                file_name = os.path.basename(full_path)
                                f.seek(0)
                                count_full = struct.unpack('<I', f.read(4))[0]
                                f.read(4)
                                count_text = struct.unpack('<I', f.read(4))[0]
                                f.read(12)
                                code = f.read(count_full).hex()
                                f.read(17)
                                data_start = f.tell()
                                with open(output_path, form, newline='', encoding="utf-8") as out_f:
                                    writer = csv.writer(out_f, delimiter=';')
                                    if form == 'w':
                                        writer.writerow(['Number','File','All Blocks','Work Blocks','Current Block','Unknown','ID','OriginalText'])
                                    for i in range(count_full):
                                        f.seek(data_start + (i * 16))
                                        id_hex = f.read(8).hex()
                                        start_text_offset = f.tell()
                                        offset_text = struct.unpack('<I', f.read(4))[0]
                                        length = struct.unpack('<I', f.read(4))[0]

                                        text = ""
                                        if length > 0:
                                            text_offset = start_text_offset + offset_text
                                            # Проверяем валидность смещения (с запасом), как в версии 2.0
                                            if text_offset >= 0 and text_offset + length <= file_size_limit:
                                                f.seek(text_offset)
                                                text = f.read(length).decode('utf-8', errors='ignore')
                                                text = text.replace('\n', '\\n').replace('\r', '\\r')
                                            else:
                                                # Если смещение совсем странное — пишем длину вместо текста,
                                                # чтобы не уезжать за пределы файла.
                                                text = str(length)

                                        k += 1
                                        writer.writerow([str(k), file_name, count_full, count_text, str(i), code[i*2:(i+1)*2], id_hex, text])
                                log_callback(f"Обработан - {base_name}.txt - {count_text}")
        log_callback(f"✅ Распаковка текста завершена в {output_dir}")
        return True
    except Exception as e:
        log_callback(f"❌ Ошибка распаковки (1.0): {str(e)}")
        return False


def extract_text_v2_0(input_path, output_dir, log_callback):
    try:
        if os.path.isdir(input_path):
            y = 0
            k = 0
            # Сортируем файлы по номеру для правильного порядка
            dat_files = [f for f in os.listdir(input_path) if f.endswith('.dat')]
            dat_files.sort(key=lambda x: int(re.search(r'(\d+)\.dat$', x).group(1)) if re.search(r'(\d+)\.dat$', x) else 0)
            
            for filename in dat_files:
                # Пропускаем файл _0.dat (это заголовочный файл контейнера, не текстовый)
                if filename.endswith('_0.dat'):
                    continue
                    
                full_path = os.path.join(input_path, filename)
                if os.path.isfile(full_path):
                    base_name = os.path.splitext(os.path.basename(full_path))[0]
                    # Получаем размер файла для проверки валидности смещений (с запас)
                    file_size = os.path.getsize(full_path)
                    file_size_limit = file_size * 10
                    with open(full_path, 'rb') as f:
                        # Проверяем сигнатуру на позиции 16
                        f.seek(16)
                        signature = f.read(4)
                        if signature == b'\xDC\x96\x58\x59':
                            y += 1
                            if y == 1:
                                form = 'w'
                            else:
                                form = 'a'
                            output_path = os.path.join(output_dir, f"TextExtractor.csv")
                            file_name = os.path.basename(full_path)
                            
                            # Читаем заголовок 
                            f.seek(0)
                            count_full = struct.unpack('<I', f.read(4))[0]  # INT32 (4 байта)
                            
                            # Вычисляем позицию таблицы (GetTableOffset)
                            # Для translate_words_map_*_diff используется формула A (48/56/296/552)
                            if count_full <= 8:
                                table_offset = 24 + 24
                            elif count_full <= 128:
                                table_offset = 32 + 24
                            elif count_full <= 256:
                                table_offset = 272 + 24
                            else:
                                table_offset = 552
                            
                            # Читаем HeaderData (всё между count и table_offset)
                            header_data = f.read(table_offset - 4)
                            header_hex = header_data.hex()  # Сохраняем как hex
                            
                            # Определяем count_text (из HeaderData на позиции 4-8)
                            count_text = struct.unpack('<I', header_data[4:8])[0] if len(header_data) >= 8 else count_full
                            
                            with open(output_path, form, newline='', encoding="utf-8") as out_f:
                                writer = csv.writer(out_f, delimiter=';')
                                if form == 'w':
                                    writer.writerow(['Number','File','All Blocks','Work Blocks','HeaderData','ID','OriginalText'])
                                
                                for i in range(count_full):
                                    # Позиция записи в таблице
                                    entry_offset = table_offset + (i * 16)
                                    f.seek(entry_offset)
                                    
                                    # логика: current = позиция ДО чтения ID
                                    current = f.tell()
                                    
                                    id_bytes = f.read(8)
                                    id_hex = id_bytes.hex()
                                    
                                    offset = struct.unpack('<I', f.read(4))[0]
                                    length = struct.unpack('<I', f.read(4))[0]
                                    
                                    # расчёт: TextOffset = offset + current + 8
                                    text_offset = offset + current + 8
                                    
                                    # Читаем текст
                                    text = ""
                                    if length > 0:
                                        # Проверяем валидность смещения (с запасом)
                                        if text_offset >= 0 and text_offset + length <= file_size_limit:
                                            f.seek(text_offset)
                                            text = f.read(length).decode('utf-8', errors='ignore')
                                            # Заменяем спецсимволы на escape-последовательности для CSV
                                            text = text.replace('\n', '\\n')
                                            text = text.replace('\r', '\\r')
                                        else:
                                            text = str(length)
                                    
                                    k += 1
                                    # HeaderData пишем только для первой записи файла
                                    if i == 0:
                                        writer.writerow([str(k), file_name, count_full, count_text, header_hex, id_hex, text])
                                    else:
                                        writer.writerow([str(k), file_name, count_full, count_text, "", id_hex, text])
                            
                            log_callback(f"Обработан - {base_name}.txt - {count_text}")
        log_callback(f"✅ Распаковка текста завершена в {output_path}")   
        return True
    except Exception as e:
        log_callback(f"❌ Ошибка распаковки: {str(e)}")
        return False

def pak_text_v2_0(input_file, output_dir, log_callback):
    """
    Запаковка текста в .dat файлы (с HeaderData)
    CSV формат: Number;File;All Blocks;Work Blocks;HeaderData;ID;OriginalText
    """
    try:
        base_name = ''
        count_full = 0
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            
            # Переменные для текущего файла
            all_blocks = b''
            header_data = b''
            filled_bytes_id = b''
            filled_bytes_text = b''
            table_offset = 0
            text_entries = []  # Список записей (ID, текст) для текущего файла
            
            for row in reader:
                if row[0] == "Number" or row[1] == 'File':
                    continue
                    
                if row[1] != base_name:
                    # Записываем предыдущий файл
                    if base_name != '' and len(text_entries) > 0:
                        _write_dat_file_csharp(output_dir, base_name, count_full, header_data, text_entries, log_callback)
                    
                    # Начинаем новый файл
                    base_name = str(row[1])
                    count_full = int(row[2])
                    
                    # Читаем HeaderData из CSV (только из первой записи файла)
                    if row[4] and row[4].strip():
                        header_data = bytes.fromhex(row[4])
                    else:
                        # Если HeaderData пустой, создаём дефолтный
                        work_blocks_count = int(row[3])
                        header_data = _create_default_header(count_full, work_blocks_count)
                    
                    # Вычисляем table_offset
                    if count_full == 0:
                        table_offset = 8
                    else:
                        num = (count_full + 16) // 16 * 16
                        table_offset = num + 25
                    
                    text_entries = []
                
                # Обрабатываем текст
                text = (
                    row[6]  # Теперь текст в колонке 6 (было 7)
                    .replace('\\n', '\x0A')
                    .replace('\\r', '\x0D')
                    .encode('utf-8')
                )
                
                # ID (8 байт)
                id_hex = row[5]  # Теперь ID в колонке 5 (было 6)
                
                text_entries.append((id_hex, text))
            
            # Записываем последний файл
            if base_name != '' and len(text_entries) > 0:
                _write_dat_file_csharp(output_dir, base_name, count_full, header_data, text_entries, log_callback)
        
        log_callback(f"✅ Запаковка завершена")            
        return True

    except Exception as e:
        log_callback(f"❌ Ошибка запаковки: {str(e)}")
        return False


def pak_text_v1_0(input_file, output_dir, log_callback):
    """
    Версия 1.0 (path_1) запаковки текста.
    CSV формат: Number;File;All Blocks;Work Blocks;Current Block;Unknown;ID;OriginalText
    """
    try:
        base_name = ''
        with open(input_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            start_unk = 0
            start_id = 0
            curr_text = 0
            all_blocks = b''
            work_blocks = b''
            filled_bytes_unk = b''
            filled_bytes_id = b''
            filled_bytes_text = b''
            for row in reader:
                if row[0] == "Number" or row[1] == 'File':
                    continue

                if row[1] != base_name:
                    form = 'wb'
                    if base_name != '':
                        output_path = os.path.join(output_dir, base_name)
                        with open(output_path, form) as out_f:
                            out_f.write(all_blocks)
                            out_f.write(work_blocks)
                            out_f.write(file_bytes)
                            out_f.write(filled_bytes_unk)
                            out_f.write(filled_bytes_id)
                            out_f.write(filled_bytes_text)
                    base_name = str(row[1])
                else:
                    form = 'ab'

                if form == 'wb':
                    all_blocks = struct.pack('<II', int(row[2]), 0)
                    work_blocks = struct.pack('<II', int(row[3]), 0)
                    file_bytes = b'\xDC\x96\x58\x59\x00\x00\x00\x00'
                    filled_bytes_unk = b''
                    filled_bytes_id = b''
                    filled_bytes_text = b''
                    start_unk = len(all_blocks) + len(work_blocks) + len(file_bytes)
                    start_id = start_unk + int(row[2]) + 17
                    curr_text = start_id + int(row[2]) * 16

                text = row[7].replace('\\n', '\x0A').encode('utf-8')
                unk_byte = bytes.fromhex(row[5])
                filled_bytes_unk += unk_byte
                start_unk += 1
                if start_unk >= int(row[2]) + 24:
                    if len(filled_bytes_unk) >= 16:
                        filled_bytes_unk += b'\xFF' + filled_bytes_unk[:16]
                    else:
                        filled_bytes_unk += b'\xFF' + filled_bytes_unk + b'\x80' * (16 - len(filled_bytes_unk))
                id_byte = bytes.fromhex(row[6])
                filled_bytes_id += id_byte
                start_id += 8
                offset_len = struct.pack('<II', (curr_text - start_id), len(text))
                filled_bytes_id += offset_len
                start_id += 8
                filled_bytes_text += text
                curr_text += len(text)
            if base_name:
                output_path = os.path.join(output_dir, base_name)
                with open(output_path, form) as out_f:
                    out_f.write(all_blocks)
                    out_f.write(work_blocks)
                    out_f.write(file_bytes)
                    out_f.write(filled_bytes_unk)
                    out_f.write(filled_bytes_id)
                    out_f.write(filled_bytes_text)
        log_callback("✅ Запаковка завершена (1.0)")
        return True

    except Exception as e:
        log_callback(f"❌ Ошибка запаковки (1.0): {str(e)}")
        return False


def _create_default_header(count_full, work_blocks_count):
    """Создаёт дефолтный HeaderData если его нет в CSV"""
    # work_blocks (4 байта) + padding (4 байта)
    header = struct.pack('<II', work_blocks_count, 0)
    # Сигнатура (8 байт)
    header += b'\xDC\x96\x58\x59\x00\x00\x00\x00'
    # Unknown bytes (count_full байт по 0x80)
    header += b'\x80' * count_full
    # 0xFF маркер
    header += b'\xFF'
    # Паддинг до table_offset
    if count_full == 0:
        table_offset = 8
    else:
        num = (count_full + 16) // 16 * 16
        table_offset = num + 25
    padding_needed = table_offset - 4 - len(header)
    if padding_needed > 0:
        header += b'\x80' * padding_needed
    return header


def _write_dat_file_csharp(output_dir, filename, count, header_data, text_entries, log_callback):
    """
    Записывает .dat файл редактора
    header_data: весь блок между count и ID таблицей
    text_entries: список кортежей (id_hex, text_bytes)
    """
    try:
        output_path = os.path.join(output_dir, filename)
        
        with open(output_path, 'wb') as out_f:
            # 1. Пишем count (4 байта)
            out_f.write(struct.pack('<I', count))
            
            # 2. Пишем HeaderData
            out_f.write(header_data)
            
            # 3. Пишем нули для ID таблицы (заполним позже)
            table_start = out_f.tell()
            zeros = b'\x00' * 16
            for i in range(count):
                out_f.write(zeros)
            
            # 4. Пишем тексты и заполняем ID таблицу
            for i, (id_hex, text_bytes) in enumerate(text_entries):
                # Позиция текущего текста
                text_offset = out_f.tell()
                out_f.write(text_bytes)
                
                # Вычисляем offset для ID таблицы
                table_entry_pos = table_start + (i * 16)
                offset = text_offset - table_entry_pos - 8
                length = len(text_bytes)
                
                # Записываем в ID таблицу
                current_pos = out_f.tell()
                out_f.seek(table_entry_pos)
                out_f.write(bytes.fromhex(id_hex))
                out_f.write(struct.pack('<II', offset, length))
                out_f.seek(current_pos)
        
    except Exception as e:
        log_callback(f"❌ Ошибка записи файла {filename}: {str(e)}")


def extract_text(input_path, output_dir, log_callback):
    """
    Обёртка над версиями 1.0 и 2.0 распаковки текста.
    Выбор версии задаётся кодом CURRENT_TEXT_PATH (path_1 или path_2).
    """
    if CURRENT_TEXT_PATH == TEXT_FORMAT_PATH_1:
        log_callback("▶ Используется версия распаковки 1.0")
        return extract_text_v1_0(input_path, output_dir, log_callback)
    else:
        log_callback("▶ Используется версия распаковки 2.0")
        return extract_text_v2_0(input_path, output_dir, log_callback)


def pak_text(input_file, output_dir, log_callback):
    """
    Обёртка над версиями 1.0 и 2.0 запаковки текста.
    Выбор версии задаётся кодом CURRENT_TEXT_PATH (path_1 или path_2).
    """
    if CURRENT_TEXT_PATH == TEXT_FORMAT_PATH_1:
        log_callback("▶ Используется версия запаковки 1.0")
        return pak_text_v1_0(input_file, output_dir, log_callback)
    else:
        log_callback("▶ Используется версия запаковки 2.0")
        return pak_text_v2_0(input_file, output_dir, log_callback)


def extract_all(input_file, output_dir, log_callback):
    """
    Обобщённая функция:
    1) распаковывает контейнер в подпапку data (extract_file);
    2) извлекает текст из получившихся .dat в подпапку text (extract_text).
    """
    try:
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        data_dir = os.path.join(output_dir, "data")
        text_dir = os.path.join(output_dir, "text")

        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(text_dir, exist_ok=True)

        log_callback(f"▶ Полная распаковка для: {input_file}")
        log_callback(f"   data → {data_dir}")
        log_callback(f"   text → {text_dir}")

        # Шаг 1: распаковка файлов
        ok_files = extract_file(input_file, data_dir, log_callback)
        if not ok_files:
            log_callback("❌ Полная распаковка: ошибка на этапе распаковки файлов")
            return False

        # Шаг 2: извлечение текста из распакованных .dat
        ok_text = extract_text(data_dir, text_dir, log_callback)
        if not ok_text:
            log_callback("❌ Полная распаковка: ошибка на этапе извлечения текста")
            return False

        log_callback(f"✅ Полная распаковка завершена. DAT в папке: {data_dir}, CSV в папке: {text_dir}")
        return True
    except Exception as e:
        log_callback(f"❌ Ошибка полной распаковки: {str(e)}")
        return False


def pak_file_custom(input_dir, output_file, log_callback):
    """
    Вариант pak_file с явным именем итогового файла.
    """
    try:
        files = [f for f in os.listdir(input_dir) if f.endswith('.dat')]

        def extract_number(filename):
            match = re.search(r'(\d+)\.dat$', filename)
            return int(match.group(1)) if match else float('inf')

        files.sort(key=extract_number)

        if not files:
            log_callback("❌ В папке с данными нет ни одного .dat файла для сборки")
            return False

        with open(output_file, 'wb') as outfile:
            outfile.write(b'\xEF\xBE\xAD\xDE\x01\x00\x00\x00')
            count_files = struct.pack('<I', len(files))
            outfile.write(count_files)
            archive = b''
            for filename in files:
                file_path = os.path.join(input_dir, filename)
                file_size = os.path.getsize(file_path)
                with open(file_path, 'rb') as infile:
                    comp_data = pyzstd.compress(infile.read())
                    header = struct.pack('<BII', 4, len(comp_data), file_size)
                    len_arch = struct.pack('<I', len(archive))
                    outfile.write(len_arch)
                    archive += header + comp_data
                log_callback(f"Обработан: {filename}")

            len_arch = struct.pack('<I', len(archive))
            outfile.write(len_arch)
            outfile.write(archive)

        log_callback(f"✅ Сборка завершена. Файл сохранен как: {output_file}")
        return True
    except Exception as e:
        log_callback(f"❌ Ошибка сборки файла: {str(e)}")
        return False


def full_pack(base_dir, trans_path, output_file, log_callback):
    """
    Полная запаковка:
    1) берёт text/TextExtractor.csv и файл перевода (CSV/TSV: ID,OriginalText);
    2) создаёт text/TextExtractor_new.csv с подставленными переводами;
    3) из TextExtractor_new.csv пересобирает .dat-файлы прямо в существующей папке data/;
       (файл вида *_0.dat с «шапкой» остаётся нетронутым);
    4) из папки data/ собирает итоговый bin-файл с указанным именем.
    """
    try:
        if not base_dir:
            log_callback("❌ Полная запаковка: базовая папка не задана")
            return False
        if not trans_path or not os.path.isfile(trans_path):
            log_callback("❌ Полная запаковка: файл перевода не найден")
            return False
        if not output_file:
            log_callback("❌ Полная запаковка: путь итогового файла не задан")
            return False

        text_dir = os.path.join(base_dir, "text")
        data_dir = os.path.join(base_dir, "data")
        textextractor_path = os.path.join(text_dir, "TextExtractor.csv")

        if not os.path.isdir(text_dir) or not os.path.isdir(data_dir):
            log_callback("❌ Полная запаковка: в выбранной папке нет подпапок data и text")
            return False
        if not os.path.isfile(textextractor_path):
            log_callback("❌ Полная запаковка: не найден text/TextExtractor.csv")
            return False

        dat_files = [f for f in os.listdir(data_dir) if f.endswith(".dat")]
        if not dat_files:
            log_callback("❌ Полная запаковка: в папке data нет ни одного .dat файла")
            return False

        log_callback(f"▶ Полная запаковка для папки: {base_dir}")
        log_callback(f"   Файл перевода: {trans_path}")
        log_callback(f"   Исходный TextExtractor.csv: {textextractor_path}")

        # 1. Читаем файл перевода и строим словарь ID -> текст
        ext = os.path.splitext(trans_path)[1].lower()
        if ext == '.tsv':
            delim = '\t'
        else:
            delim = ';'

        translations = {}
        try:
            with open(trans_path, 'r', encoding='utf-8', newline='') as tf:
                reader = csv.reader(tf, delimiter=delim)
                header = next(reader, None)
                if header:
                    try:
                        id_idx = header.index('ID')
                        text_idx = header.index('OriginalText')
                    except ValueError:
                        id_idx = 0
                        text_idx = 1
                        if len(header) > 1 and header[0].strip():
                            translations[header[0].strip()] = header[1]
                for row in reader:
                    if len(row) <= max(id_idx, text_idx):
                        continue
                    key = row[id_idx].strip()
                    if not key:
                        continue
                    text = row[text_idx]
                    text = text.replace('\n', '\\n').replace('\r', '\\r')
                    translations[key] = text
        except Exception as e:
            log_callback(f"❌ Полная запаковка: ошибка чтения файла перевода: {str(e)}")
            return False

        if not translations:
            log_callback("❌ Полная запаковка: в файле перевода не найдено ни одной строки с ID")
            return False

        # 2. Создаём TextExtractor_new.csv на основе оригинального TextExtractor.csv
        new_csv_path = os.path.join(text_dir, "TextExtractor_new.csv")
        try:
            replaced = 0
            total = 0
            with open(textextractor_path, 'r', encoding='utf-8', newline='') as src_f, \
                 open(new_csv_path, 'w', encoding='utf-8', newline='') as out_f:

                reader = csv.reader(src_f, delimiter=';')
                writer = csv.writer(out_f, delimiter=';')

                header = next(reader, None)
                if not header:
                    log_callback("❌ Полная запаковка: в TextExtractor.csv нет заголовка")
                    return False

                writer.writerow(header)

                try:
                    id_idx_csv = header.index('ID')
                    text_idx_csv = header.index('OriginalText')
                except ValueError:
                    log_callback("❌ Полная запаковка: в TextExtractor.csv не найдены колонки 'ID' и 'OriginalText'")
                    return False

                for row in reader:
                    if len(row) <= max(id_idx_csv, text_idx_csv):
                        writer.writerow(row)
                        continue
                    total += 1
                    key = row[id_idx_csv]
                    if key in translations:
                        row[text_idx_csv] = translations[key]
                        replaced += 1
                    writer.writerow(row)

            log_callback(f"✅ Создан TextExtractor_new.csv: {new_csv_path} (заменено строк: {replaced} из {total})")
        except Exception as e:
            log_callback(f"❌ Полная запаковка: ошибка при создании TextExtractor_new.csv: {str(e)}")
            return False

        # 3. Запаковка текста в .dat прямо в существующую папку data/
        #    Здесь обновляются только те файлы, которые есть в TextExtractor_new.csv.
        #    «Шапочный» файл вида *_0.dat (без текста) остаётся как есть.
        log_callback(f"▶ Запаковка текста в DAT (папка: {data_dir})")
        ok_text = pak_text(new_csv_path, data_dir, log_callback)
        if not ok_text:
            log_callback("❌ Полная запаковка: ошибка на этапе запаковки текста")
            return False

        # 4. Сборка итогового bin-файла из основной папки data/
        log_callback(f"▶ Сборка итогового файла: {output_file}")
        ok_file = pak_file_custom(data_dir, output_file, log_callback)
        if not ok_file:
            log_callback("❌ Полная запаковка: ошибка на этапе сборки итогового файла")
            return False

        log_callback(f"✅ Полная запаковка завершена. Итоговый файл: {output_file}")
        return True
    except Exception as e:
        log_callback(f"❌ Ошибка полной запаковки: {str(e)}")
        return False
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)

    def __init__(self, input_path, output_dir, func, extra=None):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.func = func
        self.extra = extra

    def run(self):
        if self.func == 1:
            extract_file(self.input_path, self.output_dir, self.log_signal.emit)
        elif self.func == 2:
            pak_file(self.input_path, self.output_dir, self.log_signal.emit)
        elif self.func == 3:
            extract_text(self.input_path, self.output_dir, self.log_signal.emit)
        elif self.func == 4:
            pak_text(self.input_path, self.output_dir, self.log_signal.emit)
        elif self.func == 5:
            extract_all(self.input_path, self.output_dir, self.log_signal.emit)
        elif self.func == 6:
            # Полная запаковка (data + text → итоговый файл)
            # input_path: базовая папка с data/ и text/
            # output_dir: полный путь к итоговому .bin файлу
            # extra: словарь с ключом trans_path
            trans_path = None
            if isinstance(self.extra, dict):
                trans_path = self.extra.get("trans_path")
            full_pack(self.input_path, trans_path, self.output_dir, self.log_signal.emit)

class MyApp(QWidget):
    def __init__(self):
        super().__init__()
        self.config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        # Язык интерфейса по умолчанию / из конфига
        self.current_lang = self._load_language_from_config()
        self.initUI()

    def _load_language_from_config(self):
        """Читает выбранный язык из config.ini, по умолчанию 'en'."""
        config = configparser.ConfigParser()
        if os.path.isfile(self.config_path):
            try:
                config.read(self.config_path, encoding="utf-8")
            except Exception:
                config = None
        else:
            config = None

        if config and "settings" in config:
            lang = config["settings"].get("language", "en").strip() or "en"
            return lang
        return "en"

    def _t(self, key):
        """Возврат текста для текущего языка интерфейса."""
        table = LANG_UI.get(self.current_lang, LANG_UI["en"])
        # fallback к en и самому ключу
        return table.get(key, LANG_UI["en"].get(key, key))

    def initUI(self):
        # Основной layout в виде сетки 2 колонки:
        # [ Переключатель языка ]          (100%)
        # [ Полная распаковка ]            (100%)
        # [ Распаковка файла ] [ Распаковка текста ]
        # [ Запаковка текста ] [ Запаковка файла ]
        # [ Перевод по ID ]                (100%) + лог
        main_layout = QGridLayout()
        main_layout.setColumnStretch(0, 1)
        main_layout.setColumnStretch(1, 1)

        # Переключатель языка интерфейса
        lang_widget = QWidget()
        lang_layout = QHBoxLayout()
        lang_layout.setContentsMargins(5, 5, 5, 5)

        lang_label = QLabel(self._t("ui_lang_label"))
        self.lang_combo = QComboBox()
        # По умолчанию English
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("Русский", "ru")
        # Зарезервировано под будущие языки
        # self.lang_combo.addItem("中文", "zh")

        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)
        lang_layout.addStretch(1)
        lang_widget.setLayout(lang_layout)

        # Создаем QGroupBox с локализованными заголовками
        group_box_extr_files = QGroupBox(self._t("group_extract_files"))
        group_box_pack_files = QGroupBox(self._t("group_pack_files"))
        group_box_extr_texts = QGroupBox(self._t("group_extract_texts"))
        group_box_pack_texts = QGroupBox(self._t("group_pack_texts"))
        group_box_translate = QGroupBox(self._t("group_translate"))
        group_box_full_extract = QGroupBox(self._t("group_full_extract"))
        group_box_full_pack = QGroupBox(self._t("group_full_pack"))

        # Создаем QPushButton's в "Распаковка файлов"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonEF_select_file = QPushButton(self._t("btn_select_file"))
        self.labelEF_select_file = QLabel('Файл не выбран')
        self.labelEF_select_file.setWordWrap(True)
        buttonEF_select_file.clicked.connect(self.selectEF_input_file)
        group_layout.addWidget(buttonEF_select_file, 0, 0)
        group_layout.addWidget(self.labelEF_select_file, 0, 1)
        
        buttonEF_output_folder = QPushButton(self._t("btn_output_folder"))
        self.labelEF_output_folder = QLabel('Папка не выбрана')
        self.labelEF_output_folder.setWordWrap(True)
        buttonEF_output_folder.clicked.connect(self.selectEF_output_dir)
        group_layout.addWidget(buttonEF_output_folder, 1, 0)
        group_layout.addWidget(self.labelEF_output_folder, 1, 1)

        buttonEF_run = QPushButton(self._t("btn_run_extract_file"))
        buttonEF_run.setStyleSheet("background: #2196F3; color: white; font-weight: bold;")
        buttonEF_run.clicked.connect(self.start_processing1)
        group_layout.addWidget(buttonEF_run, 2, 0, 1, 0)
        group_box_extr_files.setLayout(group_layout)

        # Создаем QPushButton's в "Запаковка файлов"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonPF_select_folder = QPushButton(self._t("btn_select_folder"))
        self.labelPF_select_folder = QLabel('Папка не выбрана')
        self.labelPF_select_folder.setWordWrap(True)
        buttonPF_select_folder.clicked.connect(self.selectPF_input_dir)
        group_layout.addWidget(buttonPF_select_folder, 0, 0)
        group_layout.addWidget(self.labelPF_select_folder, 0, 1)
        
        buttonPF_output_folder = QPushButton(self._t("btn_output_folder"))
        self.labelPF_output_folder = QLabel('Папка не выбрана')
        self.labelPF_output_folder.setWordWrap(True)
        buttonPF_output_folder.clicked.connect(self.selectPF_output_dir)
        group_layout.addWidget(buttonPF_output_folder, 1, 0)
        group_layout.addWidget(self.labelPF_output_folder, 1, 1)

        buttonPF_run = QPushButton(self._t("btn_run_pack_file"))
        buttonPF_run.setStyleSheet("background: #4CAF50; color: white; font-weight: bold;")
        buttonPF_run.clicked.connect(self.start_processing2)
        group_layout.addWidget(buttonPF_run, 2, 0, 1, 0)
        group_box_pack_files.setLayout(group_layout)

        # Создаем QPushButton's в "Полная распаковка (файл → data + text)"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonFE_select_file = QPushButton(self._t("btn_select_file"))
        self.labelFE_select_file = QLabel('Файл не выбран')
        self.labelFE_select_file.setWordWrap(True)
        buttonFE_select_file.clicked.connect(self.selectFE_input_file)
        group_layout.addWidget(buttonFE_select_file, 0, 0)
        group_layout.addWidget(self.labelFE_select_file, 0, 1)

        buttonFE_output_folder = QPushButton(self._t("btn_full_output_folder"))
        self.labelFE_output_folder = QLabel('Папка не выбрана')
        self.labelFE_output_folder.setWordWrap(True)
        buttonFE_output_folder.clicked.connect(self.selectFE_output_dir)
        group_layout.addWidget(buttonFE_output_folder, 1, 0)
        group_layout.addWidget(self.labelFE_output_folder, 1, 1)

        buttonFE_run = QPushButton(self._t("btn_full_run"))
        buttonFE_run.setStyleSheet("background: #9C27B0; color: white; font-weight: bold;")
        buttonFE_run.clicked.connect(self.start_processing5)
        group_layout.addWidget(buttonFE_run, 2, 0, 1, 0)
        group_box_full_extract.setLayout(group_layout)

        # Создаем QPushButton's в "Полная запаковка (data + text → файл)"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonFP_base_folder = QPushButton(self._t("btn_full_pack_base_folder"))
        self.labelFP_base_folder = QLabel('Папка не выбрана')
        self.labelFP_base_folder.setWordWrap(True)
        buttonFP_base_folder.clicked.connect(self.selectFP_base_folder)
        group_layout.addWidget(buttonFP_base_folder, 0, 0)
        group_layout.addWidget(self.labelFP_base_folder, 0, 1)

        buttonFP_trans_file = QPushButton(self._t("btn_full_pack_trans_file"))
        self.labelFP_trans_file = QLabel('Файл не выбран')
        self.labelFP_trans_file.setWordWrap(True)
        buttonFP_trans_file.clicked.connect(self.selectFP_trans_file)
        group_layout.addWidget(buttonFP_trans_file, 1, 0)
        group_layout.addWidget(self.labelFP_trans_file, 1, 1)

        buttonFP_output_file = QPushButton(self._t("btn_full_pack_output_file"))
        self.labelFP_output_file = QLabel('Файл не выбран')
        self.labelFP_output_file.setWordWrap(True)
        buttonFP_output_file.clicked.connect(self.selectFP_output_file)
        group_layout.addWidget(buttonFP_output_file, 2, 0)
        group_layout.addWidget(self.labelFP_output_file, 2, 1)

        buttonFP_run = QPushButton(self._t("btn_full_pack_run"))
        buttonFP_run.setStyleSheet("background: #9C27B0; color: white; font-weight: bold;")
        buttonFP_run.clicked.connect(self.start_processing6)
        group_layout.addWidget(buttonFP_run, 3, 0, 1, 0)

        group_box_full_pack.setLayout(group_layout)

        # Создаем QPushButton's в "Распаковка текста"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonET_select_folder = QPushButton(self._t("btn_select_folder"))
        self.labelET_select_folder = QLabel('Папка не выбрана')
        self.labelET_select_folder.setWordWrap(True)
        buttonET_select_folder.clicked.connect(self.selectET_input_dir)
        group_layout.addWidget(buttonET_select_folder, 0, 0)
        group_layout.addWidget(self.labelET_select_folder, 0, 1)
        
        buttonET_output_folder = QPushButton(self._t("btn_output_folder"))
        self.labelET_output_folder = QLabel('Папка не выбрана')
        self.labelET_output_folder.setWordWrap(True)
        buttonET_output_folder.clicked.connect(self.selectET_output_dir)
        group_layout.addWidget(buttonET_output_folder, 1, 0)
        group_layout.addWidget(self.labelET_output_folder, 1, 1)

        buttonET_run = QPushButton(self._t("btn_extract_texts_run"))
        buttonET_run.setStyleSheet("background: #2196F3; color: white; font-weight: bold;")
        buttonET_run.clicked.connect(self.start_processing3)
        group_layout.addWidget(buttonET_run, 2, 0, 1, 0)
        group_box_extr_texts.setLayout(group_layout)

        # Создаем QPushButton's в "Запаковка текста"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonPT_select_file = QPushButton(self._t("btn_select_file"))
        self.labelPT_select_file = QLabel('Файл не выбран')
        self.labelPT_select_file.setWordWrap(True)
        buttonPT_select_file.clicked.connect(self.selectPT_input_file)
        group_layout.addWidget(buttonPT_select_file, 0, 0)
        group_layout.addWidget(self.labelPT_select_file, 0, 1)
        
        buttonPT_output_folder = QPushButton(self._t("btn_output_folder"))
        self.labelPT_output_folder = QLabel('Папка не выбрана')
        self.labelPT_output_folder.setWordWrap(True)
        buttonPT_output_folder.clicked.connect(self.selectPT_output_dir)
        group_layout.addWidget(buttonPT_output_folder, 1, 0)
        group_layout.addWidget(self.labelPT_output_folder, 1, 1)

        buttonPT_run = QPushButton(self._t("btn_pack_text_run"))
        buttonPT_run.setStyleSheet("background: #4CAF50; color: white; font-weight: bold;")
        buttonPT_run.clicked.connect(self.start_processing4)
        group_layout.addWidget(buttonPT_run, 2, 0, 1, 0)
        group_box_pack_texts.setLayout(group_layout)

        # Создаем QPushButton's в "Перевод по ID"
        group_layout = QGridLayout()
        group_layout.setColumnMinimumWidth(0, 250)
        group_layout.setColumnStretch(0, 0)
        group_layout.setColumnStretch(1, 1)

        buttonTR_select_file = QPushButton(self._t("btn_tr_select_file"))
        self.labelTR_select_file = QLabel('Файл не выбран')
        self.labelTR_select_file.setWordWrap(True)
        buttonTR_select_file.clicked.connect(self.selectTR_input_file)
        group_layout.addWidget(buttonTR_select_file, 0, 0)
        group_layout.addWidget(self.labelTR_select_file, 0, 1)

        labelTR_format = QLabel(self._t("label_tr_format"))
        self.comboTR_format = QComboBox()
        self.comboTR_format.addItem("CSV (; разделитель)", ";")
        self.comboTR_format.addItem("TSV (табуляция)", "\t")
        group_layout.addWidget(labelTR_format, 1, 0)
        group_layout.addWidget(self.comboTR_format, 1, 1)

        # Выбор версии формата текста (1.0 / 2.0)
        label_text_path = QLabel(self._t("label_text_path"))
        self.comboTextPath = QComboBox()
        self.comboTextPath.addItem("1.0 (path_1)", TEXT_FORMAT_PATH_1)
        self.comboTextPath.addItem("2.0 (path_2)", TEXT_FORMAT_PATH_2)
        group_layout.addWidget(label_text_path, 2, 0)
        group_layout.addWidget(self.comboTextPath, 2, 1)

        buttonTR_export = QPushButton(self._t("btn_tr_export"))
        buttonTR_export.setStyleSheet("background: #2196F3; color: white; font-weight: bold;")
        buttonTR_export.clicked.connect(self.export_translation_csv)
        group_layout.addWidget(buttonTR_export, 3, 0, 1, 0)

        buttonTR_apply = QPushButton(self._t("btn_tr_apply"))
        buttonTR_apply.setStyleSheet("background: #4CAF50; color: white; font-weight: bold;")
        buttonTR_apply.clicked.connect(self.apply_translation_csv)
        group_layout.addWidget(buttonTR_apply, 4, 0, 1, 0)

        buttonTR_debug = QPushButton(self._t("btn_tr_debug"))
        buttonTR_debug.setStyleSheet("background: #FF9800; color: white; font-weight: bold;")
        buttonTR_debug.clicked.connect(self.create_debug_csv)
        group_layout.addWidget(buttonTR_debug, 5, 0, 1, 0)

        buttonTR_validate = QPushButton(self._t("btn_tr_validate"))
        buttonTR_validate.setStyleSheet("background: #607D8B; color: white; font-weight: bold;")
        buttonTR_validate.clicked.connect(self.validate_textextractor_csv)
        group_layout.addWidget(buttonTR_validate, 6, 0, 1, 0)

        group_box_translate.setLayout(group_layout)
        
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        # Раскладка по строкам/колонкам
        # 0: Переключатель языка — на всю ширину
        main_layout.addWidget(lang_widget, 0, 0, 1, 2)
        # 1: Полная распаковка — на всю ширину
        main_layout.addWidget(group_box_full_extract, 1, 0, 1, 2)
        # 2: Полная запаковка — на всю ширину
        main_layout.addWidget(group_box_full_pack, 2, 0, 1, 2)
        # 3: Распаковка файла / Распаковка текста
        main_layout.addWidget(group_box_extr_files, 3, 0)
        main_layout.addWidget(group_box_extr_texts, 3, 1)
        # 4: Запаковка текста / Запаковка файлов
        main_layout.addWidget(group_box_pack_texts, 4, 0)
        main_layout.addWidget(group_box_pack_files, 4, 1)
        # 5: Перевод по ID — на всю ширину
        main_layout.addWidget(group_box_translate, 5, 0, 1, 2)
        # 6: Лог — на всю ширину
        main_layout.addWidget(self.log_box, 6, 0, 1, 2)

        self.setLayout(main_layout)

        # Применяем вычитанный из конфига язык к комбобоксу
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == self.current_lang:
                self.lang_combo.setCurrentIndex(i)
                break
        # Текущий путь формата текста (по умолчанию 2.0)
        for i in range(self.comboTextPath.count()):
            if self.comboTextPath.itemData(i) == CURRENT_TEXT_PATH:
                self.comboTextPath.setCurrentIndex(i)
                break

        # Сохраняем язык и путь при смене пользователем
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        self.comboTextPath.currentIndexChanged.connect(self.on_text_path_changed)

        self.EFinput_path = None
        self.EFoutput_dir = None
        self.ETinput_path = None
        self.EToutput_dir = None
        self.PFinput_path = None
        self.PFoutput_dir = None
        self.PTinput_path = None
        self.PToutput_dir = None
        self.TRinput_path = None
        self.FEinput_path = None
        self.FEoutput_dir = None
        self.FP_base_dir = None
        self.FP_trans_path = None
        self.FP_output_file = None

        # Загружаем сохранённые пути, если есть
        self.load_paths_config()

        self.setWindowTitle("WWM Распаковка/Запаковка файлов и текста")
        self.setGeometry(100, 100, 800, 600)
        self.show()

    def load_paths_config(self):
        """Загрузка путей из config.ini и установка лейблов, если файлы/папки существуют."""
        config = configparser.ConfigParser()
        if not os.path.isfile(self.config_path):
            return

        try:
            config.read(self.config_path, encoding="utf-8")
        except Exception:
            return

        if "paths" not in config and "settings" not in config:
            return

        # Секция путей может отсутствовать — тогда просто не заполняем пути
        if "paths" in config:
            paths = config["paths"]
        else:
            paths = {}

        def _set_path(attr_name, label, key, is_dir):
            value = paths.get(key, "").strip()
            if not value:
                return
            if is_dir and not os.path.isdir(value):
                return
            if not is_dir and not os.path.isfile(value):
                return
            setattr(self, attr_name, value)
            if label is not None:
                label.setText(value)

        _set_path("EFinput_path", self.labelEF_select_file, "EFinput_path", False)
        _set_path("EFoutput_dir", self.labelEF_output_folder, "EFoutput_dir", True)
        _set_path("ETinput_path", self.labelET_select_folder, "ETinput_path", True)
        _set_path("EToutput_dir", self.labelET_output_folder, "EToutput_dir", True)
        _set_path("PFinput_path", self.labelPF_select_folder, "PFinput_path", True)
        _set_path("PFoutput_dir", self.labelPF_output_folder, "PFoutput_dir", True)
        _set_path("PTinput_path", self.labelPT_select_file, "PTinput_path", False)
        _set_path("PToutput_dir", self.labelPT_output_folder, "PToutput_dir", True)
        _set_path("TRinput_path", self.labelTR_select_file, "TRinput_path", False)
        _set_path("FEinput_path", self.labelFE_select_file, "FEinput_path", False)
        _set_path("FEoutput_dir", self.labelFE_output_folder, "FEoutput_dir", True)
        _set_path("FP_base_dir", self.labelFP_base_folder, "FP_base_dir", True)
        _set_path("FP_trans_path", self.labelFP_trans_file, "FP_trans_path", False)
        _set_path("FP_output_file", self.labelFP_output_file, "FP_output_file", False)

        # Загрузка настроек (язык интерфейса, путь формата текста)
        if "settings" in config:
            settings = config["settings"]
            lang_code = settings.get("language", "en").strip() or "en"
            # Подбираем элемент комбобокса по data
            for i in range(self.lang_combo.count()):
                if self.lang_combo.itemData(i) == lang_code:
                    self.lang_combo.setCurrentIndex(i)
                    break

            text_path = settings.get("text_path", TEXT_FORMAT_PATH_2).strip() or TEXT_FORMAT_PATH_2
            global CURRENT_TEXT_PATH
            CURRENT_TEXT_PATH = text_path
            if hasattr(self, "comboTextPath"):
                for i in range(self.comboTextPath.count()):
                    if self.comboTextPath.itemData(i) == text_path:
                        self.comboTextPath.setCurrentIndex(i)
                        break

    def save_paths_config(self):
        """Сохранение текущих путей в config.ini."""
        config = configparser.ConfigParser()
        if os.path.isfile(self.config_path):
            try:
                config.read(self.config_path, encoding="utf-8")
            except Exception:
                config = configparser.ConfigParser()

        if "paths" not in config:
            config["paths"] = {}
        paths = config["paths"]
        for key in [
            "EFinput_path", "EFoutput_dir",
            "ETinput_path", "EToutput_dir",
            "PFinput_path", "PFoutput_dir",
            "PTinput_path", "PToutput_dir",
            "TRinput_path",
            "FEinput_path", "FEoutput_dir",
            "FP_base_dir", "FP_trans_path", "FP_output_file",
        ]:
            value = getattr(self, key, None)
            if value:
                paths[key] = value

        # Секция настроек (в том числе язык интерфейса)
        if "settings" not in config:
            config["settings"] = {}
        settings = config["settings"]
        if hasattr(self, "lang_combo"):
            current_lang = self.lang_combo.currentData()
            if current_lang:
                settings["language"] = current_lang

        if hasattr(self, "comboTextPath"):
            current_path = self.comboTextPath.currentData()
            if current_path:
                settings["text_path"] = current_path

        try:
            with open(self.config_path, "w", encoding="utf-8") as cfg:
                config.write(cfg)
        except Exception:
            pass

    def on_language_changed(self, index):
        """Обработчик смены языка в комбобоксе — просто сохраняем в config.ini."""
        data = self.lang_combo.itemData(index)
        if data:
            self.current_lang = data
            # Пересохраняем настройки (включая language)
            self.save_paths_config()

    def on_text_path_changed(self, index):
        """Обработчик смены версии формата текста (1.0 / 2.0)."""
        data = self.comboTextPath.itemData(index)
        if data:
            global CURRENT_TEXT_PATH
            CURRENT_TEXT_PATH = data
            self.save_paths_config()

    # Функция записи в лог
    def log(self, message):
        self.log_box.append(message)

    # Функция открытия файла для распаковки файла
    def selectEF_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл для распаковки файла")
        if file_path:
            self.EFinput_path = file_path
            self.log(f"Для распаковки файла выбран файл: {file_path}")
            self.labelEF_select_file.setText(f"{file_path}")
            self.save_paths_config()
            
    # Функция открытия папки сохранения для распаковки файла
    def selectEF_output_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку сохранения для распаковки файла")
        if folder_path:
            self.EFoutput_dir = folder_path
            self.log(f"Для распаковки файла выбрана папка сохранения: {folder_path}")
            self.labelEF_output_folder.setText(f"{folder_path}")
            self.save_paths_config()

    # Функция открытия папки с *.dat файлами для запаковки файла
    def selectPF_input_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку с *.dat файлами для запаковки файла")
        if folder_path:
            self.PFinput_path = folder_path
            self.log(f"Для запаковки файла выбрана папка с dat: {folder_path}")
            self.labelPF_select_folder.setText(f"{folder_path}")
            self.save_paths_config()
            
    # Функция открытия папки сохранения для запаковки файла
    def selectPF_output_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку сохранения для запаковки файла")
        if folder_path:
            self.PFoutput_dir = folder_path
            self.log(f"Для запаковки файла выбрана папка сохранения: {folder_path}")
            self.labelPF_output_folder.setText(f"{folder_path}")
            self.save_paths_config()
            
    # Функция открытия папки с *.dat файлами для распаковки текста
    def selectET_input_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку с *.dat файлами для распаковки текста")
        if folder_path:
            self.ETinput_path = folder_path
            self.log(f"Для распаковки текста выбрана папка с *.dat: {folder_path}")
            self.labelET_select_folder.setText(f"{folder_path}")
            self.save_paths_config()
            
    # Функция открытия папки сохранения для распаковки текста
    def selectET_output_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку сохранения для распаковки текста")
        if folder_path:
            self.EToutput_dir = folder_path
            self.log(f"Для распаковки текста выбрана папка сохранения: {folder_path}")
            self.labelET_output_folder.setText(f"{folder_path}")
            self.save_paths_config()

    # Функция выбора TextExtractor.csv для работы с переводом
    def selectTR_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите TextExtractor.csv", filter='*.csv')
        if file_path:
            self.TRinput_path = file_path
            self.log(f"Для перевода выбран файл: {file_path}")
            self.labelTR_select_file.setText(f"{file_path}")
            self.save_paths_config()
            
    # Функция открытия файла CSV для запаковки текста
    def selectPT_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл CSV для запаковки текста", filter='*.csv')
        if file_path:
            self.PTinput_path = file_path
            self.log(f"Для запаковки текста выбран файл: {file_path}")
            self.labelPT_select_file.setText(f"{file_path}")
            self.save_paths_config()
            
    # Функция открытия папки сохранения для запаковки текста
    def selectPT_output_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку сохранения для запаковки текста")
        if folder_path:
            self.PToutput_dir = folder_path
            self.log(f"Для запаковки текста выбрана папка сохранения: {folder_path}")
            self.labelPT_output_folder.setText(f"{folder_path}")
            self.save_paths_config()

    # Функции выбора файла и папки для полной распаковки (файл → data + text)
    def selectFE_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл для полной распаковки")
        if file_path:
            self.FEinput_path = file_path
            self.log(f"Для полной распаковки выбран файл: {file_path}")
            self.labelFE_select_file.setText(f"{file_path}")
            self.save_paths_config()

    def selectFE_output_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите базовую папку для полной распаковки")
        if folder_path:
            self.FEoutput_dir = folder_path
            self.log(f"Для полной распаковки выбрана папка: {folder_path} (будут созданы data и text)")
            self.labelFE_output_folder.setText(f"{folder_path}")
            self.save_paths_config()

    # Функции для полной запаковки (data + text → файл)
    def selectFP_base_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Выберите папку, в которой есть подпапки data и text")
        if folder_path:
            self.FP_base_dir = folder_path
            self.log(f"Для полной запаковки выбрана база: {folder_path} (ожидаются подпапки data и text)")
            self.labelFP_base_folder.setText(f"{folder_path}")
            self.save_paths_config()

    def selectFP_trans_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл перевода CSV/TSV (ID,OriginalText)",
            filter='CSV/TSV Files (*.csv *.tsv)'
        )
        if file_path:
            self.FP_trans_path = file_path
            self.log(f"Для полной запаковки выбран файл перевода: {file_path}")
            self.labelFP_trans_file.setText(f"{file_path}")
            self.save_paths_config()

    def selectFP_output_file(self):
        default_name = "translate_words_map_en"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Выберите имя и папку итогового файла",
            default_name,
            "All Files (*.*)"
        )
        if file_path:
            self.FP_output_file = file_path
            self.log(f"Итоговый файл для полной запаковки: {file_path}")
            self.labelFP_output_file.setText(f"{file_path}")
            self.save_paths_config()

    # Создать CSV ID,OriginalText из TextExtractor.csv
    def export_translation_csv(self):
        if not self.TRinput_path:
            self.log("Пожалуйста, выберите TextExtractor.csv для экспорта перевода")
            return

        # Определяем формат (CSV или TSV) и разделитель
        sep = ";"
        default_name = "translation.csv"
        file_filter = "CSV Files (*.csv);;TSV Files (*.tsv)"
        if hasattr(self, "comboTR_format"):
            fmt_sep = self.comboTR_format.currentData()
            if fmt_sep == "\t":
                sep = "\t"
                default_name = "translation.tsv"
                file_filter = "TSV Files (*.tsv);;CSV Files (*.csv)"
            else:
                sep = ";"

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить файл для перевода (ID,OriginalText)",
            default_name,
            file_filter
        )
        if not output_path:
            return

        try:
            with open(self.TRinput_path, 'r', encoding='utf-8', newline='') as src_f:
                reader = csv.reader(src_f, delimiter=';')
                header = next(reader, None)
                if not header:
                    self.log("❌ В исходном CSV нет заголовка")
                    return

                try:
                    id_idx = header.index('ID')
                    text_idx = header.index('OriginalText')
                except ValueError:
                    self.log("❌ В исходном CSV не найдены колонки 'ID' и 'OriginalText'")
                    return

                with open(output_path, 'w', encoding='utf-8', newline='') as out_f:
                    writer = csv.writer(out_f, delimiter=sep)
                    writer.writerow(['ID', 'OriginalText'])
                    count = 0
                    for row in reader:
                        if len(row) <= max(id_idx, text_idx):
                            continue
                        text = row[text_idx]
                        if sep == '\t' and text:
                            text = text.replace('\t', ' \\t ')
                        if text and text.strip():
                            writer.writerow([row[id_idx], text])
                            count += 1

            self.log(f"✅ Создан файл перевода: {output_path} (строк: {count})")
        except Exception as e:
            self.log(f"❌ Ошибка при создании файла перевода: {str(e)}")

    # Применить переводы из CSV обратно в TextExtractor.csv
    def apply_translation_csv(self):
        if not self.TRinput_path:
            self.log("Пожалуйста, выберите TextExtractor.csv для применения перевода")
            return

        trans_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите CSV/TSV с переводом (ID,OriginalText)",
            filter='CSV/TSV Files (*.csv *.tsv)'
        )
        if not trans_path:
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить обновлённый TextExtractor.csv",
            "TextExtractor_translated.csv",
            "CSV Files (*.csv)"
        )
        if not output_path:
            return

        try:
            # Определяем разделитель в файле перевода:
            ext = os.path.splitext(trans_path)[1].lower()
            if ext == '.tsv':
                delim = '\t'
            else:
                delim = ';'

            translations = {}
            with open(trans_path, 'r', encoding='utf-8', newline='') as tf:
                reader = csv.reader(tf, delimiter=delim)
                header = next(reader, None)
                if header:
                    try:
                        id_idx = header.index('ID')
                        text_idx = header.index('OriginalText')
                    except ValueError:
                        # Если нет заголовков, считаем, что первые две колонки — ID и текст
                        id_idx = 0
                        text_idx = 1
                        # обработаем первую строку как данные
                        if len(header) > 1 and header[0].strip():
                            translations[header[0].strip()] = header[1]
                for row in reader:
                    if len(row) <= max(id_idx, text_idx):
                        continue
                    key = row[id_idx].strip()
                    if not key:
                        continue
                    text = row[text_idx]
                    # Преобразуем реальные переводчикиные переносы в \n и \r для совместимости с pak_text
                    text = text.replace('\n', '\\n').replace('\r', '\\r')
                    translations[key] = text

            if not translations:
                self.log("❌ В файле перевода не найдено ни одной строки с ID")
                return

            replaced = 0
            total = 0
            with open(self.TRinput_path, 'r', encoding='utf-8', newline='') as src_f, \
                 open(output_path, 'w', encoding='utf-8', newline='') as out_f:

                reader = csv.reader(src_f, delimiter=';')
                writer = csv.writer(out_f, delimiter=';')

                header = next(reader, None)
                if not header:
                    self.log("❌ В исходном TextExtractor.csv нет заголовка")
                    return

                writer.writerow(header)

                try:
                    id_idx_csv = header.index('ID')
                    text_idx_csv = header.index('OriginalText')
                except ValueError:
                    self.log("❌ В исходном TextExtractor.csv не найдены колонки 'ID' и 'OriginalText'")
                    return

                for row in reader:
                    if len(row) <= max(id_idx_csv, text_idx_csv):
                        writer.writerow(row)
                        continue
                    total += 1
                    key = row[id_idx_csv]
                    if key in translations:
                        row[text_idx_csv] = translations[key]
                        replaced += 1
                    writer.writerow(row)

            self.log(f"✅ Применён перевод к файлу: {output_path} (заменено строк: {replaced} из {total})")
        except Exception as e:
            self.log(f"❌ Ошибка при применении файла перевода: {str(e)}")

    # Создать debug-версию TextExtractor.csv с тегами [xxxx] в начале текста
    def create_debug_csv(self):
        if not self.TRinput_path:
            self.log("Пожалуйста, выберите TextExtractor.csv для создания debug файла")
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить debug TextExtractor.csv",
            "TextExtractor_debug.csv",
            "CSV Files (*.csv)"
        )
        if not output_path:
            return

        allowed_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz123456789"
        used_tags = set()

        def gen_tag():
            # Генерация уникального 4-символьного тега
            while True:
                t = "".join(random.choice(allowed_chars) for _ in range(4))
                if t not in used_tags:
                    used_tags.add(t)
                    return t

        try:
            with open(self.TRinput_path, 'r', encoding='utf-8', newline='') as src_f, \
                 open(output_path, 'w', encoding='utf-8', newline='') as out_f:

                reader = csv.reader(src_f, delimiter=';')
                writer = csv.writer(out_f, delimiter=';')

                header = next(reader, None)
                if not header:
                    self.log("❌ В исходном TextExtractor.csv нет заголовка")
                    return

                writer.writerow(header)

                try:
                    text_idx = header.index('OriginalText')
                except ValueError:
                    self.log("❌ В исходном TextExtractor.csv не найдена колонка 'OriginalText'")
                    return

                count = 0
                for row in reader:
                    if len(row) <= text_idx:
                        writer.writerow(row)
                        continue
                    text = row[text_idx]
                    if text and text.strip():
                        tag = gen_tag()
                        row[text_idx] = f"[{tag}]{text}"
                        count += 1
                    writer.writerow(row)

            self.log(f"✅ Создан debug файл: {output_path} (строк с тегами: {count})")
        except Exception as e:
            self.log(f"❌ Ошибка при создании debug файла: {str(e)}")

    def validate_textextractor_csv(self):
        """
        Проверка выбранного TextExtractor.csv на базовые ошибки формата:
        - наличие заголовка
        - одинаковое количество колонок в каждой строке
        - базовая проверка числовых и hex полей
        - проверка OriginalText на наличие ID (hex-строк длиной 16 символов)
        """
        if not self.TRinput_path:
            self.log("Пожалуйста, выберите TextExtractor.csv для проверки")
            return

        try:
            with open(self.TRinput_path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.reader(f, delimiter=';')
                header = next(reader, None)
                if not header:
                    self.log("❌ В TextExtractor.csv нет заголовка")
                    return

                # Находим индекс колонки OriginalText
                try:
                    text_idx = header.index('OriginalText')
                except ValueError:
                    text_idx = None

                expected_cols = len(header)
                total_rows = 0
                error_rows = 0
                logged_errors = 0

                # Паттерн для поиска hex-строк длиной 16 символов (8 байт = ID)
                hex_id_pattern = re.compile(r'[0-9a-fA-F]{16}')

                for line_no, row in enumerate(reader, start=2):
                    total_rows += 1
                    row_errors = []

                    # Количество колонок
                    if len(row) != expected_cols:
                        row_errors.append(
                            f"ожидалось колонок: {expected_cols}, получено: {len(row)}"
                        )
                    else:
                        # Базовые проверки формата для стандартного TextExtractor.csv
                        try:
                            if row[0] and not row[0].isdigit():
                                row_errors.append("поле Number не является числом")
                        except IndexError:
                            row_errors.append("нет поля Number")

                        try:
                            if row[2] and not row[2].isdigit():
                                row_errors.append("поле All Blocks не является числом")
                        except IndexError:
                            pass

                        try:
                            if row[3] and not row[3].isdigit():
                                row_errors.append("поле Work Blocks не является числом")
                        except IndexError:
                            pass

                        # Unknown (1 байт hex)
                        try:
                            if row[5]:
                                bytes.fromhex(row[5])
                        except (IndexError, ValueError):
                            row_errors.append("поле Unknown не является корректным hex-байтом")

                        # ID (8 байт hex)
                        try:
                            if row[6]:
                                bytes.fromhex(row[6])
                        except (IndexError, ValueError):
                            row_errors.append("поле ID не является корректной hex-строкой")

                        # Проверка OriginalText на наличие ID (hex-строк длиной 16 символов)
                        if text_idx is not None:
                            try:
                                if len(row) > text_idx and row[text_idx]:
                                    text = row[text_idx]
                                    # Ищем hex-строки длиной 16 символов в тексте
                                    found_ids = hex_id_pattern.findall(text)
                                    if found_ids:
                                        # Проверяем, что найденные строки действительно являются валидными hex
                                        valid_ids = []
                                        for hex_str in found_ids:
                                            try:
                                                # Проверяем, что это действительно hex (8 байт)
                                                bytes.fromhex(hex_str)
                                                valid_ids.append(hex_str)
                                            except ValueError:
                                                pass
                                        if valid_ids:
                                            row_errors.append(
                                                f"в поле OriginalText обнаружен ID (hex-строка): {', '.join(valid_ids[:3])}"
                                                + (f" и еще {len(valid_ids) - 3}" if len(valid_ids) > 3 else "")
                                            )
                            except IndexError:
                                pass

                    if row_errors:
                        error_rows += 1
                        if logged_errors < 50:
                            self.log(f"❌ Строка {line_no}: " + "; ".join(row_errors))
                            logged_errors += 1

                if error_rows == 0:
                    self.log(f"✅ Проверка завершена. Найдено строк: {total_rows}, ошибок не обнаружено.")
                else:
                    self.log(
                        f"⚠ Проверка завершена. Всего строк: {total_rows}, проблемных строк: {error_rows}. "
                        f"Показано первых {logged_errors} ошибок."
                    )
        except Exception as e:
            self.log(f"❌ Ошибка при проверке TextExtractor.csv: {str(e)}")

    # Функция запуска скрипта распаковки файла
    def start_processing1(self):
        if not self.EFinput_path:
            self.log("Пожалуйста, выберите файл для распаковки файла")
            return
        if not self.EFoutput_dir:
            self.log("Пожалуйста, выберите папку сохранения для распаковки файла")
            return

        self.worker = WorkerThread(self.EFinput_path, self.EFoutput_dir, 1)
        self.worker.log_signal.connect(self.log)
        self.worker.start()
        
    # Функция запуска скрипта запаковки файла
    def start_processing2(self):
        if not self.PFinput_path:
            self.log("Пожалуйста, выберите папку c *.dat для запаковки файла")
            return
        if not self.PFoutput_dir:
            self.log("Пожалуйста, выберите папку сохранения для запаковки файла")
            return

        self.worker = WorkerThread(self.PFinput_path, self.PFoutput_dir, 2)
        self.worker.log_signal.connect(self.log)
        self.worker.start()
        
    # Функция запуска скрипта распаковки текста
    def start_processing3(self):
        if not self.ETinput_path:
            self.log("Пожалуйста, выберите папку c *.dat для распаковки текста")
            return
        if not self.EToutput_dir:
            self.log("Пожалуйста, выберите папку сохранения для распаковки текста")
            return

        self.worker = WorkerThread(self.ETinput_path, self.EToutput_dir, 3)
        self.worker.log_signal.connect(self.log)
        self.worker.start()
        
    # Функция запуска скрипта распаковки текста
    def start_processing4(self):
        if not self.PTinput_path:
            self.log("Пожалуйста, выберите файл CSV для запаковки текста")
            return
        if not self.PToutput_dir:
            self.log("Пожалуйста, выберите папку сохранения для запаковки текста")
            return

        self.worker = WorkerThread(self.PTinput_path, self.PToutput_dir, 4)
        self.worker.log_signal.connect(self.log)
        self.worker.start()

    # Функция запуска полной распаковки (файл → data + text)
    def start_processing5(self):
        if not self.FEinput_path:
            self.log("Пожалуйста, выберите файл для полной распаковки")
            return
        if not self.FEoutput_dir:
            self.log("Пожалуйста, выберите базовую папку для полной распаковки")
            return

        self.worker = WorkerThread(self.FEinput_path, self.FEoutput_dir, 5)
        self.worker.log_signal.connect(self.log)
        self.worker.start()

    # Функция запуска полной запаковки (data + text → файл)
    def start_processing6(self):
        if not self.FP_base_dir:
            self.log("Пожалуйста, выберите базовую папку, где находятся подпапки data и text")
            return
        if not self.FP_trans_path:
            self.log("Пожалуйста, выберите файл перевода CSV/TSV (ID,OriginalText)")
            return
        if not self.FP_output_file:
            self.log("Пожалуйста, выберите итоговый файл для полной запаковки")
            return

        self.worker = WorkerThread(
            self.FP_base_dir,
            self.FP_output_file,
            6,
            extra={"trans_path": self.FP_trans_path},
        )
        self.worker.log_signal.connect(self.log)
        self.worker.start()



if __name__ == '__main__':
    app = QApplication(sys.argv)
    app_font = QFont("Verdana", 10)
    app.setFont(app_font)
    ex = MyApp()
    ex.show()
    sys.exit(app.exec_())
