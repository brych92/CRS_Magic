import json
import math
import re

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsWkbTypes,
)
from qgis.gui import (
    QgsMapCanvas,
    QgsMapTool,
    QgsProjectionSelectionTreeWidget,
    QgsRubberBand,
)
from qgis.PyQt.QtCore import QModelIndex, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTextEdit,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


CRS_CODE_ROLE = Qt.UserRole
CRS_SETS_FILE_FORMAT = 'CRS Magic finder CRS sets'
CRS_SETS_FILE_VERSION = 1


def qgis_icon(names, fallback_standard_icon=None):
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

    if fallback_standard_icon is not None:
        return QApplication.style().standardIcon(fallback_standard_icon)

    return QApplication.style().standardIcon(QStyle.SP_FileIcon)


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


def normalize_crs_set_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}

    result = {}
    description = str(metadata.get('description', '') or '').strip()
    if description:
        result['description'] = description

    raw_extent = metadata.get('extent')
    if isinstance(raw_extent, dict):
        try:
            extent = {
                key: float(raw_extent[key])
                for key in ('xmin', 'ymin', 'xmax', 'ymax')
            }
        except (KeyError, TypeError, ValueError):
            extent = None

        if (
            extent
            and all(math.isfinite(value) for value in extent.values())
            and extent['xmin'] < extent['xmax']
            and extent['ymin'] < extent['ymax']
        ):
            crs = str(raw_extent.get('crs', '') or '').strip()
            crs_wkt = str(raw_extent.get('crs_wkt', '') or '').strip()
            if crs:
                extent['crs'] = crs
            elif crs_wkt:
                extent['crs_wkt'] = crs_wkt
            result['extent'] = extent

    return result


def crs_sets_bundle_from_json_data(data):
    if not isinstance(data, dict):
        raise ValueError('Кореневий елемент JSON має бути об’єктом.')

    if data.get('version') != CRS_SETS_FILE_VERSION:
        raise ValueError(
            f'Підтримується лише версія структури {CRS_SETS_FILE_VERSION}.'
        )

    raw_sets = data.get('CRS_sets')
    if not isinstance(raw_sets, dict):
        raise ValueError('Поле «CRS_sets» має містити об’єкти наборів СК.')

    crs_sets = {}
    crs_set_metadata = {}
    skipped_names = []
    for raw_name, raw_set in raw_sets.items():
        name = str(raw_name).strip()
        if isinstance(raw_set, dict) and isinstance(raw_set.get('codes'), list):
            code_text = '\n'.join(str(code) for code in raw_set['codes'])
        else:
            code_text = ''

        codes = parse_crs_codes(code_text)
        if name and codes:
            crs_sets[name] = codes
            metadata = normalize_crs_set_metadata(raw_set)
            if metadata:
                crs_set_metadata[name] = metadata
        else:
            skipped_names.append(name or str(raw_name))

    return crs_sets, crs_set_metadata, skipped_names


def crs_sets_from_json_data(data):
    crs_sets, _, skipped_names = crs_sets_bundle_from_json_data(data)
    return crs_sets, skipped_names


def crs_sets_to_json_data(crs_sets, crs_set_metadata=None):
    objects = {}
    for raw_name, raw_codes in crs_sets.items():
        name = str(raw_name).strip()
        codes = parse_crs_codes('\n'.join(str(code) for code in raw_codes))
        if not name or not codes:
            continue

        set_object = {'codes': codes}
        metadata = normalize_crs_set_metadata(
            (crs_set_metadata or {}).get(name, {})
        )
        if metadata.get('description'):
            set_object['description'] = metadata['description']
        if metadata.get('extent'):
            set_object['extent'] = metadata['extent']
        objects[name] = set_object

    return {
        'format': CRS_SETS_FILE_FORMAT,
        'version': CRS_SETS_FILE_VERSION,
        'CRS_sets': objects,
    }


def crs_from_code(crs_code):
    code = normalize_crs_code(crs_code)
    if code.startswith('QGIS:'):
        try:
            return QgsCoordinateReferenceSystem.fromSrsId(int(code.split(':', 1)[1]))
        except Exception:
            return QgsCoordinateReferenceSystem()

    return QgsCoordinateReferenceSystem(code)


def crs_auth_id(crs, fallback_code=''):
    try:
        auth_id = crs.authid()
    except Exception:
        auth_id = ''
    return auth_id or fallback_code


def crs_description(crs):
    try:
        return crs.description()
    except Exception:
        return ''


def crs_display_label(crs_code):
    code = normalize_crs_code(crs_code)
    crs = crs_from_code(code)
    auth_id = crs_auth_id(crs, code)
    description = crs_description(crs)

    if description:
        return f'{auth_id} — {description}'
    return auth_id


def configure_osm_canvas(map_canvas, source_canvas=None):
    web_mercator = QgsCoordinateReferenceSystem('EPSG:3857')
    map_canvas.setDestinationCrs(web_mercator)
    osm_uri = (
        'type=xyz&url=https://tile.openstreetmap.org/'
        '{z}/{x}/{y}.png&zmax=19&zmin=0'
    )
    osm_layer = QgsRasterLayer(osm_uri, 'OpenStreetMap', 'wms')
    if osm_layer.isValid():
        map_canvas.setLayers([osm_layer])

    initial_extent = None
    if source_canvas is not None and source_canvas.layers():
        try:
            source_crs = source_canvas.mapSettings().destinationCrs()
            source_extent = source_canvas.extent()
            if source_crs.isValid() and source_extent and not source_extent.isEmpty():
                transform = QgsCoordinateTransform(
                    source_crs,
                    web_mercator,
                    QgsProject.instance()
                )
                initial_extent = transform.transformBoundingBox(source_extent)
        except Exception:
            initial_extent = None

    if initial_extent is None or initial_extent.isEmpty():
        if osm_layer.isValid() and not osm_layer.extent().isEmpty():
            initial_extent = osm_layer.extent()
        else:
            initial_extent = QgsRectangle(
                -20037508.3427892,
                -20037508.3427892,
                20037508.3427892,
                20037508.3427892,
            )

    map_canvas.setExtent(initial_extent)
    map_canvas.refresh()
    return osm_layer


def extent_rectangle_from_metadata(metadata, destination_crs=None):
    metadata = normalize_crs_set_metadata(metadata)
    raw_extent = metadata.get('extent')
    if not raw_extent:
        return None

    rectangle = QgsRectangle(
        raw_extent['xmin'],
        raw_extent['ymin'],
        raw_extent['xmax'],
        raw_extent['ymax'],
    )
    if destination_crs is None or not destination_crs.isValid():
        return rectangle

    source_crs = QgsCoordinateReferenceSystem(raw_extent.get('crs', ''))
    if not source_crs.isValid() and raw_extent.get('crs_wkt'):
        source_crs = QgsCoordinateReferenceSystem()
        source_crs.createFromWkt(raw_extent['crs_wkt'])

    if not source_crs.isValid() or source_crs == destination_crs:
        return rectangle

    try:
        transform = QgsCoordinateTransform(
            source_crs,
            destination_crs,
            QgsProject.instance()
        )
        return transform.transformBoundingBox(rectangle)
    except Exception:
        return None


class CRSSetExtentMapTool(QgsMapTool):
    extentChanged = pyqtSignal(object)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.start_point = None
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber_band.setStrokeColor(QColor(220, 45, 45, 230))
        self.rubber_band.setFillColor(QColor(220, 45, 45, 45))
        self.rubber_band.setWidth(2)

    def canvasPressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.start_point = event.mapPoint()
        self.update_rectangle(self.start_point)

    def canvasMoveEvent(self, event):
        if self.start_point is not None:
            self.update_rectangle(event.mapPoint())

    def canvasReleaseEvent(self, event):
        if self.start_point is None or event.button() != Qt.LeftButton:
            return

        rectangle = QgsRectangle(self.start_point, event.mapPoint())
        rectangle.normalize()
        self.start_point = None
        if rectangle.isEmpty():
            self.clear_extent()
            return

        self.update_rectangle_from_extent(rectangle)
        self.extentChanged.emit(QgsRectangle(rectangle))

    def update_rectangle(self, end_point):
        rectangle = QgsRectangle(self.start_point, end_point)
        rectangle.normalize()
        self.update_rectangle_from_extent(rectangle)

    def update_rectangle_from_extent(self, rectangle):
        self.rubber_band.setToGeometry(QgsGeometry.fromRect(rectangle), None)

    def clear_extent(self):
        self.start_point = None
        self.rubber_band.reset(QgsWkbTypes.PolygonGeometry)


class CRSSetMetadataEditorWidget(QWidget):
    def __init__(self, metadata=None, source_canvas=None, parent=None):
        super().__init__(parent)

        self.description_edit = QTextEdit()
        self.description_edit.setPlaceholderText('Введіть опис набору')
        self.description_edit.setMaximumHeight(110)

        self.map_canvas = QgsMapCanvas(self)
        self.map_canvas.setCanvasColor(QColor(245, 245, 245))
        self.map_canvas.setMinimumHeight(280)
        self.osm_layer = configure_osm_canvas(self.map_canvas, source_canvas)

        self.extent_tool = CRSSetExtentMapTool(self.map_canvas)
        self.extent_tool.extentChanged.connect(self.set_extent)
        self.map_canvas.setMapTool(self.extent_tool)
        self.selected_extent = None

        self.draw_extent_button = QPushButton('Намалювати екстент')
        self.draw_extent_button.setToolTip(
            'Протягніть мишею прямокутник на мінікарті. Колесо миші змінює масштаб.'
        )
        self.draw_extent_button.clicked.connect(
            lambda: self.map_canvas.setMapTool(self.extent_tool)
        )
        self.clear_extent_button = QPushButton('Очистити екстент')
        self.clear_extent_button.clicked.connect(self.clear_extent)

        extent_buttons_layout = QHBoxLayout()
        extent_buttons_layout.addWidget(self.draw_extent_button)
        extent_buttons_layout.addWidget(self.clear_extent_button)
        extent_buttons_layout.addStretch()

        self.extent_label = QLabel('Екстент не задано')
        self.extent_label.setWordWrap(True)
        osm_attribution = QLabel(
            'Підоснова: <a href="https://www.openstreetmap.org/copyright">'
            '© OpenStreetMap contributors</a>'
        )
        osm_attribution.setOpenExternalLinks(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel('Опис набору (необов’язково)'))
        layout.addWidget(self.description_edit)
        layout.addWidget(QLabel('Екстент застосування (необов’язково)'))
        layout.addWidget(self.map_canvas, 1)
        layout.addWidget(osm_attribution)
        layout.addLayout(extent_buttons_layout)
        layout.addWidget(self.extent_label)
        self.setLayout(layout)
        self.load_metadata(metadata)

    def load_metadata(self, metadata):
        metadata = normalize_crs_set_metadata(metadata)
        self.description_edit.setPlainText(metadata.get('description', ''))
        rectangle = extent_rectangle_from_metadata(
            metadata,
            self.map_canvas.mapSettings().destinationCrs()
        )
        if rectangle is None:
            return

        self.extent_tool.update_rectangle_from_extent(rectangle)
        self.set_extent(rectangle)
        preview_extent = QgsRectangle(rectangle)
        preview_extent.grow(max(rectangle.width(), rectangle.height()) * 0.15)
        self.map_canvas.setExtent(preview_extent)
        self.map_canvas.refresh()

    def set_extent(self, rectangle):
        self.selected_extent = QgsRectangle(rectangle)
        crs_label = self.map_canvas.mapSettings().destinationCrs().authid()
        self.extent_label.setText(
            f'{crs_label}: '
            f'{rectangle.xMinimum():.3f}, {rectangle.yMinimum():.3f} — '
            f'{rectangle.xMaximum():.3f}, {rectangle.yMaximum():.3f}'
        )

    def clear_extent(self):
        self.selected_extent = None
        self.extent_tool.clear_extent()
        self.extent_label.setText('Екстент не задано')

    def metadata(self):
        result = {}
        description = self.description_edit.toPlainText().strip()
        if description:
            result['description'] = description
        if self.selected_extent is not None:
            rectangle = self.selected_extent
            extent = {
                'xmin': rectangle.xMinimum(),
                'ymin': rectangle.yMinimum(),
                'xmax': rectangle.xMaximum(),
                'ymax': rectangle.yMaximum(),
            }
            crs = self.map_canvas.mapSettings().destinationCrs()
            auth_id = crs.authid()
            if auth_id:
                extent['crs'] = auth_id
            elif crs.toWkt():
                extent['crs_wkt'] = crs.toWkt()
            result['extent'] = extent
        return normalize_crs_set_metadata(result)


class CRSSetMetadataWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(350)

        self.description_view = QTextEdit()
        self.description_view.setReadOnly(True)
        self.description_view.setPlaceholderText('Опис не задано')
        self.description_view.setMaximumHeight(110)

        self.map_canvas = QgsMapCanvas(self)
        self.map_canvas.setCanvasColor(QColor(245, 245, 245))
        self.map_canvas.setMinimumHeight(260)
        self.osm_layer = configure_osm_canvas(self.map_canvas)

        self.extent_band = QgsRubberBand(
            self.map_canvas,
            QgsWkbTypes.PolygonGeometry
        )
        self.extent_band.setStrokeColor(QColor(220, 45, 45, 230))
        self.extent_band.setFillColor(QColor(220, 45, 45, 45))
        self.extent_band.setWidth(2)

        self.extent_info_label = QLabel('Екстент не задано')
        self.extent_info_label.setWordWrap(True)
        osm_attribution = QLabel(
            'Підоснова: <a href="https://www.openstreetmap.org/copyright">'
            '© OpenStreetMap contributors</a>'
        )
        osm_attribution.setOpenExternalLinks(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel('Опис набору'))
        layout.addWidget(self.description_view)
        layout.addWidget(QLabel('Екстент застосування'))
        layout.addWidget(self.map_canvas, 1)
        layout.addWidget(osm_attribution)
        layout.addWidget(self.extent_info_label)
        self.setLayout(layout)

    def set_metadata(self, metadata):
        metadata = normalize_crs_set_metadata(metadata)
        self.description_view.setPlainText(metadata.get('description', ''))
        self.extent_band.reset(QgsWkbTypes.PolygonGeometry)

        rectangle = extent_rectangle_from_metadata(
            metadata,
            self.map_canvas.mapSettings().destinationCrs()
        )
        if rectangle is None:
            self.extent_info_label.setText('Екстент не задано')
            if self.osm_layer.isValid() and not self.osm_layer.extent().isEmpty():
                self.map_canvas.setExtent(self.osm_layer.extent())
            else:
                self.map_canvas.setExtent(QgsRectangle(
                    -20037508.3427892,
                    -20037508.3427892,
                    20037508.3427892,
                    20037508.3427892,
                ))
            self.map_canvas.refresh()
            return

        self.extent_band.setToGeometry(QgsGeometry.fromRect(rectangle), None)
        preview_extent = QgsRectangle(rectangle)
        preview_extent.grow(max(rectangle.width(), rectangle.height()) * 0.15)
        self.map_canvas.setExtent(preview_extent)
        self.map_canvas.refresh()

        raw_extent = metadata['extent']
        crs_label = raw_extent.get('crs', 'СК збереженого екстенту')
        self.extent_info_label.setText(
            f'{crs_label}: '
            f"{raw_extent['xmin']:.3f}, {raw_extent['ymin']:.3f} — "
            f"{raw_extent['xmax']:.3f}, {raw_extent['ymax']:.3f}"
        )


class CRSSetEditorDialog(QDialog):
    def __init__(
        self,
        set_name,
        crs_codes,
        metadata=None,
        source_canvas=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f'Редагування набору — {set_name}')
        self.resize(1380, 700)

        self.selected_list = QListWidget()
        self.selected_list.setAlternatingRowColors(True)
        self.selected_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.selected_list.itemDoubleClicked.connect(self.remove_selected_crs)
        self.selected_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.selected_list.customContextMenuRequested.connect(
            self.open_selected_crs_context_menu
        )

        self.remove_button = QToolButton()
        self.remove_button.setIcon(qgis_icon(
            ['mActionRemove.svg', 'symbologyRemove.svg', 'mIconRemove.svg'],
            QStyle.SP_DialogDiscardButton
        ))
        self.remove_button.setToolTip('Видалити вибрані СК з набору')
        self.remove_button.clicked.connect(self.remove_selected_crs)

        selected_buttons_layout = QHBoxLayout()
        selected_buttons_layout.addWidget(self.remove_button)
        selected_buttons_layout.addStretch()

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel('СК у наборі'))
        left_layout.addWidget(self.selected_list)
        left_layout.addLayout(selected_buttons_layout)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        self.crs_picker = QgsProjectionSelectionTreeWidget(self)
        if hasattr(self.crs_picker, 'setShowNoProjection'):
            self.crs_picker.setShowNoProjection(False)
        if hasattr(self.crs_picker, 'setShowBoundsMap'):
            self.crs_picker.setShowBoundsMap(True)
        if hasattr(self.crs_picker, 'projectionDoubleClicked'):
            self.crs_picker.projectionDoubleClicked.connect(self.add_selected_crs)

        self.add_button = QPushButton('Додати вибрану СК')
        self.add_button.setIcon(qgis_icon(
            ['mActionAdd.svg', 'symbologyAdd.svg', 'mIconAdd.svg'],
            QStyle.SP_DialogApplyButton
        ))
        self.add_button.clicked.connect(self.add_selected_crs)

        self.add_visible_button = QPushButton('Додати всі видимі')
        self.add_visible_button.setToolTip(
            'Додає всі СК, видимі після фільтрування за назвою.'
        )
        self.add_visible_button.setIcon(qgis_icon(
            ['mActionAdd.svg', 'symbologyAdd.svg', 'mIconAdd.svg'],
            QStyle.SP_DialogApplyButton
        ))
        self.add_visible_button.clicked.connect(self.add_visible_crs)

        right_buttons_layout = QHBoxLayout()
        right_buttons_layout.addStretch()
        right_buttons_layout.addWidget(self.add_button)
        right_buttons_layout.addWidget(self.add_visible_button)

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel('Вибір СК'))
        right_layout.addWidget(self.crs_picker, 1)
        right_layout.addLayout(right_buttons_layout)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        self.metadata_editor = CRSSetMetadataEditorWidget(
            metadata,
            source_canvas=source_canvas,
            parent=self,
        )

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.addWidget(self.metadata_editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        layout.addWidget(self.buttons)
        self.setLayout(layout)

        self.load_selected_codes(crs_codes)

    def load_selected_codes(self, crs_codes):
        for code in crs_codes:
            self.add_crs_code(code)

    def selected_codes(self):
        codes = []
        for row in range(self.selected_list.count()):
            code = self.selected_list.item(row).data(CRS_CODE_ROLE)
            if code:
                codes.append(code)
        return codes

    def add_crs_code(self, crs_code):
        code = normalize_crs_code(crs_code)
        if not code or code in self.selected_codes():
            return

        item = QListWidgetItem(crs_display_label(code))
        item.setData(CRS_CODE_ROLE, code)
        item.setToolTip(code)
        self.selected_list.addItem(item)

    def add_selected_crs(self, *args):
        crs = self.crs_picker.crs()
        try:
            is_valid = crs.isValid()
        except Exception:
            is_valid = False

        if not is_valid:
            QMessageBox.warning(self, 'Набір СК', 'Виберіть СК перед додаванням.')
            return

        try:
            fallback_code = f'QGIS:{crs.srsid()}'
        except Exception:
            fallback_code = ''

        code = normalize_crs_code(crs_auth_id(crs, fallback_code))
        before = len(self.selected_codes())
        self.add_crs_code(code)
        if len(self.selected_codes()) > before:
            self.selected_list.scrollToBottom()

    def add_visible_crs(self, *args):
        codes = self.visible_crs_codes()
        if not codes:
            QMessageBox.warning(
                self,
                'Набір СК',
                'Не вдалося отримати видимі СК зі стандартного віджета QGIS.'
            )
            return

        before = len(self.selected_codes())
        for code in codes:
            self.add_crs_code(code)

        added = len(self.selected_codes()) - before
        if added:
            self.selected_list.scrollToBottom()
            return

        QMessageBox.information(self, 'Набір СК', 'Усі видимі СК вже додано до набору.')

    def visible_crs_codes(self):
        tree_view = self.crs_tree_view()
        if not tree_view:
            return []

        model = tree_view.model()
        if not model:
            return []

        codes = []
        known_codes = set()

        def collect(parent_index):
            for row in range(model.rowCount(parent_index)):
                if tree_view.isRowHidden(row, parent_index):
                    continue

                row_codes = self.crs_codes_from_model_row(model, row, parent_index)
                for code in row_codes:
                    if code not in known_codes:
                        codes.append(code)
                        known_codes.add(code)

                child_parent = model.index(row, 0, parent_index)
                if child_parent.isValid():
                    collect(child_parent)

        collect(tree_view.rootIndex())
        return codes

    def crs_tree_view(self):
        candidates = self.crs_picker.findChildren(QTreeView)
        for candidate in candidates:
            model = candidate.model()
            if model and model.rowCount(QModelIndex()) > 0:
                return candidate
        return None

    def crs_codes_from_model_row(self, model, row, parent_index):
        codes = []
        column_count = max(1, model.columnCount(parent_index))
        for column in range(column_count):
            index = model.index(row, column, parent_index)
            code = self.crs_code_from_model_index(index)
            if code and code not in codes:
                codes.append(code)
        return codes

    def crs_code_from_model_index(self, index):
        if not index.isValid():
            return ''

        display_code = self.crs_code_from_value(index.data(Qt.DisplayRole), True)
        if display_code:
            return display_code

        for role in range(Qt.UserRole, Qt.UserRole + 40):
            code = self.crs_code_from_value(index.data(role), False)
            if code:
                return code

        return ''

    def crs_code_from_value(self, value, allow_plain_epsg):
        if value is None:
            return ''

        if hasattr(value, 'isValid') and hasattr(value, 'authid'):
            try:
                if value.isValid():
                    return normalize_crs_code(crs_auth_id(value))
            except Exception:
                return ''

        text = str(value)
        pattern = r'[A-Za-z][A-Za-z0-9_]*:\d+'
        if allow_plain_epsg:
            pattern = r'[A-Za-z][A-Za-z0-9_]*:\d+|\b\d{4,}\b'

        match = re.search(pattern, text)
        if not match:
            return ''

        return normalize_crs_code(match.group(0))

    def remove_selected_crs(self, *args):
        rows = sorted(
            [self.selected_list.row(item) for item in self.selected_list.selectedItems()],
            reverse=True
        )
        for row in rows:
            self.selected_list.takeItem(row)

    def open_selected_crs_context_menu(self, position):
        item = self.selected_list.itemAt(position)
        if not item:
            return

        if not item.isSelected():
            self.selected_list.clearSelection()
            item.setSelected(True)
        self.selected_list.setCurrentItem(item)

        menu = QMenu(self)
        delete_action = menu.addAction(qgis_icon(
            ['mActionRemove.svg', 'symbologyRemove.svg', 'mIconRemove.svg'],
            QStyle.SP_DialogDiscardButton
        ), 'Видалити')

        if menu.exec_(self.selected_list.mapToGlobal(position)) == delete_action:
            self.remove_selected_crs()

    def result_codes(self):
        return self.selected_codes()

    def result_metadata(self):
        return self.metadata_editor.metadata()


class CRSSetSettingsDialog(QDialog):
    def __init__(
        self,
        crs_sets,
        parent=None,
        fast_mode=False,
        group_search=False,
        disable_fallback_handler=True,
        allow_fallback=True,
        allow_ballpark=False,
        source_map_canvas=None,
        crs_set_metadata=None,
    ):
        super().__init__(parent)
        self.source_map_canvas = source_map_canvas
        self.crs_sets = {}
        for name, codes in crs_sets.items():
            normalized_codes = parse_crs_codes('\n'.join(codes))
            if str(name).strip() and normalized_codes:
                self.crs_sets[str(name).strip()] = normalized_codes
        self.crs_set_metadata = {}
        for name, metadata in (crs_set_metadata or {}).items():
            clean_name = str(name).strip()
            normalized_metadata = normalize_crs_set_metadata(metadata)
            if clean_name in self.crs_sets and normalized_metadata:
                self.crs_set_metadata[clean_name] = normalized_metadata

        self.current_set_name = None
        self.loading = False

        self.setWindowTitle('CRS Magic finder — налаштування')
        self.resize(1220, 560)

        self.sets_list = QListWidget()
        self.sets_list.setAlternatingRowColors(True)
        self.sets_list.setMinimumWidth(220)
        self.sets_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.sets_list.currentItemChanged.connect(self.change_set)
        self.sets_list.itemChanged.connect(self.rename_set)
        self.sets_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sets_list.customContextMenuRequested.connect(self.open_sets_context_menu)

        self.add_button = QToolButton()
        self.add_button.setIcon(qgis_icon(
            ['mActionAdd.svg', 'symbologyAdd.svg', 'mIconAdd.svg'],
            QStyle.SP_DialogApplyButton
        ))
        self.add_button.setToolTip('Додати набір')
        self.add_button.clicked.connect(self.add_set)

        self.delete_button = QToolButton()
        self.delete_button.setIcon(qgis_icon(
            ['mActionRemove.svg', 'symbologyRemove.svg', 'mIconRemove.svg'],
            QStyle.SP_DialogDiscardButton
        ))
        self.delete_button.setToolTip('Видалити набір')
        self.delete_button.clicked.connect(self.delete_set)

        self.import_button = QToolButton()
        self.import_button.setIcon(qgis_icon(
            ['mActionFileOpen.svg', 'mActionOpen.svg'],
            QStyle.SP_DialogOpenButton
        ))
        self.import_button.setToolTip('Імпортувати набори СК із JSON')
        self.import_button.clicked.connect(self.import_sets)

        self.export_button = QToolButton()
        self.export_button.setIcon(qgis_icon(
            ['mActionFileSave.svg', 'mActionSave.svg'],
            QStyle.SP_DialogSaveButton
        ))
        self.export_button.setToolTip(
            'Експортувати вибрані набори СК у JSON (Ctrl або Shift для вибору кількох)'
        )
        self.export_button.clicked.connect(self.export_sets)
        self.sets_list.itemSelectionChanged.connect(self.update_export_button)

        self.edit_button = QToolButton()
        self.edit_button.setIcon(qgis_icon(
            ['mActionOptions.svg', 'mIconSettings.svg', 'propertyicons/settings.svg'],
            QStyle.SP_FileDialogDetailedView
        ))
        self.edit_button.setToolTip('Редагувати вибраний набір')
        self.edit_button.clicked.connect(self.open_set_editor)

        set_buttons_layout = QHBoxLayout()
        set_buttons_layout.addWidget(self.add_button)
        set_buttons_layout.addWidget(self.delete_button)
        set_buttons_layout.addWidget(self.import_button)
        set_buttons_layout.addWidget(self.export_button)
        set_buttons_layout.addStretch()
        set_buttons_layout.addWidget(self.edit_button)

        self.fast_mode_checkbox = QCheckBox(
            'Швидкий режим (без PROJ-рядків)'
        )
        self.fast_mode_checkbox.setChecked(bool(fast_mode))
        self.fast_mode_checkbox.setToolTip(
            'Використовує визначення СК безпосередньо з бази QGIS без '
            'попереднього перетворення в PROJ-рядки. Може пришвидшити підготовку, '
            'але на старих версіях QGIS інколи дає некоректні результати.'
        )

        self.group_search_checkbox = QCheckBox('Груповий підбір для кількох шарів')
        self.group_search_checkbox.setChecked(bool(group_search))
        self.group_search_checkbox.setToolTip(
            'Об’єднує вибрані шари в групи за взаємним перетином їхніх екстентів. '
            'Пошук починається з найбільшого екстенту серед ще не згрупованих шарів. '
            'Для шарів однієї групи перевірка виконується спільно, що може прискорити '
            'роботу з кількома просторово пов’язаними шарами.'
        )

        self.disable_fallback_handler_checkbox = QCheckBox(
            'Виявляти запасні перетворення (Fallback)'
        )
        self.disable_fallback_handler_checkbox.setChecked(
            bool(disable_fallback_handler)
        )
        self.disable_fallback_handler_checkbox.setToolTip(
            'Вимикає стандартний обробник QGIS, щоб плагін міг виявляти й позначати '
            'запасні операції. Самі запасні перетворення цей параметр не забороняє.'
        )

        self.allow_fallback_checkbox = QCheckBox('Дозволяти запасні перетворення (Fallback)')
        self.allow_fallback_checkbox.setChecked(bool(allow_fallback))
        self.allow_fallback_checkbox.setToolTip(
            'Якщо рекомендована операція перетворення координат недоступна або не може '
            'бути виконана, PROJ може використати іншу придатну операцію. '
            'Результат може бути менш точним; використання запасної операції буде позначено в таблиці.'
        )

        self.allow_ballpark_checkbox = QCheckBox(
            'Дозволяти приблизні перетворення (Ballpark)'
        )
        self.allow_ballpark_checkbox.setChecked(bool(allow_ballpark))
        self.allow_ballpark_checkbox.setToolTip(
            'Дозволяє PROJ використовувати приблизне перетворення, коли немає точної '
            'операції або необхідних параметрів і координатних сіток. Геодезична точність '
            'не гарантується. Має пріоритет над забороною запасних перетворень.'
        )

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel('Набори'))
        left_layout.addWidget(self.sets_list)
        left_layout.addLayout(set_buttons_layout)
        left_layout.addWidget(self.fast_mode_checkbox)
        left_layout.addWidget(self.group_search_checkbox)
        left_layout.addWidget(self.disable_fallback_handler_checkbox)
        left_layout.addWidget(self.allow_fallback_checkbox)
        left_layout.addWidget(self.allow_ballpark_checkbox)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        self.crs_list = QListWidget()
        self.crs_list.setAlternatingRowColors(True)
        self.crs_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.crs_list_label = QLabel('СК у вибраному наборі: 0')

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.crs_list_label)
        right_layout.addWidget(self.crs_list)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        right_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.metadata_widget = CRSSetMetadataWidget(self)
        metadata_container_layout = QVBoxLayout()
        metadata_container_layout.addWidget(QLabel('Параметри вибраного набору'))
        metadata_container_layout.addWidget(self.metadata_widget, 1)
        metadata_widget = QWidget()
        metadata_widget.setLayout(metadata_container_layout)
        metadata_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        content_layout = QHBoxLayout()
        content_layout.addWidget(left_widget)
        content_layout.addWidget(right_widget, 1)
        content_layout.addWidget(metadata_widget, 1)

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

    def set_item_editable(self, item):
        item.setFlags(item.flags() | Qt.ItemIsEditable)

    def add_set_item(self, name):
        item = QListWidgetItem(name)
        item.setData(Qt.UserRole, name)
        self.set_item_editable(item)
        self.sets_list.addItem(item)
        return item

    def open_sets_context_menu(self, position):
        current_item = self.sets_list.itemAt(position)
        if current_item:
            if not current_item.isSelected():
                self.sets_list.clearSelection()
                current_item.setSelected(True)
            self.sets_list.setCurrentItem(current_item)

        has_current = self.sets_list.currentItem() is not None
        has_selection = bool(self.sets_list.selectedItems())

        menu = QMenu(self)
        add_action = menu.addAction(qgis_icon(
            ['mActionAdd.svg', 'symbologyAdd.svg', 'mIconAdd.svg'],
            QStyle.SP_DialogApplyButton
        ), 'Додати набір')
        delete_action = menu.addAction(qgis_icon(
            ['mActionRemove.svg', 'symbologyRemove.svg', 'mIconRemove.svg'],
            QStyle.SP_DialogDiscardButton
        ), 'Видалити')
        rename_action = menu.addAction('Перейменувати')
        configure_action = menu.addAction(qgis_icon(
            ['mActionOptions.svg', 'mIconSettings.svg', 'propertyicons/settings.svg'],
            QStyle.SP_FileDialogDetailedView
        ), 'Редагувати')
        menu.addSeparator()
        save_action = menu.addAction(qgis_icon(
            ['mActionFileSave.svg', 'mActionSave.svg'],
            QStyle.SP_DialogSaveButton
        ), 'Експортувати вибрані набори…')
        load_action = menu.addAction(qgis_icon(
            ['mActionFileOpen.svg', 'mActionOpen.svg'],
            QStyle.SP_DialogOpenButton
        ), 'Імпортувати набори…')

        delete_action.setEnabled(has_current)
        rename_action.setEnabled(has_current)
        configure_action.setEnabled(has_current)
        save_action.setEnabled(has_selection)

        selected_action = menu.exec_(self.sets_list.mapToGlobal(position))
        if selected_action == add_action:
            self.add_set()
        elif selected_action == delete_action:
            self.delete_set()
        elif selected_action == rename_action:
            self.rename_current_set()
        elif selected_action == configure_action:
            self.open_set_editor()
        elif selected_action == save_action:
            self.export_sets()
        elif selected_action == load_action:
            self.import_sets()

    def load_sets_list(self):
        self.loading = True
        self.sets_list.clear()
        for name in sorted(self.crs_sets.keys()):
            self.add_set_item(name)
        self.loading = False

    def change_set(self, current, previous):
        if self.loading:
            return

        if current:
            self.current_set_name = current.data(Qt.UserRole) or current.text()
        else:
            self.current_set_name = None

        self.load_current_crs_list()

    def rename_set(self, item):
        if self.loading or not item:
            return

        old_name = item.data(Qt.UserRole)
        new_name = item.text().strip()

        if not old_name:
            item.setData(Qt.UserRole, new_name)
            return

        if not new_name:
            QMessageBox.warning(self, 'Набір СК', 'Вкажіть назву набору.')
            self.revert_item_name(item, old_name)
            return

        if new_name != old_name and new_name in self.crs_sets:
            QMessageBox.warning(self, 'Набір СК', 'Набір з такою назвою вже існує.')
            self.revert_item_name(item, old_name)
            return

        if new_name == old_name:
            return

        self.crs_sets[new_name] = self.crs_sets.pop(old_name, [])
        if old_name in self.crs_set_metadata:
            self.crs_set_metadata[new_name] = self.crs_set_metadata.pop(old_name)
        item.setData(Qt.UserRole, new_name)
        self.current_set_name = new_name
        self.load_current_crs_list()

    def revert_item_name(self, item, name):
        self.loading = True
        item.setText(name)
        self.loading = False

    def add_set(self):
        name = self.unique_set_name('Новий набір')
        self.crs_sets[name] = []

        self.loading = True
        item = self.add_set_item(name)
        self.loading = False

        self.sets_list.setCurrentItem(item)
        self.sets_list.editItem(item)

    def rename_current_set(self):
        current = self.sets_list.currentItem()
        if current:
            self.sets_list.editItem(current)

    def delete_set(self):
        current = self.sets_list.currentItem()
        if not current:
            return

        set_name = current.data(Qt.UserRole) or current.text()
        answer = QMessageBox.question(
            self,
            'Видалити набір?',
            f"Видалити набір «{set_name}»?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        row = self.sets_list.row(current)
        self.crs_sets.pop(set_name, None)
        self.crs_set_metadata.pop(set_name, None)

        self.loading = True
        self.sets_list.takeItem(row)
        self.loading = False

        if self.sets_list.count():
            self.sets_list.setCurrentRow(min(row, self.sets_list.count() - 1))
        else:
            self.current_set_name = None
            self.load_current_crs_list()

    def update_export_button(self):
        self.export_button.setEnabled(bool(self.sets_list.selectedItems()))

    def export_sets(self):
        selected_names = []
        for item in self.sets_list.selectedItems():
            name = item.data(Qt.UserRole) or item.text()
            if name not in selected_names:
                selected_names.append(name)

        if not selected_names:
            QMessageBox.warning(
                self,
                'Експорт наборів СК',
                'Виберіть один або кілька наборів СК для експорту.'
            )
            return

        export_sets = {
            name: self.crs_sets[name]
            for name in selected_names
            if name in self.crs_sets and self.crs_sets[name]
        }
        if not export_sets:
            QMessageBox.warning(
                self,
                'Експорт наборів СК',
                'У вибраних наборах немає жодної СК.'
            )
            return

        suggested_file_name = 'crs_sets.json'
        if len(selected_names) == 1:
            safe_set_name = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]',
                '_',
                selected_names[0]
            ).strip().rstrip('. ')
            reserved_names = {
                'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{number}' for number in range(1, 10)),
                *(f'LPT{number}' for number in range(1, 10)),
            }
            if safe_set_name.upper() in reserved_names:
                safe_set_name = f'_{safe_set_name}'
            if safe_set_name:
                suggested_file_name = safe_set_name
                if not suggested_file_name.lower().endswith('.json'):
                    suggested_file_name = f'{suggested_file_name}.json'

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            'Експортувати набори СК',
            suggested_file_name,
            'JSON (*.json)'
        )
        if not file_name:
            return
        if not file_name.lower().endswith('.json'):
            file_name = f'{file_name}.json'

        export_metadata = {
            name: self.crs_set_metadata[name]
            for name in export_sets
            if name in self.crs_set_metadata
        }
        data = crs_sets_to_json_data(export_sets, export_metadata)
        try:
            with open(file_name, 'w', encoding='utf-8') as export_file:
                json.dump(data, export_file, ensure_ascii=False, indent=2)
                export_file.write('\n')
        except OSError as error:
            QMessageBox.critical(
                self,
                'Експорт наборів СК',
                f'Не вдалося зберегти файл:\n{error}'
            )
            return

        skipped_empty = len(selected_names) - len(export_sets)
        message = f'Кількість експортованих наборів: {len(export_sets)}.'
        if skipped_empty:
            message += f' Пропущено порожніх наборів: {skipped_empty}.'
        QMessageBox.information(self, 'Експорт наборів СК', message)

    def import_sets(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            'Імпорт наборів СК',
            '',
            'JSON (*.json);;Усі файли (*)'
        )
        if not file_name:
            return

        try:
            with open(file_name, 'r', encoding='utf-8-sig') as import_file:
                data = json.load(import_file)
            imported_sets, imported_metadata, skipped_names = (
                crs_sets_bundle_from_json_data(data)
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            QMessageBox.critical(
                self,
                'Імпорт наборів СК',
                f'Не вдалося імпортувати файл:\n{error}'
            )
            return

        if not imported_sets:
            QMessageBox.warning(
                self,
                'Імпорт наборів СК',
                'У файлі немає придатних для імпорту непорожніх наборів СК.'
            )
            return

        conflicts = sorted(
            name for name in imported_sets
            if name in self.crs_sets and self.crs_sets[name]
        )
        overwrite_conflicts = True
        if conflicts:
            conflict_names = '\n'.join(f'• {name}' for name in conflicts)
            answer = QMessageBox.question(
                self,
                'Однакові назви наборів',
                'Такі набори вже існують:\n'
                f'{conflict_names}\n\n'
                'Замінити їх імпортованими?\n'
                '«Ні» — залишити наявні та імпортувати лише нові.',
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Cancel
            )
            if answer == QMessageBox.Cancel:
                return
            overwrite_conflicts = answer == QMessageBox.Yes

        if self.crs_sets and not any(self.crs_sets.values()):
            self.crs_sets.clear()
            self.crs_set_metadata.clear()

        applied_sets = {}
        skipped_conflicts = 0
        for name, codes in imported_sets.items():
            if name in conflicts and not overwrite_conflicts:
                skipped_conflicts += 1
                continue
            self.crs_sets[name] = codes
            metadata = normalize_crs_set_metadata(imported_metadata.get(name, {}))
            if metadata:
                self.crs_set_metadata[name] = metadata
            else:
                self.crs_set_metadata.pop(name, None)
            applied_sets[name] = codes

        if not applied_sets:
            QMessageBox.information(
                self,
                'Імпорт наборів СК',
                'Нових наборів не імпортовано: усі однойменні набори залишено без змін.'
            )
            return

        self.load_sets_list()
        selected_name = next(iter(applied_sets))
        for row in range(self.sets_list.count()):
            item = self.sets_list.item(row)
            if item.data(Qt.UserRole) == selected_name:
                self.sets_list.setCurrentItem(item)
                break

        imported_codes = sum(len(codes) for codes in applied_sets.values())
        message = (
            f'Кількість імпортованих наборів: {len(applied_sets)}. '
            f'Кількість імпортованих СК: {imported_codes}.'
        )
        if skipped_conflicts:
            message += f' Однойменних наборів пропущено: {skipped_conflicts}.'
        if skipped_names:
            message += f' Некоректних або порожніх наборів пропущено: {len(skipped_names)}.'
        QMessageBox.information(self, 'Імпорт наборів СК', message)

    def load_current_crs_list(self):
        self.crs_list.clear()
        codes = self.crs_sets.get(self.current_set_name, [])

        for code in codes:
            item = QListWidgetItem(crs_display_label(code))
            item.setData(CRS_CODE_ROLE, code)
            item.setToolTip(code)
            self.crs_list.addItem(item)

        self.crs_list_label.setText(f'СК у вибраному наборі: {len(codes)}')
        self.edit_button.setEnabled(self.current_set_name is not None)
        self.metadata_widget.set_metadata(
            self.crs_set_metadata.get(self.current_set_name, {})
        )

    def open_set_editor(self):
        if not self.current_set_name:
            return

        dialog = CRSSetEditorDialog(
            self.current_set_name,
            self.crs_sets.get(self.current_set_name, []),
            metadata=self.crs_set_metadata.get(self.current_set_name, {}),
            source_canvas=self.source_map_canvas,
            parent=self,
        )

        if not dialog.exec_():
            return

        self.crs_sets[self.current_set_name] = dialog.result_codes()
        metadata = dialog.result_metadata()
        if metadata:
            self.crs_set_metadata[self.current_set_name] = metadata
        else:
            self.crs_set_metadata.pop(self.current_set_name, None)
        self.load_current_crs_list()

    def validate_sets(self):
        if not self.crs_sets:
            QMessageBox.warning(self, 'Набір СК', 'Додайте хоча б один набір СК.')
            return False

        for name, codes in self.crs_sets.items():
            if not str(name).strip():
                QMessageBox.warning(self, 'Набір СК', 'Задайте назву для кожного набору.')
                return False
            if not codes:
                QMessageBox.warning(self, 'Набір СК', f"Додайте хоча б одну СК до набору «{name}».")
                return False

        return True

    def result_sets(self):
        return {
            name: codes
            for name, codes in self.crs_sets.items()
            if name.strip() and codes
        }

    def result_metadata(self):
        return {
            name: metadata
            for name, metadata in self.crs_set_metadata.items()
            if name in self.crs_sets and normalize_crs_set_metadata(metadata)
        }

    def allow_fallback(self):
        return self.allow_fallback_checkbox.isChecked()

    def allow_ballpark(self):
        return self.allow_ballpark_checkbox.isChecked()

    def fast_mode(self):
        return self.fast_mode_checkbox.isChecked()

    def group_search(self):
        return self.group_search_checkbox.isChecked()

    def disable_fallback_handler(self):
        return self.disable_fallback_handler_checkbox.isChecked()

    def accept(self):
        if not self.validate_sets():
            return
        super().accept()
