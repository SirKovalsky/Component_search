# -*- coding: utf-8 -*-
"""
sync_db.py — загрузка двух таблиц из PostgreSQL (БД comp) в локальные CSV.

Формируются две таблицы:
  1) номенклатурный справочник  -> data/nomenclature.csv
     (структура как в 20260817_Export.csv)
  2) наличие в чистой зоне      -> data/comp_exist.xlsx
     (структура как в 20260817_Export.xlsx: № п/п, Наименование,
      Обозначение, Типоразмер, Кол-во в наличии, Место хранения)

Данные сохраняются локально, чтобы утилита работала офлайн. Перед перезаписью
каждого файла создаётся бэкап в data/backups/<имя>_YYYYMMDD_HHMMSS.<ext>.

Запуск:
  * самостоятельно:  python sync_db.py
  * из утилиты:      from sync_db import open_sync_dialog
                     open_sync_dialog(self)

Зависимости: psycopg (psycopg3), openpyxl.
Установка: pip install "psycopg[binary]" openpyxl
"""

import csv
import math
import os
import shutil
import sys
import unicodedata
from datetime import datetime, date
from decimal import Decimal

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QProgressBar, QTextEdit, QMessageBox,
    QCheckBox,
)

try:
    import psycopg
    PSYCOPG_AVAILABLE = True
except Exception:
    psycopg = None
    PSYCOPG_AVAILABLE = False

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except Exception:
    openpyxl = None
    OPENPYXL_AVAILABLE = False


# --------------------------------------------------------------------------
# Константы
# --------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')

NOMENCLATURE_FILE = 'nomenclature.csv'
EXIST_FILE = 'comp_exist.xlsx'

CLEAN_ZONE_ROOT_ID = 616          # корень склада «Чистая зона» в таблице store
BOM_SECTIONS = {0: 'Прочие', 1: 'Стандартные'}

DEFAULT_DB = {
    'host': '192.168.37.117',
    'port': '5432',
    'dbname': 'comp',
    'user': 'postgres',
    'password': 'changemeeeea',
}

SETTINGS_ORG = 'ComponentFilterApp'
SETTINGS_APP = 'ComponentFilterApp'

NOMENCLATURE_HEADERS = [
    'Name', 'Code', 'sUnit', 'BodyName', 'ManufactName', 'PartNumber',
    'sOrderCodes', 'Multiple', 'StoreName', 'MinQty', 'DataSheet', 'URL',
    'Description', 'GroupName', 'GroupFullName', 'StoreFullName',
    'StatusName', 'SymbolName',
    'FullVal0', 'FullVal1', 'FullVal2', 'FullVal3', 'FullVal4', 'FullVal5',
    'DisplayName', 'QtyStockSum', 'Marking', 'BOMSectionName', 'AltURL',
]

EXIST_HEADERS = [
    '№ п/п', 'Наименование', 'Обозначение', 'Типоразмер',
    'Кол-во в наличии', 'Место хранения',
]

CHUNK = 500
KEEP_BACKUPS = 10

SQL_GROUPS = "SELECT id, parent, name FROM groups"
SQL_STORES = "SELECT id, parent, name FROM store"

SQL_COMPONENT = """
SELECT c.id, c.name, c.code, u.symbol, b.name, m.name, c.partnumber,
       c.multiple, c.minqty, c.datasheet, c.url, c.description,
       c."Group", st.name, sy.name,
       c.val0, c.val1, c.val2, c.val3, c.val4, c.val5,
       c.marking, c.bomsection, c.alturl, c.store, s.name,
       COALESCE(ss.num, 0)
FROM component c
LEFT JOIN unit u     ON u.id = c.unitid
LEFT JOIN body b     ON b.id = c.body
LEFT JOIN manufact m ON m.id = c.manufact
LEFT JOIN status st  ON st.id = c.statusid
LEFT JOIN symbol sy  ON sy.id = c.symbolid
LEFT JOIN store  s   ON s.id = c.store
LEFT JOIN (SELECT comp, SUM(num) AS num FROM stock GROUP BY comp) ss
       ON ss.comp = c.id
ORDER BY c.id
"""

SQL_STOCK = """
SELECT s.store, c.name, c.code, b.name, s.num
FROM stock s
JOIN component c ON c.id = s.comp
LEFT JOIN body b ON b.id = c.body
WHERE s.num > 0
"""


# --------------------------------------------------------------------------
# Утилиты обработки значений и иерархий
# --------------------------------------------------------------------------
def _decimal_to_str(value):
    if value == value.to_integral_value():
        return str(int(value))
    return format(value, 'f').rstrip('0').rstrip('.')


def _clean(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        value = _decimal_to_str(value)
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


def _num(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return _decimal_to_str(value)
    if isinstance(value, float):
        return _decimal_to_str(Decimal(str(value)))
    if isinstance(value, int):
        return str(value)
    return _clean(value)


def _native_number(value):
    """Число как int/float (для xlsx) либо None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return value


def _sort_key(value):
    """Ключ сортировки как в примере: без пунктуации, регистронезависимо.

    Пробелы сохраняются — они влияют на порядок в эталонном файле.
    """
    text = '' if value is None else str(value)
    return ''.join(ch for ch in text.casefold()
                   if not unicodedata.category(ch).startswith('P'))


def _build_paths(rows):
    """rows: iterable (id, parent, name) -> ({id: 'root/leaf'}, {id: name})."""
    items = {}
    for node_id, parent, name in rows:
        items[int(node_id)] = (int(parent) if parent is not None else 0,
                               (name or '').strip())
    cache = {}

    def path(node_id, seen=None):
        if node_id in cache:
            return cache[node_id]
        if node_id not in items:
            return ''
        seen = seen or set()
        if node_id in seen:
            return items[node_id][1]
        seen.add(node_id)
        parent, name = items[node_id]
        if parent == 0 or parent not in items:
            result = name
        else:
            parent_path = path(parent, seen)
            result = f"{parent_path}/{name}" if parent_path else name
        cache[node_id] = result
        return result

    names = {}
    for node_id in list(items):
        path(node_id)
        names[node_id] = items[node_id][1]
    return cache, names


def _descendants(root_id, rows):
    children = {}
    for node_id, parent, _name in rows:
        children.setdefault(int(parent) if parent is not None else 0,
                            []).append(int(node_id))
    result = set()
    stack = [int(root_id)]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


def _component_to_row(row, group_paths, group_names, store_paths, store_names):
    (cid, name, code, unit, body, manufact, partnumber, multiple, minqty,
     datasheet, url, description, group_id, status_name, symbol_name,
     val0, val1, val2, val3, val4, val5, marking, bomsection, alturl,
     store_id, store_name, qty_sum) = row
    gid = int(group_id) if group_id is not None else None
    sid = int(store_id) if store_id is not None else None
    if bomsection is None:
        bomsection_text = ''
    else:
        bomsection_text = BOM_SECTIONS.get(int(bomsection), str(bomsection))
    return [
        _clean(name), _clean(code), _clean(unit), _clean(body), _clean(manufact),
        _clean(partnumber), '', _num(multiple), _clean(store_name), _num(minqty),
        _clean(datasheet), _clean(url), _clean(description),
        group_names.get(gid, ''), group_paths.get(gid, ''),
        store_paths.get(sid, ''),
        _clean(status_name), _clean(symbol_name),
        _clean(val0), _clean(val1), _clean(val2), _clean(val3),
        _clean(val4), _clean(val5),
        '', _num(qty_sum), _clean(marking), bomsection_text, _clean(alturl),
    ]


# --------------------------------------------------------------------------
# Работа с локальными файлами
# --------------------------------------------------------------------------
def _csv_value(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return _decimal_to_str(value)
    if isinstance(value, float):
        return _decimal_to_str(Decimal(str(value)))
    return value


def _xlsx_value(value):
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return _native_number(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == '':
            return None
        try:
            return int(text)
        except ValueError:
            pass
        try:
            number = float(text)
        except ValueError:
            return value
        if math.isfinite(number):
            return number
        return value
    return str(value)


def save_csv(path, headers, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_csv_value(value) for value in row])
    os.replace(tmp, path)


def save_xlsx(path, headers, rows):
    if not OPENPYXL_AVAILABLE:
        raise RuntimeError('Модуль openpyxl не установлен.')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Sheet 1'
    sheet.append(list(headers))
    for row in rows:
        sheet.append([_xlsx_value(value) for value in row])
    workbook.save(tmp)
    os.replace(tmp, path)


SAVE_WRITERS = {'.csv': save_csv, '.xlsx': save_xlsx}


def backup_file(path):
    if not os.path.exists(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = os.path.join(BACKUP_DIR, f'{base}_{stamp}{ext}')
    counter = 1
    while os.path.exists(dest):
        dest = os.path.join(BACKUP_DIR, f'{base}_{stamp}_{counter}{ext}')
        counter += 1
    shutil.copy2(path, dest)
    return dest


def prune_backups(prefix, keep=KEEP_BACKUPS):
    if not os.path.isdir(BACKUP_DIR):
        return
    files = sorted(
        (os.path.join(BACKUP_DIR, name) for name in os.listdir(BACKUP_DIR)
         if name.startswith(prefix + '_')),
        key=os.path.getmtime, reverse=True,
    )
    for old in files[keep:]:
        try:
            os.remove(old)
        except OSError:
            pass


# --------------------------------------------------------------------------
# Загрузка данных из БД
# --------------------------------------------------------------------------
def fetch_all(params, progress_cb=None, status_cb=None):
    def progress(value):
        if progress_cb:
            progress_cb(int(value))

    def status(text):
        if status_cb:
            status_cb(text)

    conn = psycopg.connect(
        host=params['host'], port=params['port'], dbname=params['dbname'],
        user=params['user'], password=params['password'], connect_timeout=10,
    )
    try:
        cur = conn.cursor()

        status('Чтение справочников (группы, склады)...')
        progress(4)
        cur.execute(SQL_GROUPS)
        group_rows = cur.fetchall()
        cur.execute(SQL_STORES)
        store_rows = cur.fetchall()
        group_paths, group_names = _build_paths(group_rows)
        store_paths, store_names = _build_paths(store_rows)
        clean_zone = _descendants(CLEAN_ZONE_ROOT_ID, store_rows)
        progress(12)

        status('Загрузка номенклатурного справочника...')
        cur.execute("SELECT count(*) FROM component")
        total_comp = cur.fetchone()[0] or 1
        cur.execute(SQL_COMPONENT)
        nomenclature = []
        got = 0
        while True:
            batch = cur.fetchmany(CHUNK)
            if not batch:
                break
            for row in batch:
                nomenclature.append(
                    _component_to_row(row, group_paths, group_names,
                                      store_paths, store_names))
            got += len(batch)
            progress(12 + 38 * got / total_comp)
        progress(50)

        status('Загрузка наличия в чистой зоне...')
        cur.execute("SELECT count(*) FROM stock WHERE num > 0")
        total_stock = cur.fetchone()[0] or 1
        cur.execute(SQL_STOCK)
        exist = []
        got = 0
        while True:
            batch = cur.fetchmany(CHUNK)
            if not batch:
                break
            for store_id, name, code, body, qty in batch:
                sid = int(store_id) if store_id is not None else 0
                if sid not in clean_zone:
                    continue
                exist.append([
                    name,
                    code,
                    body,
                    _native_number(qty),
                    store_paths.get(sid, ''),
                ])
            got += len(batch)
            progress(50 + 45 * got / total_stock)
        exist.sort(key=lambda row: _sort_key(row[0]))
        for index, row in enumerate(exist, start=1):
            row.insert(0, index)
        progress(97)
        status('Формирование локальных таблиц завершено.')
        return {
            'nomenclature': (NOMENCLATURE_HEADERS, nomenclature),
            'exist': (EXIST_HEADERS, exist),
        }
    finally:
        conn.close()


class FetchWorker(QThread):
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = params

    def run(self):
        try:
            result = fetch_all(self.params, self.progress.emit, self.status.emit)
            files = self._save_result(result)
            self.progress.emit(100)
            self.finished_ok.emit({'result': result, 'files': files})
        except Exception as exc:
            self.failed.emit(f'{type(exc).__name__}: {exc}')

    def _save_result(self, result):
        files = {}
        for key, filename in (('nomenclature', NOMENCLATURE_FILE),
                              ('exist', EXIST_FILE)):
            headers, rows = result[key]
            path = os.path.join(DATA_DIR, filename)
            ext = os.path.splitext(filename)[1].lower()
            writer = SAVE_WRITERS.get(ext, save_csv)
            self.status.emit(f'Сохранение {filename} ({len(rows)} строк)...')
            previous = backup_file(path)
            writer(path, headers, rows)
            prune_backups(os.path.splitext(filename)[0])
            files[key] = {'path': path, 'rows': len(rows), 'backup': previous}
        return files


# --------------------------------------------------------------------------
# Диалог
# --------------------------------------------------------------------------
class SyncDBDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Обновление локальной базы из PostgreSQL')
        self.resize(900, 640)
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.worker = None
        self._build_ui()
        self._load_settings()
        self._update_psycopg_state()

    # ---- построение интерфейса ----
    def _build_ui(self):
        root = QVBoxLayout(self)

        conn_group = QGroupBox('Подключение к базе данных')
        form = QFormLayout(conn_group)
        self.host_edit = QLineEdit()
        self.port_edit = QLineEdit()
        self.db_edit = QLineEdit()
        self.user_edit = QLineEdit()
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.show_pass = QCheckBox('Показать пароль')
        self.show_pass.toggled.connect(self._toggle_password)
        pass_row = QHBoxLayout()
        pass_row.addWidget(self.pass_edit)
        pass_row.addWidget(self.show_pass)
        form.addRow('Хост:', self.host_edit)
        form.addRow('Порт:', self.port_edit)
        form.addRow('База:', self.db_edit)
        form.addRow('Пользователь:', self.user_edit)
        form.addRow('Пароль:', pass_row)
        note = QLabel('Пароль хранится локально в настройках открытым текстом.')
        note.setStyleSheet('color: #b45309;')
        form.addRow('', note)
        root.addWidget(conn_group)

        buttons = QHBoxLayout()
        self.fetch_btn = QPushButton('Получить')
        self.fetch_btn.setStyleSheet(
            'QPushButton { background-color: #2196F3; color: white; padding: 8px 18px;'
            ' border: none; border-radius: 6px; font-weight: 600; }'
            'QPushButton:hover { background-color: #1976D2; }'
            'QPushButton:disabled { background-color: #cccccc; }'
        )
        self.fetch_btn.clicked.connect(self.start_fetch)
        self.folder_btn = QPushButton('Открыть папку data')
        self.folder_btn.clicked.connect(self._open_data_dir)
        buttons.addWidget(self.fetch_btn)
        buttons.addWidget(self.folder_btn)
        buttons.addStretch()
        root.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        self.status_label = QLabel(f'Локальные данные: {DATA_DIR}')
        root.addWidget(self.status_label)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close_btn = QPushButton('Закрыть')
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    # ---- настройки ----
    def _load_settings(self):
        self.host_edit.setText(
            self.settings.value('db_host', DEFAULT_DB['host'], type=str))
        self.port_edit.setText(
            self.settings.value('db_port', DEFAULT_DB['port'], type=str))
        self.db_edit.setText(
            self.settings.value('db_name', DEFAULT_DB['dbname'], type=str))
        self.user_edit.setText(
            self.settings.value('db_user', DEFAULT_DB['user'], type=str))
        self.pass_edit.setText(
            self.settings.value('db_password', DEFAULT_DB['password'], type=str))

    def _save_settings(self):
        self.settings.setValue('db_host', self.host_edit.text().strip())
        self.settings.setValue('db_port', self.port_edit.text().strip())
        self.settings.setValue('db_name', self.db_edit.text().strip())
        self.settings.setValue('db_user', self.user_edit.text().strip())
        self.settings.setValue('db_password', self.pass_edit.text())

    def _params(self):
        return {
            'host': self.host_edit.text().strip(),
            'port': self.port_edit.text().strip(),
            'dbname': self.db_edit.text().strip(),
            'user': self.user_edit.text().strip(),
            'password': self.pass_edit.text(),
        }

    def _toggle_password(self, shown):
        self.pass_edit.setEchoMode(
            QLineEdit.Normal if shown else QLineEdit.Password)

    def _missing_drivers(self):
        missing = []
        if not PSYCOPG_AVAILABLE:
            missing.append('psycopg[binary]')
        if not OPENPYXL_AVAILABLE:
            missing.append('openpyxl')
        return missing

    def _update_psycopg_state(self):
        missing = self._missing_drivers()
        if missing:
            self.fetch_btn.setEnabled(False)
            self.status_label.setText(
                'Нет модулей: ' + ', '.join(missing) +
                '. Установите: pip install ' + ' '.join(missing))
            self._log('Не найдены модули: ' + ', '.join(missing) +
                      ' — загрузка из БД недоступна.')

    # ---- журнал ----
    def _log(self, message):
        self.log.append(f'[{datetime.now().strftime("%H:%M:%S")}] {message}')

    def _open_data_dir(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if sys.platform.startswith('win'):
            try:
                os.startfile(DATA_DIR)
                return
            except OSError:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(DATA_DIR))

    # ---- запуск загрузки ----
    def start_fetch(self):
        missing = self._missing_drivers()
        if missing:
            QMessageBox.critical(
                self, 'Нет модулей',
                'Не установлены модули: ' + ', '.join(missing) +
                '.\nУстановите: pip install ' + ' '.join(missing))
            return
        params = self._params()
        if not params['host'] or not params['dbname'] or not params['user']:
            QMessageBox.warning(self, 'Проверка',
                                'Заполните хост, базу и пользователя.')
            return
        self._save_settings()
        self.fetch_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText('Подключение к базе данных...')
        self._log(
            f"Подключение: {params['user']}@{params['host']}:"
            f"{params['port']}/{params['dbname']}")

        self.worker = FetchWorker(params, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self._on_status)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_status(self, text):
        self.status_label.setText(text)
        self._log(text)

    def _on_finished(self, payload):
        self.fetch_btn.setEnabled(True)
        for info in payload['files'].values():
            backup = info['backup'] or '—'
            self._log(
                f"{os.path.basename(info['path'])}: {info['rows']} строк, "
                f"бэкап: {backup}")
        self.status_label.setText('Готово. Локальные таблицы обновлены.')
        QMessageBox.information(self, 'Готово', 'Локальные таблицы обновлены.')

    def _on_failed(self, text):
        self.fetch_btn.setEnabled(True)
        self.status_label.setText('Ошибка: ' + text)
        self._log('ОШИБКА: ' + text)
        QMessageBox.critical(
            self, 'Ошибка подключения/загрузки',
            f'{text}\n\nЛокальные файлы не изменены.')


def open_sync_dialog(parent=None):
    """Открывает окно синхронизации. Возвращает код QDialog."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    dialog = SyncDBDialog(parent)
    return dialog.exec_()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    dialog = SyncDBDialog()
    dialog.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
