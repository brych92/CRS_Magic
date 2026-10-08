import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsMapLayerType,
    QgsProject,
)
from qgis.PyQt.QtCore import QItemSelectionModel, Qt, QTimer
from qgis.PyQt.QtGui import QFontMetrics, QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QHeaderView,
    QVBoxLayout,
)


def qgis_icon(names, fallback_standard_icon):
    for name in names:
        candidates = [name]
        if name.startswith('/'):
            candidates.append(name[1:])
        else:
            candidates.append(f'/{name}')

        for candidate in candidates:
            icon = QgsApplication.getThemeIcon(candidate)
            if not icon.isNull():
                return icon

    return QApplication.style().standardIcon(fallback_standard_icon)


class CustomMessageBox(QDialog):
    def __init__(self, title, message, parent=None):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.plugin_dir = os.path.dirname(__file__)
        self.setWindowIcon(QIcon(os.path.join(self.plugin_dir, "icon.png")))

        text_edit = QTextEdit()
        html_text = message.replace("\n", "<br>")
        text_edit.setHtml(html_text)
        max_line_width = 0
        font_metrics = QFontMetrics(text_edit.font())
        for line in html_text.split('<br>'):
            max_line_width = max(max_line_width, font_metrics.width(line))
        self.setMinimumWidth(int(max_line_width) + 20)

        line_height = font_metrics.height()
        self.setMinimumHeight(min(640, int(html_text.count('<br>') * line_height * 1.5)))
        text_edit.setReadOnly(True)

        ok_button = QPushButton('OK')
        ok_button.clicked.connect(self.accept)

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
        self.results_by_layer = {layer.id(): {} for layer in layers}
        self.units_by_id = {
            layer.id(): {
                'id': layer.id(),
                'name': layer.name(),
                'layer_ids': [layer.id()],
                'grouped': False,
            }
            for layer in layers
        }
        self.layer_to_unit_id = {layer.id(): layer.id() for layer in layers}
        self.syncing_tree_selection = False
        self.manual_layer_ids = set()
        self.manual_result_text = {}
        self.pending_results = []
        self.undo_stack = []
        self.redo_stack = []
        self.is_closing = False
        self.last_stats = None
        self.phase_status = ''
        self.phase_progress = 0
        self.task_progress = 0
        self.status_suffix = ''
        self.search_finished = False

        self.setWindowTitle('CRS Magic finder — результати підбору')
        self.plugin_dir = os.path.dirname(__file__)
        self.setWindowIcon(QIcon(os.path.join(self.plugin_dir, "icon.png")))

        self.layer_combo = QComboBox()
        self.layer_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.layer_combo.view().setTextElideMode(Qt.ElideRight)
        for layer in layers:
            self.add_layer_combo_item(layer.name(), layer.id(), [layer.id()])
        self.layer_combo.currentIndexChanged.connect(self.on_search_unit_changed)
        self.layer_combo.currentIndexChanged.connect(
            self.update_layer_combo_tooltip
        )
        self.update_layer_combo_tooltip()

        self.zoom_button = QPushButton()
        self.zoom_button.setToolTip('Наблизити до шару або групи шарів')
        self.zoom_button.setIcon(qgis_icon(
            ['mActionZoomToLayer.svg', 'mActionZoomFullExtent.svg'],
            QStyle.SP_DesktopIcon,
        ))
        self.zoom_button.clicked.connect(self.zoom_to_current_unit)

        self.undo_button = QPushButton()
        self.undo_button.setToolTip('Скасувати останню операцію')
        self.undo_button.setIcon(qgis_icon(
            ['mActionUndo.svg', 'mActionEditUndo.svg'],
            QStyle.SP_ArrowBack,
        ))
        self.undo_button.clicked.connect(self.undo_last_operation)

        self.redo_button = QPushButton()
        self.redo_button.setToolTip('Повторити останню операцію')
        self.redo_button.setIcon(qgis_icon(
            ['mActionRedo.svg', 'mActionEditRedo.svg'],
            QStyle.SP_ArrowForward,
        ))
        self.redo_button.clicked.connect(self.redo_last_operation)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel('Шар або група:'))
        top_layout.addWidget(self.layer_combo, 1)
        top_layout.addWidget(self.zoom_button)
        top_layout.addWidget(self.undo_button)
        top_layout.addWidget(self.redo_button)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['СК', 'Відстань, м', 'Примітка'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeaderItem(2).setToolTip(
            'Позначає результати, отримані запасним або '
            'приблизним способом перетворення.'
        )
        self.table.horizontalHeader().sectionResized.connect(self.elide_crs_labels)
        self.table.itemDoubleClicked.connect(self.apply_selected_crs)
        self.table.itemSelectionChanged.connect(self.update_button_states)

        self.status_label = QLabel('Очікування результатів…')
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status_label.setContentsMargins(5, 0, 5, 0)
        self.status_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.status_label.setStyleSheet('background: transparent;')

        self.status_progress = QProgressBar()
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        self.status_progress.setTextVisible(False)
        self.status_progress.setFixedHeight(self.status_label.sizeHint().height() + 4)
        self.status_progress.setStyleSheet(
            'QProgressBar {'
            '  border: 1px solid palette(mid);'
            '  border-radius: 2px;'
            '  background: palette(base);'
            '}'
            'QProgressBar::chunk {'
            '  background: rgba(60, 150, 220, 80);'
            '}'
        )

        status_layout = QGridLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        status_layout.addWidget(self.status_progress, 0, 0)
        status_layout.addWidget(self.status_label, 0, 0)

        self.cancel_button = QPushButton('Скасувати пошук')
        self.cancel_button.clicked.connect(self.cancel_search)
        self.close_button = QPushButton('Закрити')
        self.close_button.clicked.connect(self.close)
        self.apply_button = QPushButton('Застосувати вибрану СК до виділених шарів')
        self.apply_button.setIcon(qgis_icon(
            ['mActionApply.svg', 'mIconSuccess.svg', 'mActionSelectAll.svg'],
            QStyle.SP_DialogApplyButton,
        ))
        self.apply_button.clicked.connect(self.apply_selected_crs)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.apply_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.close_button)

        layout = QVBoxLayout()
        layout.addLayout(top_layout)
        layout.addWidget(self.table)
        layout.addLayout(buttons_layout)

        self.status_separator = QFrame()
        self.status_separator.setFrameShape(QFrame.HLine)
        self.status_separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(self.status_separator)
        layout.addLayout(status_layout)
        self.setLayout(layout)
        self.configure_dialog_width()

        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(250)
        self.flush_timer.timeout.connect(self.flush_pending_results)

        try:
            self.iface.currentLayerChanged.connect(self.on_current_layer_changed)
        except Exception:
            pass

        self.on_current_layer_changed(self.iface.activeLayer())
        self.update_button_states()

    def text_width(self, text):
        metrics = QFontMetrics(self.status_label.font())
        if hasattr(metrics, 'horizontalAdvance'):
            return metrics.horizontalAdvance(text)
        return metrics.width(text)

    def configure_dialog_width(self):
        status_sample = (
            'СК: 9999 | Перевірено: 9999 | Успішних: 9999 | '
            'Помилок: 9999 | Пропущено: 9999 | Збігів до 200 км: 9999 | '
            'У поточній таблиці: 9999 | Скасування…'
        )
        margins = self.layout().contentsMargins()
        desired_width = (
            self.text_width(status_sample)
            + margins.left()
            + margins.right()
        )
        screen = QApplication.primaryScreen()
        if screen is not None:
            desired_width = min(
                desired_width,
                screen.availableGeometry().width(),
            )

        self.setMinimumWidth(max(1, desired_width))
        self.resize(max(1, desired_width), 520)

    def set_task(self, task):
        self.task = task
        task.progressChanged.connect(self.set_progress)
        task.phaseChanged.connect(self.set_phase_status)
        task.phaseProgressChanged.connect(self.set_phase_progress)

    def set_phase_status(self, status):
        self.phase_status = str(status or '')
        if self.phase_status:
            self.phase_progress = 0
            self.render_phase_status()
            return

        self.status_progress.setValue(self.task_progress)
        if self.last_stats is not None:
            self.render_stats()

    def set_phase_progress(self, progress):
        self.phase_progress = max(
            0,
            min(100, int(round(float(progress)))),
        )
        if self.phase_status:
            self.render_phase_status()

    def render_phase_status(self):
        self.status_progress.setValue(self.phase_progress)
        self.status_label.setText(
            f'{self.phase_status} {self.phase_progress}%.'
        )

    def set_progress(self, progress):
        self.task_progress = max(
            0,
            min(100, int(round(float(progress)))),
        )
        if not self.phase_status:
            self.status_progress.setValue(self.task_progress)

    def layer_combo_tooltip(self, layer_ids):
        layer_names = []
        for layer_id in layer_ids:
            layer = self.layers_by_id.get(layer_id)
            if layer is not None:
                layer_names.append(layer.name())
        if not layer_names:
            return ''
        return 'Шари:\n' + '\n'.join(f'• {name}' for name in layer_names)

    def add_layer_combo_item(self, text, unit_id, layer_ids):
        index = self.layer_combo.count()
        self.layer_combo.addItem(text, unit_id)
        self.layer_combo.setItemData(
            index,
            self.layer_combo_tooltip(layer_ids),
            Qt.ToolTipRole,
        )

    def update_layer_combo_tooltip(self, *args):
        tooltip = self.layer_combo.currentData(Qt.ToolTipRole) or ''
        self.layer_combo.setToolTip(str(tooltip))

    def set_search_units(self, units):
        if self.is_closing or not units:
            return

        active_layer = self.iface.activeLayer()
        active_layer_id = active_layer.id() if active_layer is not None else None
        self.units_by_id = {unit['id']: dict(unit) for unit in units}
        self.layer_to_unit_id = {}
        for unit in units:
            for layer_id in unit.get('layer_ids', []):
                self.layer_to_unit_id[layer_id] = unit['id']

        self.results_by_layer = {
            unit['id']: self.results_by_layer.get(unit['id'], {})
            for unit in units
        }

        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for unit in units:
            self.add_layer_combo_item(
                unit['name'],
                unit['id'],
                unit.get('layer_ids', []),
            )

        target_unit_id = self.layer_to_unit_id.get(active_layer_id)
        target_index = self.layer_combo.findData(target_unit_id)
        if target_index < 0 and self.layer_combo.count():
            target_index = 0
        if target_index >= 0:
            self.layer_combo.setCurrentIndex(target_index)
        self.layer_combo.blockSignals(False)
        self.update_layer_combo_tooltip()
        self.on_search_unit_changed()

    def crs_label(self, crs_code, crs_name):
        if crs_name:
            return f'{crs_code} — {crs_name}'
        return crs_code

    def active_layer_id(self):
        return self.layer_combo.currentData()

    def current_unit_layer_ids(self):
        unit = self.units_by_id.get(self.active_layer_id(), {})
        return list(unit.get('layer_ids', []))

    def on_current_layer_changed(self, layer):
        if self.is_closing or self.syncing_tree_selection or layer is None:
            return

        unit_id = self.layer_to_unit_id.get(layer.id(), layer.id())
        index = self.layer_combo.findData(unit_id)
        if index >= 0 and index != self.layer_combo.currentIndex():
            self.layer_combo.setCurrentIndex(index)

    def on_search_unit_changed(self, *args):
        if self.is_closing:
            return
        self.rebuild_table()
        self.select_current_unit_layers()

    def select_current_unit_layers(self):
        layer_ids = self.current_unit_layer_ids()
        if not layer_ids:
            return

        tree_view = self.iface.layerTreeView()
        selection_model = tree_view.selectionModel()
        if selection_model is None:
            return
        root = QgsProject.instance().layerTreeRoot()
        indexes = []
        for layer_id in layer_ids:
            node = root.findLayer(layer_id)
            if node is None:
                continue
            index = tree_view.node2index(node)
            if index.isValid():
                indexes.append(index)

        if not indexes:
            return

        self.syncing_tree_selection = True
        try:
            selection_model.clearSelection()
            flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
            for index in indexes:
                selection_model.select(index, flags)
            selection_model.setCurrentIndex(indexes[0], QItemSelectionModel.NoUpdate)
        finally:
            self.syncing_tree_selection = False

    def zoom_to_current_unit(self, *args):
        self.select_current_unit_layers()
        action = self.iface.actionZoomToLayers()
        if action is not None:
            action.trigger()

    def add_result(
        self,
        layer_id,
        layer_name,
        crs_code,
        crs_name,
        distance,
        crs,
        note,
    ):
        if self.is_closing:
            return

        self.pending_results.append(
            (layer_id, layer_name, crs_code, crs_name, distance, crs, note)
        )
        if not self.flush_timer.isActive():
            self.flush_timer.start()

    def flush_pending_results(self):
        if self.is_closing or not self.pending_results:
            return

        results = self.pending_results
        self.pending_results = []
        active_layer_id = self.active_layer_id()
        active_layer_changed = False

        for layer_id, layer_name, crs_code, crs_name, distance, crs, note in results:
            layer_results = self.results_by_layer.setdefault(layer_id, {})
            previous = layer_results.get(crs_code)
            if previous is None or distance < previous[2]:
                layer_results[crs_code] = (crs_name, crs, distance, note)
                if layer_id == active_layer_id:
                    active_layer_changed = True

        if active_layer_changed:
            self.rebuild_table()
        else:
            self.update_button_states()

    def rebuild_table(self, *args):
        if self.is_closing:
            return

        layer_id = self.active_layer_id()
        results = self.results_by_layer.get(layer_id, {})
        ordered_results = sorted(results.items(), key=lambda item: item[1][2])

        self.table.setSortingEnabled(False)
        self.table.clearSpans()
        self.table.setRowCount(
            len(ordered_results) if ordered_results else int(self.search_finished)
        )

        if not ordered_results and self.search_finished:
            unit = self.units_by_id.get(layer_id, {})
            center_coordinates = unit.get('center_coordinates')
            empty_text = 'Нічого не знайдено'
            if unit.get('near_origin_warning'):
                centroid_text = ''
                if center_coordinates:
                    centroid_text = (
                        f' (X = {center_coordinates[0]:.3f}, '
                        f'Y = {center_coordinates[1]:.3f})'
                    )
                empty_text += (
                    f'. ⚠ Центроїд геоданих{centroid_text} '
                    'розташований на відстані менш як 10 км від '
                    'початку координат. Можливо, дані не мають '
                    'просторової прив’язки.'
                )
            empty_item = QTableWidgetItem(empty_text)
            if unit.get('near_origin_warning') and center_coordinates:
                empty_item.setToolTip(
                    'Центроїд: '
                    f'X = {center_coordinates[0]:.3f}, '
                    f'Y = {center_coordinates[1]:.3f}. '
                    'Це може свідчити про локальну або умовну систему координат.'
                )
            empty_item.setTextAlignment(Qt.AlignCenter)
            empty_item.setFlags(Qt.NoItemFlags)
            self.table.setItem(0, 0, empty_item)
            self.table.setSpan(0, 0, 1, self.table.columnCount())

        for row, (crs_code, (crs_name, crs, distance, note)) in enumerate(ordered_results):
            full_crs_label = self.crs_label(crs_code, crs_name)
            crs_item = QTableWidgetItem(full_crs_label)
            crs_item.setToolTip(full_crs_label)
            crs_item.setData(Qt.UserRole + 1, layer_id)
            crs_item.setData(Qt.UserRole + 2, crs)
            crs_item.setData(Qt.UserRole + 3, crs_code)
            crs_item.setData(Qt.UserRole + 4, distance)
            crs_item.setData(Qt.UserRole + 5, crs_name)

            distance_item = DistanceTableWidgetItem(f'{distance:,.0f}'.replace(',', ' '))
            distance_item.setData(Qt.UserRole, distance)

            note_item = QTableWidgetItem(note)
            if note == 'Ballpark':
                note_item.setToolTip(
                    'Використано приблизне перетворення (Ballpark); '
                    'геодезична точність не гарантується.'
                )
            elif note == 'Fallback':
                note_item.setToolTip(
                    'Використано запасну операцію (Fallback); '
                    'точність може бути нижчою.'
                )

            self.table.setItem(row, 0, crs_item)
            self.table.setItem(row, 1, distance_item)
            self.table.setItem(row, 2, note_item)

        self.table.setSortingEnabled(True)
        self.table.sortItems(1, Qt.AscendingOrder)
        self.elide_crs_labels()
        QTimer.singleShot(0, self.elide_crs_labels)
        if ordered_results:
            self.table.selectRow(0)
        self.render_stats()
        self.update_button_states()

    def elide_crs_labels(self, *args):
        available_width = max(1, self.table.columnWidth(0) - 16)
        metrics = QFontMetrics(self.table.font())
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            crs_code = item.data(Qt.UserRole + 3)
            if not crs_code:
                continue
            full_label = self.crs_label(
                crs_code,
                item.data(Qt.UserRole + 5),
            )
            item.setText(
                metrics.elidedText(full_label, Qt.ElideRight, available_width)
            )
            item.setToolTip(full_label)

    def current_result(self):
        row = self.table.currentRow()
        if row < 0:
            return None

        crs_item = self.table.item(row, 0)
        if crs_item is None:
            return None

        crs = crs_item.data(Qt.UserRole + 2)
        crs_code = crs_item.data(Qt.UserRole + 3)
        if crs is None or not crs_code:
            return None

        return {
            'source_unit_id': crs_item.data(Qt.UserRole + 1),
            'crs': crs,
            'crs_code': crs_code,
            'distance': crs_item.data(Qt.UserRole + 4),
            'crs_name': crs_item.data(Qt.UserRole + 5),
        }

    def selected_supported_layers(self):
        try:
            selected_layers = self.iface.layerTreeView().selectedLayersRecursive()
        except Exception:
            selected_layers = []

        result = []
        known_ids = set()
        for layer in selected_layers:
            if layer.id() in known_ids:
                continue
            if layer.type() not in (QgsMapLayerType.VectorLayer, QgsMapLayerType.RasterLayer):
                continue
            result.append(layer)
            known_ids.add(layer.id())
        return result

    def result_text_for_layer_crs(self, result_id, crs_code, crs_name):
        layer_result = self.results_by_layer.get(result_id, {}).get(crs_code)
        if layer_result is None:
            return f'{self.crs_label(crs_code, crs_name)} — застосовано користувачем'
        distance = layer_result[2]
        return (
            f"{self.crs_label(crs_code, crs_name)} — "
            f"{f'{distance:,.0f}'.replace(',', ' ')} м від точки кліку"
        )

    def apply_selected_crs(self, *args):
        result = self.current_result()
        if result is None:
            return

        target_layers = self.selected_supported_layers()
        if not target_layers:
            self.iface.messageBar().pushMessage(
                '[CRS Magic finder] Виділіть у дереві хоча б один векторний або растровий шар.',
                Qgis.MessageLevel.Warning,
                5,
            )
            return

        changes = []
        crs = result['crs']
        crs_code = result['crs_code']
        crs_name = result['crs_name']
        source_unit_id = result['source_unit_id']

        for layer in target_layers:
            layer_id = layer.id()
            old_crs = QgsCoordinateReferenceSystem(layer.crs())
            new_crs = QgsCoordinateReferenceSystem(crs)
            manual_before = self.manual_result_text.get(layer_id)
            manual_after = self.result_text_for_layer_crs(
                source_unit_id,
                crs_code,
                crs_name,
            )

            layer.setCrs(new_crs)
            self.manual_layer_ids.add(layer_id)
            self.manual_result_text[layer_id] = manual_after
            changes.append({
                'layer_id': layer_id,
                'old_crs': old_crs,
                'new_crs': new_crs,
                'manual_before': manual_before,
                'manual_after': manual_after,
            })

        self.push_history_action(changes)
        self.refresh_layers(target_layers)
        self.iface.messageBar().pushMessage(
            f"[CRS Magic finder] {self.crs_label(crs_code, crs_name)} застосовано. "
            f"Кількість шарів: {len(target_layers)}.",
            Qgis.MessageLevel.Success,
            4,
        )

    def record_external_changes(self, changes):
        if self.is_closing:
            return
        history_changes = []
        for layer, old_crs, new_crs in changes:
            layer_id = layer.id()
            manual_state = self.manual_result_text.get(layer_id)
            history_changes.append({
                'layer_id': layer_id,
                'old_crs': QgsCoordinateReferenceSystem(old_crs),
                'new_crs': QgsCoordinateReferenceSystem(new_crs),
                'manual_before': manual_state,
                'manual_after': manual_state,
            })
        self.push_history_action(history_changes)

    def push_history_action(self, changes):
        if self.is_closing or not changes:
            return
        self.undo_stack.append(changes)
        self.redo_stack.clear()
        self.update_button_states()

    def refresh_layers(self, layers):
        refreshed_ids = set()
        for layer in layers:
            if layer is None or layer.id() in refreshed_ids:
                continue
            layer.triggerRepaint(True)
            refreshed_ids.add(layer.id())
        if refreshed_ids:
            self.iface.mapCanvas().refresh()

    def apply_history_state(self, changes, use_new_state):
        project = QgsProject.instance()
        changed_layers = []
        for change in changes:
            layer = project.mapLayer(change['layer_id'])
            if layer is None:
                continue

            crs_key = 'new_crs' if use_new_state else 'old_crs'
            manual_key = 'manual_after' if use_new_state else 'manual_before'
            layer.setCrs(QgsCoordinateReferenceSystem(change[crs_key]))
            changed_layers.append(layer)

            manual_text = change[manual_key]
            if manual_text is None:
                self.manual_layer_ids.discard(change['layer_id'])
                self.manual_result_text.pop(change['layer_id'], None)
            else:
                self.manual_layer_ids.add(change['layer_id'])
                self.manual_result_text[change['layer_id']] = manual_text

        self.refresh_layers(changed_layers)

    def undo_last_operation(self):
        if not self.undo_stack:
            return
        changes = self.undo_stack.pop()
        self.apply_history_state(changes, False)
        self.redo_stack.append(changes)
        self.update_button_states()

    def redo_last_operation(self):
        if not self.redo_stack:
            return
        changes = self.redo_stack.pop()
        self.apply_history_state(changes, True)
        self.undo_stack.append(changes)
        self.update_button_states()

    def update_button_states(self):
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))
        self.apply_button.setEnabled(self.current_result() is not None)
        self.zoom_button.setEnabled(bool(self.current_unit_layer_ids()))

    def update_stats(self, total, processed, success, failed, skipped, matched):
        self.last_stats = (total, processed, success, failed, skipped, matched)
        self.render_stats()

    def render_stats(self):
        if self.phase_status:
            self.render_phase_status()
            return
        if self.last_stats is None:
            return
        total, processed, success, failed, skipped, matched = self.last_stats
        active_rows = len(self.results_by_layer.get(self.active_layer_id(), {}))
        self.status_label.setText(
            f'СК: {total} | Перевірено: {processed} | Успішних: {success} | '
            f'Помилок: {failed} | Пропущено: {skipped} | Збігів до 200 км: {matched} | '
            f'У поточній таблиці: {active_rows}{self.status_suffix}'
        )

    def has_manual_selection(self, layer_id):
        return layer_id in self.manual_layer_ids

    def manual_selection_text(self, layer_id):
        return self.manual_result_text.get(layer_id, '')

    def mark_finished(self):
        self.flush_pending_results()
        self.cancel_button.setEnabled(False)
        self.status_progress.setValue(100)
        self.task = None
        self.phase_status = ''
        self.search_finished = True
        self.status_suffix = ' | Готово'
        self.rebuild_table()

    def mark_failed(self, failure):
        self.flush_pending_results()
        self.cancel_button.setEnabled(False)
        self.task = None
        self.phase_status = ''
        self.status_suffix = ''
        self.status_label.setText(f'Помилка: {failure}')

    def cancel_search(self):
        if self.task:
            self.task.cancel()
            self.phase_status = ''
            self.status_suffix = ' | Скасування…'
            if self.last_stats is None:
                self.status_label.setText('Скасування…')
            else:
                self.render_stats()

    def closeEvent(self, event):
        self.is_closing = True
        try:
            if self.task and not self.task.isCanceled():
                self.task.cancel()
        except RuntimeError:
            pass
        try:
            self.iface.currentLayerChanged.disconnect(self.on_current_layer_changed)
        except Exception:
            pass
        self.flush_timer.stop()
        self.pending_results.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.manual_layer_ids.clear()
        self.manual_result_text.clear()
        super().closeEvent(event)
