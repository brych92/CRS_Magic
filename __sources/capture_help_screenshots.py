"""Create rough help screenshots from the current plugin widgets.

Run from a QGIS Python environment. The generated PNG files are intentionally
kept simple so they can be replaced by polished release screenshots later.
"""

import json
import sys
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsPointXY,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QWidget
from qgis.gui import QgsMessageBar


PLUGIN_DIRECTORY = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PLUGIN_DIRECTORY.parent
OUTPUT_DIRECTORY = PLUGIN_DIRECTORY / 'help' / 'images'


class DummyLayerTreeView:
    def selectedLayersRecursive(self):
        return []


class DummyIface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self, active_layer):
        super().__init__()
        self._active_layer = active_layer
        self._layer_tree_view = DummyLayerTreeView()

    def activeLayer(self):
        return self._active_layer

    def layerTreeView(self):
        return self._layer_tree_view


class DummyHelpMenuIface:
    def __init__(self):
        self.window = QWidget()
        self.help_menu = QMenu(self.window)

    def mainWindow(self):
        return self.window

    def pluginHelpMenu(self):
        return self.help_menu


class DummyMessageBarIface:
    def __init__(self, bar):
        self.bar = bar

    def messageBar(self):
        return self.bar


class DummySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def contains(self, key):
        return key in self.values

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        pass


def save_widget(widget, file_name):
    widget.move(-10000, -10000)
    widget.show()
    application.processEvents()
    widget.grab().save(str(OUTPUT_DIRECTORY / file_name), 'PNG')
    widget.close()
    application.processEvents()


if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from crs_magic_finder_dev.plugin_window import CRSResultsDialog
from crs_magic_finder_dev.find_crs import (
    CRS_FILTER_CACHE_DIRECTORY,
    CRS_FILTER_STATUS,
    _ALL_CRS_MEMORY_CACHE,
    _ALL_CRS_MEMORY_CACHE_LOCK,
    findCrs,
)
from crs_magic_finder_dev.settings_window import (
    CRSSetSettingsDialog,
    crs_sets_bundle_from_json_data,
)
from crs_magic_finder_dev.code import (
    ACTIVE_CRS_SET_SETTINGS_KEY,
    ALL_CRS_SET_KEY,
    DEFAULT_ACTIVE_CRS_SET,
    CRS_Magic,
)


OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
application = QgsApplication([], True)
application.initQgis()

layer = QgsVectorLayer('Polygon?crs=EPSG:3857', 'Топографічний план', 'memory')
iface = DummyIface(layer)
results = CRSResultsDialog([layer], iface)
results.set_progress(12)
results.set_phase_status(CRS_FILTER_STATUS)
results.set_phase_progress(47.6)
results.update_stats(9892, 0, 0, 0, 0, 0)
assert results.status_label.text() == (
    f'{CRS_FILTER_STATUS} 48%.'
)
assert results.status_progress.value() == 48
save_widget(results, 'cache-stage.png')

results = CRSResultsDialog([layer], iface)
for code, distance, note in (
    ('EPSG:5561', 318, ''),
    ('EPSG:7826', 1240, 'Fallback'),
    ('EPSG:28406', 4870, 'Ballpark'),
):
    crs = QgsCoordinateReferenceSystem(code)
    results.add_result(
        layer.id(),
        layer.name(),
        code,
        crs.description(),
        distance,
        crs,
        note,
    )
results.flush_pending_results()
processed_crs = 4200
total_crs = 9892
results.update_stats(total_crs, processed_crs, 4150, 18, 32, 3)
assert results.status_label.text().startswith('СК: 9892 | Перевірено: 4200')
results.set_progress(5 + 94 * processed_crs / total_crs)
save_widget(results, 'results-window.png')

if '--results-only' in sys.argv:
    application.exitQgis()
    raise SystemExit(0)

with (PLUGIN_DIRECTORY / 'initial_crs_sets' / 'default_crs_sets.json').open(
    encoding='utf-8-sig'
) as source_file:
    initial_data = json.load(source_file)
initial_sets, initial_metadata, _ = crs_sets_bundle_from_json_data(initial_data)

settings = CRSSetSettingsDialog(
    initial_sets,
    fast_mode=False,
    group_search=True,
    disable_fallback_handler=True,
    allow_fallback=True,
    allow_ballpark=False,
    filter_by_crs_bounds=True,
    crs_set_metadata=initial_metadata,
    reset_cache_callback=lambda: (True, 'Кеш скинуто'),
)
for row in range(settings.sets_list.count()):
    if settings.sets_list.item(row).text() == 'Ukraine - UCS/CS63':
        settings.sets_list.setCurrentRow(row)
        break
save_widget(settings, 'settings-window.png')
assert settings.filter_by_crs_bounds()
assert settings.reset_cache_button.text() == 'Скинути кеш шейдерів'
assert settings.reset_cache_button.isEnabled()
assert settings.reset_cache_button.toolTip()

transform_context = QgsCoordinateTransformContext()
wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
web_mercator = QgsCoordinateReferenceSystem('EPSG:3857')
click_point = QgsCoordinateTransform(
    wgs84,
    web_mercator,
    transform_context,
).transform(QgsPointXY(31, 49))
filter_task = findCrs(
    'Перевірка фільтрів СК',
    [],
    click_point,
    web_mercator,
    filter_by_crs_bounds=True,
    transform_context=transform_context,
)
filter_task.initialize_transform_tools()
assert filter_task.crs_is_supported_horizontal_2d(
    QgsCoordinateReferenceSystem('EPSG:3857')
)
assert not filter_task.crs_is_supported_horizontal_2d(
    QgsCoordinateReferenceSystem('EPSG:4979')
)
assert not filter_task.crs_is_supported_horizontal_2d(
    QgsCoordinateReferenceSystem('EPSG:4978')
)
assert not filter_task.crs_is_earth(
    QgsCoordinateReferenceSystem('IAU_2015:49900')
)
deprecated_crs = QgsCoordinateReferenceSystem('EPSG:3785')
assert deprecated_crs.isValid()
assert filter_task.crs_is_supported_horizontal_2d(deprecated_crs)
assert filter_task.crs_is_earth(deprecated_crs)
ukrainian_crs = QgsCoordinateReferenceSystem('EPSG:5564')
north_american_crs = QgsCoordinateReferenceSystem('EPSG:26910')
assert filter_task.crs_bounds_intersect_search_area(ukrainian_crs)
assert not filter_task.crs_bounds_intersect_search_area(north_american_crs)
assert filter_task.transformed_point_is_within_crs_bounds(
    ukrainian_crs,
    click_point,
)
assert not filter_task.transformed_point_is_within_crs_bounds(
    north_american_crs,
    click_point,
)

tiny_task = findCrs(
    'Перевірка інтеграції каталогу СК',
    [],
    click_point,
    web_mercator,
    transform_context=transform_context,
)
tiny_task.initialize_transform_tools()
tiny_task.total_result = {
    'layer': {'LayerName': 'Тестовий шар', 'Checked': True},
}


def prepare_tiny_catalog(progress):
    tiny_task.catalog_crs_qty = 2
    tiny_task.unsupported_crs_type_qty = 1
    tiny_task.catalog_cache_source = 'memory'
    return [(3857, QgsCoordinateReferenceSystem('EPSG:3857'))]


tiny_task.prepare_all_crs_candidates = prepare_tiny_catalog
tiny_stats = []
tiny_task.statsChanged.connect(lambda *values: tiny_stats.append(values))
assert tiny_task.range_distances({'layer': click_point}, click_point)
assert tiny_task.total_crs_to_check == 1
assert tiny_task.processed_crs_qty == 1
assert tiny_task.matched_crs_qty == 1
assert tiny_stats[-1][:2] == (1, 1)

plugin = CRS_Magic.__new__(CRS_Magic)
plugin.crs_menu = QMenu()
plugin.action_reference = QAction('CRS Magic finder')
plugin.crs_sets = {'Українські': ['EPSG:5561']}
plugin.crs_set_metadata = {}
plugin.active_crs_set = ALL_CRS_SET_KEY
plugin.fast_mode = False
plugin.group_search = False
plugin.disable_fallback_handler = True
plugin.allow_fallback = True
plugin.allow_ballpark = False
plugin.filter_by_crs_bounds = False
plugin.rebuild_crs_menu()
assert any(action.text() == 'Довідка' for action in plugin.crs_menu.actions())


def assert_menu_tooltips(menu):
    assert menu.toolTipsVisible()
    for action in menu.actions():
        if action.isSeparator():
            continue
        assert action.toolTip(), action.text()
        submenu = action.menu()
        if submenu is not None:
            assert_menu_tooltips(submenu)


assert_menu_tooltips(plugin.crs_menu)
assert not any(
    action.text() == 'Скинути кеш шейдерів'
    for action in plugin.crs_menu.actions()
)

cache_directory = Path(QgsApplication.qgisSettingsDirPath()).joinpath(
    *CRS_FILTER_CACHE_DIRECTORY.split('/')
)
cache_directory.mkdir(parents=True, exist_ok=True)
cache_file = cache_directory / 'test-cache.json'
unrelated_file = cache_directory / 'keep.txt'
cache_file.write_text('{}', encoding='utf-8')
unrelated_file.write_text('keep', encoding='utf-8')
with _ALL_CRS_MEMORY_CACHE_LOCK:
    _ALL_CRS_MEMORY_CACHE['test'] = {'srs_ids': [1]}
cache_plugin = CRS_Magic.__new__(CRS_Magic)
cache_plugin.results_dialog = None
cache_success, cache_message = cache_plugin.reset_crs_filter_cache()
assert cache_success
assert 'Кеш шейдерів скинуто' in cache_message
assert not cache_file.exists()
assert unrelated_file.exists()
with _ALL_CRS_MEMORY_CACHE_LOCK:
    assert not _ALL_CRS_MEMORY_CACHE

message_iface = DummyMessageBarIface(QgsMessageBar())
message_plugin = CRS_Magic.__new__(CRS_Magic)
message_plugin.iface = message_iface
message_plugin.transform_message_interceptor_connected = False
message_plugin.transform_message_interceptor_active = False
message_plugin.transform_message_interceptor_generation = 0
message_plugin.start_transform_message_interception()
message_iface.bar.pushWarning(
    'Неможливо використовувати переважне перетворення між '
    'ESRI:103991 та EPSG:3857',
    '',
)
message_iface.bar.pushWarning('Інше попередження QGIS', '')
for _ in range(3):
    application.processEvents()
assert not any(
    message_plugin.is_preferred_transform_message(item)
    for item in message_iface.bar.items()
)
assert any(
    'Інше попередження QGIS' in message_plugin.message_bar_item_text(item)
    for item in message_iface.bar.items()
)
message_plugin.stop_transform_message_interception()
message_iface.bar.pushWarning(
    'Cannot use preferred transform between EPSG:6923 and EPSG:3857',
    '',
)
application.processEvents()
assert any(
    message_plugin.is_preferred_transform_message(item)
    for item in message_iface.bar.items()
)
message_plugin.disconnect_transform_message_interceptor()

help_iface = DummyHelpMenuIface()
help_plugin = CRS_Magic.__new__(CRS_Magic)
help_plugin.iface = help_iface
help_plugin.plugin_help_menu = None
help_plugin.plugin_help_action = None
help_plugin.SPT = None
help_plugin.register_plugin_help_action(QIcon())
assert [action.text() for action in help_iface.help_menu.actions()] == [
    'CRS Magic finder'
]
help_plugin.unload()
assert not help_iface.help_menu.actions()

default_plugin = CRS_Magic.__new__(CRS_Magic)
default_plugin.settings = DummySettings()
default_plugin.crs_sets = {DEFAULT_ACTIVE_CRS_SET: ['EPSG:5561']}
assert default_plugin.load_active_crs_set() == DEFAULT_ACTIVE_CRS_SET
assert (
    default_plugin.settings.values[ACTIVE_CRS_SET_SETTINGS_KEY]
    == DEFAULT_ACTIVE_CRS_SET
)

saved_plugin = CRS_Magic.__new__(CRS_Magic)
saved_plugin.settings = DummySettings({ACTIVE_CRS_SET_SETTINGS_KEY: ALL_CRS_SET_KEY})
saved_plugin.crs_sets = {DEFAULT_ACTIVE_CRS_SET: ['EPSG:5561']}
assert saved_plugin.load_active_crs_set() == ALL_CRS_SET_KEY

fallback_plugin = CRS_Magic.__new__(CRS_Magic)
fallback_plugin.settings = DummySettings()
fallback_plugin.crs_sets = {'Another set': ['EPSG:4326']}
assert fallback_plugin.load_active_crs_set() == ALL_CRS_SET_KEY

application.exitQgis()
