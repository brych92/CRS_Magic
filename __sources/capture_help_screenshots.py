"""Create rough help screenshots from the current plugin widgets.

Run from a QGIS Python environment. The generated PNG files are intentionally
kept simple so they can be replaced by polished release screenshots later.
"""

import json
import sys
from pathlib import Path

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QWidget


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
application = QgsApplication([], False)
application.initQgis()

layer = QgsVectorLayer('Polygon?crs=EPSG:3857', 'Топографічний план', 'memory')
iface = DummyIface(layer)
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
total_crs = 12869
results.update_stats(total_crs, processed_crs, 4150, 18, 32, 3)
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
    crs_set_metadata=initial_metadata,
)
for row in range(settings.sets_list.count()):
    if settings.sets_list.item(row).text() == 'Ukraine - UCS/CS63':
        settings.sets_list.setCurrentRow(row)
        break
save_widget(settings, 'settings-window.png')

plugin = CRS_Magic.__new__(CRS_Magic)
plugin.crs_menu = QMenu()
plugin.action_reference = QAction('CRS Magic finder')
plugin.crs_sets = {'Українські': ['EPSG:5561']}
plugin.active_crs_set = ALL_CRS_SET_KEY
plugin.fast_mode = False
plugin.group_search = False
plugin.disable_fallback_handler = True
plugin.allow_fallback = True
plugin.allow_ballpark = False
plugin.rebuild_crs_menu()
assert any(action.text() == 'Довідка' for action in plugin.crs_menu.actions())

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
