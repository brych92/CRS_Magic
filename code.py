import json
import os
import re
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication
from qgis.core import Qgis, QgsApplication, QgsVectorLayer, QgsProject, QgsMapLayerType, QgsCoordinateTransform, QgsCsException, QgsCoordinateReferenceSystem,\
    QgsWkbTypes, QgsGeometry, QgsRectangle, QgsPointXY
from qgis.PyQt.QtCore import Qt, QTimer, QSettings
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from .find_crs import findCrs
from PyQt5.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel, QSizePolicy, \
    QTableWidget, QTableWidgetItem, QHBoxLayout, QHeaderView, QAbstractItemView, QListWidget, QLineEdit, \
    QPlainTextEdit, QDialogButtonBox, QWidget, QToolButton, QMenu
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFontMetrics, QCursor, QPixmap


ALL_CRS_SET_KEY = '__all__'
CRS_SETS_SETTINGS_KEY = 'CRS_Magic/crs_sets'
ACTIVE_CRS_SET_SETTINGS_KEY = 'CRS_Magic/active_crs_set'


def normalize_crs_code(crs_code):
    code = str(crs_code).strip().upper()
    if not code:
        return ''
    if code.isdigit() and len(code) >= 4:
        return f'EPSG:{code}'
    if re.match(r'^[A-Z][A-Z0-9_]*:\d+$', code):
        return code
    return ''


def parse_crs_codes(text):
    cleaned_lines = []
    for line in str(text or '').splitlines():
        cleaned_lines.append(line.split('#', 1)[0])
    cleaned_text = '\n'.join(cleaned_lines)
    candidates = re.findall(r'[A-Za-z][A-Za-z0-9_]*:\d+|\b\d{4,}\b', cleaned_text)

    result = []
    known_codes = set()
    for candidate in candidates:
        code = normalize_crs_code(candidate)
        if code and code not in known_codes:
            result.append(code)
            known_codes.add(code)
    return result


class CustomMessageBox(QDialog):
    def __init__(self, title, message, parent=None):
        super().__init__(parent)

        self.setWindowTitle(title)

        # Set the window icon
        self.plugin_dir = os.path.dirname(__file__)
        icon = QIcon(os.path.join(self.plugin_dir,"icon.png"))        
        self.setWindowIcon(icon)

        # Create a QLabel widget with HTML formatting
        text_edit = QTextEdit()
        
        html_text=message.replace("\n", "<br>")
        
        text_edit.setHtml(html_text)
        max_line_width = 0
        font_metrics=QFontMetrics(text_edit.font())
        for line in html_text.split('<br>'):
            line_width = font_metrics.width(line)
            max_line_width = max(max_line_width, line_width)
        self.setMinimumWidth(int(max_line_width) + 20)
        
        line_height = font_metrics.height()
        height=min(640,int(html_text.count('<br>')*line_height*1.5))
        self.setMinimumHeight(height)
        
        text_edit.setReadOnly(True)
        
        # Create a QPushButton to close the dialog
        ok_button = QPushButton('OK')
        ok_button.clicked.connect(self.accept)

        # Set up the layout
        layout = QVBoxLayout()
        layout.addWidget(text_edit)
        layout.addWidget(ok_button)

        self.setLayout(layout)


class DistanceTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        left_value = self.data(Qt.UserRole)
        right_value = other.data(Qt.UserRole)
        if left_value is not None and right_value is not None:
            return left_value < right_value
        return super().__lt__(other)


class CRSResultsDialog(QDialog):
    def __init__(self, layers, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.task = None
        self.layers_by_id = {layer.id(): layer for layer in layers}
        self.manual_layer_ids = set()
        self.manual_result_text = {}
        self.pending_results = []

        self.setWindowTitle('CRS Magic - результати підбору')
        self.plugin_dir = os.path.dirname(__file__)
        icon = QIcon(os.path.join(self.plugin_dir, "icon.png"))
        self.setWindowIcon(icon)
        self.resize(820, 520)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Шар', 'СК', 'Відстань, м'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(True)
        self.table.sortItems(2, Qt.AscendingOrder)
        self.table.itemDoubleClicked.connect(self.apply_selected_crs)

        self.status_label = QLabel('Очікуємо результати...')

        self.cancel_button = QPushButton('Скасувати пошук')
        self.cancel_button.clicked.connect(self.cancel_search)
        self.close_button = QPushButton('Закрити')
        self.close_button.clicked.connect(self.close)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.status_label)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.close_button)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)

        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(250)
        self.flush_timer.timeout.connect(self.flush_pending_results)

    def set_task(self, task):
        self.task = task

    def crs_label(self, crs_code, crs_name):
        if crs_name:
            return f'{crs_code} - {crs_name}'
        return crs_code

    def short_crs_label(self, crs_code, crs_name):
        if crs_name and len(crs_name) > 100:
            return f'{crs_code} - {crs_name[:100]}...'
        return self.crs_label(crs_code, crs_name)

    def add_result(self, layer_id, layer_name, crs_code, crs_name, distance, crs):
        self.pending_results.append((layer_id, layer_name, crs_code, crs_name, distance, crs))
        if not self.flush_timer.isActive():
            self.flush_timer.start()

    def flush_pending_results(self):
        if not self.pending_results:
            return

        results = self.pending_results
        self.pending_results = []
        self.table.setSortingEnabled(False)
        for layer_id, layer_name, crs_code, crs_name, distance, crs in results:
            row = self.table.rowCount()
            self.table.insertRow(row)

            layer_item = QTableWidgetItem(layer_name)
            crs_item = QTableWidgetItem(self.short_crs_label(crs_code, crs_name))
            crs_item.setToolTip(self.crs_label(crs_code, crs_name))
            distance_item = DistanceTableWidgetItem(f'{distance:,.0f}'.replace(',', ' '))
            distance_item.setData(Qt.UserRole, distance)

            for item in (layer_item, crs_item, distance_item):
                item.setData(Qt.UserRole + 1, layer_id)
                item.setData(Qt.UserRole + 2, crs)
                item.setData(Qt.UserRole + 3, crs_code)
                item.setData(Qt.UserRole + 4, distance)
                item.setData(Qt.UserRole + 5, crs_name)

            self.table.setItem(row, 0, layer_item)
            self.table.setItem(row, 1, crs_item)
            self.table.setItem(row, 2, distance_item)

        self.table.setSortingEnabled(True)
        self.table.sortItems(2, Qt.AscendingOrder)

    def apply_selected_crs(self, *args):
        if args and args[0]:
            row = args[0].row()
        else:
            row = self.table.currentRow()
        if row < 0:
            return

        layer_item = self.table.item(row, 0)
        if not layer_item:
            return

        layer_id = layer_item.data(Qt.UserRole + 1)
        crs = layer_item.data(Qt.UserRole + 2)
        crs_code = layer_item.data(Qt.UserRole + 3)
        distance = layer_item.data(Qt.UserRole + 4)
        crs_name = layer_item.data(Qt.UserRole + 5)
        layer = self.layers_by_id.get(layer_id)
        if not layer or not crs:
            return

        layer.setCrs(crs)
        self.manual_layer_ids.add(layer_id)
        self.manual_result_text[layer_id] = f"{self.crs_label(crs_code, crs_name)} - {f'{distance:,.0f}'.replace(',', ' ')} метрів від точки кліку"
        self.iface.mapCanvas().refreshAllLayers()
        self.iface.messageBar().pushMessage(
            f"[CRS Magic] Для шару '{layer.name()}' встановлено {self.crs_label(crs_code, crs_name)}",
            Qgis.MessageLevel.Success,
            3
        )

    def update_stats(self, total, processed, success, failed, matched):
        rows_qty = self.table.rowCount() + len(self.pending_results)
        self.status_label.setText(
            f'Усього: {total} | Перевірено: {processed} | Успішно: {success} | '
            f'Помилок/пропущено: {failed} | До 200 км: {matched} | У таблиці: {rows_qty}'
        )

    def has_manual_selection(self, layer_id):
        return layer_id in self.manual_layer_ids

    def manual_selection_text(self, layer_id):
        return self.manual_result_text.get(layer_id, '')

    def mark_finished(self):
        self.flush_pending_results()
        self.cancel_button.setEnabled(False)
        self.status_label.setText(self.status_label.text() + ' | Готово')

    def mark_failed(self, failure):
        self.flush_pending_results()
        self.cancel_button.setEnabled(False)
        self.status_label.setText(f'Помилка: {failure}')

    def cancel_search(self):
        if self.task:
            self.task.cancel()
            self.status_label.setText(self.status_label.text() + ' | Скасування...')


class CRSSetSettingsDialog(QDialog):
    def __init__(self, crs_sets, parent=None):
        super().__init__(parent)
        self.crs_sets = {}
        for name, codes in crs_sets.items():
            normalized_codes = parse_crs_codes('\n'.join(codes))
            if str(name).strip() and normalized_codes:
                self.crs_sets[str(name).strip()] = normalized_codes

        self.current_set_name = None
        self.loading = False

        self.setWindowTitle('CRS Magic - набори СК')
        self.resize(720, 420)

        self.sets_list = QListWidget()
        self.sets_list.setMinimumWidth(190)
        self.sets_list.currentItemChanged.connect(self.change_set)

        self.add_button = QPushButton('Додати')
        self.add_button.clicked.connect(self.add_set)
        self.delete_button = QPushButton('Видалити')
        self.delete_button.clicked.connect(self.delete_set)

        set_buttons_layout = QHBoxLayout()
        set_buttons_layout.addWidget(self.add_button)
        set_buttons_layout.addWidget(self.delete_button)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel('Набори'))
        left_layout.addWidget(self.sets_list)
        left_layout.addLayout(set_buttons_layout)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        self.name_edit = QLineEdit()
        self.codes_edit = QPlainTextEdit()
        self.codes_edit.setPlaceholderText('EPSG:5562\nEPSG:5563\n4326')
        self.codes_edit.textChanged.connect(self.update_count_label)
        self.count_label = QLabel('Кодів у наборі: 0')

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel('Назва набору'))
        right_layout.addWidget(self.name_edit)
        right_layout.addWidget(QLabel('Коди СК'))
        right_layout.addWidget(self.codes_edit)
        right_layout.addWidget(self.count_label)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        content_layout = QHBoxLayout()
        content_layout.addWidget(left_widget)
        content_layout.addWidget(right_widget, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(content_layout)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        self.load_sets_list()
        if self.sets_list.count():
            self.sets_list.setCurrentRow(0)
        else:
            self.add_set()

    def unique_set_name(self, base_name):
        name = base_name
        counter = 2
        while name in self.crs_sets:
            name = f'{base_name} {counter}'
            counter = counter + 1
        return name

    def load_sets_list(self):
        self.loading = True
        self.sets_list.clear()
        for name in sorted(self.crs_sets.keys()):
            self.sets_list.addItem(name)
        self.loading = False

    def load_set(self, set_name):
        self.loading = True
        self.current_set_name = set_name
        self.name_edit.setText(set_name)
        self.codes_edit.setPlainText('\n'.join(self.crs_sets.get(set_name, [])))
        self.update_count_label()
        self.loading = False

    def change_set(self, current, previous):
        if self.loading:
            return
        if previous and not self.save_current_set():
            self.loading = True
            self.sets_list.setCurrentItem(previous)
            self.loading = False
            return
        if current:
            self.load_set(current.text())
        else:
            self.current_set_name = None
            self.name_edit.clear()
            self.codes_edit.clear()

    def add_set(self):
        if self.current_set_name and not self.save_current_set():
            return

        name = self.unique_set_name('Новий набір')
        self.crs_sets[name] = []
        self.sets_list.addItem(name)
        self.sets_list.setCurrentRow(self.sets_list.count() - 1)
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def delete_set(self):
        current = self.sets_list.currentItem()
        if not current:
            return

        answer = QMessageBox.question(
            self,
            'Видалити набір?',
            f"Видалити набір '{current.text()}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        row = self.sets_list.row(current)
        self.crs_sets.pop(current.text(), None)
        self.loading = True
        self.sets_list.takeItem(row)
        self.loading = False

        if self.sets_list.count():
            self.sets_list.setCurrentRow(min(row, self.sets_list.count() - 1))
        else:
            self.current_set_name = None
            self.name_edit.clear()
            self.codes_edit.clear()
            self.update_count_label()

    def save_current_set(self, show_warning=True):
        if not self.current_set_name:
            return True

        new_name = self.name_edit.text().strip()
        codes = parse_crs_codes(self.codes_edit.toPlainText())

        if not new_name:
            if show_warning:
                QMessageBox.warning(self, 'Набір СК', 'Вкажіть назву набору.')
            return False

        if not codes:
            if show_warning:
                QMessageBox.warning(self, 'Набір СК', 'Додайте хоча б один код СК у набір.')
            return False

        if new_name != self.current_set_name and new_name in self.crs_sets:
            if show_warning:
                QMessageBox.warning(self, 'Набір СК', 'Набір з такою назвою вже існує.')
            return False

        current_item = self.sets_list.currentItem()
        if new_name != self.current_set_name:
            self.crs_sets.pop(self.current_set_name, None)
            self.current_set_name = new_name
            if current_item:
                current_item.setText(new_name)

        self.crs_sets[self.current_set_name] = codes
        self.update_count_label()
        return True

    def update_count_label(self):
        self.count_label.setText(f'Кодів у наборі: {len(parse_crs_codes(self.codes_edit.toPlainText()))}')

    def result_sets(self):
        return {
            name: codes
            for name, codes in self.crs_sets.items()
            if name.strip() and codes
        }

    def accept(self):
        if self.current_set_name and not self.save_current_set(True):
            return
        super().accept()


class CRS_Magic:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.folder_path=os.path.expanduser('~')
        self.activated=False
        
        self.pointTool = QgsMapToolEmitPoint(self.iface.mapCanvas())
        cursor_pixmap=QPixmap(os.path.join(self.plugin_dir,"cursor.png")).scaledToHeight(32,Qt.SmoothTransformation)
        cursor=QCursor(cursor_pixmap)
        self.pointTool.setCursor(cursor)
        self.pointTool.canvasClicked.connect(self.get_CRS_dict)
        self.pointTool.deactivated.connect(self.tool_chaged)
        
        self.layers=[]
        self.selected_layers=[]
        self.results_dialog=None
        self.settings = QSettings()
        self.crs_sets = self.load_crs_sets()
        self.active_crs_set = self.load_active_crs_set()
        self.crs_menu = None
        self.crs_menu_action = None
        self.menu_button = None
        
    def initGui(self):
        icon = QIcon(os.path.join(self.plugin_dir,"icon.png"))
        tooltip=f"・*.ﾟ☆ <b>CRS Magic</b> ☆ﾟ.*・\nПідібрати СК для вибраних шарів"
        
        action = QAction(icon, tooltip, self.iface.mainWindow())
        action.triggered.connect(self.Run)
        action.setEnabled(True)
        action.setCheckable(True)
        self.iface.addToolBarIcon(action)
        self.actions.append(action)
        self.action_reference=action
        self.add_crs_menu_button()
        
    def unload(self):
        for action in self.actions:
            self.iface.removeToolBarIcon(action)
        if self.menu_button:
            self.menu_button.deleteLater()

    def load_crs_sets(self):
        value = self.settings.value(CRS_SETS_SETTINGS_KEY, '{}')
        try:
            raw_sets = json.loads(str(value))
        except Exception:
            raw_sets = {}

        if not isinstance(raw_sets, dict):
            return {}

        crs_sets = {}
        for name, codes in raw_sets.items():
            if isinstance(codes, list):
                parsed_codes = parse_crs_codes('\n'.join([str(code) for code in codes]))
            else:
                parsed_codes = parse_crs_codes(codes)

            if str(name).strip() and parsed_codes:
                crs_sets[str(name).strip()] = parsed_codes

        return crs_sets

    def save_crs_sets(self):
        self.settings.setValue(CRS_SETS_SETTINGS_KEY, json.dumps(self.crs_sets, ensure_ascii=False))

    def load_active_crs_set(self):
        active_set = self.settings.value(ACTIVE_CRS_SET_SETTINGS_KEY, ALL_CRS_SET_KEY)
        active_set = str(active_set or ALL_CRS_SET_KEY)
        if active_set != ALL_CRS_SET_KEY and active_set not in self.crs_sets:
            return ALL_CRS_SET_KEY
        return active_set

    def save_active_crs_set(self):
        self.settings.setValue(ACTIVE_CRS_SET_SETTINGS_KEY, self.active_crs_set)

    def active_crs_set_label(self):
        if self.active_crs_set == ALL_CRS_SET_KEY:
            return 'Всі СК'
        codes = self.crs_sets.get(self.active_crs_set, [])
        return f'{self.active_crs_set} ({len(codes)} СК)'

    def active_crs_codes(self):
        if self.active_crs_set == ALL_CRS_SET_KEY:
            return None

        codes = self.crs_sets.get(self.active_crs_set)
        if not codes:
            self.active_crs_set = ALL_CRS_SET_KEY
            self.save_active_crs_set()
            self.rebuild_crs_menu()
            return None

        return codes

    def add_crs_menu_button(self):
        self.crs_menu = QMenu(self.iface.mainWindow())
        self.rebuild_crs_menu()

        if hasattr(self.iface, 'addToolBarWidget'):
            self.menu_button = QToolButton(self.iface.mainWindow())
            self.menu_button.setText('▾')
            self.menu_button.setToolTip(f'Набір СК: {self.active_crs_set_label()}')
            self.menu_button.setPopupMode(QToolButton.InstantPopup)
            self.menu_button.setAutoRaise(True)
            self.menu_button.setFixedWidth(22)
            self.menu_button.setMenu(self.crs_menu)
            self.crs_menu_action = self.iface.addToolBarWidget(self.menu_button)
            if self.crs_menu_action:
                self.actions.append(self.crs_menu_action)
        else:
            self.crs_menu_action = QAction('▾', self.iface.mainWindow())
            self.crs_menu_action.setToolTip(f'Набір СК: {self.active_crs_set_label()}')
            self.crs_menu_action.setMenu(self.crs_menu)
            self.iface.addToolBarIcon(self.crs_menu_action)
            self.actions.append(self.crs_menu_action)

    def rebuild_crs_menu(self):
        if not self.crs_menu:
            return

        self.crs_menu.clear()

        all_action = self.crs_menu.addAction('Всі СК')
        all_action.setCheckable(True)
        all_action.setChecked(self.active_crs_set == ALL_CRS_SET_KEY)
        all_action.triggered.connect(lambda checked=False: self.set_active_crs_set(ALL_CRS_SET_KEY))

        if self.crs_sets:
            self.crs_menu.addSeparator()
            for set_name in sorted(self.crs_sets.keys()):
                codes = self.crs_sets.get(set_name, [])
                action = self.crs_menu.addAction(f'{set_name} ({len(codes)} СК)')
                action.setCheckable(True)
                action.setChecked(self.active_crs_set == set_name)
                action.triggered.connect(lambda checked=False, name=set_name: self.set_active_crs_set(name))

        self.crs_menu.addSeparator()
        settings_action = self.crs_menu.addAction('Налаштування...')
        settings_action.triggered.connect(self.open_crs_sets_settings)

        if self.menu_button:
            self.menu_button.setToolTip(f'Набір СК: {self.active_crs_set_label()}')
        if self.crs_menu_action:
            self.crs_menu_action.setToolTip(f'Набір СК: {self.active_crs_set_label()}')

    def set_active_crs_set(self, set_name):
        if set_name != ALL_CRS_SET_KEY and set_name not in self.crs_sets:
            set_name = ALL_CRS_SET_KEY

        self.active_crs_set = set_name
        self.save_active_crs_set()
        self.rebuild_crs_menu()

    def open_crs_sets_settings(self):
        dialog = CRSSetSettingsDialog(self.crs_sets, self.iface.mainWindow())
        icon = QIcon(os.path.join(self.plugin_dir, "icon.png"))
        dialog.setWindowIcon(icon)

        if not dialog.exec_():
            return

        self.crs_sets = dialog.result_sets()
        self.save_crs_sets()

        if self.active_crs_set != ALL_CRS_SET_KEY and self.active_crs_set not in self.crs_sets:
            self.active_crs_set = ALL_CRS_SET_KEY
            self.save_active_crs_set()

        self.rebuild_crs_menu()
    
    def clearMBar(self):        
        mbar=self.iface.messageBar()
        for message in mbar.items():
            if message.text().startswith("[CRS Magic]"):
                message.dismiss()
    
    
    def get_CRS_dict(self,click_point):
        def status_changed(status):
            if status==3:
                fk_b_s=r'<span style="color:black">'
                fk_r_s='<span style="color:red">'
                fk_e=r'</span>'
                self.clearMBar()
                if self.results_dialog:
                    self.results_dialog.mark_finished()
                #print("Завершено!")
                #print('Звіт:')
                #print(task.message)
                result_message=f'[CRS Magic] Перевірте коректність підбору СК по фотоплану.\r\n\r\n'
                number=1
                
                for layer in self.selected_layers:
                    result_message=result_message+f'\r\n{number}. '
                    number=number+1
                    layer_id=layer.id()
                    if layer_id in task.total_result and task.total_result[layer_id]['Checked']:
                        if 'PossibleCRS' in task.total_result[layer_id]:
                            if self.results_dialog and self.results_dialog.has_manual_selection(layer_id):
                                crs=self.results_dialog.manual_selection_text(layer_id)
                                result_message=result_message+f"{fk_b_s}Шар '{layer.name()}':\r\n СК змінено вручну на {crs}.{fk_e}\r\n"
                            else:
                                crs=task.total_result[layer_id]['PossibleCRS']
                                other_crs=task.total_result[layer_id]['OtherPossibleCRS']
                                found_crs=task.total_result[layer_id]['FoundCRS']
                                layer.setCrs(found_crs)
                                result_message=result_message+f"{fk_b_s}Шар '{layer.name()}':\r\n СК змінено на {crs}.  {other_crs}{fk_e}\r\n"
                        else:
                            result_message=result_message+f"{fk_r_s}Шар '{layer.name()}': помилка підбору СК - {task.total_result[layer_id]['Error']}{fk_e}\r\n"
                            
                    elif layer.type() != QgsMapLayerType.VectorLayer:
                        result_message=result_message+f"{fk_r_s}Шар '{layer.name()}': не було перевірено, так як він не векторний{fk_e}\r\n"
                        
                    elif layer.featureCount() == 0:
                        result_message=result_message+f"{fk_r_s}Шар '{layer.name()}': не було перевірено, так як в ньому відсутні об'єкти{fk_e}\r\n"
                                
                
                canvas.refreshAllLayers()
                self.clearMBar()
                message_bar.pushMessage("[CRS Magic] Підбір СК завершено. Результати доступні у таблиці.", Qgis.MessageLevel.Success, 5)
                print(result_message)
                # if len(self.selected_layers)>0:
                    # custom_message_box = CustomMessageBox('Готово!', result_message)
                    # custom_message_box.exec_()
                # else:
                    # message_bar.pushMessage(result_message, Qgis.MessageLevel.Success,0)
                    # print(result_message)
                self.activated=False
                self.action_reference.setChecked(False)
                self.iface.mapCanvas().unsetMapTool(self.iface.mapCanvas().mapTool())
                # print(task.message)
                return
            if status==4:
                self.clearMBar()
                # print(task.message)
                # print(task.last_action)
                if task.isCanceled():
                    if self.results_dialog:
                        self.results_dialog.mark_failed('Підбір СК відмінено користувачем')
                    print("Відмінено користувачем!")
                else:
                    if task.getFailure():                            
                        failure=task.getFailure()
                    else:
                        failure="Помилка, спробуйте ще раз!"
                    if self.results_dialog:
                        self.results_dialog.mark_failed(failure)
                    print(f"[CRS Magic] {failure}")
                    print(task.message)
                    message_bar.pushMessage(f"[CRS Magic] {failure}", Qgis.MessageLevel.Warning, 5)                        
                
        self.clearMBar()
        message_bar = self.iface.messageBar()
        #print(f'Точка кліку до входження в задачу: {click_point.toString(4)}')
        project = QgsProject.instance()
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()        
        work_crs = QgsCoordinateReferenceSystem('EPSG:3857')
        
        transformation = QgsCoordinateTransform(canvas_crs, work_crs, project)
        transformation.disableFallbackOperationHandler(True)
        tr_click_point=transformation.transform(click_point)
        
        crs_codes = self.active_crs_codes()
        crs_set_name = self.active_crs_set_label()

        message_bar.pushMessage(f'[CRS Magic] Зачекайте будь ласка, йде підбір СК... Набір: {crs_set_name}', Qgis.MessageLevel.Success,0)
        
        if self.results_dialog:
            self.results_dialog.close()
        self.results_dialog = CRSResultsDialog(self.layers, self.iface, self.iface.mainWindow())
        self.results_dialog.show()

        task = findCrs("Пошук можливих систем координат", self.layers, tr_click_point, work_crs, project, crs_codes, crs_set_name)
        self.results_dialog.set_task(task)
        task.crsChecked.connect(self.results_dialog.add_result)
        task.statsChanged.connect(self.results_dialog.update_stats)
        
        task.statusChanged.connect(status_changed)
        task.setDependentLayers(self.layers)
        QgsApplication.taskManager().addTask(task)
        
        print('Запускаю процес підбору...')
    
    
    def Run(self):
        # simple_search=False
        
        # if self.isControlOrShift()=='shift':#якщо зажато шифт - виконуємо підбір по центру екстенту
            # simple_search=True            
        
        message_bar = self.iface.messageBar()
        self.clearMBar()
        
        if self.activated:#Якщо увімкнено то вимикаємо і відключаємо інструмент
            self.activated=False
            self.action_reference.setChecked(False)
            self.iface.mapCanvas().unsetMapTool(self.pointTool)            
            return
        
        layers=[]
        
        selected_layers = self.iface.layerTreeView().selectedLayersRecursive()
        
        if len(selected_layers)<1:
            message_bar.pushMessage("[CRS Magic] Спочатку виділіть векторні шари в панелі шарів!", Qgis.MessageLevel.Warning, 5)
            self.action_reference.setChecked(False)
            return
        
        for layer in selected_layers:
            if layer.type() == QgsMapLayerType.VectorLayer and layer.featureCount() != 0:
                layers.append(layer)
        
        if len(layers)<1:
            message_bar.pushMessage("[CRS Magic] Жоден з вибраних шарів не векторний або в не містить об'єктів для аналізу. Будь ласка спочатку виберіть векторні шари", Qgis.MessageLevel.Warning, 5)
            self.action_reference.setChecked(False)
            return
        
        # if self.isControlOrShift()=='ctrl':
            # self.visualizeExtent(layers)
            # self.action_reference.setChecked(False)
            # return
        
        layers_warning=''
        if not all(element in layers for element in selected_layers):
            layers_warning=".Зверніть увагу: деякі з вибраних шарів не векторні або в них відсутні об'єкти!" 
        
        self.activated=True
        self.action_reference.setChecked(True)
        crs_set_name = self.active_crs_set_label()
        
        if len(layers)==1:
            message_bar.pushMessage(f"[CRS Magic] Клікніть на карті приблизне можливе місцезнаходження об'єктів шару '{layers[0].name()}'{layers_warning}. Набір СК: {crs_set_name}", Qgis.MessageLevel.Info, 0)
        else:
            message_bar.pushMessage(f"[CRS Magic] Клікніть на карті приблизне можливе місцезнаходження об'єктів вибраних шарів({len(selected_layers)}шт.) {layers_warning}. Набір СК: {crs_set_name}", Qgis.MessageLevel.Info, 0)
        
        self.layers=layers
        self.selected_layers=selected_layers
        
        self.iface.mapCanvas().setMapTool(self.pointTool)
        

    def tool_chaged(self):
        self.activated=False
        self.action_reference.setChecked(False)
        self.clearMBar()
    
    def isControlOrShift(self):
        ctrl_pressed = Qt.ControlModifier & QApplication.keyboardModifiers()
        shift_pressed = Qt.ShiftModifier & QApplication.keyboardModifiers()
            
        if ctrl_pressed and shift_pressed:
            print('ctrl+shift')
            return 'ctrl+shift'
        elif ctrl_pressed:
            print('ctrl')
            return 'ctrl'
        elif shift_pressed:
            print('shift')
            return 'shift'
        else:
            return False
    
    def visualizeExtent(self, layers):
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()

        # Create a rubber band for the total extent
        total_rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        total_extent = QgsRectangle()

        for current_layer in layers:
            layer_extent = current_layer.extent()

            # Transform layer extent to canvas CRS
            transform = QgsCoordinateTransform(current_layer.crs(), canvas_crs, QgsProject.instance())
            layer_extent = transform.transformBoundingBox(layer_extent)
            # Combine the layer geometry with the total extent
            total_extent.combineExtentWith(layer_extent)

        # Set the geometry of the total rubber band
        total_rubber_band.setToGeometry(QgsGeometry.fromRect(total_extent).convertToType(QgsWkbTypes.LineGeometry), None)

        # Set the color and width of the total rubber band
        total_rubber_band.setColor(Qt.red)
        total_rubber_band.setWidth(1)        
        # Reset the total rubber band after a timeout
        def aaa():
            canvas = self.iface.mapCanvas()

            # Get all rubber bands on the canvas
            rubber_bands = [item for item in canvas.scene().items() if isinstance(item, QgsRubberBand)]

            # Remove each rubber band
            for band in rubber_bands:
                band.reset()

            # Refresh the canvas
            canvas.refresh()
        timer = QTimer()
        timer.timeout.connect(aaa)
        timer.start(10)  # Adjust the timeout as needed

        # Set the extent and zoom the canvas
        canvas.setExtent(total_extent)
        canvas.zoomScale(canvas.scale() * 1.5)
        canvas.refresh()
    
   
