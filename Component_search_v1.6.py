import sys
import csv
import os
import re
import json
from datetime import datetime
from PyQt5.QtGui import QColor, QTextDocument, QAbstractTextDocumentLayout
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QTableWidget,
    QTableWidgetItem, QComboBox, QGroupBox, QTabWidget, QHeaderView,
    QMessageBox, QGridLayout, QSplitter, QTextEdit, QCheckBox, QAbstractItemView,
    QMenu, QAction, QDialog, QListWidget, QListWidgetItem,
    QCompleter, QStyledItemDelegate, QStyleOptionViewItem, QStyle
)
from PyQt5.QtCore import Qt, QSettings, QRectF, QStringListModel, QTimer


class ColumnConfigDialog(QDialog):
    """Диалог настройки отображаемых столбцов"""

    def __init__(self, current_headers, all_headers, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка столбцов")
        self.setGeometry(300, 300, 400, 500)

        layout = QVBoxLayout()

        self.list_widget = QListWidget()
        source = all_headers or current_headers
        for header in source:
            if header in (None, "⭐"):
                continue
            item = QListWidgetItem(str(header))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if header in current_headers else Qt.Unchecked)
            self.list_widget.addItem(item)

        layout.addWidget(QLabel("Выберите отображаемые столбцы:"))
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def get_selected_headers(self):
        """Возвращает список выбранных заголовков"""
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected


class CustomTabDialog(QDialog):
    """Диалог создания пользовательской вкладки из нескольких категорий."""

    def __init__(self, categories, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новая вкладка")
        self.setGeometry(350, 300, 480, 560)

        layout = QVBoxLayout()

        layout.addWidget(QLabel("Название вкладки:"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Например: Сборка узла А")
        layout.addWidget(self.title_edit)

        layout.addWidget(QLabel("Категории для объединения:"))
        self.list_widget = QListWidget()
        for category in categories:
            item = QListWidgetItem(category)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        hint = QLabel("Вкладка покажет записи всех отмеченных категорий вместе.")
        hint.setStyleSheet("color: #666;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        ok_btn = QPushButton("Создать")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        self.setLayout(layout)

    def tab_title(self):
        return self.title_edit.text().strip()

    def selected_categories(self):
        return [self.list_widget.item(i).text()
                for i in range(self.list_widget.count())
                if self.list_widget.item(i).checkState() == Qt.Checked]


class HighlightDelegate(QStyledItemDelegate):
    """Делегат: подсвечивает синим фрагмент текста, совпадающий с запросом поиска."""

    HIGHLIGHT_COLOR = "#1d4ed8"

    @staticmethod
    def _escape(s):
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    def _query_for(self, widget):
        if widget is None:
            return ""
        return getattr(widget, "_highlight_query", "") or ""

    def paint(self, painter, option, index):
        query = self._query_for(option.widget)
        text = index.data()
        if not query or not text or not isinstance(text, str):
            super().paint(painter, option, index)
            return

        low_text = text.lower()
        low_query = query.lower()
        if low_query not in low_text:
            super().paint(painter, option, index)
            return

        parts = []
        start = 0
        while True:
            idx = low_text.find(low_query, start)
            if idx < 0:
                parts.append(self._escape(text[start:]))
                break
            parts.append(self._escape(text[start:idx]))
            parts.append('<span style="color:%s;font-weight:bold;">%s</span>'
                         % (self.HIGHLIGHT_COLOR, self._escape(text[idx:idx + len(query)])))
            start = idx + len(query)
        html = '<html><body style="white-space:pre;">' + "".join(parts) + '</body></html>'

        # Рисуем фон/выделение стандартным способом, а текст — поверх с подсветкой.
        painter.save()
        try:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            style = opt.widget.style() if opt.widget is not None else None
            if style is not None:
                style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

            doc = QTextDocument()
            doc.setDefaultFont(opt.font)
            doc.setTextWidth(option.rect.width())
            doc.setHtml(html)

            doc_h = doc.size().height()
            y_offset = max(0.0, (option.rect.height() - doc_h) / 2.0)
            painter.translate(option.rect.left(), option.rect.top() + y_offset)
            clip = QRectF(0, 0, option.rect.width(), option.rect.height())
            painter.setClipRect(clip)
            ctx = QAbstractTextDocumentLayout.PaintContext()
            ctx.clip = clip
            ctx.palette = opt.palette
            doc.documentLayout().draw(painter, ctx)
        except Exception:
            # Никакое исключение не должно покидать paint (это вызывает фатальный
            # сбой 0xC0000409 внутри живописания Qt).
            return
        finally:
            painter.restore()


class ComponentFilterApp(QMainWindow):
    def __init__(self):
        super().__init__()

        # Постоянные настройки приложения
        self.settings = QSettings("ComponentFilterApp", "ComponentFilterApp")
        self.favorites = set()
        self.load_favorites()

        self.input_file = None
        self.filtered_data = []
        self.all_data = []
        self.headers = []
        self.normalized_data = []
        self.filtered_normalized = []
        self.special_filter_sets = {}
        self.custom_tabs = {}          # key -> конфиг пользовательской вкладки

        # Настройки отображения столбцов - по умолчанию нужные столбцы
        self.default_headers = ['Name', 'BodyName', 'PartNumber', 'Description',
                                'FullVal0', 'FullVal1', 'FullVal2', 'FullVal3',
                                'FullVal4', 'FullVal5', 'QtyStockSum']
        self.current_headers = self.default_headers.copy()

        # Кэши для ускорения поиска и подсветки результатов
        self._table_base = {}          # id(table) -> список строк, показанных сейчас
        self._hay_cache = {}           # id(row) -> нормализованная "строка для поиска"
        self._suggestion_list = []
        self._filter_timer = None      # таймер-отсечка для перестроения таблицы поиска

        self.init_ui()
        self._setup_completers()
        QTimer.singleShot(0, self.restore_last_file)

    def normalize_value(self, value):
        """Нормализует значения для устранения различий в форматах"""
        if not value:
            return ""

        normalized = str(value).lower()
        normalized = re.sub(r'[\s\t\n\r]+', ' ', normalized)
        normalized = re.sub(r'\s*\(\s*', '(', normalized)
        normalized = re.sub(r'\s*\)\s*', ')', normalized)
        normalized = re.sub(r'\s*,\s*', ',', normalized)
        normalized = re.sub(r'(\d),(\d)', r'\1.\2', normalized)
        normalized = re.sub(r'(\d+)\s*%', r'\1%', normalized)
        normalized = re.sub(r'\s*(nf|uf|pf|мкф|нф|пф|om|kOm|mom|ом|k Om|мОм|ohm|kohm|mohm|v|в|volt|вольт)\s*', r' \1',
                            normalized)
        normalized = re.sub(r'(\d)\s*(nf|uf|pf|мкф|нф|пф|om|kOm|mom|ом|k Om|мОм|ohm|kohm|mohm|v|в|volt|вольт)',
                            r'\1 \2', normalized)
        normalized = re.sub(r'\s{2,}', ' ', normalized)

        # Убираем все в скобках для конденсаторов
        if '(' in normalized:
            main_part = normalized.split('(')[0].strip()
            main_part = re.sub(r'\s+', ' ', main_part)
            normalized = main_part

        return normalized.strip()

    def normalize_row(self, row):
        """Нормализует все значения в строке"""
        normalized_row = {}
        for key, value in row.items():
            normalized_row[key] = self.normalize_value(value)
        return normalized_row

    def init_ui(self):
        self.setWindowTitle('Фильтр компонентов - Чистая зона')
        self.setGeometry(80, 60, 1800, 1000)
        self.setStyleSheet("""
            QMainWindow { background: #f4f7fb; }
            QGroupBox { background: white; border: 1px solid #dbe3ef; border-radius: 8px;
                        margin-top: 12px; padding: 10px; font-weight: 600; color: #253858; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QComboBox, QLineEdit { min-height: 28px; padding: 2px 8px; border: 1px solid #cbd5e1;
                                    border-radius: 5px; background: #ffffff; }
            QComboBox:hover, QLineEdit:focus { border-color: #3b82f6; }
            QComboBox::drop-down { border: none; width: 22px; }
            QComboBox QAbstractItemView {
                background: #ffffff;
                color: #253858;
                border: 1px solid #cbd5e1;
                selection-background-color: #dbeafe;
                selection-color: #0b1e4b;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                min-height: 24px;
                padding: 3px 8px;
            }
            QComboBox QAbstractItemView::item:hover {
                background: #e8f0fe;
                color: #123a8c;
                font-weight: bold;
            }
            QComboBox QAbstractItemView::item:selected {
                background: #dbeafe;
                color: #0b1e4b;
                font-weight: bold;
            }
            QTabBar::tab { background: #e8edf5; padding: 9px 15px; margin-right: 2px; border-radius: 6px; }
            QTabBar::tab:selected { background: #2563eb; color: white; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        self.create_file_panel(main_layout)

        splitter = QSplitter(Qt.Vertical)
        self.tab_widget = QTabWidget()

        self.search_tab = self.create_search_tab()
        self.tab_widget.addTab(self.search_tab, "Общий поиск")

        self.ceramic_tab = self.create_ceramic_tab()
        self.tab_widget.addTab(self.ceramic_tab, "Керамические")

        self.resistor_tab = self.create_resistor_tab()
        self.tab_widget.addTab(self.resistor_tab, "Резисторы")

        # Добавляем новые вкладки
        self.electrolytic_tab = self.create_capacitor_tab("Электролитические")
        self.tab_widget.addTab(self.electrolytic_tab, "Электролитические")

        self.tantalum_tab = self.create_capacitor_tab("Танталовые")
        self.tab_widget.addTab(self.tantalum_tab, "Танталовые")

        self.polymer_tab = self.create_capacitor_tab("Полимерные")
        self.tab_widget.addTab(self.polymer_tab, "Полимерные")

        self.favorites_tab = self.create_favorites_tab()
        self.tab_widget.addTab(self.favorites_tab, "⭐ Избранное")

        splitter.addWidget(self.tab_widget)
        self.status_tab = self.create_status_tab()
        splitter.addWidget(self.status_tab)
        splitter.setSizes([800, 170])
        main_layout.addWidget(splitter)

        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.on_tab_close_requested)
        self.restore_custom_tabs()

    def create_file_panel(self, parent_layout):
        file_group = QGroupBox("Управление файлами")
        file_layout = QHBoxLayout()

        self.input_label = QLabel("Входной файл: не выбран")
        self.input_label.setStyleSheet("color: #666; padding: 5px;")

        input_btn = QPushButton("Выбрать входной файл")
        input_btn.clicked.connect(self.select_input_file)
        input_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        self.filter_btn = QPushButton("Фильтровать и сохранить")
        self.filter_btn.clicked.connect(self.filter_and_save)
        self.filter_btn.setEnabled(False)
        self.filter_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)

        # Кнопка настройки столбцов
        self.columns_btn = QPushButton("Настройка столбцов")
        self.columns_btn.clicked.connect(self.configure_columns)
        self.columns_btn.setEnabled(False)
        self.columns_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)

        # Кнопка создания пользовательской вкладки
        self.add_tab_btn = QPushButton("Добавить вкладку")
        self.add_tab_btn.clicked.connect(self.add_custom_tab_dialog)
        self.add_tab_btn.setEnabled(False)
        self.add_tab_btn.setStyleSheet("""
            QPushButton {
                background-color: #00897B;
                color: white;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00796B;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)

        self.recent_btn = QPushButton("Последние файлы")
        self.recent_btn.clicked.connect(self.show_recent_files_menu)
        self.recent_btn.setEnabled(True)

        self.auto_open_checkbox = QCheckBox("Открывать последний файл")
        self.auto_open_checkbox.setChecked(
            self.settings.value("auto_open_last_file", True, type=bool)
        )
        self.auto_open_checkbox.toggled.connect(
            lambda checked: self.settings.setValue("auto_open_last_file", checked)
        )

        file_layout.addWidget(self.input_label)
        file_layout.addWidget(input_btn)
        file_layout.addWidget(self.recent_btn)
        file_layout.addWidget(self.filter_btn)
        file_layout.addWidget(self.columns_btn)
        file_layout.addWidget(self.add_tab_btn)
        file_layout.addWidget(self.auto_open_checkbox)
        file_layout.addStretch()

        file_group.setLayout(file_layout)
        parent_layout.addWidget(file_group)

    def create_search_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Панель поиска по всем столбцам
        search_panel = QGroupBox("Поиск по всем столбцам")
        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Поиск:"))
        self.global_search_input = QLineEdit()
        self.global_search_input.setPlaceholderText("Введите текст для поиска во всех столбцах...")
        self.global_search_input.textChanged.connect(self.global_search)
        search_layout.addWidget(self.global_search_input)

        search_panel.setLayout(search_layout)
        layout.addWidget(search_panel)

        filter_group = QGroupBox("Фильтры поиска")
        filter_group.setMinimumHeight(205)
        filter_layout = QGridLayout()
        # Те же интервалы, что и на специальных вкладках.
        filter_layout.setHorizontalSpacing(12)
        filter_layout.setVerticalSpacing(8)
        # Пустые колонки отделяют основной фильтр от компактного блока FullVal.
        filter_layout.setColumnMinimumWidth(2, 24)
        filter_layout.setColumnMinimumWidth(3, 24)
        filter_layout.setColumnStretch(8, 1)

        filter_layout.addWidget(QLabel("Категория:"), 0, 0)
        self.category_combo = QComboBox()
        self.category_combo.setFixedWidth(250)
        self.category_combo.currentTextChanged.connect(self.apply_main_filters)
        filter_layout.addWidget(self.category_combo, 0, 1)

        # BodyName и FullVal0–FullVal5 — взаимосвязанные фильтры.
        # Каждый список показывает только значения, доступные при остальных условиях.
        self.main_smart_filters = {}
        body_label, body_column = 'Body Name', 'BodyName'
        filter_layout.addWidget(QLabel(f"{body_label}:"), 1, 0)
        body_combo = QComboBox()
        body_combo.addItem("Все")
        body_combo.setFixedWidth(250)
        body_combo.currentTextChanged.connect(self.apply_main_filters)
        filter_layout.addWidget(body_combo, 1, 1)
        self.main_smart_filters[body_column] = body_combo

        fullval_filter_labels = [
            ('FullVal0', 'FullVal 0'), ('FullVal1', 'FullVal 1'),
            ('FullVal2', 'FullVal 2'), ('FullVal3', 'FullVal 3'),
            ('FullVal4', 'FullVal 4'), ('FullVal5', 'FullVal 5'),
        ]
        # FullVal0–2 слева, FullVal3–5 справа — компактная сетка 2×3.
        for position, (column, label) in enumerate(fullval_filter_labels):
            row = position % 3
            label_col = 4 + (position // 3) * 2
            filter_layout.addWidget(QLabel(f"{label}:"), row, label_col)
            combo = QComboBox()
            combo.addItem("Все")
            combo.setFixedWidth(125)
            combo.currentTextChanged.connect(self.apply_main_filters)
            filter_layout.addWidget(combo, row, label_col + 1)
            self.main_smart_filters[column] = combo

        # Быстрый фильтр по наличию на складе.
        filter_layout.addWidget(QLabel("Наличие:"), 2, 0)
        self.stock_filter_combo = QComboBox()
        self.stock_filter_combo.addItems([
            "Все",
            "В наличии",
            "Меньше минимального остатка",
            "Нет на складе"
        ])
        self.stock_filter_combo.currentTextChanged.connect(self.apply_main_filters)
        filter_layout.addWidget(self.stock_filter_combo, 2, 1)

        # Нижняя строка вынесена в отдельный контейнер, чтобы длинная подпись
        # «Быстрый поиск» не отодвигала список категории от его подписи.
        quick_search_row = QWidget()
        quick_search_layout = QHBoxLayout(quick_search_row)
        quick_search_layout.setContentsMargins(0, 0, 0, 0)
        quick_search_layout.setSpacing(12)
        quick_search_layout.addWidget(QLabel("Быстрый поиск:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск в текущей категории...")
        self.search_input.textChanged.connect(self.on_quick_search)
        quick_search_layout.addWidget(self.search_input, 1)

        reset_btn = QPushButton("Сбросить фильтры")
        reset_btn.clicked.connect(self.reset_filters)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                min-width: 150px;
                min-height: 30px;
                padding: 4px 12px;
                border: none;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:pressed { background-color: #1e40af; }
        """)
        quick_search_layout.addWidget(reset_btn)

        # Быстрый поиск — отдельный ряд, не влияющий на ширину колонок фильтров.
        filter_content_layout = QVBoxLayout()
        filter_content_layout.setContentsMargins(0, 0, 0, 0)
        filter_content_layout.setSpacing(8)
        filter_content_layout.addLayout(filter_layout)
        filter_content_layout.addWidget(quick_search_row)
        filter_group.setLayout(filter_content_layout)
        layout.addWidget(filter_group)

        self.search_table = QTableWidget()
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.search_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.search_table.verticalScrollBar().setSingleStep(12)
        self.search_table.horizontalScrollBar().setSingleStep(12)
        self.search_table.setSortingEnabled(True)  # Включаем сортировку
        self.search_table.setStyleSheet("""
            QTableWidget {
                background-color: #f9f9f9;
                gridline-color: #ddd;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QHeaderView::section {
                background-color: #e8e8e8;
                padding: 5px;
                border: 1px solid #ddd;
                font-weight: bold;
            }
        """)
        self.search_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.search_table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        layout.addWidget(self.search_table)

        return widget

    def create_ceramic_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Панель поиска по всем столбцам
        search_panel = QGroupBox("Поиск по всем столбцам")
        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Поиск:"))
        self.ceramic_search_input = QLineEdit()
        self.ceramic_search_input.setPlaceholderText("Введите текст для поиска во всех столбцах...")
        self.ceramic_search_input.textChanged.connect(self.ceramic_global_search)
        search_layout.addWidget(self.ceramic_search_input)

        search_panel.setLayout(search_layout)
        layout.addWidget(search_panel)

        ceramic_filter_group = QGroupBox("Фильтры для керамических конденсаторов")
        ceramic_filter_layout = QGridLayout()
        self.configure_compact_filter_layout(ceramic_filter_layout)

        ceramic_filter_layout.addWidget(QLabel("Типоразмер:"), 0, 0)
        self.ceramic_body_combo = QComboBox()
        self.ceramic_body_combo.addItem("Все")
        self.ceramic_body_combo.currentTextChanged.connect(self.apply_ceramic_filters)
        ceramic_filter_layout.addWidget(self.ceramic_body_combo, 0, 1)

        ceramic_filter_layout.addWidget(QLabel("Номинал:"), 0, 2)
        self.ceramic_value_combo = QComboBox()
        self.ceramic_value_combo.addItem("Все")
        self.ceramic_value_combo.currentTextChanged.connect(self.apply_ceramic_filters)
        ceramic_filter_layout.addWidget(self.ceramic_value_combo, 0, 3)

        ceramic_filter_layout.addWidget(QLabel("Напряжение:"), 1, 0)
        self.ceramic_voltage_combo = QComboBox()
        self.ceramic_voltage_combo.addItem("Все")
        self.ceramic_voltage_combo.currentTextChanged.connect(self.apply_ceramic_filters)
        ceramic_filter_layout.addWidget(self.ceramic_voltage_combo, 1, 1)

        ceramic_filter_layout.addWidget(QLabel("Отклонение:"), 1, 2)
        self.ceramic_tolerance_combo = QComboBox()
        self.ceramic_tolerance_combo.addItem("Все")
        self.ceramic_tolerance_combo.currentTextChanged.connect(self.apply_ceramic_filters)
        ceramic_filter_layout.addWidget(self.ceramic_tolerance_combo, 1, 3)

        ceramic_filter_layout.addWidget(QLabel("Диэлектрик:"), 2, 0)
        self.ceramic_dielectric_combo = QComboBox()
        self.ceramic_dielectric_combo.addItem("Все")
        self.ceramic_dielectric_combo.currentTextChanged.connect(self.apply_ceramic_filters)
        ceramic_filter_layout.addWidget(self.ceramic_dielectric_combo, 2, 1)

        ceramic_filter_layout.addWidget(QLabel("Наличие:"), 3, 0)
        self.ceramic_stock_combo = QComboBox()
        self.ceramic_stock_combo.addItem("Все")
        self.ceramic_stock_combo.currentTextChanged.connect(self.apply_ceramic_filters)
        ceramic_filter_layout.addWidget(self.ceramic_stock_combo, 3, 1)

        ceramic_fullval_combos = self.add_fullval_filter_grid(
            ceramic_filter_layout, 0, self.apply_ceramic_filters
        )
        self.special_filter_sets['ceramic'] = [
                                                  ('body', 'BodyName', self.ceramic_body_combo),
                                                  ('value', 'FullVal0', self.ceramic_value_combo),
                                                  ('voltage', 'FullVal1', self.ceramic_voltage_combo),
                                                  ('tolerance', 'FullVal2', self.ceramic_tolerance_combo),
                                                  ('dielectric', 'FullVal3', self.ceramic_dielectric_combo),
                                                  ('stock', self.STOCK_COLUMN, self.ceramic_stock_combo),
                                              ] + [(f'full{index}', f'FullVal{index}', combo)
                                                   for index, combo in enumerate(ceramic_fullval_combos.values())]

        ceramic_filter_group.setLayout(ceramic_filter_layout)
        layout.addWidget(ceramic_filter_group)

        self.ceramic_table = QTableWidget()
        self.ceramic_table.setAlternatingRowColors(True)
        self.ceramic_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.ceramic_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.ceramic_table.setSortingEnabled(True)  # Включаем сортировку
        self.ceramic_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.ceramic_table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        layout.addWidget(self.ceramic_table)

        return widget

    def create_resistor_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Панель поиска по всем столбцам
        search_panel = QGroupBox("Поиск по всем столбцам")
        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Поиск:"))
        self.resistor_search_input = QLineEdit()
        self.resistor_search_input.setPlaceholderText("Введите текст для поиска во всех столбцах...")
        self.resistor_search_input.textChanged.connect(self.resistor_global_search)
        search_layout.addWidget(self.resistor_search_input)

        search_panel.setLayout(search_layout)
        layout.addWidget(search_panel)

        resistor_filter_group = QGroupBox("Фильтры для резисторов")
        resistor_filter_layout = QGridLayout()
        self.configure_compact_filter_layout(resistor_filter_layout)

        resistor_filter_layout.addWidget(QLabel("Типоразмер:"), 0, 0)
        self.resistor_body_combo = QComboBox()
        self.resistor_body_combo.addItem("Все")
        self.resistor_body_combo.currentTextChanged.connect(self.apply_resistor_filters)
        resistor_filter_layout.addWidget(self.resistor_body_combo, 0, 1)

        resistor_filter_layout.addWidget(QLabel("Номинал:"), 0, 2)
        self.resistor_value_combo = QComboBox()
        self.resistor_value_combo.addItem("Все")
        self.resistor_value_combo.currentTextChanged.connect(self.apply_resistor_filters)
        resistor_filter_layout.addWidget(self.resistor_value_combo, 0, 3)

        resistor_filter_layout.addWidget(QLabel("Точность:"), 1, 0)
        self.resistor_tolerance_combo = QComboBox()
        self.resistor_tolerance_combo.addItem("Все")
        self.resistor_tolerance_combo.currentTextChanged.connect(self.apply_resistor_filters)
        resistor_filter_layout.addWidget(self.resistor_tolerance_combo, 1, 1)

        resistor_filter_layout.addWidget(QLabel("Наличие:"), 2, 0)
        self.resistor_stock_combo = QComboBox()
        self.resistor_stock_combo.addItem("Все")
        self.resistor_stock_combo.currentTextChanged.connect(self.apply_resistor_filters)
        resistor_filter_layout.addWidget(self.resistor_stock_combo, 2, 1)

        resistor_fullval_combos = self.add_fullval_filter_grid(
            resistor_filter_layout, 0, self.apply_resistor_filters
        )
        self.special_filter_sets['resistor'] = [
                                                   ('body', 'BodyName', self.resistor_body_combo),
                                                   ('value', 'FullVal0', self.resistor_value_combo),
                                                   ('tolerance', 'FullVal1', self.resistor_tolerance_combo),
                                                   ('stock', self.STOCK_COLUMN, self.resistor_stock_combo),
                                               ] + [(f'full{index}', f'FullVal{index}', combo)
                                                    for index, combo in enumerate(resistor_fullval_combos.values())]

        resistor_filter_group.setLayout(resistor_filter_layout)
        layout.addWidget(resistor_filter_group)

        self.resistor_table = QTableWidget()
        self.resistor_table.setAlternatingRowColors(True)
        self.resistor_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.resistor_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.resistor_table.setSortingEnabled(True)  # Включаем сортировку
        self.resistor_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.resistor_table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        layout.addWidget(self.resistor_table)

        return widget

    def create_capacitor_tab(self, capacitor_type):
        """Создает вкладку для различных типов конденсаторов"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Панель поиска по всем столбцам
        search_panel = QGroupBox("Поиск по всем столбцам")
        search_layout = QHBoxLayout()

        search_layout.addWidget(QLabel("Поиск:"))
        search_input = QLineEdit()
        search_input.setPlaceholderText("Введите текст для поиска во всех столбцах...")
        search_layout.addWidget(search_input)

        search_panel.setLayout(search_layout)
        layout.addWidget(search_panel)

        filter_group = QGroupBox(f"Фильтры для {capacitor_type.lower()} конденсаторов")
        filter_layout = QGridLayout()
        self.configure_compact_filter_layout(filter_layout)

        filter_layout.addWidget(QLabel("Типоразмер:"), 0, 0)
        body_combo = QComboBox()
        body_combo.addItem("Все")
        filter_layout.addWidget(body_combo, 0, 1)

        filter_layout.addWidget(QLabel("Номинал:"), 0, 2)
        value_combo = QComboBox()
        value_combo.addItem("Все")
        filter_layout.addWidget(value_combo, 0, 3)

        filter_layout.addWidget(QLabel("Напряжение:"), 1, 0)
        voltage_combo = QComboBox()
        voltage_combo.addItem("Все")
        filter_layout.addWidget(voltage_combo, 1, 1)

        filter_layout.addWidget(QLabel("Наличие:"), 2, 0)
        stock_combo = QComboBox()
        stock_combo.addItem("Все")
        filter_layout.addWidget(stock_combo, 2, 1)

        fullval_combos = self.add_fullval_filter_grid(filter_layout, 0, lambda: None)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setSortingEnabled(True)  # Включаем сортировку
        table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        layout.addWidget(table)

        # Сохраняем ссылки на виджеты
        if capacitor_type == "Электролитические":
            self.electrolytic_body_combo = body_combo
            self.electrolytic_value_combo = value_combo
            self.electrolytic_voltage_combo = voltage_combo
            self.electrolytic_stock_combo = stock_combo
            self.electrolytic_table = table
            self.electrolytic_search_input = search_input

            body_combo.currentTextChanged.connect(self.apply_electrolytic_filters)
            value_combo.currentTextChanged.connect(self.apply_electrolytic_filters)
            voltage_combo.currentTextChanged.connect(self.apply_electrolytic_filters)
            stock_combo.currentTextChanged.connect(self.apply_electrolytic_filters)
            for combo in fullval_combos.values():
                combo.currentTextChanged.connect(self.apply_electrolytic_filters)
            self.special_filter_sets['electrolytic'] = [
                                                           ('body', 'BodyName', body_combo),
                                                           ('value', 'FullVal0', value_combo),
                                                           ('voltage', 'FullVal1', voltage_combo),
                                                           ('stock', self.STOCK_COLUMN, stock_combo),
                                                       ] + [(f'full{index}', f'FullVal{index}', combo)
                                                            for index, combo in enumerate(fullval_combos.values())]
            search_input.textChanged.connect(self.electrolytic_global_search)

        elif capacitor_type == "Танталовые":
            self.tantalum_body_combo = body_combo
            self.tantalum_value_combo = value_combo
            self.tantalum_voltage_combo = voltage_combo
            self.tantalum_stock_combo = stock_combo
            self.tantalum_table = table
            self.tantalum_search_input = search_input

            body_combo.currentTextChanged.connect(self.apply_tantalum_filters)
            value_combo.currentTextChanged.connect(self.apply_tantalum_filters)
            voltage_combo.currentTextChanged.connect(self.apply_tantalum_filters)
            stock_combo.currentTextChanged.connect(self.apply_tantalum_filters)
            for combo in fullval_combos.values():
                combo.currentTextChanged.connect(self.apply_tantalum_filters)
            self.special_filter_sets['tantalum'] = [
                                                       ('body', 'BodyName', body_combo),
                                                       ('value', 'FullVal0', value_combo),
                                                       ('voltage', 'FullVal1', voltage_combo),
                                                       ('stock', self.STOCK_COLUMN, stock_combo),
                                                   ] + [(f'full{index}', f'FullVal{index}', combo)
                                                        for index, combo in enumerate(fullval_combos.values())]
            search_input.textChanged.connect(self.tantalum_global_search)

        elif capacitor_type == "Полимерные":
            self.polymer_body_combo = body_combo
            self.polymer_value_combo = value_combo
            self.polymer_voltage_combo = voltage_combo
            self.polymer_stock_combo = stock_combo
            self.polymer_table = table
            self.polymer_search_input = search_input

            body_combo.currentTextChanged.connect(self.apply_polymer_filters)
            value_combo.currentTextChanged.connect(self.apply_polymer_filters)
            voltage_combo.currentTextChanged.connect(self.apply_polymer_filters)
            stock_combo.currentTextChanged.connect(self.apply_polymer_filters)
            for combo in fullval_combos.values():
                combo.currentTextChanged.connect(self.apply_polymer_filters)
            self.special_filter_sets['polymer'] = [
                                                      ('body', 'BodyName', body_combo),
                                                      ('value', 'FullVal0', value_combo),
                                                      ('voltage', 'FullVal1', voltage_combo),
                                                      ('stock', self.STOCK_COLUMN, stock_combo),
                                                  ] + [(f'full{index}', f'FullVal{index}', combo)
                                                       for index, combo in enumerate(fullval_combos.values())]
            search_input.textChanged.connect(self.polymer_global_search)

        return widget

    def create_status_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("""
            QTextEdit {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                padding: 10px;
                font-family: monospace;
            }
        """)

        layout.addWidget(QLabel("Журнал операций:"))
        layout.addWidget(self.status_text)

        return widget

    def show_header_context_menu(self, position):
        """Показывает контекстное меню для заголовков таблицы"""
        table = self.sender().parentWidget()  # Получаем таблицу из заголовка

        menu = QMenu()

        # Добавляем действие для настройки столбцов
        configure_action = QAction("Настроить столбцы...", self)
        configure_action.triggered.connect(lambda: self.configure_columns_for_table(table))
        menu.addAction(configure_action)

        menu.addSeparator()

        # Добавляем действия для показа/скрытия каждого столбца
        for i in range(1, table.columnCount()):
            header = table.horizontalHeaderItem(i).text()
            action = QAction(header, self)
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(i))
            action.triggered.connect(lambda checked, idx=i, tbl=table:
                                     self.toggle_column_visibility(tbl, idx, checked))
            menu.addAction(action)

        menu.exec_(table.horizontalHeader().mapToGlobal(position))

    def toggle_column_visibility(self, table, column_index, visible):
        """Показывает или скрывает столбец таблицы"""
        if visible:
            table.showColumn(column_index)
        else:
            table.hideColumn(column_index)

    def configure_columns_for_table(self, table):
        """Настраивает столбцы для конкретной таблицы"""
        # Отбрасываем служебные колонки (звезда избранного и статус наличия).
        current = [table.horizontalHeaderItem(i).text()
                   for i in range(1, table.columnCount())
                   if table.horizontalHeaderItem(i).text() not in ("⭐", self.STOCK_HEADER)]
        dialog = ColumnConfigDialog(current, self.headers, self)

        if dialog.exec_() == QDialog.Accepted:
            selected_headers = dialog.get_selected_headers()
            self.current_headers = selected_headers

            # Обновляем все таблицы
            self.update_table_headers(self.search_table)
            self.update_table_headers(self.ceramic_table)
            self.update_table_headers(self.resistor_table)
            self.update_table_headers(self.electrolytic_table)
            self.update_table_headers(self.tantalum_table)
            self.update_table_headers(self.polymer_table)
            for cfg in self.custom_tabs.values():
                self.update_table_headers(cfg['table'])

            # Перерисовываем данные в текущей таблице
            current_tab = self.tab_widget.currentWidget()
            if current_tab == self.search_tab and hasattr(self, 'filtered_data'):
                self.display_data_in_table(self.search_table, self.filtered_data)
            elif current_tab == self.ceramic_tab:
                self.apply_ceramic_filters()
            elif current_tab == self.resistor_tab:
                self.apply_resistor_filters()
            elif current_tab == self.electrolytic_tab:
                self.apply_electrolytic_filters()
            elif current_tab == self.tantalum_tab:
                self.apply_tantalum_filters()
            elif current_tab == self.polymer_tab:
                self.apply_polymer_filters()
            else:
                for key, cfg in self.custom_tabs.items():
                    if cfg['widget'] == current_tab:
                        self.apply_special_smart_filters(key, cfg['patterns'], cfg['table'])
                        break

    def update_table_headers(self, table):
        """Обновляет заголовки таблицы"""
        if table.columnCount() > 0:
            table.setHorizontalHeaderLabels(["⭐"] + self.current_headers + [self.STOCK_HEADER])

    def configure_columns(self):
        """Открывает диалог настройки столбцов"""
        self.configure_columns_for_table(self.search_table)

    def log_status(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.append(f"[{timestamp}] {message}")

    # ---------- Наличие на складе ----------
    def stock_value(self, row):
        """Безопасно возвращает числовой остаток QtyStockSum."""
        value = row.get('QtyStockSum', 0)
        try:
            text = str(value).strip().replace(',', '.')
            return float(text) if text else 0.0
        except (TypeError, ValueError):
            return 0.0

    def min_stock_value(self, row):
        """Безопасно возвращает минимальный остаток MinQty."""
        value = row.get('MinQty', 0)
        try:
            text = str(value).strip().replace(',', '.')
            return float(text) if text else 0.0
        except (TypeError, ValueError):
            return 0.0

    STOCK_COLUMN = '__STOCK__'
    STOCK_HEADER = 'Наличие'
    STOCK_ALL = 'Все'
    STOCK_IN = 'В наличии'
    STOCK_LOW = 'Меньше минимального остатка'
    STOCK_NONE = 'Нет на складе'

    def stock_status(self, row):
        """Возвращает текстовый статус наличия строки."""
        stock = self.stock_value(row)
        min_qty = self.min_stock_value(row)
        if stock <= 0:
            return self.STOCK_NONE
        if min_qty > 0 and stock < min_qty:
            return self.STOCK_LOW
        return self.STOCK_IN

    def _filter_row_value(self, row, column):
        """Возвращает значение псевдо-колонки для фильтра (для наличия — вычисляется)."""
        if column == self.STOCK_COLUMN:
            return self.stock_status(row)
        return str(row.get(column, '')).strip()

    # ---------- Многочастный поиск ----------
    def _search_normalize(self, value):
        """Нормализация для поиска: допускает 10k и 10 kΩ как один запрос."""
        text = self.normalize_value(value)
        text = text.lower()
        text = text.replace('ё', 'е')
        text = re.sub(r'\s+', '', text)
        return text

    def _row_normalized(self, row):
        """Кэшированная нормализованная строка для быстрого поиска."""
        rid = id(row)
        cached = self._hay_cache.get(rid)
        if cached is None:
            cached = self._search_normalize(' '.join(str(v) for v in row.values()))
            self._hay_cache[rid] = cached
        return cached

    def search_terms_match(self, row, query):
        """Каждая часть запроса должна встретиться где-либо в строке, порядок не важен."""
        terms = [self._search_normalize(part) for part in re.split(r'\s+', str(query).strip()) if part.strip()]
        if not terms:
            return True

        haystack = self._row_normalized(row)
        return all(term in haystack for term in terms)

    # ---------- Автодополнение и подсветка поиска ----------
    def _setup_completers(self):
        """Настраивает автодополнение для полей поиска (как в браузере)."""
        model = QStringListModel([], self)
        for line_edit in (self.search_input, self.global_search_input):
            completer = QCompleter(model, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            line_edit.setCompleter(completer)

    def _build_suggestions(self):
        """Собирает уникальные значения из данных для автодополнения."""
        suggestions = set()
        columns = ['FullVal0', 'FullVal1', 'FullVal2', 'FullVal3',
                   'FullVal4', 'FullVal5', 'BodyName', 'PartNumber', 'Name']
        for row in getattr(self, 'all_data', []) or []:
            for column in columns:
                value = str(row.get(column, '')).strip()
                if value:
                    suggestions.add(value)
        self._suggestion_list = sorted(suggestions, key=str.lower)
        for line_edit in (self.search_input, self.global_search_input):
            cmp = line_edit.completer()
            if cmp is not None:
                cmp.model().setStringList(self._suggestion_list)

    def _set_table_query(self, table, query):
        """Задаёт текст подсветки для таблицы и перерисовывает её."""
        table._highlight_query = query or ""
        if table.isVisible():
            table.viewport().update()

    def _schedule_main_filter(self):
        """Откладывает перестроение таблицы поиска, чтобы ввод не лагал."""
        if self._filter_timer is None:
            self._filter_timer = QTimer(self)
            self._filter_timer.setSingleShot(True)
            self._filter_timer.setInterval(180)
            self._filter_timer.timeout.connect(self._run_debounced_main_filter)
        self._filter_timer.start()

    def _run_debounced_main_filter(self):
        """Выполняет отложенную фильтрацию главной таблицы."""
        self.apply_main_filters(rebuild_options=False)
        # Подсветка должна остаться актуальной после фактического фильтра.
        self._set_table_query(self.search_table, self._combined_search_text())

    # ---------- История файлов ----------
    def recent_files(self):
        files = self.settings.value("recent_files", [], type=list)
        if isinstance(files, str):
            files = [files]
        return [path for path in files if path and os.path.exists(path)]

    def add_recent_file(self, file_path):
        files = [file_path] + [
            path for path in self.recent_files() if os.path.abspath(path) != os.path.abspath(file_path)
        ]
        files = files[:10]
        self.settings.setValue("recent_files", files)

    def show_recent_files_menu(self):
        menu = QMenu(self)
        files = self.recent_files()

        if not files:
            action = menu.addAction("Нет недавно открытых файлов")
            action.setEnabled(False)
        else:
            for file_path in files:
                action = QAction(os.path.basename(file_path), self)
                action.setToolTip(file_path)
                action.triggered.connect(
                    lambda checked=False, path=file_path: self.open_recent_file(path)
                )
                menu.addAction(action)

            menu.addSeparator()
            clear_action = QAction("Очистить историю", self)
            clear_action.triggered.connect(self.clear_recent_files)
            menu.addAction(clear_action)

        menu.exec_(self.recent_btn.mapToGlobal(
            self.recent_btn.rect().bottomLeft()
        ))

    def open_recent_file(self, file_path):
        if not os.path.exists(file_path):
            self.clear_recent_files()
            QMessageBox.warning(self, "Файл не найден", f"Файл больше не существует:\n{file_path}")
            return

        self.input_file = file_path
        self.add_recent_file(file_path)
        self.settings.setValue("last_file", file_path)
        self.input_label.setText(f"Входной файл: {os.path.basename(file_path)}")
        self.filter_btn.setEnabled(True)
        self.columns_btn.setEnabled(True)
        self.load_csv_data(file_path)
        self.load_initial_tab_data()
        self.log_status(f"Открыт файл из истории: {file_path}")

    def clear_recent_files(self):
        self.settings.setValue("recent_files", [])
        self.settings.remove("last_file")

    def restore_last_file(self):
        if not hasattr(self, 'auto_open_checkbox') or not self.auto_open_checkbox.isChecked():
            return

        last_file = self.settings.value("last_file", "", type=str)
        if last_file and os.path.exists(last_file):
            self.open_recent_file(last_file)

    # ---------- Избранное ----------
    def component_key(self, row):
        """Стабильный ключ компонента для избранного."""
        part = str(row.get('PartNumber', '')).strip()
        name = str(row.get('Name', '')).strip()
        code = str(row.get('Code', '')).strip()
        category = str(row.get('GroupName', '')).strip()

        key = part or name or code
        if not key:
            key = '|'.join(str(row.get(h, '')).strip() for h in self.headers[:5])
        return f"{category}::{key}"

    def load_favorites(self):
        try:
            stored = self.settings.value("favorites_json", "[]", type=str)
            self.favorites = set(json.loads(stored))
        except Exception:
            self.favorites = set()

    def save_favorites(self):
        self.settings.setValue("favorites_json", json.dumps(sorted(self.favorites), ensure_ascii=False))

    def on_table_cell_clicked(self, row, column):
        if column != 0:
            return

        table = self.sender()
        item = table.item(row, 0)
        if not item:
            return

        key = item.data(Qt.UserRole)
        if not key:
            return

        if key in self.favorites:
            self.favorites.remove(key)
        else:
            self.favorites.add(key)

        self.save_favorites()
        self.refresh_all_tables()
        self.refresh_favorites_tab()

    def find_favorite_rows(self):
        result = []
        seen = set()
        for row in self.all_data:
            key = self.component_key(row)
            if key in self.favorites and key not in seen:
                result.append(row)
                seen.add(key)
        return result

    def refresh_all_tables(self):
        """Обновляет только звёздочки, не сбрасывая текущие фильтры и позицию прокрутки."""
        tables = [
            getattr(self, 'search_table', None),
            getattr(self, 'ceramic_table', None),
            getattr(self, 'resistor_table', None),
            getattr(self, 'electrolytic_table', None),
            getattr(self, 'tantalum_table', None),
            getattr(self, 'polymer_table', None),
        ] + [cfg['table'] for cfg in self.custom_tabs.values()]

        for table in tables:
            if table is None:
                continue
            for row_idx in range(table.rowCount()):
                star_item = table.item(row_idx, 0)
                if not star_item:
                    continue
                key = star_item.data(Qt.UserRole)
                if not key:
                    continue
                is_favorite = key in self.favorites
                star_item.setText("★" if is_favorite else "☆")
                star_item.setToolTip(
                    "Убрать из избранного" if is_favorite else "Добавить в избранное"
                )

    def create_favorites_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        top = QHBoxLayout()
        top.addWidget(QLabel("⭐ Избранные компоненты"))
        top.addStretch()

        self.compare_btn = QPushButton("Сравнить выбранные (2–5)")
        self.compare_btn.clicked.connect(self.compare_selected_favorites)
        top.addWidget(self.compare_btn)

        self.remove_favorites_btn = QPushButton("Удалить выбранные")
        self.remove_favorites_btn.clicked.connect(self.remove_selected_favorites)
        top.addWidget(self.remove_favorites_btn)

        layout.addLayout(top)

        self.favorites_table = QTableWidget()
        self.favorites_table.setColumnCount(6)
        self.favorites_table.setHorizontalHeaderLabels([
            "✓", "⭐", "Название", "PartNumber", "Категория", "Остаток"
        ])
        self.favorites_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.favorites_table.setAlternatingRowColors(True)
        self.favorites_table.setSortingEnabled(True)
        layout.addWidget(self.favorites_table)

        return widget

    def refresh_favorites_tab(self):
        if not hasattr(self, 'favorites_table'):
            return

        rows = self.find_favorite_rows()
        self.favorites_table.setSortingEnabled(False)
        self.favorites_table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            key = self.component_key(row)

            check = QTableWidgetItem()
            check.setFlags(check.flags() | Qt.ItemIsUserCheckable)
            check.setCheckState(Qt.Unchecked)
            check.setData(Qt.UserRole, key)
            self.favorites_table.setItem(i, 0, check)

            star = QTableWidgetItem("★")
            star.setTextAlignment(Qt.AlignCenter)
            star.setData(Qt.UserRole, key)
            self.favorites_table.setItem(i, 1, star)

            values = [
                str(row.get('Name', '')),
                str(row.get('PartNumber', '')),
                str(row.get('GroupName', '')),
                str(row.get('QtyStockSum', '')),
            ]
            for col, value in enumerate(values, start=2):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, key)
                self.favorites_table.setItem(i, col, item)

        self.favorites_table.setColumnWidth(0, 35)
        self.favorites_table.setColumnWidth(1, 40)
        self.favorites_table.resizeColumnsToContents()
        self.favorites_table.setSortingEnabled(True)

    def selected_favorite_rows(self):
        selected = []
        keys = set()

        for row_idx in range(self.favorites_table.rowCount()):
            check = self.favorites_table.item(row_idx, 0)
            if check and check.checkState() == Qt.Checked:
                key = check.data(Qt.UserRole)
                if key:
                    keys.add(key)

        for row in self.find_favorite_rows():
            if self.component_key(row) in keys:
                selected.append(row)

        return selected

    def remove_selected_favorites(self):
        rows = self.selected_favorite_rows()
        if not rows:
            QMessageBox.information(self, "Избранное", "Выберите хотя бы один компонент.")
            return

        for row in rows:
            self.favorites.discard(self.component_key(row))

        self.save_favorites()
        self.refresh_favorites_tab()
        self.refresh_all_tables()

    def compare_selected_favorites(self):
        rows = self.selected_favorite_rows()

        if not 2 <= len(rows) <= 5:
            QMessageBox.warning(
                self,
                "Сравнение",
                "Для сравнения выберите от 2 до 5 компонентов."
            )
            return

        categories = {str(row.get('GroupName', '')).strip() for row in rows}
        if len(categories) != 1:
            QMessageBox.warning(
                self,
                "Сравнение",
                "Сравнивать можно только компоненты из одной категории."
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Сравнение компонентов")
        dialog.resize(1100, 650)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            f"Сравнение {len(rows)} компонентов — категория: {next(iter(categories))}"
        ))

        key_fields = [
            'Name', 'PartNumber', 'ManufactName', 'BodyName',
            'FullVal0', 'FullVal1', 'FullVal2', 'FullVal3',
            'FullVal4', 'FullVal5', 'QtyStockSum', 'MinQty',
            'StoreFullName', 'StatusName', 'Description'
        ]
        key_fields = [field for field in key_fields if field in self.headers]

        table = QTableWidget()
        table.setRowCount(len(key_fields))
        table.setColumnCount(len(rows) + 1)

        headers = ["Параметр"] + [
            str(row.get('PartNumber') or row.get('Name') or '')
            for row in rows
        ]
        table.setHorizontalHeaderLabels(headers)

        for r, field in enumerate(key_fields):
            table.setItem(r, 0, QTableWidgetItem(field))
            for c, row in enumerate(rows, start=1):
                value = str(row.get(field, ''))
                item = QTableWidgetItem(value)
                table.setItem(r, c, item)

        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        layout.addWidget(table)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec_()

    def select_input_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Выберите CSV файл", "", "CSV Files (*.csv)"
        )

        if file_name:
            self.input_file = file_name
            self.input_label.setText(f"Входной файл: {os.path.basename(file_name)}")
            self.add_recent_file(file_name)
            self.settings.setValue("last_file", file_name)
            self.filter_btn.setEnabled(True)
            self.columns_btn.setEnabled(True)
            self.load_csv_data(file_name)
            self.log_status(f"Загружен файл: {file_name}")

            # После загрузки файла сразу загружаем данные для вкладок
            self.load_initial_tab_data()

    def load_csv_data(self, file_path):
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file, delimiter=';')
                self.headers = reader.fieldnames
                self.all_data = list(reader)

            self.normalized_data = [self.normalize_row(row) for row in self.all_data]

            self._hay_cache = {}  # сброс кэша нормализованных строк для поиска
            self._build_suggestions()

            self.log_status(f"Загружено записей: {len(self.all_data)}")
            self.add_tab_btn.setEnabled(True)
            self.update_category_list()
            self.update_main_smart_filters()
            self.display_data_in_table(self.search_table, self.all_data)
            self.refresh_favorites_tab()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файл:\n{str(e)}")

    def load_initial_tab_data(self):
        """Загружает данные для вкладок при открытии файла"""
        if not hasattr(self, 'all_data') or not self.all_data:
            return

        # Фильтруем данные по "Чистая зона" для начальной загрузки
        filtered_data = []
        filtered_indices = []

        for idx, row in enumerate(self.all_data):
            store_full_name = row.get('StoreFullName', '')
            if store_full_name and 'Чистая зона' in store_full_name:
                filtered_data.append(row)
                filtered_indices.append(idx)

        if filtered_data:
            self.filtered_data = filtered_data
            self.filtered_normalized = [self.normalized_data[i] for i in filtered_indices]

            # Обновляем специализированные вкладки
            self.update_special_tabs()
            self.update_main_smart_filters()
            self.apply_main_filters()
            self.log_status(f"Загружено {len(filtered_data)} записей для вкладок")

    def update_category_list(self):
        categories = set()
        for row in self.all_data:
            category = row.get('GroupName', '')
            if category:
                categories.add(category)

        self.category_combo.clear()
        self.category_combo.addItem("Все категории")
        self.category_combo.addItems(sorted(categories))

    def _main_filter_source(self):
        """Возвращает набор строк, доступный для общего поиска."""
        return self.filtered_data if getattr(self, 'filtered_data', None) else getattr(self, 'all_data', [])

    def add_fullval_filter_grid(self, layout, start_row, callback, start_column=4):
        """Добавляет компактный блок: FullVal0–2 слева, FullVal3–5 справа."""
        combos = {}
        for index in range(6):
            row = start_row + index % 3
            column = start_column + (index // 3) * 2
            layout.addWidget(QLabel(f"FullVal {index}:"), row, column)
            combo = QComboBox()
            combo.addItem("Все")
            combo.setFixedWidth(125)
            combo.currentTextChanged.connect(callback)
            layout.addWidget(combo, row, column + 1)
            combos[f'FullVal{index}'] = combo
        return combos

    def configure_compact_filter_layout(self, layout):
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)
        for column in (1, 3, 5):
            layout.setColumnStretch(column, 1)

    # ---------- Пользовательские вкладки ----------
    def _matches_category(self, row, matcher):
        """True, если категория строки подходит под условие вкладки."""
        category = row.get('GroupName', '')
        if isinstance(matcher, str):
            # Встроенные вкладки: поиск подстроки.
            return matcher in category.lower()
        # Пользовательские вкладки: точное совпадение с одной из категорий.
        return category in matcher

    def _next_custom_key(self):
        index = 1
        while f'custom_{index}' in self.special_filter_sets:
            index += 1
        return f'custom_{index}'

    def _key_for_custom_widget(self, widget):
        for key, cfg in self.custom_tabs.items():
            if cfg['widget'] is widget:
                return key
        return None

    def create_custom_tab(self, title, patterns):
        """Создаёт вкладку, объединяющую несколько категорий."""
        key = self._next_custom_key()

        widget = QWidget()
        layout = QVBoxLayout(widget)

        search_panel = QGroupBox("Поиск по всем столбцам")
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Поиск:"))
        search_input = QLineEdit()
        search_input.setPlaceholderText("Введите текст для поиска во всех столбцах...")
        search_layout.addWidget(search_input)
        search_panel.setLayout(search_layout)
        layout.addWidget(search_panel)

        filter_group = QGroupBox(f"Фильтры: {title}")
        filter_layout = QGridLayout()
        self.configure_compact_filter_layout(filter_layout)

        filter_layout.addWidget(QLabel("Типоразмер:"), 0, 0)
        body_combo = QComboBox()
        body_combo.addItem("Все")
        filter_layout.addWidget(body_combo, 0, 1)

        filter_layout.addWidget(QLabel("Наличие:"), 1, 0)
        stock_combo = QComboBox()
        stock_combo.addItem("Все")
        filter_layout.addWidget(stock_combo, 1, 1)

        fullval_combos = self.add_fullval_filter_grid(filter_layout, 0, lambda _=None: None)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        table = QTableWidget()
        table.setAlternatingRowColors(True)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setSortingEnabled(True)
        table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        table.horizontalHeader().customContextMenuRequested.connect(self.show_header_context_menu)
        layout.addWidget(table)

        self.special_filter_sets[key] = [
            ('body', 'BodyName', body_combo),
            ('stock', self.STOCK_COLUMN, stock_combo),
        ] + [(f'full{index}', f'FullVal{index}', combo)
             for index, combo in enumerate(fullval_combos.values())]

        for combo in [body_combo, stock_combo] + list(fullval_combos.values()):
            combo.currentTextChanged.connect(
                lambda _=None, k=key, m=list(patterns), t=table:
                self.apply_special_smart_filters(k, m, t))
        search_input.textChanged.connect(
            lambda text, k=key, t=table: self._custom_tab_search(k, t, text))

        self.custom_tabs[key] = {
            'title': title,
            'patterns': list(patterns),
            'widget': widget,
            'table': table,
            'search_input': search_input,
        }
        return widget

    def add_custom_tab(self, title, patterns, persist=True):
        """Добавляет готовую пользовательскую вкладку в интерфейс."""
        widget = self.create_custom_tab(title, patterns)
        self.tab_widget.addTab(widget, title)
        self.tab_widget.setCurrentWidget(widget)

        key = self._key_for_custom_widget(widget)
        cfg = self.custom_tabs[key]
        if self.filtered_normalized:
            indices = [i for i, row in enumerate(self.filtered_normalized)
                       if self._matches_category(row, cfg['patterns'])]
            self.display_data_in_table(cfg['table'],
                                       [self.filtered_data[i] for i in indices])
            self.update_special_smart_filters(key, cfg['patterns'])
        if persist:
            self.save_custom_tabs()
        self.log_status(f"Создана вкладка «{title}» ({len(patterns)} категор.)")

    def add_custom_tab_dialog(self):
        """Диалог создания пользовательской вкладки."""
        if not self.all_data:
            QMessageBox.information(self, "Новая вкладка",
                                    "Сначала загрузите файл с данными.")
            return

        categories = sorted({
            str(row.get('GroupName', '')).strip()
            for row in self.all_data
            if str(row.get('GroupName', '')).strip()
        })
        dialog = CustomTabDialog(categories, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        title = dialog.tab_title()
        selected = dialog.selected_categories()
        if not title:
            QMessageBox.warning(self, "Новая вкладка", "Укажите название вкладки.")
            return
        if not selected:
            QMessageBox.warning(self, "Новая вкладка",
                                "Отметьте хотя бы одну категорию.")
            return

        existing_titles = [self.tab_widget.tabText(i)
                           for i in range(self.tab_widget.count())]
        if title in existing_titles:
            QMessageBox.warning(self, "Новая вкладка",
                                "Вкладка с таким названием уже существует.")
            return

        patterns = [self.normalize_value(category) for category in selected]
        self.add_custom_tab(title, patterns)

    def _custom_tab_search(self, key, table, text):
        """Поиск по всем столбцам пользовательской вкладки."""
        self._set_table_query(table, text)
        self.perform_global_search(text, table)

    def on_tab_close_requested(self, index):
        """Закрывает пользовательскую вкладку; встроенные не закрываются."""
        widget = self.tab_widget.widget(index)
        key = self._key_for_custom_widget(widget)
        if key is None:
            return
        title = self.tab_widget.tabText(index)
        self.tab_widget.removeTab(index)
        self.custom_tabs.pop(key, None)
        self.special_filter_sets.pop(key, None)
        self.save_custom_tabs()
        self.log_status(f"Удалена вкладка «{title}»")

    def save_custom_tabs(self):
        configs = [
            {'title': cfg['title'], 'patterns': cfg['patterns']}
            for cfg in self.custom_tabs.values()
        ]
        self.settings.setValue("custom_tabs_json",
                               json.dumps(configs, ensure_ascii=False))

    def restore_custom_tabs(self):
        try:
            stored = self.settings.value("custom_tabs_json", "[]", type=str)
            configs = json.loads(stored)
        except Exception:
            configs = []
        for cfg in configs:
            title = str(cfg.get('title', '')).strip() or 'Моя вкладка'
            patterns = [str(p) for p in cfg.get('patterns', []) if p]
            if patterns:
                self.add_custom_tab(title, patterns, persist=False)

    def update_special_smart_filters(self, key, matcher):
        """Оставляет в каждом фильтре только значения, совместимые с остальными."""
        if key not in self.special_filter_sets or not hasattr(self, 'filtered_normalized'):
            return
        filters = self.special_filter_sets[key]
        source = [row for row in self.filtered_normalized
                  if self._matches_category(row, matcher)]
        for filter_id, column, combo in filters:
            current = combo.currentText()
            values = set()
            for row in source:
                if all(other_id == filter_id or other_combo.currentText() == "Все"
                       or self._filter_row_value(row, other_column) == other_combo.currentText()
                       for other_id, other_column, other_combo in filters):
                    value = self._filter_row_value(row, column)
                    if value:
                        values.add(value)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Все")
            if column == self.STOCK_COLUMN:
                # Фиксированный логичный порядок статусов наличия.
                order = [self.STOCK_IN, self.STOCK_LOW, self.STOCK_NONE]
                combo.addItems([s for s in order if s in values])
            else:
                combo.addItems(sorted(values, key=str.lower))
            combo.setCurrentText(current if current in values else "Все")
            combo.blockSignals(False)

    def apply_special_smart_filters(self, key, matcher, table):
        self.update_special_smart_filters(key, matcher)
        filters = self.special_filter_sets[key]
        result = []
        for index, row in enumerate(self.filtered_normalized):
            if not self._matches_category(row, matcher):
                continue
            if all(combo.currentText() == "Все"
                   or self._filter_row_value(row, column) == combo.currentText()
                   for _, column, combo in filters):
                result.append(self.filtered_data[index])
        self.display_data_in_table(table, result)

    def _matches_main_filters(self, row, exclude_column=None, include_text=True, exclude_stock=False):
        """Проверяет строку по всем условиям главной вкладки."""
        category = self.category_combo.currentText()
        if category != "Все категории" and row.get('GroupName', '') != category:
            return False

        for column, combo in self.main_smart_filters.items():
            if column == exclude_column:
                continue
            selected = combo.currentText()
            if selected != "Все" and str(row.get(column, '')).strip() != selected:
                return False

        if include_text:
            search_text = self.search_input.text()
            global_text = self.global_search_input.text()
            for text in (search_text, global_text):
                if text and not self.search_terms_match(row, text):
                    return False

        if not exclude_stock and hasattr(self, 'stock_filter_combo'):
            stock_filter = self.stock_filter_combo.currentText()
            stock = self.stock_value(row)
            min_qty = self.min_stock_value(row)

            if stock_filter == "В наличии" and stock <= 0:
                return False
            elif stock_filter == "Меньше минимального остатка":
                if min_qty <= 0 or stock >= min_qty:
                    return False
            elif stock_filter == "Нет на складе" and stock > 0:
                return False

        return True

    def _main_stock_status(self, row):
        """Текстовый статус наличия (те же названия, что в stock_status)."""
        return self.stock_status(row)

    def update_main_smart_filters(self):
        """Обновляет варианты BodyName/FullVal без сброса допустимого выбора."""
        if not hasattr(self, 'main_smart_filters'):
            return
        source = self._main_filter_source()
        for column, combo in self.main_smart_filters.items():
            current = combo.currentText()
            values = {
                str(row.get(column, '')).strip()
                for row in source
                if str(row.get(column, '')).strip()
                   and self._matches_main_filters(row, exclude_column=column)
            }
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Все")
            combo.addItems(sorted(values, key=lambda value: value.lower()))
            combo.setCurrentText(current if current in values else "Все")
            combo.blockSignals(False)

        # Умный фильтр наличия: показываем только статусы, доступные при остальных фильтрах.
        if hasattr(self, 'stock_filter_combo'):
            stock_combo = self.stock_filter_combo
            current = stock_combo.currentText()
            statuses = {
                self.stock_status(row)
                for row in source
                if self._matches_main_filters(row, exclude_stock=True)
            }
            order = [self.STOCK_IN, self.STOCK_LOW, self.STOCK_NONE]
            available = [s for s in order if s in statuses]
            stock_combo.blockSignals(True)
            stock_combo.clear()
            stock_combo.addItem("Все")
            stock_combo.addItems(available)
            stock_combo.setCurrentText(current if not current or current in available else "Все")
            stock_combo.blockSignals(False)

    def apply_main_filters(self, rebuild_options=True):
        """Применяет все фильтры общего поиска как единое условие AND.
        При изменении только текста поиска тяжёлый пересчёт опций фильтров
        пропускается (rebuild_options=False), чтобы убрать лаги при вводе."""
        if not self._main_filter_source():
            return
        if rebuild_options:
            self.update_main_smart_filters()
        result = [row for row in self._main_filter_source()
                  if self._matches_main_filters(row)]
        self.display_data_in_table(self.search_table, result)
        self._set_table_query(self.search_table, self._combined_search_text())

    def on_quick_search(self, text):
        """Быстрый поиск: подсветка сразу, фильтрация — с отсечкой (без лагов)."""
        self._set_table_query(self.search_table, self._combined_search_text())
        self._schedule_main_filter()

    def _combined_search_text(self):
        """Для подсветки объединяем оба поля поиска главной вкладки."""
        parts = [self.search_input.text(), self.global_search_input.text()]
        parts = [p for p in parts if p]
        return " ".join(parts)

    # Функции глобального поиска для каждой таблицы
    def global_search(self, text):
        """Глобальный поиск: подсветка сразу, фильтрация — с отсечкой (без лагов)."""
        self._set_table_query(self.search_table, self._combined_search_text())
        self._schedule_main_filter()

    def ceramic_global_search(self, text):
        """Глобальный поиск по всем столбцам в таблице керамических конденсаторов"""
        self._set_table_query(self.ceramic_table, text)
        self.perform_global_search(text, self.ceramic_table)

    def resistor_global_search(self, text):
        """Глобальный поиск по всем столбцам в таблице резисторов"""
        self._set_table_query(self.resistor_table, text)
        self.perform_global_search(text, self.resistor_table)

    def electrolytic_global_search(self, text):
        """Глобальный поиск по всем столбцам в таблице электролитических конденсаторов"""
        self._set_table_query(self.electrolytic_table, text)
        self.perform_global_search(text, self.electrolytic_table)

    def tantalum_global_search(self, text):
        """Глобальный поиск по всем столбцам в таблице таллантовых конденсаторов"""
        self._set_table_query(self.tantalum_table, text)
        self.perform_global_search(text, self.tantalum_table)

    def polymer_global_search(self, text):
        """Глобальный поиск по всем столбцам в таблице полимерных конденсаторов"""
        self._set_table_query(self.polymer_table, text)
        self.perform_global_search(text, self.polymer_table)

    def perform_global_search(self, text, table):
        """Глобальный поиск по кэшу данных вкладки: все слова запроса должны присутствовать."""
        base = self._table_base.get(id(table), [])
        if not text:
            self.display_data_in_table(table, base)
            return

        filtered_data = [
            row_data for row_data in base
            if self.search_terms_match(row_data, text)
        ]
        self.display_data_in_table(table, filtered_data)

    def filter_and_save(self):
        if not self.input_file:
            return

        output_file, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отфильтрованный файл",
            f"{datetime.now().strftime('%Y-%m-%d')}_component_list.csv",
            "CSV Files (*.csv)"
        )

        if not output_file:
            return

        try:
            filtered_data = []
            filtered_indices = []

            for idx, row in enumerate(self.all_data):
                store_full_name = row.get('StoreFullName', '')
                if store_full_name and 'Чистая зона' in store_full_name:
                    filtered_data.append(row)
                    filtered_indices.append(idx)

            if not filtered_data:
                QMessageBox.warning(self, "Предупреждение",
                                    "Не найдено записей с 'Чистая зона' в месте хранения")
                return

            with open(output_file, 'w', newline='', encoding='utf-8') as file:
                writer = csv.DictWriter(file, fieldnames=self.headers, delimiter=';')
                writer.writeheader()
                writer.writerows(filtered_data)

            self.filtered_data = filtered_data
            self.filtered_normalized = [self.normalized_data[i] for i in filtered_indices]

            self.display_data_in_table(self.search_table, filtered_data)
            self.update_special_tabs()
            self.update_main_smart_filters()
            self.apply_main_filters()

            self.log_status(f"Сохранено {len(filtered_data)} записей в: {output_file}")
            QMessageBox.information(self, "Успех",
                                    f"Сохранено {len(filtered_data)} записей в:\n{output_file}")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

    def update_special_tabs(self):
        if not hasattr(self, 'filtered_normalized'):
            return

        ceramic_indices = []
        resistor_indices = []
        electrolytic_indices = []
        tantalum_indices = []
        polymer_indices = []

        for idx, row in enumerate(self.filtered_normalized):
            category = row.get('GroupName', '').lower()

            # Для керамических
            if 'керамическ' in category:
                ceramic_indices.append(idx)
            # Для резисторов
            elif 'резистор' in category:
                resistor_indices.append(idx)
            # Для электролитических
            elif 'электролит' in category:
                electrolytic_indices.append(idx)
            # Для таллантовых
            elif 'тантал' in category:
                tantalum_indices.append(idx)
            # Для полимерных
            elif 'полимер' in category:
                polymer_indices.append(idx)

        # Обновляем данные для каждой вкладки
        self.update_ceramic_tab_data(ceramic_indices)
        self.update_resistor_tab_data(resistor_indices)
        self.update_capacitor_tab_data(electrolytic_indices, 'electrolytic')
        self.update_capacitor_tab_data(tantalum_indices, 'tantalum')
        self.update_capacitor_tab_data(polymer_indices, 'polymer')
        self.update_special_smart_filters('ceramic', 'керамическ')
        self.update_special_smart_filters('resistor', 'резистор')
        self.update_special_smart_filters('electrolytic', 'электролит')
        self.update_special_smart_filters('tantalum', 'тантал')
        self.update_special_smart_filters('polymer', 'полимер')

        custom_counts = {}
        for key, cfg in self.custom_tabs.items():
            indices = [i for i, row in enumerate(self.filtered_normalized)
                       if self._matches_category(row, cfg['patterns'])]
            self.display_data_in_table(cfg['table'],
                                       [self.filtered_data[i] for i in indices])
            self.update_special_smart_filters(key, cfg['patterns'])
            custom_counts[cfg['title']] = len(indices)

        summary = (f"Обновлены вкладки: Керамические={len(ceramic_indices)}, "
                   f"Резисторы={len(resistor_indices)}, "
                   f"Электролитические={len(electrolytic_indices)}, "
                   f"Танталовые={len(tantalum_indices)}, "
                   f"Полимерные={len(polymer_indices)}")
        if custom_counts:
            summary += " | Свои: " + ", ".join(
                f"{title}={count}" for title, count in custom_counts.items())
        self.log_status(summary)

    def update_ceramic_tab_data(self, indices):
        """Обновляет данные для вкладки керамических конденсаторов."""
        ceramic_data = [self.filtered_data[i] for i in indices]
        self.display_data_in_table(self.ceramic_table, ceramic_data)
    def update_resistor_tab_data(self, indices):
        """Обновляет данные для вкладки резисторов."""
        resistor_data = [self.filtered_data[i] for i in indices]
        self.display_data_in_table(self.resistor_table, resistor_data)
    def update_capacitor_tab_data(self, indices, capacitor_type):
        """Обновляет данные для вкладок различных конденсаторов."""
        if capacitor_type == 'electrolytic':
            table = self.electrolytic_table
        elif capacitor_type == 'tantalum':
            table = self.tantalum_table
        else:  # polymer
            table = self.polymer_table

        data = [self.filtered_data[i] for i in indices]
        self.display_data_in_table(table, data)
    def display_data_in_table(self, table, data):
        """Заполняет таблицу и добавляет интерактивную колонку избранного."""
        sorting_enabled = table.isSortingEnabled()
        vertical_position = table.verticalScrollBar().value()
        horizontal_position = table.horizontalScrollBar().value()

        table.setUpdatesEnabled(False)
        table.setSortingEnabled(False)

        # Кэшируем показанные строки для быстрого глобального поиска по вкладке.
        self._table_base[id(table)] = list(data)

        # Устанавливаем делегат подсветки результатов поиска.
        if not table.property("highlight_delegate_set"):
            table.setItemDelegate(HighlightDelegate(self))
            table.setProperty("highlight_delegate_set", True)
            table._highlight_query = ""

        # Колонка 0 — звезда, затем колонки current_headers и в конце статус наличия.
        display_headers = self.current_headers
        headers_with_favorite = ["⭐"] + display_headers + [self.STOCK_HEADER]
        stock_col = len(headers_with_favorite) - 1

        table.setColumnCount(len(headers_with_favorite))
        table.setHorizontalHeaderLabels(headers_with_favorite)

        if not data:
            table.setRowCount(0)
            table.setSortingEnabled(sorting_enabled)
            table.setUpdatesEnabled(True)
            return

        table.setRowCount(len(data))

        for row_idx, row_data in enumerate(data):
            key = self.component_key(row_data)
            is_favorite = key in self.favorites

            star_item = QTableWidgetItem("★" if is_favorite else "☆")
            star_item.setTextAlignment(Qt.AlignCenter)
            star_item.setData(Qt.UserRole, key)
            star_item.setToolTip(
                "Убрать из избранного" if is_favorite else "Добавить в избранное"
            )
            table.setItem(row_idx, 0, star_item)

            stock = self.stock_value(row_data)
            min_qty = self.min_stock_value(row_data)

            for col_idx, header in enumerate(display_headers, start=1):
                value = row_data.get(header, '')
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, key)

                if header == 'QtyStockSum':
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                    if stock <= 0:
                        item.setBackground(QColor("#ff8a8a"))
                    elif min_qty > 0 and stock < min_qty:
                        item.setBackground(QColor("#ffe08a"))

                table.setItem(row_idx, col_idx, item)

            # Столбец «Наличие» — наглядный статус с яркой подсветкой.
            status_item = QTableWidgetItem(self.stock_status(row_data))
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setData(Qt.UserRole, key)
            if stock <= 0:
                status_rank = 2
                status_item.setBackground(QColor("#ff5c5c"))
                status_item.setForeground(QColor("#ffffff"))
            elif min_qty > 0 and stock < min_qty:
                status_rank = 1
                status_item.setBackground(QColor("#ffd166"))
            else:
                status_rank = 0
                status_item.setBackground(QColor("#7fd4a2"))
            status_item.setData(Qt.UserRole + 1, status_rank)
            table.setItem(row_idx, stock_col, status_item)

            # Если остаток низкий/нулевой, подсвечиваем всю строку ярко.
            # Статус-ячейка и QtyStockSum получают ещё более явную подсветку выше.
            if stock <= 0:
                for col_idx in range(1, table.columnCount()):
                    item = table.item(row_idx, col_idx)
                    if item and col_idx != stock_col \
                            and table.horizontalHeaderItem(col_idx).text() != "QtyStockSum":
                        item.setBackground(QColor("#ffd0d0"))
            elif min_qty > 0 and stock < min_qty:
                for col_idx in range(1, table.columnCount()):
                    item = table.item(row_idx, col_idx)
                    if item and col_idx != stock_col \
                            and table.horizontalHeaderItem(col_idx).text() != "QtyStockSum":
                        item.setBackground(QColor("#fff0c2"))

        if not table.property("favorite_click_connected"):
            table.cellClicked.connect(self.on_table_cell_clicked)
            table.setProperty("favorite_click_connected", True)

        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 42)

        for i in range(1, min(6, table.columnCount())):
            table.resizeColumnToContents(i)
        table.resizeColumnToContents(stock_col)

        table.setSortingEnabled(sorting_enabled)
        table.setUpdatesEnabled(True)
        table.verticalScrollBar().setValue(
            min(vertical_position, table.verticalScrollBar().maximum())
        )
        table.horizontalScrollBar().setValue(
            min(horizontal_position, table.horizontalScrollBar().maximum())
        )

    def apply_ceramic_filters(self):
        if not hasattr(self, 'filtered_normalized'):
            return
        self.apply_special_smart_filters('ceramic', 'керамическ', self.ceramic_table)
    def apply_resistor_filters(self):
        if not hasattr(self, 'filtered_normalized'):
            return
        self.apply_special_smart_filters('resistor', 'резистор', self.resistor_table)
    def apply_electrolytic_filters(self):
        self.apply_capacitor_filters('electrolytic')

    def apply_tantalum_filters(self):
        self.apply_capacitor_filters('tantalum')

    def apply_polymer_filters(self):
        self.apply_capacitor_filters('polymer')

    def apply_capacitor_filters(self, capacitor_type):
        """Применяет фильтры для различных типов конденсаторов."""
        if not hasattr(self, 'filtered_normalized'):
            return

        smart_configs = {
            'electrolytic': ('электролит', self.electrolytic_table),
            'tantalum': ('тантал', self.tantalum_table),
            'polymer': ('полимер', self.polymer_table),
        }
        category_pattern, table = smart_configs[capacitor_type]
        self.apply_special_smart_filters(capacitor_type, category_pattern, table)
    def reset_filters(self):
        self.search_input.clear()
        self.global_search_input.clear()
        self.category_combo.setCurrentIndex(0)
        if hasattr(self, 'stock_filter_combo'):
            self.stock_filter_combo.setCurrentIndex(0)
        for combo in self.main_smart_filters.values():
            combo.setCurrentIndex(0)
        for filters in self.special_filter_sets.values():
            for _, _, combo in filters:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
        self.update_main_smart_filters()

        if hasattr(self, 'filtered_data'):
            self.apply_main_filters()

        if hasattr(self, 'filtered_normalized'):
            ceramic_indices = []
            resistor_indices = []
            electrolytic_indices = []
            tantalum_indices = []
            polymer_indices = []

            for idx, row in enumerate(self.filtered_normalized):
                category = row.get('GroupName', '').lower()
                if 'керамическ' in category:
                    ceramic_indices.append(idx)
                elif 'резистор' in category:
                    resistor_indices.append(idx)
                elif 'электролит' in category:
                    electrolytic_indices.append(idx)
                elif 'тантал' in category:
                    tantalum_indices.append(idx)
                elif 'полимер' in category:
                    polymer_indices.append(idx)

            if ceramic_indices:
                ceramic_data = [self.filtered_data[i] for i in ceramic_indices]
                self.display_data_in_table(self.ceramic_table, ceramic_data)

            if resistor_indices:
                resistor_data = [self.filtered_data[i] for i in resistor_indices]
                self.display_data_in_table(self.resistor_table, resistor_data)

            if electrolytic_indices:
                electrolytic_data = [self.filtered_data[i] for i in electrolytic_indices]
                self.display_data_in_table(self.electrolytic_table, electrolytic_data)

            if tantalum_indices:
                tantalum_data = [self.filtered_data[i] for i in tantalum_indices]
                self.display_data_in_table(self.tantalum_table, tantalum_data)

            if polymer_indices:
                polymer_data = [self.filtered_data[i] for i in polymer_indices]
                self.display_data_in_table(self.polymer_table, polymer_data)

            # Обновляем умные фильтры (включая наличие) для всех специализированных вкладок.
            self.update_special_smart_filters('ceramic', 'керамическ')
            self.update_special_smart_filters('resistor', 'резистор')
            self.update_special_smart_filters('electrolytic', 'электролит')
            self.update_special_smart_filters('tantalum', 'тантал')
            self.update_special_smart_filters('polymer', 'полимер')

            for key, cfg in self.custom_tabs.items():
                indices = [i for i, row in enumerate(self.filtered_normalized)
                           if self._matches_category(row, cfg['patterns'])]
                self.display_data_in_table(cfg['table'],
                                           [self.filtered_data[i] for i in indices])
                self.update_special_smart_filters(key, cfg['patterns'])


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = ComponentFilterApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

